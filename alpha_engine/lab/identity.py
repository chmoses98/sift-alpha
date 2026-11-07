"""Season-specific player identity resolution for Kalshi player-prop contracts (RESEARCH_ONLY, never guesses).

Every contract is assigned exactly one reason:
  RESOLVED_SEASON_TEAM   exactly one player of that normalised name appeared for the contract team in the contract season (play-by-play rows)
  RESOLVED_ROSTER        no appearance yet, exactly one name match whose latest roster team is the contract team and last_season >= season
  NON_PLAYER_NO_TD       the "No Touchdown" outcome of an any-TD market (an event, not a person)
  NON_PLAYER_DEFENSE     a team defence/special-teams contract ("<City> D/ST")
  AMBIGUOUS              several name candidates remain after the team/season filters  (left unresolved)
  NO_NAME_MATCH          no player of that name in the identity table                  (left unresolved)
  TEAM_NOT_MATCHED       the name matches but never for this team in this season       (left unresolved)
The identity table is used only to attach an id to a contract; it never enters a feature.
"""
from __future__ import annotations
import re
import unicodedata
import pandas as pd
from . import player_lab as PL

DST = re.compile(r"(\bD/ST\b|\bDefense$|\bSpecial Teams$)", re.I)
# nicknames absent from every identity field.  An alias is only USED when the candidate it names actually appeared for the contract team in the contract season.
ALIASES = {"hollywood brown": "marquise brown"}


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    n = PL.norm_name(s)
    return ALIASES.get(n, n)
NO_TD = re.compile(r"^no touchdown$", re.I)
PLAYER_REASONS = ("RESOLVED_SEASON_TEAM", "RESOLVED_ROSTER")


def build_tables(players: pd.DataFrame, pg: pd.DataFrame):
    names = players.dropna(subset=["gsis_id", "display_name"]).copy()
    legal = names.dropna(subset=["first_name", "last_name"]).assign(display_name=lambda x: x["first_name"] + " " + x["last_name"])
    both = pd.concat([names, legal]).drop_duplicates(["gsis_id", "display_name"])
    both["nn"] = both["display_name"].map(norm)
    by_name = {nn: g.drop_duplicates("gsis_id")[["gsis_id", "latest_team", "last_season"]].to_dict("records") for nn, g in both.groupby("nn")}
    played = pg.groupby(["pid", "season"])["team"].agg(lambda s: set(s)).to_dict()
    return by_name, played


def resolve_one(player, team, season, by_name, played) -> tuple[str | None, str]:
    p = "" if player is None else str(player)
    if NO_TD.match(p.strip()):
        return None, "NON_PLAYER_NO_TD"
    if DST.search(p):
        return None, "NON_PLAYER_DEFENSE"
    cand = by_name.get(norm(p), [])
    if not cand:
        return None, "NO_NAME_MATCH"
    season = int(season)
    same = [c["gsis_id"] for c in cand if team in played.get((c["gsis_id"], season), set())]
    if len(same) == 1:
        return same[0], "RESOLVED_SEASON_TEAM"
    if len(same) > 1:
        return None, "AMBIGUOUS"
    # nobody of that name has appeared for the team that season: allow the roster table only if it is unambiguous and consistent
    ros = [c["gsis_id"] for c in cand if c.get("latest_team") == team and (pd.isna(c.get("last_season")) or c["last_season"] >= season) and not played.get((c["gsis_id"], season))]
    if len(ros) == 1 and len(cand) == 1:
        return ros[0], "RESOLVED_ROSTER"
    return None, "AMBIGUOUS" if len(cand) > 1 else "TEAM_NOT_MATCHED"


def resolve(contracts: pd.DataFrame, players: pd.DataFrame, pg: pd.DataFrame, season_col: str = "season") -> pd.DataFrame:
    by_name, played = build_tables(players, pg)
    key = contracts[["player", "team"]].copy()
    key["season"] = contracts[season_col] if season_col in contracts else 2025
    uniq = key.drop_duplicates()
    m = {}
    for r in uniq.itertuples(index=False):
        m[(r.player, r.team, r.season)] = resolve_one(r.player, r.team, r.season, by_name, played)
    out = contracts.copy()
    res = [m[(a, b, c)] for a, b, c in zip(key["player"], key["team"], key["season"])]
    out["pid"] = [x[0] for x in res]
    out["id_reason"] = [x[1] for x in res]
    return out


def report(resolved: pd.DataFrame) -> dict:
    return {"contracts": int(len(resolved)), "by_reason": {k: int(v) for k, v in resolved["id_reason"].value_counts().items()},
            "player_contracts": int((~resolved["id_reason"].str.startswith("NON_PLAYER")).sum()),
            "player_resolved": int(resolved["pid"].notna().sum())}
