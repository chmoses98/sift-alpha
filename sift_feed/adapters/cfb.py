"""CFB: the production pipeline publishes NO model projections. Its live execution index
(cfb-edge-finder `main:data/live/cfb_execution_index.json`, written by kalshi-market-catalog.yml /
cfb-execution-slate.yml) declares `contains_model_projections: false`; the app bundle's
model_prices is empty; the Script Engine's claims are SHADOW / uncalibrated descriptive bands.
So status is "unavailable" and there are no production games.

Research block (never production): the projection-foundation shadow `projection-data:
projections/cfb/latest.json` (model pf-cfb, authority research_only, role shadow). Only its per-team
mean points are copied as published; no spread, total or win probability is derived from them.
"""
from .. import promotion
from ..schema import RESEARCH, iso, make_game, parse_ts
from . import artifact, ref_string

SPORT = "CFB"
MAX_AGE_HOURS = 48
SOURCES = {"prod": ("cfb-edge-finder", "main"), "research": ("cfb-edge-finder", "projection-data")}
INDEX = "data/live/cfb_execution_index.json"
RESEARCH_PATH = "projections/cfb/latest.json"
OAE_KEY = "oae_challenger"
OAE_DECL_KEYS = ("status", "activated", "authority", "role", "operating_forecast")


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
        promo = promotion.promoted(SPORT)
        if promo is not None:
            apply_promotion(out, src["research"], promo, now)
    return out


def apply_promotion(out, s, promo, now):
    """Two-key promotion: serve the OAE block's games only when the producer declares it activated with the promoted
    model_version. The incumbent publishes nothing, so otherwise the sport stays unavailable (with the reason)."""
    try:
        pf = s.read_json(RESEARCH_PATH)
        art = artifact(s, RESEARCH_PATH)
    except Exception as e:  # noqa: BLE001
        out["promotion"] = promotion.summary(promo, 0, [f"promoted source unreadable: {type(e).__name__}"])
        return
    b = pf.get(OAE_KEY) or {}
    decl = {k: b.get(k) for k in OAE_DECL_KEYS}
    why = ("artifact carries no oae_challenger block" if not b else
           f"block unavailable: {b.get('unavailable_reason')}" if not b.get("available") else
           promotion.check_block(decl, b.get("model_version"), promo))
    names = {str(g["game_id"]): g for g in pf.get("games", [])}
    games = []
    if why is None:
        for g in b.get("games", []):
            meta = names.get(str(g["game_id"]), {})
            fg = g["fg"]
            periods = {seg: {k: v for k, v in d.items() if k in ("expected_margin", "expected_total", "p_home_win",
                                                                 "p_away_win")}
                       for seg, d in (g.get("periods") or {}).items()}
            games.append(make_game(
                sport=SPORT, game_id=g["game_id"], start_time=g["start_utc"],
                home={"name": meta.get("home"), "abbr": None}, away={"name": meta.get("away"), "abbr": None},
                model_version=b["model_version"], projected_at=b.get("forecast_utc"), source=ref_string(art),
                declaration=decl, p_home=fg.get("p_home_win"), p_away=fg.get("p_away_win"),
                margin_home=fg.get("expected_margin"), period_projections=periods or None,
                flags=["promoted_model: CFB production publishes no model projection; this is the approved OAE forecast"],
                detail={"sigma_margin": fg.get("sigma_margin"), "not_published": list((b.get("excluded") or {}))}))
    out["promotion"] = promotion.summary(promo, len(games), [] if games or why is None else [why])
    if games:
        out.update(status=None, reason=None, source_class=None, games=games, artifact=art, declaration=decl,
                   model_version=b["model_version"], projected_at=b.get("forecast_utc"),
                   bet_authority="NONE (forecast only)", authority_note=b.get("note"))
    elif why is not None:
        out["reason"] = f"{out['reason']}; promoted {promo['model_version']} not served: {why}"


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
