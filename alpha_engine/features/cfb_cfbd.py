"""CFB point-in-time team features from the owner's CFBD research cache (cfb-edge-finder branch `research-data`,
data/research_cache/v2/<season>/*.json.gz, 2014-2025) -- RESEARCH_ONLY. Derived outputs only; no raw row is committed.

Used: games (schedule, results, venue, neutral site), advanced box WITHOUT garbage time (regular season), drives, transfer portal,
returning production, recruiting team points, 247 talent composite. NOT used (by design): betting lines (`lines_*`, market data),
end-of-season ratings and season totals (`ratings_sp`, `season_advanced`: they contain the future), polls, provider pregame Elo.

Every in-season value for a game on date D uses team-games dated STRICTLY BEFORE D:
  adj_epa_o_pre / adj_epa_d_pre / adj_epa_net_pre  opponent-adjusted EPA (PPA) per play, the CBB alternating-least-squares model
        (features/cbb_box._ratings) over the previous 400 days, weight 0.5 ** (age_days / 120), with a joint home-field term
  hfa_epa_pre   that home-field term (EPA/play)
  sr_o_pre, sr_d_pre, expl_o_pre, expl_d_pre, pass_ppa_o_pre, rush_ppa_o_pre, pass_ppa_d_pre, rush_ppa_d_pre, line_yds_o_pre,
  stuff_o_pre   play-weighted window means (same weights)
  ppd_o_pre, ppd_d_pre, start_ytg_o_pre   points per drive (TD 7, FG 3) for/against and mean start yards-to-goal
  n_pre         weighted games in the window
Season priors (published before the season): talent, returning PPA share and usage, recruiting points (mean of the season and
the 3 earlier classes), transfer-portal entries in/out with transferDate before Aug 1 of the season and the mean stars in minus out.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import cbb_box as CB

HL_DAYS = 120.0
WINDOW_DAYS = 400
FIRST, LAST = 2014, 2025


def _load(d: Path, name: str) -> list:
    p = d / f"{name}.json.gz"
    if not p.exists():
        return []
    x = json.load(gzip.open(p))
    return x if isinstance(x, list) else x.get("data", [])


def load_raw(cache: Path) -> dict:
    cache = Path(cache); out = {k: [] for k in ("games", "adv", "drives", "portal", "ret", "talent", "recruit")}
    for s in range(FIRST, LAST + 1):
        d = cache / str(s)
        out["games"] += _load(d, "games")
        out["adv"] += [dict(r, _season_type="regular") for r in _load(d, "advanced_regular_nogarbage")]
        out["drives"] += _load(d, "drives_regular") + _load(d, "drives_postseason")
        out["portal"] += _load(d, "portal"); out["ret"] += _load(d, "returning_production")
        out["talent"] += _load(d, "talent"); out["recruit"] += _load(d, "recruiting_teams")
    return out


def games_table(raw: dict) -> pd.DataFrame:
    g = pd.DataFrame(raw["games"]).drop_duplicates("id")
    g = g[g.completed.fillna(False) & g.homePoints.notna() & g.awayPoints.notna()]
    g = g[(g.homeClassification == "fbs") | (g.awayClassification == "fbs")]
    g["start_utc"] = pd.to_datetime(g.startDate, utc=True, errors="coerce")
    g["date"] = g.start_utc.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    return g[["id", "season", "week", "seasonType", "start_utc", "date", "neutralSite", "conferenceGame", "homeTeam", "awayTeam", "homeConference", "awayConference",
              "homeClassification", "awayClassification", "homePoints", "awayPoints", "venueId"]].rename(columns={"id": "game_id"})


def team_games(raw: dict, g: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in raw["adv"]:
        o, d = r.get("offense") or {}, r.get("defense") or {}
        f = lambda b, *k: (lambda v: float(v) if isinstance(v, (int, float)) else np.nan)(_dig(b, k))
        rows.append({"game_id": r["gameId"], "team": r["team"], "opp": r["opponent"], "plays": f(o, "plays"), "d_plays": f(d, "plays"),
                     "ppa_o": f(o, "ppa"), "ppa_d": f(d, "ppa"), "sr_o": f(o, "successRate"), "sr_d": f(d, "successRate"), "expl_o": f(o, "explosiveness"), "expl_d": f(d, "explosiveness"),
                     "pass_ppa_o": f(o, "passingPlays", "ppa"), "rush_ppa_o": f(o, "rushingPlays", "ppa"), "pass_ppa_d": f(d, "passingPlays", "ppa"), "rush_ppa_d": f(d, "rushingPlays", "ppa"),
                     "line_yds_o": f(o, "lineYards"), "stuff_o": f(o, "stuffRate")})
    t = pd.DataFrame(rows).drop_duplicates(["game_id", "team"])
    dr = pd.DataFrame(raw["drives"])
    if not dr.empty:
        dr["pts"] = np.where(dr.driveResult.astype(str).str.contains("TD") & ~dr.driveResult.astype(str).str.contains("DEF|INT TD|FUMBLE TD|PUNT TD"), 7.0,
                             np.where(dr.driveResult.astype(str).eq("FG"), 3.0, 0.0))
        a = dr.groupby(["gameId", "offense"]).agg(drives=("pts", "size"), ppd=("pts", "mean"), start_ytg=("startYardsToGoal", "mean")).reset_index()
        t = t.merge(a.rename(columns={"gameId": "game_id", "offense": "team", "ppd": "ppd_o", "start_ytg": "start_ytg_o"}), on=["game_id", "team"], how="left")
        t = t.merge(a.rename(columns={"gameId": "game_id", "offense": "opp", "ppd": "ppd_d"})[["game_id", "opp", "ppd_d"]], on=["game_id", "opp"], how="left")
    t = t.merge(g[["game_id", "date", "season", "homeTeam", "awayTeam", "neutralSite"]], on="game_id", how="inner")
    t["site"] = np.where(t.neutralSite.fillna(False), 0.0, np.where(t.team == t.homeTeam, 1.0, -1.0))
    return t.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)


def _dig(b, k):
    for x in k:
        if not isinstance(b, dict):
            return None
        b = b.get(x)
    return b


WIN = ["sr_o", "sr_d", "expl_o", "expl_d", "pass_ppa_o", "rush_ppa_o", "pass_ppa_d", "rush_ppa_d", "line_yds_o", "stuff_o", "ppd_o", "ppd_d", "start_ytg_o"]
PRE = ["adj_epa_o_pre", "adj_epa_d_pre", "adj_epa_net_pre", "hfa_epa_pre", "n_pre"] + [c + "_pre" for c in WIN]
PRIOR = ["talent_prior", "ret_ppa_prior", "ret_usage_prior", "recruit_prior", "portal_in_prior", "portal_out_prior", "portal_stars_net_prior"]


def in_season(t: pd.DataFrame, game_dates) -> pd.DataFrame:
    old_hl, old_win = CB.HL_DAYS, CB.WINDOW_DAYS
    CB.HL_DAYS, CB.WINDOW_DAYS = HL_DAYS, WINDOW_DAYS
    try:
        out, prev = [], None
        h_all = t.dropna(subset=["ppa_o"]).assign(team_id=lambda x: x.team, opponent_team_id=lambda x: x.opp, eff_o=lambda x: x.ppa_o)
        for d in sorted(game_dates):
            d = pd.Timestamp(d)
            h = h_all[(h_all.date < d) & (h_all.date >= d - pd.Timedelta(days=WINDOW_DAYS))]
            teams_today = t[t.date == d][["game_id", "team"]]
            if len(h) < 100:
                prev = None; out.append(teams_today.assign(**{c: np.nan for c in PRE})); continue
            lg, hfa, O, D, n = CB._ratings(h, d, prev); prev = {"O": O, "D": D, "hca": hfa}
            w = 0.5 ** ((d - h.date).dt.days.to_numpy(float) / HL_DAYS) * h.plays.fillna(60).to_numpy(float)
            hw = h.assign(_w=w); gw = hw.groupby("team")._w.sum()
            means = {c: (hw[c] * hw._w).groupby(hw.team).sum() / hw[hw[c].notna()].groupby("team")._w.sum() for c in WIN}
            r = teams_today.copy()
            r["adj_epa_o_pre"] = r.team.map(lambda x: lg + O[x] if x in O else np.nan)
            r["adj_epa_d_pre"] = r.team.map(lambda x: lg - D[x] if x in D else np.nan)
            r["adj_epa_net_pre"] = r.adj_epa_o_pre - r.adj_epa_d_pre; r["hfa_epa_pre"] = hfa
            r["n_pre"] = r.team.map(n)
            for c in WIN:
                r[c + "_pre"] = r.team.map(means[c])
            out.append(r)
        return pd.concat(out, ignore_index=True)
    finally:
        CB.HL_DAYS, CB.WINDOW_DAYS = old_hl, old_win


def priors(raw: dict) -> pd.DataFrame:
    tal = pd.DataFrame(raw["talent"]).rename(columns={"year": "season"})[["team", "season", "talent"]] if raw["talent"] else pd.DataFrame(columns=["team", "season", "talent"])
    ret = pd.DataFrame(raw["ret"])[["team", "season", "percentPPA", "usage"]] if raw["ret"] else pd.DataFrame(columns=["team", "season", "percentPPA", "usage"])
    rec = pd.DataFrame(raw["recruit"]).rename(columns={"year": "season"})[["team", "season", "points"]] if raw["recruit"] else pd.DataFrame(columns=["team", "season", "points"])
    seasons = range(FIRST, LAST + 1)
    rr = []
    for s in seasons:
        x = rec[rec.season.between(s - 3, s)].groupby("team").points.mean().rename("recruit_prior").reset_index(); x["season"] = s; rr.append(x)
    rec4 = pd.concat(rr, ignore_index=True)
    po = pd.DataFrame(raw["portal"])
    pp = []
    if not po.empty:
        po["td"] = pd.to_datetime(po.transferDate, utc=True, errors="coerce")
        for s in seasons:
            cut = pd.Timestamp(f"{s}-08-01", tz="UTC"); x = po[(po.season == s) & (po.td < cut)]
            i = x.dropna(subset=["destination"]).groupby("destination").agg(portal_in_prior=("stars", "size"), si=("stars", "mean"))
            o = x.groupby("origin").agg(portal_out_prior=("stars", "size"), so=("stars", "mean"))
            j = i.join(o, how="outer"); j["portal_stars_net_prior"] = j.si.fillna(0) * j.portal_in_prior.fillna(0) - j.so.fillna(0) * j.portal_out_prior.fillna(0)
            j.index.name = "team"; j = j.reset_index(); j["season"] = s
            pp.append(j[["team", "season", "portal_in_prior", "portal_out_prior", "portal_stars_net_prior"]])
    portal = pd.concat(pp, ignore_index=True) if pp else pd.DataFrame(columns=["team", "season"])
    p = tal.rename(columns={"talent": "talent_prior"}).merge(ret.rename(columns={"percentPPA": "ret_ppa_prior", "usage": "ret_usage_prior"}), on=["team", "season"], how="outer")
    return p.merge(rec4, on=["team", "season"], how="outer").merge(portal, on=["team", "season"], how="outer")


def compute(raw: dict) -> dict:
    g = games_table(raw); t = team_games(raw, g)
    # every team of every game gets a row (postseason games too: they receive features even though their own stats are not in the window)
    long = pd.concat([g.assign(team=g.homeTeam, opp=g.awayTeam), g.assign(team=g.awayTeam, opp=g.homeTeam)])[["game_id", "date", "season", "team", "opp"]]
    base = long.merge(t.drop(columns=["date", "season", "opp"]), on=["game_id", "team"], how="left")
    feats = in_season(base, base.date.unique())
    team = base[["game_id", "date", "season", "team", "opp"]].merge(feats, on=["game_id", "team"], how="left").merge(priors(raw), on=["team", "season"], how="left")
    return {"team": team.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True), "games": g}
