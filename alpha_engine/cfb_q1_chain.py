"""Factor-level source-to-model trace for the reference family CFB/quarter_total (1st-quarter total).

Each FACTOR is a *candidate mechanism*, not a presumed predictor. It is mapped to registry input ids; a factor whose input is
not in the registry is recorded as REGISTRY_GAP (itself a finding), never silently dropped. Status/stage values come from
verification_engine (pure functions of committed evidence); predictive evidence comes only from the pinned ablation file.
"""
from __future__ import annotations

import json

from . import verification_engine as ve

FAMILY = "CFB/quarter_total"
# (group, factor, mechanism for a Q1 total, registry inputs ("" = none exists), exact point-in-time requirement)
FACTORS = [
 ("offense_defense", "Opponent-adjusted offensive efficiency (PPA/EPA, success rate)", "scoring rate per possession", ["cfb.off_ppa"], "season-to-date as of kickoff, opponent-adjusted, excluding the game itself"),
 ("offense_defense", "Opponent-adjusted defensive efficiency", "points allowed per possession", ["cfb.def_ppa"], "same"),
 ("offense_defense", "Composite ratings (SP+/FPI-style)", "prior on team strength", ["cfb.sp_plus"], "published before kickoff"),
 ("offense_defense", "Explosiveness / finishing drives", "TD vs FG vs punt conversion of drives", ["cfb.drives", "cfb.redzone"], "season-to-date"),
 ("offense_defense", "Run/pass tendency and script", "clock use and scoring variance", ["cfb.pass_rate", "cfb.script"], "season-to-date"),
 ("offense_defense", "Schemes and coaching (incl. tempo tendencies)", "opening-script and pace", ["cfb.coaching"], "coaching staff as of kickoff"),
 ("offense_defense", "Matchup-specific advantage (team vs team)", "interaction of offense and opposing defense", [], "no registry input exists for pairwise matchup features"),
 ("offense_defense", "Offensive/defensive line quality", "sustaining drives / pressure", ["cfb.ol"], "lineup as of kickoff"),
 ("offense_defense", "Quarterback performance", "efficiency of first drives", ["cfb.qb"], "season-to-date"),
 ("early_game", "Historical first-quarter scoring distribution", "base rate of Q1 points per team / opponent", ["cfb.q_scoring"], "only games final before kickoff (availability = game end; ESPN backfill has a single observed_at)"),
 ("early_game", "First-drive TD/FG/punt rates", "opening-drive outcomes dominate Q1", ["cfb.first_drive"], "lagged rate from earlier games only"),
 ("early_game", "Possessions, drives and plays per quarter", "number of scoring chances in Q1", ["cfb.drives"], "season-to-date"),
 ("early_game", "Tempo / no-huddle tendency", "plays per quarter", ["cfb.pace"], "season-to-date"),
 ("early_game", "Opening possession (toss / deferral)", "who has the ball first changes Q1 distribution", ["cfb.opening_poss"], "toss result is known only at kickoff: use deferral TENDENCY, never the realised toss"),
 ("personnel_env", "Confirmed starters and QB status", "QB change moves the whole line", ["cfb.depth_chart", "cfb.qb_status_pit"], "status visible before the quote; never final inactives"),
 ("personnel_env", "Injuries and roster changes", "availability", ["cfb.injuries", "cfb.transfer_roster"], "report vintage <= quote time"),
 ("personnel_env", "Weather and venue", "wind/precip/dome affect kicking and passing", ["cfb.weather_pit", "cfb.venue"], "forecast vintage visible before the quote; never realised weather"),
 ("personnel_env", "Rest and travel", "fatigue", ["cfb.rest_travel"], "schedule-derived"),
 ("personnel_env", "Kicker accuracy by distance / effective range", "FG vs punt/go decision and FG conversion", ["cfb.kicker"], "prior-season + season-to-date; distance buckets are NOT in the ESPN box score"),
 ("personnel_env", "Field position and FG decision tendencies", "converts drives into points", ["cfb.field_pos"], "season-to-date"),
 ("market", "Exact 1Q contract identity and settlement rules", "defines what is predicted (regulation Q1 combined points, strike, push)", ["m.rules_text"], "rules text versioned at capture"),
 ("market", "Pre-kickoff price history", "market-implied baseline and CLV", ["m.quote_history"], "timestamped quotes before kickoff"),
 ("market", "Line thresholds / ladder structure", "implied distribution over 0/3/7/10/14", ["m.ladder_structure"], "all rungs at the same instant"),
 ("market", "Historical settlement outcomes", "independent truth for evaluation", ["m.settlement_truth"], "settled value + timestamp"),
 ("market", "Historical strike hit rates", "calibration of ladder", ["m.strike_hit_rates"], "settled history"),
 ("market", "Market-implied probability", "baseline to beat", ["m.quote_history", "m.ladder_structure"], "derived from quotes; needs the two inputs above"),
]


def build(ctx=None):
    ctx = ctx or ve.build()
    f = ctx["fams"][FAMILY]
    linked = {r["input"]: r for r in f["inputs"]}
    ab = ctx["ablation"].get(FAMILY)
    factors, gaps = [], []
    for grp, name, mech, ids, pit in FACTORS:
        ins = []
        for i in ids:
            rec = ctx["inputs"].get(f"CFB:{i}")
            lk = linked.get(i)
            ins.append({"input": i, "linked_to_family": lk is not None, "tier": lk["tier"] if lk else None, "status": (lk or rec or {}).get("status", "UNKNOWN") if rec else "UNKNOWN",
                        "stages": rec["stages"] if rec else None, "first_failure": rec["first_failure"] if rec else {"stage": "source", "state": "UNKNOWN", "why": "not in registry"},
                        "evidence": rec["evidence"] if rec else [], "note": rec["note"] if rec else ""})
            if lk is None:
                gaps.append({"factor": name, "input": i, "defect": "input exists in registry but is NOT linked to CFB/quarter_total (market_specs driver missing)"})
        if not ids:
            gaps.append({"factor": name, "input": None, "defect": "no registry input exists for this factor"})
        st = [x["status"] for x in ins]
        factors.append({"group": grp, "factor": name, "mechanism": mech, "pit_requirement": pit, "inputs": ins,
                        "factor_status": "REGISTRY_GAP" if not ins else ("VALIDATED_PREDICTIVE" if "VALIDATED_PREDICTIVE" in st else "VERIFIED" if all(s == "VERIFIED" for s in st) else "PARTIAL" if any(s in ("VERIFIED", "COLLECTED_UNVERIFIED", "COLLECTED_UNUSED", "STALE") for s in st) else "NOT_AVAILABLE")})
    from collections import Counter
    return {"schema_version": "chain-1.0", "family": FAMILY, "period": "Q1", "markets_now": f["markets_now"], "projection": f["projection"], "family_stages": f["stages"],
            "ablation": ab, "factors": factors, "gaps": gaps, "factor_status_counts": dict(Counter(x["factor_status"] for x in factors)),
            "failure_stage_counts": dict(Counter((i["first_failure"] or {}).get("stage", "NONE") for x in factors for i in x["inputs"]))}
