"""Independent re-implementation of the CFB game-level feature dataset (certification, RESEARCH_ONLY).

Built only from docs/certification/CFB_FEATURE_SPEC.md (and the rating-solver section of
docs/certification/CBB_FEATURE_SPEC.md). No production feature code was consulted.

Usage:
    python -m alpha_engine.certify.cfb_independent --cfb DIR --out FILE.parquet

SPEC AMBIGUITIES (each resolved by the most literal reading)
------------------------------------------------------------
1. Seasons: only S = 2014..2025 are read even though the cache also holds 2026 (spec says 2014..2025).
2. Drive points use plain substring tests on `driveResult`. Hence "FUMBLE RETURN TD", "PUNT RETURN TD",
   "MISSED FG TD", "DOWNS TD", "END OF HALF TD" count 7 (they contain "TD" and none of the excluded
   substrings "DEF", "INT TD", "FUMBLE TD", "PUNT TD"); "PUNT TD"/"INT TD"/"FUMBLE TD" count 0. A non-string
   driveResult scores 0. Drives are not deduplicated (spec gives no rule).
3. `ppd_d` = the drive-aggregate `ppd_o` at (gameId, opponent) where opponent is the advanced-box record's
   `opponent` field. Drive aggregates are attached to the advanced-box rows by (gameId, team), so drives of games
   without an advanced-box record (all postseason drives, since the box is regular-season only) are unused.
   `start_ytg_o` averages only drives whose `startYardsToGoal` is a number.
4. "Not a JSON number" -> missing: booleans are treated as non-numbers.
5. `site` for the solver is computed on the frame from the game (identical to the stats-table definition for
   every row that has stats; rows without stats never enter H(D)).
6. "Teams absent from H(D)" = teams not in the solver team set (union of `team` and `opp` over H(D)). A team that
   appears in H(D) only as an opponent therefore gets adj_epa_* (O = 0), n_pre = 0, and missing window means
   (0/0). (Moot on the current cache: every opponent in H(D) also has rows as `team`.)
7. Warm start state = exactly the previous solved date's team set and values; a team not in that set starts at 0
   even if it was solved on an earlier date. `lg` is always re-initialised to the weighted mean of y.
8. O updates are simultaneous across teams (Jacobi within step 1) using the previous iteration's D; D uses the
   new O; h and lg use the newest values (CBB spec order).
9. Window mean with sum(v) == 0 (e.g. plays == 0 on all eligible rows) -> missing.
10. `age_days` = integer calendar-day difference D - date (dates are NY calendar dates).
11. recruit_prior: rows exist for each (team, year) present in recruiting_teams; value = mean of that team's
    `points` over years S-3..S that are present in the loaded data (2011-2013 are not in the cache, so early
    seasons average fewer years). No row is created for a season the team lacks a record for.
12. Portal: entries with missing `transferDate` are excluded (not "before" the cutoff). portal_in_prior /
    portal_out_prior come from separate group-bys, so a team with only outgoing (or only incoming) entries has the
    other count missing (not 0) after the outer join. portal_stars_net_prior treats missing mean_stars or missing
    count as 0 and is defined for every team in either group-by. mean_stars ignores entries with missing stars;
    count_in/out count all entries.
13. Priors sources are not deduplicated (no duplicates exist in the data anyway). talent / returning values are
    coerced numeric.
14. `completed == true` is tested as identity with JSON true; points "present" = not null.
15. Output dtypes: `date` is a naive datetime64 (midnight of the NY date); `cutoff_utc` is tz-aware UTC;
    neutral/conference_game/postseason/y_home_win are floats 0/1.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import time

import numpy as np
import pandas as pd

SEASONS = list(range(2014, 2026))
SOURCES = ["games", "advanced_regular_nogarbage", "drives_regular", "drives_postseason", "portal",
           "returning_production", "talent", "recruiting_teams"]
WINDOW_COLS = ["sr_o", "sr_d", "expl_o", "expl_d", "pass_ppa_o", "rush_ppa_o", "pass_ppa_d", "rush_ppa_d",
               "line_yds_o", "stuff_o", "ppd_o", "ppd_d", "start_ytg_o"]
INSEASON = ["adj_epa_o_pre", "adj_epa_d_pre", "adj_epa_net_pre", "hfa_epa_pre", "n_pre"] + \
    [c + "_pre" for c in WINDOW_COLS]
PRIORS = ["talent_prior", "ret_ppa_prior", "ret_usage_prior", "recruit_prior", "portal_in_prior",
          "portal_out_prior", "portal_stars_net_prior"]
MIN_HIST = 100
WINDOW_DAYS = 400
HALF_LIFE = 120.0
N_ITER = 12
SHRINK = 3.0


# ----------------------------------------------------------------------------------------------- loading
def _read(path):
    if not os.path.exists(path):
        return []
    with gzip.open(path, "rt") as fh:
        payload = json.load(fh)
    if isinstance(payload, dict):
        payload = payload.get("data", []) or []
    return list(payload)


def load_raw(cache_dir) -> dict:
    raw = {name: [] for name in SOURCES}
    raw["drives"] = []  # per season: drives_regular followed by drives_postseason
    for s in SEASONS:
        for name in SOURCES:
            part = _read(os.path.join(cache_dir, str(s), name + ".json.gz"))
            raw[name].extend(part)
            if name.startswith("drives_"):
                raw["drives"].extend(part)
    return raw


def _num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return np.nan
    return float(x)


def _get(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


# ----------------------------------------------------------------------------------------------- games
def _games(raw):
    rows, seen = [], set()
    for g in raw["games"]:
        gid = g.get("id")
        if gid in seen:
            continue
        seen.add(gid)
        rows.append(g)
    keep = [g for g in rows
            if g.get("completed") is True and g.get("homePoints") is not None and g.get("awayPoints") is not None
            and (g.get("homeClassification") == "fbs" or g.get("awayClassification") == "fbs")]
    df = pd.DataFrame({
        "game_id": [g["id"] for g in keep],
        "season": [g.get("season") for g in keep],
        "startDate": [g.get("startDate") for g in keep],
        "home_team": [g.get("homeTeam") for g in keep],
        "away_team": [g.get("awayTeam") for g in keep],
        "neutralSite": [g.get("neutralSite") for g in keep],
        "conferenceGame": [g.get("conferenceGame") for g in keep],
        "seasonType": [g.get("seasonType") for g in keep],
        "homePoints": [float(g["homePoints"]) for g in keep],
        "awayPoints": [float(g["awayPoints"]) for g in keep],
    })
    df["start_utc"] = pd.to_datetime(df["startDate"], utc=True)
    df["date"] = df["start_utc"].dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    return df


# ----------------------------------------------------------------------------------------------- team-game stats
def _stats(raw, games):
    recs, seen = [], set()
    for r in raw["advanced_regular_nogarbage"]:
        key = (r.get("gameId"), r.get("team"))
        if key in seen:
            continue
        seen.add(key)
        o, d = r.get("offense"), r.get("defense")
        recs.append({
            "game_id": r.get("gameId"), "team": r.get("team"), "adv_opp": r.get("opponent"),
            "plays": _num(_get(o, "plays")),
            "ppa_o": _num(_get(o, "ppa")), "ppa_d": _num(_get(d, "ppa")),
            "sr_o": _num(_get(o, "successRate")), "sr_d": _num(_get(d, "successRate")),
            "expl_o": _num(_get(o, "explosiveness")), "expl_d": _num(_get(d, "explosiveness")),
            "pass_ppa_o": _num(_get(o, "passingPlays", "ppa")), "pass_ppa_d": _num(_get(d, "passingPlays", "ppa")),
            "rush_ppa_o": _num(_get(o, "rushingPlays", "ppa")), "rush_ppa_d": _num(_get(d, "rushingPlays", "ppa")),
            "line_yds_o": _num(_get(o, "lineYards")), "stuff_o": _num(_get(o, "stuffRate")),
        })
    st = pd.DataFrame(recs)

    def drive_pts(res):
        if not isinstance(res, str):
            return 0.0
        if "TD" in res and not any(x in res for x in ("DEF", "INT TD", "FUMBLE TD", "PUNT TD")):
            return 7.0
        if res == "FG":
            return 3.0
        return 0.0

    dr = pd.DataFrame({
        "game_id": [x.get("gameId") for x in raw["drives"]],
        "team": [x.get("offense") for x in raw["drives"]],
        "pts": [drive_pts(x.get("driveResult")) for x in raw["drives"]],
        "ytg": [_num(x.get("startYardsToGoal")) for x in raw["drives"]],
    })
    agg = dr.groupby(["game_id", "team"], sort=False, dropna=False).agg(ppd_o=("pts", "mean"),
                                                                       start_ytg_o=("ytg", "mean")).reset_index()
    st = st.merge(agg, on=["game_id", "team"], how="left")
    opp_agg = agg[["game_id", "team", "ppd_o"]].rename(columns={"team": "adv_opp", "ppd_o": "ppd_d"})
    st = st.merge(opp_agg, on=["game_id", "adv_opp"], how="left")
    # inner join to filtered games
    st = st[st["game_id"].isin(set(games["game_id"]))]
    return st.drop(columns=["adv_opp"])


# ----------------------------------------------------------------------------------------------- frame
def _frame(games, stats):
    home = pd.DataFrame({"game_id": games["game_id"], "date": games["date"], "season": games["season"],
                         "team": games["home_team"], "opp": games["away_team"],
                         "site": np.where(games["neutralSite"] == True, 0, 1)})  # noqa: E712
    away = pd.DataFrame({"game_id": games["game_id"], "date": games["date"], "season": games["season"],
                         "team": games["away_team"], "opp": games["home_team"],
                         "site": np.where(games["neutralSite"] == True, 0, -1)})  # noqa: E712
    fr = pd.concat([home, away], ignore_index=True)
    fr = fr.merge(stats, on=["game_id", "team"], how="left")
    return fr


# ----------------------------------------------------------------------------------------------- solver
def _solve(ti, oi, site, y, w, n_teams, O0, D0, h0):
    """CBB-spec alternating solver on global team indices. Returns lg, O, D, h."""
    sw = w.sum()
    lg = float((w * y).sum() / sw)
    O, D, h = O0.copy(), D0.copy(), float(h0)
    wt = np.bincount(ti, weights=w, minlength=n_teams)
    wo = np.bincount(oi, weights=w, minlength=n_teams)
    nz = site != 0
    w_nz = w[nz].sum()
    for _ in range(N_ITER):
        O = np.bincount(ti, weights=w * (y - lg - h * site + D[oi]), minlength=n_teams) / (wt + SHRINK)
        D = np.bincount(oi, weights=w * (lg + O[ti] + h * site - y), minlength=n_teams) / (wo + SHRINK)
        if w_nz > 0:
            r = w * site * (y - lg - O[ti] + D[oi])
            h = float(r[nz].sum() / w_nz)
        else:
            h = 0.0
        lg = float((w * (y - O[ti] + D[oi] - h * site)).sum() / sw)
    return lg, O, D, h


def _inseason(fr):
    teams = pd.Index(pd.unique(pd.concat([fr["team"], fr["opp"]], ignore_index=True)))
    n_teams = len(teams)
    fr_t = teams.get_indexer(fr["team"])
    day = (fr["date"].values.astype("datetime64[D]")).astype(np.int64)

    hist_mask = fr["ppa_o"].notna().values
    hidx = np.where(hist_mask)[0]
    hidx = hidx[np.argsort(day[hidx], kind="stable")]
    h_day = day[hidx]
    h_t = fr_t[hidx]
    h_o = teams.get_indexer(fr["opp"].values[hidx])
    h_site = fr["site"].values[hidx].astype(float)
    h_y = fr["ppa_o"].values[hidx].astype(float)
    h_plays = fr["plays"].values[hidx].astype(float)
    h_plays = np.where(np.isnan(h_plays), 60.0, h_plays)
    h_c = {c: fr[c].values[hidx].astype(float) for c in WINDOW_COLS}

    out = {f: np.full(len(fr), np.nan) for f in INSEASON}
    warm_O = np.zeros(n_teams)
    warm_D = np.zeros(n_teams)
    warm_in = np.zeros(n_teams, dtype=bool)
    warm_h = 0.0
    warm_ok = False

    for D_ in np.unique(day):
        rows = np.where(day == D_)[0]
        lo = np.searchsorted(h_day, D_ - WINDOW_DAYS, side="left")
        hi = np.searchsorted(h_day, D_, side="left")
        if hi - lo < MIN_HIST:
            warm_ok = False
            warm_in[:] = False
            continue
        sl = slice(lo, hi)
        ti, oi, site, y = h_t[sl], h_o[sl], h_site[sl], h_y[sl]
        age = (D_ - h_day[sl]).astype(float)
        w = 0.5 ** (age / HALF_LIFE)
        in_set = np.zeros(n_teams, dtype=bool)
        in_set[ti] = True
        in_set[oi] = True
        if warm_ok:
            O0 = np.where(in_set & warm_in, warm_O, 0.0)
            D0 = np.where(in_set & warm_in, warm_D, 0.0)
            h0 = warm_h
        else:
            O0, D0, h0 = np.zeros(n_teams), np.zeros(n_teams), 0.0
        lg, O, D, h = _solve(ti, oi, site, y, w, n_teams, O0, D0, h0)
        warm_O, warm_D, warm_h, warm_in, warm_ok = O, D, h, in_set, True

        t = fr_t[rows]
        present = in_set[t]
        o_val = lg + O[t]
        d_val = lg - D[t]
        out["adj_epa_o_pre"][rows] = np.where(present, o_val, np.nan)
        out["adj_epa_d_pre"][rows] = np.where(present, d_val, np.nan)
        out["adj_epa_net_pre"][rows] = np.where(present, o_val - d_val, np.nan)
        out["hfa_epa_pre"][rows] = h
        n_w = np.bincount(ti, weights=w, minlength=n_teams)
        out["n_pre"][rows] = np.where(present, n_w[t], np.nan)
        v = w * h_plays[sl]
        for c in WINDOW_COLS:
            x = h_c[c][sl]
            ok = ~np.isnan(x)
            num = np.bincount(ti[ok], weights=(v * x)[ok], minlength=n_teams)
            den = np.bincount(ti[ok], weights=v[ok], minlength=n_teams)
            with np.errstate(invalid="ignore", divide="ignore"):
                val = np.where(den[t] != 0, num[t] / np.where(den[t] != 0, den[t], 1.0), np.nan)
            out[c + "_pre"][rows] = np.where(present, val, np.nan)
    for f in INSEASON:
        fr[f] = out[f]
    return fr


# ----------------------------------------------------------------------------------------------- priors
def _priors(raw):
    tal = pd.DataFrame({"team": [r.get("team") for r in raw["talent"]],
                        "season": [r.get("year") for r in raw["talent"]],
                        "talent_prior": pd.to_numeric(pd.Series([r.get("talent") for r in raw["talent"]],
                                                                dtype=object), errors="coerce")})
    ret = pd.DataFrame({"team": [r.get("team") for r in raw["returning_production"]],
                        "season": [r.get("season") for r in raw["returning_production"]],
                        "ret_ppa_prior": pd.to_numeric(pd.Series([r.get("percentPPA") for r in
                                                                  raw["returning_production"]], dtype=object),
                                                       errors="coerce"),
                        "ret_usage_prior": pd.to_numeric(pd.Series([r.get("usage") for r in
                                                                    raw["returning_production"]], dtype=object),
                                                         errors="coerce")})
    rec = pd.DataFrame({"team": [r.get("team") for r in raw["recruiting_teams"]],
                        "season": [r.get("year") for r in raw["recruiting_teams"]],
                        "points": pd.to_numeric(pd.Series([r.get("points") for r in raw["recruiting_teams"]],
                                                          dtype=object), errors="coerce")})
    look = {}
    for t, s, p in zip(rec["team"], rec["season"], rec["points"]):
        look.setdefault(t, []).append((s, p))
    # spec v1.1 amendment: a (team, S) prior exists for every S in 2014..2025 where the team has >= 1 record in S-3..S
    # (not only when a year-S record exists)
    rows = []
    for t, lst in look.items():
        for s in range(2014, 2026):
            pts = [p for (ss, p) in lst if s - 3 <= ss <= s and not pd.isna(p)]
            if pts:
                rows.append((t, s, float(np.mean(pts))))
    rec_p = pd.DataFrame(rows, columns=["team", "season", "recruit_prior"])

    po = pd.DataFrame({"season": [r.get("season") for r in raw["portal"]],
                       "origin": [r.get("origin") for r in raw["portal"]],
                       "destination": [r.get("destination") for r in raw["portal"]],
                       "stars": [_num(r.get("stars")) for r in raw["portal"]],
                       "td": pd.to_datetime(pd.Series([r.get("transferDate") for r in raw["portal"]]),
                                            utc=True, errors="coerce")})
    po = po[po["season"].notna()].copy()
    po["season"] = po["season"].astype(int)
    cutoff = pd.to_datetime(po["season"].astype(str) + "-08-01", utc=True)
    po = po[po["td"].notna() & (po["td"] < cutoff)]
    pin = po[po["destination"].notna()].groupby(["destination", "season"]).agg(
        portal_in_prior=("stars", "size"), stars_in=("stars", "mean")).reset_index().rename(
        columns={"destination": "team"})
    pout = po[po["origin"].notna()].groupby(["origin", "season"]).agg(
        portal_out_prior=("stars", "size"), stars_out=("stars", "mean")).reset_index().rename(
        columns={"origin": "team"})
    port = pin.merge(pout, on=["team", "season"], how="outer")
    port["portal_in_prior"] = port["portal_in_prior"].astype(float)
    port["portal_out_prior"] = port["portal_out_prior"].astype(float)
    port["portal_stars_net_prior"] = (port["stars_in"] * port["portal_in_prior"]).fillna(0.0) - \
        (port["stars_out"] * port["portal_out_prior"]).fillna(0.0)
    port = port[["team", "season", "portal_in_prior", "portal_out_prior", "portal_stars_net_prior"]]

    pri = tal.merge(ret, on=["team", "season"], how="outer")
    pri = pri.merge(rec_p, on=["team", "season"], how="outer")
    pri = pri.merge(port, on=["team", "season"], how="outer")
    return pri[["team", "season"] + PRIORS]


# ----------------------------------------------------------------------------------------------- build
def build(raw: dict) -> pd.DataFrame:
    if "drives" not in raw:
        raw = dict(raw)
        raw["drives"] = list(raw.get("drives_regular", [])) + list(raw.get("drives_postseason", []))
    games = _games(raw)
    stats = _stats(raw, games)
    fr = _frame(games, stats)
    fr = _inseason(fr)
    pri = _priors(raw)
    fr = fr.merge(pri, on=["team", "season"], how="left")
    feats = fr[["game_id", "team"] + INSEASON + PRIORS]

    out = pd.DataFrame({
        "game_id": games["game_id"].values,
        "season": games["season"].values,
        "date": games["date"].values,
        "cutoff_utc": games["start_utc"].values,
        "home_team": games["home_team"].values,
        "away_team": games["away_team"].values,
        "neutral": games["neutralSite"].map(lambda v: 1.0 if v is True else 0.0).values,
        "conference_game": games["conferenceGame"].map(lambda v: 1.0 if v is True else 0.0).values,
        "postseason": (games["seasonType"] != "regular").astype(float).values,
    })
    out["cutoff_utc"] = pd.to_datetime(out["cutoff_utc"], utc=True)
    margin = games["homePoints"].values - games["awayPoints"].values
    out["y_home_margin"] = margin
    out["y_total"] = games["homePoints"].values + games["awayPoints"].values
    out["y_home_win"] = (margin > 0).astype(float)

    for side, col in (("home", "home_team"), ("away", "away_team")):
        f = feats.rename(columns={"team": col, **{c: f"{side}_{c}" for c in INSEASON + PRIORS}})
        out = out.merge(f, on=["game_id", col], how="left")

    s = out["season"]
    out["split"] = np.where(s <= 2019, "train", np.where(s <= 2021, "validate", "test"))
    out = out.sort_values(["date", "game_id"], kind="stable").reset_index(drop=True)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cfb", required=True, help="CFBD research cache directory (contains <season>/ folders)")
    ap.add_argument("--out", required=True, help="output parquet path")
    a = ap.parse_args(argv)
    t0 = time.time()
    df = build(load_raw(a.cfb))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    df.to_parquet(a.out, index=False)
    print(f"rows={len(df)} cols={df.shape[1]} seconds={time.time() - t0:.1f} -> {a.out}")


if __name__ == "__main__":
    main()
