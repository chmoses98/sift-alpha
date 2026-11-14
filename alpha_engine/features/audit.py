"""Verified-computable input audit (RESEARCH_ONLY). For every catalog input (sport:id) either a FeatureSpec was computed from real raw rows and verified here, or the reason it is not computed is recorded.

Verification per spec: (1) every column exists and is non-constant, (2) coverage overall / per season / first-last date, (3) point-in-time perturbation test: recompute after randomising every outcome statistic
of games on/after a cut date and require every spec column of rows BEFORE the cut to be bit-identical (and require post-cut rows to change, so the test is not vacuous), (4) pit class gating
(final_postgame columns are never pregame eligible). Status is only COMPUTED_* when all checks pass; keyword matching of source names never produces a COMPUTED status."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from . import college, mlb, nba, nfl, nhl, soccer, tennis
from .core import Paths

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research/input_research/computable_inputs.json"
CACHE = Path("/tmp/featcache")
# Columns that are structure, not outcomes: never perturbed (ids, dates, names, keys, role flags that decide which rows exist).
PROTECT = re.compile(r"(^|_)(id|ids|date|time|season|week|year|team|teams|name|code|type|game|match|tourney|ord|location|round|surface|level|hand|entry|pid|nba|pos|bat|order|side|dh|"
                     r"sweater|schema|version|state|number|num|draw|seed|slot|lineup|rank|rest|age|ht|best|of)(_|$)|(^|_)(id|date|time|rank|rest)$|(Id|Date)$|^(home|away|is_home|played|started|starter|start|gs|dnp_reason|pa|ab|bf)$|^(home|away)_(team|id)$", re.I)
OUTCOME_STR = {"score", "last_period_type", "home_runs_by_inning", "away_runs_by_inning", "zone", "home_periods", "away_periods"}
OUTCOME_BOOL = {"shot_made"}
# derived from role flags (started / starter / played / lineup slot): perturbing those flags would change which rows exist, so these are checked for future/own-row stability only and flagged as such
ROLE_DERIVED = {"started_f_pre", "role_change_pre", "started_pre", "slot_pre", "p_play_given_status_pre", "p_same_goalie_pre", "return_from_absence", "is_d", "bf_pre", "pa_pre"}
# outcome-independent columns (schedule / attributes / counts): allowed to be unchanged by outcome perturbation
STATIC_COLS = {"rest", "rest_gap", "home", "neutral", "neutral_home", "conf_game", "ranked", "opp_ranked", "rank", "is_left", "opp_is_left", "round_idx", "seeded", "qualifier", "draw_size", "rank_pts", "rank_log", "rank_diff_log",
               "age", "age_sq", "ht", "tour_wta", "early_season", "short_rest", "bye", "div_game", "outdoors", "coach_games_pre", "season_games_pre", "n_pre", "n_surface_pre", "matches_14d_pre", "games_7d_pre", "days_since_surface",
               "layoff_days_pre", "h2h_n_pre", "back_to_back", "games_remaining", "games_played_pre", "dh", "day_after_night", "plays_pre", "pace_sum_pre", "matches_last14d_pre", "days_since_prev", "games_left_pre", "rest_days", "starts_pre", "games_last7", "attendance", "opp_n_pre", "best_of5", "surf_clay", "surf_grass", "surf_hard", "inj_status_code", "games_season_pre"}

SPORTS = {
    "NBA": dict(mod=nba, tables={"team_games": ("date", "game_date_et"), "player_games": ("date", "game_date_et"), "shots": ("gid", "team_games"), "injury": ("gid", "team_games")}),
    "NHL": dict(mod=nhl, tables={"mp": ("date", "game_date"), "games": ("date", "game_date"), "skaters": ("date", "game_date"), "goalies": ("date", "game_date"), "states": ("date", "game_date")}),
    "MLB": dict(mod=mlb, tables={"schedule": ("date", "date"), "box": ("date", "date")}),
    "TENNIS": dict(mod=tennis, tables={"atp": ("date", "tourney_date"), "wta": ("date", "tourney_date")}),
    "SOCCER": dict(mod=soccer, tables={None: ("date", "Date")}),
    "CBB": dict(mod=college, tables={None: ("date", "date")}, college="CBB"),
    "CFB": dict(mod=college, tables={None: ("date", "date")}, college="CFB"),
    "NFL": dict(mod=nfl, tables={"pbp": ("gid", "games"), "games": ("date", "gameday")}),
}


def _load(sp, cfg, paths):
    return cfg["mod"].load_raw(paths, cfg["college"]) if "college" in cfg else cfg["mod"].load_raw(paths)


def _compute(sp, cfg, raw):
    return cfg["mod"].compute(raw)


def _specs(sp, cfg):
    m = cfg["mod"]
    specs = m.specs_cbb() if sp == "CBB" else m.specs_cfb() if sp == "CFB" else m.specs()
    from .pit_policy import load_quarantine
    q = load_quarantine()
    for s in specs:   # point-in-time repair: an input that replay evidence shows depends on a FORBIDDEN-as-pregame field cannot be certified as pregame
        if f"{sp}:{s.catalog_id}" in q and s.pit != "final_postgame":
            s.pit = "final_postgame"
            s.missing = list(s.missing) + ["(point-in-time quarantine) depends on " + ", ".join(q[f"{sp}:{s.catalog_id}"]["fields"]) + ": not a pregame vintage"]
    return specs


def _dates(df, kind, col):
    if kind == "date":
        s = df[col]
        if col == "tourney_date":
            return pd.to_datetime(s.astype(str), format="%Y%m%d", errors="coerce")
        return pd.to_datetime(s, format="mixed", dayfirst=(col == "Date"), errors="coerce")
    return None


def _perturb_df(df, mask, rng):
    out = df.copy()
    mask = np.asarray(mask, dtype=bool)
    if mask.sum() == 0:
        return out
    for c in out.columns:
        if c in OUTCOME_BOOL and c in out:
            idx = np.where(mask & (rng.random(len(out)) < 0.5))[0]; col = out.columns.get_loc(c); out.iloc[idx, col] = ~out[c].iloc[idx].astype(bool).to_numpy()
            continue
        if c in OUTCOME_STR and c in out:
            idx = np.where(mask)[0]; out.iloc[idx, out.columns.get_loc(c)] = out[c].iloc[idx].to_numpy()[rng.permutation(len(idx))]
            continue
        if PROTECT.search(c) or pd.api.types.is_bool_dtype(out[c]) or not pd.api.types.is_numeric_dtype(out[c]):
            continue
        if c.startswith(("winner_", "loser_", "w_", "l_")):
            continue          # handled by the winner/loser swap below
        f = rng.uniform(0.3, 1.7, size=int(mask.sum()))
        v = out.loc[mask, c].astype(float).to_numpy() * f
        src = df[c].dropna()
        intlike = pd.api.types.is_integer_dtype(df[c]) or (len(src) and bool((src.to_numpy() == np.round(src.to_numpy())).all()))
        out.loc[mask, c] = np.round(v) if intlike else v
    if "winner_id" in out.columns:       # tennis: flip the outcome of a random half of the post-cut matches by swapping the winner_*/loser_* identity columns only (the w_/l_ serve statistics stay put, so each player is handed the other's match statistics too)
        flip = mask & (rng.random(len(out)) < 0.5)
        for a in [c for c in out.columns if c.startswith("winner_")]:
            b = "loser_" + a[7:]
            if b in out.columns:
                va, vb = out.loc[flip, a].copy(), out.loc[flip, b].copy(); out.loc[flip, a], out.loc[flip, b] = vb.to_numpy(), va.to_numpy()
    return out


def perturb_raw(sp, cfg, raw, cut, seed=7, last_only=False):
    rng = np.random.default_rng(seed)
    tabs = cfg["tables"]
    if sp in ("SOCCER", "CBB", "CFB"):
        k, col = tabs[None][1], tabs[None][1]
        d = _dates(raw, "date", col)
        return _perturb_df(raw, (d >= cut).to_numpy(), rng)
    out, gdate = {}, {}
    for key, (kind, col) in tabs.items():
        if kind == "date":
            d = _dates(raw[key], kind, col)
            m = (d >= cut).to_numpy()
            if last_only and sp == "TENNIS":      # only dates carry the tournament start: perturb just the final-round matches of the last finished tournaments (later rounds legitimately depend on earlier ones)
                m = m & (raw[key]["round"] == "F").to_numpy()
            out[key] = _perturb_df(raw[key], m, rng)
            if "game_id" in raw[key]:
                gdate.update(dict(zip(raw[key]["game_id"], d)))
    for key, (kind, ref) in tabs.items():
        if kind == "gid":
            late = {g for g, d in gdate.items() if d >= cut}
            out[key] = _perturb_df(raw[key], raw[key]["game_id"].isin(late).to_numpy(), rng)
    return {k: out.get(k, v) for k, v in raw.items()}


def _table_dates(df):
    if "date" in df:
        return pd.to_datetime(df["date"], errors="coerce")
    return None


def _cmp(t0, t1, cols, sel):
    bad, moved = [], 0
    for c in cols:
        if c not in t0:
            bad.append(f"{c}:missing"); continue
        a, b = t0[c].to_numpy(), t1[c].to_numpy()
        try:
            a = a.astype(float); b = b.astype(float)
            same = np.isclose(a[sel], b[sel], rtol=1e-9, atol=1e-9, equal_nan=True)
            mv = (~sel).any() and not np.isclose(a[~sel], b[~sel], rtol=1e-9, atol=1e-9, equal_nan=True).all()
        except Exception:
            same = (pd.Series(a[sel]).fillna("§").to_numpy() == pd.Series(b[sel]).fillna("§").to_numpy())
            mv = False
        if not same.all():
            bad.append(c)
        moved += int(mv)
    return bad, moved


def leak_test(sp, cfg, raw, base, specs, cut_q=0.85):
    """Test A (future): outcomes of games on/after the 85th-percentile date are randomised -> every spec column of earlier rows must be bit-identical, and later rows must move.
    Test B (own game): outcomes of ONLY the final date are randomised -> every spec column of the rows on that date must be bit-identical (a feature may not see its own game)."""
    allv = pd.concat([_table_dates(t) for t in base.values() if _table_dates(t) is not None]).dropna()
    cutA = allv.quantile(cut_q).normalize(); cutB = allv.max().normalize()
    if sp == "TENNIS":       # the latest date that has a completed final
        cutB = min(pd.to_datetime(raw[k][raw[k]["round"] == "F"]["tourney_date"].astype(str), format="%Y%m%d").max() for k in raw)
    newA = _compute(sp, cfg, perturb_raw(sp, cfg, raw, cutA, seed=7))
    newB = _compute(sp, cfg, perturb_raw(sp, cfg, raw, cutB, seed=11, last_only=True))
    res = {}
    for sp_ in specs:
        t0 = base[sp_.table]; tA, tB = newA[sp_.table], newB[sp_.table]
        if len(t0) != len(tA) or len(t0) != len(tB):
            res[sp_.catalog_id] = dict(ok=False, why=f"row count changed {len(t0)}->{len(tA)}/{len(tB)}"); continue
        d = _table_dates(t0)
        preA = (d < cutA).to_numpy() if d is not None else np.ones(len(t0), bool)
        badA, moved = _cmp(t0, tA, sp_.columns, preA)
        badB, _ = _cmp(t0, tB, sp_.columns, np.ones(len(t0), bool))
        unmoved_nonstatic = [c for c in sp_.columns if c not in STATIC_COLS and c not in ROLE_DERIVED and c in t0 and not _col_moved(t0, tA, c, preA)]
        res[sp_.catalog_id] = dict(ok=not badA and not badB, bad=badA, bad_own_game=badB, post_columns_moved=moved, unmoved_nonstatic=unmoved_nonstatic, cut=str(cutA.date()), last_date=str(cutB.date()))
    return res


def _col_moved(t0, t1, c, sel):
    try:
        a, b = t0[c].to_numpy().astype(float)[~sel], t1[c].to_numpy().astype(float)[~sel]
        return not np.isclose(a, b, rtol=1e-9, atol=1e-9, equal_nan=True).all()
    except Exception:
        return False


def coverage(df, cols):
    out = {}
    season = df["season"].astype(str) if "season" in df else (pd.to_datetime(df["date"]).dt.year.astype(str) if "date" in df else pd.Series("all", index=df.index))
    dts = _table_dates(df)
    for c in cols:
        if c not in df:
            out[c] = dict(present=False); continue
        s = df[c]; nn = s.notna()
        per = nn.groupby(season).mean()
        vals = pd.to_numeric(s, errors="coerce")
        out[c] = dict(present=True, coverage=round(float(nn.mean()), 4), n=int(len(s)), nonnull=int(nn.sum()), nunique=int(vals.nunique()) if vals.notna().any() else 0, std=float(vals.std()) if vals.notna().sum() > 1 else 0.0,
                      season_cov_min=round(float(per.min()), 3), seasons_ok=int((per >= 0.6).sum()), seasons=int(len(per)),
                      first=str(dts[nn].min().date()) if dts is not None and nn.any() else None, last=str(dts[nn].max().date()) if dts is not None and nn.any() else None)
    return out


def classify(sp_, cov, leak, benchmark_only):
    if sp_.catalog_id in benchmark_only:
        return "EXCLUDED_BENCHMARK_ONLY", "catalog input is market-derived; a market-free analogue column set exists but is not counted"
    if sp_.pit == "final_postgame":
        return "NOT_PREGAME_ELIGIBLE", "values are observed after the fact; usable only for post-hoc analysis"
    cs = [cov[c] for c in sp_.columns]
    if any(not c["present"] for c in cs):
        return "BUILD_FAILED", "column not produced"
    if not leak["ok"]:
        return "LEAK_FAIL", f"point-in-time test failed: future-perturbation changed {leak.get('bad')}, own-game perturbation changed {leak.get('bad_own_game')} {leak.get('why') or ''}"
    if all(c["nunique"] <= 1 for c in cs):
        return "DEGENERATE", "all columns constant"
    if leak.get("unmoved_nonstatic"):
        return "UNVERIFIED_LEAK_TEST", f"outcome perturbation did not reach columns {leak['unmoved_nonstatic']}, so they are not verified"
    lo = min(c["coverage"] for c in cs)
    if any(c in ROLE_DERIVED for c in sp_.columns):
        sp_.missing = list(sp_.missing) + ["(verification limit: role-flag-derived columns could not be outcome-perturbed)"]
    if lo < 0.5:
        return f"COMPUTED_LIMITED_{sp_.level}", f"min column coverage {lo:.2f} (history is short for part of the sample)"
    return f"COMPUTED_{sp_.level}", ""


def _one_sport(args):
    sp, paths, leak = args
    cached = CACHE / f"{sp}_audit.json"
    if cached.exists() and not os.environ.get("AUDIT_FORCE"):
        r = json.load(open(cached)); return sp, r["items"], r["log"]
    cfg = SPORTS[sp]; t0 = time.time(); raw = _load(sp, cfg, paths); base = _compute(sp, cfg, raw)
    for k, t in base.items():
        t = t.copy()
        for c in t.columns[t.dtypes == object]:
            t[c] = t[c].astype(str).where(t[c].notna())
        t.to_parquet(CACHE / f"{sp}_{k}.parquet")
    specs = _specs(sp, cfg)
    lk = leak_test(sp, cfg, raw, base, specs) if leak else {s.catalog_id: dict(ok=True, unmoved_nonstatic=[]) for s in specs}
    md = json.load(open(ROOT / "research/input_research/market_dependency.json")); bench = {i for v in md["benchmark_only"].values() for i in v}
    items = {}
    for s in specs:
        cov = coverage(base[s.table], s.columns); st, why = classify(s, cov, lk[s.catalog_id], bench)
        items[f"{sp}:{s.catalog_id}"] = dict(sport=sp, id=s.catalog_id, status=st, reason=why, level=s.level, table=s.table, columns=s.columns, definition=s.definition, done=s.done, missing=s.missing, raw=s.raw, pit=s.pit,
                                            coverage={c: cov[c] for c in s.columns}, leak_test=lk[s.catalog_id])
    print(sp, "done", round(time.time() - t0), file=sys.stderr, flush=True)
    log = dict(seconds=round(time.time() - t0), tables={k: len(v) for k, v in base.items()})
    if leak:
        cached.write_text(json.dumps(dict(items=items, log=log), default=str))
    return sp, items, log


def run(paths=None, only=None, leak=True):
    paths = paths or Paths(); CACHE.mkdir(exist_ok=True)
    md = json.load(open(ROOT / "research/input_research/market_dependency.json"))
    bench = {i for v in md["benchmark_only"].values() for i in v}
    rd = json.load(open(ROOT / "research/input_research/data_readiness.json"))
    inputs, per_sport, log = {}, {}, {}
    import multiprocessing as mp
    todo = [sp for sp in SPORTS if not only or sp in only]
    with mp.get_context("fork").Pool(4) as pool:
        parts = pool.map(_one_sport, [(sp, paths, leak) for sp in todo], chunksize=1)
    for sp, items, lg in parts:
        inputs.update(items); log[sp] = lg
    # a constant column carries no information: drop it from the spec (recorded) and demote a spec with nothing left
    for v in inputs.values():
        cov = v.get("coverage")
        if not cov or not v["status"].startswith("COMPUTED"):
            continue
        const = [c for c, cv in cov.items() if cv.get("nunique", 0) <= 1]
        if const:
            v["dropped_constant"] = const
            v["columns"] = [c for c in v["columns"] if c not in const]
            v["coverage"] = {c: cv for c, cv in cov.items() if c not in const}
            if not v["columns"]:
                v["status"], v["reason"] = "DEGENERATE", "all columns constant"
    # inputs without a builder: reason from the raw-data classes they need
    for key, v in rd["inputs"].items():
        if key in inputs:
            continue
        sp, cid = key.split(":", 1)
        if cid in bench or v["status"] == "EXCLUDED_BENCHMARK_ONLY":
            inputs[key] = dict(sport=sp, id=cid, status="EXCLUDED_BENCHMARK_ONLY", reason="market-derived; benchmark only"); continue
        blockers = [c for c, lvl in v.get("levels", []) if lvl == 0]
        inputs[key] = dict(sport=sp, id=cid, status="NOT_COMPUTED", reason=("raw data class absent: " + ", ".join(blockers)) if blockers else "raw data present for the keyword-matched classes but no verified builder (not computed)", blockers=blockers)
    tot = {}
    for v in inputs.values():
        tot[v["status"]] = tot.get(v["status"], 0) + 1
    per_sport = {}
    for v in inputs.values():
        d = per_sport.setdefault(v["sport"], {}); d[v["status"]] = d.get(v["status"], 0) + 1
    doc = dict(schema_version="computable-inputs-1.0", status="RESEARCH_ONLY", generated=time.strftime("%Y-%m-%d"), totals=tot, by_sport=per_sport, n_inputs=len(inputs), n_non_market=sum(1 for v in inputs.values() if v["status"] != "EXCLUDED_BENCHMARK_ONLY"), timing=log, inputs=inputs)
    if not only:
        OUT.write_text(json.dumps(doc, indent=1, default=str))
    return doc


if __name__ == "__main__":
    only = sys.argv[1:] or None
    d = run(only=only)
    print(json.dumps({k: d[k] for k in ("totals", "by_sport", "n_inputs", "n_non_market")}, indent=1))
