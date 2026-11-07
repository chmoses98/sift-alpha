"""Aggregate-only dashboard summary of the independent laboratory (RESEARCH_ONLY).  No tickers, no per-order data, no profitability claim."""
from __future__ import annotations
import json
from pathlib import Path


def verdict(g: dict) -> str:
    lo, hi = g["ci"]
    return "MARKET_BETTER" if hi < 0 else ("MODEL_BETTER_UNCONFIRMED" if lo > 0 else "NO_DIFFERENCE_DETECTED")


def build(lab: Path, prospective: Path) -> dict:
    before = json.load(open(lab / "market_lab_report_before_repairs.json"))
    after = json.load(open(lab / "market_lab_report.json"))
    cov = json.load(open(lab / "coverage_report.json"))
    cases = json.load(open(lab / "repair_cases.json"))["cases"]
    rows = []
    for fam, a in after["predictive"].items():
        b = before["predictive"].get(fam)
        rows.append({"family": fam, "n_before": b["n"] if b else None, "games_before": b["games"] if b else None, "gain_before": b["logloss_gain"]["mean"] if b else None,
                     "n_after": a["n"], "games_after": a["games"], "gain_after": a["logloss_gain"]["mean"], "ci_after": a["logloss_gain"]["ci"], "verdict": verdict(a["logloss_gain"]),
                     "mean_model_p": a["mean_model_p"], "mean_market_mid": a["mean_mid"], "base_rate": a["base_rate"]})
    rep = json.load(open(prospective / "REPORT.json")) if (prospective / "REPORT.json").exists() else {}
    pred = [json.loads(l) for l in open(prospective / "predictions.jsonl")] if (prospective / "predictions.jsonl").exists() else []
    quo = sum(1 for _ in open(prospective / "quotes.jsonl")) if (prospective / "quotes.jsonl").exists() else 0
    return {"mode": "RESEARCH_ONLY", "claim_boundary": "Model-vs-market log-loss on the 2025 season (already examined; not an untouched holdout). No family shows a model advantage over Kalshi prices; nothing here is an after-fee edge.",
            "families": sorted(rows, key=lambda r: r["family"]),
            "player_bias": json.load(open(lab / "player_bias_audit.json")) if (lab / "player_bias_audit.json").exists() else None,
            "repair_cases": [{"id": c["id"], "priority": c["priority"], "status": c["status"], "family": c.get("family")} for c in cases[:12]],
            "coverage": {"archive_settled_by_family": {f: sum(v.values()) for f, v in cov["archive_settled_by_family_season"].items()}, "weather_roof_aware_2025": cov["weather_roof_aware"].get("2025")},
            "prospective_2026": {"frozen_model": "nfl_totals_v1", "predictions": len(pred), "quotes": quo, "decision_games": (rep.get("evaluation") or {}).get("decision_games", 0), "status": (rep.get("evaluation") or {}).get("status", "NO_DECISIONS_YET"),
                                 "inference": "withheld until >= 60 settled decision games"}}
