"""NBA operating forecast (source_class follows the artifact's own declaration).
Source: the `nba simulate` slate (model nba-sim-*) that the main-branch capture
worker writes to `data-archive:slates/latest/slate.json` (nba-edge-finder .github/workflows/
capture_worker.yml / conductor.yml -> `nba simulate --out data/archive`).

NOT used: `projection-data` (projection-foundation pf-nba, self-declared `authority: research_only`,
"LIVE shadow operation ... nothing here is read by production").

Field map (slate.games[]): p_home_win -> win_probability.home; margin_mean (HOME minus AWAY, per the
slate's own note) -> projected_margin_home; total_mean; home_pts_mean / away_pts_mean -> team_totals.
inputs_trusted=false is surfaced as a flag with the slate's own reasons. Contract probabilities are the
slate's `p_data_only` (the simulation's own probability) for game/period winner, spread, total and team
total contracts. Period projections: only the period-winner probabilities the slate prices (those same
contracts; side read from the Kalshi ticker suffix, which is the team tricode); the slate has no
per-period score means, so nothing else is reported. A tie in a period is possible, so home+away < 1.
"""
from .. import teams
from ..schema import contract, make_game
from . import artifact, ref_string

SPORT = "NBA"
MAX_AGE_HOURS = 12
SOURCES = {"prod": ("nba-edge-finder", "data-archive")}
PATH = "slates/latest/slate.json"
FAMILIES = ("game_winner", "game_spread", "game_total", "team_total", "period_winner")


def build(src, now):
    s = src["prod"]
    slate = s.read_json(PATH)
    art = artifact(s, PATH)
    decl = {"authority_note": slate.get("authority_note")}
    by_game = {}
    for c in slate.get("contracts", []):
        if c.get("family") in FAMILIES and c.get("p_data_only") is not None:
            by_game.setdefault(c["game_id"], []).append(
                contract(c["ticker"], c["family"], c.get("period"), c["p_data_only"], title=c.get("title"),
                         line=c.get("threshold")))
    games = []
    for g in slate.get("games", []):
        home, away = teams.team(SPORT, g["home"]), teams.team(SPORT, g["away"])
        cs = by_game.get(g["game_id"], [])
        periods = {}
        for c in cs:
            suffix = c["ticker"].rsplit("-", 1)[-1].rstrip("0123456789")  # "CLE", "CLE10" (spread rung)
            c["side"] = "home" if suffix == g["home"] else "away" if suffix == g["away"] else None
            if c["family"] == "period_winner" and c["side"]:
                periods.setdefault(c["period"], {})[f"{c['side']}_win_prob"] = round(c["p_model"], 3)
        flags = [] if g.get("inputs_trusted", True) else ["inputs_not_trusted: " + "; ".join(g.get("input_reasons") or [])]
        games.append(make_game(
            sport=SPORT, game_id=g["game_id"], start_time=g["tip_utc"], home=home, away=away,
            model_version=slate.get("model_version"), projected_at=slate["generated_at_utc"], source=ref_string(art),
            declaration=decl, p_home=g.get("p_home_win"), margin_home=g.get("margin_mean"), total=g.get("total_mean"),
            home_pts=g.get("home_pts_mean"), away_pts=g.get("away_pts_mean"),
            period_projections=periods or None, contracts=cs, flags=flags,
            detail={"margin_sd": g.get("margin_sd"), "total_sd": g.get("total_sd"), "ot_rate": g.get("ot_rate"),
                    "n_sims": g.get("n_sims"), "model_spread_label": g.get("spread_label")}))
    return {"artifact": art, "model_version": slate.get("model_version"), "projected_at": slate["generated_at_utc"],
            "bet_authority": "RESEARCH (no betting authority)", "authority_note": slate.get("authority_note"),
            "declaration": decl, "games": games}
