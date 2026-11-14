"""CBB challenger ``alpha-cbb-mean-0.1``: where the frozen game MEANS lose to the market, and a walk-forward
conference / team re-centring of the frozen team scores (RESEARCH_ONLY).

Diagnosis (full sample, descriptive; ``studies`` in the evaluation): the incumbent ``pure-0.2.0`` margin error is not a
uniform compression. Between conference tiers the projected gap is too SMALL (power-conference teams are under-rated
against low-majors) while WITHIN a tier projected margins are too WIDE. The market line shows the same pattern in its
disagreement with the model and none of it in its own residual. Walk-forward, the per-conference version of that
pattern is NOT yet exploitable on two weeks of games (see the committed evaluation).

Challenger (one coherent model for both team scores, so margin and total move together): a ridge regression of the
two team-score residuals ``final - frozen team mean`` of completed games on

* ``conf``  : an offence effect for the scoring team's conference and a defence effect for the opponent's conference;
* ``slope`` : ``+margin/20`` (home row) / ``-margin/20`` (away row), i.e. a margin slope CONDITIONAL on the conference
  effects (total untouched);
* ``team``  : an in-season offence effect for the scoring team and a defence effect for the opponent (opponent-adjusted
  because both are estimated jointly with the conference effects).

Arms: ``C`` = conf, ``CS`` = conf + slope, ``CST`` = conf + slope + team (the designated full arm). Two reference arms
exist ONLY to show what the owner's preregistered waves already cover and are never headline rows: ``LEVEL`` (one
scoring-level constant: the Wave 12 / Wave 14 thread) and ``STRETCH`` (the margin slope alone: Wave 15 A1's mechanism).
No arm here has an explicit level term and no arm is a pure stretch; SDs are the frozen ones.

Walk-forward by slate only: the parameters used for a slate are fitted on games of EARLIER slates whose verified final
was first archived before that slate's first tip. Penalties are fixed constants chosen from prior scales before any
walk-forward score was computed (``PEN``); nothing is tuned.

Inputs (read-only, no network): the four archive branches extracted as in ``cbb_joint_periods`` plus
``espn-lines-archive`` (owner-captured pre-tip line, benchmark only) in the same directory, and the owner's clone
(team ids, model checkpoint tables, ``research/wave12/wave12_game_table.csv`` for box-score possessions of Nov 1-9).
Only ``pure-0.2.0`` records are read; no Wave 14-16 forecast, spec or result is read or produced.
Output aggregates only: ``research/data_foundation_ops/CBB/alpha-cbb-mean-0.1/evaluation.json``. Byte-identical on re-run.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from . import cbb_joint_periods as J
from . import cbb_venue_prior as V
from . import contract as C

CHALLENGER_ID = "alpha-cbb-mean-0.1"
INCUMBENT_ID = "pure-0.2.0"
OUT_DIR = C.OPS / "CBB" / CHALLENGER_ID
CKPT = V.CKPT
WAVE12_TABLE = "research/wave12/wave12_game_table.csv"
ESPN_BRANCH = "espn-lines-archive"
WAVE15_16_WINDOW_OPENS = "2026-11-15"
N_BOOT = 2000
# Ridge penalties in pseudo-rows (team-score rows; one game = two rows). Fixed a priori from prior scales:
# team-score residual variance ~ 113 pts^2; conference offence/defence effect SD ~ 2 pts -> 113/4 ~ 30;
# conditional margin-slope deviation SD ~ 0.2 (coefficient on margin/20 has SD 2) -> 30; team effect SD ~ 1.5 -> 50;
# level 60 rows = the 30 pseudo-games used by the owner's Wave 12 rule (reference arm only).
PEN = dict(level=60.0, conf=30.0, slope=30.0, team=50.0)
BLOCKS = {"LEVEL": ("level",), "STRETCH": ("slope",), "C": ("conf",), "CS": ("conf", "slope"), "CST": ("conf", "slope", "team")}
ARMS = ["C", "CS", "CST"]                 # challenger arms (headline)
REF_ARMS = ["LEVEL", "STRETCH"]           # wave-owned mechanisms, reference only
FULL = "CST"
ARCH = {"game_margin": ["CBB:game_moneyline_spread"], "game_total": ["CBB:game_total"], "game_moneyline": ["CBB:game_moneyline_spread"],
        "game_spread": ["CBB:game_moneyline_spread"]}
# Conference tiers for the DESCRIPTIVE studies only (hand-defined before the tier regressions were run; the challenger
# itself uses one effect per conference, never these lists).
TIER_P = ("Atlantic Coast Conference", "Southeastern Conference", "Big Ten Conference", "Big 12 Conference", "Big East Conference")
TIER_M = ("Atlantic 10 Conference", "Mountain West Conference", "American Conference", "West Coast Conference", "Missouri Valley Conference")


def tier(conf) -> str:
    return "P" if conf in TIER_P else ("M" if conf in TIER_M else "L")


def chk(name, passed, detail, basis="COMPUTED") -> dict:
    return dict(name=name, passed=bool(passed), detail=str(detail), basis=basis)


# ================================================================== pure core
def empty_params() -> dict:
    return dict(n=0, level=0.0, slope=0.0, conf_o={}, conf_d={}, team_o={}, team_d={})


def fit_arm(train: pd.DataFrame, blocks) -> dict:
    """Ridge fit of the stacked team-score residuals (home rows then away rows). Needs columns
    fh, fa, mu_h, mu_a, margin, conf_h, conf_a, home_tid, away_tid. An empty frame returns the no-change parameters."""
    p = empty_params(); n = len(train)
    if n == 0:
        return p
    r = np.concatenate([(train["fh"] - train["mu_h"]).to_numpy(float), (train["fa"] - train["mu_a"]).to_numpy(float)])
    cols, pen, names = [], [], []
    if "level" in blocks:
        cols.append(np.ones(2 * n)); pen.append(PEN["level"]); names.append(("level", None))
    if "slope" in blocks:
        m = train["margin"].to_numpy(float) / 20.0
        cols.append(np.concatenate([m, -m])); pen.append(PEN["slope"]); names.append(("slope", None))
    for blk, hc, ac in (("conf", "conf_h", "conf_a"), ("team", "home_tid", "away_tid")):
        if blk not in blocks:
            continue
        h = train[hc].to_numpy(object); a = train[ac].to_numpy(object)
        for key in sorted({x for x in np.concatenate([h, a]) if isinstance(x, str)}):
            cols.append(np.concatenate([h == key, a == key]).astype(float)); pen.append(PEN[blk]); names.append((blk + "_o", key))
            cols.append(np.concatenate([a == key, h == key]).astype(float)); pen.append(PEN[blk]); names.append((blk + "_d", key))
    X = np.column_stack(cols)
    b = np.linalg.solve(X.T @ X + np.diag(pen), X.T @ r)
    for (kind, key), v in zip(names, b):
        if key is None:
            p[kind] = float(v)
        else:
            p[kind][key] = float(v)
    p["n"] = n
    return p


def walk_forward(games: pd.DataFrame, arms=tuple(BLOCKS)) -> dict:
    """{slate: {arm: params}} fitted on earlier slates whose final was observed before the slate's first tip."""
    out = {}
    for d in sorted(games["slate"].unique()):
        first = games.loc[games["slate"] == d, "tip"].min()
        tr = games[(games["slate"] < d) & (games["obs_at"] < first)]
        out[d] = {a: fit_arm(tr, BLOCKS[a]) for a in arms}
        out[d]["_meta"] = dict(n=int(len(tr)), train_max_slate=None if tr.empty else str(tr["slate"].max()),
                               n_not_yet_archived=int(((games["slate"] < d) & ~(games["obs_at"] < first)).sum()))
    return out


def _lookup(keys, table) -> np.ndarray:
    return np.array([table.get(k, 0.0) if isinstance(k, str) else 0.0 for k in keys], float)


def team_shifts(games: pd.DataFrame, p: dict):
    """(home shift, away shift) in points for one parameter set."""
    m = games["margin"].to_numpy(float) / 20.0
    dh = p["level"] + p["slope"] * m + _lookup(games["conf_h"], p["conf_o"]) + _lookup(games["conf_a"], p["conf_d"]) \
        + _lookup(games["home_tid"], p["team_o"]) + _lookup(games["away_tid"], p["team_d"])
    da = p["level"] - p["slope"] * m + _lookup(games["conf_a"], p["conf_o"]) + _lookup(games["conf_h"], p["conf_d"]) \
        + _lookup(games["away_tid"], p["team_o"]) + _lookup(games["home_tid"], p["team_d"])
    return dh, da


def apply_arm(games: pd.DataFrame, params: dict, arm: str) -> dict:
    """Arrays m, sm, t, st for one arm (``INC`` = the frozen incumbent unchanged). SDs are always the frozen ones."""
    m = games["margin"].to_numpy(float).copy(); t = games["total"].to_numpy(float).copy()
    if arm != "INC":
        sl = games["slate"].to_numpy()
        for d in np.unique(sl):
            idx = np.flatnonzero(sl == d)
            dh, da = team_shifts(games.iloc[idx], params[d][arm])
            m[idx] += dh - da; t[idx] += dh + da
    return dict(m=m, sm=games["msd"].to_numpy(float).copy(), t=t, st=games["tsd"].to_numpy(float).copy())


def contract_probs(rows: pd.DataFrame, arr: dict) -> np.ndarray:
    """Full-game Kalshi contracts in the projection frame: WINNER / MARGIN home P(D>k), away P(D<-k) (k = 0 for
    WINNER); TOTAL P(T>k)."""
    gi = rows["gi"].to_numpy(int); mt = rows["mtype"].to_numpy()
    k = np.where(mt == "WINNER", 0.0, rows["strike"].to_numpy(float))
    m, s, t, st = arr["m"][gi], arr["sm"][gi], arr["t"][gi], arr["st"][gi]
    home = rows["side"].to_numpy() == "home"
    pm = np.where(home, 1.0 - J.phi((k - m) / s), J.phi((-k - m) / s))
    return np.where(mt == "TOTAL", 1.0 - J.phi((k - t) / st), pm)


def settle(rows: pd.DataFrame, games: pd.DataFrame) -> np.ndarray:
    gi = rows["gi"].to_numpy(int); mt = rows["mtype"].to_numpy()
    d = games["y_m"].to_numpy(float)[gi]; tot = games["y_t"].to_numpy(float)[gi]
    k = np.where(mt == "WINNER", 0.0, rows["strike"].to_numpy(float))
    ym = np.where(rows["side"].to_numpy() == "home", d > k, -d > k)
    return np.where(mt == "TOTAL", tot > k, ym).astype(float)


# ================================================================== data
def _frozen_fields(arch: Path, rels) -> pd.DataFrame:
    base = arch / "projections-archive" / "projections"; rows = []
    for rel in rels:
        d = json.loads((base / rel).read_text()); p = d["projection"]; fr = d.get("freshness") or {}
        r = dict(rel=rel, version=d["model"]["version"], conf_h=d["home"].get("conference"), conf_a=d["away"].get("conference"),
                 poss=p.get("possessions"), ppp_h=p.get("home_ppp"), ppp_a=p.get("away_ppp"), hgs=fr.get("home_games_seen"), ags=fr.get("away_games_seen"))
        for s, k in (("h", "home"), ("a", "away")):
            pc = (d.get("player_context") or {}).get(s) or {}
            r["pl_" + s] = (pc.get("player_off") - pc.get("player_def")) if pc.get("player_off") is not None and pc.get("player_def") is not None else np.nan
        rows.append(r)
    return pd.DataFrame(rows)


def load_espn_lines(arch: Path) -> pd.DataFrame:
    rows = []
    for f in sorted(glob.glob(str(arch / ESPN_BRANCH / "snapshots" / "*" / "*" / "*" / "*.jsonl"))):
        with open(f) as fh:
            for line in fh:
                if line.strip():
                    d = json.loads(line)
                    rows.append({k: d.get(k) for k in ("game_id", "captured_at", "home_espn_id", "away_espn_id", "spread", "over_under", "provider")})
    L = pd.DataFrame(rows); L["captured_at"] = J._ts(L["captured_at"]); L["game_id"] = "G" + L["game_id"].astype(str)
    return L


def build(arch: Path, repo: Path):
    teams_csv = repo / "cbb_edge" / "data" / "ids" / "teams.csv"
    g, audit, checks, tips = J.build_games(arch, teams_csv)
    checks = [dict(c, basis="COMPUTED") for c in checks]
    runs = J.load_projection_runs(arch); versions_read = sorted(set(runs.loc[runs["version"] == INCUMBENT_ID, "version"]))
    runs = runs[runs["version"] == INCUMBENT_ID]
    rel = runs.set_index(["game_id", "as_of"])["rel"]
    g = g.copy(); g["rel"] = [rel[(a, b)] for a, b in zip(g["game_id"], g["as_of"])]
    g = g.merge(_frozen_fields(arch, g["rel"]), on="rel", how="left", validate="one_to_one")
    g = g.sort_values(["tip", "game_id"], kind="mergesort").reset_index(drop=True)
    g["y_m"] = g["fh"] - g["fa"]; g["y_t"] = g["fh"] + g["fa"]
    checks.append(chk("only_incumbent_records_read", set(g["version"]) == {INCUMBENT_ID} and versions_read == [INCUMBENT_ID],
                      f"model versions of the {len(g)} frozen records used: {sorted(set(g['version']))}; no pure-0.5.0 / roster-overlay (Wave 14-16 base) record is opened"))
    checks.append(chk("sample_ends_before_wave15_16_window", g["slate"].max() < WAVE15_16_WINDOW_OPENS and bool((g["as_of"] < pd.Timestamp(WAVE15_16_WINDOW_OPENS, tz="UTC")).all()),
                      f"last slate {g['slate'].max()}, latest as_of {g['as_of'].max()}; Waves 15-16 eligibility opens {WAVE15_16_WINDOW_OPENS}T00:00Z"))
    dev = max(float((g["mu_h"] + g["mu_a"] - g["total"]).abs().max()), float((g["mu_h"] - g["mu_a"] - g["margin"]).abs().max()))
    dev2 = max(float((g["poss"] * g["ppp_h"] - g["mu_h"]).abs().max()), float((g["poss"] * g["ppp_a"] - g["mu_a"]).abs().max()))
    checks.append(chk("frozen_team_means_reproduce_margin_total_and_possessions_times_ppp", dev < 1e-6 and dev2 < 1e-6,
                      f"max |mu_h+mu_a-total|, |mu_h-mu_a-margin| = {dev:.2e}; max |possessions*ppp - team mean| = {dev2:.2e} over {len(g)} records"))
    checks.append(chk("final_first_observed_after_tip", bool((g["obs_at"] > g["tip"]).all()), f"{int((g['obs_at'] > g['tip']).sum())} of {len(g)} verified finals were first archived after the scheduled tip (walk-forward clock = first observation)"))
    ncf = int(g["conf_h"].isna().sum() + g["conf_a"].isna().sum())
    checks.append(chk("conference_label_coverage", ncf <= 0.05 * 2 * len(g), f"{2 * len(g) - ncf} of {2 * len(g)} team-game conference labels present in the frozen record ({g['conf_h'].nunique()} home conferences); missing -> no conference effect"))
    # ---- ESPN pre-tip line (owner-captured benchmark), oriented by team id
    L = load_espn_lines(arch); n_snap = len(L)
    tipmap = dict(zip(g["game_id"], g["tip"])); L = L[L["game_id"].isin(tipmap)].copy()
    L = L[L["captured_at"] < L["game_id"].map(tipmap)].sort_values(["captured_at", "game_id"], kind="mergesort").drop_duplicates("game_id", keep="last").set_index("game_id")
    teams = pd.read_csv(teams_csv, usecols=["team_id", "espn_team_id"]).dropna(); t2e = dict(zip(teams["team_id"], teams["espn_team_id"].astype(int)))
    g = g.join(L[["spread", "over_under", "home_espn_id", "captured_at"]].rename(columns={"captured_at": "line_at"}), on="game_id")
    lh = pd.to_numeric(g["home_espn_id"], errors="coerce")
    same = (lh == g["home_tid"].map(t2e)).to_numpy(); swap = (lh == g["away_tid"].map(t2e)).to_numpy() & ~same
    g["mk_m"] = np.where(same, -g["spread"], np.where(swap, g["spread"], np.nan)); g["mk_t"] = g["over_under"].astype(float)
    have = g["spread"].notna()
    checks.append(chk("espn_line_oriented_by_team_id", int((have & ~(same | swap)).sum()) == 0,
                      f"{int(have.sum())} of {len(g)} games have a pre-tip line ({n_snap} snapshots read): {int((have & same).sum())} SAME, {int((have & swap).sum())} SWAPPED (all neutral: {bool((g.loc[have & swap, 'site'] == 'neutral').all())}), {int((have & ~(same | swap)).sum())} unresolved"))
    checks.append(chk("espn_line_captured_before_tip", bool((g.loc[have, "line_at"] < g.loc[have, "tip"]).all()), f"latest snapshot strictly before the scheduled tip for {int(have.sum())} games; benchmark only, never an input"))
    fav_agree = float((np.sign(g.loc[have, "mk_m"]) == np.sign(g.loc[have, "margin"])).mean())
    checks.append(chk("espn_line_sign_convention", fav_agree > 0.85, f"market and model agree on the favourite in {fav_agree:.3f} of games after orientation (a flipped sign convention would give < 0.5)"))
    # ---- owner's Wave 12 game table: box-score possessions for Nov 1-9 (scoring-side descriptive use only)
    w = pd.read_csv(repo / WAVE12_TABLE, usecols=["game_id", "home_final", "away_final", "act_poss"]); w["game_id"] = "G" + w["game_id"].astype(str)
    g = g.join(w.set_index("game_id"), on="game_id")
    hp = g["act_poss"].notna(); okf = int(((g["home_final"] == g["fh"]) & (g["away_final"] == g["fa"]))[hp].sum())
    checks.append(chk("wave12_possession_table_finals_match_verified_finals", okf == int(hp.sum()) and int(hp.sum()) > 0,
                      f"{int(hp.sum())} used games carry box-score possessions in {WAVE12_TABLE} ({len(w)} rows); finals agree with the verified period-score finals in {okf}"))
    # ---- frozen team tables
    net, ret, tmeta = V.team_tables(repo)
    pre = pd.read_parquet(repo / CKPT / "preseason.parquet").set_index("team_id")
    for s, c in (("h", "home_tid"), ("a", "away_tid")):
        g["net26_" + s] = g[c].map(net); g["ret_" + s] = g[c].map(ret); g["pre_" + s] = g[c].map(pre["pre_net"]); g["lost_" + s] = g[c].map(pre["lost_impact"])
    checks.append(chk("checkpoint_tables_match_manifest_sha256", all(tmeta["sha_match"].values()), f"{CKPT}: {tmeta['sha_match']}; preseason table season {tmeta['preseason_season']}, finals through {tmeta['finals_seasons'][1]}"))
    meta = dict(audit=audit["games"], tmeta=tmeta, espn_snapshots=int(n_snap), wave12_rows=int(len(w)), espn_first=str(L["captured_at"].min()), espn_last=str(L["captured_at"].max()))
    return g, checks, tips, meta


def market_rows(arch: Path, games: pd.DataFrame, tips: dict, workers=None):
    panel, kres, _, _, pmeta = J.load_panel(arch, tips, workers)
    gidx = {x: i for i, x in enumerate(games["game_id"])}
    k = panel[panel["game_id"].isin(gidx) & (panel["period"] == "FULL") & panel["mtype"].isin(["WINNER", "MARGIN", "TOTAL"])].copy()
    k["bid"] = pd.to_numeric(k["yes_bid"], errors="coerce"); k["ask"] = pd.to_numeric(k["yes_ask"], errors="coerce")
    k["strike"] = pd.to_numeric(k["strike"], errors="coerce"); k["gi"] = k["game_id"].map(gidx).astype(int)
    lad = k["mtype"].isin(["MARGIN", "TOTAL"])
    bad = lad & (~((k["strike"] * 2) % 2 == 1) | (k["direction"] != "greater"))
    k = k[~bad].copy(); lad = k["mtype"].isin(["MARGIN", "TOTAL"])
    ok_strikes = bool((((k.loc[lad, "strike"] * 2) % 2 == 1) & (k.loc[lad, "direction"] == "greater")).all())
    ht = games["home_tid"].to_numpy()[k["gi"]]; at = games["away_tid"].to_numpy()[k["gi"]]; st = k["subject_tid"].to_numpy()
    tot = (k["mtype"] == "TOTAL").to_numpy()
    by_id = np.where(tot, "none", np.where(st == ht, "home", np.where(st == at, "away", "unresolved")))
    n_unres = int((by_id == "unresolved").sum()); n_flip = int(((by_id != k["side"].to_numpy()) & ~tot & (by_id != "unresolved")).sum())
    k["side"] = by_id; k = k[k["side"] != "unresolved"].reset_index(drop=True)
    k["y"] = settle(k, games)
    kr = k["ticker"].map(kres); have = kr.notna(); agree = int(((kr[have] == "yes").astype(float) == k.loc[have, "y"]).sum())
    k["two_sided"] = (k["bid"] > 0) & (k["ask"] < 1) & (k["ask"] > k["bid"])
    k["mid"] = np.where(k["two_sided"] & ((k["ask"] - k["bid"]) <= J.TIGHT_SPREAD + 1e-9), (k["bid"] + k["ask"]) / 2.0, np.nan)
    k["family"] = k["mtype"].map({"WINNER": "game_moneyline", "MARGIN": "game_spread", "TOTAL": "game_total"})
    cap_ok = bool((J._ts(k["captured_at"]) < games["tip"].to_numpy()[k["gi"]]).all())
    checks = [chk("kalshi_side_resolved_by_subject_team_id", n_unres == 0, f"{len(k) + n_unres} full-game winner/spread/total contracts in used games: {n_flip} winner/spread contracts re-labelled from the schedule frame to the projection frame by subject_team_id; {n_unres} unresolved (dropped)"),
              chk("own_settlement_matches_kalshi_result", agree == int(have.sum()) and int(have.sum()) > 0, f"{int(have.sum())} contracts carry a Kalshi result; {agree} agree with the outcome settled here (winner, spread and total)"),
              chk("ladder_strikes_half_integer_greater_than", ok_strikes, f"{int(bad.sum())} contracts with a whole-number strike or a non-'greater' direction excluded; all {int(lad.sum())} remaining ladder strikes are half-integers"),
              chk("kalshi_quote_strictly_before_tip", cap_ok, f"latest panel observation per contract is before the scheduled tip for all {len(k)} contracts")]
    return k, checks, pmeta


# ================================================================== descriptive studies
def _ols_ci(d: pd.DataFrame, y: str, xs, seed=17) -> dict:
    d = d.dropna(subset=[y] + list(xs)); n = len(d)
    X = np.column_stack([np.ones(n)] + [d[c].to_numpy(float) for c in xs]); yy = d[y].to_numpy(float)
    b = np.linalg.lstsq(X, yy, rcond=None)[0]
    rng = np.random.default_rng(seed); bs = np.empty((N_BOOT, X.shape[1]))
    for i in range(N_BOOT):
        idx = rng.integers(0, n, n); bs[i] = np.linalg.lstsq(X[idx], yy[idx], rcond=None)[0]
    return dict(n=int(n), y=y, coef={c: dict(est=float(v), ci95=[float(np.quantile(bs[:, j], 0.025)), float(np.quantile(bs[:, j], 0.975))]) for j, (c, v) in enumerate(zip(["const"] + list(xs), b))})


def _grp(d: pd.DataFrame, key, cols) -> list:
    out = []
    for kv, s in d.groupby(key, observed=True, sort=True):
        row = dict(group=str(kv), n=int(len(s)))
        for c in cols:
            x = s[c].dropna().to_numpy(float)
            row[c] = float(x.mean()) if len(x) else None
            row[c + "_se"] = float(x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else None
        out.append(row)
    return out


def studies(g: pd.DataFrame, meta: dict) -> dict:
    d = g.copy()
    d["rm"] = d["y_m"] - d["margin"]; d["rt"] = d["y_t"] - d["total"]; d["gm"] = d["mk_m"] - d["margin"]; d["gt"] = d["mk_t"] - d["total"]
    d["km"] = d["y_m"] - d["mk_m"]; d["kt"] = d["y_t"] - d["mk_t"]
    d["th"] = d["conf_h"].map(tier); d["ta"] = d["conf_a"].map(tier); d["tiers"] = d["th"] + d["ta"]
    d["ph"] = (d["th"] == "P").astype(float) - (d["ta"] == "P"); d["lh"] = (d["th"] == "L").astype(float) - (d["ta"] == "L")
    d["neu"] = (d["site"] == "neutral").astype(float); d["gmin"] = np.minimum(d["hgs"], d["ags"]).clip(upper=3)
    d["absm"] = pd.cut(d["margin"].abs(), [0, 5, 10, 16, 24, 100]).astype(str)
    fav = np.sign(d["margin"]); d["fav_resid"] = fav * d["rm"]; d["fav_gap"] = fav * d["gm"]
    d["rh"] = d["fh"] - d["mu_h"]; d["ra"] = d["fa"] - d["mu_a"]
    d["net26_d"] = d["net26_h"] - d["net26_a"]; d["pre_d"] = d["pre_h"] - d["pre_a"]; d["ret_d"] = d["ret_h"] - d["ret_a"]; d["pl_d"] = d["pl_h"] - d["pl_a"]; d["lost_d"] = d["lost_h"] - d["lost_a"]
    d["pe"] = d["act_poss"] - d["poss"]; d["pace_t"] = d["pe"] * (d["ppp_h"] + d["ppp_a"]); d["eff_t"] = d["y_t"] - d["act_poss"] * (d["ppp_h"] + d["ppp_a"])
    d["n_p"] = (d["th"] == "P").astype(float) + (d["ta"] == "P"); d["n_l"] = (d["th"] == "L").astype(float) + (d["ta"] == "L")
    hs = d[d["site"] == "home"]; same = d[d["th"] == d["ta"]]; cross = d[d["th"] != d["ta"]]
    acc = {k: dict(model_mae=float(d[a].abs().mean()), market_mae=float(d[b].abs().mean()), model_rmse=float(np.sqrt((d[a] ** 2).mean())), market_rmse=float(np.sqrt((d[b] ** 2).mean())),
                   model_bias=float(d[a].mean()), market_bias=float(d[b].mean()), corr_with_actual=dict(model=float(np.corrcoef(d[c1], d[yy])[0, 1]), market=float(np.corrcoef(d[c2], d[yy])[0, 1])))
           for k, a, b, c1, c2, yy in (("margin", "rm", "km", "margin", "mk_m", "y_m"), ("total", "rt", "kt", "total", "mk_t", "y_t"))}
    tm = pd.concat([pd.DataFrame(dict(team_tier=d["th"], opp_tier=d["ta"], pts_resid=d["rh"], mkt_implied_gap=(d["gt"] + d["gm"]) / 2)),
                    pd.DataFrame(dict(team_tier=d["ta"], opp_tier=d["th"], pts_resid=d["ra"], mkt_implied_gap=(d["gt"] - d["gm"]) / 2))])
    attrs = ["net26_d", "pre_d", "ret_d", "pl_d", "lost_d", "ph", "lh", "neu"]
    ot = d["ot"] > 0
    return dict(
        note="Descriptive, full sample, NOT used for forecasting. Residual = actual - frozen pure-0.2.0; gap = ESPN pre-tip line - model (home frame); market residual = actual - line. Intervals: pairs bootstrap over games.",
        accuracy_vs_espn_line=acc,
        margin=dict(
            slope_actual_on_model=_ols_ci(d, "y_m", ["margin"]), slope_market_on_model=_ols_ci(d, "mk_m", ["margin"]), slope_actual_on_market=_ols_ci(d, "y_m", ["mk_m"]),
            residual_on_market_gap=_ols_ci(d, "rm", ["gm"]),
            same_tier_games=_ols_ci(same, "y_m", ["margin"]), cross_tier_games=_ols_ci(cross, "y_m", ["margin"]),
            same_tier_games_market_on_model=_ols_ci(same, "mk_m", ["margin"]),
            residual_on_margin_and_tier=_ols_ci(d, "rm", ["margin", "ph", "lh"]), market_gap_on_margin_and_tier=_ols_ci(d, "gm", ["margin", "ph", "lh"]),
            market_residual_on_margin_and_tier=_ols_ci(d, "km", ["margin", "ph", "lh"]),
            by_cohort={c: dict(residual=_ols_ci(s, "rm", ["margin", "ph", "lh"]), market_gap=_ols_ci(s, "gm", ["margin", "ph", "lh"])) for c, s in d.groupby("cohort")},
            home_court=dict(home_site_intercept=_ols_ci(hs, "y_m", ["margin"]), home_site_intercept_with_tier=_ols_ci(hs, "rm", ["margin", "ph", "lh"]),
                            note="const = what is left of home court at a zero projected margin on true home-site games; an interval covering 0 = no detectable mis-sizing"),
            favourite_residual_by_abs_margin=_grp(d, "absm", ["fav_resid", "fav_gap"]),
            tier_note=f"ph / lh = (home is power) - (away is power) / (home is low-major) - (away is low-major). Power = {list(TIER_P)}; mid = {list(TIER_M)}; low = every other conference."),
        attributes=dict(
            one_at_a_time={a: dict(market_gap=_ols_ci(d, "gm", ["margin", a]), residual=_ols_ci(d, "rm", ["margin", a]), market_residual=_ols_ci(d, "km", ["margin", a])) for a in attrs},
            joint=dict(market_gap=_ols_ci(d, "gm", ["margin"] + attrs), residual=_ols_ci(d, "rm", ["margin"] + attrs), market_residual=_ols_ci(d, "km", ["margin"] + attrs)),
            definitions=dict(net26_d="2026 end-of-season net (o-d) difference, frozen checkpoint", pre_d="preseason.parquet pre_net difference (roster-based preseason net)", ret_d="expected returning-minutes share difference",
                             pl_d="frozen record player_context (player_off - player_def) difference", lost_d="lost_impact difference (production that left)", ph="power-conference indicator difference", lh="low-major indicator difference", neu="neutral site")),
        total=dict(
            slope_actual_on_model=_ols_ci(d, "y_t", ["total"]), slope_market_on_model=_ols_ci(d, "mk_t", ["total"]), residual_on_market_gap=_ols_ci(d, "rt", ["gt"]),
            market_gap_on_attributes=_ols_ci(d, "gt", ["total", "poss", "gmin", "n_p", "n_l", "neu"]), residual_on_attributes=_ols_ci(d, "rt", ["total", "poss", "gmin", "n_p", "n_l", "neu"]),
            market_residual_on_attributes=_ols_ci(d, "kt", ["total", "poss", "gmin", "n_p", "n_l", "neu"]),
            overtime=dict(n_overtime=int(ot.sum()), residual_overtime=float(d.loc[ot, "rt"].mean()), residual_regulation=_ols_ci(d[~ot], "rt", [])["coef"]["const"], residual_all=_ols_ci(d, "rt", [])["coef"]["const"],
                          note="overtime games sit far above the frozen total; the regulation-only residual is the part of the level error that is not overtime (whether the frozen total includes an expected-overtime allowance is not stated in the record)"),
            by_tier_pair=_grp(d, "tiers", ["rt", "gt", "kt", "rm", "gm", "km"]), by_abs_margin=_grp(d, "absm", ["rt", "gt", "kt"]), by_min_games_seen=_grp(d, "gmin", ["rt", "gt", "kt", "fav_resid"]),
            by_site=_grp(d, "site", ["rt", "gt", "kt", "rm", "gm", "rh", "ra"]),
            tempo_efficiency=dict(
                note=f"exact split on the games with box-score possessions in the owner's {WAVE12_TABLE} (Nov 1-9): pace = (actual - projected possessions) x projected points per possession; efficiency = the rest",
                all=_grp(d[d["act_poss"].notna()].assign(all="all"), "all", ["pe", "pace_t", "eff_t", "rt", "gt"]),
                regulation_only=_grp(d[d["act_poss"].notna() & ~ot].assign(all="regulation"), "all", ["pe", "pace_t", "eff_t", "rt", "gt"]),
                by_tier_pair=_grp(d[d["act_poss"].notna()], "tiers", ["pe", "pace_t", "eff_t", "rt"]), by_abs_margin=_grp(d[d["act_poss"].notna()], "absm", ["pe", "pace_t", "eff_t", "rt"]),
                by_min_games_seen=_grp(d[d["act_poss"].notna()], "gmin", ["pe", "pace_t", "eff_t", "rt"]),
                possession_error_on_market_total_gap=_ols_ci(d, "pe", ["gt"]), efficiency_term_on_market_total_gap=_ols_ci(d, "eff_t", ["gt"]))),
        team_scores=dict(home=_ols_ci(d, "rh", [])["coef"]["const"], away=_ols_ci(d, "ra", [])["coef"]["const"],
                         by_team_tier_and_opponent_tier=_grp(tm, ["team_tier", "opp_tier"], ["pts_resid", "mkt_implied_gap"])),
        coverage=dict(period_score_games_without_incumbent_projection=meta["audit"].get("period_score_games_without_incumbent_projection"),
                      note="games with a verified final but no pure-0.2.0 record (mostly Division I against non-Division-I opponents) are never projected, so a D1-versus-non-D1 error cannot be measured from this archive"))


# ================================================================== run
def _row(fam, metric, ref, arm, loss_ch, loss_ref, ids, cohorts, headline, universe):
    return V._row(fam, metric, ref, arm, loss_ch, loss_ref, ids, cohorts, headline, universe)


def run(arch: Path, repo: Path, out_dir: Path = OUT_DIR, workers=None):
    if not (arch / ESPN_BRANCH / "snapshots").is_dir():
        raise FileNotFoundError(f"{arch / ESPN_BRANCH}: extract origin/{ESPN_BRANCH} next to the other archive branches")
    g, checks, tips, meta = build(arch, repo)
    cut = J._cohort_of(g["slate"]); g["cohort"] = np.where(g["slate"] < cut, "cohort_1", "cohort_2")
    params = walk_forward(g)
    slates = sorted(params)
    leak_ok = all(params[d]["_meta"]["train_max_slate"] is None or params[d]["_meta"]["train_max_slate"] < d for d in slates)
    checks.append(chk("walk_forward_training_strictly_before_slate", leak_ok, "; ".join(f"{d}: n={params[d]['_meta']['n']}" for d in slates)))
    arr = {a: apply_arm(g, params, a) for a in ["INC"] + list(BLOCKS)}
    first = (g["slate"] == slates[0]).to_numpy()
    checks.append(chk("first_slate_is_the_incumbent_unchanged", all(np.array_equal(arr[a]["m"][first], arr["INC"]["m"][first]) and np.array_equal(arr[a]["t"][first], arr["INC"]["t"][first]) for a in BLOCKS),
                      f"{int(first.sum())} game(s) on {slates[0]} have no earlier final: every arm equals the frozen forecast there"))
    checks.append(chk("standard_deviations_are_the_frozen_ones", all(np.array_equal(arr[a]["sm"], arr["INC"]["sm"]) and np.array_equal(arr[a]["st"], arr["INC"]["st"]) for a in BLOCKS),
                      "margin_sd and total_sd identical to the frozen record in every arm"))
    ids = g["game_id"].to_numpy(); coh = g["cohort"].to_numpy(); ym = g["y_m"].to_numpy(float); yt = g["y_t"].to_numpy(float); win = (ym > 0).astype(float)
    inc = arr["INC"]; REF = f"incumbent:{INCUMBENT_ID}"; LINE = "market:espn_pretip_line"
    results = []
    for a in ARMS + REF_ARMS:
        x = arr[a]; hl = a in ARMS
        results += _row("game_margin", "margin_nll", REF, a, V.norm_nll(ym, x["m"], x["sm"]), V.norm_nll(ym, inc["m"], inc["sm"]), ids, coh, hl, "all_games")
        results += _row("game_total", "total_nll", REF, a, V.norm_nll(yt, x["t"], x["st"]), V.norm_nll(yt, inc["t"], inc["st"]), ids, coh, hl, "all_games")
        results += _row("game_margin", "margin_abs_err", REF, a, np.abs(ym - x["m"]), np.abs(ym - inc["m"]), ids, coh, False, "all_games")
        results += _row("game_total", "total_abs_err", REF, a, np.abs(yt - x["t"]), np.abs(yt - inc["t"]), ids, coh, False, "all_games")
        results += _row("game_moneyline", "brier", REF + "(normal)", a, C.brier_rows(J.phi(x["m"] / x["sm"]), win), C.brier_rows(J.phi(inc["m"] / inc["sm"]), win), ids, coh, a == FULL, "all_games")
    # increment of the challenger structure over the wave-owned reference mechanisms (never headline)
    for a, ref in ((FULL, "LEVEL"), (FULL, "STRETCH"), ("C", "STRETCH")):
        results += _row("game_margin", "margin_nll", f"reference_arm:{ref}", a, V.norm_nll(ym, arr[a]["m"], arr[a]["sm"]), V.norm_nll(ym, arr[ref]["m"], arr[ref]["sm"]), ids, coh, False, "all_games")
        results += _row("game_total", "total_nll", f"reference_arm:{ref}", a, V.norm_nll(yt, arr[a]["t"], arr[a]["st"]), V.norm_nll(yt, arr[ref]["t"], arr[ref]["st"]), ids, coh, False, "all_games")
    # ESPN pre-tip line (point forecasts)
    hm = g["mk_m"].notna().to_numpy(); mkm = g["mk_m"].to_numpy(float); mkt = g["mk_t"].to_numpy(float)
    for a in [FULL, "INC"]:
        results += _row("game_margin", "margin_abs_err", LINE, a, np.abs(ym - arr[a]["m"])[hm], np.abs(ym - mkm)[hm], ids[hm], coh[hm], a == FULL, "espn_line_games")
        results += _row("game_total", "total_abs_err", LINE, a, np.abs(yt - arr[a]["t"])[hm], np.abs(yt - mkt)[hm], ids[hm], coh[hm], a == FULL, "espn_line_games")
    # Kalshi
    k, kchk, pmeta = market_rows(arch, g, tips, workers); checks += kchk
    kc = g["cohort"].to_numpy()[k["gi"]]; kid = k["game_id"].to_numpy(); y = k["y"].to_numpy(float); mid = k["mid"].to_numpy(float)
    pk = {a: contract_probs(k, arr[a]) for a in ["INC", FULL]}
    mkt_rows = []
    for fam in ("game_moneyline", "game_spread", "game_total"):
        m = (k["family"] == fam).to_numpy(); mm = m & np.isfinite(mid)
        results += _row(fam, "brier", REF + "(normal)", FULL, C.brier_rows(pk[FULL][m], y[m]), C.brier_rows(pk["INC"][m], y[m]), kid[m], kc[m], True, "kalshi_listed")
        results += _row(fam, "brier", "market:kalshi_mid", FULL, C.brier_rows(pk[FULL][mm], y[mm]), C.brier_rows(mid[mm], y[mm]), kid[mm], kc[mm], True, "kalshi_listed")
        results += _row(fam, "brier", "market:kalshi_mid", "INC", C.brier_rows(pk["INC"][mm], y[mm]), C.brier_rows(mid[mm], y[mm]), kid[mm], kc[mm], False, "kalshi_listed")
        mkt_rows.append(dict(market_family=fam, contracts=int(m.sum()), games=int(k.loc[m, "game_id"].nunique()), tight_mid=int(mm.sum()), games_with_mid=int(k.loc[mm, "game_id"].nunique()),
                             brier_mid=float(C.brier_rows(mid[mm], y[mm]).mean()), brier_incumbent=float(C.brier_rows(pk["INC"][mm], y[mm]).mean()), brier_full=float(C.brier_rows(pk[FULL][mm], y[mm]).mean())))
    results = V.finalize(results)

    st = studies(g, meta)
    last = params[slates[-1]]
    # final-slate conference net effects (aggregates per conference; not rows)
    cf = last["C"]; conf_net = sorted(((c, cf["conf_o"][c] - cf["conf_d"][c], cf["conf_o"][c] + cf["conf_d"][c]) for c in cf["conf_o"]), key=lambda x: x[1])
    st["walk_forward_last_slate"] = dict(
        slate=slates[-1], n_train=last["_meta"]["n"],
        arm_C_conference_effects=[dict(conference=c, tier=tier(c), net_margin_pts=float(a), total_pts=float(b)) for c, a, b in conf_net],
        arm_C_net_effect_mean_by_tier={t: float(np.mean([a for c, a, _ in conf_net if tier(c) == t])) for t in ("P", "M", "L")},
        slope_conditional_on_conference=dict(coef_per_20pts=last["CS"]["slope"], implied_margin_multiplier=1.0 + last["CS"]["slope"] / 10.0),
        slope_alone_reference=dict(coef_per_20pts=last["STRETCH"]["slope"], implied_margin_multiplier=1.0 + last["STRETCH"]["slope"] / 10.0),
        level_reference_pts_per_team=last["LEVEL"]["level"],
        team_effects=dict(n_teams=len(last[FULL]["team_o"]), sd_offence=float(np.std(list(last[FULL]["team_o"].values()))), sd_defence=float(np.std(list(last[FULL]["team_d"].values())))))
    st["market"] = mkt_rows
    bias = {a: dict(margin_bias=float((ym - arr[a]["m"]).mean()), total_bias=float((yt - arr[a]["t"]).mean()), margin_mae=float(np.abs(ym - arr[a]["m"]).mean()), total_mae=float(np.abs(yt - arr[a]["t"]).mean()),
                    margin_slope=float(np.polyfit(arr[a]["m"], ym, 1)[0])) for a in arr}
    st["arm_summary"] = bias

    hl = [r for r in results if r["headline"]]
    cnt = {v: sum(r["verdict"] == v for r in hl) for v in C.VERDICTS}
    lab = lambda r: f"{r['arm']}:{r['market_family']}/{r['metric']} vs {r['reference']} ({r['universe']})"  # noqa: E731
    fav = [lab(r) for r in hl if r["verdict"] in ("VALIDATED_IMPROVEMENT", "IMPROVED_NOT_VALIDATED")]
    unf = [lab(r) for r in hl if r["verdict"] == "NOT_IMPROVED"]
    val_inc = [r for r in hl if r["verdict"] == "VALIDATED_IMPROVEMENT" and r["reference"].startswith("incumbent")]
    unf_inc = [u for r, u in ((r, lab(r)) for r in hl if r["verdict"] == "NOT_IMPROVED") if r["reference"].startswith("incumbent")]
    # The model structure was chosen after looking at full-sample diagnostics that include both cohorts, so the
    # overall verdict is capped at IMPROVED_NOT_VALIDATED whatever the rows say (rows keep the rule's own verdict).
    overall = "NOT_IMPROVED" if unf_inc and not fav else ("IMPROVED_NOT_VALIDATED" if [f for f in fav if "incumbent" in f] and not unf_inc else "INCONCLUSIVE")

    def hres(a, fam, met, ref=REF, uni=None):
        r = next((r for r in results if r["arm"] == a and r["market_family"] == fam and r["metric"] == met and r["reference"] == ref and r["cohort"] == "pooled" and (uni is None or r["universe"] == uni)), None)
        return "n/a" if r is None else f"{r['challenger']:.4f} vs {r['reference_value']:.4f}, diff {r['diff']:+.4f} [{r['ci95'][0]:+.4f}, {r['ci95'][1]:+.4f}], p_holm {r['p_holm']:.3f}, replicated {r['replicated']}, {r['verdict']} (n={r['n_clusters']})"

    sha = J.git_shas(repo) | {"cbb-edge-finder": _rev(repo, "HEAD"), f"cbb-edge-finder@origin/{ESPN_BRANCH}": _rev(repo, f"origin/{ESPN_BRANCH}")}
    pit = [c for c in checks if any(s in c["name"] for s in ("walk_forward", "first_slate", "as_of", "final_first", "only_incumbent", "sample_ends"))]
    doc = dict(
        schema=C.EVAL_SCHEMA, status="RESEARCH_ONLY", sport="CBB", challenger_id=CHALLENGER_ID, incumbent_id=INCUMBENT_ID,
        data=[
            dict(dataset_id="cbb.projections_archive.pure-0.2.0", repo=J.REPO, path="origin/projections-archive:projections/<season>/<date>/<game_id>/<as_of>.json", rows=int(len(g)),
                 rows_unit="games (latest frozen pre-tip forecast per game; team means, possessions, points per possession, conference, games seen, player context)",
                 first=str(g["tip"].min()), last=str(g["tip"].max()), rights_tier="UNRESOLVED_INTERNAL_ONLY", kind="PROSPECTIVE_CAPTURE"),
            dict(dataset_id="cbb.period_scores_archive", repo=J.REPO, path="origin/period-scores-archive:periods/...", rows=int(len(g)), rows_unit="verified finals used", first=str(g["tip"].min()), last=str(g["tip"].max()),
                 rights_tier="UNRESOLVED_INTERNAL_ONLY", kind="PROSPECTIVE_CAPTURE"),
            dict(dataset_id="cbb.espn_lines_archive", repo=J.REPO, path=f"origin/{ESPN_BRANCH}:snapshots/<yyyy>/<mm>/<dd>/<hhmmss>.jsonl", rows=int(g["mk_m"].notna().sum()), rows_unit="games with a pre-tip line (latest snapshot before tip)",
                 first=meta["espn_first"], last=meta["espn_last"], rights_tier="UNRESOLVED_INTERNAL_ONLY (owner-captured; benchmark only, never an input)", kind="PROSPECTIVE_CAPTURE", snapshots_read=meta["espn_snapshots"]),
            dict(dataset_id="cbb.wave12_game_table.possessions", repo=J.REPO, path=f"main:{WAVE12_TABLE}", rows=int(g["act_poss"].notna().sum()), rows_unit="used games with box-score possessions (descriptive tempo/efficiency split only)",
                 first="2026-11-01", last="2026-11-09", rights_tier="UNRESOLVED_INTERNAL_ONLY (derived from sportsdataverse bulk; already committed by the owner, nothing new collected)", kind="HISTORICAL_BACKFILL"),
            dict(dataset_id="cbb.model_checkpoint.finals_and_preseason", repo=J.REPO, path=f"main:{CKPT}/{{finals,preseason}}.parquet", rows=meta["tmeta"]["finals_rows"] + meta["tmeta"]["preseason_rows"],
                 rows_unit="team-season ratings + team preseason rows (descriptive attribute study only)", first=str(meta["tmeta"]["finals_seasons"][0]), last="2027",
                 rights_tier="UNRESOLVED_INTERNAL_ONLY (derived from sportsdataverse bulk)", kind="HISTORICAL_BACKFILL", sha256=meta["tmeta"]["sha"]),
            dict(dataset_id="cbb.kalshi_panel_archive", repo=J.REPO, path="origin/kalshi-panel-archive:panels/...", rows=int(len(k)), rows_unit="full-game winner/spread/total contracts in used games (latest pre-tip snapshot)",
                 first=str(pmeta["first"]), last=str(pmeta["last"]), rights_tier="KALSHI_PUBLIC_MARKET_DATA_INTERNAL", kind="PROSPECTIVE_CAPTURE"),
        ],
        features=[
            dict(feature_id="conference_offence_defence_effects", catalog_inputs=["CBB:cbb.conf_strength", "CBB:cbb.ratings"],
                 description=f"walk-forward ridge offence and defence effect per conference on the team-score residuals ({PEN['conf']:.0f} pseudo-rows each)",
                 pit_rule="fitted on finals of earlier slates first archived before the slate's first tip; conference label from the frozen pre-tip record", checks=checks),
            dict(feature_id="margin_slope_conditional_on_conference", catalog_inputs=["CBB:cbb.score_resid"],
                 description=f"coefficient on +/- margin/20 estimated jointly with the conference effects ({PEN['slope']:.0f} pseudo-rows); not a stand-alone stretch", pit_rule="same walk-forward clock", checks=pit),
            dict(feature_id="in_season_team_offence_defence_effects", catalog_inputs=["CBB:cbb.ratings", "CBB:cbb.in_season_improvement"],
                 description=f"walk-forward ridge offence / defence effect per team, estimated jointly with opponent and conference effects ({PEN['team']:.0f} pseudo-rows each)",
                 pit_rule="same walk-forward clock; a team with no earlier final gets 0", checks=pit),
            dict(feature_id="market_benchmarks", catalog_inputs=["CBB:m.external_lines"], description="ESPN pre-tip line (margin, total) and Kalshi mids as references; never model inputs",
                 pit_rule="latest observation strictly before the scheduled tip", checks=[c for c in checks if "espn" in c["name"] or "kalshi" in c["name"] or "settlement" in c["name"] or "ladder" in c["name"]]),
        ],
        design=dict(cohort_cut=cut, cohorts="slates before / on-or-after the cut", walk_forward="slate-by-slate; training = earlier slates with the final first observed before the slate's first tip",
                    arms={"C": "conference offence/defence effects", "CS": "C + margin slope conditional on conference", "CST": "CS + in-season team offence/defence effects (designated full arm)",
                          "LEVEL": "REFERENCE ONLY: one scoring-level constant (mechanism owned by cbb-edge-finder Waves 12/14)", "STRETCH": "REFERENCE ONLY: margin slope alone (mechanism owned by Wave 15 A1)"},
                    penalties_pseudo_rows=PEN, penalties_rule="fixed a priori from prior scales (see module constants); never tuned; no grid was run",
                    loss_metrics="normal negative log density of the realised margin / total with the FROZEN SDs (nats); absolute error; Brier (home win; Kalshi contracts)",
                    contract_probabilities="P(D>k) = 1 - Phi((k-m)/margin_sd), k = 0 for winner; P(T>k) = 1 - Phi((k-t)/total_sd); incumbent reference = same formula on its own frozen means",
                    headline_rule="headline rows = arms C/CS/CST margin and total NLL vs incumbent; CST moneyline Brier; CST Kalshi Brier vs incumbent and vs mid; CST abs error vs the ESPN line. Holm across headline rows; verdict_from(); other rows Bonferroni by the headline count",
                    selection_disclosure="The STRUCTURE (conference effects, conditional slope) was chosen after full-sample descriptive regressions that include both cohorts; parameters are walk-forward but the choice of structure is not. The overall verdict is therefore capped at IMPROVED_NOT_VALIDATED.",
                    wave_separation=dict(
                        wave14="pw-level-0.5.0-v1 shifts the pure-0.5.0 TOTAL by beta*prior_weight*possessions on records from 2026-11-11T22:00Z; margin untouched. Here: no level term, no prior-weight input, base pure-0.2.0; the LEVEL reference arm is reported only to show what a level explains and is owned by Waves 12/14.",
                        wave15="A1 stretches the pure-0.5.0 margin by one walk-forward slope; A2 rescales margin SD by |margin|; window opens 2026-11-15. Here: the slope is estimated jointly with conference effects (walk-forward value in studies.walk_forward_last_slate), SDs are frozen; the STRETCH reference arm is Wave 15's mechanism on another base and is never a headline row.",
                        wave16="rcenter-0.5.0r-v1 removes the roster overlay's mean margin offset; window opens 2026-11-15. Here: no roster-overlay record is read and no global margin intercept is fitted.",
                        untouched="no Wave 14-16 file, forecast, spec or result was read by this module, modified or re-run; the sample ends before the Waves 15-16 window opens")),
        games=dict(used=int(len(g)), slates=int(g["slate"].nunique()), first_tip=str(g["tip"].min()), last_tip=str(g["tip"].max()), neutral=int((g["site"] == "neutral").sum()),
                   cohort_1=int((g["cohort"] == "cohort_1").sum()), cohort_2=int((g["cohort"] == "cohort_2").sum()), period_score_audit=meta["audit"]),
        results=results, studies=st,
        walk_forward_params={d: dict(params[d]["_meta"], level_ref=params[d]["LEVEL"]["level"], stretch_ref=params[d]["STRETCH"]["slope"], slope_cs=params[d]["CS"]["slope"],
                                     n_conferences=len(params[d]["C"]["conf_o"]), n_teams=len(params[d][FULL]["team_o"])) for d in slates},
        verdict=dict(overall=overall, headline_counts=cnt, favourable=fav, unfavourable=unf, validated_rows_vs_incumbent=len(val_inc),
                     reason=f"{len(hl)} headline pooled comparisons (Holm): {cnt}. Structure chosen on full-sample diagnostics, so the overall verdict cannot exceed IMPROVED_NOT_VALIDATED; one season, {g['slate'].nunique()} slates."),
        limitations=[
            f"{len(g)} games over {g['slate'].nunique()} slates of one November; early-season non-conference play only (2 same-conference games), so conference effects are identified from cross-conference games and will be re-learned differently once league play starts.",
            "The model structure was selected after full-sample descriptive regressions (both cohorts). Walk-forward protects the parameters, not the choice of structure; treat every favourable row as exploratory until a prospective, preregistered run confirms it.",
            "SDs are the frozen ones: a better mean with an unchanged SD slightly understates the challenger's density gain and leaves calibration to the incumbent.",
            "Tempo versus efficiency uses box-score possessions for Nov 1-9 only (owner's committed Wave 12 table); later games have no possession count in any committed archive.",
            "The ESPN line is one book's free line captured by the owner (rights unresolved; benchmark only). Kalshi quotes are latest pre-tip snapshots; mids are not executable; fees not modelled; nothing here is a profitability claim.",
            "No multi-season game-level lake is committed, so none of this can be checked on earlier Novembers; see research/data_foundation_ops/CBB/MULTISEASON_GAME_DATA_SPEC.md.",
            "Games against non-Division-I opponents have no frozen projection and are outside the sample.",
        ],
        input_stage_claims=[
            dict(input="CBB:cbb.conf_strength", stage="EVALUATED", outcome="PARTIAL", evidence=f"Arm C (conference effects): margin NLL {hres('C', 'game_margin', 'margin_nll')}; total NLL {hres('C', 'game_total', 'total_nll')}."),
            dict(input="CBB:cbb.in_season_improvement", stage="EVALUATED", outcome="PARTIAL", evidence=f"Arm CST (conference + conditional slope + team effects): margin NLL {hres(FULL, 'game_margin', 'margin_nll')}; total NLL {hres(FULL, 'game_total', 'total_nll')}; vs ESPN line margin abs err {hres(FULL, 'game_margin', 'margin_abs_err', LINE)}."),
            dict(input="CBB:cbb.score_resid", stage="EVALUATED", outcome="PARTIAL", evidence=f"Arm CS (conditional slope): margin NLL {hres('CS', 'game_margin', 'margin_nll')}."),
        ],
        source_commits=sha,
    )
    errs = C.validate_evaluation(doc)
    if errs:
        raise ValueError(f"evaluation.json violates the contract: {errs}")
    bad_basis = [c["name"] for f in doc["features"] for c in f["checks"] if c.get("basis") not in ("COMPUTED", "ATTESTED")]
    if bad_basis:
        raise ValueError(f"checks without a basis: {bad_basis}")
    out_dir.mkdir(parents=True, exist_ok=True)
    C.write_json(out_dir / "evaluation.json", doc)
    return doc


def _rev(repo, ref):
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", ref], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arch", default=os.environ.get("SIFT_CBB_ARCH_DIR"))
    ap.add_argument("--repo", default=str(C.repos_dir() / "cbb-edge-finder"))
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args(argv)
    if not a.arch:
        ap.error("--arch or SIFT_CBB_ARCH_DIR is required")
    doc = run(Path(a.arch), Path(a.repo), Path(a.out), a.workers)
    print(f"games {doc['games']['used']}; overall {doc['verdict']['overall']}")
    for r in doc["results"]:
        if r["cohort"] == "pooled":
            print(f"  {'*' if r['headline'] else ' '} {r['arm']:7s} {r['universe']:15s} {r['market_family']:14s} {r['metric']:14s} vs {r['reference'][:34]:34s} n={r['n_clusters']:4d} "
                  f"ch={r['challenger']:.4f} ref={r['reference_value']:.4f} d={r['diff']:+.4f} [{r['ci95'][0]:+.4f},{r['ci95'][1]:+.4f}] ph={r['p_holm']:.3f} rep={int(r['replicated'])} {r['verdict']}")


if __name__ == "__main__":
    main()
