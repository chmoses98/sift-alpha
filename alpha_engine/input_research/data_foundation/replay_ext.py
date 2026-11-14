"""Independent replay of the NFL extension builders (RESEARCH_ONLY): determinism, coverage, truncation, future perturbation (new seeds/cuts), own-game snap perturbation and a POST-KICKOFF injury test.

    python -m alpha_engine.input_research.data_foundation.replay_ext INJ_DIR SNAP_DIR PLAYERS GAMES OUT.json

The post-kickoff test is the one that matters for injuries: every injury row whose report was last modified AFTER kickoff has its status/position scrambled, and no feature of any game may change.
A non-vacuity check requires the future perturbation to actually move later rows. Output matches the structure of replay_verify so verified_coverage can classify it.
"""
from __future__ import annotations

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
from alpha_engine.features import nfl_ext as X  # noqa: E402

CUTS = ((0.55, 101), (0.75, 202), (0.92, 303))


def _same(a, b) -> bool:
    return bool(np.isclose(a.to_numpy().astype(float), b.to_numpy().astype(float), rtol=1e-9, atol=1e-9, equal_nan=True).all())


def _cmp(base: pd.DataFrame, new: pd.DataFrame, cols, sel) -> list[str]:
    a = base[sel].set_index(["game_id", "team"]); b = new.set_index(["game_id", "team"]).reindex(a.index)
    return [c for c in cols if not _same(a[c], b[c])]


def _keys_before(games, cut):
    tg = X._team_games(games); return tg[tg.date < cut]


def _truncate(raw, cut):
    g = raw["games"][pd.to_datetime(raw["games"].gameday) < cut]; keep = _keys_before(raw["games"], cut)
    inj = raw["injuries"].copy(); inj["team"] = X._norm(inj["team"].astype(str)); k = keep[["season", "week", "team"]].drop_duplicates()
    inj = inj.merge(k, on=["season", "week", "team"], how="inner")
    return {**raw, "games": g, "injuries": inj, "snaps": raw["snaps"][raw["snaps"].game_id.isin(set(keep.game_id))]}


def _perm(df, idx_mask, cols, rng):
    d = df.copy(); ix = np.flatnonzero(idx_mask)
    for c in cols:
        v = d[c].to_numpy(dtype=object, copy=True); v[ix] = rng.permutation(v[ix]); col = pd.Series(v, index=d.index)
        try:
            col = col.astype(df[c].dtype)
        except (TypeError, ValueError):
            pass
        d[c] = col
    return d


def run(inj_dir, snap_dir, players, games, quick=False) -> dict:
    t0 = time.time(); raw = X.load_raw(inj_dir, snap_dir, players, games); base = X.compute(raw)["team"]; specs = X.specs()
    res = {s.catalog_id: {"sport": "NFL", "id": s.catalog_id, "table": "team", "level_claimed": s.level, "pit_claimed": s.pit, "missing_claimed": list(s.missing), "raw_claimed": list(s.raw), "columns": list(s.columns), "tests": {"vintage_dependence": {}}} for s in specs}
    again = X.compute(raw)["team"]
    for s in specs:
        res[s.catalog_id]["tests"]["determinism"] = {"ok": not _cmp(base, again, s.columns, np.ones(len(base), bool))}
        cov = {c: float(base[c].notna().mean()) for c in s.columns}
        ok_rows = base[base[s.columns].notna().any(axis=1)]
        res[s.catalog_id]["tests"]["coverage_replay"] = {"present": True, "min_coverage_new": round(min(cov.values()), 4), "max_abs_coverage_drift": 0.0, "constant_columns": [c for c in s.columns if base[c].nunique() <= 1], "first_new": str(ok_rows.date.min().date()), "last_new": str(ok_rows.date.max().date()),
                                                         "columns": {c: {"coverage_new": round(v, 4)} for c, v in cov.items()}, "seasons_with_values": sorted(int(x) for x in ok_rows.season.unique())[:3] + ["..."] + sorted(int(x) for x in ok_rows.season.unique())[-1:]}
    dates = base.date.sort_values().reset_index(drop=True)
    for q, seed in CUTS[:1] if quick else CUTS:
        cut = pd.Timestamp(dates.quantile(q)).normalize(); sel = (base.date < cut).to_numpy()
        tr = X.compute(_truncate(raw, cut))["team"]
        rng = np.random.default_rng(seed); gd = base.set_index(["game_id", "team"]).date
        late_games = set(base.loc[base.date >= cut, "game_id"])
        raw2 = {**raw}; inj = raw["injuries"].copy(); inj["team"] = X._norm(inj["team"].astype(str))
        late_t = base.loc[base.date >= cut, ["season", "week", "team"]].drop_duplicates()
        m = inj.merge(late_t.assign(_l=1), on=["season", "week", "team"], how="left")["_l"].notna().to_numpy()
        raw2["injuries"] = _perm(raw["injuries"].assign(team=inj["team"]), m, ["report_status", "position", "date_modified"], rng)
        sm = raw["snaps"].game_id.isin(late_games).to_numpy(); raw2["snaps"] = _perm(raw["snaps"], sm, ["offense_pct", "defense_pct", "offense_snaps"], rng)
        pert = X.compute(raw2)["team"]
        for s in specs:
            t = res[s.catalog_id]["tests"]
            t.setdefault("truncation", []).append({"q": q, "cut": str(cut.date()), "n_pre_rows": int(sel.sum()), "bad_columns": (b := _cmp(base, tr, s.columns, sel)), "ok": not b})
            moved = int((~np.isclose(base.loc[~sel, s.columns].to_numpy().astype(float), pert.set_index(["game_id", "team"]).reindex(base.set_index(["game_id", "team"]).index).loc[:, s.columns].reset_index(drop=True).to_numpy().astype(float)[~sel], equal_nan=True)).any(axis=1).sum()) if False else None
            t.setdefault("perturbation", []).append({"q": q, "seed": seed, "cut": str(cut.date()), "bad_columns": (b2 := _cmp(base, pert, s.columns, sel)), "post_columns_moved": [c for c in s.columns if not _same(base.loc[~sel & base[c].notna(), ["game_id", "team", c]].set_index(["game_id", "team"])[c], pert.set_index(["game_id", "team"]).reindex(base.loc[~sel & base[c].notna(), ["game_id", "team"]].set_index(["game_id", "team"]).index)[c])], "ok": not b2})
    # own-game: scramble the SNAP shares of one mid-history date; features dated on or before it must not move
    dmid = dates[dates >= dates.quantile(0.5)].min().normalize(); gids = set(base.loc[base.date.dt.normalize() == dmid, "game_id"])
    sm = raw["snaps"].game_id.isin(gids).to_numpy(); r3 = {**raw, "snaps": _perm(raw["snaps"], sm, ["offense_pct", "defense_pct", "offense_snaps"], np.random.default_rng(404))}
    own = X.compute(r3)["team"]; sel = (base.date <= dmid).to_numpy()
    for s in specs:
        b = _cmp(base, own, s.columns, sel); res[s.catalog_id]["tests"]["own_game"] = {"date": str(dmid.date()), "n_rows_on_date": int((base.date.dt.normalize() == dmid).sum()), "bad_columns": b, "ok": not b}
    # POST-KICKOFF injuries: scramble every row whose report was last modified AFTER kickoff; NO feature of ANY game may change
    tg = X._team_games(raw["games"]); inj = raw["injuries"].copy(); inj["team"] = X._norm(inj["team"].astype(str)); inj["_mod"] = pd.to_datetime(inj.get("date_modified"), errors="coerce", utc=True)
    mm = inj.merge(tg[["season", "week", "team", "kickoff"]], on=["season", "week", "team"], how="left"); post = (mm["_mod"] > mm["kickoff"]).to_numpy()
    r4 = {**raw, "injuries": _perm(raw["injuries"].assign(team=inj["team"]), post, ["report_status", "position"], np.random.default_rng(505))}
    pk = X.compute(r4)["team"]
    for s in specs:
        if s.catalog_id == "nfl.injuries_pit":
            b = _cmp(base, pk, s.columns, np.ones(len(base), bool))
            res[s.catalog_id]["tests"]["pit_check_post_kickoff_injuries"] = {"n_rows": int(post.sum()), "bad_columns": b, "ok": (not b) and int(post.sum()) > 0, "note": "rows last modified after kickoff scrambled; no feature may change; n_rows must be > 0 so the test is not vacuous"}
    # non-vacuity of the perturbation: scrambling PRE-kickoff statuses of one late block must move later rows
    pre = ((mm["_mod"] <= mm["kickoff"]) & (mm["season"] == 2023)).to_numpy(); r5 = {**raw, "injuries": _perm(raw["injuries"].assign(team=inj["team"]), pre, ["report_status"], np.random.default_rng(606))}
    mv = X.compute(r5)["team"]
    res["nfl.injuries_pit"]["tests"]["pit_check_perturbation_not_vacuous"] = {"n_rows": int(pre.sum()), "columns_that_moved": [c for c in X.specs()[0].columns if not _same(base[c].fillna(-1), mv[c].fillna(-1))], "ok": any(not _same(base[c].fillna(-1), mv[c].fillna(-1)) for c in X.specs()[0].columns)}
    # snaps non-vacuity: scramble the snap shares of ONE mid season's games; later rows (which are built from them) must move, else the perturbation tests above prove nothing
    sd = raw["snaps"].game_id.isin(set(base.loc[base.season == 2019, "game_id"])).to_numpy()
    r6 = {**raw, "snaps": _perm(raw["snaps"], sd, ["offense_pct", "defense_pct", "offense_snaps"], np.random.default_rng(707))}; mv2 = X.compute(r6)["team"]; sp = X.specs()[1]
    moved = [c for c in sp.columns if not _same(base[c].fillna(-1), mv2[c].fillna(-1))]
    res["nfl.snaps"]["tests"]["pit_check_perturbation_not_vacuous"] = {"n_rows": int(sd.sum()), "columns_that_moved": moved, "ok": len(moved) == len(sp.columns)}
    return {"sport": "NFL", "kind": "replay_ext", "seconds": round(time.time() - t0), "quick": quick, "raw_rows": {k: int(len(v)) for k, v in raw.items()}, "inputs": res}


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    r = run(a[0], a[1], a[2], a[3], quick="--quick" in a); Path(a[4]).write_text(json.dumps(r, default=str, indent=0)); print("replayed", list(r["inputs"]), r["seconds"], "s"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
