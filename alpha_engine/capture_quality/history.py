"""Status-change history builder (goalie / starter / injury observations).

Sources such as ESPN 'reported' give only the newest update, and an append-only archive of snapshots is hard to read for
'when did the confirmed goalie change'. These pure helpers turn a time-ordered list of observations into explicit events.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

RANK = {"UNKNOWN": 0, "PROJECTED": 1, "PROBABLE": 2, "CONFIRMED": 3}


def _key(r: Mapping[str, Any]) -> tuple:
    return (str(r.get("game_id")), str(r.get("team_id")))


def diff_status_snapshots(prev: Iterable[Mapping[str, Any]], cur: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Events between two snapshots (one row per game/team). Types: FIRST_SEEN, STATUS_UPGRADE, STATUS_DOWNGRADE, PLAYER_CHANGE, DISAPPEARED."""
    p = {_key(r): r for r in prev}
    c = {_key(r): r for r in cur}
    ev: list[dict[str, Any]] = []
    for k, r in c.items():
        o = p.get(k)
        base = {"game_id": k[0], "team_id": k[1], "at": r.get("observed_at_utc")}
        if o is None:
            ev.append({**base, "type": "FIRST_SEEN", "player": r.get("player_name"), "status": r.get("status")})
            continue
        if o.get("player_name") != r.get("player_name"):
            ev.append({**base, "type": "PLAYER_CHANGE", "from_player": o.get("player_name"), "to_player": r.get("player_name"),
                       "from_status": o.get("status"), "to_status": r.get("status")})
        elif o.get("status") != r.get("status"):
            d = RANK.get(str(r.get("status")), 0) - RANK.get(str(o.get("status")), 0)
            ev.append({**base, "type": "STATUS_UPGRADE" if d > 0 else "STATUS_DOWNGRADE", "player": r.get("player_name"),
                       "from_status": o.get("status"), "to_status": r.get("status")})
    for k, o in p.items():
        if k not in c:
            ev.append({"game_id": k[0], "team_id": k[1], "at": None, "type": "DISAPPEARED", "player": o.get("player_name")})
    return ev


def build_status_history(observations: Iterable[Mapping[str, Any]]) -> dict[tuple, dict[str, Any]]:
    """Group observations by (game_id, team_id), sort by observed_at_utc, and emit change events plus the gap to the last observation."""
    groups: dict[tuple, list[Mapping[str, Any]]] = defaultdict(list)
    for r in observations:
        groups[_key(r)].append(r)
    out: dict[tuple, dict[str, Any]] = {}
    for k, rows in groups.items():
        rows = sorted(rows, key=lambda r: str(r.get("observed_at_utc")))
        events: list[dict[str, Any]] = []
        prev: Mapping[str, Any] | None = None
        for r in rows:
            events.extend(diff_status_snapshots([prev] if prev else [], [r]))
            prev = r
        out[k] = {"n_observations": len(rows), "first": rows[0].get("observed_at_utc"), "last": rows[-1].get("observed_at_utc"),
                  "final_player": rows[-1].get("player_name"), "final_status": rows[-1].get("status"),
                  "events": events, "changed_after_first": any(e["type"] != "FIRST_SEEN" for e in events)}
    return out
