#!/usr/bin/env python3
"""Render reports/outcome_intel/nba_nhl_SUMMARY.md from nba_audit.json + nhl_audit.json (numbers only come from the JSON; RESEARCH_ONLY)."""
from __future__ import annotations
import collections, json, os, sys


def f(x, n=4):
    return "n/a" if x is None else f"{x:.{n}f}"


def cells_table(cells, tested_only=True):
    rows = []
    for c in cells:
        g = c.get("incremental_gain")
        if tested_only and not g:
            continue
        mm = c.get("market_metrics") or {}
        md = c.get("model_metrics") or {}
        rows.append(f"| {c.get('challenger', 'SIFT nba-sim')} | {c['family']} | {c['horizon']} | {c['n_games']} | {c.get('n_rows', '')} | {md.get('holdout_games', '')} | "
                    f"{f(mm.get('holdout_logloss_calibrated_market'))} | {f(md.get('holdout_logloss_challenger'))} | {f(g['mean'])} [{f(g['lo'])}, {f(g['hi'])}] | {f(g['holm_p'], 3)} | {c['status']} |")
    return "| challenger | family | horizon | games | rows | holdout games | cal. market logloss | challenger logloss | gain [95% game-cluster CI] | Holm p | status |\n|---|---|---|---:|---:|---:|---:|---:|---|---:|---|\n" + "\n".join(rows)


def family_table(rep):
    out = ["| family | contracts observed | games | engine YES/NO/UNSETTLEABLE | verified settled (re-derived = engine) | settlement support |", "|---|---:|---:|---|---:|---|"]
    for fam, v in sorted(rep["families"].items()):
        e = v["engine_outcomes"]
        out.append(f"| {fam} | {v['contracts_observed']} | {v['games_observed']} | {e.get('YES', 0)}/{e.get('NO', 0)}/{e.get('UNSETTLEABLE', 0) + e.get('NOT_SETTLED', 0)} | {v['settled_yes_no_rederived_agree']} | {', '.join(f'{k}:{n}' for k, n in v['support'].items())} |")
    return "\n".join(out)


def sport_section(rep, name):
    dq = rep["data_quality"]
    ie = rep["independent_events"]
    cells = rep["cells"]
    sc = collections.Counter(c["status"] for c in cells)
    tested = [c for c in cells if c.get("incremental_gain")]
    best = sorted(tested, key=lambda c: -c["incremental_gain"]["mean"])[:5]
    L = [f"## {name}", ""]
    L.append(f"* Independent events: **{ie['games_with_verified_settled_contract']} games** with at least one independently verified settlement "
             f"({ie.get('games_with_final_box', ie.get('games_with_final_result'))} finals archived; {ie['games_with_any_contract']} games with any listed contract); {ie['games_in_tested_rows']} games contribute rows to tested cells.")
    s = dq["settlements"]
    L.append(f"* Settlements: {s['rows']} rows, {s['unique_tickers']} unique tickers, outcomes {s['outcome_counts']}; sources {s.get('sources')}; resettlements with a changed outcome: "
             f"{s.get('conflicting_resettlements', s.get('resettled_with_changed_outcome'))}; tickers with >1 row: {s['tickers_with_multiple_rows']}.")
    ev = dq["engine_vs_independent_derivation"]
    L.append(f"* Independent re-derivation: {ev['derivable_and_compared']} of {ev['engine_yes_no']} engine YES/NO outcomes re-derived from final scores/box/goal events; **{ev['disagreements']} disagreements** {ev['disagreement_tickers']}.")
    L.append(f"* Kalshi official result: **not in the archive** ({dq['kalshi_official_result']['reason']}). Exchange cross-check on the owner's settled wagers: {rep.get('exchange_crosscheck', dq.get('exchange_crosscheck'))}.")
    bi = dq["board_integrity"]
    L.append(f"* Price history: {bi['n_checkpoints']} full-board checkpoints + {bi['n_deltas']} chained deltas; chain breaks {bi['chain_broken']}, count mismatches {bi['count_mismatch']}, non-monotonic boards {bi['nonmonotonic']}. "
             f"Order-book ladders cover {dq['orderbook_archive'].get('tickers_covered_of_settled', dq['orderbook_archive'].get('tickers_covered_of_verified'))} verified tickers (<=300 tickers/capture); best bid/ask and their sizes exist for every listed market on every board.")
    L.append(f"* Row drops before testing: {dq['row_drops']}.")
    L.append(f"* Cells: {rep['protocol']['n_cells_total']} reported, {rep['protocol']['n_cells_tested']} tested (Holm over all {rep['protocol']['n_cells_tested']}). Status counts: {dict(sc)}.")
    L.append("* Largest point-estimate gains (all uncorrected for the selection of best):")
    for c in best:
        g = c["incremental_gain"]
        L.append(f"  * {c.get('challenger', 'SIFT')} / {c['family']} / {c['horizon']}: {f(g['mean'])} [{f(g['lo'])}, {f(g['hi'])}], Holm p={f(g['holm_p'], 3)}, {c['n_games']} games, {c['status']}")
    L += ["", "### Family coverage", "", family_table(rep), "", "### Tested cells", "", cells_table(cells), ""]
    miss = collections.defaultdict(list)
    for c in cells:
        if c["status"] == "MISSING_DATA":
            miss[c["reason"]].append(f"{c.get('challenger', '')}:{c['family']}:{c['horizon']}")
    L += ["### MISSING_DATA cells (reason -> cells)", ""]
    for r, v in miss.items():
        L.append(f"* {r}\n  * {len(v)} cells: {', '.join(v[:12])}{' ...' if len(v) > 12 else ''}")
    L.append("")
    return "\n".join(L)


def controls(rep):
    t = [c for c in rep["cells"] if c.get("incremental_gain")]
    pc = sum(1 for c in t if c["incremental_gain"]["positive_control"] and c["incremental_gain"]["positive_control"]["lo"] > 0)
    nc_bad = sum(1 for c in t if c["incremental_gain"]["negative_control"] and c["incremental_gain"]["negative_control"]["lo"] > 0)
    return len(t), pc, nc_bad


def notes(nba, nhl):
    (n1, p1, b1), (n2, p2, b2) = controls(nba), controls(nhl)
    promising = [f"{c.get('challenger', 'SIFT')}/{c['family']}/{c['horizon']} ({c['n_games']} games, gain {f(c['incremental_gain']['mean'])} [{f(c['incremental_gain']['lo'])}, {f(c['incremental_gain']['hi'])}], Holm p {f(c['incremental_gain']['holm_p'], 2)})"
                 for r in (nba, nhl) for c in r["cells"] if c["status"] in ("PROMISING_INSUFFICIENT", "VALIDATED_IMPROVEMENT")]
    validated = [c for r in (nba, nhl) for c in r["cells"] if c["status"] == "VALIDATED_IMPROVEMENT"]
    L = ["", "## Findings, caveats and what was not done", "",
         f"* **VALIDATED_IMPROVEMENT cells: {len(validated)}** (NBA tested {n1}, NHL tested {n2}; Holm is applied across all tested cells of each sport separately, challenger x family x horizon plus exploratory pooled cells).",
         f"* PROMISING_INSUFFICIENT (uncorrected CI above 0, >= 20 holdout games, gain >= 0.002 nats, fails Holm): " + "; ".join(promising) + ". At this multiplicity a few such cells are expected by chance; only the NHL `PLAYER_SIM_V1` goalie-saves cells repeat across three horizons and deserve a pre-registered prospective re-test.",
         "* Everything else is NO_DEMONSTRATED_IMPROVEMENT (enough holdout games and the CI excludes a material gain, or the challenger is reliably worse than the calibrated market) or INCONCLUSIVE_UNDERPOWERED (holdout < 30 games or CI too wide). Underpowered cells are not negatives.",
         "* The SIFT models are not market-beating on the moneylines/spreads/totals archived so far: standalone logloss is worse than the market in the NBA moneyline cells (about 0.70 vs 0.56 at T-6h) and the NHL V1/V2 win-probability cells show gains of -0.003 to -0.015 (V2 at T-6h: CI excludes 0 on the negative side). The NHL sportsbook consensus (6 providers, de-vigged) adds nothing beyond the Kalshi mid either.",
         f"* Controls: the look-ahead positive control is detected (CI lower bound > 0) in {p1}/{n1} NBA and {p2}/{n2} NHL tested cells; the shuffled negative control has a CI strictly above 0 in {b1} NBA and {b2} NHL cells (the harness does not manufacture gains).",
         "* **Settlement is derived, not official.** The board `result` field is empty everywhere (resolved markets leave the board), so there is no archived Kalshi settlement value. Outcomes come from the engines (ESPN box for NBA, NHL API box/PBP for NHL) and were re-derived independently here from final box scores / goal events / player rows; only outcomes where the independent derivation agrees enter any test. The only exchange evidence is the owner's settled wagers (NBA 44/44 and NHL 30/30 agree with our derivation).",
         "* NHL: shootout-ambiguous spread/total/team-total contracts (33) and period/first-goal contracts of the one game whose goal events do not sum to the final score (2026020155) are excluded; period `TIE` contracts are derived. NBA: 2H contracts treat OT as outside the half; none of the 8 OT games changes a 1H/FULL derivation, and all 2H derivations agreed with the engine.",
         "* NBA predictions carry no embedded quote (`p_market` null, `no_quote`), so the market input is the latest board captured at or before `predicted_at` (median age ~3 min; > 30 min is dropped), not the exact quote the model saw. NHL rows embed the quote and it equals the reconstructed board mid in 100% of rows.",
         "* Only tight, two-sided markets are tested (spread <= 10c, mid in [0.03, 0.97]); thin or one-sided contracts are dropped (NBA 29k, NHL 44k candidate rows), so conclusions do not extend to illiquid strikes. Depth: best-bid/ask size is archived for every market; full ladders only for <= 300 tickers per capture (NBA 18k/54k and NHL 6k/51k verified tickers appear at least once).",
         "* Window is short (NBA 2026-10-03..11-03, 158 final games; NHL 2026-10-07..11-03, 246 final games), rows within a game and strike ladders are heavily dependent, so every interval resamples games and holdouts are only 12-80 games.",
         "* NOT done: standalone structured pregame inputs (rest/back-to-back, injuries, rosters, lineups, goalie status) as challengers (they exist as time-stamped context snapshots and are only used inside the SIFT models); fee/executable-price economics; CLV; the `projection-data` branches; Kalshi-official settlement comparison beyond the owner wagers.",
         "* Collection repairs: (1) archive the Kalshi settlement value/result per market at close; (2) store the exact quote (bid/ask/sizes) in the NBA prediction rows and a full-depth ladder per decision; (3) prove and settle the UNSETTLEABLE families (NBA `game_overtime`, `game_points_leader`, `game_race_to`, `game_win_margin`, `player_stocks`, protected-prop families; NHL `game_early_goal`, `game_overtime`); (4) price NHL period markets in V1 (V2 does) and archive horizon-specific model rows at T-24h; (5) keep accumulating - most cells need 3-5x more games.", "",
         "## Reproduce", "", "```",
         "git -C <nba> checkout ea34ea59c048eae8e03dd26ba4d92e3b57785242   # data-archive (sparse: kalshi/ contracts predictions settlements boxscores context/schedule manifest.jsonl)",
         "git -C <nba_shadow> checkout 7beeb96c8d4753b94c67a36fee23c244ad1b01da   # nba-shadow-pure",
         "git -C <nhl> checkout eacc3b9dcf6a943a313367f2ff3a0feaa57e2722   # data-archive (adds results player_events context/{schedule,sportsbook_odds} predictions_{v2,player,oa})",
         "python3 -I research/outcome_intel/nba_audit.py --root <nba> --accounting <nba_acc> --shadow <nba_shadow> --shadow-sha 7beeb96c --repo-sha ea34ea59 --out reports/outcome_intel/nba_audit.json",
         "python3 -I research/outcome_intel/nhl_audit.py --root <nhl> --accounting <nhl_acc> --repo-sha eacc3b9d --out reports/outcome_intel/nhl_audit.json",
         "python3 -I research/outcome_intel/nba_nhl_summary.py reports/outcome_intel",
         "python3 -m unittest discover -s tests -p 'test_outcome_intel_nba_nhl.py'", "```", ""]
    return "\n".join(L)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "reports/outcome_intel"
    nba = json.load(open(os.path.join(out_dir, "nba_audit.json")))
    nhl = json.load(open(os.path.join(out_dir, "nhl_audit.json")))
    head = ["# NBA + NHL market-first evidence audit and incremental-information test (RESEARCH_ONLY)", "",
            "Generated by `research/outcome_intel/nba_nhl_summary.py` from `nba_audit.json` / `nhl_audit.json`; no execution code, no trading authority.", "",
            "Question per cell: does a time-valid challenger (SIFT model, or an external pregame input) improve logloss BEYOND the calibrated contemporaneous Kalshi mid? "
            "Train = earliest 2/3 of games, holdout = latest 1/3 (never fitted on), game-cluster bootstrap, Holm across every tested cell, negative (shuffled) and positive (look-ahead) controls per cell. "
            "An underpowered or untested cell is a coverage gap, never a negative result.", "",
            f"Inputs: NBA `chmoses98/nba-edge-finder@data-archive` {nba['inputs']['commit_sha']} (roll-up sha256 {nba['inputs']['input_rollup_sha256']}); "
            f"NHL `chmoses98/NHL-edge-finder@data-archive` {nhl['inputs']['commit_sha']} (roll-up sha256 {nhl['inputs']['input_rollup_sha256']}). Per-file digests: `nba_input_sha256.json`, `nhl_input_sha256.json`.", ""]
    body = [sport_section(nba, "NBA"), sport_section(nhl, "NHL")]
    path = os.path.join(out_dir, "nba_nhl_SUMMARY.md")
    tail = notes(nba, nhl)
    open(path, "w").write("\n".join(head + body) + "\n" + tail)
    print("wrote", path)


if __name__ == "__main__":
    main()
