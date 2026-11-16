"""Point-in-time certification checks for the Phase 8 CBB / CFB game datasets (RESEARCH_ONLY).

Each check rebuilds a dataset from MODIFIED raw inputs and compares the feature values of the games on a cutoff date D
against an unmodified build that covers the same dates:

* future_scramble: every source row dated >= D (D's own games included) gets its statistics and scores replaced by random
  draws. If any feature value for D's games changes, a value dated on or after D reached a pre-game feature
  (future leakage, or own-game leakage, since D's games are inside the scrambled set).
* own_game: one game G on date D has its statistics and score perturbed; G's own feature row must not change.
* outcome_reconciliation: each dataset outcome is compared with an independent result table from the same provider
  (CBB: ESPN schedule home/away score; CFB: CFBD games_teams points).

Builds are restricted to dates <= D + 7 days so each check costs one chain up to D rather than a full history build;
rows after D cannot affect D unless the builder leaks, which is what the check detects.

    python -m alpha_engine.certify.leakage cbb --cbb DIR --dates 2008-01-12,2013-02-02 --out OUT.json
    python -m alpha_engine.certify.leakage cfb --cfb DIR --dates 2016-10-15,2023-11-25 --out OUT.json
"""
from __future__ import annotations

import argparse
import copy
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

TOL = 1e-9
CBB_STATS = ["field_goals_attempted", "field_goals_made", "three_point_field_goals_made", "free_throws_attempted",
             "offensive_rebounds", "defensive_rebounds", "turnovers", "team_score", "opponent_team_score"]


def _compare(a: pd.DataFrame, b: pd.DataFrame, fc: list[str]) -> dict:
    a = a.set_index("game_id").sort_index(); b = b.set_index("game_id").sort_index()
    common = a.index.intersection(b.index)
    A, B = a.loc[common, fc].to_numpy(float), b.loc[common, fc].to_numpy(float)
    nan_eq = np.isnan(A) == np.isnan(B)
    diff = np.abs(np.nan_to_num(A) - np.nan_to_num(B))
    bad = (~nan_eq) | (diff > TOL * np.maximum(1, np.abs(np.nan_to_num(B))))
    cols = sorted({fc[j] for j in np.where(bad.any(axis=0))[0]})
    return {"games": int(len(common)), "games_only_one_side": int(len(a.index.symmetric_difference(b.index))),
            "cells_differing": int(bad.sum()), "columns_differing": cols, "max_abs_diff": float(diff.max()) if diff.size else 0.0,
            "identical": bool(len(common) > 0 and not bad.any())}


# ------------------------------------------------------------------------------------------------------------------- CBB
def _cbb_build(raw):
    from ..foundation.training_sets_multi import cbb_dataset
    return cbb_dataset(Path("."), raw)


def cbb_checks(cbb_dir: Path, dates: list[str], seed: int = 7) -> dict:
    from ..features import cbb_box as C
    raw = C.load_raw(cbb_dir)
    tb = raw["team_box"].copy(); tb["_d"] = pd.to_datetime(tb.game_date)
    rng = np.random.default_rng(seed); out = {}
    for ds in dates:
        D = pd.Timestamp(ds); lim = tb[tb._d <= D + pd.Timedelta(days=7)]
        base, meta = _cbb_build({"team_box": lim.drop(columns="_d"), "schedule": raw["schedule"]}); fc = meta["feature_columns"]
        # future scramble: rows on/after D
        sc = lim.copy(); m = sc._d >= D
        for c in CBB_STATS:
            sc[c] = pd.to_numeric(sc[c], errors="coerce").astype(float)
        for c in CBB_STATS:
            v = pd.to_numeric(sc.loc[m, c], errors="coerce")
            sc.loc[m, c] = rng.integers(0, 120, size=m.sum()).astype(float) if c.endswith("score") else rng.permutation(v.to_numpy())
        scr, _ = _cbb_build({"team_box": sc.drop(columns="_d"), "schedule": raw["schedule"]})
        r_future = _compare(base[base.date == D], scr[scr.date == D], fc)
        # own-game: perturb one home game on D
        g = base[base.date == D].game_id.iloc[len(base[base.date == D]) // 2]
        og = lim.copy(); mm = og.game_id == g
        for c in CBB_STATS:
            og[c] = pd.to_numeric(og[c], errors="coerce").astype(float)
        for c in CBB_STATS:
            og.loc[mm, c] = pd.to_numeric(og.loc[mm, c], errors="coerce") * 1.5 + 11
        own, _ = _cbb_build({"team_box": og.drop(columns="_d"), "schedule": raw["schedule"]})
        r_own = _compare(base[base.game_id == g], own[own.game_id == g], fc)
        # sanity: the perturbation must reach later games (otherwise the check is vacuous)
        later = _compare(base[base.date > D], own[own.date > D], fc)
        out[ds] = {"future_scramble": r_future, "own_game": {"game_id": int(g), **r_own},
                   "perturbation_reaches_later_games": not later["identical"], "rows_scrambled": int(m.sum())}
    return out


def cbb_outcomes(cbb_dir: Path, d: pd.DataFrame) -> dict:
    from ..features import cbb_box as C
    sc = C.load_raw(cbb_dir)["schedule"].drop_duplicates("game_id")
    sc = sc[["game_id", "home_id", "away_id", "home_score", "away_score"]].copy()
    for c in ("home_score", "away_score"):
        sc[c] = pd.to_numeric(sc[c], errors="coerce")
    j = d[["game_id", "home_team", "away_team", "y_home_margin", "y_total"]].merge(sc, on="game_id", how="left")
    same_orient = (j.home_team.astype(str) == j.home_id.astype(str))
    flip = (j.home_team.astype(str) == j.away_id.astype(str))
    sm = np.where(same_orient, j.home_score - j.away_score, np.where(flip, j.away_score - j.home_score, np.nan))
    st = j.home_score + j.away_score
    has = ~np.isnan(sm)
    agree = has & (np.abs(sm - j.y_home_margin) < 1e-9) & (np.abs(st - j.y_total) < 1e-9)
    bad = j[has & ~agree]
    return {"games": int(len(j)), "schedule_result_available": int(has.sum()), "orientation_flipped": int(flip.sum()),
            "agree": int(agree.sum()), "disagree": int(len(bad)), "disagree_examples": bad.game_id.head(20).astype(int).tolist(),
            "disagree_all": bad.game_id.astype(int).tolist(), "unchecked_all": j.game_id[~has].astype(int).tolist(),
            "reference": "ESPN schedule home_score/away_score (separate table from the team box used for the outcome)"}


# ------------------------------------------------------------------------------------------------------------------- CFB
def _cfb_build(cache: Path, raw: dict):
    from ..features import cfb_cfbd as F
    from ..foundation import training_sets_multi as T
    orig = F.load_raw
    try:
        F.load_raw = lambda c, _r=raw: _r
        return T.cfb_dataset(cache)
    finally:
        F.load_raw = orig


def _cfb_date(g) -> pd.Timestamp | None:
    return pd.Timestamp(g["startDate"]).tz_convert("America/New_York").tz_localize(None).normalize() if g.get("startDate") else None


def cfb_checks(cache: Path, dates: list[str], seed: int = 7) -> dict:
    from ..features import cfb_cfbd as F
    raw = F.load_raw(cache); rng = np.random.default_rng(seed); out = {}
    gd = {g["id"]: _cfb_date(g) for g in raw["games"]}
    for ds in dates:
        D = pd.Timestamp(ds); keep = {k for k, v in gd.items() if v is not None and v <= D + pd.Timedelta(days=7)}
        fut = {k for k in keep if gd[k] >= D}
        lim = {**raw, "games": [g for g in raw["games"] if g["id"] in keep], "adv": [a for a in raw["adv"] if a["gameId"] in keep],
               "drives": [x for x in raw["drives"] if x["gameId"] in keep]}
        base, meta = _cfb_build(cache, lim); fc = meta["feature_columns"]

        def scramble(rec, ids, k):
            r = copy.deepcopy(rec)
            for g in r["games"]:
                if g["id"] in ids:
                    g["homePoints"], g["awayPoints"] = int(rng.integers(0, 70)), int(rng.integers(0, 70))
            for a in r["adv"]:
                if a["gameId"] in ids:
                    for side in ("offense", "defense"):
                        b = a.get(side) or {}
                        for key in ("ppa", "successRate", "explosiveness", "lineYards", "stuffRate", "plays"):
                            if isinstance(b.get(key), (int, float)):
                                b[key] = float(b[key]) * k + float(rng.normal())
                        for sub in ("passingPlays", "rushingPlays"):
                            if isinstance(b.get(sub), dict) and isinstance(b[sub].get("ppa"), (int, float)):
                                b[sub]["ppa"] = float(rng.normal())
            for x in r["drives"]:
                if x["gameId"] in ids:
                    x["driveResult"] = ["TD", "FG", "PUNT"][int(rng.integers(0, 3))]; x["startYardsToGoal"] = int(rng.integers(1, 99))
            return r
        scr, _ = _cfb_build(cache, scramble(lim, fut, 3.0))
        r_future = _compare(base[base.date == D], scr[scr.date == D], fc)
        today = base[base.date == D]; g = int(today.game_id.iloc[len(today) // 2])
        own, _ = _cfb_build(cache, scramble(lim, {g}, 2.0))
        r_own = _compare(base[base.game_id == g], own[own.game_id == g], fc)
        later = _compare(base[base.date > D], own[own.date > D], fc)
        out[ds] = {"future_scramble": r_future, "own_game": {"game_id": g, **r_own},
                   "perturbation_reaches_later_games": not later["identical"], "games_scrambled": len(fut)}
    return out


def cfb_outcomes(cache: Path, d: pd.DataFrame) -> dict:
    pts = {}
    for s in range(2014, 2026):
        p = Path(cache) / str(s) / "games_teams.json.gz"
        if not p.exists():
            continue
        x = json.load(gzip.open(p)); x = x if isinstance(x, list) else x.get("data", [])
        for g in x:
            t = {tt.get("homeAway"): tt for tt in g.get("teams", [])}
            if "home" in t and "away" in t:
                pts[g["id"]] = (t["home"].get("school") or t["home"].get("team"), t["home"].get("points"), t["away"].get("points"))
    j = d[["game_id", "home_team", "y_home_margin", "y_total", "postseason"]].copy()
    ref = j.game_id.map(pts)
    has = ref.notna()
    m = np.array([r[1] - r[2] if isinstance(r, tuple) and r[1] is not None and r[2] is not None else np.nan for r in ref])
    t = np.array([r[1] + r[2] if isinstance(r, tuple) and r[1] is not None and r[2] is not None else np.nan for r in ref])
    ok = ~np.isnan(m)
    agree = ok & (np.abs(m - j.y_home_margin.to_numpy()) < 1e-9) & (np.abs(t - j.y_total.to_numpy()) < 1e-9)
    bad = j[ok & ~agree]
    return {"games": int(len(j)), "reference_available": int(ok.sum()), "reference_missing": int((~ok).sum()),
            "reference_missing_postseason": int(((~ok) & (j.postseason.to_numpy() == 1)).sum()),
            "agree": int(agree.sum()), "disagree": int(len(bad)), "disagree_examples": bad.game_id.head(20).astype(int).tolist(),
            "disagree_all": bad.game_id.astype(int).tolist(), "unchecked_all": j.game_id[~ok].astype(int).tolist(),
            "reference": "CFBD games_teams team points (separate endpoint from games.homePoints/awayPoints)"}


def main(a=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("sport", choices=["cbb", "cfb"]); ap.add_argument("--cbb"); ap.add_argument("--cfb")
    ap.add_argument("--dates", required=True); ap.add_argument("--dataset", help="full-build parquet for outcome reconciliation"); ap.add_argument("--out", required=True)
    x = ap.parse_args(a); dates = x.dates.split(",")
    if x.sport == "cbb":
        res = {"leakage": cbb_checks(Path(x.cbb), dates)}
        if x.dataset:
            res["outcomes"] = cbb_outcomes(Path(x.cbb), pd.read_parquet(x.dataset))
    else:
        res = {"leakage": cfb_checks(Path(x.cfb), dates)}
        if x.dataset:
            res["outcomes"] = cfb_outcomes(Path(x.cfb), pd.read_parquet(x.dataset))
    Path(x.out).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps(res, default=str)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
