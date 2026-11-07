"""Catalog-driven coverage report for NFL (RESEARCH_ONLY).  Joins three things that were previously reported separately:
  1  #53's catalog/availability (per archetype: which candidate inputs exist, are free, are pregame-knowable, have a PIT archive)
  2  what the laboratory actually computes today (LAB_IMPLEMENTS: catalog id -> lab realisation) and how complete those columns are per season (measured, roof-aware for weather)
  3  usable market data per modelled family and season from the recovered Kalshi archive: settled contracts, two-sided T-6h quotes, fresh (<=15 min) quotes
Gaps become repair cases (id, priority, evidence, action) in the shape alpha_engine.repair_queue.choose_next consumes.  Nothing here fabricates or substitutes an input."""
from __future__ import annotations
import glob, json
from collections import Counter, defaultdict
from pathlib import Path
import pandas as pd

LAB_IMPLEMENTS = {
    "nfl.off_epa": "game_lab strength: epa_pass/epa_rush (opponent-adjusted, rolling)", "nfl.def_epa": "game_lab strength (defence side of the same ratings)", "nfl.success_rate": "game_lab strength: sr",
    "nfl.pass_efficiency": "game_lab strength: epa_pass", "nfl.rush_efficiency": "game_lab strength: epa_rush", "nfl.explosive": "game_lab explosive", "nfl.pace": "game_lab tempo: sec_play, plays",
    "nfl.proe": "game_lab tempo: pass_oe, neutral_pass", "nfl.turnovers": "game_lab efficiency_luck: to_rate", "nfl.penalties": "game_lab efficiency_luck: pen_rate", "nfl.ratings": "game_lab rating grid",
    "nfl.redzone": "game_lab efficiency_luck: score_drive, third_conv (proxy)", "nfl.qb": "game_lab qb (realised starter: PARTIAL)", "nfl.qb_efficiency": "game_lab qb: diff_qb_epa (PARTIAL)",
    "nfl.injuries_pit": "game_lab injuries / player_lab inj status (report timestamp < kickoff; pre-2016 timestamps absent)", "nfl.skill_avail": "game_lab inj_*_skill", "nfl.ol": "game_lab inj_*_ol",
    "nfl.rest_travel": "game_lab schedule: rest_diff, short_week_any", "nfl.divisional_familiarity": "game_lab schedule: div_flag", "nfl.venue": "game_lab environment: dome", "nfl.weather_pit": "game_lab environment: OBSERVED game-time weather (not a forecast; PARTIAL)",
    "nfl.pass_rush": "game_lab protection: sack_rate, qbhit_rate", "nfl.pressure_qb": "game_lab protection", "nfl.targets": "player_lab usage EWMA: tgt, tgt_share", "nfl.carries": "player_lab usage EWMA: car, car_share",
    "nfl.air_yards_adot": "player_lab usage: air", "nfl.snaps": "involvement model (appearance history; snap counts not used)", "nfl.script": "player_lab game_ctx: predicted margin/total/team points from the game lab (never prices)",
}
FAMILY_MAP = {"moneyline": "NFL/GAME_WINNER", "spread": "NFL/SPREAD", "total": "NFL/TOTAL", "team_total": "NFL/TEAM_TOTAL", "rec_yds": "NFL/PLAYER_STAT", "receptions": "NFL/PLAYER_STAT",
              "rush_yds": "NFL/PLAYER_STAT", "pass_yds": "NFL/PLAYER_STAT", "td_any": "NFL/PLAYER_STAT"}
GAPS = ("NOT_IN_REGISTRY", "NO_REFERENCE_FOUND", "SOURCE_AVAILABLE_NOT_COLLECTED", "CODE_REFERENCE_ONLY")
KSTAT = {"receiving_yards": "rec_yds", "receptions": "receptions", "rushing_yards": "rush_yds", "passing_yards": "pass_yds", "touchdowns": "td_any"}
KFAM = {"GAME_WINNER": "moneyline", "SPREAD": "spread", "TOTAL": "total", "TEAM_TOTAL": "team_total"}


def archive_coverage(horizon_glob: str, horizon: str = "T-6h") -> dict:
    """family -> season -> {settled, quoted (two-sided book at the horizon), fresh15 (quote <=15 min old, spread<=10c)}."""
    out: dict = defaultdict(lambda: defaultdict(Counter))
    for p in sorted(glob.glob(horizon_glob)):
        for l in open(p):
            r = json.loads(l)
            if r.get("period") != "FULL" or r.get("result") not in ("yes", "no"):
                continue
            fam = KFAM.get(r["family"]) or (KSTAT.get(r.get("stat")) if r["family"] == "PLAYER_STAT" else None)
            if not fam:
                continue
            season = str(r.get("season") or str(r.get("game_id", ""))[:4] or "unknown")
            c = out[fam][season]
            c["settled"] += 1
            s = (r.get("snaps") or {}).get(horizon)
            if s and s.get("bid") is not None and s.get("ask") is not None and not s.get("book_empty") and s["ask"] > s["bid"]:
                c["quoted"] += 1
                if (s["ask"] - s["bid"]) <= 0.10 and float(s.get("age_min") or 0) <= 15:
                    c["fresh15"] += 1
    return {f: {s: dict(c) for s, c in v.items()} for f, v in out.items()}


def lab_column_coverage(gt: pd.DataFrame, groups: dict[str, list[str]]) -> dict:
    """Per feature group and season: mean non-null share of its columns over ALL games (weather columns are roof-aware: indoor games are not expected to have them)."""
    out = {}
    for g, cols in groups.items():
        cols = [c for c in gt.columns if any(m in c for m in cols)]
        if not cols:
            out[g] = {"status": "NO_COLUMNS"}
            continue
        out[g] = {int(s): round(float(x[cols].notna().mean().mean()), 4) for s, x in gt[gt["season"] >= 2010].groupby("season")}
    return out


def family_inputs(sport_doc: dict, families: list[str]) -> dict:
    inputs = sport_doc["inputs"]
    out = {}
    for fam in families:
        f = sport_doc["families"][fam]
        arch = sport_doc["archetypes"].get(f["archetype"] or "", None)
        rows = []
        for i in (arch["inputs"] if arch else []):
            a = inputs[i["id"]]["availability"]
            rows.append({"id": i["id"], "role": i["role"], "status": a["overall"], "pregame_knowable": a["pregame_knowable"], "free_source": a["free_sources"] != ["NONE_FOUND"],
                         "lab_realisation": LAB_IMPLEMENTS.get(i["id"])})
        tally = Counter(r["status"] for r in rows)
        out[fam] = {"archetype": f["archetype"], "markets_now": f["markets_now"], "inputs": len(rows), "status_tally": dict(tally), "lab_implemented": sum(1 for r in rows if r["lab_realisation"]),
                    "primary_not_implemented": [r["id"] for r in rows if r["role"] == "primary" and not r["lab_realisation"]], "gaps": [r for r in rows if r["status"] in GAPS and not r["lab_realisation"]]}
    return out


def repair_cases(fam_inputs: dict, archive: dict, gt_cov: dict, weather: dict) -> list[dict]:
    cases = []
    for fam, v in fam_inputs.items():
        for g in v["gaps"]:
            if g["role"] == "primary" and g["pregame_knowable"] in ("yes", "partial") and g["free_source"]:
                cases.append({"id": f"nfl:input:{g['id']}", "priority": 55 + (10 if g["status"] == "SOURCE_AVAILABLE_NOT_COLLECTED" else 0), "status": "PENDING", "family": fam,
                              "evidence": {"catalog_status": g["status"], "pregame_knowable": g["pregame_knowable"], "free_source": True, "archetype": v["archetype"]},
                              "action": "collect/derive from the catalogued free source with a point-in-time join and a coverage test"})
    seen, uniq = set(), []
    for c in sorted(cases, key=lambda c: -c["priority"]):
        if c["id"] not in seen:
            seen.add(c["id"]); uniq.append(c)
    thin = [(f, s, c.get("settled", 0)) for f, v in archive.items() for s, c in v.items() if s == "2025" and c.get("settled", 0) < 150]
    for f, s, n in thin:
        uniq.append({"id": f"nfl:market_data:{f}:{s}", "priority": 45, "status": "PENDING", "family": f, "evidence": {"settled_contracts": n, "season": s},
                     "action": "extend the recovered tape for this family; too few settled contracts for family-level conclusions"})
    for s, w in weather.items():
        if w.get("still_missing") and int(s) <= 2025:
            uniq.append({"id": f"nfl:weather_observed:{s}", "priority": 30, "status": "PENDING", "family": "game_total, team_total", "evidence": w,
                         "action": "outdoor games still lacking observed temp/wind after pbp-text fill; find a free observed-weather source"})
    uniq.append({"id": "nfl:weather_forecast_pit", "priority": 62, "status": "BLOCKED", "family": "game_total, player props",
                 "evidence": {"reason": "no free point-in-time forecast archive reachable: open-meteo historical-forecast host is not on the session network allowlist; model-reanalysis is not what was known pre-game"},
                 "action": "capture forecasts prospectively before kickoff (2026) and keep fcst_* separate from observed weather"})
    uniq.append({"id": "nfl:inactives_pit", "priority": 70, "status": "PENDING", "family": "player props", "evidence": {"catalog_status": "NOT_IN_REGISTRY", "why": "game-day inactive list ~90 min before kickoff would replace the P(involved) proxy"},
                 "action": "collect official inactives with publication timestamps prospectively (nflverse inactives are post-hoc and carry no timestamp)"})
    return sorted(uniq, key=lambda c: -c["priority"])
