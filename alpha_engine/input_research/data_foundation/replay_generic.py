"""Generic independent replay for game-keyed extension builders (RESEARCH_ONLY).

A builder module provides compute(raw)->{"team": df[game_id, team, date, season, <feature cols>]} and specs(). The caller names the GAME-KEYED raw tables and the columns of each that carry game content.
Tests (all must pass; fail-closed in verified_coverage): determinism; coverage; truncation at 3 date cuts (data on/after the cut removed -> earlier features identical); future perturbation at 3 cuts with NEW seeds
(content columns of every game on/after the cut permuted -> earlier features identical); own-game (one mid date's content permuted -> features dated on/before it identical); non-vacuity (permuting one EARLY
block must move later features, per input, else the perturbation tests prove nothing).
    python -m alpha_engine.input_research.data_foundation.replay_generic <module> <sport> <out.json> <arg ...>   (args go to module.load_raw)
"""
from __future__ import annotations

import importlib
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
CUTS = ((0.55, 111), (0.75, 222), (0.92, 333))


def _same(a, b) -> bool:
    return bool(np.isclose(a.to_numpy().astype(float), b.to_numpy().astype(float), rtol=1e-9, atol=1e-9, equal_nan=True).all())


def _cmp(base, new, cols, sel) -> list[str]:
    n = new.set_index(["game_id", "team"]).reindex(base.set_index(["game_id", "team"]).index).reset_index(drop=True)
    return [c for c in cols if not _same(base.loc[sel, c].reset_index(drop=True), n.loc[sel, c].reset_index(drop=True))]


def _perm(df, mask, cols, rng):
    d = df.copy(); ix = np.flatnonzero(mask)
    for c in cols:
        if c not in d: continue
        v = d[c].to_numpy(dtype=object, copy=True); v[ix] = rng.permutation(v[ix]); col = pd.Series(v, index=d.index)
        try: col = col.astype(df[c].dtype)
        except (TypeError, ValueError): pass
        d[c] = col
    return d


def run(mod, raw: dict, sport: str, tables: dict, games_table: str = "games", games_date_col: str = "gameday", quick: bool = False) -> dict:
    """tables: {table: (game_id_col, [content columns])}; every table here is truncated and permuted by game id."""
    t0 = time.time(); specs = mod.specs(); base = mod.compute(raw)["team"]
    res = {s.catalog_id: {"sport": sport, "id": s.catalog_id, "table": "team", "level_claimed": s.level, "pit_claimed": s.pit, "missing_claimed": list(s.missing), "raw_claimed": list(s.raw), "columns": list(s.columns), "tests": {"vintage_dependence": {}}} for s in specs}
    again = mod.compute(raw)["team"]; allsel = np.ones(len(base), bool)
    for s in specs:
        T = res[s.catalog_id]["tests"]; T["determinism"] = {"ok": not _cmp(base, again, s.columns, allsel)}
        cov = {c: float(base[c].notna().mean()) for c in s.columns}; okr = base[base[s.columns].notna().any(axis=1)]
        T["coverage_replay"] = {"present": bool(len(okr)), "min_coverage_new": round(min(cov.values()), 4), "max_abs_coverage_drift": 0.0, "constant_columns": [c for c in s.columns if base[c].nunique() <= 1], "first_new": str(okr.date.min().date()), "last_new": str(okr.date.max().date()),
                                "columns": {c: {"coverage_new": round(v, 4)} for c, v in cov.items()}, "n_rows_with_values": int(len(okr))}
    dates = base.date.sort_values().reset_index(drop=True); gdate = base.drop_duplicates("game_id").set_index("game_id").date

    def cut_tables(r, keep_ids):
        o = dict(r)
        for tb, (gc, _) in tables.items(): o[tb] = r[tb][r[tb][gc].isin(keep_ids)]
        return o

    def scramble(r, late_ids, seed):
        if hasattr(mod, "perturb"):     # builders whose outcome lives in WHICH entity won (tennis) supply their own role-preserving perturbation: the row universe (game_id, entity) must not change
            return mod.perturb(r, late_ids, seed)
        o = dict(r); rng = np.random.default_rng(seed)
        for tb, (gc, cols) in tables.items(): o[tb] = _perm(r[tb], r[tb][gc].isin(late_ids).to_numpy(), cols, rng)
        return o

    for q, seed in (CUTS[:1] if quick else CUTS):
        cut = pd.Timestamp(dates.quantile(q)).normalize(); sel = (base.date < cut).to_numpy(); early = set(base.loc[base.date < cut, "game_id"]); late = set(base.game_id) - early
        tr = mod.compute(cut_tables({**raw, games_table: raw[games_table][pd.to_datetime(raw[games_table][games_date_col]) < cut]}, early))["team"]
        pert = mod.compute(scramble(raw, late, seed))["team"]
        for s in specs:
            T = res[s.catalog_id]["tests"]
            T.setdefault("truncation", []).append({"q": q, "cut": str(cut.date()), "n_pre_rows": int(sel.sum()), "bad_columns": (b := _cmp(base, tr, s.columns, sel)), "ok": not b})
            T.setdefault("perturbation", []).append({"q": q, "seed": seed, "cut": str(cut.date()), "n_late_games": len(late), "bad_columns": (b2 := _cmp(base, pert, s.columns, sel)), "ok": not b2})
    dmid = dates[dates >= dates.quantile(0.5)].min().normalize(); gids = set(base.loc[base.date.dt.normalize() == dmid, "game_id"])
    own = mod.compute(scramble(raw, gids, 404))["team"]; sel = (base.date <= dmid).to_numpy()
    for s in specs:
        b = _cmp(base, own, s.columns, sel); res[s.catalog_id]["tests"]["own_game"] = {"date": str(dmid.date()), "n_rows_on_date": int((base.date.dt.normalize() == dmid).sum()), "bad_columns": b, "ok": not b}
    # non-vacuity: permute ONE early block (a mid season) -> later features of the same inputs must move
    yr = int(base.season.median()); blk = set(base.loc[base.season == yr, "game_id"]); mv = mod.compute(mod.perturb_nv(raw, blk, 707) if hasattr(mod, "perturb_nv") else scramble(raw, blk, 707))["team"]
    for s in specs:
        moved = [c for c in s.columns if not _same(base[c].fillna(-1), mv[c].fillna(-1))]
        res[s.catalog_id]["tests"]["pit_check_perturbation_not_vacuous"] = {"block_season": yr, "n_block_games": len(blk), "columns_that_moved": moved, "ok": len(moved) == len(s.columns)}
    return {"sport": sport, "kind": "replay_ext", "seconds": round(time.time() - t0), "quick": quick, "raw_rows": {k: int(len(v)) for k, v in raw.items()}, "inputs": res}
