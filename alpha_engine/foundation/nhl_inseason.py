"""NHL in-season reconstruction helpers for ``alpha-nhl-joint-0.3`` (RESEARCH_ONLY, pure numpy; unit-tested on synthetic data).

Three things live here, all point-in-time by construction of their inputs:

* ``first_available``  - per key, the FIRST archived observation and the capture time it became visible (archive file stamp).
* ``availability_masks`` - which archived team-game rows may update a team state / a league mean for a later game, given
  that game's freeze time (start - 60 min). A row that was captured too late is dropped, never back-dated.
* a small shot-level expected-goals model on official play-by-play shot events (distance, angle, shot type, strength, rebound,
  zone), fitted on prior seasons only, plus the team-game aggregation that makes it comparable with MoneyPuck.

Nothing here reads a file or the network.
"""
from __future__ import annotations

import math

import numpy as np

NET_X = 89.0
SHOT_TYPES = ["snap", "slap", "backhand", "tip-in", "deflected", "wrap-around", "other"]  # base level = wrist
XG_FEATS = (["intercept", "dist", "dist2", "log_dist", "angle", "angle2", "rebound", "quick", "zone_N", "zone_D", "str_PP", "str_SH", "missing_xy"]
            + [f"type_{t}" for t in SHOT_TYPES])
UNBLOCKED = ("SOG", "MISS", "GOAL")
HIGH_DANGER_XG = 0.2  # MoneyPuck's own definition of a high-danger attempt (xG >= 0.2)


def stamp_hours(ts) -> float:
    """Hours since 2000-01-01T00:00Z for 'YYYYMMDDTHHMMSSZ' or ISO 'YYYY-MM-DDTHH:MM:SSZ' stamps."""
    s = str(ts).replace("-", "").replace(":", "")
    d = np.datetime64(f"{s[0:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}")
    return float((d - np.datetime64("2000-01-01T00:00:00")) / np.timedelta64(1, "s")) / 3600.0


def first_available(observations):
    """``observations`` = iterable of (key, capture_stamp, row) in ANY order. Returns {key: (capture_stamp, row)} for the
    EARLIEST capture of each key: the value as it was first visible, never a later revision."""
    out = {}
    for k, ts, r in observations:
        if k not in out or ts < out[k][0]:
            out[k] = (ts, r)
    return out


def availability_masks(team, game_day, avail_h, freeze_h):
    """Point-in-time usability of per-team-game stat rows (rows in chronological order, as in the model frame).

    ``avail_h``  hours-stamp at which the row's source stats were first captured (NaN = history: published before any later game),
    ``freeze_h`` hours-stamp of the row's own forecast freeze (NaN = history).
    Returns (state_ok, league_ok):
      state_ok[i]  False when row i was NOT yet captured at the freeze of the same team's NEXT game (it would leak into that
                   team's pre-game state), so it must not update the team state;
      league_ok[i] False when row i was not captured at the EARLIEST freeze of any game on a later calendar day (the league
                   mean for a later game reads every earlier-day row).
    A row that fails is excluded for good (conservative): it is never re-admitted later."""
    team = np.asarray(team); game_day = np.asarray(game_day); a = np.asarray(avail_h, float); f = np.asarray(freeze_h, float)
    n = len(team); state_ok = np.ones(n, bool); league_ok = np.ones(n, bool)
    nxt = {}
    for i in range(n - 1, -1, -1):
        t = team[i]; j = nxt.get(t)
        if j is not None and np.isfinite(a[i]) and np.isfinite(f[j]) and a[i] > f[j]:
            state_ok[i] = False
        nxt[t] = i
    days = np.unique(game_day[np.isfinite(f)])
    if len(days):
        first_freeze = np.array([np.nanmin(f[game_day == d]) for d in days])
        suffix_min = np.minimum.accumulate(first_freeze[::-1])[::-1]  # earliest freeze on day >= d
        for i in np.flatnonzero(np.isfinite(a)):
            k = np.searchsorted(days, game_day[i], side="right")  # first later day
            if k < len(days) and a[i] > suffix_min[k]:
                league_ok[i] = False
    return state_ok, league_ok


# ====================================================================== shot-level expected goals
def shot_geometry(x, y, zone):
    """Distance (ft) and absolute angle (degrees) to the attacked net from rink coordinates. Offensive-zone attempts attack the
    net on their own side of centre; neutral/defensive-zone attempts attack the far net."""
    x = np.asarray(x, float); y = np.asarray(y, float); z = np.asarray(zone).astype(str)
    miss = ~(np.isfinite(x) & np.isfinite(y))
    ax = np.abs(np.where(miss, 0.0, x)); yy = np.where(miss, 0.0, y)
    dx = np.where(z == "O", NET_X - ax, np.where(z == "D", NET_X + ax, NET_X))
    dist = np.hypot(dx, yy)
    ang = np.degrees(np.arctan2(np.abs(yy), np.maximum(dx, 1e-6)))
    ang = np.where(dx <= 0, 90.0 + np.degrees(np.arctan2(-dx, np.abs(yy) + 1e-6)), ang)  # behind the goal line
    return np.where(miss, 35.0, dist), np.where(miss, 20.0, ang), miss


def xg_design(x, y, zone, shot_type, strength, since_prev_s):
    """Design matrix (columns = XG_FEATS) for unblocked attempts on a goalie."""
    dist, ang, miss = shot_geometry(x, y, zone)
    z = np.asarray(zone).astype(str); st = np.asarray(shot_type).astype(str); sg = np.asarray(strength).astype(str)
    sp = np.asarray(since_prev_s, float)
    known = set(SHOT_TYPES[:-1]) | {"wrist"}
    cols = [np.ones(len(dist)), dist / 30.0, (dist / 30.0) ** 2, np.log1p(dist), ang / 45.0, (ang / 45.0) ** 2,
            (np.isfinite(sp) & (sp <= 3)).astype(float), (np.isfinite(sp) & (sp > 3) & (sp <= 8)).astype(float),
            (z == "N").astype(float), (z == "D").astype(float), (sg == "PP").astype(float), (sg == "SH").astype(float), miss.astype(float)]
    for t in SHOT_TYPES[:-1]:
        cols.append((st == t).astype(float))
    cols.append(np.array([s not in known for s in st], float))
    return np.column_stack(cols)


def fit_logistic(X, y, ridge=1.0, iters=60):
    """Ridge-penalised logistic regression by Newton steps (intercept unpenalised)."""
    X = np.asarray(X, float); y = np.asarray(y, float); b = np.zeros(X.shape[1])
    b[0] = math.log(max(y.mean(), 1e-6) / max(1 - y.mean(), 1e-6))
    R = ridge * np.eye(X.shape[1]); R[0, 0] = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30))); w = np.clip(p * (1 - p), 1e-9, None)
        step = np.linalg.solve(X.T @ (X * w[:, None]) + R, X.T @ (y - p) - R @ b)
        b += step
        if np.max(np.abs(step)) < 1e-9:
            break
    return b


def predict_logistic(X, b):
    return 1 / (1 + np.exp(-np.clip(np.asarray(X, float) @ b, -30, 30)))


def fit_shot_xg(sh, mask):
    """Fit the two-part model on rows ``mask`` of a shot frame (columns kind, x, y, zone, shot_type, strength, since_prev_s):
    a logistic model for unblocked attempts on a goalie and a distance-only logistic model for attempts at an empty net."""
    unb = np.isin(sh["kind"], UNBLOCKED); y = (np.asarray(sh["kind"]) == "GOAL").astype(float); en = np.asarray(sh["strength"]).astype(str) == "EN"
    m1 = mask & unb & ~en; m2 = mask & unb & en
    X = xg_design(sh["x"][m1], sh["y"][m1], sh["zone"][m1], sh["shot_type"][m1], sh["strength"][m1], sh["since_prev_s"][m1])
    b = fit_logistic(X, y[m1])
    d2 = shot_geometry(sh["x"][m2], sh["y"][m2], sh["zone"][m2])[0]
    # too few empty-net attempts to fit (synthetic or partial data): a flat 50% model, never a crash
    b_en = fit_logistic(np.column_stack([np.ones(len(d2)), d2 / 30.0]), y[m2], ridge=0.1) if int(m2.sum()) >= 20 else np.zeros(2)
    return {"beta": b, "beta_empty_net": b_en, "n_fit": int(m1.sum()), "n_fit_empty_net": int(m2.sum())}


def shot_xg(sh, model):
    """Per-row xG (0 for blocked attempts, which carry the blocker's coordinates and are counted as volume only)."""
    n = len(sh["kind"]); out = np.zeros(n)
    unb = np.isin(sh["kind"], UNBLOCKED); en = np.asarray(sh["strength"]).astype(str) == "EN"
    m1 = unb & ~en; m2 = unb & en
    if m1.any():
        out[m1] = predict_logistic(xg_design(sh["x"][m1], sh["y"][m1], sh["zone"][m1], sh["shot_type"][m1], sh["strength"][m1], sh["since_prev_s"][m1]), model["beta"])
    if m2.any():
        d2 = shot_geometry(sh["x"][m2], sh["y"][m2], sh["zone"][m2])[0]
        out[m2] = predict_logistic(np.column_stack([np.ones(len(d2)), d2 / 30.0]), model["beta_empty_net"])
    return out


def team_game_xg(game_id, is_home, strength, kind, xg):
    """Aggregate shot rows to {(game_id, is_home): dict(xf_all, xf_ev, xf_pp, xf_sh, hd_all, att_all, goals_all)} (FOR side)."""
    game_id = np.asarray(game_id); is_home = np.asarray(is_home).astype(int); sg = np.asarray(strength).astype(str); kd = np.asarray(kind).astype(str)
    xg = np.asarray(xg, float); out = {}
    key = game_id.astype(np.int64) * 2 + is_home
    uk, inv = np.unique(key, return_inverse=True)
    def agg(w):
        return np.bincount(inv, weights=w, minlength=len(uk))
    cols = {"xf_all": agg(xg), "xf_ev": agg(xg * (sg == "EV")), "xf_pp": agg(xg * (sg == "PP")), "xf_sh": agg(xg * (sg == "SH")),
            "hd_all": agg(xg * (xg >= HIGH_DANGER_XG)), "att_all": agg(np.ones(len(xg))), "goals_all": agg((kd == "GOAL").astype(float))}
    for j, k in enumerate(uk):
        out[(int(k // 2), int(k % 2))] = {c: float(v[j]) for c, v in cols.items()}
    return out
