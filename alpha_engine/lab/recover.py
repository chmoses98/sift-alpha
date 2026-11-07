"""Exact game / side recovery for archived Kalshi contracts whose horizon record has no game_id (RESEARCH_ONLY).

The tape-repair horizon files leave game_id/season/week/home/away/team null for ~3,700 settled 2025 contracts (Sep-Jan).  The event ticker encodes the kickoff date and both team codes
("KXNFLTOTAL-26JAN25LASEA-74": 2026-01-25, away LA @ home SEA), so the nflverse game is a unique (gameday, away+home) match.  The contract side is the team-code prefix of the
suffix token (GAME/SPREAD/TEAMTOTAL/player contracts).  Rules, all fail-closed:
  * only fields that are null in the record are filled; nothing existing is overwritten
  * exactly one game must match the date and the two-team code; otherwise the record is left untouched and counted
  * the side team must be one of the game's two teams (longest code first); otherwise `team` stays null
  * preseason events (no nflverse game) are never matched"""
from __future__ import annotations
import re
import pandas as pd

MON = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
EV = re.compile(r"^KXNFL[A-Z0-9]+-(\d\d)([A-Z]{3})(\d\d)([A-Z]+?)(TD\d+)?-(.*)$")
ALT = {"JAC": "JAX", "JAX": "JAC"}


def games_index(games: pd.DataFrame) -> dict:
    idx: dict = {}
    for r in games.itertuples():
        for a in {r.away_team, ALT.get(r.away_team, r.away_team)}:
            for h in {r.home_team, ALT.get(r.home_team, r.home_team)}:
                idx.setdefault((str(r.gameday), a + h), []).append(r)
    return idx


def recover(rec: dict, idx: dict) -> dict | None:
    m = EV.match(rec.get("ticker", ""))
    if not m:
        return None
    yy, mon, dd, teams, _, suffix = m.groups()
    if mon not in MON:
        return None
    hit = idx.get((f"20{yy}-{MON[mon]:02d}-{dd}", teams), [])
    if len({h.game_id for h in hit}) != 1:
        return None
    g = hit[0]
    out = {"game_id": g.game_id, "season": str(g.season), "week": int(g.week), "home_team": g.home_team, "away_team": g.away_team}
    for t in sorted((g.away_team, g.home_team), key=lambda x: -len(x)):
        if suffix.startswith(t) or suffix.startswith(ALT.get(t, t)):
            if not any(suffix.startswith(o) and len(o) > len(t) for o in (g.away_team, g.home_team) if o != t):
                out["team"] = t
                break
    return out


def fill(rec: dict, idx: dict) -> bool:
    """Fill null fields in-place.  Returns True if the record was recovered."""
    if rec.get("game_id") is not None:
        return False
    r = recover(rec, idx)
    if r is None:
        return False
    for k, v in r.items():
        if rec.get(k) is None:
            rec[k] = v
    rec["recovered_from_ticker"] = True
    return True
