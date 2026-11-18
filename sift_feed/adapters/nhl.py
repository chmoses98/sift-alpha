"""NHL production forecast: the primary model (`model_version`, DATA_ONLY_V1 at the time of writing)
of the main-branch `simulate` job, written to `data-archive:slates/latest/slate.json`
(NHL-edge-finder capture_worker.yml / conductor.yml). The slate simulates each game only inside its
pregame window (roughly 4h before puck drop), so between slates there may be no upcoming game.

NOT used: the slate's own `v2_shadow`, `oa_shadow`, `player_shadow` blocks (role SHADOW) and the
`projection-data` branch (pf-nhl, authority research_only).

Field map (slate.games[]): p_home_win / p_away_win (both published); exp_home_goals, exp_away_goals,
exp_total. Derivation: projected_margin_home = exp_home_goals - exp_away_goals (exact by linearity of
expectation; both are the simulation's own means). The slate publishes no per-period goal means, so
period_projections is null; regulation-tie / overtime / shootout probabilities are kept in `detail`.
Contract probabilities are `p_data_only` (null for unsupported families, which are dropped).
"""
from .. import teams
from ..schema import contract, make_game
from . import artifact, ref_string

SPORT = "NHL"
MAX_AGE_HOURS = 6
SOURCES = {"prod": ("NHL-edge-finder", "data-archive")}
PATH = "slates/latest/slate.json"
FAMILIES = ("game_winner", "game_spread", "game_total", "team_total", "period_winner", "period_spread", "period_total")


def build(src, now):
    s = src["prod"]
    slate = s.read_json(PATH)
    art = artifact(s, PATH)
    by_game = {}
    for c in slate.get("contracts", []):
        if c.get("family") in FAMILIES and c.get("p_data_only") is not None:
            by_game.setdefault(c["game_id"], []).append(
                contract(c["ticker"], c["family"], c.get("period"), c["p_data_only"], title=c.get("title"),
                         line=c.get("threshold")))
    games = []
    for g in slate.get("games", []):
        eh, ea = g.get("exp_home_goals"), g.get("exp_away_goals")
        margin = None if eh is None or ea is None else eh - ea
        flags = [] if g.get("inputs_trusted", True) else ["inputs_not_trusted: " + "; ".join(g.get("input_reasons") or [])]
        goalies = {side: (g.get(f"{side}_goalie") or {}).get("player_name") for side in ("home", "away")}
        games.append(make_game(
            sport=SPORT, game_id=g["game_id"], start_time=g["start_time_utc"],
            home=teams.team(SPORT, g["home"]), away=teams.team(SPORT, g["away"]),
            model_version=slate.get("model_version"), projected_at=slate["generated_at_utc"], source=ref_string(art),
            p_home=g.get("p_home_win"), p_away=g.get("p_away_win"), margin_home=margin, total=g.get("exp_total"),
            home_pts=eh, away_pts=ea, contracts=by_game.get(g["game_id"], []), flags=flags, digits=2,
            derived=["projected_margin_home: exp_home_goals - exp_away_goals"] if margin is not None else [],
            detail={"p_reg_tie": g.get("p_reg_tie"), "p_overtime": g.get("p_overtime"), "p_shootout": g.get("p_shootout"),
                    "margin_sd": g.get("margin_sd"), "total_sd": g.get("total_sd"), "goalies": goalies,
                    "horizon": g.get("horizon"), "sim_version": slate.get("sim_version")}))
    return {"artifact": art, "model_version": slate.get("model_version"), "projected_at": slate["generated_at_utc"],
            "bet_authority": slate.get("authority"), "authority_note": slate.get("authority_note"), "games": games}
