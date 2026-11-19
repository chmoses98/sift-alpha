"""Verification and publication of the derived inputs (RESEARCH_ONLY).

    python -m alpha_engine.derived.verify --nba <restored NBA archive> --cbb <restored CBB archive> [--repos <dir holding the projection repos>]

Four independent questions, never merged into one flag:
  1. POINT IN TIME   outcome-perturbation replay: every outcome statistic and linescore of games on/after a cut date is shuffled, the whole engine is re-run, and every
                     feature of every row dated ON OR BEFORE the cut must be unchanged (own-game and future leakage), while rows after the cut must move (non-vacuous).
  2. CALCULATION     an independent plain-Python recomputation from the raw parquet rows (no shared code with the engine) of the two-stage adjusted estimates for sampled rows.
  3. COVERAGE        non-null share overall and for the worst season, first/last date.
  4. PREDICTIVE      out-of-sample comparison with a stated naive baseline on the latest seasons. This is evidence about the INPUT only; it is not a model improvement claim.
A level (FULL / PARTIAL / PROXY) is a statement about the definition and comes from the registry; verification can only withhold a status, never raise a level.
Writes research/audit/derived_inputs.json ONLY. The certified ledger (research/input_research/computable_inputs.json and the data-foundation matrix built on it) is never written here:
that ledger has its own promotion process (foundation replay plus two blind rechecks, rights tiering, promotion audit). Each input therefore carries
`ledger_promotion: PENDING_FOUNDATION_REPLAY`, and the accounting reports the certified numbers and the pending numbers side by side.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
import time
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import basketball as B
from . import registry as R

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research/audit/derived_inputs.json"
CI = ROOT / "research/input_research/computable_inputs.json"
OUTCOME = ["team_score", "field_goals_made", "field_goals_attempted", "three_point_field_goals_made", "three_point_field_goals_attempted", "free_throws_made", "free_throws_attempted",
           "offensive_rebounds", "defensive_rebounds", "assists", "steals", "blocks", "fouls", "fast_break_points", "total_turnovers", "turnovers", "team_winner", "opponent_team_score"]
STATIC = {"rest_min_pre", "rest_days", "p_ot2_given_ot_pre"}       # schedule-only, or a pooled prior-season constant that a within-season perturbation cannot reach
HOLDOUT_SEASONS = 4
TOL = 1e-9          # replay tolerance (relative, floor 1): float summation order can differ in the last bits; an information leak moves values by many orders more. Max observed diff is recorded per input.
ADOPTION_PROBE = {"NBA": ("nba-edge-finder", "src"), "CBB": ("cbb-edge-finder", "cbb_edge")}
PROBE_RX = {"four_factors": r"\befg|four_factor", "tempo|pace": r"possessions|tempo|\bpace\b", "adj_off|adj_def|fundamental_expectation": r"adj_off|adj_def|off_rtg|ortg|def_rtg|net_rtg",
            "three": r"fg3a|three_att|3pa", "ft_points|foul": r"ft_rate|ftr|fta", "ot_prob": r"p_ot|ot_prob|overtime_prob", "variance|sd|hetero": r"margin_sd|sd_margin|sigma_margin|total_sd|uncertainty",
            "covariance|coupling": r"margin_total|copula|rho_m", "opportunity": r"reb_pool|rebound_pool|ast_rate|opp_ast"}


# ------------------------------------------------------------------ 1. point in time
def perturb(raw: dict, cut: pd.Timestamp, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed); box = raw["box"].copy()
    m = (pd.to_datetime(box.game_date) >= cut).to_numpy(); idx = np.flatnonzero(m)
    for c in [c for c in OUTCOME if c in box.columns]:
        v = box[c].to_numpy(copy=True); v[idx] = v[idx][rng.permutation(len(idx))]; box[c] = v
    sch = raw["sched"].copy(); gd = dict(zip(box.game_id, pd.to_datetime(box.game_date)))
    m2 = sch.game_id.map(gd).ge(cut).fillna(True).to_numpy(); i2 = np.flatnonzero(m2); perm = rng.permutation(len(i2))
    for c in ("home_linescores", "away_linescores", "status_period"):
        v = sch[c].to_numpy(copy=True); v[i2] = v[i2][perm]; sch[c] = v
    return {"box": box, "sched": sch}


def pit_test(raw, sport, t0, f0, cols):
    seasons = sorted(t0.season.unique()); S = seasons[-2]                      # last complete season: a later season exists, so walk-forward fits are exercised too
    d = t0.loc[t0.season == S, "date"].sort_values(); cut = d.iloc[len(d) // 2]
    t1 = B.team_games(perturb(raw, cut), sport); f1 = B.features(t1, sport)
    a = f0.set_index(["game_id", "team"]); b = f1.set_index(["game_id", "team"]).reindex(a.index)
    pre = (a.date <= cut).to_numpy(); post = ~pre
    res = {"cut": str(cut.date()), "rows_on_or_before_cut": int(pre.sum()), "rows_after_cut": int(post.sum()), "rows_missing_after_replay": int(b.date.isna().sum()), "tolerance": TOL, "columns": {}}
    for c in cols:
        x, y = a[c].to_numpy(float), b[c].to_numpy(float)
        same = (np.abs(x - y) <= TOL * np.maximum(1.0, np.abs(x))) | (np.isnan(x) & np.isnan(y)); diff = np.nanmax(np.abs(x[pre] - y[pre])) if pre.any() and np.isfinite(x[pre]).any() else 0.0
        res["columns"][c] = {"identical_on_or_before_cut": bool(same[pre].all()), "max_abs_diff": float(np.nan_to_num(diff)), "share_moved_after_cut": round(float((~same[post]).mean()), 4)}
    return res


# ------------------------------------------------------------------ 2. independent recomputation (plain Python over raw rows; shares no code with basketball.py)
def independent_check(root, sport, f0, n_sample=40, seed=3, return_rows=False):
    c = B.CFG[sport]; reg, P, hl, k, win = c["reg_min"], c["periods"], c["hl"], c["k"], c["window"]
    box = pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(str(Path(root) / c["box"] / "*.parquet")))])
    box = box[box.season_type.isin(c["types"])]
    if sport == "NBA":
        box = box[(box.team_id >= 1) & (box.team_id <= 30) & (box.opponent_team_id >= 1) & (box.opponent_team_id <= 30)]
    sch = pd.concat([pd.read_parquet(p).reindex(columns=["game_id", "neutral_site", "home_linescores", "status_period"]) for p in sorted(glob.glob(str(Path(root) / c["sched"] / "*.parquet")))]).drop_duplicates("game_id")
    meta = {}
    for gid, neu, ls, spd in zip(sch.game_id, sch.neutral_site, sch.home_linescores, sch.status_period):
        nper = int(spd) if spd is not None and spd == spd and spd >= P else 0          # status_period first, linescore entry count as fallback
        if nper < P:
            nper = len(re.findall(r"'value'", ls)) if isinstance(ls, str) else 0
            nper = nper if nper >= P else 0
        meta[int(gid)] = (1 if neu is True or neu == 1 else 0, max(nper - P, 0))
    games = defaultdict(dict)
    for r in box.itertuples(index=False):
        if not r.field_goals_attempted > 0:
            continue
        tov = r.total_turnovers if r.total_turnovers == r.total_turnovers else r.turnovers
        games[int(r.game_id)][int(r.team_id)] = dict(season=int(r.season), date=pd.Timestamp(r.game_date), home=str(r.team_home_away) == "home", fta=float(r.free_throws_attempted), pts=float(r.team_score),
                                                     own=r.field_goals_attempted - r.offensive_rebounds + tov + 0.44 * r.free_throws_attempted)
    rows = []                                                                    # one record per game x team with the game's realised metrics
    for gid, g in games.items():
        if len(g) != 2:
            continue
        (ta, a), (tb, b) = g.items(); poss = (a["own"] + b["own"]) / 2.0; neu, ot = meta.get(gid, (0, 0))
        pace = poss * reg / (reg + 5.0 * ot)
        for tm, me, op, opp in ((ta, a, b, tb), (tb, b, a, ta)):
            rows.append(dict(gid=gid, team=tm, opp=opp, season=me["season"], date=me["date"], site=0 if neu else (1 if me["home"] else -1), pace=pace, ftr=100 * me["fta"] / poss, d_ftr=100 * op["fta"] / poss,
                             ortg=100 * me["pts"] / poss, d_ortg=100 * op["pts"] / poss))
    rows.sort(key=lambda r: (r["date"], r["gid"]))
    by_ts, by_season, at = defaultdict(list), defaultdict(list), {}
    for r in rows:
        by_ts[(r["team"], r["season"])].append(r); by_season[r["season"]].append(r); at[(r["gid"], r["team"])] = r
    if return_rows:
        return rows
    mean = lambda v: sum(v) / len(v) if v else float("nan")

    def league(season, date, m):
        v = [r[m] for r in by_season[season] if r["date"] < date]
        return mean(v) if v else mean([r[m] for r in by_season.get(season - 1, [])])

    def edge(season, m):                                                         # venue edge: half the home-away gap of earlier seasons (non-neutral games)
        gaps = []
        for s in range(season - win, season):
            h = [r[m] for r in by_season.get(s, []) if r["site"] == 1]; a_ = [r[m] for r in by_season.get(s, []) if r["site"] == -1]
            if h and a_:
                gaps.append((mean(h) - mean(a_)) / 2.0)
        return mean(gaps) if gaps else 0.0

    def shrink(values, team, season, date, m, src):
        prev = [r[src] for r in by_ts.get((team, season - 1), [])]
        target = mean(prev) if len(prev) >= 10 else league(season, date, m)
        n = len(values)
        if n == 0:
            return target
        wts = [0.5 ** ((n - 1 - i) / hl) for i in range(n)]; ew = sum(w * v for w, v in zip(wts, values)) / sum(wts)
        return (n * ew + k * target) / (n + k) if target == target else ew
    memo = {}

    def stage1(team, gid, src, m):
        key = (team, gid, src)
        if key not in memo:
            r = at[(gid, team)]; prior = [x for x in by_ts[(team, r["season"])] if (x["date"], x["gid"]) < (r["date"], r["gid"])]
            memo[key] = shrink([x[src] for x in prior], team, r["season"], r["date"], m, src)
        return memo[key]

    def adj(x, which, m):                                                        # one earlier game's opponent- and venue-adjusted value (stage 2 input)
        lg_ = league(x["season"], x["date"], m)
        if which == "pace":
            o = stage1(x["opp"], x["gid"], "pace", "pace"); return x["pace"] - ((o - lg_) if o == o and lg_ == lg_ else 0.0)
        if which == "off":
            o = stage1(x["opp"], x["gid"], "d_" + m, m); return x[m] - x["site"] * edge(x["season"], m) - ((o - lg_) if o == o and lg_ == lg_ else 0.0)
        o = stage1(x["opp"], x["gid"], m, m); return x["d_" + m] + x["site"] * edge(x["season"], m) - ((o - lg_) if o == o and lg_ == lg_ else 0.0)

    def stage2(team, gid, which, m):
        r = at[(gid, team)]; prior = [x for x in by_ts[(team, r["season"])] if (x["date"], x["gid"]) < (r["date"], r["gid"])]
        vals = [adj(x, which, m) for x in prior]
        # the previous-season target of an adjusted series is the previous season's mean of that ADJUSTED series, so recompute it the same way
        prev_rows = by_ts.get((team, r["season"] - 1), [])
        target = mean([adj(x, which, m) for x in prev_rows]) if len(prev_rows) >= 10 else league(r["season"], r["date"], m)
        n = len(vals)
        if n == 0:
            return target
        wts = [0.5 ** ((n - 1 - i) / hl) for i in range(n)]; ew = sum(w * v for w, v in zip(wts, vals)) / sum(wts)
        return (n * ew + k * target) / (n + k)
    rng = np.random.default_rng(seed); last = sorted(f0.season.unique())[-2:]
    pool = f0[f0.season.isin(last)]; samp = pool.iloc[rng.choice(len(pool), size=min(n_sample, len(pool)), replace=False)]
    out = {"n_rows": int(len(samp)), "seasons": [int(s) for s in last], "method": "plain-Python loops over raw parquet rows; separate possession, overtime, league, venue, shrink and two-stage code", "columns": {}}
    # pace, free-throw rate and points per 100 possessions (the core of adj_off / adj_def and every expected-points column); all three use the default half-life and shrink weight
    for col, which, m in (("pace_pre", "pace", "pace"), ("off_ftr100_pre", "off", "ftr"), ("def_ftr100_pre", "def", "ftr"), ("off_ortg_pre", "off", "ortg"), ("def_ortg_pre", "def", "ortg")):
        d = [abs(stage2(int(r.team), int(r.game_id), which, m) - getattr(r, col)) for r in samp.itertuples(index=False) if (int(r.game_id), int(r.team)) in at]
        out["columns"][col] = {"n": len(d), "max_abs_diff": float(max(d)), "ok": bool(max(d) < 1e-6)}
    out["ok"] = all(v["ok"] for v in out["columns"].values())
    return out


# ------------------------------------------------------------------ 3 + 4. coverage and out-of-sample evidence
def coverage(f, cols):
    out = {}
    for c in cols:
        s = f[c]; by = s.notna().groupby(f.season).mean(); nn = f.loc[s.notna(), "date"]
        out[c] = {"present": True, "coverage": round(float(s.notna().mean()), 4), "season_cov_min": round(float(by.min()), 4), "seasons_ge_95": int((by >= 0.95).sum()), "seasons": int(len(by)),
                  "first": str(nn.min().date()) if len(nn) else None, "last": str(nn.max().date()) if len(nn) else None, "nunique": int(s.nunique()), "std": float(np.nan_to_num(s.std()))}
    return out


def evidence(t, f, triples):
    seasons = sorted(t.season.unique()); ho = seasons[-HOLDOUT_SEASONS:]; test = t.season.isin(ho).to_numpy(); train = ~test
    res_of = {"ABS_TOTAL_RES": t.total - f.exp_total_pre, "ABS_MARGIN_RES": t.margin - f.exp_margin_pre, "ABS_PTS_RES": t.pts - f.exp_pts_pre}
    out = []
    for pred, target, base in triples:
        p = f[pred].to_numpy(float)
        if target in res_of:                                        # scale forecast: Gaussian negative log-likelihood of the residual, predicted sd vs one constant sd
            r = res_of[target].to_numpy(float); ok = test & np.isfinite(p) & np.isfinite(r) & (p > 0)
            const = float(np.nanstd(r[train & np.isfinite(p)])); nll = lambda sd: float(np.mean(np.log(sd) + 0.5 * (r[ok] / sd) ** 2))
            m, b_ = nll(p[ok]), nll(np.full(ok.sum(), const))
            out.append(dict(pred=pred, target=target.replace("ABS_", "").lower() + "idual", metric="gaussian_nll", baseline="constant sd from earlier seasons", n=int(ok.sum()), value=round(m, 5), baseline_value=round(b_, 5),
                            improvement_pct=round(100 * (b_ - m) / abs(b_), 3), z_sd=round(float(np.std(r[ok] / p[ok])), 3), corr_abs_res=round(float(np.corrcoef(np.abs(r[ok]), p[ok])[0, 1]), 4)))
            continue
        y = t[target].to_numpy(float)
        if base == "BASE_RATE":
            ok = test & np.isfinite(p) & np.isfinite(y); br = float(np.nanmean(y[train])); m, b_ = float(np.mean((p[ok] - y[ok]) ** 2)), float(np.mean((br - y[ok]) ** 2))
            out.append(dict(pred=pred, target=target, metric="brier", baseline="base rate of earlier seasons", n=int(ok.sum()), value=round(m, 6), baseline_value=round(b_, 6), improvement_pct=round(100 * (b_ - m) / b_, 3)))
            continue
        if base == "ZERO":
            bv, bn = np.zeros(len(t)), "zero"
        elif base == "LEAGUE_MEAN":
            sm = pd.Series(y).groupby(t.season.to_numpy()).mean(); bv, bn = t.season.map({s: sm.get(s - 1, np.nan) for s in sm.index}).to_numpy(float), "previous-season league mean"
        elif base == "OWN_RATE_FG3A":
            bv, bn = (f.off_fg3a100_pre * f.exp_poss_pre / 100.0).to_numpy(float), "team's own 3PA rate x expected possessions (no opponent term)"
        else:
            bv, bn = f[base].to_numpy(float), base
        ok = test & np.isfinite(p) & np.isfinite(y) & np.isfinite(bv); rm = lambda v: float(np.sqrt(np.mean((v[ok] - y[ok]) ** 2)))
        m, b_ = rm(p), rm(bv)
        out.append(dict(pred=pred, target=target, metric="rmse", baseline=bn, n=int(ok.sum()), value=round(m, 4), baseline_value=round(b_, 4), improvement_pct=round(100 * (b_ - m) / b_, 3), corr=round(float(np.corrcoef(p[ok], y[ok])[0, 1]), 4)))
    return out, [int(s) for s in ho]


def predictive_label(ev):
    if not ev:
        return "NOT_ASSESSED"
    return "BEATS_NAIVE_BASELINE_OOS" if all(e["improvement_pct"] > 0.25 for e in ev) else "MIXED_VS_NAIVE_BASELINE" if any(e["improvement_pct"] > 0.25 for e in ev) else "NO_GAIN_VS_NAIVE_BASELINE"


def adoption(sport, cid, repos):
    """Code-reference probe only: does the projection repo's production tree mention the same concept? This never proves the same definition is used."""
    if not repos:
        return {"status": "NOT_PROBED"}
    repo, sub = ADOPTION_PROBE[sport]; base = Path(repos) / repo / sub
    rx = next((v for k, v in PROBE_RX.items() if re.search(k, cid)), None)
    if not base.exists() or rx is None:
        return {"status": "NOT_PROBED"}
    hits = sorted(str(p.relative_to(Path(repos))) for p in base.rglob("*.py") if not re.search(r"test|research|archive|signal_discovery", str(p)) and re.search(rx, p.read_text(errors="ignore"), re.I))
    return {"status": "CONCEPT_REFERENCED_IN_PROJECTION_REPO" if hits else "NOT_ADOPTED", "shared_alpha_feature_consumed": False, "probe_regex": rx, "files": hits[:5], "n_files": len(hits),
            "note": "concept match by code reference only; the projection repo does not import alpha_engine.derived"}


def run(paths: dict, repos=None) -> dict:
    R.load_catalog_ids(ROOT); specs = R.specs()
    ms = json.loads((ROOT / "research/audit/market_specs.json").read_text())["families"]
    ci = json.loads(CI.read_text())
    doc = {"schema_version": "derived-inputs-1.0", "status": "RESEARCH_ONLY", "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "engine": "alpha_engine.derived.basketball", "sports": {}, "inputs": []}
    try:
        doc["code_commit"] = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        pass
    for sp, root in paths.items():
        raw, t, f = B.build(root, sp); mine = [s for s in specs if s["sport"] == sp]; cols = sorted({c for s in mine for c in s["columns"]})
        pit = pit_test(raw, sp, t, f, cols); ind = independent_check(root, sp, f); cov = coverage(f, cols)
        doc["sports"][sp] = {"raw": R.RAW[sp], "team_games": int(len(t)), "games": int(t.game_id.nunique()), "seasons": [int(t.season.min()), int(t.season.max())], "last_game_date": str(t.date.max().date()),
                             "feature_columns_verified": len(cols), "pit_test": {k: v for k, v in pit.items() if k != "columns"}, "independent_check": ind}
        for s in mine:
            pc = {c: pit["columns"][c] for c in s["columns"]}
            leak_ok = all(v["identical_on_or_before_cut"] for v in pc.values()) and pit["rows_missing_after_replay"] == 0
            unmoved = [c for c, v in pc.items() if v["share_moved_after_cut"] == 0 and c not in STATIC]
            cv = {c: cov[c] for c in s["columns"]}; lo = min(v["coverage"] for v in cv.values()); const = [c for c, v in cv.items() if v["nunique"] <= 1]
            ev, ho = evidence(t, f, s["evidence"])
            if not leak_ok:
                status, why = "LEAK_DETECTED", "a feature of a row on/before the cut changed when later outcomes were shuffled"
            elif unmoved or const:
                status, why = "UNVERIFIED", f"perturbation did not reach {unmoved} / constant {const}"
            elif not ind["ok"]:
                status, why = "UNVERIFIED", "independent recomputation of the shared primitives disagreed"
            elif lo < 0.5:
                status, why = f"COMPUTED_LIMITED_{s['level']}", f"min column coverage {lo:.2f}"
            else:
                status, why = f"COMPUTED_{s['level']}", ""
            key = f"{sp}:{s['id']}"; prev = ci["inputs"].get(key, {}) if s["kind"] == "catalog" else {}
            fams = [{"family": f"{sp}/{n}", "markets_now": ms.get(f"{sp}/{n}", {}).get("markets_now")} for kind_ in s["families"] for n in R.FAM[sp][kind_]]
            fams = [x for i, x in enumerate(fams) if x not in fams[:i]]
            doc["inputs"].append({"sport": sp, "id": s["id"], "kind": s["kind"], "level": s["level"], "status": status, "reason": why, "previous_status": prev.get("status", "NOT_IN_CATALOG"), "previous_level": prev.get("level"), "ledger_promotion": "PENDING_FOUNDATION_REPLAY" if s["kind"] == "catalog" else "NOT_IN_CATALOG_PROPOSED_INPUT",
                                  "definition": s["definition"], "done": s["done"], "missing": s["missing"], "columns": s["columns"], "pit_class": s["pit"],
                                  "coverage": {"min": lo, "worst_season_min": min(v["season_cov_min"] for v in cv.values()), "first": min(v["first"] for v in cv.values()), "last": max(v["last"] for v in cv.values()), "by_column": cv},
                                  "pit_test": {"ok": leak_ok, "cut": pit["cut"], "max_abs_diff_on_or_before_cut": max(v["max_abs_diff"] for v in pc.values()), "min_share_moved_after_cut": min(v["share_moved_after_cut"] for c, v in pc.items() if c not in STATIC) if any(c not in STATIC for c in pc) else None},
                                  "independent_check": "shared two-stage primitives recomputed independently (see sports.%s.independent_check); composites are closed-form functions of those columns" % sp,
                                  "predictive": {"label": predictive_label(ev), "holdout_seasons": ho, "tests": ev, "scope": "input vs naive baseline only; no projection-model improvement is claimed"},
                                  "lineage": {"raw": s["raw"], "builder": "alpha_engine.derived.basketball.features", "columns": s["columns"], "model_adoption": adoption(sp, s["id"], repos), "kalshi_families": fams}})
    ins = doc["inputs"]; ok = [i for i in ins if i["status"].startswith("COMPUTED")]
    up = [i for i in ok if i["kind"] == "catalog"]
    doc["summary"] = {"inputs_built": len(ins), "verified": len(ok), "by_level": dict(Counter(i["level"] for i in ok)), "by_sport": {sp: sum(1 for i in ok if i["sport"] == sp) for sp in paths},
                      "catalog_newly_computed": sorted(f"{i['sport']}:{i['id']}" for i in up if not i["previous_status"].startswith("COMPUTED")),
                      "catalog_upgraded": sorted(f"{i['sport']}:{i['id']} ({i['previous_status']} -> {i['status']})" for i in up if i["previous_status"].startswith("COMPUTED")),
                      "discovered_new_inputs": sorted(f"{i['sport']}:{i['id']}" for i in ok if i["kind"] == "discovered"),
                      "predictive_labels": dict(Counter(i["predictive"]["label"] for i in ok)), "model_adoption": dict(Counter(i["lineage"]["model_adoption"]["status"] for i in ok)),
                      "kalshi_families_touched": len({x["family"] for i in ok for x in i["lineage"]["kalshi_families"]}),
                      "markets_now_in_touched_families": {sp: sum(ms.get(k, {}).get("markets_now") or 0 for k in {x["family"] for i in ok if i["sport"] == sp for x in i["lineage"]["kalshi_families"]}) for sp in paths}}
    # honest accounting of what is left: calculation-only work versus real acquisition gaps. `certified` = the committed ledger, untouched; `pending` = what it would read once
    # the builder-verified catalog inputs above pass the foundation's own replay and are promoted (never assumed).
    def account(inputs):
        tot = Counter(v["status"] for v in inputs.values()); left = [v for v in inputs.values() if v["status"] == "NOT_COMPUTED"]
        return {"verified_computed": sum(n for st, n in tot.items() if st.startswith("COMPUTED")), "not_computed": len(left), "calculation_only_no_raw_blocker": sum(1 for v in left if not v.get("blockers")),
                "acquisition_gap_raw_class_absent": sum(1 for v in left if v.get("blockers")), "acquisition_gap_by_raw_class": dict(Counter(b for v in left for b in v.get("blockers", [])).most_common()),
                "by_sport": {sp: {"verified_computed": sum(1 for v in inputs.values() if v["sport"] == sp and v["status"].startswith("COMPUTED")), "calculation_only": sum(1 for v in left if v["sport"] == sp and not v.get("blockers")),
                                  "acquisition_gap": sum(1 for v in left if v["sport"] == sp and v.get("blockers"))} for sp in sorted({v["sport"] for v in inputs.values()})}}
    pend = {k: dict(v) for k, v in ci["inputs"].items()}
    for i in up:
        pend[f"{i['sport']}:{i['id']}"].update(status=i["status"], blockers=[])
    doc["accounting"] = {"catalog_inputs": len(ci["inputs"]), "benchmark_only_excluded": sum(1 for v in ci["inputs"].values() if v["status"] == "EXCLUDED_BENCHMARK_ONLY"), "certified_ledger_unchanged": True,
                         "certified": account(ci["inputs"]), "pending_promotion": account(pend),
                         "raw_class_regraded_by_this_build": sorted(f"{i['sport']}:{i['id']} (ledger blockers: {', '.join(ci['inputs'][i['sport'] + ':' + i['id']].get('blockers') or ['none'])})" for i in up
                                                                  if ci["inputs"][f"{i['sport']}:{i['id']}"].get("blockers")),
                         "note": "calculation_only = the keyword-mapped raw classes are graded present and no builder is verified yet (an estimate, not a promise that each is computable); acquisition_gap = at least one required raw data class is graded absent. "
                                 "pending_promotion counts the builder-verified catalog inputs of this artifact as computed; the certified ledger changes only through the foundation replay."}
    attach_governance(doc)
    OUT.write_text(json.dumps(doc, indent=1, default=str))
    return doc


VC = ROOT / "research/input_research/data_foundation/verified_coverage.json"
OPERATING = ROOT / "sift_feed/operating_models.json"
FOUNDATION_FAMILY_FILES = ("NBA_derived.json", "CBB_derived.json")      # foundation replay of THIS builder (data_foundation/verification/replay_ext)


def attach_governance(doc: dict) -> dict:
    """Three separate questions per input, read from the committed ledgers (never written here):
    calculated  = this engine built it and its own checks passed (status COMPUTED_*);
    certified   = the data foundation's verified_coverage ledger holds VERIFIED_FULL / VERIFIED_PARTIAL / VERIFIED_PROXY for the catalog key, and whether that rests on THIS builder's replay;
    consumed    = an operating (promoted) model in sift_feed/operating_models.json reads it. No operating model imports alpha_engine.derived, so this is false for every input."""
    vc = {r["key"]: r for r in json.loads(VC.read_text())["rows"]} if VC.exists() else {}
    ops = json.loads(OPERATING.read_text())["sports"] if OPERATING.exists() else {}
    ext_dir = VC.parent / "verification/replay_ext"
    mine = set()
    for fn in FOUNDATION_FAMILY_FILES:
        if (ext_dir / fn).exists():
            mine |= {f"{json.loads((ext_dir / fn).read_text())['sport']}:{k}" for k in json.loads((ext_dir / fn).read_text())["inputs"]}
    for i in doc["inputs"]:
        key = f"{i['sport']}:{i['id']}"; row = vc.get(key)
        if i["kind"] != "catalog":
            cert = {"status": "NOT_IN_CATALOG", "certified": False, "basis": "proposed input outside the approved catalog: no certification path until the catalog adds it"}
        else:
            vs = row["verified_status"] if row else "NO_LEDGER_ROW"; ev = (row or {}).get("evidence") or {}
            cert = {"status": vs, "certified": vs in ("VERIFIED_FULL", "VERIFIED_PARTIAL", "VERIFIED_PROXY"), "by_this_builder": key in mine and bool(ev.get("promoted_from")),
                    "promoted_from": ev.get("promoted_from"), "full_candidate": bool(ev.get("full_candidate")), "limits": ev.get("limits", [])}
        i["certification"] = cert
        if i["kind"] == "catalog":
            i["ledger_promotion"] = ("CERTIFIED_BY_THIS_BUILDER" if cert.get("by_this_builder") else "CERTIFIED_BY_EARLIER_BUILDER") if cert["certified"] else \
                ("NOT_PROMOTABLE_UNDER_LEDGER_RULES_" + cert["status"] if cert["status"] in ("BLOCKED_CONTESTED", "BLOCKED_CONFIRMED", "BLOCKED_BY_POLICY", "DOWNGRADED_BY_VERIFIER", "PIT_QUARANTINED") else "PENDING_FOUNDATION_REPLAY")
        op = (ops.get(i["sport"]) or {}).get("promoted") or {}
        i["operating_model"] = {"consumed": False, "operating_model": op.get("model_version"), "basis": "no operating model imports alpha_engine.derived; adoption needs a separate approved model change"}
    cat = [i for i in doc["inputs"] if i["kind"] == "catalog"]
    doc["governance"] = {"calculated": sum(1 for i in doc["inputs"] if i["status"].startswith("COMPUTED")), "catalog_inputs": len(cat),
                         "certified_in_foundation": sum(1 for i in cat if i["certification"]["certified"]), "certified_by_this_builder": sum(1 for i in cat if i["certification"].get("by_this_builder")),
                         "certification_status": dict(Counter(i["certification"]["status"] for i in cat)), "consumed_by_operating_model": 0,
                         "ledger": "research/input_research/data_foundation/verified_coverage.json (foundation replay + blind exact match + promotion rules); read only"}
    return doc


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--nba"); ap.add_argument("--cbb"); ap.add_argument("--repos"); ap.add_argument("--governance-only", action="store_true")
    a = ap.parse_args()
    if a.governance_only:          # refresh certification / consumption from the committed ledgers without rebuilding features
        d = attach_governance(json.loads(OUT.read_text())); OUT.write_text(json.dumps(d, indent=1, default=str)); print(json.dumps(d["governance"], indent=1)); raise SystemExit(0)
    d = run({k: v for k, v in (("NBA", a.nba), ("CBB", a.cbb)) if v}, a.repos)
    print(json.dumps({"summary": d["summary"], "accounting": d["accounting"]}, indent=1))
    for i in d["inputs"]:
        print(i["sport"], i["id"], i["status"], "| was", i["previous_status"], "|", i["predictive"]["label"], [(e["pred"], e["improvement_pct"]) for e in i["predictive"]["tests"]], "|", i["lineage"]["model_adoption"]["status"])
