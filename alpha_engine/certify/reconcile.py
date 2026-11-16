"""Reconcile the Phase 8 training datasets against the per-game completeness ledgers of sift-alpha PR #80 (RESEARCH_ONLY).

Reads PR #80's `research/game_completeness/<SPORT>/games.csv.gz` (identifiers and status letters only, read from its branch,
never modified) and each rebuilt training dataset. Every FINAL game in the ledger, and every dataset game, is put in exactly
one class, so differences of denominator or date range are not reported as missing records:

  IN_DATASET              in both
  OUTSIDE_SEASON_RANGE    ledger season outside the dataset's declared seasons (scope, not a gap)
  AFTER_BUILD_VINTAGE     ledger date later than the dataset's last game date (build vintage, not a gap)
  OUT_OF_SCOPE_GAME_TYPE  game type the dataset excludes by design (NHL: non-regular-season ids; NBA: play-in / playoffs,
                          inferred because every regular-season game is present and all such games fall in Apr-Jun)
  SOURCE_NOT_COMPLETE     the source family the builder needs is not COMPLETE in the ledger (a real source gap)
  BUILDER_EXCLUDED        source COMPLETE in the ledger but the builder dropped the game (a builder filter; listed for review)
  DATASET_ONLY            in the dataset but not a FINAL ledger game (the two denominators differ)

    python -m alpha_engine.certify.reconcile --ledgers DIR --datasets DIR --out OUT.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

# sport -> (dataset file, source family in the ledger the builder needs, declared seasons from the manifest)
SPORTS = {
    "NHL": ("nhl_game_training.parquet", "shot_xg", None),
    "NBA": ("nba_game_training.parquet", "team_box", None),
    "CBB": ("cbb_game_training.parquet", "team_box", None),
    "CFB": ("cfb_game_training.parquet", "final_score", None),
}


def _season_key(sport: str, s: str) -> int:
    return int(str(s)[:4]) if sport != "NBA" else int(str(s)[:4])


def reconcile(sport: str, ledger: pd.DataFrame, d: pd.DataFrame, family: str, per_game: bool = False):
    L = ledger[ledger.state == "FINAL"].copy()
    L["gid"] = L.game_id.astype(str); d = d.assign(gid=d.game_id.astype(str))
    L["season_k"] = [_season_key(sport, s) for s in L.season]; L["date"] = pd.to_datetime(L.date)
    smin, smax = int(d.season.min()), int(d.season.max()); dmax = pd.to_datetime(d.date).max()
    ids = set(d.gid)
    cls = []
    for r in L.itertuples(index=False):
        if r.gid in ids:
            c = "IN_DATASET"
        elif not (smin <= r.season_k <= smax):
            c = "OUTSIDE_SEASON_RANGE"
        elif sport == "NHL" and r.gid[4:6] != "02":
            c = "OUT_OF_SCOPE_GAME_TYPE"
        elif r.date > dmax:
            c = "AFTER_BUILD_VINTAGE"
        elif getattr(r, family) != "C":
            c = "SOURCE_NOT_COMPLETE"
        elif sport == "NBA" and r.date.month in (4, 5, 6):
            c = "OUT_OF_SCOPE_GAME_TYPE"          # NBA builder is regular season only; every Apr-Jun game it lacks is play-in / playoffs
        else:
            c = "BUILDER_EXCLUDED"
        cls.append(c)
    L["cls"] = cls
    if per_game:
        return pd.Series(L.cls.to_numpy(), index=L.gid)
    only = d[~d.gid.isin(set(L.gid))]
    by_season = {str(k): v for k, v in L.groupby("season_k").cls.value_counts().unstack(fill_value=0).to_dict("index").items()}
    by_season = {k: {c: int(n) for c, n in v.items() if n} for k, v in by_season.items()}
    for s, n in only.groupby("season").size().items():
        by_season.setdefault(str(int(s)), {})["DATASET_ONLY"] = int(n)
    fam_cols = [c for c in L.columns if c not in ("season", "date", "game_id", "state", "overall", "gid", "season_k", "cls")]
    in_ds = L[L.cls == "IN_DATASET"]
    stat_fam = {f: {k: int(v) for k, v in in_ds[f].value_counts().items()} for f in fam_cols}
    return {"ledger_final_games": int(len(L)), "dataset_games": int(len(d)),
            "classes": {k: int(v) for k, v in L.cls.value_counts().items()} | {"DATASET_ONLY": int(len(only))},
            "by_season": dict(sorted(by_season.items())),
            "builder_excluded_game_ids": L[L.cls == "BUILDER_EXCLUDED"].gid.head(500).tolist(),
            "source_not_complete_game_ids": L[L.cls == "SOURCE_NOT_COMPLETE"].gid.head(500).tolist(),
            "dataset_only_game_ids": only.gid.head(200).tolist(),
            "ledger_status_of_dataset_games_by_family": stat_fam,
            "needed_family": family, "dataset_seasons": [smin, smax], "dataset_last_date": str(dmax.date())}


def main(x=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--ledgers", required=True); ap.add_argument("--datasets", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(x); out = {}
    for s, (f, fam, _) in SPORTS.items():
        p = Path(a.datasets) / f
        if not p.exists():
            continue
        out[s] = reconcile(s, pd.read_csv(Path(a.ledgers) / f"{s}.games.csv.gz", dtype=str), pd.read_parquet(p), fam)
        print(s, out[s]["classes"])
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
