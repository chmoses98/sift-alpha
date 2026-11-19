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
from datetime import timedelta

from .. import promotion, teams
from ..schema import contract, make_game, parse_ts
from . import artifact, ref_string

SPORT = "NBA"
MAX_AGE_HOURS = 12
SOURCES = {"prod": ("nba-edge-finder", "data-archive")}
PROMOTED_SOURCE = ("nba-edge-finder", "projection-data")   # read ONLY when operating_models.json promotes NBA
PATH = "slates/latest/slate.json"
FAMILIES = ("game_winner", "game_spread", "game_total", "team_total", "period_winner")
PAG_KEY = "pag_v1"
PAG_DIR = "game_forecasts/nba"
PAG_DECL_KEYS = ("activation", "authority", "role", "operating_forecast")


def sources():
    """The incumbent slate always; projection-data only when a promotion is approved in the manifest."""
    return {**SOURCES, "promoted": PROMOTED_SOURCE} if promotion.promoted(SPORT) else dict(SOURCES)


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
    res = {"artifact": art, "model_version": slate.get("model_version"), "projected_at": slate["generated_at_utc"],
           "bet_authority": "RESEARCH (no betting authority)", "authority_note": slate.get("authority_note"),
           "declaration": decl, "games": games}
    promo = promotion.promoted(SPORT)
    if promo is not None:
        apply_promotion(res, src.get("promoted"), promo, now)
    return res


def newest_pag_records(s, now):
    """Newest pf game-forecast record per upcoming game (generated at or before `now`), from the day folders around now."""
    import gzip
    import json
    newest = {}
    for d in range(-1, 4):
        day = (now + timedelta(days=d)).strftime("%Y-%m-%d")
        for path in s.list_files(f"{PAG_DIR}/{day}"):
            if not path.endswith(".jsonl.gz"):
                continue
            for line in gzip.decompress(s.read_bytes(path)).decode().splitlines():
                r = json.loads(line)
                gen, start = parse_ts(r.get("generated_utc")), parse_ts(r.get("game_start_utc"))
                if gen is None or start is None or gen > now or start <= now:
                    continue
                cur = newest.get(r["game_id"])
                if cur is None or r["generated_utc"] > cur[0]["generated_utc"]:
                    newest[r["game_id"]] = (r, path)
    return newest


def pag_game(r, b, ref):
    fg = b["full_game"]
    periods = {}
    for seg, v in ((b.get("periods") or {}).get("segments") or {}).items():
        pub = v.get("published") or []
        periods[seg] = {"total": v.get("total_mean") if "total" in pub else None,
                        "home": v.get("home_mean") if "team_total" in pub else None,
                        "away": v.get("away_mean") if "team_total" in pub else None,
                        "settlement_basis": v.get("settlement_basis")}
    return make_game(
        sport=SPORT, game_id=r["game_id"], start_time=r["game_start_utc"], home=teams.team(SPORT, r["home"]),
        away=teams.team(SPORT, r["away"]), model_version=b["model_version"], projected_at=b["generated_utc"], source=ref,
        declaration={k: b.get(k) for k in PAG_DECL_KEYS}, p_home=fg.get("p_home_win"), margin_home=fg.get("margin_mean"),
        period_projections=periods or None, flags=["promoted_model: replaces the incumbent nba-sim forecast for this game"],
        detail={"margin_sd": fg.get("margin_sd"), "not_published": ["projected_total", "team_totals", "period spread/winner"],
                "betting_authority": b.get("betting_authority"), "frozen_sha256": b.get("frozen_sha256")})


def apply_promotion(res, s, promo, now):
    """Serve each game from its newest activated PAG block (both keys); otherwise keep the incumbent game, flagged."""
    by_game = {g["game_id"]: g for g in res["games"]}
    reasons, served, newest_at = [], 0, None
    try:
        records = newest_pag_records(s, now) if s is not None else {}
        art = artifact(s, PAG_DIR) if s is not None else None
    except Exception as e:  # noqa: BLE001 - the incumbent must still publish
        records, art = {}, None
        reasons.append(f"promoted source unreadable: {type(e).__name__}")
    for gid in sorted(set(by_game) | set(records)):
        rec = records.get(gid)
        b = (rec[0].get(PAG_KEY) if rec else None) or None
        why = ("no promoted-model record for this game" if rec is None else
               "newest projection run published no pag_v1 block" if b is None else
               promotion.check_block({k: b.get(k) for k in PAG_DECL_KEYS}, b.get("model_version"), promo))
        if why is None:
            by_game[gid] = pag_game(rec[0], b, ref_string(art, rec[1]))
            served += 1
            newest_at = max(newest_at or b["generated_utc"], b["generated_utc"])
        elif gid in by_game:
            by_game[gid]["flags"].append(f"fallback_incumbent: {why}")
            reasons.append(why)
    res["games"] = list(by_game.values())
    res["promotion"] = promotion.summary(promo, served, reasons)
    if served and not reasons:   # every game is the promoted model: the sport is labelled from ITS declaration
        res["declaration"] = {k: b2.get(k) for k in PAG_DECL_KEYS} if (b2 := _any_served_block(records)) else res["declaration"]
        res["artifact"] = art
    if served:
        res["model_version"] = promo["model_version"] if not reasons else f"{promo['model_version']} (+ incumbent fallback)"
        res["projected_at"] = max(res["projected_at"], newest_at) if res.get("projected_at") else newest_at


def _any_served_block(records):
    for r, _ in records.values():
        if (r.get(PAG_KEY) or {}).get("activation") == "activated":
            return r[PAG_KEY]
    return None
