"""Phase 8: game-level TRAINING DATASETS for CBB, NHL and NBA (RESEARCH_ONLY). Raw and dataset rows stay out of the repository.

    python -m alpha_engine.foundation.training_sets_multi nhl --nhl-history DIR --out OUT [--write-manifest]
    python -m alpha_engine.foundation.training_sets_multi nba --raw RAWROOT --out OUT [--write-manifest]
    python -m alpha_engine.foundation.training_sets_multi cbb --cbb DIR --out OUT [--write-manifest]

NHL / NBA admit ONLY inputs whose readiness state is TRAINING_READY (acquisition_inputs.json) and only their TEAM-level columns:
player-level inputs (nhl.shot_rate, nhl.toi_trend, nba.minutes, nba.steal_block_rates) stay in their player tables, except columns that
are constant within a team-game (opponent-team quantities attached to every player row), which are lifted unchanged.
CBB has no training-ready input. Its dataset uses the Phase 8 builder `features/cbb_box.py` (BUILT + replay-checked here, NOT certified,
certified 2026-11-16 by a blind re-implementation and leakage suite, see research/certification/): `admission: CERTIFIED_TRAINING_READY`.
Checks per dataset: unique keys, both sides present, outcome sanity, missingness by season, deterministic regeneration (canonical hash
twice), a market-free walk-forward ridge diagnostic, and for CBB a truncation check (rebuild with every game after D removed; D's values
must be identical).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .training_sets import MANIFEST_DIR, canonical_hash, ready_inputs

SPLITS = {"NHL": [("train", 2008, 2019), ("validate", 2020, 2022), ("test", 2023, 2025), ("prospective", 2026, 2026)],
          "NBA": [("train", 2023, 2024), ("test", 2025, 2025), ("prospective", 2026, 2026)],
          "CBB": [("train", 2006, 2019), ("validate", 2020, 2022), ("test", 2023, 2026), ("prospective", 2027, 2027)],
          "CFB": [("train", 2014, 2019), ("validate", 2020, 2021), ("test", 2022, 2025)]}


def _split(season: int, sport: str) -> str:
    for n, a, b in SPLITS[sport]:
        if a <= season <= b:
            return n
    return "unassigned"


def _home_away(team: pd.DataFrame, games: pd.DataFrame, fcols: list[str]) -> pd.DataFrame:
    h = team.rename(columns={c: "home_" + c for c in fcols}).rename(columns={"team": "home_team"})
    a = team.rename(columns={c: "away_" + c for c in fcols}).rename(columns={"team": "away_team"})
    return games.merge(h[["game_id", "home_team"] + ["home_" + c for c in fcols]], on=["game_id", "home_team"], how="left") \
                .merge(a[["game_id", "away_team"] + ["away_" + c for c in fcols]], on=["game_id", "away_team"], how="left")


def walk_forward(d: pd.DataFrame, feats: list[str], seasons: list[int], target: str, first: int) -> dict:
    from sklearn.linear_model import Ridge
    out = {}
    for s in seasons:
        tr = d[(d.season < s) & (d.season >= first) & d[target].notna()]; te = d[(d.season == s) & d[target].notna()]
        if len(tr) < 200 or te.empty:
            continue
        X = tr[feats]; med = X.median(); mu = X.fillna(med).mean(); sd = X.fillna(med).std().replace(0, 1)
        f = lambda Z: ((Z[feats].fillna(med) - mu) / sd).fillna(0).to_numpy()
        m = Ridge(alpha=10.0).fit(f(tr), tr[target].to_numpy()); p = m.predict(f(te)); y = te[target].to_numpy()
        out[str(s)] = {"n": int(len(te)), "mae_model": round(float(np.abs(y - p).mean()), 4), "mae_constant": round(float(np.abs(y - tr[target].mean()).mean()), 4),
                       "winner_acc_model": round(float(((p > 0) == (y > 0))[y != 0].mean()), 4)}
    mean = {k: round(float(np.mean([v[k] for v in out.values()])), 4) for k in ("mae_model", "mae_constant", "winner_acc_model")} if out else {}
    return {"per_season": out, "mean": mean, "note": "market-free ridge (alpha 10) refitted per season on all earlier seasons; diagnostic only, not a model promotion"}


def _manifest(sport, d, fc, inputs, admission, sources, rights, extra, h1, h2, target, first) -> dict:
    tests = [s for n, a, b in SPLITS[sport] if n in ("test", "prospective") for s in range(a, b + 1)]
    both = d[[c for c in fc if c.startswith("home_")]].notna().any(axis=1) & d[[c for c in fc if c.startswith("away_")]].notna().any(axis=1)
    return {"schema": "training-set-manifest-1.0", "status": "RESEARCH_ONLY", "sport": sport, "admission": admission,
            "unit": "game (home perspective; home_/away_ pre-game columns)", "inputs": inputs, "n_inputs": len(inputs), "n_feature_columns": len(fc),
            "rows": int(len(d)), "rows_by_split": d.split.value_counts().sort_index().to_dict(), "seasons": [int(d.season.min()), int(d.season.max())],
            "date_range": [str(d.date.min().date()), str(d.date.max().date())], "rows_without_outcome": int(d[target].isna().sum()),
            "checks": {"keys_unique": bool(not d.duplicated("game_id").any()), "deterministic_regeneration": h1 == h2, "canonical_sha256": h1,
                       "home_and_away_features_present_share": round(float(both.mean()), 4)},
            "missing_share_by_season": {str(k): round(float(v), 4) for k, v in d.groupby("season")[fc].apply(lambda x: x.isna().mean().mean()).items()},
            "column_coverage": {c: round(float(d[c].notna().mean()), 4) for c in fc},
            "walk_forward": walk_forward(d, fc, tests, target, first), "sources": sources, "rights": rights, **extra}


# ------------------------------------------------------------------------------------------------------------------- NHL
def nhl_dataset(hist: Path) -> tuple[pd.DataFrame, dict]:
    from ..features import nhl as N, nhl_ext as E, nhl_ext3 as X3, nhl_player_ext3 as P3
    from ..features.core import Paths
    ready = set(ready_inputs("NHL"))
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="nhl_hub_")); (tmp / "nhl_hist" / "data").mkdir(parents=True); (tmp / "nhl_hist" / "data" / "history").symlink_to(hist.resolve())
    base = N.compute(N.load_raw(Paths(raw=str(tmp))))["team"]
    inputs, team = {}, base[["game_id", "team"]].copy()
    for M, t in ((N, base), (E, E.compute(E.load_raw(hist))["team"]), (X3, X3.compute(X3.load_raw(hist))["team"])):
        for s in M.specs():
            if s.catalog_id in ready and s.table == "team":
                inputs[s.catalog_id] = list(s.columns)
                team = team.merge(t[["game_id", "team"] + s.columns].drop_duplicates(["game_id", "team"]), on=["game_id", "team"], how="left")
    # nhl.pk_structure_opp: its builder emits player rows; the four pko_* columns are the OPPONENT team's PK structure, constant per team-game
    pk = [s for s in P3.specs() if s.catalog_id in ready]
    if pk:
        rawp = P3.load_raw(hist); pt = P3.compute(rawp)["team"]
        pl = rawp["players"][["game_id", "player_id", "team_id"]].drop_duplicates(["game_id", "player_id"])
        pt = pt.merge(pl.rename(columns={"player_id": "team"}), on=["game_id", "team"], how="left")
        cand = [c for c in pk[0].columns if c.startswith("pko_")]
        nu = pt.groupby(["game_id", "team_id"])[cand].nunique()
        lift = [c for c in cand if (nu[c] <= 1).all()]          # pko_combo_pp_sog60_pre mixes in the player's own PP rate: player-level, stays out
        if not lift:
            raise ValueError("no team-constant pko_* column")
        tt = pt.groupby(["game_id", "team_id"], as_index=False)[lift].first().rename(columns={"team_id": "team"})
        inputs[pk[0].catalog_id] = lift
        team = team.merge(tt, on=["game_id", "team"], how="left")
    g = pd.concat([pd.read_parquet(f) for f in sorted(hist.glob("nhl/games_*.parquet"))], ignore_index=True)
    g = g[(g.game_type == 2) & g.final].drop_duplicates("game_id")
    g = g.assign(home_team=g.home_team_id, away_team=g.away_team_id, date=pd.to_datetime(g.game_date))
    g["cutoff_utc"] = pd.to_datetime(g.start_time_et, errors="coerce").dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    g["y_home_goal_diff"] = g.home_score.astype(float) - g.away_score.astype(float); g["y_total"] = g.home_score.astype(float) + g.away_score.astype(float)
    g["y_home_win"] = (g.y_home_goal_diff > 0).astype(float); g["y_went_beyond_regulation"] = (g.last_period_type != "REG").astype(float)
    fc0 = [c for c in team.columns if c not in ("game_id", "team")]
    d = _home_away(team, g[["game_id", "season", "date", "cutoff_utc", "home_team", "away_team", "y_home_goal_diff", "y_total", "y_home_win", "y_went_beyond_regulation"]], fc0)
    d = d[d.game_id.isin(set(base.game_id))]                 # games the base builder covers (MoneyPuck team-games)
    d["split"] = [_split(int(s), "NHL") for s in d.season]
    d = d.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    return d, {"inputs": inputs, "feature_columns": ["home_" + c for c in fc0] + ["away_" + c for c in fc0]}


# ------------------------------------------------------------------------------------------------------------------- NBA
def nba_dataset(raw_root: Path) -> tuple[pd.DataFrame, dict]:
    from ..features import nba as N
    from ..features.core import Paths
    ready = set(ready_inputs("NBA"))
    out = N.compute(N.load_raw(Paths(raw=str(raw_root))))
    t = out["team"]; inputs = {}; team = t[["game_id", "team"]].copy()
    for s in N.specs():
        if s.catalog_id not in ready:
            continue
        src = out.get(s.table)
        if s.table == "team":
            inputs[s.catalog_id] = list(s.columns); team = team.merge(t[["game_id", "team"] + s.columns], on=["game_id", "team"], how="left")
        elif src is not None and "team" in src.columns:
            key = "team" if "team" in src.columns else None
            const = [c for c in s.columns if c in src.columns and src.groupby(["game_id", key])[c].nunique().le(1).mean() >= 0.999]
            if const:
                inputs[s.catalog_id + " (team-constant columns)"] = const
                team = team.merge(src.groupby(["game_id", key], as_index=False)[const].first(), on=["game_id", "team"], how="left")
    g = t[t.home == 1][["game_id", "season", "date", "start_time_utc", "team", "opp", "margin", "total"]].rename(columns={"team": "home_team", "opp": "away_team"})
    g["season"] = g.season.astype(str).str.slice(0, 4).astype(int)          # "2023-24" -> 2023 (start year)
    g["cutoff_utc"] = pd.to_datetime(g.start_time_utc, utc=True, errors="coerce")
    g["y_home_margin"] = g.margin.astype(float); g["y_total"] = g.total.astype(float); g["y_home_win"] = (g.y_home_margin > 0).astype(float)
    fc0 = [c for c in team.columns if c not in ("game_id", "team")]
    d = _home_away(team, g[["game_id", "season", "date", "cutoff_utc", "home_team", "away_team", "y_home_margin", "y_total", "y_home_win"]], fc0)
    d["split"] = [_split(int(s), "NBA") for s in d.season]
    return d.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True), {"inputs": inputs, "feature_columns": ["home_" + c for c in fc0] + ["away_" + c for c in fc0]}


# ------------------------------------------------------------------------------------------------------------------- CBB
def cbb_dataset(cbb_dir: Path, raw: dict | None = None) -> tuple[pd.DataFrame, dict]:
    from ..features import cbb_box as C
    raw = raw or C.load_raw(cbb_dir)
    t = C.compute(raw)["team"].rename(columns={"team_id": "team"})
    fc0 = C.PRE_COLS
    sc = raw["schedule"].drop_duplicates("game_id")
    g = t[t.team_home_away == "home"][["game_id", "season", "date", "team", "opponent_team_id", "neutral", "conference_competition", "pts_for", "pts_against"]]
    g = g.rename(columns={"team": "home_team", "opponent_team_id": "away_team"})
    st = sc.set_index("game_id")["start_date"] if "start_date" in sc.columns else pd.Series(dtype=str)
    g["cutoff_utc"] = pd.to_datetime(g.game_id.map(st), utc=True, errors="coerce")
    g["y_home_margin"] = (g.pts_for - g.pts_against).astype(float); g["y_total"] = (g.pts_for + g.pts_against).astype(float); g["y_home_win"] = (g.y_home_margin > 0).astype(float)
    g["neutral"] = g.neutral.astype(float); g["conference_game"] = g.conference_competition.fillna(False).astype(float)
    d = _home_away(t[["game_id", "team"] + fc0], g.drop(columns=["pts_for", "pts_against", "conference_competition"]), fc0)
    d["split"] = [_split(int(s), "CBB") for s in d.season]
    fc = ["home_" + c for c in fc0] + ["away_" + c for c in fc0] + ["neutral", "conference_game"]
    return d.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True), {"inputs": {"cbb_box (Phase 8 builder)": fc0}, "feature_columns": fc}


def cfb_dataset(cache: Path) -> tuple[pd.DataFrame, dict]:
    from ..features import cfb_cfbd as F
    out = F.compute(F.load_raw(cache)); t, g = out["team"], out["games"]
    fc0 = F.PRE + F.PRIOR
    gg = g.assign(home_team=g.homeTeam, away_team=g.awayTeam, cutoff_utc=g.start_utc, neutral=g.neutralSite.fillna(False).astype(float),
                  conference_game=g.conferenceGame.fillna(False).astype(float), postseason=(g.seasonType != "regular").astype(float))
    gg["y_home_margin"] = (g.homePoints - g.awayPoints).astype(float); gg["y_total"] = (g.homePoints + g.awayPoints).astype(float); gg["y_home_win"] = (gg.y_home_margin > 0).astype(float)
    d = _home_away(t[["game_id", "team"] + fc0], gg[["game_id", "season", "date", "cutoff_utc", "home_team", "away_team", "neutral", "conference_game", "postseason", "y_home_margin", "y_total", "y_home_win"]], fc0)
    d["split"] = [_split(int(s), "CFB") for s in d.season]
    fc = ["home_" + c for c in fc0] + ["away_" + c for c in fc0] + ["neutral", "conference_game", "postseason"]
    return d.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True), {"inputs": {"cfb_cfbd in-season (Phase 8 builder)": F.PRE, "cfb_cfbd season priors": F.PRIOR}, "feature_columns": fc}


def cbb_truncation(cbb_dir: Path, full: pd.DataFrame, dates: list[str]) -> dict:
    from ..features import cbb_box as C
    raw = C.load_raw(cbb_dir); res = {}
    for ds in dates:
        d = pd.Timestamp(ds)
        tb = raw["team_box"][pd.to_datetime(raw["team_box"].game_date) <= d]
        part, meta = cbb_dataset(cbb_dir, {"team_box": tb, "schedule": raw["schedule"]})
        fc = meta["feature_columns"]
        a = part[part.date == d].set_index("game_id")[fc].sort_index(); b = full[full.date == d].set_index("game_id").loc[a.index, fc]
        A, B = a.to_numpy(float), b.to_numpy(float)
        res[ds] = {"games": int(len(a)), "nan_pattern_equal": bool((np.isnan(A) == np.isnan(B)).all()),
                   "values_equal": bool(np.allclose(np.nan_to_num(A), np.nan_to_num(B), rtol=1e-9, atol=1e-9))}
    return {"rule": "rebuild from team-games dated <= D only (warm-start chain included); D's feature values must equal the full build", "dates": res,
            "all_equal": all(v["games"] > 0 and v["nan_pattern_equal"] and v["values_equal"] for v in res.values())}


def cfb_truncation(cache: Path, full: pd.DataFrame, dates: list[str]) -> dict:
    from ..features import cfb_cfbd as F
    import tempfile
    raw = F.load_raw(cache); res = {}
    for ds in dates:
        d = pd.Timestamp(ds)
        gd = {g["id"]: pd.Timestamp(g["startDate"]).tz_convert("America/New_York").tz_localize(None).normalize() for g in raw["games"] if g.get("startDate")}
        keep = {k for k, v in gd.items() if v <= d}
        r2 = {**raw, "games": [g for g in raw["games"] if g["id"] in keep], "adv": [a for a in raw["adv"] if a["gameId"] in keep], "drives": [x for x in raw["drives"] if x["gameId"] in keep]}
        F_load = F.load_raw
        try:
            F.load_raw = lambda c, _r=r2: _r
            part, meta = cfb_dataset(cache)
        finally:
            F.load_raw = F_load
        fc = meta["feature_columns"]
        a = part[part.date == d].set_index("game_id")[fc].sort_index(); b = full[full.date == d].set_index("game_id").loc[a.index, fc]
        A, B = a.to_numpy(float), b.to_numpy(float)
        res[ds] = {"games": int(len(a)), "nan_pattern_equal": bool((np.isnan(A) == np.isnan(B)).all()),
                   "values_equal": bool(np.allclose(np.nan_to_num(A), np.nan_to_num(B), rtol=1e-9, atol=1e-9))}
    return {"rule": "rebuild from games dated <= D only; D's feature values must equal the full build", "dates": res,
            "all_equal": all(v["games"] > 0 and v["nan_pattern_equal"] and v["values_equal"] for v in res.values())}


SOURCES = {
    "NHL": (["MoneyPuck team-game xG rows 2008-2025 (NHL-edge-finder data/history)", "NHL API games, players, team states, shots (NHL-edge-finder data/history)"],
            "MoneyPuck: free with attribution; NHL API: public endpoints; internal research only; no rows committed"),
    "NBA": (["ESPN team/player box scores, shot events, official injury reports (nba-edge-finder data/history)"], "owner archive; internal research only; no rows committed"),
    "CFB": (["CollegeFootballData (CFBD) research cache 2014-2025 in the owner's cfb-edge-finder `research-data` branch (games, advanced box without garbage time, drives, portal, returning production, recruiting, talent); betting lines, end-of-season ratings and season totals excluded"],
            "cfbd_cbbd_direct_api: CLEARED_PROVIDER_TERMS_DIRECT_API (owner-reported): derived outputs allowed, raw redistribution prohibited -> no rows committed; internal research"),
    "CBB": (["ESPN men's college basketball team box scores and schedules via SportsDataverse hoopR-mbb-data releases, re-materialised from the owner's cbb-edge-finder bronze manifest (sha256-checked)"],
            "sportsdataverse_espn_mbb_cfb: tier UNRESOLVED_INTERNAL_ONLY (unchanged); MIT covers pipeline code only, not ESPN data; internal research only; no rows committed; not commercially cleared"),
}


def build(sport: str, args) -> dict:
    sport = sport.upper()
    if sport == "NHL":
        f = lambda: nhl_dataset(Path(args.nhl_history)); target, first, adm = "y_home_goal_diff", 2008, "TRAINING_READY inputs only (team-level columns)"
    elif sport == "NBA":
        f = lambda: nba_dataset(Path(args.raw)); target, first, adm = "y_home_margin", 2023, "TRAINING_READY inputs only (team-level / team-constant columns)"
    elif sport == "CFB":
        f = lambda: cfb_dataset(Path(args.cfb)); target, first, adm = "y_home_margin", 2014, "CERTIFIED_TRAINING_READY (2026-11-16, research/certification/certification.json; drive-points defect documented)"
    else:
        f = lambda: cbb_dataset(Path(args.cbb)); target, first, adm = "y_home_margin", 2006, "CERTIFIED_TRAINING_READY (2026-11-16, research/certification/certification.json)"
    d, meta = f(); d2, _ = f()
    h1, h2 = canonical_hash(d.drop(columns=["cutoff_utc"])), canonical_hash(d2.drop(columns=["cutoff_utc"]))
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True); d.to_parquet(out / f"{sport.lower()}_game_training.parquet", index=False)
    extra = {}
    if sport == "CFB":
        extra["truncation_check"] = cfb_truncation(Path(args.cfb), d, ["2019-10-12", "2023-11-25", "2025-09-06"])
    if sport == "CBB":
        extra["truncation_check"] = cbb_truncation(Path(args.cbb), d, ["2019-02-16", "2025-01-11", "2026-11-14"])
    src, rights = SOURCES[sport]
    m = _manifest(sport, d, meta["feature_columns"], meta["inputs"], adm, src, rights, extra, h1, h2, target, first)
    if args.write_manifest:
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True); (MANIFEST_DIR / f"{sport}.json").write_text(json.dumps(m, indent=1, default=str) + "\n")
    return m


def main(a=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("sport", choices=["nhl", "nba", "cbb", "cfb"]); ap.add_argument("--cfb"); ap.add_argument("--out", required=True)
    ap.add_argument("--nhl-history"); ap.add_argument("--raw"); ap.add_argument("--cbb"); ap.add_argument("--write-manifest", action="store_true")
    x = ap.parse_args(a)
    m = build(x.sport, x)
    print(json.dumps({k: m[k] for k in ("sport", "rows", "rows_by_split", "n_inputs", "n_feature_columns", "checks")}, default=str))
    print(json.dumps(m["walk_forward"]["mean"]), json.dumps(m.get("truncation_check", {}).get("all_equal")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
