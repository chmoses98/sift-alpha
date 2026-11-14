"""Which catalog inputs depend on market prices/lines (RESEARCH_ONLY). Enforces the market-free policy at the catalog level.

  BENCHMARK_ONLY   defined from prices/lines/odds: never a predictor; used only to benchmark a finished model.
  HYBRID_REBUILD   the catalog measures it partly from a spread/total/line; allowed in a primary model ONLY after rebuilding from the model's own forecast (marketfree.own_script).
  INCIDENTAL       the measurement text mentions prices/lines only to validate or benchmark; the feature itself is market-free.
Detection is a regex over label+measurement; every hit must be classified here (a test fails on an unclassified hit, so new catalog text cannot silently add a market dependency).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAT = ROOT / "research/input_research/catalog"
OUT = ROOT / "research/input_research/market_dependency.json"
RX = re.compile(r"((point )?spread\b|closing (line|total|price)|market[- ]implied|implied (team )?(total|points|pts|lambda)|\bodds\b|sportsbook|consensus line|moneyline|total line|line movement|market (line|total|price|spread|calibration)|from (the )?(spread|line)|vs (the )?line|around (market )?lines|bookmaker)", re.I)
BENCHMARK_ONLY = {"nba.implied_team_totals", "cbb.implied_team_totals", "cfb.market_ratings", "soc.market_odds", "soc.implied_lambda_from_lines", "soc.favourite_longshot_bias", "ten.market_odds",
                  "ten.market_margin_bias", "nba.market_calibration_bias", "cbb.market_calibration_bias", "nfl.score_resid", "cfb.score_resid", "nba.score_resid", "cbb.score_resid"}
PRICE_M = re.compile(r"^m\.(external_lines|quote_history|orderbook_depth|trade_tape|volume_oi|ladder_structure|combo_pricing|fees)$")
HYBRID_REBUILD = {"nfl.ratings": "own power ratings from results (opponent-adjusted EPA/Elo); drop the market-implied history",
                  "nfl.garbage_time": "blowout probability from own margin forecast", "nfl.script": "game script from own margin/total forecast", "nfl.two_minute_tempo": "hurry-up tendency from own margin forecast",
                  "nfl.qb": "QB status from timestamped reports, not from line moves", "nfl.team_total_split": "team points split from own margin and total forecast",
                  "cfb.sp_plus": "composite ratings from results only", "cfb.script": "script from own margin forecast", "cfb.blowout_management": "blowout probability from own margin forecast",
                  "cfb.pass_rate": "pass rate vs own expected margin", "cfb.half_split": "half scoring split vs own forecast", "cfb.offense_style": "style clash without line-based expectations",
                  "cfb.td_rates": "TD rates vs own forecast game script", "cfb.team_total_split": "team points split from own forecast",
                  "nba.pace": "pace from own possessions model", "nba.lineup_adj_rating": "availability-adjusted rating without the closing spread as anchor", "nba.garbage": "blowout probability from own margin forecast",
                  "nba.ot_model": "overtime frequency by own margin/total bucket", "nba.late_game_script": "late-game script from own margin forecast", "nba.minutes": "minutes with blowout risk from own forecast",
                  "nba.bench_scoring": "bench share vs own margin forecast", "cbb.ratings": "ratings from results only", "cbb.conf_strength": "conference strength from cross-conference results only",
                  "cbb.ot_model": "overtime by own margin bucket", "cbb.blowout_garbage": "blowout probability from own margin forecast", "cbb.late_game_foul_script": "foul script from own margin forecast",
                  "cbb.player_minutes": "minutes with blowout risk from own forecast", "nhl.game_script_prob": "pregame script distribution from own win-probability model", "nhl.reg_tie_model": "regulation tie probability from own goal model",
                  "mlb.extras_prob": "extra-innings probability from own tie-after-nine model"}


def classify_all() -> dict:
    out = {"benchmark_only": {}, "hybrid_rebuild": {}, "incidental": {}, "unclassified_regex_hits": []}
    for sp in ("NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"):
        c = json.loads((CAT / f"{sp}.json").read_text())
        for i, r in c["inputs"].items():
            hit = bool(RX.search(r["label"] + " || " + r["measurement"]))
            if PRICE_M.match(i) or i in BENCHMARK_ONLY:
                out["benchmark_only"].setdefault(sp, []).append(i)
            elif i in HYBRID_REBUILD:
                out["hybrid_rebuild"].setdefault(sp, {})[i] = HYBRID_REBUILD[i]
            elif hit:
                out["incidental"].setdefault(sp, []).append(i)
    return out


def kind(iid: str) -> str:
    if PRICE_M.match(iid) or iid in BENCHMARK_ONLY:
        return "benchmark_only"
    return "hybrid_rebuild" if iid in HYBRID_REBUILD else "clean_or_incidental"


if __name__ == "__main__":
    r = classify_all()
    OUT.write_text(json.dumps({"schema_version": "market-dependency-1.0", "status": "RESEARCH_ONLY", **r}, indent=0, sort_keys=True))
    print({k: sum(len(v) for v in r[k].values()) if isinstance(r[k], dict) else len(r[k]) for k in r})
