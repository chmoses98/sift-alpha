"""Point-in-time CFB game ↔ captured market ↔ official score staging.

Crucial: this is verified internal repo linkage, NOT proof of independent
Kalshi contract settlement or ask-side execution. Events preserve when each
piece of information became available and never retroactively relabel quotes.
"""
from __future__ import annotations

from collections import Counter
from .audits import audit_cfb


def assemble_cfb_game_timeline(records):
    # Validates event identity, kickoff, capture windows, result and exclusions
    quality = audit_cfb(records)
    games = []
    ordering = Counter()
    for game in records:
        captured = game["capture"].get("entry")
        price_time = captured["captured_at"] if captured else None
        research_time = game["final_pregame"]["recorded_at"]
        kickoff = game["kickoff_utc"]
        resolved = game["settled_at"]
        events = [{
            "at": research_time,
            "kind": "RESEARCH_CLAIMS_ARCHIVED",
            "data_available": "research claims published in separate source artifact",
            "artifact_hash": game["final_pregame"].get("claims_artifact_hash"),
            "point_in_time_warning": "Do not apply claims to any earlier market observation",
        }, {
            "at": kickoff,
            "kind": "GAME_START",
            "data_available": "kickoff boundary only, not game result",
        }, {
            "at": resolved,
            "kind": "POSTGAME_SCORE_OBSERVED",
            "data_available": "final score known only after game",
            "score": {
                "control": game["settlement"]["control_points"],
                "opponent": game["settlement"]["opponent_points"],
            },
            "control_won": game["settlement"]["control_won"],
            "kalshi_contract_result": "NOT_INDEPENDENTLY_VERIFIED",
        }]
        if captured:
            ordering["priced_games"] += 1
            availability = "RESEARCH_KNOWN_AT_CAPTURE" if research_time <= price_time else "RESEARCH_NOT_YET_PUBLISHED"
            ordering["research_before_or_at_quote" if research_time <= price_time else "quote_before_research"] += 1
            events.append({
                "at": price_time, "kind": "KALSHI_MARKET_PRICE_CAPTURE",
                "ticker": game["capture"]["market_ticker"],
                "observed_control_price": captured["price"],
                "price_semantics": "Control-side captured entry proxy, not independently certified ask/fill",
                "research_availability_at_quote": availability,
                "physical_game_id": str(game["event_id"]),
            })
        else:
            ordering["unpriced_games"] += 1
        events.sort(key=lambda x: (x["at"], x["kind"]))
        games.append({
            "sport": "CFB",
            "source_game_key": game["game_key"],
            "physical_game_id": str(game["event_id"]),
            "physical_game_id_system": "ESPN id as recorded by CFB source; independent mapping pending",
            "market_ticker": game["capture"]["market_ticker"],
            "away": game["teams"]["away"]["name"],
            "home": game["teams"]["home"]["name"],
            "start_time": kickoff,
            "events": events,
            "status": "HISTORICAL_CONTEXT_RECONSTRUCTION_RESEARCH_ONLY",
        })
    return {
        "sport": "CFB",
        "status": "GAMES_AND_PRICES_RECONSTRUCTED_FROM_PROSPECTIVE_RECORDS",
        "game_count": len(games),
        "quote_coverage": dict(sorted(ordering.items())),
        "data_quality": quality,
        "game_examples": games[:5],
        "game_event_count": sum(len(g["events"]) for g in games),
        "limitations": [
            "Original source claims artifact content is not ingested: availability established only from recorded publication time",
            "Market quoted control-side price not independently certified as executable ask",
            "Game id is recorded by CFB repo; market/result orientation not independently corroborated",
            "This is a selected 25-game prospective subset, not the full CFB market universe",
            "Postgame scores must never be exposed to pregame feature construction",
        ],
    }
