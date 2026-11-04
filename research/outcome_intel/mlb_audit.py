#!/usr/bin/env python3
"""MLB 2022-2026 market-first evidence audit (RESEARCH_ONLY). Inventory + settlement verification + validity checks + merged per-cell results.
usage: python3 -I research/outcome_intel/mlb_audit.py --root <edge-finder-api main checkout> --out reports/outcome_intel/mlb_audit.json
                [--incremental reports/outcome_intel/mlb_incremental.json] [--pinnacle reports/outcome_intel/mlb_pinnacle.json] [--cache DIR]
Counts are computed here, not copied from any report."""
from __future__ import annotations
import argparse, json, os, pickle, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import mlb_data as D

SEASONS = (2022, 2023, 2024, 2025, 2026)
FAMILY_LABEL = {"moneyline": "moneyline", "f3_result": "F3 result (home/away/tie)", "f5_result": "F5 result (home/away/tie)", "f7_result": "F7 result (home/away/tie)",
                "run_line": "full-game run line", "f5_run_line": "F5 run line", "game_total": "full-game total (ladder)", "f5_total": "F5 total (ladder)",
                "team_total": "team total (ladder)", "nrfi_yrfi": "NRFI/YRFI (first-inning run)", "pitcher_strikeouts": "pitcher strikeouts (ladder)",
                "pitcher_outs": "pitcher outs (ladder)", "hitter_hits": "hitter hits", "hitter_total_bases": "hitter total bases", "hitter_hits_runs_rbis": "hitter H+R+RBI",
                "hitter_rbis": "hitter RBI", "hitter_stolen_bases": "hitter stolen bases"}
LADDERS = {"run_line", "f5_run_line", "game_total", "f5_total", "team_total", "pitcher_strikeouts", "pitcher_outs", "hitter_hits", "hitter_total_bases",
           "hitter_hits_runs_rbis", "hitter_rbis", "hitter_stolen_bases"}
SELECTION_FAMILY = {"ML_Home": "moneyline", "ML_Away": "moneyline", "F5_ML_Home": "f5_result", "F5_ML_Away": "f5_result", "YRFI": "nrfi_yrfi", "NRFI": "nrfi_yrfi",
                    "Game_Total": "game_total", "RL_Home": "run_line", "RL_Away": "run_line", "TT_Home_Over": "team_total", "TT_Away_Over": "team_total"}

PREGAME_INPUTS = [
    dict(input="starting pitchers", exists="YES (SIFT slate/pipeline; MLB probable pitchers)", historical_timestamp="PARTIAL: ModelEvaluation rows carry the model run timestamp (2026-07-30..), not the time each starter was announced; 2022-2025 starters exist only as post-game boxscore facts (probable-starter-as-of-time NOT archived)", usable_as_time_valid=False,
         repair="archive MLB probable-pitcher feed with fetch timestamp daily (statsapi schedule?hydrate=probablePitcher) from now on"),
    dict(input="confirmed lineups", exists="YES 2026 (lineupConfirmationState on observations/evaluations; LINEUP_CONFIRMATION model checkpoint)", historical_timestamp="2026 only: state flag + evaluation run time; the lineup card's own posting time is not stored", usable_as_time_valid="2026 SIFT model rows only",
         repair="store raw lineup JSON with posted_at/fetched_at per game"),
    dict(input="pitch mix / Statcast", exists="YES 2026 pitch-level (data/statcast_raw, 643 games) ; boxscores 2022-2026", historical_timestamp="post-game data; point-in-time features would have to be rebuilt from strictly earlier games (feasible for 2026 pitch data, not done here); NOT a pregame snapshot", usable_as_time_valid=False,
         repair="build rolling pitcher/batter pitch-mix features from games strictly before first pitch, then register as a challenger"),
    dict(input="handedness / platoon", exists="static player attribute", historical_timestamp="time-invariant", usable_as_time_valid="static, but no lineup timestamp so platoon exposure cannot be time-stamped", repair="same as lineups"),
    dict(input="bullpen workload", exists="YES: reconstructable from schedule+boxscores 2022-2026 (MLB-RSCH-0003); data/bullpen.json is a current-day overwrite", historical_timestamp="reconstructable point-in-time (prior games only); no archived pregame bullpen snapshot", usable_as_time_valid="reconstructable, NOT built here", repair="register reconstruction as challenger"),
    dict(input="weather", exists="NO historical archive (Milestone 2 PIT audit: UNAVAILABLE_HISTORICALLY)", historical_timestamp="none", usable_as_time_valid=False, repair="archive forecast at fetch time per game"),
    dict(input="park factors", exists="static season constants", historical_timestamp="season-aggregate; as-of time not stored (C RETROSPECTIVE_LIMITED)", usable_as_time_valid=False, repair="store park-factor table version with date"),
    dict(input="injuries / roster status", exists="NO historical archive", historical_timestamp="none", usable_as_time_valid=False, repair="archive transactions/IL feed with timestamps"),
    dict(input="SIFT projections / model probability", exists="2026-07-30..2026-10-29: ModelEvaluation with pipelineRunId (pregame run time) for ML, F5 ML, YRFI/NRFI, team total", historical_timestamp="ESTABLISHED per row for sources prospective_snapshot and pipeline_recommendations (run id = UTC timestamp); NOT established for source kalshi_discovery_extension (created after the fact)", usable_as_time_valid="prospective_snapshot + pipeline_recommendations only",
         repair="persist model probability with computed_at for every contract family at each capture (game_total, run line, F3/F7, props currently have none or only discovery rows)"),
    dict(input="Pinnacle", exists="YES sampled: 178 dates (every ~5th day) 2022-2026, two snapshots/day (18:15, 21:15 ET), h2h + totals only; no F5", historical_timestamp="ESTABLISHED: snapshot requestedAtIso and bookmaker last_update", usable_as_time_valid="YES (used in mlb_pinnacle.py)", repair="daily + per-game pregame sampling, add F5 via per-event endpoint"),
]


def git_sha(root):
    try:
        return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default="reports/outcome_intel/mlb_audit.json")
    ap.add_argument("--incremental", default="reports/outcome_intel/mlb_incremental.json")
    ap.add_argument("--pinnacle", default="reports/outcome_intel/mlb_pinnacle.json")
    ap.add_argument("--cache", default=None)
    a = ap.parse_args()
    games, gh = D.load_schedule_games(a.root)
    box, bh = D.load_boxscore_runs(a.root)
    obs, oh = D.load_obs(a.root)
    settle, sh = D.load_settlements(a.root)
    E, eh = D.load_evals(a.root)
    panel = D.build_panel(obs, games)
    Y = D.build_outcomes(panel, games, settle)
    Q = D.pregame_quotes(panel)
    sd, conflicts = D.dedup_settlements(settle)
    pin_h = {}
    for f in sorted(os.popen(f"ls {a.root}/data/research_cache/pinnacle_historical/*/*.json").read().split()):
        pin_h[os.path.relpath(f, a.root)] = D.sha256_file(f)

    # ---------------- seasons table
    gsum = games.groupby("season").agg(schedule_games=("gamePk", "size"), final_with_runs=("homeRuns", "count"), doubleheader_games=("doubleHeader", lambda s: int((s != "N").sum())))
    seasons = {}
    pin = json.load(open(a.pinnacle)) if os.path.exists(a.pinnacle) else {}
    for s in SEASONS:
        k = int(panel[panel["season"] == s].shape[0]) if s == 2026 else 0
        seasons[str(s)] = dict(schedule_games=int(gsum.loc[s, "schedule_games"]), final_games_with_runs=int(gsum.loc[s, "final_with_runs"]),
                               boxscore_games=int(sum(1 for pk in box if pk in set(games[games.season == s].gamePk))) if True else None,
                               kalshi_observation_rows=k, kalshi_markets_with_price_history=int(panel[panel["season"] == s]["marketTicker"].nunique()) if k else 0,
                               kalshi_status=("PRESENT (2026-08-01..2026-10-29 captures; regular season captured only from 2026-08-01)" if s == 2026 else "MISSING_DATA: no Kalshi MLB price history archived"),
                               pinnacle_games_matched_pregame=(pin.get("cells", [{}])[0].get("per_season_games", {}).get(str(s)) if pin else None))
    # ---------------- per family inventory (2026 Kalshi)
    ev = E.copy()
    ev["fam"] = [D.family_of(t, None) if str(t).startswith("KXMLB") else SELECTION_FAMILY.get(sel, "other") for t, sel in zip(ev["marketTicker"], ev["selection"])]
    ev["has_p"] = ev["modelFairProbability"].notna()
    fam_inv = {}
    tick = panel.drop_duplicates("marketTicker")
    for fam in sorted(f for f in panel["family"].unique() if not f.startswith("other:")):
        pf = panel[panel["family"] == fam]
        qf = Q[(Q["family"] == fam) & Q["two_sided_ok"]]
        tk = tick[tick["family"] == fam]["marketTicker"]
        ys = Y.loc[Y.index.intersection(tk), :]
        settled = ys[ys["y"].notna()]
        with_quote = settled.index.intersection(qf["marketTicker"].unique())
        near = qf[(qf["mins_before"] <= 60)]["marketTicker"].unique()
        within180 = qf[(qf["mins_before"] <= 180)]["marketTicker"].unique()
        closest = qf.groupby("marketTicker")["mins_before"].min()
        e = ev[(ev["fam"] == fam) & ev["has_p"]]
        e_ts = e[e["source"].isin(["prospective_snapshot", "pipeline_recommendations"])]
        e_disc = e[e["source"] == "kalshi_discovery_extension"]
        ind = ys[ys["y_indep"].notna() & ys["y_edgelab"].notna()]
        fam_inv[fam] = dict(
            label=FAMILY_LABEL.get(fam, fam), ladder_or_alt_lines=fam in LADDERS,
            observation_rows=int(len(pf)), date_range=[str(pf["t_cap"].min()), str(pf["t_cap"].max())],
            unique_contracts_observed=int(len(tk)), pregame_two_sided_rows=int(len(qf)), contracts_with_pregame_two_sided_quote=int(qf["marketTicker"].nunique()),
            price_type="yesBid/yesAsk (cents) + lastPrice; mid used only when both sides present, spread<=10c", price_coverage=dict(
                settled_contracts_with_quote=int(len(with_quote)), share_with_quote_within_60min=float(len(set(near) & set(settled.index)) / max(len(settled), 1)),
                share_with_quote_within_180min=float(len(set(within180) & set(settled.index)) / max(len(settled), 1)),
                median_mins_before_of_closest_quote=float(closest.reindex(with_quote).median()) if len(with_quote) else None,
                row_checkpoints={str(k): int(v) for k, v in pf["checkpoint"].fillna("NONE").value_counts().items()}),
            settlement=dict(official_kalshi_result_archived=False, source="edgelab_settle_markets <- MLB Stats API (derived, not Kalshi's official result)",
                            contracts_total=int(len(tk)), settled_contracts=int(len(settled)), unresolved_or_missing=int(len(tk) - len(settled)),
                            dropped_total_boundary_unverifiable=int((ys["y_src"] == "dropped_total_boundary_unverifiable").sum()),
                            rederived_ge_N=int(ys["y_src"].astype(str).str.startswith("rederived").sum()),
                            independent_rederivation=dict(n_compared=int(len(ind)), n_agree=int((ind["y_indep"] == ind["y_edgelab"]).sum()) if len(ind) else 0,
                                                          note="independent = final runs from MLB schedule (2026 schedule results end ~2026-08-27); not possible for period/props families")),
            unique_settled_contracts_with_pregame_quote=int(len(with_quote)),
            independent_games=int(Y.loc[with_quote, "pk"].nunique()) if len(with_quote) else 0,
            model_probability_coverage=dict(contracts_or_selections_with_prob_and_pregame_timestamp=int(e_ts["marketTicker"].nunique()),
                                            contracts_with_prob_but_timestamp_not_established=int(e_disc["marketTicker"].nunique()),
                                            games_with_timestamped_prob=int(pd.to_numeric(e_ts["gameId"], errors="coerce").nunique())))
    # ---------------- settlement verification
    comp = Y[Y["y_indep"].notna() & Y["y_edgelab"].notna()]
    ver = {}
    for fam, g in comp.groupby("family"):
        ver[fam] = dict(n=int(len(g)), agree=int((g["y_indep"] == g["y_edgelab"]).sum()), disagree=int((g["y_indep"] != g["y_edgelab"]).sum()))
    pre = Y[(Y["family"] == "game_total") & (Y["gdate"] < D.TOTAL_FIX_DATE) & Y["y_edgelab"].notna() & Y["y_indep"].notna()]
    n_boundary = 0
    for t, r in pre.iterrows():
        n = D.parse_suffix(t)[1]
        tot = (r["hr"] + r["ar"]) if pd.notna(r["hr"]) else None
        n_boundary += int(tot is not None and tot == n)
    gt_stored = Y[(Y["family"] == "game_total") & (Y["y_src"].astype(str).str.startswith("rederived"))]
    wrong = int((gt_stored["y"] != gt_stored["y_edgelab"]).sum())
    sdup = settle[settle["marketTicker"].duplicated(keep=False)]
    stat = sd[sd["status"] == "SETTLED"]["gameStatus"].value_counts(dropna=False).to_dict()
    pk_sched = games.set_index("gamePk")
    kal_pk = set(panel["pk"].dropna().astype(int))
    in_s = [p for p in kal_pk if p in pk_sched.index]
    settlement_verification = dict(
        edgelab_settlement_rows=int(len(settle)), unique_marketTickers=int(settle["marketTicker"].nunique()), tickers_with_two_rows=int(sdup["marketTicker"].nunique()),
        conflicting_settled_results_for_one_ticker=int(conflicts), unresolved_status_after_dedup=int((sd["status"] != "SETTLED").sum()),
        official_kalshi_result_present_rows=int(settle["officialKalshi"].notna().sum()),
        settled_gameStatus_counts={str(k): int(v) for k, v in stat.items()},
        rain_shortened_or_cancelled_settled_contracts=int(sum(v for k, v in stat.items() if str(k).startswith(("Completed Early", "Cancelled")))),
        independent_vs_stored_by_family=ver,
        KNOWN_DEFECT_total_ladder=dict(
            description="Stored edgelab settlement for KXMLBTOTAL (and F3/F5/F7 total) rungs settles YES iff total > N for games before 2026-09-01; Kalshi pays YES iff total >= N. Disagrees ONLY at total == N. From 2026-09-01 stored results follow >= N (verified with team-total-pinned totals).",
            repo_doc="docs/EDGELAB_KALSHI_TOTAL_LADDER_SEMANTICS.md (repo states stored rows are NOT rewritten)",
            game_total_boundary_rungs_wrongly_settled_NO_in_stored_data=wrong,
            action_taken="game_total before 2026-09-01 re-derived with >= N from schedule/team-total pins; contracts without a derivable total and all F3/F5/F7 totals before 2026-09-01 are DROPPED (cannot be verified)"),
        schedule_coverage_for_kalshi_games=dict(kalshi_gamepks=len(kal_pk), in_schedule_regular_season=len(in_s), postseason_or_unmapped=len(kal_pk) - len(in_s)),
        schedule_final_runs_end=str(pd.to_datetime(games[games["homeRuns"].notna() & (games["season"] == 2026)]["gameDate"], utc=True).max()),
        doubleheaders_in_kalshi_games=int(sum(1 for p in in_s if pk_sched.loc[p, "doubleHeader"] != "N")),
        postponed_or_resched_signals=dict(gamepks_with_multiple_scheduled_starts=int((panel.dropna(subset=["pk"]).groupby("pk")["t_start"].nunique() > 1).sum()),
                                          schedule_states=pk_sched.loc[in_s, "state"].value_counts().to_dict()),
        duplicates=dict(duplicate_observation_ticker_capturedAt=int(obs.duplicated(["marketTicker", "capturedAt"]).sum())))
    # ---------------- pregame validity check vs the repo's own flag
    flagged = panel[panel["isValidPregameObservation"] == True]
    bad = flagged[flagged["mins_before"] <= 0]
    validity = dict(rows_flagged_isValidPregameObservation_true=int(len(flagged)), of_which_captured_at_or_after_earliest_known_scheduled_first_pitch=int(len(bad)),
                    median_minutes_after_scheduled_start=float((-bad["mins_before"]).median()) if len(bad) else None,
                    interpretation="The repo flag is not equivalent to 'captured before scheduled first pitch'. Such rows MAY be pregame if first pitch was delayed (actual first-pitch time is not archived), so this audit excludes them (conservative). They are 'unverifiable', not proven leaks.",
                    rule_used="pregame iff capturedAt < MIN(obs.scheduledStart, schedule gameDate, Kalshi ticker ET start)")
    # ---------------- cells
    cells = []
    inc = json.load(open(a.incremental)) if os.path.exists(a.incremental) else None
    if inc:
        for c in inc["cells"]:
            cells.append(_cell(c, fam_inv, "edgelab_settlement(MLB_STATS_API)"))
    have_sift = {(c["family"], c["horizon"]) for c in (inc["cells"] if inc else []) if c["challenger"] == "sift_model"}
    for fam in fam_inv:
        for hz in ("NEAR", "FAR"):
            if (fam, hz) not in have_sift:
                reason = {"game_total": "Game_Total probability is null in every archived prospective/pipeline evaluation (MISSING_MARKET_PRICE); only discovery_extension rows carry one and those have no established run timestamp",
                          "run_line": "RL_Home/RL_Away probability null in every archived prospective/pipeline evaluation (NO_MODEL_SUPPORT)"}.get(
                    fam, "no archived SIFT probability with an established pregame timestamp for this family (only kalshi_discovery_extension rows, created after the fact); hitter/pitcher props: projections exist for 2026 but are not archived per capture with computed_at")
                cells.append(dict(sport="MLB", family=fam, horizon=hz, challenger="sift_model", inputs_available=[], n_games=0, n_contracts=0,
                                  price_coverage=fam_inv[fam]["price_coverage"], settlement_source=fam_inv[fam]["settlement"]["source"], market_logloss=None, market_brier=None, model_metrics=None,
                                  incremental_gain=None, status="MISSING_DATA", reason=reason + ". Repair: persist model probability with computed_at at each capture."))
    cells.append(dict(sport="MLB", family="ALL", horizon="2022-2025", challenger="any", inputs_available=["sampled Pinnacle only (see mlb_pinnacle cells)"], n_games=0, n_contracts=0,
                      price_coverage=None, settlement_source="n/a", market_logloss=None, market_brier=None, model_metrics=None, incremental_gain=None, status="MISSING_DATA",
                      reason="No Kalshi MLB price history or settlement for 2022-2025 exists in edge-finder-api (Kalshi corpus starts 2026-07-30). This is a COVERAGE GAP, not a negative result. Repair: Kalshi historical-candlestick backfill per market + official settled results."))
    if pin:
        for c in pin["cells"]:
            cells.append(dict(sport="MLB", family=c["family"] + " (Pinnacle baseline)", horizon=c["horizon"], challenger=c["challenger"], inputs_available=c["inputs_available"],
                              n_games=c["n_games"], n_contracts=c["n_contracts"], price_coverage=dict(market="PINNACLE sampled", per_season_games=c["per_season_games"]),
                              settlement_source=c["settlement_source"], market_logloss=c.get("market_logloss"), market_brier=c.get("market_brier"),
                              model_metrics=dict(validation_2025=c.get("validation_2025"), negative_control_holdout_gain=c.get("negative_control_holdout_gain")),
                              incremental_gain=c.get("incremental_gain"), status=c["status_final"], reason=c["reason"], split="train 2022-2024 / validate 2025 / holdout 2026"))
    counts = pd.Series([c["status"] for c in cells]).value_counts().to_dict()
    res = dict(schema="sift-outcome-intel-mlb-audit/1", status="RESEARCH_ONLY",
               inputs=dict(repo="https://github.com/chmoses98/edge-finder-api", branch="main", commit_sha=git_sha(a.root),
                           file_counts=dict(schedule=len(gh), boxscores=len(bh), observations=len(oh), settlements=len(sh), model_evaluations=len(eh), pinnacle=len(pin_h)),
                           sha256=dict(schedule=gh, boxscores=bh, observations=oh, settlements=sh, model_evaluations=eh, pinnacle=pin_h),
                           note="other branches (kalshi-router/MLB, kalshi-router/backfill-MLB, mlb-player-prop-projections, f3-f7-real-structure-verification) were listed; kalshi-router/MLB data/edgelab is a strict subset of main for the tables used"),
               record_counts=dict(observation_rows=int(len(obs)), observation_rows_after_dedup=int(len(panel)), settlement_rows=int(len(settle)), model_evaluation_rows=int(len(E)),
                                  schedule_games=int(len(games)), pregame_two_sided_rows=int(len(Q))),
               seasons=seasons, families_2026_kalshi=fam_inv, settlement_verification=settlement_verification, pregame_flag_validity=validity,
               pregame_input_availability=PREGAME_INPUTS, status_counts=counts, cells=cells)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print("status counts", counts)
    for f, v in fam_inv.items():
        print(f"{f:22s} contracts={v['unique_contracts_observed']:6d} settled={v['settlement']['settled_contracts']:6d} w/quote={v['unique_settled_contracts_with_pregame_quote']:6d} games={v['independent_games']:4d}")


def _cell(c, fam_inv, src):
    f = c["family"]
    return dict(sport="MLB", family=f, horizon=c["horizon"], challenger=c["challenger"], inputs_available=c["inputs_available"], n_games=c["n_games"], n_contracts=c["n_contracts"],
                n_games_baseline=c["n_games_baseline"], n_contracts_baseline=c["n_contracts_baseline"], holdout_games=c.get("holdout_games"), holdout_contracts=c.get("n_holdout"),
                price_coverage=fam_inv.get(f, {}).get("price_coverage"), settlement_source=src, market_logloss=c.get("market_logloss"), market_brier=c.get("market_brier"),
                model_metrics=c.get("model_metrics"), incremental_gain=c.get("incremental_gain"), negative_control=c.get("negative_control_gain"),
                positive_control_detected=c.get("positive_control_detected"), mde_logloss=c.get("mde_logloss_80pct_power"), status=c["status_final"], reason=c["reason"],
                split="chronological by first pitch, train earliest 2/3 games, holdout latest 1/3 (single 2026 season)")


if __name__ == "__main__":
    main()
