"""Market-specific input specs: maps every inventoried market family onto one or more market-class specs
(market_specs_data.SPEC), validates every driver against the input catalog, and joins each driver to its
evidence-based collection status so the dashboard can say, per family, which essential inputs we actually hold.

Spec status is about the *blueprint only*:
  SPECIFIED             - mapped to complete class spec(s); family has observed markets
  SPECIFIED_UNOBSERVED  - spec exists but no markets were observed in the audited snapshot (do not over-read)
  UNSPECIFIED           - no truthful spec possible yet (unclassified / unmapped series); named, not hidden
  OUT_OF_SCOPE          - not a sports-outcome market for this sport
A spec is NOT evidence of collection, model use, or predictive value.
Usage: python -m alpha_engine.market_specs
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .input_catalog import INPUTS, COMMON, COMMON_BP
from .market_specs_data import SPEC
from . import unresolved_families as uf

AUDIT = Path(__file__).resolve().parent.parent / "research" / "audit"
SPORT_GROUP = {"NFL": "fb", "CFB": "fb", "NBA": "bb", "CBB": "bb", "NHL": "hk", "MLB": "bs", "SOCCER": "sc", "TENNIS": "tn"}
FIELDS = ("outcome", "distribution", "key_numbers", "settle", "pit", "history")


def _map(sport, spec, names):
    return {f"{sport}/{n}": ([spec] if isinstance(spec, str) else list(spec)) for n in names.split()}


M = {}
for _s, _spec, _names in [
 # NFL
 ("NFL", "fb_side", "GAME_WINNER"), ("NFL", ["fb_side", "fb_half_side", "fb_quarter_side"], "SPREAD"),
 ("NFL", ["fb_total", "fb_half_total", "fb_quarter_total"], "TOTAL"), ("NFL", ["fb_team_total", "fb_half_total"], "TEAM_TOTAL"),
 ("NFL", ["fb_half_side", "fb_quarter_side"], "PERIOD_WINNER HALF_FULL_RESULT"), ("NFL", "fb_margin_bucket", "WIN_MARGIN_BUCKET"),
 ("NFL", "fb_btts", "BOTH_TEAMS_SCORE BOTH_TEAMS_SCORE_N"), ("NFL", "fb_td_scorer", "FIRST_TD_SCORER NEXT_TD_SCORER"),
 ("NFL", "fb_first_event", "FIRST_TD_TEAM FIRST_TD_TIME RACE_TO_N"),
 ("NFL", ["fb_player_pass", "fb_player_rush", "fb_player_rec", "fb_player_other"], "PLAYER_STAT"), ("NFL", "fb_player_other", "PLAYER_H2H"),
 ("NFL", "fb_game_event", "GAME_EVENT GAME_STAT TEAM_STAT TOTAL_TD PERIOD_TD"), ("NFL", "fb_availability", "PLAYER_AVAILABILITY PLAYER_ROLE_EVENT"),
 ("NFL", ["fb_side", "fb_total"], "COMBO PARLAY"),
 ("NFL", "fb_futures_team", "CONFERENCE_WINNER DIVISION_WINNER MAKE_PLAYOFFS SEASON_DIVISION_ORDER SEASON_DIVISION_STAT SEASON_SEED SEASON_TEAM_H2H SEASON_WINS SEASON_WINS_EXACT SUPER_BOWL_MATCHUP SUPER_BOWL_WINNER TEAM_WINS_BY_WEEK SEASON_TEAM_EVENT"),
 ("NFL", "fb_futures_player", "AWARD SEASON_FANTASY SEASON_LEADER SEASON_MATCHUP SEASON_PLAYER_SPECIAL SEASON_PLAYER_STAT SEASON_SPECIAL SEASON_TEAM_LEADER WEEK_LEADER"),
 ("NFL", "fb_news_event", "COACH_EVENT DRAFT SUPER_BOWL_EVENT TRANSACTION_EVENT WEEK_EVENT"),
 # CFB
 ("CFB", "fb_half_side", "first_half_moneyline first_half_spread second_half_moneyline second_half_spread"), ("CFB", ["fb_team_total", "fb_half_total"], "first_half_team_total"),
 ("CFB", "fb_half_total", "first_half_total second_half_total"), ("CFB", "fb_side", "game_moneyline game_spread"), ("CFB", "fb_total", "game_total"),
 ("CFB", "fb_game_event", "game_stat_prop team_stat_prop"), ("CFB", "fb_overtime", "overtime"), ("CFB", "fb_quarter_side", "quarter_moneyline quarter_spread"),
 ("CFB", "fb_quarter_total", "quarter_total"), ("CFB", "fb_team_total", "team_total"), ("CFB", "fb_td_scorer", "touchdown_scorer"), ("CFB", "fb_futures_team", "season_level_events"),
 # NBA
 ("NBA", "bb_side", "game_winner game_spread summer_league_game summer_league_spread"), ("NBA", "bb_total", "game_total summer_league_total h2h_team_stat"),
 ("NBA", "bb_team_total", "team_total team_bench_points"), ("NBA", "bb_period_side", "period_winner period_spread"), ("NBA", "bb_period_total", "period_total"),
 ("NBA", ["bb_team_total", "bb_period_total"], "period_team_total"), ("NBA", "bb_margin_bucket", "game_win_margin"), ("NBA", "bb_overtime", "game_overtime"),
 ("NBA", "bb_first_event", "game_points_leader game_race_to first_basket"), ("NBA", ["bb_side", "bb_total"], "parlay_combo"),
 ("NBA", "bb_player_pts", "player_points summer_league_player"), ("NBA", "bb_player_reb", "player_rebounds"), ("NBA", "bb_player_ast", "player_assists"),
 ("NBA", "bb_player_threes", "player_threes"), ("NBA", "bb_player_def", "player_steals player_blocks player_turnovers player_stocks"),
 ("NBA", "bb_player_combo", "player_pra player_free_throws player_pr player_pa player_ra player_double_double player_triple_double h2h_player_stat"),
 ("NBA", "bb_lineup", "starting_lineup"),
 ("NBA", "bb_futures_team", "season_champion champion_special conference_champion playoff_round_reach division_winner season_wins season_record playoffs_qualify playoff_seed nba_cup series_winner series_props summer_league_season"),
 ("NBA", "bb_futures_player", "series_player_stat season_stat_leader season_player_streak season_specials awards all_nba_selections draft"),
 ("NBA", "bb_news_event", "all_star_events transactions coaching franchise_business schedule_announcement non_basketball_or_offcourt"),
 # CBB
 ("CBB", "bb_futures_team", "FUTURES_CHAMPION FUTURES_CONFERENCE FUTURES_OTHER FUTURES_SEED"), ("CBB", "bb_side", "GAME_WINNER SPREAD"),
 ("CBB", ["bb_period_side", "bb_period_total"], "HALF"), ("CBB", ["bb_player_pts", "bb_player_reb", "bb_player_ast", "bb_player_threes"], "PLAYER_PROP"),
 ("CBB", "bb_team_total", "TEAM_TOTAL"), ("CBB", "bb_total", "TOTAL"),
 # NHL
 ("NHL", "hk_side", "game_winner game_regulation_winner game_spread"), ("NHL", "hk_total", "game_total"), ("NHL", "hk_team_total", "team_total"),
 ("NHL", "hk_margin", "game_win_margin"), ("NHL", "hk_ot_so", "game_overtime game_shootout game_multi_overtime"), ("NHL", "hk_btts", "game_both_teams_score period_btts"),
 ("NHL", "hk_period", "period_winner period_total period_spread"), ("NHL", "hk_first_event", "first_goal game_early_goal"),
 ("NHL", "hk_player_goals", "player_goals player_points player_assists"), ("NHL", "hk_player_shots", "player_shots"), ("NHL", "hk_goalie_saves", "goalie_saves"),
 ("NHL", "hk_h2h", "player_h2h"), ("NHL", ["hk_side", "hk_total"], "parlay_combo"), ("NHL", "hk_futures", "season_champion playoff_series season_player_stats season_awards"),
 ("NHL", "hk_news_event", "non_hockey_or_office"),
 # MLB
 ("MLB", "bs_side", "game_result game_spread other_league_game_result"), ("MLB", "bs_total", "game_total"), ("MLB", "bs_team_total", "team_total"),
 ("MLB", ["bs_inning_result", "bs_f3"], "inning_result"), ("MLB", "bs_f5", "inning_total first5_spread first5_total"), ("MLB", "bs_first_inning", "first_inning_runs"),
 ("MLB", "bs_margin", "winning_margin"), ("MLB", "bs_extras", "extra_innings"), ("MLB", "bs_delay", "game_delay"),
 ("MLB", "bs_hitter_hits", "hitter_hits hitter_hits_runs_rbis"), ("MLB", "bs_hitter_tb_rbi", "hitter_rbis hitter_stolen_bases hitter_total_bases"),
 ("MLB", "bs_hitter_hr", "hitter_home_runs"), ("MLB", "bs_pitcher_k", "pitcher_strikeouts"), ("MLB", "bs_pitcher_other", "pitcher_outs pitcher_earned_runs pitcher_hits_allowed pitcher_walks_allowed"),
 ("MLB", "bs_participation", "player_participation"),
 ("MLB", "bs_futures", "awards division_winner postseason_futures postseason_series season_leaders season_player_stat season_specials team_season_records team_season_wins"),
 ("MLB", "bs_news_event", "announcer_mentions business_other coaching transactions"),
 # SOCCER
 ("SOCCER", "sc_1x2", "match_result_3way"), ("SOCCER", "sc_2way", "match_winner_2way"), ("SOCCER", "sc_total", "total_goals"), ("SOCCER", "sc_exact_score", "exact_score"),
 ("SOCCER", "sc_handicap", "handicap"), ("SOCCER", "sc_team_total", "team_total"), ("SOCCER", "sc_btts", "btts"),
 ("SOCCER", "sc_half", "first_half_result first_half_total first_half_handicap first_half_btts second_half_result"), ("SOCCER", ["sc_half", "sc_exact_score"], "first_half_exact_score"),
 ("SOCCER", "sc_first_event", "first_to_score"),
 ("SOCCER", "sc_futures_team", "competition_winner competition_team_points competition_top_n competition_qualification competition_last_place competition_relegation competition_trophies competition_points_margin competition_promotion competition_head_to_head competition_outright tournament_advancement"),
 ("SOCCER", "sc_futures_player", "player_season_leader season_player_total player_award"), ("SOCCER", "sc_news_event", "soccer_special competition_host"),
 # TENNIS
 ("TENNIS", "tn_match_winner", "MATCH_WINNER"), ("TENNIS", "tn_set", "ANY_SET_WINNER EXACT_SET_SCORE SET_SPREAD SET_SWEEP SET_WINNER"), ("TENNIS", "tn_game_spread", "GAME_SPREAD"),
 ("TENNIS", "tn_total_games", "TOTAL_GAMES TOTAL_SETS"), ("TENNIS", "tn_tiebreak", "TIEBREAK_OCCURS"), ("TENNIS", "tn_aces", "PLAYER_ACES"), ("TENNIS", "tn_inplay", "GAME_WINNER_INPLAY"),
 ("TENNIS", "tn_futures", "COMBO_TOURNAMENT_WINNERS NATIONALITY_STAGE_COUNT NATIONALITY_WINNER ROUND_ADVANCE ROUND_OF_ELIMINATION SEASON_MAJORS SEASON_QUALIFICATION SEASON_RANKING TEAM_ADVANCE TEAM_COMPETITION_WINNER TOURNAMENT_WINNER"),
 ("TENNIS", "tn_news_event", "CAREER_OR_NOVELTY PLAYER_PARTICIPATION"),
]:
    M.update(_map(_s, _spec, _names))

UNSPECIFIED = {  # honest: named, with the reason a truthful spec cannot be written yet
 "NFL/NFL_MISC_UNCLASSIFIED": "380 open markets across 47 series not yet classified; classify series before specifying",
 "NBA/UNMAPPED_SERIES": "27 series (2,293 markets) not yet mapped to a family",
 "CBB/OTHER": "8 series unclassified in coarse snapshot", "NHL/UNMAPPED_SERIES": "2 series unmapped (45 markets)",
 "MLB/unknown": "7 series with unknown semantics (37 markets)",
}
OUT_OF_SCOPE = {"MLB/non_baseball": "not a baseball-outcome market", "MLB/non_baseball_esports": "esports, not baseball",
                "MLB/SWEPT_EMPTY_SERIES": "71 swept series returned zero markets (nothing to specify)", "TENNIS/NOT_TENNIS": "not a tennis-outcome market"}
ANTICIPATED = {  # classes the user named / sport norms imply; NOT observed in audited Kalshi snapshots
 "sc_cards": "soccer cards/bookings: NO series with card/booking/yellow in its title among the 4,081 live Sports series (2026-11-03), so likely not offered"}


def parse_driver(s):
    return {t.rsplit(":", 1)[0]: t.rsplit(":", 1)[1] for t in s.split()}


def validate():
    errs = []
    ids = {sp: {l.split("|")[0] for l in INPUTS[sp].splitlines()} | {l.split("|")[0] for l in COMMON.splitlines()} for sp in INPUTS}
    group_sports = defaultdict(list)
    for sp, g in SPORT_GROUP.items():
        group_sports[g].append(sp)
    for key, sp in SPEC.items():
        for f in FIELDS:
            if not str(sp.get(f, "")).strip():
                errs.append(f"{key}: empty {f}")
        if not sp["drivers"]:
            errs.append(f"{key}: no drivers")
        g = key.split("_")[0]
        for sport, d in sp["drivers"].items():
            if sport not in SPORT_GROUP or SPORT_GROUP[sport] != g:
                errs.append(f"{key}: driver sport {sport} not in group {g}")
                continue
            dr = parse_driver(d)
            if not any(t == "E" for t in dr.values()):
                errs.append(f"{key}/{sport}: no ESSENTIAL driver")
            for i, t in dr.items():
                if i not in ids[sport]:
                    errs.append(f"{key}/{sport}: unknown input {i}")
                if t not in "ECX":
                    errs.append(f"{key}/{sport}: bad tier {t} on {i}")
    for fid, specs in M.items():
        sport = fid.split("/")[0]
        for s in specs:
            if s not in SPEC:
                errs.append(f"{fid}: unknown spec {s}")
            elif sport not in SPEC[s]["drivers"]:
                errs.append(f"{fid}: spec {s} has no drivers for {sport}")
    return errs


def build():
    errs = validate()
    if errs:
        raise SystemExit("spec validation failed:\n" + "\n".join(errs))
    master = json.loads((AUDIT / "master_inventory.json").read_text())
    cs = json.loads((AUDIT / "collection_status.json").read_text())["sports"]
    fams, unmapped = {}, []
    inv = {sp: json.loads((AUDIT / "inventory" / f"{sp}.json").read_text()) for sp in ("NFL", "NBA", "CBB", "NHL", "MLB")}
    res_all = uf.build(inv)
    (AUDIT / "resolutions" / "unresolved_families.json").write_text(json.dumps(res_all, indent=1))
    for f in master["families"]:
        fid, sp = f["id"], f["sport"]
        now = (f["observed"].get("markets_now") or 0)
        row = {"sport": sp, "native_family": f["native_family"], "markets_now": f["observed"].get("markets_now")}
        if fid in OUT_OF_SCOPE:
            row.update(status="OUT_OF_SCOPE", reason=OUT_OF_SCOPE[fid], specs=[])
        elif fid in uf.FAMILY_STATUS:   # resolved by series split / mismapping (see resolutions/unresolved_families.json)
            res = res_all["families"][fid]
            row.update(status=uf.FAMILY_STATUS[fid], specs=res["classes"], reason=(
                "all %d series routed: %s; %d series TITLE_ONLY (provisional: %s)" % (res["n_series"], ", ".join(res["classes"]) or "none (mis-filed/out of scope)", res["series_title_only"], res["missing_evidence"])
                if res["series_title_only"] else "all %d series routed to %s from archived rules text" % (res["n_series"], ", ".join(res["classes"]))))
            if fid != "MLB/unknown":
                drivers = {}
                for s in res["classes"]:
                    for i, t in parse_driver(SPEC[s]["drivers"][sp]).items():
                        if i not in drivers or "XCE".index(t) > "XCE".index(drivers[i]):
                            drivers[i] = t
                ess = [i for i, t in drivers.items() if t == "E"]
                vc = Counter(cs[sp]["inputs"][i]["verification_class"] for i in ess)
                row.update(drivers=drivers, essential_total=len(ess), essential_by_status=dict(vc), essential_verified=vc.get("VERIFIED_COLLECTION", 0) + vc.get("DERIVED", 0),
                           essential_missing=sorted(i for i in ess if cs[sp]["inputs"][i]["verification_class"] in ("MISSING", "UNKNOWN", "CODE_REFERENCE_ONLY")))
        elif fid in M:
            drivers = {}
            for s in M[fid]:
                for i, t in parse_driver(SPEC[s]["drivers"][sp]).items():
                    if i not in drivers or "XCE".index(t) > "XCE".index(drivers[i]):
                        drivers[i] = t
            for tok in COMMON_BP.split():
                i, t = tok.rsplit(":", 1)
                if t == "E":
                    drivers.setdefault(i, "E")
            ess = [i for i, t in drivers.items() if t == "E"]
            vc = Counter(cs[sp]["inputs"][i]["verification_class"] for i in ess)
            row.update(status="SPECIFIED" if (f["observed"].get("markets_now") or f.get("series_count")) else "SPECIFIED_UNOBSERVED", specs=M[fid], drivers=drivers,
                       essential_total=len(ess), essential_by_status=dict(vc),
                       essential_verified=vc.get("VERIFIED_COLLECTION", 0) + vc.get("DERIVED", 0),
                       essential_missing=sorted(i for i in ess if cs[sp]["inputs"][i]["verification_class"] in ("MISSING", "UNKNOWN", "CODE_REFERENCE_ONLY")))
        else:
            unmapped.append(fid)
            row.update(status="UNSPECIFIED", reason="no mapping in market_specs.M", specs=[])
        fams[fid] = row
    for fid, a in res_all["added_families"].items():   # families the master inventory omitted (additive overlay)
        sp = a["sport"]; drivers = {}
        for s in a["specs"]:
            for i, t in parse_driver(SPEC[s]["drivers"][sp]).items():
                if i not in drivers or "XCE".index(t) > "XCE".index(drivers[i]): drivers[i] = t
        ess = [i for i, t in drivers.items() if t == "E"]; vc = Counter(cs[sp]["inputs"][i]["verification_class"] for i in ess)
        fams[fid] = {"sport": sp, "native_family": a["native_family"], "markets_now": a["markets_observed"], "status": a.get("status", "SPECIFIED"), "specs": a["specs"], "drivers": drivers, "added_by_overlay": True, "reason": a["note"],
                     "essential_total": len(ess), "essential_by_status": dict(vc), "essential_verified": vc.get("VERIFIED_COLLECTION", 0) + vc.get("DERIVED", 0),
                     "essential_missing": sorted(i for i in ess if cs[sp]["inputs"][i]["verification_class"] in ("MISSING", "UNKNOWN", "CODE_REFERENCE_ONLY"))}
    if unmapped:
        raise SystemExit(f"families without any mapping/decision: {unmapped}")
    summary = {}
    for sp in SPORT_GROUP:
        c = Counter(r["status"] for r in fams.values() if r["sport"] == sp)
        summary[sp] = dict(c, families=sum(c.values()), classes=sorted({s for r in fams.values() if r["sport"] == sp for s in r["specs"]}))
    out = {"schema_version": "specs-1.0", "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "note": "Blueprints are research requirements, not evidence of collection, model use or predictive value.",
           "classes": {k: {**{f: v[f] for f in FIELDS}, "drivers": {sp: parse_driver(d) for sp, d in v["drivers"].items()}} for k, v in SPEC.items()},
           "anticipated_unobserved": ANTICIPATED, "families": fams, "summary": summary}
    (AUDIT / "market_specs.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    o = build()
    for sp, s in o["summary"].items():
        print(sp, {k: v for k, v in s.items() if k != "classes"}, len(s["classes"]), "classes")
