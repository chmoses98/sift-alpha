"""READ-ONLY: game-level NBA market families (moneyline, spread, total, team total) evaluated from the producer's FROZEN team-score
distributions (``sift.game_forecast.v1``: one pmf of final points per team + the producer's own correlation ``rho``).

These are DERIVED forecasts. The producer archived score distributions, not market probabilities. Alpha therefore applies ONE fixed,
versioned transformation (``alpha-derive:gauss-copula-notie-v1``): a Gaussian copula with the producer's ``rho`` joins the two frozen
marginals (iterative proportional fitting makes both marginals exact), conditioned on no tie (an NBA game cannot end tied). The
version suffix is part of ``model_version`` so every derived result is attributable to this choice, not to the producer's model.
The producer states its game-market probabilities are approximate; so are these.

Outcomes come from final team scores (``team_outcomes``). Every derived outcome is cross-checked against the producer's separately
implemented settle engine (``settlements``); a disagreement adds a conflicting outcome row so the STANDARD blocks it. Ticker
identity is checked against the independent game record. Freeze evidence: the producer's own ``generated_utc`` /``archived_utc``
only (no hash-chain attestation exists for this archive), so these rows are classed BACKTEST, never PROSPECTIVE.
Cells are keyed on the SEMANTIC model version (the part before ``+``: semver build metadata is not a version change); the full build
string is kept in ``meta.model_build`` and the number of distinct builds is reported.
Quotes: archived ``market_snapshots`` (two-sided only). Kalshi's official result is not retained in the archive.
"""
from __future__ import annotations

import glob
import gzip
import json
import math
import os
import re
from collections import Counter, defaultdict
from statistics import NormalDist
from typing import Optional

import numpy as np

from .nba_shadow import _cross, check_identity
from .schema import BACKTEST, LADDER_RUNG, MAIN, SCHEMA_VERSION

DERIVE_VERSION = "alpha-derive:gauss-copula-notie-v1"
SERIES_FAMILY = {"KXNBAGAME": "game_winner", "KXNBASPREAD": "game_spread", "KXNBATOTAL": "game_total", "KXNBATEAMTOTAL": "team_total"}
FAMILIES = tuple(SERIES_FAMILY.values())
_N = NormalDist()
_Z = np.linspace(-7.0, 7.0, 2801)               # quadrature nodes for the copula
_W = np.exp(-_Z ** 2 / 2) / math.sqrt(2 * math.pi) * (_Z[1] - _Z[0])


def _ndtr(x):
    """Vectorised standard-normal CDF (Abramowitz-Stegun 7.1.26 erf, |err| < 1.5e-7). numpy-only: the repo carries no scipy."""
    x = np.asarray(x, float) / math.sqrt(2.0)
    s = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-a * a)
    return 0.5 * (1.0 + s * y)


def joint_pmf(p_home, p_away, rho: float, *, iters: int = 60) -> np.ndarray:
    """Joint pmf J[h, a] with the given marginals (exact after IPF) and Gaussian-copula dependence ``rho`` (|rho| < 1)."""
    p1, p2 = np.asarray(p_home, float), np.asarray(p_away, float)
    p1, p2 = p1 / p1.sum(), p2 / p2.sum()
    if not -1 < rho < 1:
        raise ValueError("rho must be in (-1, 1)")
    eps = 1e-12
    zb1 = np.array([_N.inv_cdf(min(max(c, eps), 1 - eps)) for c in np.cumsum(p1)[:-1]] + [np.inf])
    zb2 = np.array([_N.inv_cdf(min(max(c, eps), 1 - eps)) for c in np.cumsum(p2)[:-1]] + [np.inf])
    s = math.sqrt(1 - rho * rho)
    with np.errstate(invalid="ignore"):
        C = _ndtr((zb2[None, :] - rho * _Z[:, None]) / s)           # P(A <= a | z)
    C[:, -1] = 1.0
    PA = np.diff(C, axis=1, prepend=0.0)                            # P(A = a | z)
    bins = np.searchsorted(zb1, _Z)                                 # home score bin of each node
    J = np.zeros((len(p1), len(p2)))
    np.add.at(J, bins.clip(0, len(p1) - 1), _W[:, None] * PA)
    J = np.maximum(J, 1e-300)
    for _ in range(iters):                                          # IPF: enforce BOTH marginals exactly
        J *= (p1 / J.sum(1))[:, None]
        J *= (p2 / J.sum(0))[None, :]
    return J / J.sum()


def market_probability(series: str, team: Optional[str], n: Optional[int], J: np.ndarray, lo_h: int, lo_a: int, home: str, away: str) -> float:
    """P(YES) for one market given the joint of final points. Conditions on no tie. Integer strike N <=> floor_strike N-0.5, 'greater'."""
    H = lo_h + np.arange(J.shape[0])[:, None]
    A = lo_a + np.arange(J.shape[1])[None, :]
    keep = (H != A)
    Jn = J * keep
    Jn = Jn / Jn.sum()
    D, T = H - A, H + A
    if series == "KXNBAGAME":
        return float(Jn[(D > 0) if team == home else (D < 0)].sum())
    if series == "KXNBASPREAD":
        return float(Jn[(D >= n) if team == home else (-D >= n)].sum())
    if series == "KXNBATOTAL":
        return float(Jn[T >= n].sum())
    if series == "KXNBATEAMTOTAL":
        pts = H + 0 * A if team == home else A + 0 * H
        return float(Jn[pts >= n].sum())
    raise ValueError(series)


def market_outcome(series: str, team: Optional[str], n: Optional[int], pts: dict, home: str, away: str) -> int:
    """Realised YES/NO from FINAL points {team: pts} under exactly the semantics above."""
    h, a = pts[home], pts[away]
    if series == "KXNBAGAME":
        return int((h > a) if team == home else (a > h))
    if series == "KXNBASPREAD":
        return int((h - a >= n) if team == home else (a - h >= n))
    if series == "KXNBATOTAL":
        return int(h + a >= n)
    if series == "KXNBATEAMTOTAL":
        return int(pts[team] >= n)
    raise ValueError(series)


_REST = re.compile(r"^(?P<team>[A-Z]{3})?(?P<n>\d+)?$")


def parse_market(ticker: str):
    """-> (series, team|None, N|None) for the four supported series; None otherwise (unsupported shapes are counted by the caller)."""
    parts = ticker.split("-")
    if len(parts) < 3 or parts[0] not in SERIES_FAMILY:
        return None
    series, rest = parts[0], parts[2]
    m = _REST.match(rest)
    if not m or not (m["team"] or m["n"]):
        return None
    team, n = m["team"], (int(m["n"]) if m["n"] else None)
    if series == "KXNBAGAME" and (team is None or n is not None):
        return None
    if series in ("KXNBASPREAD", "KXNBATEAMTOTAL") and (team is None or n is None):
        return None
    if series == "KXNBATOTAL" and (team is not None or n is None):
        return None
    return series, team, n


def _read(root, pat):
    for f in sorted(glob.glob(os.path.join(root, pat))):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


def build(projection_root: str, classified: dict, *, settlements: Optional[dict] = None, game_identity: Optional[dict] = None) -> dict:
    """Derived BINARY forecast rows + outcomes + quotes for the four game-level families, for every in-window board ticker.
    ``classified`` is nba_universe.classify(...): supplies the ticker list per game (the eligible universe)."""
    info = Counter()
    by_game = defaultdict(list)
    for t, r in classified.items():
        if r["cls"] == "IN_WINDOW" and r["family"] in FAMILIES:
            pm = parse_market(t)
            if pm is None:
                info["unparseable_market_shape"] += 1
                continue
            by_game[r["game_id"]].append((t, pm))
    # final scores
    final, final_obs = {}, {}
    for r in _read(projection_root, "team_outcomes/nba/*/*.jsonl.gz"):
        if r.get("final") and r.get("pts") is not None:
            final.setdefault(r["game_id"], {})[r["team"]] = int(r["pts"])
            final_obs[r["game_id"]] = max(final_obs.get(r["game_id"], ""), r["observed_utc"])
    quotes = {}
    for r in _read(projection_root, "market_snapshots/nba/*/*.jsonl.gz"):
        t = r.get("ticker")
        if not t or not r.get("board_observed_utc") or r.get("series") not in SERIES_FAMILY:
            continue
        yb, ya = r.get("yes_bid"), r.get("yes_ask")
        quotes[(t, r["board_observed_utc"])] = dict(schema=SCHEMA_VERSION, market_id=t, observed_at=r["board_observed_utc"],
                                                     yes_bid=None if not yb else float(yb), yes_ask=None if not ya else float(ya),
                                                     source="producer_market_snapshot")
    forecasts, outcomes, done_out, xcheck = [], [], set(), Counter()
    joint_cache = {}
    for g in _read(projection_root, "game_forecasts/nba/*/*.jsonl.gz"):
        gid = g["game_id"]
        mk = by_game.get(gid)
        info["game_forecast_rows"] += 1
        if not mk:
            info["game_forecast_rows_without_board_markets"] += 1
            continue
        tm = {t["team"]: t for t in g["teams"]}
        home, away = g["home"], g["away"]
        if set(tm) != {home, away}:
            info["game_forecast_team_mismatch"] += 1
            continue
        key = g["game_forecast_id"]
        J = joint_pmf(tm[home]["probs"], tm[away]["probs"], float(g["rho"]))
        lo_h, lo_a = int(tm[home]["lo"]), int(tm[away]["lo"])
        written = g.get("archived_utc") or g["generated_utc"]
        start = g["game_start_utc"]
        frozen = g["generated_utc"] if written <= start else written
        for t, (series, team, n) in mk:
            p = market_probability(series, team, n, J, lo_h, lo_a, home, away)
            p = min(max(p, 1e-6), 1 - 1e-6)                        # a score-pmf tail can round to exactly 0/1; the grader needs (0,1)
            forecasts.append(dict(
                schema=SCHEMA_VERSION, forecast_id=f"{t}|{g['generated_utc']}|{g['model_id']}", sport="NBA", event_id=gid, group_id=gid,
                market_id=t, native_family=SERIES_FAMILY[series], model_id=g["model_id"],
                model_version=f"{g['model_version'].split('+')[0]}|{DERIVE_VERSION}", model_independence="sports_only", market_inputs_used=[],
                frozen_at=frozen, event_start=start, evidence_class=BACKTEST, scoring_type="BINARY", payload=dict(p_yes=p),
                line=n, line_role=LADDER_RUNG if series != "KXNBAGAME" else MAIN,
                meta=dict(derived=True, rho=g["rho"], archived_utc=written, freeze_attestation="producer_timestamps_only",
                          model_build=g["model_version"])))
            if t in done_out:
                continue
            done_out.add(t)
            sc = final.get(gid)
            ident = check_identity(t, (game_identity or {}).get(gid)) if game_identity is not None else "IDENTITY_NOT_CHECKED"
            info[f"identity[{ident}]"] += 1
            if sc is None or set(sc) != {home, away}:
                continue
            suffix = "#TICKER_IDENTITY_MISMATCH" if ident.startswith("MISMATCH") else ""
            y = market_outcome(series, team, n, sc, home, away)
            rows = [dict(schema=SCHEMA_VERSION, market_id=t, event_id=gid + suffix, source="sports", observed_at=final_obs[gid], state="final", value=y)]
            st = (settlements or {}).get(t)
            if st is not None:
                xcheck[_cross(rows, st)] += 1
                if st["outcome"] in ("YES", "NO") and (1 if st["outcome"] == "YES" else 0) != y:
                    rows.append(dict(rows[0], value=1 - y))
            outcomes.extend(rows)
    info.update({f"outcome_xcheck[{k}]": v for k, v in xcheck.items()})
    info["model_builds"] = len({f["meta"]["model_build"] for f in forecasts})
    info["model_versions_semantic"] = len({f["model_version"] for f in forecasts})
    info["derived_forecast_rows"] = len(forecasts)
    info["derived_markets"] = len({f["market_id"] for f in forecasts})
    return dict(forecasts=forecasts, outcomes=outcomes, quotes=list(quotes.values()), info=dict(info))
