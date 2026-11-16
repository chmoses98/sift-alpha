"""Point-in-time audit of the 22 features of the certified MLB dataset v1 (RESEARCH_ONLY).

The v1 certification proves the builder is reproducible and leakage-free *given its inputs*. It does not prove WHEN each
input was knowable. This audit answers that per feature, from data:

* Team form (12 columns): computed from games that ended before first pitch. For each row the earliest moment the value is
  final is the end of that team's latest prior game (`avail_utc`). The value is a valid pregame observation for any
  decision time in [avail_utc, start_utc). The audit measures the lead time start - avail, so a user can tell which
  decision horizons (T-24h, T-6h, T-90m) the stored value serves without recomputation.
* Starter form (10 columns): the statistics are prior-start aggregates (PIT-safe), but they are keyed by the starter
  IDENTITY read from the final box score. That identity is retrospective. The audit compares it to genuinely timestamped
  pregame captures (edge-finder-api `data/slates/<date>/<kind>_<YYYYMMDDTHHMMSSZ>.json`, written before first pitch) and
  reports coverage and agreement. Retrospective identity is never counted as a verified pregame observation.

Usage:
    python -m alpha_engine.certify.mlb_pit_audit --dataset mlb.parquet --slates ../edge-finder-api/data/slates --out research/certification/mlb_v1_pit_audit.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

TEAM_STATS = ["n_pre", "rs_pg_pre", "ra_pg_pre", "win_pct_pre", "rs_l10_pre", "ra_l10_pre"]
SP_STATS = ["sp_n_pre", "sp_ip_ps_pre", "sp_ra9_pre", "sp_k_rate_pre", "sp_bb_rate_pre"]
SIDES = ["home", "away"]
HORIZONS_H = {"T-24h": 24.0, "T-6h": 6.0, "T-90m": 1.5}
TS_RE = re.compile(r"^(?P<kind>[a-z]+)_(?P<ts>\d{8}T\d{6}Z)\.json$")
EXCLUDE_KINDS = {"rejected"}          # files the producer itself marked contaminated


def _utc(s) -> pd.Timestamp:
    return pd.Timestamp(s).tz_convert("UTC") if pd.Timestamp(s).tzinfo else pd.Timestamp(s).tz_localize("UTC")


def team_availability(df: pd.DataFrame) -> pd.DataFrame:
    """Per (game, side): avail_utc = end of the team's latest prior game (same season, end < start). NaT when none."""
    start = pd.to_datetime(df["start_utc"], utc=True).astype("datetime64[ns, UTC]"); end = pd.to_datetime(df["end_utc"], utc=True).astype("datetime64[ns, UTC]")
    long = pd.concat([pd.DataFrame({"game_id": df.game_id, "season": df.season, "team": df[f"{s}_id"], "side": s,
                                    "start": start, "end": end}) for s in SIDES], ignore_index=True)
    out = []
    for (_, _), g in long.groupby(["season", "team"], sort=False):
        ends = g["end"].sort_values().astype("int64").to_numpy()
        for r in g.itertuples(index=False):
            i = ends.searchsorted(r.start.value, side="left")      # ends strictly before start
            out.append((r.game_id, r.side, pd.Timestamp(int(ends[i - 1]), tz="UTC") if i else pd.NaT, r.start))
    a = pd.DataFrame(out, columns=["game_id", "side", "avail_utc", "start_utc"])
    a["lead_h"] = (a["start_utc"] - a["avail_utc"]).dt.total_seconds() / 3600.0
    return a


def _q(s: pd.Series) -> dict:
    s = s.dropna()
    return {k: round(float(s.quantile(q)), 3) for k, q in (("p05", .05), ("p25", .25), ("median", .5), ("p75", .75), ("p95", .95))} if len(s) else {}


def pregame_starters(slates: Path) -> dict:
    """gamePk -> {"home": (id, ts, file), "away": ...}: the EARLIEST timestamped capture per side whose ts precedes the
    game's own startTime in that file. Files without a timestamp in the name or marked rejected are ignored."""
    best: dict = {}
    for f in sorted(slates.glob("*/*.json")):
        m = TS_RE.match(f.name)
        if not m or m["kind"] in EXCLUDE_KINDS:
            continue
        ts = datetime.strptime(m["ts"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        try:
            games = json.loads(f.read_text()).get("games") or []
        except (OSError, ValueError, AttributeError):
            continue
        for g in games:
            try:
                pk = int(g.get("gameId")); st = datetime.fromisoformat(str(g.get("startTime")).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if ts >= st:
                continue
            for side in SIDES:
                pid = ((g.get(side) or {}).get("pitcher") or {}).get("id")
                if not pid or not str(pid).isdigit():
                    continue
                cur = best.setdefault(pk, {}).get(side)
                if cur is None or ts < cur[1]:
                    best[pk][side] = (int(pid), ts, f"{f.parent.name}/{f.name}", st)
    return best


def audit(df: pd.DataFrame, slates: Path | None) -> dict:
    a = team_availability(df)
    has = a["avail_utc"].notna()
    team = {"rows": int(len(a)), "rows_with_prior_game": int(has.sum()), "lead_hours": _q(a.loc[has, "lead_h"]),
            "share_value_final_by": {h: round(float((a.loc[has, "lead_h"] >= v).mean()), 4) for h, v in HORIZONS_H.items()},
            "min_lead_hours": round(float(a.loc[has, "lead_h"].min()), 4)}
    sp = {"source": None}
    if slates and slates.exists():
        pre = pregame_starters(slates)
        rows = []
        for r in df.itertuples(index=False):
            for side in SIDES:
                p = pre.get(int(r.game_id), {}).get(side)
                if p:
                    rows.append((int(r.season), side, int(getattr(r, f"{side}_sp_id")), p[0], (p[3] - p[1]).total_seconds() / 3600.0))
        c = pd.DataFrame(rows, columns=["season", "side", "box_sp", "pregame_sp", "lead_h"])
        agree = c["box_sp"] == c["pregame_sp"]
        by_season = df.groupby("season").size().to_dict()
        sp = {"source": "edge-finder-api data/slates/<date>/<kind>_<UTC ts>.json, earliest capture before the game's startTime",
              "slate_files_hash": hashlib.sha256("\n".join(sorted(str(p.relative_to(slates)) for p in slates.glob("*/*.json"))).encode()).hexdigest()[:16],
              "games_by_season": {int(k): int(v) for k, v in by_season.items()},
              "starter_slots_total": int(2 * len(df)), "starter_slots_with_pregame_capture": int(len(c)),
              "coverage_by_season": {int(s): round(float(len(c[c.season == s]) / (2 * by_season[s])), 4) for s in sorted(by_season)},
              "agree": int(agree.sum()), "disagree": int((~agree).sum()),
              "agreement_share": round(float(agree.mean()), 4) if len(c) else None,
              "pregame_capture_lead_hours": _q(c["lead_h"]),
              "disagree_examples": c.loc[~agree].head(10).to_dict("records")}
    feats = {}
    for s in SIDES:
        for t in TEAM_STATS:
            feats[f"{s}_{t}"] = {"group": "team_form", "pregame": "VERIFIED_PIT",
                                 "valid_from": "end of the team's latest prior game (avail_utc); valid for any decision time in [avail_utc, first pitch)",
                                 "early_forecast": "valid only on rows whose lead time covers the horizon (share_value_final_by); otherwise recompute as of the decision time"}
        for t in SP_STATS:
            feats[f"{s}_{t}"] = {"group": "starter_form", "pregame": "NOT_VERIFIED_RETROSPECTIVE_IDENTITY",
                                 "valid_from": "lineup card / confirmed starter; this dataset keys it on the box-score starter, whose pregame announcement time is not recorded",
                                 "early_forecast": "not valid: needs a timestamped probable-starter identity per decision time"}
    return {"schema": "mlb-pit-audit-1.0", "status": "RESEARCH_ONLY",
            "notice": "Agent-run, not human verified. Counts only; no data rows beyond ten id pairs.",
            "dataset_canonical_sha256": None, "features": feats, "team_form_availability": team, "starter_identity": sp}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--slates", type=Path)
    ap.add_argument("--canonical-sha", required=True, help="canonical_sha256 of the certified dataset (builder evidence)")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    df = pd.read_parquet(a.dataset)
    rep = audit(df, a.slates)
    rep["dataset_canonical_sha256"] = a.canonical_sha
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rep, indent=1, default=str) + "\n")
    print(json.dumps({k: rep[k] for k in ("team_form_availability", "starter_identity")}, indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
