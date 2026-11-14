"""CBB challenger ``alpha-cbb-venue-prior-0.1``: early-season uncertainty, venue and preseason-prior adjustments (RESEARCH_ONLY).

Four walk-forward adjustments to the FROZEN incumbent ``pure-0.2.0`` game forecast (margin, total, two SDs), each
estimated slate by slate only from games whose final was archived before the first tip of the slate being forecast:

* ``S`` (early-season sigma): margin / total SD scale ``k`` with ``k^2 = (sum z^2 + N0) / (n + N0)``, z = error / frozen SD.
  The incumbent's margin SD comes from ``sigma_margin_by_games[min(home_games_seen, away_games_seen)]`` (12.80 at 0 games).
* ``V`` (venue): neutral-site minus home-site mean residual (margin and total), shrunk by ``K_VENUE`` pseudo-games and
  added to neutral-site games only.
* ``P`` (historical prior weight): ridge term on ``w_h * net_h - w_a * net_a`` where ``net`` is the team's END-OF-2026
  rating (o - d) frozen in the owner's model checkpoint and ``w = exp(-games_seen / 6)``. A positive coefficient means
  the incumbent UNDER-weights last season early on; negative means it over-weights it.
* ``R`` (roster turnover): ridge term on ``w_h * ret_h - w_a * ret_a`` with ``ret`` = expected returning-minutes share
  frozen in the checkpoint's 2027 ``preseason.parquet`` (built at the 2026 boundary, i.e. before the season).

``FULL`` = all four. Every arm is scored against the incumbent's own frozen forecast and the full arm also against the
latest pre-tip Kalshi mid. Outcomes are verified period-score finals, extended with schedule-archive finals for games
the period-score archive has not reached yet (orientation verified by team id in both).

Inputs (read-only, no network): the four archive branches extracted as in ``cbb_joint_periods`` plus the owner's
clone (team id table and model checkpoints). Outputs aggregates only:
``research/data_foundation_ops/CBB/alpha-cbb-venue-prior-0.1/evaluation.json``. Byte-identical on re-run.

    python -m alpha_engine.foundation.cbb_venue_prior --arch $A
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import cbb_joint_periods as J
from . import contract as C

CHALLENGER_ID = "alpha-cbb-venue-prior-0.1"
INCUMBENT_ID = "pure-0.2.0"
OUT_DIR = C.OPS / "CBB" / CHALLENGER_ID
CKPT = "models/pure/checkpoints/pure-0.5.0/boundary_2026"
N0_SIGMA = 60.0       # pseudo-games at k = 1
K_VENUE = 30.0        # pseudo-games at a zero neutral-minus-home offset
RIDGE = 100.0         # pseudo-games at a zero coefficient (features standardised by fixed scales)
SCALE = dict(prior=10.0, ret=0.10)
FADE_GAMES = 6.0
N_BOOT = 2000
ARMS = ["S", "V", "P", "R", "FULL"]
ARCH = {"game_margin": ["CBB:game_moneyline_spread"], "game_total": ["CBB:game_total"], "game_moneyline": ["CBB:game_moneyline_spread"],
        "game_spread": ["CBB:game_moneyline_spread"]}
LN2PI = math.log(2 * math.pi)


# ================================================================== pure core
def norm_nll(y, m, s):
    s = np.asarray(s, float); z = (np.asarray(y, float) - m) / s
    return 0.5 * z ** 2 + np.log(s) + 0.5 * LN2PI


def fade(gs):
    return np.exp(-np.asarray(gs, float) / FADE_GAMES)


def features(g: pd.DataFrame) -> np.ndarray:
    xp = (fade(g["hgs"]) * g["net_h"] - fade(g["ags"]) * g["net_a"]) / SCALE["prior"]
    xr = (fade(g["hgs"]) * g["ret_h"] - fade(g["ags"]) * g["ret_a"]) / SCALE["ret"]
    return np.column_stack([xp, xr]).astype(float)


def fit_adjust(train: pd.DataFrame) -> dict:
    """All arm parameters from completed games (columns margin,total,msd,tsd,y_m,y_t,site,hgs,ags,net_*,ret_*).
    An empty frame returns the no-change prior exactly."""
    n = len(train)
    if n == 0:
        return dict(n=0, k_m=1.0, k_t=1.0, v_m=0.0, v_t=0.0, b_prior=0.0, b_ret=0.0, n_neutral=0)
    rm = (train["y_m"] - train["margin"]).to_numpy(float); rt = (train["y_t"] - train["total"]).to_numpy(float)
    k_m = math.sqrt((float(np.sum((rm / train["msd"]) ** 2)) + N0_SIGMA) / (n + N0_SIGMA))
    k_t = math.sqrt((float(np.sum((rt / train["tsd"]) ** 2)) + N0_SIGMA) / (n + N0_SIGMA))
    neu = (train["site"] == "neutral").to_numpy(); nn = int(neu.sum())
    v_m = v_t = 0.0
    if nn and (~neu).any():
        sh = nn / (nn + K_VENUE)
        v_m = sh * float(rm[neu].mean() - rm[~neu].mean()); v_t = sh * float(rt[neu].mean() - rt[~neu].mean())
    X = features(train); ok = np.isfinite(X).all(1)
    X, r = X[ok], rm[ok]
    b = np.linalg.solve(X.T @ X + RIDGE * np.eye(2), X.T @ r) if len(r) else np.zeros(2)
    return dict(n=n, k_m=k_m, k_t=k_t, v_m=v_m, v_t=v_t, b_prior=float(b[0]), b_ret=float(b[1]), n_neutral=nn)


def walk_forward(games: pd.DataFrame) -> dict:
    """{slate: params} fitted on games of earlier slates whose final was observed before the slate's first tip."""
    out = {}
    for d in sorted(games["slate"].unique()):
        first = games.loc[games["slate"] == d, "tip"].min()
        tr = games[(games["slate"] < d) & (games["obs_at"] < first)]
        p = fit_adjust(tr); p["train_max_slate"] = None if tr.empty else str(tr["slate"].max())
        p["n_not_yet_archived"] = int(((games["slate"] < d) & ~(games["obs_at"] < first)).sum())
        out[d] = p
    return out


def apply_arm(games: pd.DataFrame, params: dict, arm: str) -> dict:
    """Arrays m, s_m, t, s_t for one arm (``INC`` = the frozen incumbent unchanged)."""
    P = pd.DataFrame([params[d] for d in games["slate"]])
    m = games["margin"].to_numpy(float).copy(); t = games["total"].to_numpy(float).copy()
    sm = games["msd"].to_numpy(float).copy(); st = games["tsd"].to_numpy(float).copy()
    use = set(ARMS[:-1]) if arm == "FULL" else ({arm} if arm != "INC" else set())
    if "S" in use:
        sm *= P["k_m"].to_numpy(); st *= P["k_t"].to_numpy()
    if "V" in use:
        neu = (games["site"] == "neutral").to_numpy()
        m += np.where(neu, P["v_m"].to_numpy(), 0.0); t += np.where(neu, P["v_t"].to_numpy(), 0.0)
    X = np.nan_to_num(features(games))
    if "P" in use:
        m += P["b_prior"].to_numpy() * X[:, 0]
    if "R" in use:
        m += P["b_ret"].to_numpy() * X[:, 1]
    return dict(m=m, sm=sm, t=t, st=st)


def contract_probs(rows: pd.DataFrame, arr: dict) -> np.ndarray:
    """Full-game WINNER / MARGIN contracts in the projection frame: home P(D>t), away P(D<-t), t = 0 for WINNER."""
    gi = rows["gi"].to_numpy(int); m = arr["m"][gi]; s = arr["sm"][gi]
    t = np.where(rows["mtype"].to_numpy() == "WINNER", 0.0, rows["strike"].to_numpy(float))
    home = rows["side"].to_numpy() == "home"
    return np.where(home, 1.0 - J.phi((t - m) / s), J.phi((-t - m) / s))


# ================================================================== data
def team_tables(repo: Path):
    ck = repo / CKPT; man = json.load(open(ck / "manifest.json"))["files"]
    fin = pd.read_parquet(ck / "finals.parquet"); pre = pd.read_parquet(ck / "preseason.parquet")
    f26 = fin[fin["season"] == 2026]
    net = dict(zip(f26["team_id"], f26["o"] - f26["d"])); ret = dict(zip(pre["team_id"], pre["ret_min"]))
    sha = {k: C.sha256_file(ck / k) for k in ("finals.parquet", "preseason.parquet")}
    meta = dict(finals_rows=int(len(fin)), finals_seasons=[int(fin["season"].min()), int(fin["season"].max())], finals_n_seasons=int(fin["season"].nunique()),
                preseason_rows=int(len(pre)), preseason_season=int(pre["season"].iloc[0]), sha_match={k: man.get(k) == v for k, v in sha.items()}, sha=sha)
    return net, ret, meta


def games_seen(arch: Path) -> dict:
    out = {}
    base = arch / "projections-archive" / "projections"
    for f in sorted(base.glob("[0-9]*/*/*/*.json")):
        d = json.load(open(f))
        if d["model"]["version"] == INCUMBENT_ID:
            fr = d.get("freshness") or {}
            out[os.path.relpath(f, base)] = (fr.get("home_games_seen"), fr.get("away_games_seen"))
    return out


def build(arch: Path, repo: Path):
    teams_csv = repo / "cbb_edge" / "data" / "ids" / "teams.csv"
    ver, audit, checks, tips = J.build_games(arch, teams_csv)
    ver = ver.assign(src="period_scores")
    # ---- extension: schedule-archive finals for projected games the period-score archive has not reached
    runs = J.load_projection_runs(arch); runs = runs[runs["version"] == INCUMBENT_ID].copy()
    runs["tip"] = J._ts(runs["game_id"].map(tips))
    sel, _ = J.select_latest_pretip(runs[runs["tip"].notna()])
    sel = sel[~sel["game_id"].isin(ver["game_id"]) & (sel["tip"] > ver["tip"].max())]
    sched = J.load_schedule_rows(arch)
    sched["game_id"] = sched["game_id"].astype(str)
    fin = sched[sched["status_type_name"] == "STATUS_FINAL"].sort_values(["game_id", "observed_at"], kind="mergesort")
    first_obs = fin.groupby("game_id")["observed_at"].first()
    fin = fin.drop_duplicates("game_id", keep="last").set_index("game_id")
    teams = pd.read_csv(teams_csv, usecols=["team_id", "espn_team_id"]).dropna(); t2e = dict(zip(teams["team_id"], teams["espn_team_id"].astype(int)))
    ext, n_unver, n_swap = [], 0, 0
    for r in sel.itertuples():
        key = str(r.espn)
        if key not in fin.index:
            continue
        f = fin.loc[key]; eh, ea = t2e.get(r.home_tid), t2e.get(r.away_tid)
        hid, aid = float(f["home_id"]), float(f["away_id"])
        if eh == hid and ea == aid:
            fh, fa = f["home_score"], f["away_score"]
        elif eh == aid and ea == hid and r.site == "neutral":
            fh, fa = f["away_score"], f["home_score"]; n_swap += 1
        else:
            n_unver += 1; continue
        ext.append(dict(game_id=r.game_id, espn=r.espn, tip=r.tip, as_of=r.as_of, site=r.site, home_tid=r.home_tid, away_tid=r.away_tid,
                        margin=r.margin, total=r.total, msd=r.msd, tsd=r.tsd, hw=r.hw, fh=float(fh), fa=float(fa), obs_at=first_obs[key], rel=r.rel, src="schedule_final"))
    ext = pd.DataFrame(ext)
    ext["slate"] = (ext["tip"] - pd.Timedelta(hours=J.SLATE_SHIFT_H)).dt.strftime("%Y-%m-%d")
    obs_ok = bool((ext["obs_at"] > ext["tip"]).all()); asof_ok = bool((ext["as_of"] < ext["tip"]).all())
    plaus = bool((ext[["fh", "fa"]].min(axis=None) >= 20) and (ext[["fh", "fa"]].max(axis=None) <= 160) and (ext["fh"] != ext["fa"]).all())
    checks.append(C.check(name="extension_schedule_finals_orientation_by_team_id", passed=n_unver == 0,
                       detail=f"{len(ext)} games after the last period-score tip with a schedule-archive STATUS_FINAL row: {n_swap} neutral-site SWAPPED (remapped), {n_unver} unverified (dropped)"))
    checks.append(C.check(name="extension_final_first_observed_after_tip_and_projection_before_tip", passed=obs_ok and asof_ok,
                       detail=f"final first observed after scheduled tip: {obs_ok}; as_of < tip: {asof_ok}; walk-forward uses the FIRST final observation time"))
    checks.append(C.check(name="extension_score_plausibility_no_tied_final", passed=plaus, detail=f"{len(ext)} extension finals in 20-160, none tied: {plaus}"))
    # verified games: the walk-forward availability clock is the period-score observation time
    keep = ["game_id", "espn", "tip", "as_of", "slate", "site", "home_tid", "away_tid", "margin", "total", "msd", "tsd", "hw", "fh", "fa", "obs_at", "src"]
    rel = runs.set_index(["game_id", "as_of"])["rel"]
    ver["rel"] = [rel[(g, a)] for g, a in zip(ver["game_id"], ver["as_of"])]
    g = pd.concat([ver[keep + ["rel"]], ext[keep + ["rel"]]], ignore_index=True).sort_values(["tip", "game_id"], kind="mergesort").reset_index(drop=True)
    gs = games_seen(arch)
    g["hgs"] = [gs[r][0] for r in g["rel"]]; g["ags"] = [gs[r][1] for r in g["rel"]]
    gmin = np.minimum(g["hgs"], g["ags"]).clip(upper=11).astype(int)
    model = json.load(open(repo / "models" / "pure" / f"{INCUMBENT_ID}.json"))
    sig = gmin.map(lambda k: model["sigma_margin_by_games"][str(k)])
    checks.append(C.check(name="frozen_margin_sd_equals_sigma_by_min_games_seen", passed=bool(np.allclose(sig, g["msd"], atol=1e-9)),
                       detail=f"{int(np.isclose(sig, g['msd'], atol=1e-9).sum())} of {len(g)} frozen margin SDs equal sigma_margin_by_games[min(home,away games_seen)] of models/pure/{INCUMBENT_ID}.json"))
    g["y_m"] = g["fh"] - g["fa"]; g["y_t"] = g["fh"] + g["fa"]
    return g, audit, checks, tips, dict(extension_games=len(ext), extension_first_tip=str(ext["tip"].min()), extension_last_tip=str(ext["tip"].max()),
                                        sched_rows=int(len(sched)), sched_last_obs=str(sched["observed_at"].max()))


# ================================================================== evaluation helpers
def _boot_ratio(num, den, clusters, seed=11):
    rng = np.random.default_rng(seed); n = len(num)
    idx = rng.integers(0, n, size=(N_BOOT, n))
    r = np.sqrt(num[idx].sum(1) / den[idx].sum(1))
    return [float(np.quantile(r, 0.025)), float(np.quantile(r, 0.975))]


def _mean_ci(x, seed=13):
    x = np.asarray(x, float); rng = np.random.default_rng(seed)
    b = x[rng.integers(0, len(x), size=(N_BOOT, len(x)))].mean(1)
    return dict(n=int(len(x)), mean=float(x.mean()), ci95=[float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975))])


def _row(fam, metric, ref, arm, loss_ch, loss_ref, games_ids, cohorts, headline, universe):
    per = {}
    for coh in ("pooled", "cohort_1", "cohort_2"):
        m = np.ones(len(loss_ch), bool) if coh == "pooled" else cohorts == coh
        if m.sum() == 0 or len(set(games_ids[m])) < 3:
            continue
        bs = C.paired_cluster_bootstrap(loss_ch[m] - loss_ref[m], games_ids[m], n_boot=N_BOOT, seed=7)
        per[coh] = (bs, float(loss_ch[m].mean()), float(loss_ref[m].mean()))
    signs = [np.sign(per[c][0]["mean"]) for c in ("pooled", "cohort_1", "cohort_2") if c in per]
    rep = bool(len(signs) == 3 and signs[0] != 0 and signs[0] == signs[1] == signs[2])
    return [dict(market_family=fam, archetypes=ARCH[fam], universe=universe, metric=metric, arm=arm, reference=ref, cohort=c, n_rows=bs["n_rows"], n_clusters=bs["n_clusters"],
                 challenger=ch, reference_value=rf, diff=bs["mean"], ci95=[bs["lo"], bs["hi"]], p_raw=bs["p_two_sided"], p_holm=1.0, replicated=rep,
                 headline=bool(headline and c == "pooled"), verdict="INCONCLUSIVE") for c, (bs, ch, rf) in per.items()]


def finalize(results):
    hl = [r for r in results if r["headline"]]
    for r, ph in zip(hl, C.holm([r["p_raw"] for r in hl])):
        r["p_holm"] = float(ph)
    for r in results:
        if not r["headline"]:
            r["p_holm"] = float(min(1.0, r["p_raw"] * max(1, len(hl))))   # conservative Bonferroni for non-headline rows
        r["verdict"] = C.verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"])
    return results


def load_market_rows(arch, games, tips, workers=None):
    panel, kres, _, _, pmeta = J.load_panel(arch, tips, workers)
    gidx = {g: i for i, g in enumerate(games["game_id"])}
    k = panel[panel["game_id"].isin(gidx) & (panel["period"] == "FULL") & panel["mtype"].isin(["WINNER", "MARGIN"])].copy()
    k["bid"] = pd.to_numeric(k["yes_bid"], errors="coerce"); k["ask"] = pd.to_numeric(k["yes_ask"], errors="coerce")
    k["strike"] = pd.to_numeric(k["strike"], errors="coerce"); k["gi"] = k["game_id"].map(gidx).astype(int)
    k = k[k["side"].isin(["home", "away"])].copy()
    bad = (k["mtype"] == "MARGIN") & (~((k["strike"] * 2) % 2 == 1) | (k["direction"] != "greater"))
    k = k[~bad].copy()
    ht = games["home_tid"].to_numpy()[k["gi"]]; at = games["away_tid"].to_numpy()[k["gi"]]; st = k["subject_tid"].to_numpy()
    by_id = np.where(st == ht, "home", np.where(st == at, "away", "unresolved"))
    n_flip = int(((by_id != k["side"].to_numpy()) & (by_id != "unresolved")).sum()); n_unres = int((by_id == "unresolved").sum())
    flip_games = int(k.loc[(by_id != k["side"].to_numpy()) & (by_id != "unresolved"), "game_id"].nunique())
    k["side"] = by_id; k = k[k["side"] != "unresolved"].reset_index(drop=True)
    d = (games["fh"] - games["fa"]).to_numpy(float)[k["gi"]]
    t = np.where(k["mtype"] == "WINNER", 0.0, k["strike"].to_numpy(float))
    k["y"] = np.where(k["side"] == "home", d > t, -d > t).astype(float)
    kr = k["ticker"].map(kres); have = kr.notna()
    agree = int(((kr[have] == "yes").astype(float) == k.loc[have, "y"]).sum())
    k["two_sided"] = (k["bid"] > 0) & (k["ask"] < 1) & (k["ask"] > k["bid"])
    k["tight"] = k["two_sided"] & ((k["ask"] - k["bid"]) <= J.TIGHT_SPREAD + 1e-9)
    k["mid"] = np.where(k["tight"], (k["bid"] + k["ask"]) / 2.0, np.nan)
    k["family"] = np.where(k["mtype"] == "WINNER", "game_moneyline", "game_spread")
    chk = [C.check(name="kalshi_side_resolved_by_subject_team_id", passed=n_unres == 0,
                detail=f"{len(k) + n_unres} full-game winner/spread contracts in used games: {n_flip} contracts in {flip_games} neutral-site games carried the schedule-frame home/away label and were re-labelled by subject_team_id; {n_unres} unresolved (dropped)"),
           C.check(name="own_settlement_matches_kalshi_result", passed=agree == int(have.sum()),
                detail=f"{int(have.sum())} contracts carry a Kalshi result; {agree} agree with the outcome settled here"),
           C.check(name="non_half_integer_or_non_greater_spread_strikes_excluded", passed=True, basis="ATTESTED", detail=f"{int(bad.sum())} excluded")]
    return k, chk, pmeta


# ================================================================== run
def run(arch: Path, repo: Path, out_dir: Path = OUT_DIR, workers=None):
    g, audit, checks, tips, ext_meta = build(arch, repo)
    net, ret, tmeta = team_tables(repo)
    g["net_h"] = g["home_tid"].map(net); g["net_a"] = g["away_tid"].map(net); g["ret_h"] = g["home_tid"].map(ret); g["ret_a"] = g["away_tid"].map(ret)
    cov = dict(prior_net_both=int((g["net_h"].notna() & g["net_a"].notna()).sum()), ret_min_both=int((g["ret_h"].notna() & g["ret_a"].notna()).sum()))
    checks.append(C.check(name="checkpoint_tables_match_manifest_sha256", passed=all(tmeta["sha_match"].values()), detail=f"{CKPT}: {tmeta['sha_match']}"))
    checks.append(C.check(name="checkpoint_tables_frozen_before_season", passed=tmeta["preseason_season"] == 2027 and tmeta["finals_seasons"][1] == 2026,
                       detail=f"finals.parquet: {tmeta['finals_rows']} team-seasons {tmeta['finals_seasons']} (end-of-season ratings, last = 2026, i.e. before the 2026-27 season); preseason.parquet: {tmeta['preseason_rows']} teams, season {tmeta['preseason_season']} built at the 2026 boundary"))
    checks.append(C.check(name="team_feature_coverage", passed=True, basis="ATTESTED", detail=f"{len(g)} games: prior-season net for both teams {cov['prior_net_both']}, returning-minutes for both teams {cov['ret_min_both']} (missing -> feature 0, i.e. no adjustment)"))
    cut = J._cohort_of(g["slate"]); g["cohort"] = np.where(g["slate"] < cut, "cohort_1", "cohort_2")
    params = walk_forward(g)
    leak_ok = all(p["train_max_slate"] is None or p["train_max_slate"] < d for d, p in params.items())
    checks.append(C.check(name="walk_forward_training_strictly_before_slate", passed=bool(leak_ok),
                       detail="; ".join(f"{d}: n={p['n_train']}" if "n_train" in p else f"{d}: n={p['n']}" for d, p in params.items())))
    arr = {a: apply_arm(g, params, a) for a in ["INC"] + ARMS}
    ids = g["game_id"].to_numpy(); coh = g["cohort"].to_numpy(); ym = g["y_m"].to_numpy(float); yt = g["y_t"].to_numpy(float)
    win = (ym > 0).astype(float)
    inc = arr["INC"]; L_inc_m = norm_nll(ym, inc["m"], inc["sm"]); L_inc_t = norm_nll(yt, inc["t"], inc["st"])
    p_inc_n = J.phi(inc["m"] / inc["sm"]); p_inc_hw = g["hw"].to_numpy(float)

    results = []
    REF = f"incumbent:{INCUMBENT_ID}"
    for a in ARMS:
        x = arr[a]
        results += _row("game_margin", "margin_nll", REF, a, norm_nll(ym, x["m"], x["sm"]), L_inc_m, ids, coh, True, "all_games")
        if a in ("S", "V", "FULL"):
            results += _row("game_total", "total_nll", REF, a, norm_nll(yt, x["t"], x["st"]), L_inc_t, ids, coh, True, "all_games")
        if a in ("V", "P", "R", "FULL"):
            results += _row("game_margin", "margin_abs_err", REF, a, np.abs(ym - x["m"]), np.abs(ym - inc["m"]), ids, coh, False, "all_games")
        results += _row("game_moneyline", "brier", REF + "(normal)", a, C.brier_rows(J.phi(x["m"] / x["sm"]), win), C.brier_rows(p_inc_n, win), ids, coh, a == "FULL", "all_games")
    results += _row("game_moneyline", "brier", REF + "(frozen home_win_prob)", "FULL", C.brier_rows(J.phi(arr["FULL"]["m"] / arr["FULL"]["sm"]), win), C.brier_rows(p_inc_hw, win), ids, coh, False, "all_games")

    # ---------------- Kalshi
    k, kchk, pmeta = load_market_rows(arch, g, tips, workers); checks += kchk
    k["cohort"] = g["cohort"].to_numpy()[k["gi"]]; kid = k["game_id"].to_numpy()
    pk = {a: contract_probs(k, arr[a]) for a in ["INC", "FULL"]}
    mkt_rows = []
    for fam in ("game_moneyline", "game_spread"):
        m = (k["family"] == fam).to_numpy(); mm = m & np.isfinite(k["mid"].to_numpy(float))
        y = k["y"].to_numpy(float)
        results += _row(fam, "brier", REF + "(normal)", "FULL", C.brier_rows(pk["FULL"][m], y[m]), C.brier_rows(pk["INC"][m], y[m]), kid[m], k["cohort"].to_numpy()[m], True, "kalshi_listed")
        results += _row(fam, "brier", "market:kalshi_mid", "FULL", C.brier_rows(pk["FULL"][mm], y[mm]), C.brier_rows(k["mid"].to_numpy(float)[mm], y[mm]), kid[mm], k["cohort"].to_numpy()[mm], True, "kalshi_listed")
        results += _row(fam, "brier", "market:kalshi_mid", "INC", C.brier_rows(pk["INC"][mm], y[mm]), C.brier_rows(k["mid"].to_numpy(float)[mm], y[mm]), kid[mm], k["cohort"].to_numpy()[mm], False, "kalshi_listed")
        ts = m & k["two_sided"].to_numpy()
        mkt_rows.append(dict(market_family=fam, contracts=int(m.sum()), games=int(k.loc[m, "game_id"].nunique()), two_sided=int(ts.sum()), tight_mid=int(mm.sum()),
                             games_with_mid=int(k.loc[mm, "game_id"].nunique()),
                             median_spread=float((k["ask"] - k["bid"])[ts].median()) if ts.any() else None,
                             brier_mid=float(C.brier_rows(k["mid"].to_numpy(float)[mm], y[mm]).mean()) if mm.any() else None,
                             brier_ask_as_probability=float(C.brier_rows(k["ask"].to_numpy(float)[mm], y[mm]).mean()) if mm.any() else None,
                             mean_ask_minus_mid=float((k["ask"].to_numpy(float) - k["mid"].to_numpy(float))[mm].mean()) if mm.any() else None,
                             brier_incumbent=float(C.brier_rows(pk["INC"][mm], y[mm]).mean()) if mm.any() else None,
                             brier_full=float(C.brier_rows(pk["FULL"][mm], y[mm]).mean()) if mm.any() else None))
    results = finalize(results)

    # ---------------- descriptive studies (full sample, NOT used for forecasting)
    z = (ym - inc["m"]) / inc["sm"]; zt = (yt - inc["t"]) / inc["st"]
    gmin = np.minimum(g["hgs"], g["ags"]).to_numpy(int)
    sig_rows = []
    for lab, sel in (("0", gmin == 0), ("1", gmin == 1), ("2", gmin == 2), ("3+", gmin >= 3), ("all", np.ones(len(g), bool))):
        if sel.sum() < 10:
            continue
        e = (ym - inc["m"])[sel]; s = inc["sm"][sel]; et = (yt - inc["t"])[sel]
        sig_rows.append(dict(min_games_seen=lab, n=int(sel.sum()), frozen_margin_sd_mean=float(s.mean()), margin_rmse=float(np.sqrt(np.mean(e ** 2))),
                             sd_ratio=float(np.sqrt(np.mean(z[sel] ** 2))), sd_ratio_ci95=_boot_ratio(e ** 2, s ** 2, ids[sel]),
                             margin_bias=float(e.mean()), coverage80=float((np.abs(z[sel]) < 1.2816).mean()),
                             total_rmse=float(np.sqrt(np.mean(et ** 2))), total_sd_ratio=float(np.sqrt(np.mean(zt[sel] ** 2))),
                             total_sd_ratio_ci95=_boot_ratio(et ** 2, inc["st"][sel] ** 2, ids[sel]), total_bias=float(et.mean())))
    neu = (g["site"] == "neutral").to_numpy(); rm = ym - inc["m"]; rt = yt - inc["t"]
    venue = dict(n_home_site=int((~neu).sum()), n_neutral=int(neu.sum()),
                 margin_resid_home_site=_mean_ci(rm[~neu]), margin_resid_neutral=_mean_ci(rm[neu]),
                 total_resid_home_site=_mean_ci(rt[~neu]), total_resid_neutral=_mean_ci(rt[neu]),
                 neutral_minus_home_margin=float(rm[neu].mean() - rm[~neu].mean()),
                 observed_home_margin_home_sites=float(ym[~neu].mean()), projected_home_margin_home_sites=float(inc["m"][~neu].mean()),
                 note="Residual = actual - frozen incumbent (home frame). The incumbent's per-team home-court table (365 teams, models/pure/pure-0.2.0.json team_hca) is already in its home-site means; this measures what is LEFT.")
    X = features(g); okx = np.isfinite(X).all(1)
    prior_study = []
    for lab, sel in (("0", gmin == 0), ("1-2", (gmin >= 1) & (gmin <= 2)), ("3+", gmin >= 3), ("all", np.ones(len(g), bool))):
        s2 = sel & okx
        if s2.sum() < 20:
            continue
        gap = (g["net_h"] - g["net_a"]).to_numpy(float)[s2] - inc["m"][s2]
        b = float(np.sum(gap * rm[s2]) / np.sum(gap ** 2)); rr = rm[s2] - b * gap
        se = float(np.sqrt(np.sum(rr ** 2) / (s2.sum() - 1) / np.sum(gap ** 2)))
        prior_study.append(dict(min_games_seen=lab, n=int(s2.sum()), slope_resid_on_prior_gap=b, se=se,
                                note="prior_gap = last-season net difference minus frozen margin; slope > 0: incumbent should move toward last season"))
    rdiff = (g["ret_h"] - g["ret_a"]).to_numpy(float); okr = np.isfinite(rdiff)
    rmean = ((g["ret_h"] + g["ret_a"]) / 2).to_numpy(float)
    lo = okr & (rmean < np.nanmedian(rmean)); hi = okr & (rmean >= np.nanmedian(rmean))
    roster = dict(n=int(okr.sum()), corr_resid_ret_diff=float(np.corrcoef(rm[okr], rdiff[okr])[0, 1]),
                  sd_ratio_low_returning=float(np.sqrt(np.mean(z[lo] ** 2))), sd_ratio_low_ci95=_boot_ratio(rm[lo] ** 2, inc["sm"][lo] ** 2, ids[lo]),
                  sd_ratio_high_returning=float(np.sqrt(np.mean(z[hi] ** 2))), sd_ratio_high_ci95=_boot_ratio(rm[hi] ** 2, inc["sm"][hi] ** 2, ids[hi]),
                  median_mean_ret_min=float(np.nanmedian(rmean)))
    a_hw, b_hw = C.calibration_slope(p_inc_hw, win); a_n, b_n = C.calibration_slope(p_inc_n, win)
    calib = dict(n=len(g), by_source={s: int((g["src"] == s).sum()) for s in ("period_scores", "schedule_final")},
                 margin_z_mean=float(z.mean()), margin_z_sd=float(z.std()), total_z_mean=float(zt.mean()), total_z_sd=float(zt.std()),
                 margin_mae=float(np.abs(rm).mean()), total_mae=float(np.abs(rt).mean()), margin_bias=_mean_ci(rm), total_bias=_mean_ci(rt),
                 win_prob_frozen=dict(intercept=a_hw, slope=b_hw, brier=float(C.brier_rows(p_inc_hw, win).mean())),
                 win_prob_normal=dict(intercept=a_n, slope=b_n, brier=float(C.brier_rows(p_inc_n, win).mean())),
                 extension_only=dict(n=int((g["src"] == "schedule_final").sum()), margin_bias=float(rm[g["src"] == "schedule_final"].mean()),
                                     margin_sd_ratio=float(np.sqrt(np.mean(z[g["src"] == "schedule_final"] ** 2)))))
    last = params[sorted(params)[-1]]

    # ---------------- verdict
    hl = [r for r in results if r["headline"]]
    cnt = {v: sum(r["verdict"] == v for r in hl) for v in C.VERDICTS}
    fav = [f"{r['arm']}:{r['market_family']}/{r['metric']} vs {r['reference']}" for r in hl if r["verdict"] in ("VALIDATED_IMPROVEMENT", "IMPROVED_NOT_VALIDATED")]
    unf = [f"{r['arm']}:{r['market_family']}/{r['metric']} vs {r['reference']}" for r in hl if r["verdict"] == "NOT_IMPROVED"]
    overall = "VALIDATED_IMPROVEMENT" if cnt["VALIDATED_IMPROVEMENT"] and not unf else ("IMPROVED_NOT_VALIDATED" if fav and not unf else "INCONCLUSIVE")
    if not fav and unf and all("market:" in u for u in unf):
        overall = "INCONCLUSIVE"
    rejected = [a for a in ARMS[:-1] if not any(r["arm"] == a and r["headline"] and r["verdict"] in ("VALIDATED_IMPROVEMENT", "IMPROVED_NOT_VALIDATED") for r in hl)]

    def hres(a, fam, met, ref=REF):
        r = next((r for r in results if r["arm"] == a and r["market_family"] == fam and r["metric"] == met and r["reference"] == ref and r["cohort"] == "pooled"), None)
        return "n/a" if r is None else f"{r['challenger']:.4f} vs {r['reference_value']:.4f}, diff {r['diff']:+.4f} [{r['ci95'][0]:+.4f}, {r['ci95'][1]:+.4f}], p_holm {r['p_holm']:.3f}, {r['verdict']}"

    sha = J.git_shas(repo) | {"cbb-edge-finder": _rev(repo, "HEAD")}
    doc = dict(
        schema=C.EVAL_SCHEMA, status="RESEARCH_ONLY", sport="CBB", challenger_id=CHALLENGER_ID, incumbent_id=INCUMBENT_ID,
        data=[
            dict(dataset_id="cbb.projections_archive.pure-0.2.0", repo=J.REPO, path="origin/projections-archive:projections/<season>/<date>/<game_id>/<as_of>.json",
                 rows=int(len(g)), rows_unit="games (latest frozen pre-tip forecast per game)", first=str(g["tip"].min()), last=str(g["tip"].max()),
                 rights_tier="UNRESOLVED_INTERNAL_ONLY", kind="PROSPECTIVE_CAPTURE", verified="as_of < tip, manifest sha256 (period-score subset re-verified by cbb_joint_periods.build_games); games_seen from the same frozen file"),
            dict(dataset_id="cbb.period_scores_archive", repo=J.REPO, path="origin/period-scores-archive:periods/...", rows=int((g["src"] == "period_scores").sum()),
                 rows_unit="verified finals used", first=str(g.loc[g["src"] == "period_scores", "tip"].min()), last=str(g.loc[g["src"] == "period_scores", "tip"].max()),
                 rights_tier="UNRESOLVED_INTERNAL_ONLY", kind="PROSPECTIVE_CAPTURE"),
            dict(dataset_id="cbb.schedule_archive.finals", repo=J.REPO, path="origin/schedule-archive:rows/...", rows=int((g["src"] == "schedule_final").sum()),
                 rows_unit="extension finals (games after the last period-score tip)", first=ext_meta["extension_first_tip"], last=ext_meta["extension_last_tip"],
                 rights_tier="UNRESOLVED_INTERNAL_ONLY", kind="PROSPECTIVE_CAPTURE", schedule_rows_read=ext_meta["sched_rows"]),
            dict(dataset_id="cbb.model_checkpoint.finals_2006_2026", repo=J.REPO, path=f"main:{CKPT}/finals.parquet", rows=tmeta["finals_rows"], rows_unit="team-season end-of-season o/d ratings",
                 first=str(tmeta["finals_seasons"][0]), last=str(tmeta["finals_seasons"][1]), rights_tier="UNRESOLVED_INTERNAL_ONLY (derived from sportsdataverse bulk)", kind="HISTORICAL_BACKFILL",
                 sha256=tmeta["sha"]["finals.parquet"], used="season 2026 rows only (last season's net rating)"),
            dict(dataset_id="cbb.model_checkpoint.preseason_2027", repo=J.REPO, path=f"main:{CKPT}/preseason.parquet", rows=tmeta["preseason_rows"], rows_unit="teams (expected returning-minutes share etc.)",
                 first="2027", last="2027", rights_tier="UNRESOLVED_INTERNAL_ONLY (derived from sportsdataverse bulk)", kind="HISTORICAL_BACKFILL", sha256=tmeta["sha"]["preseason.parquet"]),
            dict(dataset_id="cbb.kalshi_panel_archive", repo=J.REPO, path="origin/kalshi-panel-archive:panels/...", rows=int(len(k)), rows_unit="full-game winner/spread contracts in used games (latest pre-tip snapshot)",
                 first=str(pmeta["first"]), last=str(pmeta["last"]), rights_tier="KALSHI_PUBLIC_MARKET_DATA_INTERNAL", kind="PROSPECTIVE_CAPTURE"),
        ],
        features=[
            dict(feature_id="early_season_sigma_scale", catalog_inputs=["CBB:cbb.score_resid"], description="walk-forward SD scale k for margin and total (N0=60 pseudo-games at k=1)",
                 pit_rule="fitted on finals first observed before the slate's first tip", checks=checks),
            dict(feature_id="neutral_site_offset", catalog_inputs=["CBB:cbb.neutral_site", "CBB:cbb.venue"], description=f"neutral-minus-home residual offset (margin, total), shrunk by {K_VENUE:.0f} pseudo-games",
                 pit_rule="same walk-forward clock; site flag from the frozen forecast", checks=[c for c in checks if "orientation" in c["name"] or "side" in c["name"]]),
            dict(feature_id="prior_season_net_fade", catalog_inputs=["CBB:cbb.preseason_prior"], description="w_h*net_h - w_a*net_a, net = 2026 end-of-season o-d from the frozen checkpoint, w = exp(-games_seen/6); ridge 100",
                 pit_rule="checkpoint table frozen at the 2026 boundary (before every forecast); games_seen from the frozen forecast file", checks=[c for c in checks if "checkpoint" in c["name"] or "coverage" in c["name"]]),
            dict(feature_id="returning_minutes_fade", catalog_inputs=["CBB:cbb.recruit_exp", "CBB:cbb.roster_minutes"], description="w_h*ret_h - w_a*ret_a, ret = expected returning-minutes share (preseason.parquet ret_min); ridge 100",
                 pit_rule="checkpoint table frozen at the 2026 boundary; expected (not realised) returners", checks=[c for c in checks if "checkpoint" in c["name"] or "coverage" in c["name"]]),
        ],
        design=dict(cohort_cut=cut, cohorts="slates before / on-or-after the cut", walk_forward="slate-by-slate; training = earlier slates with the final first observed before the slate's first tip",
                    arms={"S": "SD scale", "V": "neutral-site offset", "P": "prior-season net fade", "R": "returning-minutes fade", "FULL": "all four"},
                    loss_metrics="normal negative log density of the realised margin / total (nats); absolute margin error; Brier (home win, Kalshi contracts)",
                    contract_probabilities="P(D>t) = 1 - Phi((t-m)/s) in the projection frame, t = 0 for winner; the incumbent reference uses its own m and frozen margin_sd (its documented spread formula)",
                    headline_rule="Holm across all headline rows; verdict_from(); non-headline rows Bonferroni-adjusted by the headline count",
                    market_note="Kalshi mid only when 0 < bid < ask < 1 and ask - bid <= 0.10; ask reported separately; fees not modelled; no profitability claim"),
        games=dict(used=int(len(g)), slates=int(g["slate"].nunique()), first_tip=str(g["tip"].min()), last_tip=str(g["tip"].max()), neutral=int(neu.sum()),
                   period_score_audit=audit["games"], extension=ext_meta),
        results=results,
        studies=dict(early_season_sigma=sig_rows, venue=venue, prior_weight=prior_study, roster_turnover=roster, incumbent_calibration=calib, market=mkt_rows,
                     last_walk_forward_params={k2: v for k2, v in last.items()}),
        walk_forward_params={d: {k2: v for k2, v in p.items()} for d, p in params.items()},
        verdict=dict(overall=overall, headline_counts=cnt, favourable=fav, unfavourable=unf, rejected_components=rejected,
                     reason=f"{len(hl)} headline pooled comparisons (Holm): {cnt}. Two weeks of one season; most rows cannot reach significance. Components without a favourable verdict are rejected for now: {rejected}."),
        limitations=[
            f"{len(g)} games over {g['slate'].nunique()} slates of one season; {int(neu.sum())} neutral-site games. Results are immature by construction.",
            "No multi-season GAME-level lake is committed: the prior-season study uses end-of-season team ratings frozen in the model checkpoint, not a historical chronological backtest of early-season games.",
            "Returning minutes are the checkpoint's EXPECTED returners (return-probability model), not the realised 2026-27 roster.",
            "The incumbent's win probability is a logit of the margin; the challenger uses Phi(m/s). Moneyline comparisons are against the incumbent's normal-implied probability (headline) and its frozen home_win_prob (non-headline).",
            "Extension outcomes come from schedule-archive finals (not half-verified period scores); their first-observation time is the walk-forward clock.",
            "Kalshi quotes are latest pre-tip snapshots; mids are not executable; fees not modelled; nothing here is a profitability claim.",
        ],
        input_stage_claims=[
            dict(input="CBB:cbb.score_resid", stage="EVALUATED", outcome="OK", evidence=f"Early-season SD scale (arm S): margin NLL {hres('S', 'game_margin', 'margin_nll')}; total NLL {hres('S', 'game_total', 'total_nll')}."),
            dict(input="CBB:cbb.neutral_site", stage="EVALUATED", outcome="PARTIAL", evidence=f"Neutral-site offset (arm V) on {int(neu.sum())} neutral games: margin NLL {hres('V', 'game_margin', 'margin_nll')}."),
            dict(input="CBB:cbb.preseason_prior", stage="EVALUATED", outcome="PARTIAL", evidence=f"Prior-season net fade (arm P): margin NLL {hres('P', 'game_margin', 'margin_nll')}. Season ratings from the frozen checkpoint, not a multi-season game backtest."),
            dict(input="CBB:cbb.recruit_exp", stage="EVALUATED", outcome="PARTIAL", evidence=f"Expected returning-minutes fade (arm R): margin NLL {hres('R', 'game_margin', 'margin_nll')}."),
        ],
        source_commits=sha,
    )
    errs = C.validate_evaluation(doc)
    if errs:
        raise ValueError(f"evaluation.json violates the contract: {errs}")
    out_dir.mkdir(parents=True, exist_ok=True)
    C.write_json(out_dir / "evaluation.json", doc)
    return doc


def _rev(repo, ref):
    import subprocess
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
            print(f"  {'*' if r['headline'] else ' '} {r['arm']:4s} {r['universe']:13s} {r['market_family']:14s} {r['metric']:14s} vs {r['reference'][:40]:40s} n={r['n_clusters']:4d} "
                  f"ch={r['challenger']:.4f} ref={r['reference_value']:.4f} d={r['diff']:+.4f} [{r['ci95'][0]:+.4f},{r['ci95'][1]:+.4f}] ph={r['p_holm']:.3f} rep={int(r['replicated'])} {r['verdict']}")


if __name__ == "__main__":
    main()
