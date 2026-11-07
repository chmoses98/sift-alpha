"""Autonomous research loop (RESEARCH_ONLY): detect gaps -> emit repair cases -> summarise experiments -> prioritise next.

Pure functions over files the lab already produces, so the same loop runs for any sport that supplies a game table, a ledger and a market report.
Missing inputs become cases in the shape alpha_engine.repair_queue.choose_next consumes (id, evidence, priority); nothing is invented or substituted.
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd


def coverage_by_season(gt: pd.DataFrame, cols: list[str]) -> dict:
    """Share of non-null values of each input column per season (the denominator is every game in the table, never a filtered subset)."""
    out = {}
    for c in cols:
        if c not in gt:
            out[c] = {"status": "COLUMN_ABSENT"}
            continue
        out[c] = {int(s): round(float(g[c].notna().mean()), 4) for s, g in gt.groupby("season")}
    return out


def detect_gaps(gt: pd.DataFrame, contract_diag: dict, inj_diag: dict, input_cols: list[str], min_cov: float = 0.9) -> list[dict]:
    """Turn measured holes into repair cases with evidence and a priority (higher = fix first)."""
    cases = []
    miss = contract_diag.get("no_game_ids") or []
    if miss:
        cases.append({"id": "nfl:game_table_missing_postseason_2025", "priority": 90, "family": "all game-level + player prop",
                      "evidence": {"games_missing": miss, "contracts_dropped": contract_diag.get("no_game_in_table"), "total_contracts": contract_diag.get("contracts")},
                      "action": "extend the nflverse-derived game table through the 2025 postseason once the schedule/results files include it"})
    unres = contract_diag.get("unresolved_player", 0)
    if unres:
        cases.append({"id": "nfl:player_name_to_gsis_unresolved", "priority": 60, "family": "player props",
                      "evidence": {"contracts_unresolved": unres, "total_contracts": contract_diag.get("contracts")},
                      "action": "extend name->gsis_id mapping (rosters by season/team) for unresolved Kalshi player names"})
    dropped = (inj_diag or {}).get("rows_without_timestamp")
    if dropped:
        cases.append({"id": "nfl:injury_report_timestamps_pre_2016", "priority": 50, "family": "player props, game",
                      "evidence": {"rows_dropped_no_timestamp": dropped},
                      "action": "find a free archive with report-publication times, or keep injuries flagged partial point-in-time"})
    for c, cov in coverage_by_season(gt, input_cols).items():
        if cov.get("status") == "COLUMN_ABSENT":
            continue
        bad = {s: v for s, v in cov.items() if v < min_cov}
        if bad:
            cases.append({"id": f"nfl:input_gap:{c}", "priority": 40, "family": "game", "evidence": {"seasons_below_min": bad, "min_cov": min_cov},
                          "action": f"backfill {c} for the listed seasons from a free source or drop it for those seasons"})
    cases.sort(key=lambda x: -x["priority"])
    return cases


def ledger_summary(paths: list[Path]) -> dict:
    n = ok = fail = 0
    for p in paths:
        if not Path(p).exists():
            continue
        for line in open(p):
            n += 1
            r = json.loads(line)
            fail += 1 if r.get("status") == "failed" or r.get("error") else 0
    return {"experiments": n, "failed": fail}


def next_experiments(market_report: dict, alpha: float = 0.05) -> list[dict]:
    """Rank where a further experiment could still change a conclusion: families whose model-vs-market CI still includes zero come first."""
    items = []
    for fam, v in market_report.get("predictive", {}).items():
        g = v["logloss_gain"]
        lo, hi = g["ci"]
        if hi < 0:
            verdict, value = "MARKET_BETTER", 0.2
        elif lo > 0:
            verdict, value = "MODEL_BETTER_UNCONFIRMED", 1.0
        else:
            verdict, value = "INCONCLUSIVE", 0.8 + min(0.2, 1.0 / max(1, v["games"] ** 0.5))
        items.append({"family": fam, "verdict": verdict, "gain": round(g["mean"], 4), "games": v["games"], "priority": round(value, 3)})
    return sorted(items, key=lambda x: -x["priority"])


def run_loop(gt, contract_diag, inj_diag, input_cols, ledger_paths, market_report, out: Path) -> dict:
    res = {"mode": "RESEARCH_ONLY", "repair_cases": detect_gaps(gt, contract_diag, inj_diag, input_cols),
           "ledger": ledger_summary(ledger_paths), "next_experiments": next_experiments(market_report)}
    Path(out).write_text(json.dumps(res, indent=1, default=str))
    return res
