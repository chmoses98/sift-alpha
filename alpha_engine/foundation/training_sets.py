"""Phase 7: per-sport TRAINING DATASETS assembled only from training-ready inputs (RESEARCH_ONLY).

    python -m alpha_engine.foundation.training_sets nfl --raw RAW_NFL_DIR --out OUT_DIR [--write-manifest]

What a dataset is here: one row per game (home perspective) with the pre-game columns of every input whose recorded readiness state is TRAINING_READY in
`research/data_foundation_ops/acquisition_inputs.json` (nothing else is admitted), the prediction cutoff, the outcomes (kept in separate `y_` columns, never features), and a chronological split.
Checks: unique keys, both team rows present, outcomes reconciled against the play-by-play final score, feature missingness by season, deterministic regeneration (the dataset is built twice and
the canonical hashes must agree), and a market-free walk-forward check (ridge fitted on earlier seasons only; no betting line is used anywhere).
Raw rows and dataset rows stay OUT of the repository (they live in OUT_DIR); only the manifest (counts, hashes, missingness, metrics) is committed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ACQ = ROOT / "research/data_foundation_ops/acquisition_inputs.json"
MANIFEST_DIR = ROOT / "research/data_foundation_ops/training_sets"
LEGACY_FIRST = 2010
SPLITS = {"NFL": [("train", 1999, 2018), ("validate", 2019, 2021), ("test", 2022, 2025), ("prospective", 2026, 2026)]}


def ready_inputs(sport: str) -> list[str]:
    a = json.loads(ACQ.read_text())["inputs"]
    return sorted(k.split(":", 1)[1] for k, v in a.items() if v["s"] == sport and v["tr"]["state"] == "TRAINING_READY")


def canonical_hash(df: pd.DataFrame) -> str:
    """Hash of a canonical text rendering (sorted rows/columns, 12 significant digits): independent of parquet library versions."""
    d = df.sort_values(list(df.columns[:2]), kind="mergesort")[sorted(df.columns)]
    txt = d.to_csv(index=False, float_format="%.12g", na_rep="NA", date_format="%Y-%m-%dT%H:%M:%S")
    return hashlib.sha256(txt.encode()).hexdigest()


def _split(season: int, sport: str) -> str:
    for name, a, b in SPLITS[sport]:
        if a <= season <= b:
            return name
    return "unassigned"


# ---------------------------------------------------------------------------------------------------------------- NFL
def nfl_team_features(raw_dir: Path, ready: list[str]) -> tuple[pd.DataFrame, dict]:
    from ..features import nfl as N, nfl_pbp_ext3 as X3
    from ..features.core import Paths
    cols_by_input = {}
    # the legacy builder was replayed and certified on nflverse pbp 2010-2026 (its docstring and replay/NFL.json); feed it exactly that range
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="nfl_legacy_")); (tmp / "pbp").mkdir()
    for f in sorted((raw_dir / "pbp").glob("pbp_*.parquet")):
        if int(f.stem.split("_")[1]) >= LEGACY_FIRST:
            (tmp / "pbp" / f.name).symlink_to(f.resolve())
    (tmp / "games.csv").symlink_to((raw_dir / "games.csv").resolve())
    base = N.compute(N.load_raw(Paths(nfl=str(tmp))))["team"]
    if base.duplicated(["game_id", "team"]).any():
        raise ValueError("legacy NFL builder produced duplicate (game_id, team) rows")
    for s in N.specs():
        if s.catalog_id in ready and s.pit != "final_postgame":
            cols_by_input[s.catalog_id] = list(s.columns)
    feats = base[["game_id", "team"] + sorted({c for v in cols_by_input.values() for c in v})].copy()
    ext = [s for s in X3.specs() if s.catalog_id in ready]
    if ext:
        t3 = X3.compute(X3.load_raw(raw_dir / "pbp", raw_dir / "games.csv", raw_dir / "players.parquet"))["team"]
        for s in ext:
            cols_by_input[s.catalog_id] = list(s.columns)
        feats = feats.merge(t3[["game_id", "team"] + [c for s in ext for c in s.columns]], on=["game_id", "team"], how="outer")
    return feats, cols_by_input


def nfl_dataset(raw_dir: Path) -> tuple[pd.DataFrame, dict]:
    ready = ready_inputs("NFL")
    feats, cols_by_input = nfl_team_features(raw_dir, ready)
    g = pd.read_csv(raw_dir / "games.csv")
    g = g[g.season >= 1999].copy()
    from ..features.nfl_ext import TEAM_FIX
    g["home_team"] = g.home_team.replace(TEAM_FIX); g["away_team"] = g.away_team.replace(TEAM_FIX)
    t = g.gametime.fillna("13:00").astype(str).str.slice(0, 5)
    g["cutoff_utc"] = pd.to_datetime(g.gameday + " " + t, errors="coerce").dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    fcols = [c for c in feats.columns if c not in ("game_id", "team")]
    h = feats.rename(columns={c: "home_" + c for c in fcols}).rename(columns={"team": "home_team"})
    a = feats.rename(columns={c: "away_" + c for c in fcols}).rename(columns={"team": "away_team"})
    d = g[["game_id", "season", "week", "game_type", "gameday", "cutoff_utc", "home_team", "away_team", "home_score", "away_score"]].merge(h, on=["game_id", "home_team"], how="left").merge(a, on=["game_id", "away_team"], how="left")
    d["y_home_margin"] = d.home_score - d.away_score; d["y_total"] = d.home_score + d.away_score; d["y_home_win"] = np.where(d.y_home_margin.notna(), (d.y_home_margin > 0).astype(float), np.nan)
    d = d.drop(columns=["home_score", "away_score"])
    d["split"] = [_split(int(s), "NFL") for s in d.season]
    d = d[d.y_home_margin.notna() | (d.season == 2026)].sort_values(["gameday", "game_id"], kind="mergesort").reset_index(drop=True)
    meta = {"inputs": cols_by_input, "feature_columns": [c for c in d.columns if c.startswith(("home_", "away_")) and c not in ("home_team", "away_team")]}
    return d, meta


def nfl_upcoming_dataset(raw_dir: Path, truncate_at: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Rows for SCHEDULED games (each team's next game) with exactly the training set's feature columns, from completed games only.

    truncate_at (YYYY-MM-DD, testing/verification): pretend every game on/after that date is unplayed (scores and plays hidden)."""
    from ..features import nfl as N, nfl_pbp_ext3 as X3, nfl_upcoming as U
    from ..features.core import Paths
    from ..features.nfl_ext import TEAM_FIX
    import tempfile
    ready = ready_inputs("NFL")
    tmp = Path(tempfile.mkdtemp(prefix="nfl_legacy_up_")); (tmp / "pbp").mkdir()
    for f in sorted((raw_dir / "pbp").glob("pbp_*.parquet")):
        if int(f.stem.split("_")[1]) >= LEGACY_FIRST:
            (tmp / "pbp" / f.name).symlink_to(f.resolve())
    (tmp / "games.csv").symlink_to((raw_dir / "games.csv").resolve())
    raw_l = N.load_raw(Paths(nfl=str(tmp)))
    raw_x = X3.load_raw(raw_dir / "pbp", raw_dir / "games.csv", raw_dir / "players.parquet")
    if truncate_at:
        d = pd.Timestamp(truncate_at)
        raw_l, _ = U.truncate(raw_l, raw_l["games"], d)
        raw_x, _ = U.truncate(raw_x, raw_x["games"], d)
    sched = U.next_games(raw_l["games"])
    if truncate_at:
        sched = sched[sched.date == pd.Timestamp(truncate_at)].reset_index(drop=True)
    cols_by_input = {}
    for s in N.specs():
        if s.catalog_id in ready and s.pit != "final_postgame":
            cols_by_input[s.catalog_id] = list(s.columns)
    lt = U.legacy_scheduled(raw_l, sched)
    if lt.duplicated(["game_id", "team"]).any():
        raise ValueError("scheduled legacy rows duplicated")
    feats = lt[["game_id", "team"] + sorted({c for v in cols_by_input.values() for c in v})].copy()
    ext = [s for s in X3.specs() if s.catalog_id in ready]
    if ext:
        x = U.ext3_scheduled(raw_x, sched)
        for s in ext:
            cols_by_input[s.catalog_id] = list(s.columns)
        feats = feats.merge(x[["game_id", "team"] + [c for s in ext for c in s.columns]], on=["game_id", "team"], how="outer")
    g = sched.copy()
    g["home_team"] = g.home_team.replace(TEAM_FIX); g["away_team"] = g.away_team.replace(TEAM_FIX)
    t = g.gameday.astype(str) + " " + pd.read_csv(raw_dir / "games.csv", usecols=["game_id", "gametime"]).set_index("game_id").gametime.reindex(g.game_id).fillna("13:00").astype(str).str.slice(0, 5).to_numpy()
    g["cutoff_utc"] = pd.to_datetime(t, errors="coerce").dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    fcols = [c for c in feats.columns if c not in ("game_id", "team")]
    h = feats.rename(columns={c: "home_" + c for c in fcols}).rename(columns={"team": "home_team"})
    a = feats.rename(columns={c: "away_" + c for c in fcols}).rename(columns={"team": "away_team"})
    dd = g[["game_id", "season", "week", "game_type", "gameday", "cutoff_utc", "home_team", "away_team"]].merge(h, on=["game_id", "home_team"], how="left").merge(a, on=["game_id", "away_team"], how="left")
    st = U.staleness(raw_l["games"], raw_l["pbp"], pd.Timestamp(sched.date.min()) if len(sched) else pd.Timestamp.max)
    stale = U.stale_teams(raw_l["games"], raw_l["pbp"], sched)
    st["stale_games"] = stale
    dd["inputs_complete"] = ~dd.game_id.isin(set(stale))
    dd["features_asof_last_completed_game"] = str(pd.to_datetime(raw_l["games"][raw_l["games"].home_score.notna()].gameday).max().date())
    dd["split"] = "upcoming"
    # a row is a PREGAME prediction only if it was built before kickoff; rows of games already under way keep their (still
    # completed-games-only) features but are flagged so no consumer mistakes them for a pregame forecast
    built = pd.Timestamp(truncate_at, tz="UTC") if truncate_at else pd.Timestamp.now(tz="UTC")
    dd["built_at_utc"] = built.isoformat()
    dd["kickoff_passed_at_build"] = (dd.cutoff_utc <= built).fillna(True) if not truncate_at else False
    meta = {"inputs": cols_by_input, "feature_columns": [c for c in dd.columns if c.startswith(("home_", "away_")) and c not in ("home_team", "away_team")], "staleness": st}
    return dd.sort_values(["gameday", "game_id"], kind="mergesort").reset_index(drop=True), meta


def nfl_upcoming_equivalence(raw_dir: Path, dates: list[str], full: pd.DataFrame | None = None) -> dict:
    """For past dates D: hide D onward, score D's games as scheduled, compare to the full build. Exact match required (rtol=1e-9)."""
    if full is None:
        full, _ = nfl_dataset(raw_dir)
    res = {}
    for d in dates:
        up, meta = nfl_upcoming_dataset(raw_dir, truncate_at=d)
        fc = meta["feature_columns"]
        ref = full.set_index("game_id").loc[up.game_id, fc]
        got = up.set_index("game_id")[fc]
        a, b = ref.to_numpy(float), got.to_numpy(float)
        same_nan = bool((np.isnan(a) == np.isnan(b)).all())
        close = bool(np.allclose(np.nan_to_num(a, nan=0.0), np.nan_to_num(b, nan=0.0), rtol=1e-9, atol=1e-9))
        res[d] = {"games": int(len(up)), "columns": len(fc), "nan_pattern_equal": same_nan, "values_equal": close,
                  "max_abs_diff": float(np.nanmax(np.abs(a - b))) if np.isfinite(a - b).any() else 0.0}
    return {"dates": res, "all_equal": all(v["nan_pattern_equal"] and v["values_equal"] and v["games"] > 0 for v in res.values())}


def nfl_reconcile(d: pd.DataFrame, raw_dir: Path) -> dict:
    """Schedule outcome vs the last play-by-play score of the game."""
    import glob
    parts = [pd.read_parquet(f, columns=["game_id", "total_home_score", "total_away_score"]) for f in sorted(glob.glob(str(raw_dir / "pbp/pbp_*.parquet")))]
    p = pd.concat(parts, ignore_index=True).groupby("game_id").agg(h=("total_home_score", "max"), a=("total_away_score", "max")).reset_index()
    j = d[d.y_home_margin.notna()][["game_id", "y_home_margin", "y_total"]].merge(p, on="game_id", how="left")
    have = j.h.notna()
    bad = have & ((j.h - j.a != j.y_home_margin) | (j.h + j.a != j.y_total))
    return {"games_with_outcome": int(len(j)), "games_with_pbp": int(have.sum()), "outcome_mismatches": int(bad.sum()), "mismatch_game_ids": j.loc[bad, "game_id"].head(20).tolist()}


def walk_forward(d: pd.DataFrame, feats: list[str], seasons: list[int], target: str = "y_home_margin", alpha: float = 10.0) -> dict:
    """Ridge on standardised features, refitted per test season on ALL earlier seasons (>= first season with features). NaN -> training median. No market input."""
    from sklearn.linear_model import Ridge
    out = {}
    for s in seasons:
        tr = d[(d.season < s) & d[target].notna() & (d.season >= 2006)]; te = d[(d.season == s) & d[target].notna()]
        if tr.empty or te.empty:
            continue
        X = tr[feats]; med = X.median(); mu = X.fillna(med).mean(); sd = X.fillna(med).std().replace(0, 1)
        f = lambda Z: ((Z[feats].fillna(med) - mu) / sd).to_numpy()
        m = Ridge(alpha=alpha).fit(f(tr), tr[target].to_numpy())
        pred = m.predict(f(te)); base = np.full(len(te), tr[target].mean())
        y = te[target].to_numpy()
        out[str(s)] = {"n": int(len(te)), "mae_model": round(float(np.abs(y - pred).mean()), 4), "mae_constant": round(float(np.abs(y - base).mean()), 4),
                       "winner_acc_model": round(float(((pred > 0) == (y > 0))[y != 0].mean()), 4)}
    tot = {k: round(float(np.mean([v[k] for v in out.values()])), 4) for k in ("mae_model", "mae_constant", "winner_acc_model")} if out else {}
    return {"per_season": out, "mean": tot}


def build_nfl(raw_dir: Path, out_dir: Path, write_manifest: bool) -> dict:
    d, meta = nfl_dataset(raw_dir)
    d2, _ = nfl_dataset(raw_dir)
    h1, h2 = canonical_hash(d), canonical_hash(d2)
    out_dir.mkdir(parents=True, exist_ok=True); d.to_parquet(out_dir / "nfl_game_training.parquet", index=False)
    fc = meta["feature_columns"]
    keys_unique = not d.duplicated("game_id").any()
    miss = d.groupby("season")[fc].apply(lambda x: float(x.isna().mean().mean())).round(4).to_dict()
    col_cov = {c: round(float(d[c].notna().mean()), 4) for c in fc}
    legacy = [c for c in fc if not c.split("_", 1)[1].startswith(("prs_",))]
    new = [c for c in fc if c not in legacy]
    test_seasons = [s for n, a, b in SPLITS["NFL"] if n in ("test", "prospective") for s in range(a, b + 1)]
    wf_all = walk_forward(d, fc, test_seasons); wf_legacy = walk_forward(d, legacy, test_seasons)
    m = {"schema": "training-set-manifest-1.0", "status": "RESEARCH_ONLY", "sport": "NFL", "unit": "game (home perspective; home_/away_ pre-game columns)",
         "prediction_cutoff": "scheduled kickoff (gameday + gametime, America/New_York -> UTC); every feature uses games dated strictly before the game date (replay-gated per input)",
         "admission_rule": "only inputs whose readiness state is TRAINING_READY in acquisition_inputs.json", "inputs": meta["inputs"], "n_inputs": len(meta["inputs"]), "n_feature_columns": len(fc),
         "rows": int(len(d)), "rows_by_split": d.split.value_counts().sort_index().to_dict(), "seasons": [int(d.season.min()), int(d.season.max())],
         "latest_game_date": str(d[d.y_home_margin.notna()].gameday.max()), "rows_without_outcome_2026": int(d.y_home_margin.isna().sum()),
         "outcomes": ["y_home_margin", "y_total", "y_home_win"], "outcome_reconciliation": nfl_reconcile(d, raw_dir),
         "checks": {"keys_unique": keys_unique, "deterministic_regeneration": h1 == h2, "canonical_sha256": h1,
                    "home_and_away_features_present_share": round(float(d[[c for c in fc if c.startswith("home_")]].notna().any(axis=1).mul(d[[c for c in fc if c.startswith("away_")]].notna().any(axis=1)).mean()), 4)},
         "missing_share_by_season": {str(k): v for k, v in miss.items()}, "column_coverage": col_cov,
         "walk_forward_home_margin": {"note": "market-free ridge (alpha 10) refitted per season on all earlier seasons from 2006; diagnostic only, not a model promotion", "all_ready_inputs": wf_all, "legacy_ready_inputs_only": wf_legacy, "new_columns": new},
         "sources": ["nflverse play_by_play 1999-2026 (github.com/nflverse/nflverse-data releases)", "nflverse schedule games.csv", "nflverse players"],
         "rights": "nflverse: WRAPPER_LICENCE_UPSTREAM_CAVEAT (rights_registry.json); internal research only; no rows committed"}
    if write_manifest:
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True); (MANIFEST_DIR / "NFL.json").write_text(json.dumps(m, indent=1, default=str) + "\n")
    return m


EQUIVALENCE_DATES = ["2026-11-08", "2026-11-09", "2026-11-12", "2026-10-18", "2025-11-16", "2024-12-01"]


def build_nfl_upcoming(raw_dir: Path, out_dir: Path, write_manifest: bool) -> dict:
    """Scheduled-game rows + the truncation-equivalence evidence that they equal what the completed-game builders produce."""
    full, _ = nfl_dataset(raw_dir)
    eq = nfl_upcoming_equivalence(raw_dir, EQUIVALENCE_DATES, full=full)
    up, um = nfl_upcoming_dataset(raw_dir)
    out_dir.mkdir(parents=True, exist_ok=True); up.to_parquet(out_dir / "nfl_upcoming.parquet", index=False)
    fc = um["feature_columns"]
    m = {"schema": "upcoming-feature-manifest-1.0", "status": "RESEARCH_ONLY", "sport": "NFL",
         "what": "pre-game feature rows for each team's NEXT scheduled game, same 70 columns as the training set, computed from completed games only",
         "method": "stub team-game rows appended after every completed game (legacy builder `_pre_features`); ext3 `_pass_run_split` evaluated at the scheduled date; see features/nfl_upcoming.py",
         "equivalence_check": {"rule": "hide every game on/after D, score D's games as scheduled, require exact equality with the full build (rtol=atol=1e-9, identical NaN pattern)", **eq},
         "built_at_utc": str(up.built_at_utc.iloc[0]) if len(up) else None, "features_asof_last_completed_game": str(up.features_asof_last_completed_game.iloc[0]) if len(up) else None,
         "rows": int(len(up)), "rows_pregame_at_build": int((~up.kickoff_passed_at_build).sum()) if len(up) else 0,
         "games": up[["game_id", "gameday", "home_team", "away_team", "kickoff_passed_at_build", "inputs_complete"]].astype(str).values.tolist(),
         "rows_inputs_complete": int(up.inputs_complete.sum()) if len(up) else 0,
         "feature_coverage": round(float(up[fc].notna().mean().mean()), 4) if len(up) else None, "inputs_complete": bool(up.inputs_complete.all()) if len(up) else None,
         "staleness": um["staleness"], "n_feature_columns": len(fc),
         "limits": ["features only: no model is fitted or promoted here", "games already under way at build time are flagged kickoff_passed_at_build and are NOT pregame forecasts",
                    "availability (injury report) and weather forecast inputs are not training-ready and are not in these columns"]}
    if write_manifest:
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True); (MANIFEST_DIR / "NFL_upcoming.json").write_text(json.dumps(m, indent=1, default=str) + "\n")
    return m


def main(a=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("sport"); ap.add_argument("--raw", required=True); ap.add_argument("--out", required=True); ap.add_argument("--write-manifest", action="store_true")
    x = ap.parse_args(a)
    if x.sport.lower() == "nfl-upcoming":
        m = build_nfl_upcoming(Path(x.raw), Path(x.out), x.write_manifest)
        print(json.dumps({k: m[k] for k in ("rows", "rows_pregame_at_build", "feature_coverage", "inputs_complete")}), json.dumps(m["equivalence_check"]["all_equal"]))
        return 0 if m["equivalence_check"]["all_equal"] else 1
    if x.sport.lower() != "nfl":
        raise SystemExit("implemented: nfl, nfl-upcoming (NHL/NBA/CBB: alpha_engine.foundation.training_sets_multi)")
    m = build_nfl(Path(x.raw), Path(x.out), x.write_manifest)
    print(json.dumps({k: m[k] for k in ("rows", "rows_by_split", "n_inputs", "n_feature_columns", "outcome_reconciliation", "checks")}, default=str)[:1500])
    print(json.dumps(m["walk_forward_home_margin"]["all_ready_inputs"]["mean"]), json.dumps(m["walk_forward_home_margin"]["legacy_ready_inputs_only"]["mean"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
