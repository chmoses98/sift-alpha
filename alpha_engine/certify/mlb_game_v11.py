"""MLB game-level dataset v1.1: season state, Pythagorean / BaseRuns luck, close-game records, bullpen run rate (RESEARCH_ONLY).

    python -m alpha_engine.certify.mlb_game_v11 --feed-root <restored vault feeds> --out mlb_game_v11.parquet [--lead-hours L] [--evidence OUT.json]

Specification: docs/certification/MLB_FEATURE_SPEC_V11.md. PRIMARY builder; the independent re-implementation
(`mlb_independent_v11.py`) was written from the spec alone. v1 (`mlb_game_v1`, hash f598384b...) is not modified.

Differences from v1: team inputs only (no starting-pitcher column: the archive's starter identity is the box-score
starter, not a timestamped pregame announcement); an explicit decision-time lead L (prior = ended before
first pitch - L hours), so a forecast made the day before can be built without look-ahead; `X_last_end_utc`
records when each side's features became final.
"""
from __future__ import annotations

import argparse
import bisect
import glob
import json
import os
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .mlb_game_v1 import _fmt, _ts

SPEC = "docs/certification/MLB_FEATURE_SPEC_V11.md v1.1"
SIDES = ("home", "away")
SEASON_GAMES = 162
EXP = 1.83
INT_F = ["n_pre", "wins_pre", "losses_pre", "ties_pre", "games_remaining_pre", "run_diff_pre", "unresolved_pre"]
FLOAT_F1 = ["rs_pg_pre", "ra_pg_pre", "rs_l10_pre", "ra_l10_pre", "win_pct_pre", "pyth_pct_pre", "pyth_luck_pre"]
TEAM_F = INT_F + FLOAT_F1 + ["one_run_n_pre", "one_run_win_pct_pre", "bsr_rs_pg_pre", "bsr_ra_pg_pre", "bsr_pct_pre", "bsr_luck_pre",
                             "late_close_n_pre", "late_close_win_pct_pre", "bullpen_ra9_pre"]
INT_COLS = set(INT_F + ["one_run_n_pre", "late_close_n_pre"])
ID_COLS = ["game_id", "season", "official_date", "start_utc", "end_utc", "game_number", "home_id", "away_id"]
LABELS = ["home_runs", "away_runs", "total_runs", "y_home_win"]
FEATURES = [f"{s}_{f}" for s in SIDES for f in TEAM_F]
COLUMNS = ID_COLS + FEATURES + ["home_last_end_utc", "away_last_end_utc"] + LABELS
BAT = ("hits", "baseOnBalls", "homeRuns", "totalBases", "atBats")
# catalog inputs and the columns that implement their full definition
CATALOG = {
    "mlb.pythag_luck": ["win_pct_pre", "pyth_pct_pre", "pyth_luck_pre", "bsr_rs_pg_pre", "bsr_ra_pg_pre", "bsr_pct_pre", "bsr_luck_pre", "one_run_n_pre", "one_run_win_pct_pre",
                        "late_close_n_pre", "late_close_win_pct_pre", "bullpen_ra9_pre"],
    "mlb.wins_to_date_and_games_remaining": ["n_pre", "wins_pre", "losses_pre", "ties_pre", "games_remaining_pre", "run_diff_pre", "unresolved_pre"],
}


def _i(v) -> int:
    return int(v or 0)


def read_game(doc: dict):
    if (doc.get("game") or {}).get("type") != "R":
        return None, "not_regular_season"
    fp, plays = (doc.get("game_info") or {}).get("firstPitch"), doc.get("plays") or []
    if not fp or not plays or not plays[-1].get("end"):
        return None, "missing_first_pitch_or_last_play_end"
    g = {"game_id": int(doc["pk"]), "season": int(doc["game"]["season"]), "official_date": doc["datetime"]["officialDate"],
         "start": _ts(fp), "end": _ts(plays[-1]["end"]), "game_number": int(doc["game"]["gameNumber"])}
    inn = (doc.get("linescore") or {}).get("innings") or []
    for s in SIDES:
        box = doc["box"][s]
        g[f"{s}_id"] = int(doc["teams"][s]["id"])
        g[f"{s}_runs"] = _i(doc["linescore"]["teams"][s].get("runs"))
        bat = (box.get("team_stats") or {}).get("batting") or {}
        g[f"{s}_bat"] = tuple(_i(bat.get(k)) for k in BAT)
        g[f"{s}_r6"] = sum(_i((x.get(s) or {}).get("runs")) for x in inn if _i(x.get("n")) <= 6)
        pit = {p.get("id"): (p.get("pit") or {}) for p in box.get("players") or []}
        rel = [pit.get(i, {}) for i in (box.get("pitchers") or [])[1:]]
        g[f"{s}_rel"] = (sum(_i(x.get("runs")) for x in rel), sum(_i(x.get("outs")) for x in rel))
    return g, None


def load_games(feed_root) -> tuple[list, dict]:
    games, dropped = {}, {}
    for season_dir in sorted(glob.glob(os.path.join(str(feed_root), "*"))):
        if not os.path.isdir(season_dir):
            continue
        for path in sorted(glob.glob(os.path.join(season_dir, "**", "*.json"), recursive=True)):
            if os.path.basename(path).startswith("_"):
                continue
            with open(path) as fh:
                g, why = read_game(json.load(fh))
            if g is None:
                dropped[why] = dropped.get(why, 0) + 1
            elif g["game_id"] not in games:
                games[g["game_id"]] = g
            else:
                dropped["duplicate_pk"] = dropped.get("duplicate_pk", 0) + 1
    return sorted(games.values(), key=lambda g: (g["start"], g["game_id"])), dropped


def _bsr(t):
    h, bb, hr, tb, ab = t
    a = h + bb - hr; b = 1.02 * (1.4 * tb - 0.6 * h - 3 * hr + 0.1 * bb); c = ab - h
    return None if b + c <= 0 else a * b / (b + c) + hr


def _pct(x, y):
    return x ** EXP / (x ** EXP + y ** EXP)


def _team_feats(hist: list, unresolved: int) -> dict:
    """hist: prior games in (end, game_id) order; each = (rs, ra, own_bat, opp_bat, r6, opp_r6, rel)."""
    n = len(hist); nan = float("nan")
    rs = [h[0] for h in hist]; ra = [h[1] for h in hist]
    w = sum(1 for a, b in zip(rs, ra) if a > b); l = sum(1 for a, b in zip(rs, ra) if a < b)
    r = {"n_pre": n, "wins_pre": w, "losses_pre": l, "ties_pre": n - w - l, "games_remaining_pre": SEASON_GAMES - n, "run_diff_pre": sum(rs) - sum(ra),
         "unresolved_pre": unresolved}
    k = min(10, n)
    r.update(rs_pg_pre=sum(rs) / n if n else nan, ra_pg_pre=sum(ra) / n if n else nan, rs_l10_pre=sum(rs[-k:]) / k if n else nan, ra_l10_pre=sum(ra[-k:]) / k if n else nan)
    r["win_pct_pre"] = w / (w + l) if w + l else nan
    RS, RA = sum(rs), sum(ra)
    r["pyth_pct_pre"] = _pct(RS, RA) if RS + RA > 0 else nan
    r["pyth_luck_pre"] = r["win_pct_pre"] - r["pyth_pct_pre"]
    one = [(a, b) for a, b in zip(rs, ra) if abs(a - b) == 1]
    r["one_run_n_pre"] = len(one); r["one_run_win_pct_pre"] = sum(1 for a, b in one if a > b) / len(one) if one else nan
    s = _bsr(tuple(sum(h[2][i] for h in hist) for i in range(5))) if n else None
    a = _bsr(tuple(sum(h[3][i] for h in hist) for i in range(5))) if n else None
    r["bsr_rs_pg_pre"] = s / n if s is not None else nan; r["bsr_ra_pg_pre"] = a / n if a is not None else nan
    ok = s is not None and a is not None and s >= 0 and a >= 0 and s + a > 0
    r["bsr_pct_pre"] = _pct(s, a) if ok else nan
    r["bsr_luck_pre"] = r["win_pct_pre"] - r["bsr_pct_pre"]
    lc = [h for h in hist if abs(h[4] - h[5]) <= 1]
    r["late_close_n_pre"] = len(lc); r["late_close_win_pct_pre"] = sum(1 for h in lc if h[0] > h[1]) / len(lc) if lc else nan
    rr, ro = sum(h[6][0] for h in hist), sum(h[6][1] for h in hist)
    r["bullpen_ra9_pre"] = 27 * rr / ro if ro else nan
    return r


def build(games: list, lead_hours: float = 0.0) -> pd.DataFrame:
    lead = timedelta(hours=lead_hours)
    by_team: dict = {}
    for g in games:
        for s, o in (("home", "away"), ("away", "home")):
            by_team.setdefault((g["season"], g[f"{s}_id"]), []).append(
                (g["end"], g["game_id"], g["start"], (g[f"{s}_runs"], g[f"{o}_runs"], g[f"{s}_bat"], g[f"{o}_bat"], g[f"{s}_r6"], g[f"{o}_r6"], g[f"{s}_rel"])))
    keys = {}
    for k, v in by_team.items():
        v.sort(key=lambda x: (x[0], x[1])); keys[k] = [(x[0], x[1]) for x in v]
    rows = []
    for g in sorted(games, key=lambda g: (g["start"], g["game_id"])):
        t = g["start"] - lead
        r = {"game_id": g["game_id"], "season": g["season"], "official_date": g["official_date"], "start_utc": _fmt(g["start"]), "end_utc": _fmt(g["end"]),
             "game_number": g["game_number"], "home_id": g["home_id"], "away_id": g["away_id"]}
        for s in SIDES:
            k = (g["season"], g[f"{s}_id"]); v = by_team[k]
            m = bisect.bisect_left(keys[k], (t,))                              # strictly end < T
            unresolved = sum(1 for x in v[m:] if x[1] != g["game_id"] and x[2] < t)   # ended at/after T but started before it
            prior = [x for x in v[:m] if x[1] != g["game_id"]]            # h != g, even for a feed whose last play is stamped before first pitch
            for name, val in _team_feats([x[3] for x in prior], unresolved).items():
                r[f"{s}_{name}"] = val
            r[f"{s}_last_end_utc"] = _fmt(prior[-1][0]) if prior else ""
        r.update(home_runs=g["home_runs"], away_runs=g["away_runs"], total_runs=g["home_runs"] + g["away_runs"], y_home_win=int(g["home_runs"] > g["away_runs"]))
        rows.append(r)
    d = pd.DataFrame(rows, columns=COLUMNS)
    for c in FEATURES:
        d[c] = d[c].astype("int64" if c.split("_", 1)[1] in INT_COLS else float)
    return d


def _same(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    x, y = a[FEATURES].to_numpy(float), b[FEATURES].to_numpy(float)
    return bool(x.shape == y.shape and ((np.isnan(x) & np.isnan(y)) | (x == y)).all())


def _scramble(h: dict, k: int) -> dict:
    return {**h, "home_runs": h["home_runs"] + k, "away_runs": h["away_runs"] + 2 * k + 1, "home_bat": tuple(v + k for v in h["home_bat"]), "away_bat": tuple(v + 2 * k for v in h["away_bat"]),
            "home_r6": h["home_r6"] + k, "away_r6": h["away_r6"] + 3, "home_rel": (h["home_rel"][0] + k, h["home_rel"][1] + 1), "away_rel": (h["away_rel"][0] + 1, h["away_rel"][1] + k)}


def leakage_checks(games: list, d: pd.DataFrame, lead_hours: float, n_cutoffs: int = 12, seed: int = 7) -> dict:
    """Truncation (rebuild a sampled game from only the games that had STARTED before its decision time, with every game not yet ended
    stripped of its results), future scramble (change every game that ended at/after the decision time; rows decided at/before it must be
    identical) and own-outcome scramble."""
    rng = np.random.default_rng(seed); lead = timedelta(hours=lead_hours)
    idx = sorted(rng.choice(len(games), size=min(n_cutoffs, len(games)), replace=False).tolist())
    by_id = d.set_index("game_id"); trunc = scr = own = True; rows_checked = 0
    for i in idx:
        g = games[i]; t = g["start"] - lead
        visible = [h if h["end"] < t else _scramble(h, 5) for h in games if h["start"] < t and h["game_id"] != g["game_id"]]
        trunc &= _same(build(visible + [g], lead_hours).set_index("game_id").loc[[g["game_id"]]], by_id.loc[[g["game_id"]]])
        own &= _same(build([h for h in games if h["game_id"] != g["game_id"]] + [{**_scramble(g, 4), "end": g["end"] + (g["end"] - g["start"])}], lead_hours).set_index("game_id").loc[[g["game_id"]]],
                     by_id.loc[[g["game_id"]]])
        s = build([_scramble(h, 7) if h["end"] >= t else h for h in games], lead_hours).set_index("game_id")
        before = [h["game_id"] for h in games if h["start"] <= g["start"]]
        rows_checked += len(before); scr &= _same(s.loc[before], by_id.loc[before])
    return {"cutoffs": len(idx), "lead_hours": lead_hours, "truncation_identical": bool(trunc), "future_scramble_identical": bool(scr), "future_scramble_rows_checked": rows_checked,
            "own_outcome_scramble_identical": bool(own)}


def availability(d: pd.DataFrame) -> dict:
    """How long before first pitch each row's features were final (from X_last_end_utc)."""
    st = pd.to_datetime(d.start_utc, utc=True); out = {}
    le = pd.concat([pd.to_datetime(d[f"{s}_last_end_utc"].replace("", None), utc=True) for s in SIDES], axis=1).max(axis=1)
    lead = (st - le).dt.total_seconds() / 3600; has = lead.notna()
    out["rows_with_history"] = int(has.sum()); out["median_hours_final_before_first_pitch"] = round(float(lead[has].median()), 2)
    for h in (1.5, 6, 12, 24):
        out[f"share_final_by_T-{h:g}h"] = round(float((lead[has] >= h).mean()), 4)
    return out


def evidence(games: list, d: pd.DataFrame, dropped: dict, checks: dict, lead_hours: float) -> dict:
    from alpha_engine.foundation.training_sets import canonical_hash
    return {"schema": "mlb-game-dataset-1.1", "status": "RESEARCH_ONLY", "spec": SPEC, "builder": "alpha_engine.certify.mlb_game_v11", "lead_hours": lead_hours,
            "rows": int(len(d)), "columns": len(d.columns), "features": len(FEATURES), "dropped": dropped,
            "seasons": {str(k): int(v) for k, v in d["season"].value_counts().sort_index().items()}, "date_range": [d["official_date"].min(), d["official_date"].max()],
            "keys_unique": bool(not d["game_id"].duplicated().any()), "canonical_sha256": canonical_hash(d),
            "deterministic_regeneration": canonical_hash(build(games, lead_hours)) == canonical_hash(d),
            "missing_share": {c: round(float(d[c].isna().mean()), 6) for c in FEATURES if d[c].isna().any()},
            "ties_total": int(d.home_ties_pre.max()), "rows_with_unresolved_game": int(((d.home_unresolved_pre > 0) | (d.away_unresolved_pre > 0)).sum()),
            "availability": availability(d), "leakage": checks, "catalog_columns": CATALOG,
            "not_pregame": "home_runs, away_runs, total_runs, y_home_win, end_utc are outcomes; no starting-pitcher column exists in v1.1"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--feed-root", required=True); ap.add_argument("--out", required=True); ap.add_argument("--evidence"); ap.add_argument("--lead-hours", type=float, default=0.0)
    a = ap.parse_args(argv)
    games, dropped = load_games(a.feed_root)
    d = build(games, a.lead_hours)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); d.to_parquet(a.out, index=False)
    ev = evidence(games, d, dropped, leakage_checks(games, d, a.lead_hours), a.lead_hours)
    if a.evidence:
        Path(a.evidence).parent.mkdir(parents=True, exist_ok=True); Path(a.evidence).write_text(json.dumps(ev, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: ev[k] for k in ("rows", "canonical_sha256", "deterministic_regeneration", "dropped", "availability", "leakage", "ties_total", "rows_with_unresolved_game")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
