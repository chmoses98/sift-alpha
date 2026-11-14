"""Kalshi OFFICIAL settlements as a SECOND, independent outcome source for the NHL adapter (RESEARCH_ONLY, read-only).

Reconciliation of sift-alpha PRs #66 and #68, which both added ``alpha_eval/nhl_archive.py``:

* ``alpha_eval.nhl_archive`` (from #66) stays THE adapter: forecast selection, git freeze attestation, board-replay quotes and
  outcomes derived from the official NHL API with two cross-checks (producer archive re-derivation, producer settle engine).
* this module carries what #68 added and #66 did not have: Kalshi's own ``result`` for every settled game-bound NHL market
  (``scripts/alpha_eval/fetch_kalshi_settled.py`` pages), an event-identity check of each Kalshi event ticker against the archived
  NHL schedule, and #68's secondary native-family slice with its pinned confirmation test. #68's forecast selection, quote
  extraction and universe reconciliation are NOT ported: #66's implementations of those are the single ones.

The cross-check is per market: official-API outcome (``source=sports``) vs Kalshi settlement (``source=market_settlement``).
An agreeing settlement row collapses in the grader (identical event/state/value); a disagreeing one makes the standard's own
conflict rule BLOCK the market. Nothing is resolved by choosing a side. Local files only; no network; nothing in a producer
repository is imported or modified.
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

from .schema import PROSPECTIVE, SCHEMA_VERSION

SPORT = "NHL"
# Kalshi series -> producer-vocabulary native family (game-bound series only; anything else is not a per-game market).
SERIES_FAMILY = {
    "KXNHLGAME": "game_winner", "KXNHLSPREAD": "game_spread", "KXNHLTOTAL": "game_total", "KXNHLTEAMTOTAL": "team_total",
    "KXNHL1P": "period_winner", "KXNHL2P": "period_winner", "KXNHL3P": "period_winner",
    "KXNHL1PSPREAD": "period_spread", "KXNHL2PSPREAD": "period_spread", "KXNHL3PSPREAD": "period_spread",
    "KXNHL1PTOTAL": "period_total", "KXNHL2PTOTAL": "period_total", "KXNHL3PTOTAL": "period_total",
    "KXNHLGOAL": "player_goals", "KXNHLPTS": "player_points", "KXNHLAST": "player_assists", "KXNHLSAVE": "goalie_saves",
    "KXNHLFIRSTGOAL": "first_goal", "KXNHLF10G": "game_early_goal", "KXNHLOT": "game_overtime",
    "KXNHL1PBTTS": "period_btts", "KXNHL2PBTTS": "period_btts", "KXNHL3PBTTS": "period_btts",
    "KXNHL1STTEAM": "first_team_to_score", "KXNHL2OT": "game_double_overtime", "KXNHL30COMEBACK": "game_comeback",
    "KXNHLANYGOAL": "player_anytime_goal", "KXNHLSAVES": "goalie_saves_alt", "KXNHLOVERTIME": "game_overtime_alt",
}
_EVT = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$")
_MON = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}
# Kalshi team codes that differ from NHL API abbreviations. Only entries observed in the data are listed; an unknown code
# simply fails to match (counted), it is never guessed.
KALSHI_TEAM_ALIAS = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA"}


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(root: str, sub: str):
    for f in sorted(glob.glob(os.path.join(root, sub, "dt=*", "*.jsonl.gz"))):
        rel = os.path.relpath(f, root)
        with gzip.open(f, "rt") as fh:
            for line in fh:
                if line.strip():
                    yield rel, json.loads(line)



# ----------------------------------------------------------------------------- inputs
def load_schedule(root: str) -> dict:
    """game_id -> latest schedule observation (start, ET date, team abbrevs, status)."""
    out = {}
    for _, r in _rows(root, "context/schedule"):
        g = str(r["game_id"])
        if g not in out or r["_observed_at_utc"] >= out[g]["_observed_at_utc"]:
            out[g] = r
    return out

def load_kalshi_settled(kdir: str) -> dict:
    """ticker -> settled market (from fetch_kalshi_settled.py pages). A ticker seen twice keeps the later settlement."""
    out = {}
    for f in sorted(glob.glob(os.path.join(kdir, "*_p*.json.gz"))):
        series = os.path.basename(f).rsplit("_p", 1)[0]
        with gzip.open(f, "rt") as fh:
            d = json.load(fh)
        for m in d.get("markets", []):
            m = dict(m, _series=series)
            prev = out.get(m["ticker"])
            if prev is None or str(m.get("settlement_ts") or "") >= str(prev.get("settlement_ts") or ""):
                out[m["ticker"]] = m
    return out


# ----------------------------------------------------------------------------- identity
def game_index(schedule: dict) -> dict:
    """(ET date, frozenset{abbrevs}) -> [game_id]."""
    ix = defaultdict(list)
    for g, r in schedule.items():
        ix[(r["game_date_et"], frozenset((r["home_abbrev"], r["away_abbrev"])))].append(g)
    return ix


def _split_teams(code: str, abbrevs: set) -> Optional[frozenset]:
    """'BUFCHI' -> {'BUF','CHI'} using known abbreviations (NHL + Kalshi aliases); None if no unique split."""
    known = abbrevs | set(KALSHI_TEAM_ALIAS)
    splits = []
    for i in range(2, len(code) - 1):
        a, b = code[:i], code[i:]
        if a in known and b in known:
            splits.append(frozenset((KALSHI_TEAM_ALIAS.get(a, a), KALSHI_TEAM_ALIAS.get(b, b))))
    return splits[0] if len(set(splits)) == 1 else None


def ticker_game(event_ticker: str, gix: dict, abbrevs: set) -> tuple:
    """Kalshi event ticker -> (game_id | None, reason)."""
    m = _EVT.search(event_ticker or "")
    if not m:
        return None, "EVENT_TICKER_UNPARSEABLE"
    yy, mon, dd, teams = m.groups()
    if mon not in _MON:
        return None, "EVENT_TICKER_UNPARSEABLE"
    date = f"20{yy}-{_MON[mon]:02d}-{dd}"
    pair = _split_teams(teams, abbrevs)
    if pair is None:
        return None, "TEAM_CODES_UNMATCHED"
    hits = gix.get((date, pair), [])
    if len(hits) != 1:
        return None, "NO_ARCHIVED_GAME" if not hits else "AMBIGUOUS_GAME"
    return hits[0], "OK"



# ----------------------------------------------------------------------------- settlement rows + per-market cross-check
VOID_RESULTS = ("void", "canceled", "cancelled", "scalar")


def settlement_rows(kalshi: dict, schedule: dict) -> tuple:
    """Kalshi settled markets -> ({ticker: outcome row}, identity Counter, info Counter). The outcome ``event_id`` is the NHL game
    the event ticker's date + team codes resolve to in the archived schedule (never the producer's id), so a ticker whose identity
    differs from the forecast's game BLOCKS at the standard's event-identity join. ``scalar`` (Kalshi's "active but never entered"
    rule) and void/cancelled results are ``state=void``."""
    gix = game_index(schedule)
    abbrevs = {r["home_abbrev"] for r in schedule.values()} | {r["away_abbrev"] for r in schedule.values()}
    rows, ident, info = {}, Counter(), Counter()
    for ticker, m in kalshi.items():
        fam = SERIES_FAMILY.get(m["_series"])
        if fam is None:
            info["kalshi.non_game_series_markets"] += 1
            continue
        g, why = ticker_game(m.get("event_ticker", ""), gix, abbrevs)
        ident[why] += 1
        ev = g if g else f"UNMAPPED:{why}:{m.get('event_ticker')}"
        res = (m.get("result") or "").lower()
        obs = m.get("settlement_ts") or m.get("close_time")
        base = dict(schema=SCHEMA_VERSION, market_id=ticker, event_id=ev, observed_at=obs, source="market_settlement", native_family=fam)
        if res in ("yes", "no"):
            rows[ticker] = dict(base, state="final", value=1 if res == "yes" else 0)
        elif res in VOID_RESULTS:
            info[f"kalshi.void_or_scalar.{res}"] += 1
            rows[ticker] = dict(base, state="void", value=None)
        else:
            info[f"kalshi.result_other.{res or 'EMPTY'}"] += 1
    return rows, ident, info


def _official_state(rows: list) -> tuple:
    """Collapse one market's official-API outcome rows -> (kind, value, event_id): kind in FINAL / VOID / CONFLICT."""
    vals = {(r["state"], r.get("value")) for r in rows}
    ev = rows[0]["event_id"]
    if len(vals) > 1:
        return "CONFLICT", None, ev
    st, v = next(iter(vals))
    return ("VOID", None, ev) if st != "final" else ("FINAL", int(v), ev)


def cross_check(official_outcomes: list, settle: dict, *, max_examples: int = 50) -> dict:
    """Per-market comparison of the official-API outcome rows (``source=sports``, as built by ``nhl_archive``) with Kalshi's
    settlement rows. Returns dict(rows=[settlement rows to append], counts={category: n}, by_family={family: {category: n}},
    disagreements=[...]).

    A settlement row is appended for EVERY market that already has an official row: agreement collapses in the grader,
    disagreement (value, void-vs-final or event identity) becomes a conflict the standard blocks. Markets Kalshi settled that
    have no official row are counted (``KALSHI_ONLY_NO_OFFICIAL_ROW``) and NOT appended: the official source stays primary and a
    market is never graded on the settlement alone. Markets already ambiguous on the official side (shootout-goal rule) stay
    blocked, and the side Kalshi actually settled is counted so the rule can be read off the data."""
    by_mkt = defaultdict(list)
    for r in official_outcomes:
        if r.get("source") == "sports":
            by_mkt[r["market_id"]].append(r)
    counts, by_fam, add, dis = Counter(), defaultdict(Counter), [], []

    def note(cat, fam, ticker=None, **kw):
        counts[cat] += 1; by_fam[fam or "unknown"][cat] += 1
        if ticker is not None and len(dis) < max_examples:
            dis.append(dict(market_id=ticker, category=cat, native_family=fam, **kw))
    for ticker, rows in sorted(by_mkt.items()):
        k = settle.get(ticker)
        kind, val, ev = _official_state(rows)
        if k is None:
            note("NO_KALSHI_SETTLEMENT", None)
            continue
        fam = k.get("native_family")
        out = {x: k[x] for x in ("schema", "market_id", "event_id", "state", "value", "observed_at", "source")}
        add.append(out)
        k_final = k["state"] == "final"
        if k["event_id"] != ev:
            note("EVENT_IDENTITY_DISAGREE", fam, ticker, official_event=ev, kalshi_event=k["event_id"])
        elif kind == "CONFLICT":
            note("OFFICIAL_AMBIGUOUS_KALSHI_" + ("YES" if k_final and k["value"] == 1 else "NO" if k_final else "VOID"), fam)
        elif kind == "VOID":
            note("AGREE_VOID" if not k_final else "OFFICIAL_VOID_KALSHI_FINAL", fam, None if not k_final else ticker, kalshi_value=k["value"])
        elif not k_final:
            note("OFFICIAL_FINAL_KALSHI_VOID", fam, ticker, official_value=val)
        elif int(k["value"]) == val:
            note("AGREE", fam)
        else:
            note("DISAGREE", fam, ticker, official_value=val, kalshi_value=int(k["value"]))
    for ticker, k in settle.items():
        if ticker not in by_mkt:
            note("KALSHI_ONLY_NO_OFFICIAL_ROW", k.get("native_family"))
    return dict(rows=add, counts=dict(sorted(counts.items())), by_family={f: dict(sorted(c.items())) for f, c in sorted(by_fam.items())},
                disagreements=dis)


def apply(build_out: dict, kalshi: dict, schedule: dict) -> dict:
    """Add the settlement source to an ``nhl_archive.build`` result IN PLACE (outcomes extended; accounting under
    ``info['kalshi_settlement']``) and return the cross-check."""
    settle, ident, info = settlement_rows(kalshi, schedule)
    x = cross_check(build_out["outcomes"], settle)
    build_out["outcomes"].extend(x["rows"])
    build_out["info"]["kalshi_settlement"] = dict(n_settled_markets=len(kalshi), n_game_bound_rows=len(settle), identity=dict(ident),
                                                  info=dict(sorted(info.items())), cross_check_vs_official=x["counts"],
                                                  cross_check_by_family=x["by_family"], disagreement_examples=x["disagreements"],
                                                  n_settlement_rows_appended=len(x["rows"]))
    return x


# ----------------------------------------------------------------------------- secondary slices (the standard's own cells)
PRIOR_AUDIT_DATA_PIN = "2026-11-04T19:38:30Z"   # commit time of NHL-edge-finder@data-archive eacc3b9d, the input of reports/outcome_intel/nhl_audit.json
# The one candidate the prior audit carried forward (PLAYER_SIM_V1 goalie saves, PROMISING_INSUFFICIENT). Fixed before any
# goalie-saves-specific number on post-pin games was computed: one hypothesis, two-sided, alpha 0.05, standard's Brier delta.
CONFIRMATION_TEST = dict(model_id="PLAYER_SIM_V1", native_family="goalie_saves", games_starting_after=PRIOR_AUDIT_DATA_PIN,
                         metric="paired Brier delta (market - model), event-clustered bootstrap, sift-alpha-eval/1 market_cell",
                         alpha=0.05, sidedness="two-sided")


def native_family_cells(rows: list, forecasts: list) -> dict:
    """Model-vs-market per (model, native family) over all games and split at the prior audit's data pin, using
    ``aggregate.market_cell`` / ``verdict_for`` / ``holm`` unchanged. SECONDARY: its own Holm family, never pooled with
    the primary grid, never a promotion input."""
    from .aggregate import _clean, market_cell, verdict_for
    from sift_research.stats import holm
    start = {f["forecast_id"]: f["event_start"] for f in forecasts}
    groups = defaultdict(list)
    for r in rows:
        if r["evidence_class"] != PROSPECTIVE:
            continue
        nf = r["native_family"]
        post = start[r["forecast_id"]] > PRIOR_AUDIT_DATA_PIN
        groups[(r["model_id"], nf, "ALL")].append(r)
        groups[(r["model_id"], nf, "AFTER_PRIOR_AUDIT_PIN" if post else "UP_TO_PRIOR_AUDIT_PIN")].append(r)
    cells = [(k, market_cell(v)) for k, v in sorted(groups.items())]
    cells = [(k, m) for k, m in cells if m.get("n_paired_rows")]
    ph = holm([m["_p"] if m["_p"] is not None else 1.0 for _, m in cells]) if cells else []
    out = []
    for (k, m), h in zip(cells, ph):
        b = m["brier_delta_market_minus_model"]
        out.append(dict(model_id=k[0], native_family=k[1], window=k[2], n_paired_rows=m["n_paired_rows"], n_events=m["n_events"],
                        brier_delta=b, logloss_delta=m["logloss_delta_market_minus_model"], p_holm_secondary=round(float(h), 6),
                        verdict_secondary=verdict_for(m, p_holm=float(h))))
    ct = [c for c in out if c["model_id"] == CONFIRMATION_TEST["model_id"] and c["native_family"] == CONFIRMATION_TEST["native_family"]
          and c["window"] == "AFTER_PRIOR_AUDIT_PIN"]
    conf = dict(CONFIRMATION_TEST)
    if ct:
        b = ct[0]["brier_delta"]
        conf.update(n_paired_rows=ct[0]["n_paired_rows"], n_events=ct[0]["n_events"], brier_delta=b, logloss_delta=ct[0]["logloss_delta"],
                    result=("CONFIRMED_MODEL_BETTER" if b["lo"] is not None and b["lo"] > 0 and b["p"] is not None and b["p"] < 0.05
                            else "MARKET_BETTER" if b["hi"] is not None and b["hi"] < 0 else "NOT_CONFIRMED"))
    else:
        conf.update(result="NO_PAIRED_DATA")
    return dict(cells=out, confirmation_test=conf, note="secondary slice; separate Holm family; not a promotion input")


def native_family_markdown(sec: dict) -> str:
    L = ["", "## Secondary: model vs market by native family (separate Holm family; not a promotion input)", "",
         f"Split at the prior NHL audit's data pin ({PRIOR_AUDIT_DATA_PIN}). Δ = market − model (positive favours the model).", "",
         "| model | native family | window | rows | events | Δ Brier [95% CI] | Δ log-loss [95% CI] | p_holm (secondary) | verdict |",
         "|---|---|---|---|---|---|---|---|---|"]
    f = lambda d: "–" if not d or d.get("mean") is None else f"{d['mean']:+.4f} [{d['lo']:+.4f}, {d['hi']:+.4f}]"  # noqa: E731
    for c in sec["cells"]:
        L.append(f"| {c['model_id']} | {c['native_family']} | {c['window']} | {c['n_paired_rows']} | {c['n_events']} | {f(c['brier_delta'])} | "
                 f"{f(c['logloss_delta'])} | {c['p_holm_secondary']} | {c['verdict_secondary']} |")
    t = sec["confirmation_test"]
    L += ["", "### Pre-specified confirmation test", "",
          f"`{t['model_id']}` / `{t['native_family']}`, games starting after {t['games_starting_after']}; {t['metric']}; {t['sidedness']}, alpha {t['alpha']}.", "",
          f"- result: **{t['result']}**" + (f"; rows {t['n_paired_rows']}, events {t['n_events']}, Δ Brier {f(t['brier_delta'])} (p {t['brier_delta'].get('p')}), "
                                            f"Δ log-loss {f(t['logloss_delta'])}" if "brier_delta" in t else ""), ""]
    return "\n".join(L)
