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


def run(mod, raw: dict, sport: str, tables: dict, games_table: str = "games", games_date_col: str = "gameday", quick: bool = False, avail_col: str | None = None,
        truncate_by_date: bool = False) -> dict:
    """tables: {table: (game_id_col, [content columns])}; every table here is truncated and permuted by game id.
    avail_col (optional): column of the games table holding the date a game's RESULT became known (>= games_date_col, the first-pitch date). When given, the
    check `pit_check_first_pitch_availability` runs: at each cut c, the content of every game whose result became known on/after c is permuted, and every row
    whose game's FIRST PITCH (taken from the raw table, never from the builder's own date column) is before c must be unchanged. Cuts are the three standard
    quantile cuts plus first-pitch + 1 day of the (up to 4 longest) games that started before and finished after a date boundary, so a builder that dates such a
    game by its completion, or lets its result leak into the games played in between, fails.
    truncate_by_date (opt-in, default off so earlier evidence is reproduced unchanged): the truncated raw keeps EVERY game of the games table dated before the cut, not only the
    games that have output rows. This is the documented semantics ("data on/after the cut removed"); the default proxy drops a raw game that has no output row (e.g. a game
    between two teams with no earlier games), which changes later league constants and makes a correct builder fail."""
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
        if truncate_by_date:
            gt_ = raw[games_table]; early = early | set(gt_.loc[pd.to_datetime(gt_[games_date_col]) < cut, tables[games_table][0]])
        tr = mod.compute(cut_tables({**raw, games_table: raw[games_table][pd.to_datetime(raw[games_table][games_date_col]) < cut]}, early))["team"]
        pert = mod.compute(scramble(raw, late, seed))["team"]
        for s in specs:
            T = res[s.catalog_id]["tests"]
            T.setdefault("truncation", []).append({"q": q, "cut": str(cut.date()), "n_pre_rows": int(sel.sum()), "bad_columns": (b := _cmp(base, tr, s.columns, sel)), "ok": not b})
            T.setdefault("perturbation", []).append({"q": q, "seed": seed, "cut": str(cut.date()), "n_late_games": len(late), "bad_columns": (b2 := _cmp(base, pert, s.columns, sel)), "ok": not b2})
    if avail_col is not None:
        gt = raw[games_table]; fp = pd.to_datetime(gt[games_date_col]); av = pd.to_datetime(gt[avail_col]); gidc = tables[games_table][0]
        fp_by = pd.Series(fp.to_numpy(), index=gt[gidc].to_numpy()); av_by = pd.Series(av.to_numpy(), index=gt[gidc].to_numpy())
        row_fp = base.game_id.map(fp_by); strad = gt[(av - fp).dt.days >= 1].assign(_gap=(av - fp).dt.days).sort_values(["_gap", gidc], ascending=[False, True]).head(4)
        cuts = [(f"q{q}", pd.Timestamp(dates.quantile(q)).normalize()) for q, _ in (CUTS[:1] if quick else CUTS)]
        cuts += [(f"straddle:{int(r[gidc])}", pd.Timestamp(r[games_date_col]).normalize() + pd.Timedelta(days=1)) for _, r in strad.iterrows()]
        runs = []
        for i, (lab, c) in enumerate(cuts):
            late_av = set(av_by.index[(av_by >= c).to_numpy()]); sel_fp = (row_fp < c).to_numpy()
            pa = mod.compute(scramble(raw, late_av, 900 + i))["team"]
            runs.append({"cut": str(c.date()), "label": lab, "n_rows_first_pitch_before_cut": int(sel_fp.sum()), "n_games_permuted": len(late_av), "bad_columns_by_input": {s.catalog_id: _cmp(base, pa, s.columns, sel_fp) for s in specs}})
        for s in specs:
            rr = [{"cut": x["cut"], "label": x["label"], "n_rows": x["n_rows_first_pitch_before_cut"], "n_games_permuted": x["n_games_permuted"], "bad_columns": x["bad_columns_by_input"][s.catalog_id]} for x in runs]
            res[s.catalog_id]["tests"]["pit_check_first_pitch_availability"] = {"n_straddling_games": int(((av - fp).dt.days >= 1).sum()), "cuts": rr, "ok": bool(rr) and all(not x["bad_columns"] for x in rr)}
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
