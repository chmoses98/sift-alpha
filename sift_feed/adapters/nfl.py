"""NFL operating forecast: the RUN NFL handicap packet's incumbent model view, branch
`handicap-reports:latest/packet.json` (nfl-edge-finder .github/workflows/run-nfl.yml, written by
scripts/handicap/build_report.py; the packet labels this view bucket A, "validated/production model
view"). model_version is the packet's own `sources.model_version` (e.g. "shadow-0.4.0"). The packet
declares `real_money_status` "NOT VALIDATED ..." and the view's caveat says it trails the market on game
outcomes, so it classifies as operating_unapproved; the declaration is carried verbatim.

NOT used: the packet's `shadow_v2`, `game_script_v2`, coherent-simulation and `market_implied*` blocks
(research or market-derived), and the `projection-data` branch.

Field map (games[].model_view): model_win_probability {team: p} (both sides published);
model_spread is the HOME spread (home favourite negative; checked against model_score below);
model_total; model_score {team: points} -> team_totals. projected_margin_home = -model_spread.
Contracts: markets with analysis bucket "A" (incumbent pricer) and a model_probability, full-game
GAME_WINNER / SPREAD / TOTAL / TEAM_TOTAL only (the incumbent prices no period contracts), so
period_projections is null.
"""
from .. import teams
from ..schema import contract, make_game
from . import artifact, ref_string

SPORT = "NFL"
MAX_AGE_HOURS = 48
SOURCES = {"prod": ("nfl-edge-finder", "handicap-reports")}
PATH = "latest/packet.json"
FAMILIES = ("GAME_WINNER", "SPREAD", "TOTAL", "TEAM_TOTAL")


def build(src, now):
    s = src["prod"]
    pk = s.read_json(PATH)
    art = artifact(s, PATH)
    mv_top = (pk.get("sources") or {}).get("model_version")
    decl = {"real_money_status": pk.get("real_money_status"), "sources.model_version": mv_top}
    games = []
    for g in pk.get("games", []):
        h, a = g["home_team"], g["away_team"]
        mv = g.get("model_view") or {}
        wp, score = mv.get("model_win_probability") or {}, mv.get("model_score") or {}
        spread = mv.get("model_spread")
        margin = None if spread is None else -float(spread)
        flags = []
        if margin is not None and h in score and a in score and abs(score[h] - score[a]) > 0.5 and (score[h] - score[a] > 0) != (margin > 0):
            flags.append("model_spread sign disagrees with model_score; margin withheld")
            margin = None
        cs = []
        for m in g.get("markets", []):
            an = m.get("analysis") or {}
            if (m.get("family") in FAMILIES and m.get("period") == "FULL" and an.get("bucket") == "A"
                    and m.get("model_probability") is not None):
                side = "home" if m.get("team") == h else "away" if m.get("team") == a else None
                cs.append(contract(m["ticker"], m["family"], m["period"], m["model_probability"], side=side,
                                   line=m.get("threshold")))
        games.append(make_game(
            sport=SPORT, game_id=g["game_id"], start_time=g["kickoff_utc"],
            home=teams.team(SPORT, h), away=teams.team(SPORT, a),
            model_version=mv.get("model_version") or mv_top, projected_at=pk["built_at"], source=ref_string(art),
            declaration={**decl, "model_view.model_version": mv.get("model_version"), "model_view.caveat": mv.get("caveat")},
            p_home=wp.get(h), p_away=wp.get(a), margin_home=margin, total=mv.get("model_total"),
            home_pts=score.get(h), away_pts=score.get(a), contracts=cs, flags=flags,
            derived=["projected_margin_home: -model_spread (the packet's home spread)"] if margin is not None else [],
            detail={"feature_cutoff": mv.get("feature_cutoff"), "caveat": mv.get("caveat"), "week": g.get("week")}))
    return {"artifact": art, "model_version": mv_top, "projected_at": pk["built_at"],
            "bet_authority": pk.get("real_money_status"), "authority_note": pk.get("real_money_status"), "declaration": decl, "games": games}
