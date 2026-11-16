"""Cross-sport overview built ONLY from the per-sport summary.json files (no archive access).

    python -m alpha_engine.game_completeness.report

Writes research/game_completeness/overview.json and docs/GAME_COMPLETENESS.md.

Readiness here is DATA COMPLETENESS for historical research, nothing else: it says whether the records a market
family settles on and is explained by are archived and read back.  It is not evidence of edge, not a model
verdict, and not a training-ready certification (that still needs the blind re-implementation the input mission
requires).
"""
import json
from pathlib import Path

from .model import PROSPECTIVE_ONLY, RECOVERABLE, STATUSES

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "game_completeness"
DOC = ROOT / "docs" / "GAME_COMPLETENESS.md"
SPORTS = ("MLB", "NFL", "NBA", "NHL", "CBB", "CFB")

# market family -> dataset keys whose completeness bounds historical research on it (per sport)
FAMILIES = {
    "MLB": {"game result / spread / total": ("team_box",), "inning markets (F3/F5/F7, RFI)": ("team_box", "inning_linescore"),
            "pitcher props (K, outs)": ("pitcher_box",), "hitter props (H, TB, HR, RBI, SB)": ("hitter_box",),
            "pitch-level research": ("pitch_events",), "pregame-conditioned (starters, lineups)": ("probable_pitchers_pregame", "confirmed_lineup_pregame"),
            "market pricing vs outcome": ("kalshi_pregame_quotes", "kalshi_settlement_official")},
    "NFL": {"game result / spread / total": ("play_by_play",), "player props": ("player_stats", "snap_counts"),
            "play-level research (EPA, personnel)": ("play_by_play", "participation"),
            "pregame-conditioned (injuries, weather)": ("injuries_pregame_vintage", "weather_forecast_pregame"),
            "market pricing vs outcome": ("kalshi_pregame_quotes",)},
    "NBA": {"game result / spread / total / quarters": ("final_and_quarters", "team_box"), "player props": ("player_box",),
            "possession / lineup research": ("play_by_play", "lineup_stints", "shots_xy"),
            "pregame-conditioned (injuries, starters)": ("injury_report_pregame", "starters_pregame"),
            "market pricing vs outcome": ("kalshi_pregame_quotes", "kalshi_settlement_official")},
    "NHL": {"game result / total / puck line": ("final_result",), "period markets": ("final_result", "period_scores"),
            "skater and goalie props": ("skater_games", "goalie_games"), "shot-quality research": ("shots_xy", "shot_xg", "team_states"),
            "pregame-conditioned (goalie, lines)": ("goalie_pregame", "lines_pregame"),
            "market pricing vs outcome": ("kalshi_pregame_quotes", "kalshi_settlement_official")},
    "CBB": {"game result / spread / total": ("final_score", "team_box"), "half markets": ("final_score", "half_scores"),
            "player props": ("player_box",), "possession research": ("play_by_play",),
            "pregame-conditioned (availability)": ("availability_pregame",), "market pricing vs outcome": ("kalshi_pregame_panel",)},
    "CFB": {"game result / spread / total": ("final_score", "team_box"), "quarter / half markets": ("final_score", "quarter_scores"),
            "player props": ("player_box",), "drive / efficiency research": ("drives", "advanced_epa"),
            "play-level research": ("play_by_play",)},
}


def tier(rate):
    if rate is None:
        return "NOT_ASSESSED"
    return "COMPLETE_DATA" if rate >= 0.98 else "MOSTLY_COMPLETE" if rate >= 0.9 else "PARTIAL_DATA" if rate >= 0.25 else "INSUFFICIENT_DATA"


def build(out=OUT):
    sports, gaps, fam = {}, [], []
    for s in SPORTS:
        p = Path(out) / s / "summary.json"
        if not p.exists():
            continue
        sm = json.loads(p.read_text())
        ds = {d["dataset"]: d for d in sm["datasets"]}
        latest = max(sm["expected_games"]["by_season"])
        rows = []
        for d in sm["datasets"]:
            cur = d["by_season"].get(latest) or {}
            rows.append({"dataset": d["dataset"], "category": d["category"], "expected": d["expected"],
                         **{k: d[k] for k in STATUSES}, "complete_rate": d["complete_rate"],
                         "current_season": latest, "current_expected": cur.get("expected", 0),
                         "current_complete_rate": cur.get("complete_rate"), "recoverability": d["recoverability"],
                         "inputs": d["impact"]["n_inputs"], "markets_primary": d["impact"]["n_markets_primary"]})
            lost = d["MISSING"] + d["STALE"] + d["PARTIAL"]
            if lost:
                gaps.append({"sport": s, "dataset": d["dataset"], "category": d["category"], "title": d["title"],
                             "gap_games": lost, "of_expected": d["expected"], "MISSING": d["MISSING"], "STALE": d["STALE"],
                             "PARTIAL": d["PARTIAL"], "recoverability": d["recoverability"],
                             "class": ("PERMANENTLY_LOST_PAST_GAMES" if d["recoverability"] == PROSPECTIVE_ONLY else
                                       "RECOVERABLE_BACKFILL" if d["recoverability"] == RECOVERABLE else "SOURCE_UNAVAILABLE"),
                             "dependent_inputs": d["impact"]["n_inputs"], "dependent_primary_markets": d["impact"]["n_markets_primary"],
                             "note": d["note"]})
        sports[s] = {"as_of": sm["as_of"], "expected_games": sm["expected_games"]["total"],
                     "final_games": sm["expected_games"]["by_state"].get("FINAL", 0), "datasets": rows}
        for name, keys in FAMILIES[s].items():
            rates = [(ds[k]["complete_rate"], k) for k in keys if k in ds]
            known = [r for r in rates if r[0] is not None]
            lim = min(known) if known else (None, None)
            t = tier(lim[0])
            if lim[1] and lim[0] < 0.9:                           # archived but not read back is not "insufficient"
                d = ds[lim[1]]
                if d["expected"] and (d["COMPLETE"] + d["UNVERIFIED"]) / d["expected"] >= 0.9:
                    t = "ARCHIVED_NOT_READ_BACK"
            fam.append({"sport": s, "family": name, "datasets": list(keys), "limiting_dataset": lim[1],
                        "min_complete_rate": lim[0], "data_tier": t})
    gaps.sort(key=lambda g: (g["class"] != "PERMANENTLY_LOST_PAST_GAMES", -g["gap_games"]))
    ov = {"schema": "game-completeness-overview-1.0", "status": "RESEARCH_ONLY",
          "notice": "data completeness only; agent-run, not human verified; not a training-ready or edge claim",
          "sports": sports, "gaps": gaps, "market_family_data_readiness": fam}
    (Path(out) / "overview.json").write_text(json.dumps(ov, indent=1, sort_keys=True) + "\n")
    return ov


def markdown(ov):
    L = ["# Game-by-game data completeness (RESEARCH_ONLY)", "",
         "Generated by `python -m alpha_engine.game_completeness.report` from `research/game_completeness/<SPORT>/summary.json`. "
         "Agent-run read-back of the archives, **not human verified**. Completeness of archived data only: no claim about "
         "edge, model quality or training readiness. Per-game ledgers: `research/game_completeness/<SPORT>/games.csv.gz`.", "",
         "Status per game x dataset: COMPLETE (records read back, rows and required fields satisfied), PARTIAL, MISSING, "
         "STALE (pregame vintage too old), UNVERIFIED (existence evidence only), RIGHTS_BLOCKED. "
         "`rate` = COMPLETE / expected; nothing else counts toward it. Missing is never treated as zero.", ""]
    for s, v in ov["sports"].items():
        L += [f"## {s}", "", f"Expected games {v['expected_games']:,} ({v['final_games']:,} final), as of {v['as_of']}.", "",
              "| dataset | cat | expected | COMPLETE | PARTIAL | MISSING | STALE | UNVERIFIED | RIGHTS | rate | current season rate | recoverability | inputs | primary markets |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for d in v["datasets"]:
            cur = "-" if d["current_complete_rate"] is None else f"{d['current_complete_rate']:.3f} ({d['current_expected']})"
            rate = "-" if d["complete_rate"] is None else f"{d['complete_rate']:.3f}"
            L.append(f"| {d['dataset']} | {d['category'][0]} | {d['expected']:,} | {d['COMPLETE']:,} | {d['PARTIAL']:,} | {d['MISSING']:,} | "
                     f"{d['STALE']:,} | {d['UNVERIFIED']:,} | {d['RIGHTS_BLOCKED']:,} | {rate} | {cur} | {d['recoverability']} | "
                     f"{d['inputs']} | {d['markets_primary']} |")
        L.append("")
    L += ["## Gaps that cannot be reconstructed (pregame / market vintages of games already played)", "",
          "| sport | dataset | games affected | of expected | MISSING | STALE | PARTIAL | dependent inputs |", "|---|---|---|---|---|---|---|---|"]
    for g in ov["gaps"]:
        if g["class"] == "PERMANENTLY_LOST_PAST_GAMES":
            L.append(f"| {g['sport']} | {g['dataset']} | {g['gap_games']:,} | {g['of_expected']:,} | {g['MISSING']:,} | {g['STALE']:,} | {g['PARTIAL']:,} | {g['dependent_inputs']} |")
    L += ["", "## Gaps recoverable from a source that still serves the history", "",
          "| sport | dataset | games affected | of expected | dependent inputs | primary markets | note |", "|---|---|---|---|---|---|---|"]
    for g in ov["gaps"]:
        if g["class"] == "RECOVERABLE_BACKFILL":
            L.append(f"| {g['sport']} | {g['dataset']} | {g['gap_games']:,} | {g['of_expected']:,} | {g['dependent_inputs']} | {g['dependent_primary_markets']} | {g['note'][:140]} |")
    L += ["", "## Market-family data readiness (completeness only)", "",
          "Tier from the least complete dataset the family depends on: COMPLETE_DATA >= 0.98, MOSTLY_COMPLETE >= 0.90, "
          "PARTIAL_DATA >= 0.25, else INSUFFICIENT_DATA; ARCHIVED_NOT_READ_BACK when the limiting dataset is listed on its "
          "branch but its content was not read in this pass. All seasons pooled.", "",
          "| sport | family | tier | min rate | limiting dataset |", "|---|---|---|---|---|"]
    for f in ov["market_family_data_readiness"]:
        r = "-" if f["min_complete_rate"] is None else f"{f['min_complete_rate']:.3f}"
        L.append(f"| {f['sport']} | {f['family']} | {f['data_tier']} | {r} | {f['limiting_dataset']} |")
    return "\n".join(L) + "\n"


def main():
    ov = build()
    DOC.write_text(markdown(ov))
    print(f"{len(ov['sports'])} sports, {len(ov['gaps'])} gap rows -> {DOC.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
