"""CFB: the production pipeline publishes NO model projections. Its live execution index
(cfb-edge-finder `main:data/live/cfb_execution_index.json`, written by kalshi-market-catalog.yml /
cfb-execution-slate.yml) declares `contains_model_projections: false`; the app bundle's
model_prices is empty; the Script Engine's claims are SHADOW / uncalibrated descriptive bands.
So status is "unavailable" and there are no production games.

Research block (never production): the projection-foundation shadow `projection-data:
projections/cfb/latest.json` (model pf-cfb, authority research_only, role shadow). Only its per-team
mean points are copied as published; no spread, total or win probability is derived from them.
"""
from ..schema import RESEARCH, iso, parse_ts
from . import artifact, ref_string

SPORT = "CFB"
MAX_AGE_HOURS = 48
SOURCES = {"prod": ("cfb-edge-finder", "main"), "research": ("cfb-edge-finder", "projection-data")}
INDEX = "data/live/cfb_execution_index.json"
RESEARCH_PATH = "projections/cfb/latest.json"


def build(src, now):
    idx = src["prod"].read_json(INDEX)
    art = artifact(src["prod"], INDEX)
    out = {"artifact": art, "model_version": None, "projected_at": None, "bet_authority": None,
           "authority_note": None, "games": [], "source_class": RESEARCH,
           "declaration": {"contains_model_projections": idx.get("contains_model_projections")}}
    if idx.get("contains_model_projections") is False:
        out.update(status="unavailable", reason="CFB production pipeline publishes no model projections "
                   "(cfb_execution_index.contains_model_projections=false); see research block")
    else:
        out.update(status="unavailable", reason="CFB production index changed shape; adapter needs review")
    if "research" in src:
        out["research"] = research(src["research"], now)
    return out


def research(s, now):
    pf = s.read_json(RESEARCH_PATH)
    art = artifact(s, RESEARCH_PATH)
    model = pf.get("model") or {}
    rows = []
    for g in pf.get("games", []):
        st = parse_ts(g.get("start_utc"))
        if st is None or st <= now:
            continue
        pts = {t.get("team"): t.get("mean") for t in g.get("teams", []) if t.get("family") == "team_points"}
        rows.append({"sport": SPORT, "game_id": str(g["game_id"]), "start_time": iso(st),
                     "source_class": RESEARCH,
                     "source_declaration": {"model.authority": model.get("authority"), "model.role": model.get("role")},
                     "home": {"name": g.get("home"), "abbr": None}, "away": {"name": g.get("away"), "abbr": None},
                     "team_points_mean": {"home": pts.get(g.get("home")), "away": pts.get(g.get("away"))},
                     "model_version": model.get("version"),
                     "projected_at": iso(parse_ts(pf.get("generated_utc"))), "source": ref_string(art)})
    return rows
