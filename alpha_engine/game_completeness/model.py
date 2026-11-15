"""Data model: what is expected (Game, DatasetSpec) and what was read back (Observation)."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

COMPLETE, PARTIAL, MISSING, STALE = "COMPLETE", "PARTIAL", "MISSING", "STALE"
UNVERIFIED, RIGHTS_BLOCKED, NOT_APPLICABLE = "UNVERIFIED", "RIGHTS_BLOCKED", "NOT_APPLICABLE"
STATUSES = (COMPLETE, PARTIAL, MISSING, STALE, UNVERIFIED, RIGHTS_BLOCKED)       # NOT_APPLICABLE is outside the denominator

CATEGORIES = {
    "A_GAMES": "games, results, period scores, team box",
    "B_PLAYER": "player box scores, participation, advanced player stats",
    "C_EVENTS": "play-by-play and other event-level data",
    "D_PREGAME": "point-in-time pregame observations (injuries, starters, rosters, weather forecasts)",
    "E_MARKET": "Kalshi contracts, prices and settlements",
}

# What can still be done about a gap.
RECOVERABLE = "RECOVERABLE"                  # the source still serves the historical record
PROSPECTIVE_ONLY = "PROSPECTIVE_ONLY"        # only capturable before the game; a past gap is permanent
UNAVAILABLE = "UNAVAILABLE_AT_SOURCE"        # no permitted source publishes it
RECOVERABILITY = (RECOVERABLE, PROSPECTIVE_ONLY, UNAVAILABLE)

FINAL, SCHEDULED, POSTPONED, CANCELLED = "FINAL", "SCHEDULED", "POSTPONED", "CANCELLED"


def parse_ts(v) -> Optional[datetime]:
    """ISO-8601 / epoch seconds -> aware UTC datetime; None when absent or unparseable (never 'now')."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
    s = str(v).strip().replace("Z", "+00:00")
    if len(s) == 16 and s[8] == "T":                      # 20261115T204835 (compact, as used in archive file names)
        s = f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Game:
    sport: str
    season: str
    game_id: str
    date: str                                   # local game date YYYY-MM-DD
    start_utc: Optional[datetime] = None        # scheduled start; None when the archive carries a date only
    home: str = ""
    away: str = ""
    state: str = FINAL
    meta: dict = field(default_factory=dict)    # adapter extras (roof, neutral, game type) used by DatasetSpec.applies


@dataclass(frozen=True)
class DatasetSpec:
    key: str                                    # unique within sport, e.g. "player_box"
    sport: str
    category: str                               # key of CATEGORIES
    title: str
    source: str                                 # upstream provider as recorded by the archive
    recoverability: str
    map_datasets: tuple = ()                    # ids in research/input_research/market_input_map (dataset_input_edges)
    required_fields: tuple = ()                 # every one must be present (non-null) for COMPLETE
    min_records: int = 1                        # per game
    pregame: bool = False                       # only observations made before start count
    max_age_hours: Optional[float] = None       # pregame: newest pre-start observation older than this -> STALE
    rights_blocked: bool = False                # absence is by rights policy (rights registry), not a collector failure
    applies: Optional[Callable] = None          # Game -> bool; default: every FINAL game
    note: str = ""

    def applicable(self, g: Game) -> bool:
        if self.applies is not None:
            return bool(self.applies(g))
        return g.state == FINAL


@dataclass
class Observation:
    """What an adapter read back for one game x dataset.  `verified` means the records themselves were parsed and
    counted; a file listing or manifest count alone is verified=False and can never yield COMPLETE."""
    n_records: int = 0
    fields_present: frozenset = frozenset()     # required fields found non-null on (essentially) every record
    observed_at: Optional[datetime] = None      # newest capture timestamp usable for this game (pre-start if pregame)
    post_start_only: bool = False               # pregame dataset: observations exist but none precede the start
    verified: bool = True
    evidence: str = ""                          # archive path / ref the record was read from
    note: str = ""
