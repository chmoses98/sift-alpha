#!/usr/bin/env python3
"""MLB 2026 Kalshi: does any time-valid pregame input improve prediction of settled outcomes BEYOND the contemporaneous market price? (RESEARCH_ONLY)

usage: python3 -I research/outcome_intel/mlb_incremental.py --root <edge-finder-api main checkout> --out reports/outcome_intel/mlb_incremental.json [--cache DIR]

Cells = (family x horizon x challenger). Every cell attempted is reported and enters one Holm family. Protocol is fixed before looking at any holdout:
  * horizons: NEAR = decision quote 10-60 min before first pitch (SIFT model: model run 10-90 min before first pitch); FAR = 150-400 min (SIFT: 90-420).
  * baseline: latest two-sided pregame quote (spread <= 10c) of the contract at/ before the decision time; rows with mid outside [0.05, 0.95] excluded.
  * challengers: (a) 'sift_model' = archived SIFT model probability with an explicit pregame run timestamp (ModelEvaluation, sources
    prospective_snapshot / pipeline_recommendations; run time <= decision time < first pitch); (b) 'price_trajectory' = the contract's own earliest pregame
    two-sided quote that is >= 120 min older than the decision quote (a purely time-valid market-history input).
  * split: games ordered by first pitch; train = earliest 2/3, holdout = latest 1/3 (only one season, 2026, exists on Kalshi: a season split is impossible);
    ridge fixed; one pass; statistic = holdout logloss gain over the CALIBRATED market baseline; game-cluster bootstrap; Holm over all cells.
  * controls: negative = game-shuffled challenger (expect 0); positive = planted-signal challenger (expect detection).
"""
from __future__ import annotations
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import incremental as I
import mlb_data as D

HORIZONS = {"NEAR": (10, 60), "FAR": (150, 400)}
MODEL_LEAD = {"NEAR": (10, 90), "FAR": (90, 420)}
MID_LO, MID_HI = 0.05, 0.95
MIN_TRAJ_GAP = 120.0
MIN_HOLDOUT_GAMES_POWERED = 100
MAX_MDE = 0.03


def decision_quotes(Q, horizon):
    """Per ticker: the latest two-sided, tight pregame quote whose minutes-before-first-pitch lies in the horizon window."""
    lo, hi = HORIZONS[horizon]
    q = Q[Q["two_sided_ok"] & (Q["mins_before"] >= lo) & (Q["mins_before"] <= hi)]
    q = q.sort_values("t_cap").groupby("marketTicker").tail(1)
    return q


def earliest_quotes(Q):
    q = Q[Q["two_sided_ok"]].sort_values("t_cap").groupby("marketTicker").head(1)
    return q.set_index("marketTicker")


def rows_trajectory(Q, Y, family, horizon):
    dq = decision_quotes(Q[Q["family"] == family], horizon)
    first = earliest_quotes(Q[Q["family"] == family])
    rows, base_rows = [], []
    for r in dq.itertuples():
        y = Y["y"].get(r.marketTicker)
        if y is None or pd.isna(y) or not (MID_LO <= r.mid <= MID_HI):
            continue
        base = dict(game=int(r.pk) if pd.notna(r.pk) else r.gc, t=r.t_fp.isoformat(), mid=float(r.mid), y=int(y), ticker=r.marketTicker)
        base_rows.append(base)
        f = first["mid"].get(r.marketTicker) if r.marketTicker in first.index else None
        if f is not None and (first.at[r.marketTicker, "mins_before"] - r.mins_before) >= MIN_TRAJ_GAP and 0.01 <= f <= 0.99:
            rows.append(dict(base, q=float(f)))
    return base_rows, rows


def model_probs(E):
    """ModelEvaluation rows with an explicit pregame run timestamp and a probability. Percent -> probability."""
    e = E[E["source"].isin(["prospective_snapshot", "pipeline_recommendations"]) & E["modelFairProbability"].notna()].copy()
    e["t_eval"] = pd.to_datetime(e["pipelineRunId"].where(e["pipelineRunId"].notna(), e["createdAt"]), utc=True, errors="coerce")
    e["pk"] = pd.to_numeric(e["gameId"], errors="coerce")
    e["q"] = e["modelFairProbability"].astype(float) / 100.0
    return e.dropna(subset=["t_eval", "pk"])


def contract_for(e, Q):
    """Attach the Kalshi ticker each model row speaks about. moneyline/F5: the HOME-team contract of ML_Home / F5_ML_Home rows (the Away rows are the
    mirror and would double count); YRFI -> the game's RFI market; team totals -> the explicit ticker the evaluation row carries."""
    Qd = Q.drop_duplicates("marketTicker")
    ml = Qd[(Qd["family"] == "moneyline") & (Qd["team"] == Qd["homeTeam"])].set_index("pk")["marketTicker"]
    f5 = Qd[(Qd["family"] == "f5_result") & (Qd["team"] == Qd["homeTeam"])].set_index("pk")["marketTicker"]
    rfi = Qd[Qd["family"] == "nrfi_yrfi"].set_index("pk")["marketTicker"]
    out = []
    for fam, sel, mp in (("moneyline", "ML_Home", ml), ("f5_result", "F5_ML_Home", f5), ("nrfi_yrfi", "YRFI", rfi)):
        x = e[e["selection"] == sel].copy()
        x["ticker"] = x["pk"].map(mp[~mp.index.duplicated()])
        x["family"] = fam
        out.append(x)
    x = e[(e["seriesTicker"] == "KXMLBTEAMTOTAL") | e["marketTicker"].astype(str).str.startswith("KXMLBTEAMTOTAL")].copy()
    x["ticker"], x["family"] = x["marketTicker"], "team_total"
    out.append(x)
    return pd.concat(out).dropna(subset=["ticker"])


def rows_model(Q, Y, E, family, horizon):
    m = contract_for(model_probs(E), Q)
    m = m[m["family"] == family]
    lo, hi = MODEL_LEAD[horizon]
    Qf = Q[(Q["family"] == family) & Q["two_sided_ok"]]
    qd = {k: g.sort_values("t_cap") for k, g in Qf.groupby("marketTicker")}
    rows = []
    for tick, g in m.groupby("ticker"):
        if tick not in qd:
            continue
        quotes = qd[tick]
        t_fp = quotes["t_fp"].iloc[0]
        g = g.copy()
        g["lead"] = (t_fp - g["t_eval"]).dt.total_seconds() / 60.0
        g = g[(g["lead"] >= lo) & (g["lead"] <= hi)]
        if g.empty:
            continue
        e = g.sort_values("t_eval").iloc[-1]  # latest model run inside the horizon window: chosen on time only, never on outcome
        prior = quotes[(quotes["t_cap"] <= e["t_eval"]) & (quotes["t_cap"] >= e["t_eval"] - pd.Timedelta(minutes=60)) & (quotes["mins_before"] > 0)]
        y = Y["y"].get(tick)
        if prior.empty or y is None or pd.isna(y):
            continue
        p = prior.iloc[-1]
        if not (MID_LO <= p["mid"] <= MID_HI):
            continue
        rows.append(dict(game=int(p["pk"]), t=t_fp.isoformat(), mid=float(p["mid"]), q=float(np.clip(e["q"], 0.01, 0.99)), y=int(y), ticker=tick,
                         eval_time=e["t_eval"].isoformat(), quote_time=p["t_cap"].isoformat()))
    return rows


def positive_control(rows, seed=3):
    """Planted-signal challenger: q knows the outcome with moderate strength. Test must detect it or the cell's null is uninformative."""
    rng = np.random.default_rng(seed)
    fake = []
    for r in rows:
        z = I.logit([r["mid"]])[0] + 0.7 * (2 * r["y"] - 1) + rng.normal(0, 0.5)
        fake.append(dict(r, q=float(I.sigmoid(z))))
    return I.incremental_test(fake)


def classify(c, n_contracts, n_games):
    status, reason = _classify(c, n_contracts, n_games)
    if c.get("status") == "OK" and not c.get("negative_control_ok", True):
        reason += " | NEGATIVE CONTROL NOT CLEAN (shuffled challenger CI excludes 0): treat this cell as unreliable"
    if status == "NO_DEMONSTRATED_IMPROVEMENT" and c.get("challenger") == "price_trajectory":
        reason += " | applies only to the stale-quote 'price_trajectory' challenger, not to other inputs"
    return status, reason


def _classify(c, n_contracts, n_games):
    if c["status"] != "OK":
        return "INCONCLUSIVE_UNDERPOWERED", f"too few games for a chronological split (train {c.get('train_games')}, holdout {c.get('holdout_games')}); rows={n_contracts}"
    g = c["gain_vs_calibrated_market_logloss"]
    se = (g["hi"] - g["lo"]) / 3.92
    c["mde_logloss_80pct_power"] = float(2.8 * se)
    powered = c["holdout_games"] >= MIN_HOLDOUT_GAMES_POWERED and c["mde_logloss_80pct_power"] <= MAX_MDE
    if g["lo"] > 0 and c["holm_p"] <= 0.05 and c["negative_control_ok"]:
        return "VALIDATED_IMPROVEMENT", "holdout gain CI excludes 0, Holm-adjusted p<=0.05, negative control clean"
    if g["mean"] > 0 and g["p"] <= 0.05:
        return "PROMISING_INSUFFICIENT", f"nominal p={g['p']:.3f} but Holm p={c['holm_p']:.3f}; not validated across {c['_n_cells']} cells"
    if powered and c.get("positive_control_detected"):
        return "NO_DEMONSTRATED_IMPROVEMENT", f"holdout {c['holdout_games']} games, gain {g['mean']:+.4f} [{g['lo']:+.4f},{g['hi']:+.4f}]; minimum detectable gain ~{c['mde_logloss_80pct_power']:.3f}"
    return "INCONCLUSIVE_UNDERPOWERED", (f"holdout {c['holdout_games']} games, gain {g['mean']:+.4f} [{g['lo']:+.4f},{g['hi']:+.4f}]; minimum detectable gain "
                                        f"~{c['mde_logloss_80pct_power']:.3f} logloss: this null is not evidence of no effect")


def run_cell(rows, base_rows, family, horizon, challenger, inputs):
    cell = dict(sport="MLB", family=family, horizon=horizon, challenger=challenger, inputs_available=inputs,
                n_contracts_baseline=len(base_rows), n_games_baseline=len({r["game"] for r in base_rows}),
                n_contracts=len(rows), n_games=len({r["game"] for r in rows}))
    c = I.incremental_test(rows, min_games=30) if len(rows) else dict(status="UNDERPOWERED", train_games=0, holdout_games=0, n_train=0, n_holdout=0)
    if c["status"] == "OK":
        nc = I.negative_control(rows, min_games=30)
        c["negative_control_gain"] = nc.get("gain_vs_calibrated_market_logloss")
        c["negative_control_ok"] = bool(nc["gain_vs_calibrated_market_logloss"]["lo"] <= 0 <= nc["gain_vs_calibrated_market_logloss"]["hi"])
        pc = positive_control(rows)
        c["positive_control_gain"] = pc.get("gain_vs_calibrated_market_logloss")
        c["positive_control_detected"] = bool(pc["status"] == "OK" and pc["gain_vs_calibrated_market_logloss"]["lo"] > 0)
        if challenger == "sift_model":
            te = [r for r in rows if r["game"] in I.split_games(rows)[1]]
            y = np.array([r["y"] for r in te], float)
            q = np.clip([r["q"] for r in te], 1e-6, 1 - 1e-6)
            c["model_metrics"] = dict(raw_model_logloss=float(I.ll(np.asarray(q), y).mean()), raw_model_brier=float(((np.asarray(q) - y) ** 2).mean()))
    cell.update(c)
    return cell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default="reports/outcome_intel/mlb_incremental.json")
    ap.add_argument("--cache", default=None, help="optional directory to cache the parsed tables (pickle) between runs")
    a = ap.parse_args()
    import pickle
    ck = os.path.join(a.cache, "ctx.pkl") if a.cache else None
    if ck and os.path.exists(ck):
        ctx = pickle.load(open(ck, "rb"))
    else:
        games, _ = D.load_schedule_games(a.root)
        obs, _ = D.load_obs(a.root)
        settle, _ = D.load_settlements(a.root)
        E, _ = D.load_evals(a.root)
        panel = D.build_panel(obs, games)
        Y = D.build_outcomes(panel, games, settle)
        ctx = dict(panel=panel, Y=Y, E=E)
        if ck:
            os.makedirs(a.cache, exist_ok=True)
            pickle.dump(ctx, open(ck, "wb"))
    panel, Y, E = ctx["panel"], ctx["Y"], ctx["E"]
    Q = D.pregame_quotes(panel)
    fams = [f for f in sorted(Q["family"].unique()) if not f.startswith("other:")]
    cells = []
    for fam in fams:
        for hz in HORIZONS:
            base, traj = rows_trajectory(Q, Y, fam, hz)
            cells.append(run_cell(traj, base, fam, hz, "price_trajectory", ["earliest_pregame_two_sided_quote(>=120min older)"]))
            if fam in ("moneyline", "f5_result", "nrfi_yrfi", "team_total"):
                mrows = rows_model(Q, Y, E, fam, hz)
                cells.append(run_cell(mrows, base, fam, hz, "sift_model",
                                      ["SIFT ModelEvaluation probability with pregame run timestamp (lineup/starter/bullpen/park/weather inputs as of that run; per-input timestamps NOT archived)"]))
    ok = [c for c in cells if c["status"] == "OK"]
    adj = I.holm([c["gain_vs_calibrated_market_logloss"]["p"] for c in ok]) if ok else []
    for c, p in zip(ok, adj):
        c["holm_p"] = float(p)
    for c in cells:
        c["_n_cells"] = len(ok)
        status, reason = classify(c, c["n_contracts"], c["n_games"])
        if c["challenger"] == "sift_model" and c["n_contracts"] == 0:
            status, reason = "MISSING_DATA", "no archived SIFT probability with a pregame run timestamp joined to a two-sided pregame quote and a settled outcome in this horizon"
        c["status_final"], c["reason"] = status, reason
        c.pop("_n_cells", None)
        g = c.get("gain_vs_calibrated_market_logloss")
        c["incremental_gain"] = dict(mean=g["mean"], lo=g["lo"], hi=g["hi"], holm_p=c.get("holm_p")) if g else None
        lg, br = c.get("logloss"), c.get("brier")
        c["market_logloss"] = lg and dict(raw=lg["raw_market"], calibrated=lg["calibrated_market"])
        c["market_brier"] = br and dict(raw=br["raw_market"], calibrated=br["calibrated_market"])
    res = dict(status="RESEARCH_ONLY", schema="sift-outcome-intel-mlb-incremental/1", cells_tried=len(cells), cells_ok=len(ok),
               holm_family_size=len(ok), validated=[(c["family"], c["horizon"], c["challenger"]) for c in cells if c["status_final"] == "VALIDATED_IMPROVEMENT"],
               protocol=__doc__, cells=cells)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    for c in cells:
        g = c.get("incremental_gain")
        print(f"{c['family']:22s} {c['horizon']:4s} {c['challenger']:16s} n={c['n_contracts']:6d} g={c['n_games']:4d} {c['status_final']:28s}",
              g and "gain %+.4f [%+.4f,%+.4f] holm=%.3f" % (g["mean"], g["lo"], g["hi"], g["holm_p"]) or "")
    print("validated:", res["validated"])


if __name__ == "__main__":
    main()
