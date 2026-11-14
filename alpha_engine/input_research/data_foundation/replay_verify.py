"""Independent replay verification of previously computed catalog features (RESEARCH_ONLY).

    python -m alpha_engine.input_research.data_foundation.replay_verify SPORT RAW_DIR NFL_DIR SOCCER_DIR OUT.json [--quick]

For one sport: reload RE-COLLECTED raw data, recompute every feature table with the earlier milestone's builders, and test each computed input with checks that do NOT reuse the earlier
run's seeds, cut dates or protected-column lists:
  1 determinism        compute twice -> bit-identical
  2 coverage replay    non-null share, distinct values, first/last date re-measured and compared with the recorded values (raw data has been re-collected, so small drift is expected and measured)
  3 truncation (new)   recompute on raw data cut off BEFORE date D; every feature row dated before D must be identical to the full-data run. This needs no list of 'outcome' columns, so it also
                       catches look-ahead through league baselines or season aggregates that an outcome perturbation could miss
  4 perturbation       outcomes on/after a cut are randomised with NEW seeds and NEW cut quantiles (earlier run: seed 7, 85th percentile); earlier rows must not move
  5 own-game           outcomes of one MID-history date randomised; rows of that date must not move (earlier run: final date only)
It records evidence per input; `audit.py` / `verified_coverage.py` decide what that evidence is allowed to support. Writes nothing into the repo except through the caller-supplied OUT path.
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

from alpha_engine.features import audit as FA  # noqa: E402
from alpha_engine.features.core import Paths  # noqa: E402

# raw fields the data collectors document as AS-PLAYED / RETRIEVAL-TIME values (not pregame vintages): ledgers' timestamp_reliability notes, source_verification.json and the nflverse schedule (observed weather)
VINTAGE = {"CBB": [(None, "home_rank"), (None, "away_rank")], "CFB": [(None, "home_rank"), (None, "away_rank")], "NFL": [("games", "temp"), ("games", "wind")],
           "MLB": [("schedule", c) for c in ("home_lineup", "away_lineup", "home_plate_ump_id", "home_sp_id", "away_sp_id", "weather_condition", "temp", "wind")]}
# FINAL role / lineup fields of a game: legitimate only for EARLIER games. Test 7 scrambles them among the rows of one mid-history date; features dated on or before that date must not move
ROLE_FIELDS = {"NBA": [("player_games", ["started", "dnp_reason"])], "NHL": [("goalies", ["starter"])], "MLB": [("box", ["gs", "bat_order", "pos"])]}
TRUNC_Q = (0.55, 0.75, 0.92)
PERTURB = ((0.60, 101), (0.80, 202), (0.93, 303))      # (cut quantile, seed): none equals the earlier (0.85, 7)
OWN_Q = (0.5, 404)                                      # mid-history date, new seed


def _truncate(sp, cfg, raw, cut):
    tabs = cfg["tables"]
    if sp in ("SOCCER", "CBB", "CFB"):
        d = FA._dates(raw, "date", tabs[None][1])
        return raw[(d < cut).to_numpy()].reset_index(drop=True)
    out, gdate = {}, {}
    for key, (kind, col) in tabs.items():
        if kind == "date":
            d = FA._dates(raw[key], kind, col)
            out[key] = raw[key][(d < cut).to_numpy()].reset_index(drop=True)
            if "game_id" in raw[key]:
                gdate.update(dict(zip(raw[key]["game_id"], d)))
    for key, (kind, ref) in tabs.items():
        if kind == "gid":
            early = {g for g, d in gdate.items() if d < cut}
            out[key] = raw[key][raw[key]["game_id"].isin(early).to_numpy()].reset_index(drop=True)
    return {k: out.get(k, v) for k, v in raw.items()}


def _same(a: pd.Series, b: pd.Series) -> bool:
    try:
        x, y = a.to_numpy().astype(float), b.to_numpy().astype(float)
        return bool(np.isclose(x, y, rtol=1e-9, atol=1e-9, equal_nan=True).all())
    except (ValueError, TypeError):
        return bool((a.astype(str).to_numpy() == b.astype(str).to_numpy()).all())


def _cmp_rows(t0: pd.DataFrame, t1: pd.DataFrame, cols, sel0) -> list[str]:
    """Columns whose values differ between t0[sel0] and t1 (aligned by position after chronological order)."""
    a = t0[sel0].reset_index(drop=True); b = t1.reset_index(drop=True)
    if len(a) != len(b):
        return ["<row-count %d vs %d>" % (len(a), len(b))]
    return [c for c in cols if c in a and c in b and not _same(a[c], b[c])]


def run(sp: str, paths: Paths, quick: bool = False) -> dict:
    cfg = FA.SPORTS[sp]; t0 = time.time()
    raw = FA._load(sp, cfg, paths); base = FA._compute(sp, cfg, raw)
    specs = FA._specs(sp, cfg)
    rec = json.loads((ROOT / "research/input_research/computable_inputs.json").read_text())["inputs"]
    md = json.loads((ROOT / "research/input_research/market_dependency.json").read_text()); bench = {i for v in md["benchmark_only"].values() for i in v}
    allv = pd.concat([FA._table_dates(t) for t in base.values() if FA._table_dates(t) is not None]).dropna()
    res = {s.catalog_id: {"sport": sp, "id": s.catalog_id, "table": s.table, "level_claimed": s.level, "pit_claimed": s.pit, "missing_claimed": list(s.missing), "raw_claimed": list(s.raw), "columns": list(s.columns), "tests": {}} for s in specs}
    # 1 determinism
    again = FA._compute(sp, cfg, raw)
    for s in specs:
        res[s.catalog_id]["tests"]["determinism"] = {"ok": not _cmp_rows(base[s.table], again[s.table], s.columns, np.ones(len(base[s.table]), bool))}
    # 2 coverage replay vs recorded
    for s in specs:
        cov = FA.coverage(base[s.table], s.columns); old = (rec.get(f"{sp}:{s.catalog_id}") or {}).get("coverage") or {}
        diffs = {}
        for c in s.columns:
            o, n = old.get(c), cov[c]
            if o and o.get("present") and n.get("present"):
                diffs[c] = {"coverage_old": o["coverage"], "coverage_new": n["coverage"], "nunique_old": o.get("nunique"), "nunique_new": n.get("nunique"), "first_old": o.get("first"), "first_new": n.get("first"), "last_old": o.get("last"), "last_new": n.get("last")}
        mx = max([abs(d["coverage_old"] - d["coverage_new"]) for d in diffs.values()] or [0.0])
        res[s.catalog_id]["tests"]["coverage_replay"] = {"present": all(cov[c]["present"] for c in s.columns), "min_coverage_new": min((cov[c]["coverage"] for c in s.columns if cov[c]["present"]), default=None), "max_abs_coverage_drift": round(mx, 4),
                                                         "constant_columns": [c for c in s.columns if cov[c].get("nunique", 0) <= 1], "first_new": min((cov[c]["first"] for c in s.columns if cov[c].get("first")), default=None),
                                                         "last_new": max((cov[c]["last"] for c in s.columns if cov[c].get("last")), default=None), "columns": diffs}
    # 3 truncation (independent of seeds, cuts and protected-column lists)
    for q in TRUNC_Q[:1] if quick else TRUNC_Q:
        cut = allv.quantile(q).normalize(); tr = FA._compute(sp, cfg, _truncate(sp, cfg, raw, cut))
        for s in specs:
            d = FA._table_dates(base[s.table]); pre = (d < cut).to_numpy() if d is not None else np.ones(len(base[s.table]), bool)
            bad = _cmp_rows(base[s.table], tr[s.table], s.columns, pre)
            res[s.catalog_id]["tests"].setdefault("truncation", []).append({"q": q, "cut": str(cut.date()), "n_pre_rows": int(pre.sum()), "bad_columns": bad, "ok": not bad})
    # 4 future perturbation with new seeds/cuts
    for q, seed in PERTURB[:1] if quick else PERTURB:
        cut = allv.quantile(q).normalize(); new = FA._compute(sp, cfg, FA.perturb_raw(sp, cfg, raw, cut, seed=seed))
        for s in specs:
            d = FA._table_dates(base[s.table]); pre = (d < cut).to_numpy() if d is not None else np.ones(len(base[s.table]), bool)
            if len(base[s.table]) != len(new[s.table]):
                res[s.catalog_id]["tests"].setdefault("perturbation", []).append({"q": q, "seed": seed, "ok": False, "why": "row count changed"}); continue
            bad, moved = FA._cmp(base[s.table], new[s.table], s.columns, pre)
            res[s.catalog_id]["tests"].setdefault("perturbation", []).append({"q": q, "seed": seed, "cut": str(cut.date()), "bad_columns": list(bad), "post_columns_moved": moved, "ok": not bad})
    # 5 own-game at a mid-history date
    cutm = allv.quantile(OWN_Q[0]).normalize()
    cutm = allv[allv >= cutm].min().normalize()
    new = FA._compute(sp, cfg, FA.perturb_raw(sp, cfg, raw, cutm, seed=OWN_Q[1], last_only=(sp == "TENNIS")))
    for s in specs:
        d = FA._table_dates(base[s.table])
        on = (d.dt.normalize() == cutm).to_numpy() if d is not None else np.zeros(len(base[s.table]), bool)
        if len(base[s.table]) != len(new[s.table]):
            res[s.catalog_id]["tests"]["own_game"] = {"ok": False, "why": "row count changed"}; continue
        bad = _cmp_rows(base[s.table], new[s.table][on.nonzero()[0][0]:on.nonzero()[0][-1] + 1] if on.any() else new[s.table].iloc[0:0], s.columns, on) if on.any() else []
        res[s.catalog_id]["tests"]["own_game"] = {"date": str(cutm.date()), "n_rows_on_date": int(on.sum()), "bad_columns": bad, "ok": not bad}
    # 6 vintage dependence: scramble each as-played / retrieval-time raw field across rows; a computed column that moves DEPENDS on that field
    rng = np.random.default_rng(505)
    for tab, col in VINTAGE.get(sp, []):
        r2 = dict(raw) if isinstance(raw, dict) else raw.copy()
        if tab is None:
            r2[col] = rng.permutation(r2[col].to_numpy())
        else:
            t = r2[tab].copy(); t[col] = rng.permutation(t[col].to_numpy()); r2[tab] = t
        new = FA._compute(sp, cfg, r2)
        for s in specs:
            if len(new[s.table]) == len(base[s.table]):
                bad = _cmp_rows(base[s.table], new[s.table], s.columns, np.ones(len(base[s.table]), bool))
                res[s.catalog_id]["tests"].setdefault("vintage_dependence", {})[(tab or "raw") + "." + col] = bad
    # 7 role fields of the game's own date (final lineups / starters must not feed that game's pregame features)
    for tab, cols in ROLE_FIELDS.get(sp, []):
        kind, dcol = cfg["tables"][tab]
        d = FA._dates(raw[tab], kind, dcol); dmid = d.quantile(0.5).normalize(); dmid = d[d >= dmid].min().normalize()
        on = (d.dt.normalize() == dmid).to_numpy(); rng2 = np.random.default_rng(606)
        for c in cols:
            t = raw[tab].copy(); idx = np.flatnonzero(on); t.loc[t.index[idx], c] = rng2.permutation(t.loc[t.index[idx], c].to_numpy())
            r2 = dict(raw); r2[tab] = t; new = FA._compute(sp, cfg, r2)
            for s in specs:
                bt = base[s.table]; dd = FA._table_dates(bt)
                if dd is None or len(new[s.table]) != len(bt):
                    continue
                sel = (dd.dt.normalize() <= dmid).to_numpy()
                bad = _cmp_rows(bt, new[s.table][sel], s.columns, sel)   # the SAME selection on both sides
                res[s.catalog_id]["tests"].setdefault("role_fields_own_date", {})[f"{tab}.{c}"] = {"date": str(dmid.date()), "bad_columns": bad}
    for s in specs:
        res[s.catalog_id]["benchmark_only"] = s.catalog_id in bench
    return {"sport": sp, "seconds": round(time.time() - t0), "rows": {k: int(len(v)) for k, v in base.items()}, "raw_rows": ({k: int(len(v)) for k, v in raw.items()} if isinstance(raw, dict) else int(len(raw))), "quick": quick, "inputs": res}


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    sp, rawd, nfld, socd, out = a[:5]
    r = run(sp, Paths(raw=rawd, nfl=nfld, soccer=socd), quick="--quick" in a)
    Path(out).write_text(json.dumps(r, default=str, indent=0))
    print(sp, "replayed", len(r["inputs"]), "specs in", r["seconds"], "s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
