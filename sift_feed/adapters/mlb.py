"""MLB: production publishes the Edge Finder app bundle to edge-finder-api `main:app/latest/`
(.github/workflows/app-export.yml). In the offseason its board holds no scheduled game, so the
sport is reported "offseason". A game-level MLB adapter is deliberately not mapped yet: when the
board shows upcoming games the sport is reported "unavailable" until one is written and reviewed.
"""
from ..schema import parse_ts
from . import artifact

SPORT = "MLB"
MAX_AGE_HOURS = 24
SOURCES = {"prod": ("edge-finder-api", "main")}
BOARD = "app/latest/board.json"


def build(src, now):
    board = src["prod"].read_json(BOARD)
    art = artifact(src["prod"], BOARD)
    upcoming = [i for i in board.get("items", [])
                if i.get("status") == "SCHEDULED" and (parse_ts(i.get("start_time_utc")) or now) > now]
    last = max((i.get("start_time_utc") or "" for i in board.get("items", [])), default=None) or None
    out = {"artifact": art, "model_version": None, "projected_at": None,
           "bet_authority": board.get("bet_authority"), "authority_note": None, "games": []}
    if not upcoming:
        out.update(status="offseason", reason=f"no scheduled MLB game in the production app board (last game {last})")
    else:
        out.update(status="unavailable", reason=f"{len(upcoming)} scheduled games but no reviewed MLB game-level adapter yet")
    return out
