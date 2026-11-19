"""CBB operating forecast (source_class follows the artifact's own declaration).
Source: the ACTIVE INCUMBENT of the PURE_BASKETBALL model, named by
`main:models/pure/active.json` ("incumbent"), archived per (game, run) on `projections-archive`
by cbb-edge-finder .github/workflows/prospective-projections.yml. The incumbent pure-0.2.0 uses the
legacy layout projections/<season>/<date>/<game>/<run>.json; any other version lives under
projections/<version>/<season>/... . Each record must also say prospective.role == "incumbent" and
model.version == the incumbent, or it is skipped.

NOT used: the shadow challengers listed in active.json (pure-0.3.0 / 0.4.0 / 0.5.0 / 0.5.0_roster).

Field map (record.projection): home_win_prob (home only; away = 1 - home), margin (home minus away),
total, home_score / away_score -> team_totals. The newest run per game is used. The archive carries
team names but no abbreviation, so abbr is null. No period or contract probabilities are produced.
"""
from datetime import timedelta

from ..schema import make_game
from . import artifact, ref_string

SPORT = "CBB"
MAX_AGE_HOURS = 24
SOURCES = {"config": ("cbb-edge-finder", "main"), "prod": ("cbb-edge-finder", "projections-archive")}
ACTIVE = "models/pure/active.json"
LEGACY = "pure-0.2.0"
LOOKBACK_DAYS, LOOKAHEAD_DAYS = 1, 7


def base_dir(version, season):
    return f"projections/{season}" if version == LEGACY else f"projections/{version}/{season}"


def build(src, now):
    active = src["config"].read_json(ACTIVE)
    incumbent = active["incumbent"]
    s = src["prod"]
    season = now.year + 1 if now.month >= 7 else now.year
    base = base_dir(incumbent, season)
    latest = {}
    for i in range(-LOOKBACK_DAYS, LOOKAHEAD_DAYS + 1):
        day = (now + timedelta(days=i)).strftime("%Y-%m-%d")
        for p in s.list_files(f"{base}/{day}"):
            parts = p[len(base) + 1:].split("/")
            if len(parts) == 3 and parts[2].endswith(".json"):
                key = parts[1]
                if key not in latest or p > latest[key]:
                    latest[key] = p
    paths = sorted(latest.values())
    if hasattr(s, "prefetch"):
        s.prefetch(paths)
    art = artifact(s, base + "/")
    games, skipped, newest = [], 0, None
    for p in paths:
        r = s.read_json(p)
        role, version = (r.get("prospective") or {}).get("role"), (r.get("model") or {}).get("version")
        pr, gm = r.get("projection") or {}, r.get("game") or {}
        if role != "incumbent" or version != incumbent or not gm.get("start_time_utc"):
            skipped += 1
            continue
        projected_at = (r.get("prospective") or {}).get("as_of") or r.get("generated_at")
        newest = max(newest or projected_at, projected_at)
        sched = (r.get("schedule") or {}).get("live") or {}
        flags = []
        if sched.get("time_state") and sched["time_state"] != "ANNOUNCED":
            flags.append(f"start_time_{sched['time_state'].lower()}")
        games.append(make_game(
            sport=SPORT, game_id=gm.get("game_id"), start_time=gm["start_time_utc"],
            home={"name": r["home"]["name"], "abbr": None}, away={"name": r["away"]["name"], "abbr": None},
            model_version=version, projected_at=projected_at, source=ref_string(art, p),
            declaration={"model.research_state": (r.get("model") or {}).get("research_state"), "prospective.role": role},
            source_updated_at=r.get("generated_at"),
            p_home=pr.get("home_win_prob"), margin_home=pr.get("margin"), total=pr.get("total"),
            home_pts=pr.get("home_score"), away_pts=pr.get("away_score"), flags=flags,
            detail={"site": gm.get("site"), "margin_sd": pr.get("margin_sd"), "total_sd": pr.get("total_sd"),
                    "possessions": pr.get("possessions")}))
    return {"artifact": art, "model_version": incumbent, "projected_at": newest,
            "bet_authority": "RESEARCH_ONLY (cbb app health.bet_authority)",
            "authority_note": active.get("note"), "declaration": games[0]["source_declaration"] if games else None, "games": games, "skipped_records": skipped,
            "config_source": artifact(src["config"], ACTIVE)}
