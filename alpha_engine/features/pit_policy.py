"""Point-in-time policy for raw fields (RESEARCH_ONLY): what may NEVER appear as a pregame input.

Owner's explicit rules (2026-11-09): observed weather must never replace an actual pregame forecast; final lineups, game-day outcomes and revised / retrieval-time rankings cannot appear as pregame
inputs. A raw field below is FORBIDDEN as a pregame input: a computed feature that depends on it (shown by the replay's vintage-dependence or role-field tests) is QUARANTINED: it stays available for
post-hoc analysis, is marked `final_postgame` by the feature framework and cannot count as pregame-computable until a vintaged replacement (a pregame forecast, probable-starter / lineup / ranking
snapshot taken before the event) exists in history.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUARANTINE_FILE = ROOT / "research/input_research/data_foundation/pit_quarantine.json"

# "<table>.<column>" as named by the replay tests -> policy class
FIELD_POLICY = {
    "games.temp": "OBSERVED_WEATHER", "games.wind": "OBSERVED_WEATHER", "schedule.temp": "OBSERVED_WEATHER", "schedule.wind": "OBSERVED_WEATHER", "schedule.weather_condition": "OBSERVED_WEATHER",
    "raw.home_rank": "RETRIEVAL_TIME_RANK", "raw.away_rank": "RETRIEVAL_TIME_RANK",
    "schedule.home_plate_ump_id": "AS_PLAYED_OFFICIAL",
    "schedule.home_lineup": "AS_PLAYED_LINEUP", "schedule.away_lineup": "AS_PLAYED_LINEUP", "schedule.home_sp_id": "AS_PLAYED_LINEUP", "schedule.away_sp_id": "AS_PLAYED_LINEUP",
    "goalies.starter": "FINAL_STARTER_FLAG", "box.gs": "FINAL_STARTER_FLAG", "box.bat_order": "FINAL_STARTER_FLAG", "box.pos": "FINAL_STARTER_FLAG", "player_games.started": "FINAL_STARTER_FLAG", "player_games.dnp_reason": "FINAL_STARTER_FLAG",
}
CLASS_RULE = {
    "OBSERVED_WEATHER": "recorded game-time weather is not a forecast: a pregame weather input needs a forecast as issued (vintage)",
    "RETRIEVAL_TIME_RANK": "rank / record attached at retrieval time is a revised, after-the-fact value: needs a ranking snapshot dated before the game",
    "AS_PLAYED_OFFICIAL": "the crew recorded for the game after it was played: needs the assignment as published before the game",
    "AS_PLAYED_LINEUP": "final lineup / probable pitcher as retrieved after the game: needs the lineup or probable-pitcher snapshot with its posting time",
    "FINAL_STARTER_FLAG": "the game's own final starter / participation flag defines which rows exist: needs a pregame confirmed-starter (or probable-starter) vintage",
}


def classify(field: str) -> str | None:
    return FIELD_POLICY.get(field)


def load_quarantine() -> dict:
    """spec catalog id -> {"fields": [...], "classes": [...]} derived from replay evidence by data_foundation.verified_coverage."""
    try:
        return json.loads(QUARANTINE_FILE.read_text()).get("specs", {})
    except (OSError, ValueError):
        return {}
