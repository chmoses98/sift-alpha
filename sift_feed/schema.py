"""Schema v1 helpers shared by every adapter.

Derivations allowed here (and only these) are arithmetic restatements of numbers the production
model itself published; each is named in the game's `derived` list:
  * home_spread = -projected_margin_home            (sportsbook sign: the favourite is negative)
  * spread string from the same margin               ("BOS -8.4", "PK" when it rounds to 0.0)
  * away win probability = 1 - home                  (only when the artifact gives one side only)
  * projected_winner = side with the higher published win probability
Nothing else is computed: a field the artifact does not carry is null.
"""
from datetime import datetime, timezone

SCHEMA_VERSION = "sift.projection_feed.v1"
PRODUCTION = "production"
APPROVED = "activated_production_forecast"
RESEARCH = "research_only_not_activated"
SPORT_STATUSES = ("ok", "stale", "offseason", "unavailable")
# Index entries drop these heavy keys; they stay in feed/v1/<sport>.json (the index carries the
# sport-level union of `derived` as sports.<SPORT>.derivations).
DETAIL_KEYS = ("contracts", "detail", "derived")

GAME_KEYS = ("sport", "game_id", "start_time", "status", "approval_status", "home", "away", "projected_winner",
             "win_probability", "projected_margin_home", "home_spread", "spread", "projected_total", "team_totals",
             "period_projections", "contract_count", "model_version", "projected_at", "data_age_seconds", "stale",
             "flags", "derived", "source")


def parse_ts(ts):
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    s = str(ts).strip().replace("Z", "+00:00")
    if len(s) == 10:
        s += "T00:00:00+00:00"
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def iso(d):
    return None if d is None else d.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def rnd(x, n=1):
    return None if x is None else round(float(x), n)


def spread_fields(margin_home, home_label, away_label):
    """(home_spread, spread string) from the model's own projected home-minus-away margin.

    The favourite carries the negative number: margin +8.4 for the home side -> home_spread -8.4,
    "HOME -8.4"; margin -3.4 -> home_spread +3.4, "AWAY -3.4"; |margin| < 0.05 -> 0.0, "PK"."""
    if margin_home is None:
        return None, None
    m = round(float(margin_home), 1)
    if m == 0:
        return 0.0, "PK"
    fav = home_label if m > 0 else away_label
    return -m, f"{fav} -{abs(m):.1f}"


def win_probs(p_home=None, p_away=None):
    """Return ({"home","away"}, derived?) using only the artifact's own probabilities."""
    if p_home is None and p_away is None:
        return None, False
    derived = p_home is None or p_away is None
    if p_home is None:
        p_home = 1.0 - float(p_away)
    if p_away is None:
        p_away = 1.0 - float(p_home)
    return {"home": round(float(p_home), 3), "away": round(float(p_away), 3)}, derived


def label(t):
    return t.get("abbr") or t.get("name")


def make_game(*, sport, game_id, start_time, home, away, model_version, projected_at, source,
              p_home=None, p_away=None, margin_home=None, total=None, home_pts=None, away_pts=None,
              period_projections=None, contracts=None, flags=None, derived=None, detail=None, digits=1):
    """Build one production game record (schema v1). `derived` lists any extra adapter-side
    derivations; the standard ones above are appended automatically."""
    derived = list(derived or [])
    wp, wp_derived = win_probs(p_home, p_away)
    if wp_derived:
        derived.append("win_probability: complement of the artifact's single published side")
    home_spread, spread = spread_fields(margin_home, label(home), label(away))
    if spread is not None:
        derived.append("home_spread/spread: negated projected_margin_home, favourite negative")
    winner = None
    if wp and wp["home"] != wp["away"]:
        winner = label(home) if wp["home"] > wp["away"] else label(away)
    team_totals = None
    if home_pts is not None or away_pts is not None:
        team_totals = {"home": rnd(home_pts, digits), "away": rnd(away_pts, digits)}
    return {
        "sport": sport, "game_id": str(game_id), "start_time": iso(parse_ts(start_time)),
        "status": PRODUCTION, "approval_status": APPROVED,
        "home": home, "away": away, "projected_winner": winner, "win_probability": wp,
        "projected_margin_home": rnd(margin_home, max(digits, 1)), "home_spread": home_spread, "spread": spread,
        "projected_total": rnd(total, digits), "team_totals": team_totals,
        "period_projections": period_projections or None,
        "contract_count": len(contracts) if contracts else 0,
        "model_version": model_version, "projected_at": iso(parse_ts(projected_at)),
        "data_age_seconds": None, "stale": None, "flags": flags or [], "derived": derived, "source": source,
        "contracts": contracts or [], "detail": detail or {},
    }


def contract(ticker, family, period, p, title=None, side=None, line=None):
    return {"ticker": ticker, "family": family, "period": period, "side": side, "line": line,
            "p_model": round(float(p), 4), "title": title}


def validate_game(g):
    """Schema + sign invariants; returns a list of problems (empty == valid)."""
    errs = [f"missing {k}" for k in GAME_KEYS if k not in g]
    if errs:
        return errs
    if g["status"] == PRODUCTION and g["approval_status"] != APPROVED:
        errs.append("production game without activated approval")
    m, hs = g["projected_margin_home"], g["home_spread"]
    if m is not None and hs is not None and round(m, 1) != 0 and (hs > 0) == (m > 0):
        errs.append("home_spread sign does not oppose margin")
    wp = g["win_probability"]
    if wp:
        for v in wp.values():
            if not 0 <= v <= 1:
                errs.append("win probability out of [0,1]")
    for k in ("start_time", "projected_at"):
        if g[k] is not None and not g[k].endswith("Z"):
            errs.append(f"{k} not UTC ISO")
    return errs
