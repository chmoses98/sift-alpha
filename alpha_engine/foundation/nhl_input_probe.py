"""Operation Data Foundation, NHL: do the Phase 15 archive-built inputs add information to ``alpha-nhl-joint-0.3``?

RESEARCH_ONLY. An incremental-information probe, not a new model. ``nhl_joint_v3.run`` is re-run unchanged up to its fitted
headline model (``hook``); its per-game probabilities for 2021-2025 regular-season games are the offset. For each candidate
input a ONE-parameter residual model is fitted on 2021-2023 (the seasons the Phase 15 event archive and 0.3's fit window
share) and scored, unchanged, on the 2024 and 2025 test cohorts separately:

* moneyline:          logit P(home win)          = logit p_0.3 + b * z
* regulation tie:     logit P(regulation tie)    = logit p_0.3 + b * z
* overtime winner:    logit P(home wins | OT/SO) = logit p_0.3_ot + b * z  (games that went beyond regulation)
* total goals:        log E[total]               = log E_0.3[total] + b * z  (Poisson deviance)

``z`` is the standardised (fit-window mean/sd) home-minus-away difference, or home + away sum for totals, of one builder
column. An input "adds information" only if the loss falls in BOTH cohorts with a 95% game-clustered CI below zero after
Holm across every probe row; one favourable cohort is IMPROVED_NOT_VALIDATED, as everywhere in the contract.

Caveats written into the output: 0.3 is fitted on <= 2023, so its 2021-2023 probabilities are in-sample (residual slopes
are learned against an in-sample offset, which can only understate information); the builders cover 2021-2025 only, so
the 2026-27 prospective cohort is not probed (the archive has no Phase 15 event tables for it).

``python -m alpha_engine.foundation.nhl_input_probe`` writes ``research/data_foundation_ops/NHL/phase15_input_probe.json``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import contract as C
from . import nhl_joint as J
from . import nhl_joint_v3 as V3
from ..features import nhl_ev_ext2 as EV
from ..features import nhl_ext2 as E2

OUT = C.OPS / "NHL" / "phase15_input_probe.json"
FIT = (2021, 2023)
COHORTS = (2024, 2025)
CANDIDATES = [
    # (catalog input, column, family, combine)
    ("NHL:nhl.goalie_start", "gs_p_top_pre", "moneyline", "diff"),
    ("NHL:nhl.goalie_minutes_in_net_dist", "gm_p_lt40_pre", "moneyline", "diff"),
    ("NHL:nhl.first_goal_hazard", "fgh_p_first_pre", "moneyline", "home"),
    ("NHL:nhl.ot_3v3_rate", "ot_p_win_pre", "overtime_winner", "home"),
    ("NHL:nhl.ot_3v3_rate", "ot_p_decided_pre", "regulation_tie_overtime", "home"),
    ("NHL:nhl.settlement_goal_pmf", "sg_p_regtie_pre", "regulation_tie_overtime", "mean"),
    ("NHL:nhl.game_script_prob", "gsp_lead40_pre", "moneyline", "diff"),
    ("NHL:nhl.early_window_goal_rate", "ew_lambda_pre", "total_goals", "home"),
    ("NHL:nhl.opp_sog_for_rate", "os_exp_sog_faced_pre", "total_goals", "sum"),
    ("NHL:nhl.goalie_minutes_in_net_dist", "gm_p_lt40_pre", "total_goals", "sum"),
    ("NHL:nhl.period_split", "ps_dev_p3_pre", "total_goals", "sum"),
]


class _Stop(Exception):
    pass


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def fit_logit_offset(off, z, y, iters: int = 50) -> float:
    """MLE of b in P(y=1) = sigmoid(off + b z)."""
    b = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(off + b * z))); g = float(np.sum((y - p) * z)); h = float(np.sum(p * (1 - p) * z * z))
        if h <= 0:
            break
        st = g / h; b += st
        if abs(st) < 1e-10:
            break
    return float(b)


def fit_poisson_offset(off, z, y, iters: int = 50) -> float:
    b = 0.0
    for _ in range(iters):
        mu = np.exp(off + b * z); g = float(np.sum((y - mu) * z)); h = float(np.sum(mu * z * z))
        if h <= 0:
            break
        st = g / h; b += st
        if abs(st) < 1e-10:
            break
    return float(b)


def pois_dev(y, mu):
    y = np.asarray(y, float); mu = np.asarray(mu, float)
    return 2 * (np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / mu), 0.0) - (y - mu))


def game_features(hist_dir) -> pd.DataFrame:
    """One row per (game_id) with home_* and away_* columns of every candidate builder column."""
    raw = EV.load_raw(hist_dir); ev = EV.compute(raw)["team"]
    side = raw["team_states"].drop_duplicates(["game_id", "team_id"])[["game_id", "team_id", "is_home"]].rename(columns={"team_id": "team"})
    ev = ev.merge(side, on=["game_id", "team"], how="left")
    e2 = E2.compute(E2.load_raw(hist_dir))["team"]
    cols_ev = list(dict.fromkeys(c for _, c, _, _ in CANDIDATES if c in ev.columns)); cols_e2 = list(dict.fromkeys(c for _, c, _, _ in CANDIDATES if c in e2.columns and c not in cols_ev))
    e2 = e2[["game_id", "team"] + cols_e2]
    t = ev[["game_id", "team", "is_home"] + cols_ev].merge(e2, on=["game_id", "team"], how="left")
    h = t[t.is_home.astype(bool)].drop(columns=["is_home", "team"]).add_prefix("home_").rename(columns={"home_game_id": "game_id"})
    a = t[~t.is_home.astype(bool)].drop(columns=["is_home", "team"]).add_prefix("away_").rename(columns={"away_game_id": "game_id"})
    return h.merge(a, on="game_id", how="inner")


PROBE_ID = "probe:nhl-phase15-inputs-on-alpha-nhl-joint-0.3"


def claims_from_rows(rows: list) -> list:
    """Ledger claims: one per catalog input. OK = a validated row; PARTIAL = favourable but not validated; REJECTED = no
    measurable information beyond 0.3 in any probed family (stage EVALUATED either way)."""
    out = []
    for inp in dict.fromkeys(r["input"] for r in rows):
        rs = [r for r in rows if r["input"] == inp]; v = [r["verdict"] for r in rs]
        oc = "OK" if "VALIDATED_IMPROVEMENT" in v else "PARTIAL" if "IMPROVED_NOT_VALIDATED" in v else "REJECTED"
        ev = "; ".join(f"{r['column']} on {r['market_family']}: pooled {r['cohorts']['pooled']['diff']:+.5f} [{r['cohorts']['pooled']['ci95'][0]:+.5f}, "
                       f"{r['cohorts']['pooled']['ci95'][1]:+.5f}] {r['verdict']}" for r in rs)
        out.append(dict(input=inp, stage="EVALUATED", outcome=oc, evidence=f"one-parameter residual probe on 0.3 (fit 2021-23, test 2024 and 2025): {ev}"))
    return out


def run(log=print) -> dict:
    cap = {}

    def hook(d):
        cap.update(d); raise _Stop()
    try:
        V3.run(log=log, hook=hook)
    except _Stop:
        pass
    G, head, sg = cap["G"], cap["head"], cap["sg"]
    idx = np.flatnonzero((sg >= FIT[0]) & (sg <= COHORTS[-1]))
    mk = head.markets(idx)
    base = pd.DataFrame(dict(game_id=G["game_id"][idx].astype("int64"), season=sg[idx], p_home=mk["p_home_win"], p_tie=mk["p_reg_tie"], e_total=mk["exp_total"],
                             p_ot_home=V3.ot_home_prob3(head.lam_h[idx], head.lam_a[idx], head.k_ot, head.h0)))
    games, _ = J.load_games(); gi = games[games["final"].astype(bool)].drop_duplicates("game_id").set_index("game_id")
    base["home_win"] = gi.loc[base.game_id, "home_win"].astype(int).to_numpy()
    base["extra"] = gi.loc[base.game_id, "last_period_type"].isin(["OT", "SO"]).astype(int).to_numpy()
    base["total"] = (gi.loc[base.game_id, "home_score"].astype(int) + gi.loc[base.game_id, "away_score"].astype(int)).to_numpy()
    feats = game_features(C.repos_dir() / "NHL-edge-finder" / "data" / "history")
    D = base.merge(feats, on="game_id", how="left")
    checks = [C.check("probe_offset_is_the_fitted_0.3_head_model", True, "probabilities from nhl_joint_v3.run's headline Model3 (hook after fit); evaluation code path unchanged", basis=C.ATTESTED),
              C.check("phase15_features_join_2021_2025_games", float(D.home_gs_p_top_pre.notna().mean()) > 0.9,
                      f"{int(D.home_gs_p_top_pre.notna().sum())} of {len(D)} 2021-2025 regular-season games carry the event-archive builder columns")]
    rows = []
    for inp, col, fam, how in CANDIDATES:
        h, a = D[f"home_{col}"].to_numpy(float), D[f"away_{col}"].to_numpy(float)
        zr = {"diff": h - a, "sum": h + a, "home": h, "mean": (h + a) / 2}[how]
        fitm = (D.season >= FIT[0]).to_numpy() & (D.season <= FIT[1]).to_numpy() & np.isfinite(zr)
        if fam == "overtime_winner":
            fitm &= D.extra.to_numpy() == 1
        if fitm.sum() < 200:
            continue
        mu_z, sd_z = float(zr[fitm].mean()), float(zr[fitm].std()) or 1.0
        z = np.where(np.isfinite(zr), (zr - mu_z) / sd_z, 0.0)
        if fam == "total_goals":
            off = np.log(D.e_total.to_numpy()); y = D.total.to_numpy(float)
            b = fit_poisson_offset(off[fitm], z[fitm], y[fitm])
            loss_b, loss_c = pois_dev(y, np.exp(off)), pois_dev(y, np.exp(off + b * z)); metric = "poisson_deviance"
        else:
            pcol, ycol = {"moneyline": ("p_home", "home_win"), "regulation_tie_overtime": ("p_tie", "extra"), "overtime_winner": ("p_ot_home", "home_win")}[fam]
            off = logit(D[pcol].to_numpy()); y = D[ycol].to_numpy(float)
            b = fit_logit_offset(off[fitm], z[fitm], y[fitm])
            loss_b, loss_c = C.logloss_rows(1 / (1 + np.exp(-off)), y), C.logloss_rows(1 / (1 + np.exp(-(off + b * z))), y); metric = "logloss"
        per = {}
        for coh in COHORTS + ("pooled",):
            m = np.isfinite(zr) & ((D.season == coh).to_numpy() if coh != "pooled" else D.season.isin(COHORTS).to_numpy())
            if fam == "overtime_winner":
                m &= D.extra.to_numpy() == 1
            bs = C.paired_cluster_bootstrap((loss_c - loss_b)[m], D.game_id.to_numpy()[m])
            per[str(coh)] = dict(n_games=bs["n_clusters"], diff=bs["mean"], ci95=[bs["lo"], bs["hi"]], p_raw=bs["p_two_sided"], loss_0_3=float(loss_b[m].mean()))
        rows.append(dict(input=inp, column=col, combine=how, market_family=fam, metric=metric, fitted_b_per_sd=b, fit_games=int(fitm.sum()), fit_mean=mu_z, fit_sd=sd_z, cohorts=per))
    ph = C.holm([r["cohorts"]["pooled"]["p_raw"] for r in rows])
    for r, p in zip(rows, ph):
        c = r["cohorts"]; rep = all(c[str(k)]["diff"] < 0 for k in COHORTS)
        r["p_holm_pooled"] = float(p); r["replicated_both_cohorts"] = rep
        r["verdict"] = C.verdict_from(c["pooled"]["ci95"][0], c["pooled"]["ci95"][1], p, rep)
    n_val = sum(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in rows)
    doc = dict(schema="sift-foundation-probe/1", status="RESEARCH_ONLY", sport="NHL", base_model="alpha-nhl-joint-0.3 (headline Model3, fitted <= 2023)",
               design=dict(fit_seasons=list(FIT), test_cohorts=list(COHORTS), one_parameter_per_probe=True,
                           rule="VALIDATED only if pooled CI < 0, Holm p < 0.05 across all probe rows, and the loss falls in both 2024 and 2025",
                           caveats=["0.3's 2021-2023 probabilities are in-sample (fit <= 2023); a residual slope fitted against an in-sample offset can only understate information",
                                    "Phase 15 event tables cover 2021-2025; the 2026-27 prospective cohort is not probed",
                                    "market references (Kalshi) are not used here; this measures information beyond 0.3, not beyond the market",
                                    "0.3 conditions on the actual starting goalie, so pre-confirmation starter features can only add information through the starter's expected workload"]),
               checks=checks, rows=rows, probe_id=PROBE_ID, input_stage_claims=claims_from_rows(rows),
               summary=dict(n_probes=len(rows), validated=n_val, improved_not_validated=sum(r["verdict"] == "IMPROVED_NOT_VALIDATED" for r in rows),
                            not_improved=sum(r["verdict"] == "NOT_IMPROVED" for r in rows),
                            conclusion=("none of the probed Phase 15 inputs adds validated information to 0.3" if n_val == 0 else
                                        f"{n_val} probe row(s) validated: {[r['input'] + ':' + r['market_family'] for r in rows if r['verdict'] == 'VALIDATED_IMPROVEMENT']}")))
    return doc


def main(argv=None) -> int:
    doc = run()
    C.write_json(OUT, doc)
    for r in doc["rows"]:
        c = r["cohorts"]
        print(f"{r['input']:40s} {r['column']:22s} {r['market_family']:24s} b={r['fitted_b_per_sd']:+.3f} 2024 {c['2024']['diff']:+.5f} 2025 {c['2025']['diff']:+.5f} "
              f"pooled {c['pooled']['diff']:+.5f} [{c['pooled']['ci95'][0]:+.5f},{c['pooled']['ci95'][1]:+.5f}] {r['verdict']}")
    print(doc["summary"]["conclusion"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
