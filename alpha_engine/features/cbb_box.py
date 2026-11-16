"""CBB point-in-time team features from ESPN team box scores (SportsDataverse hoopR-mbb release, as ingested by the owner's
cbb-edge-finder bronze archive) -- RESEARCH_ONLY, internal research use; no rows are committed.

Every value for a game on date D uses team-games dated STRICTLY BEFORE D:
  adj_o_pre / adj_d_pre / adj_net_pre  opponent-adjusted points per 100 possessions (additive model
        eff(team vs opp) = lg + O_team - D_opp + h * site, site = +1 home / -1 away / 0 neutral), solved per date by
        weighted alternating least squares over the previous WINDOW_DAYS days, weight 0.5 ** (age_days / HL_DAYS),
        ridge shrinkage K_SHR possessions-equivalent games toward 0, warm-started from the previous date's solution
  hca_pre      the jointly estimated home-court term h (points per 100 possessions)
  tempo_pre    weighted mean possessions per 40 minutes over the same window
  efg_pre, tov_pre, orb_pre, ftr_pre (offence) and d_efg_pre, d_tov_pre, d_orb_pre, d_ftr_pre (defence): Four Factors,
               possession-weighted means over the same window
  n_pre        weighted game count in the window (information level)
  conf_net_pre mean adj_net_pre of the team's conference members (conference id from the schedule) on that date
Possessions: FGA - OREB + TO + 0.475 * FTA (each side), averaged over both sides of the game.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

WINDOW_DAYS = 400
HL_DAYS = 60.0
K_SHR = 3.0
ITERS = 12
FIRST = 2006


def load_raw(cbb_dir) -> dict:
    d = Path(cbb_dir)
    tb = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(d / "team_box/*.parquet"))) if int(Path(f).stem.split("_")[-1]) >= FIRST], ignore_index=True)
    sc = pd.concat([pd.read_parquet(f, columns=[c for c in ("game_id", "season", "season_type", "date", "start_date", "neutral_site", "conference_competition", "home_id", "away_id",
                                                             "home_conference_id", "away_conference_id", "home_score", "away_score", "status_type_completed")
                                                if c in pd.read_parquet(f).columns]) for f in sorted(glob.glob(str(d / "schedules/*.parquet"))) if int(Path(f).stem.split("_")[-1]) >= FIRST], ignore_index=True)
    return {"team_box": tb, "schedule": sc}


def team_games(raw: dict) -> pd.DataFrame:
    t = raw["team_box"].copy()
    num = ["field_goals_attempted", "field_goals_made", "three_point_field_goals_made", "free_throws_attempted", "offensive_rebounds", "defensive_rebounds", "turnovers", "team_score"]
    for c in num:
        t[c] = pd.to_numeric(t[c], errors="coerce")
    t = t[t.season_type.isin([2, 3])].dropna(subset=num).drop_duplicates(["game_id", "team_id"])
    t["date"] = pd.to_datetime(t.game_date)
    t["poss_own"] = t.field_goals_attempted - t.offensive_rebounds + t.turnovers + 0.475 * t.free_throws_attempted
    o = t[["game_id", "team_id", "poss_own", "field_goals_attempted", "field_goals_made", "three_point_field_goals_made", "free_throws_attempted", "offensive_rebounds", "defensive_rebounds", "turnovers"]]
    o = o.rename(columns={c: "o_" + c for c in o.columns if c not in ("game_id",)}).rename(columns={"o_team_id": "opponent_team_id"})
    t = t.merge(o, on=["game_id", "opponent_team_id"], how="inner")            # both sides required
    t["poss"] = (t.poss_own + t.o_poss_own) / 2
    t = t[t.poss > 40]
    t["pts_for"] = t.team_score; t["pts_against"] = pd.to_numeric(t.opponent_team_score, errors="coerce")
    t["eff_o"] = 100 * t.pts_for / t.poss; t["eff_d"] = 100 * t.pts_against / t.poss
    t["efg"] = (t.field_goals_made + 0.5 * t.three_point_field_goals_made) / t.field_goals_attempted
    t["tov"] = t.turnovers / t.poss_own; t["orb"] = t.offensive_rebounds / (t.offensive_rebounds + t.o_defensive_rebounds)
    t["ftr"] = t.free_throws_attempted / t.field_goals_attempted
    t["d_efg"] = (t.o_field_goals_made + 0.5 * t.o_three_point_field_goals_made) / t.o_field_goals_attempted
    t["d_tov"] = t.o_turnovers / t.o_poss_own; t["d_orb"] = t.o_offensive_rebounds / (t.o_offensive_rebounds + t.defensive_rebounds)
    t["d_ftr"] = t.o_free_throws_attempted / t.o_field_goals_attempted
    sc = raw["schedule"].drop_duplicates("game_id")[["game_id", "neutral_site", "conference_competition", "home_id", "away_id", "home_conference_id", "away_conference_id"]]
    t = t.merge(sc, on="game_id", how="left")
    t["neutral"] = t.neutral_site.fillna(False).astype(bool)
    t["site"] = np.where(t.neutral, 0.0, np.where(t.team_home_away == "home", 1.0, -1.0))
    t["conf_id"] = np.where(t.team_id == t.home_id, t.home_conference_id, np.where(t.team_id == t.away_id, t.away_conference_id, np.nan))
    keep = ["game_id", "season", "season_type", "date", "team_id", "opponent_team_id", "site", "neutral", "conference_competition", "conf_id", "poss", "pts_for", "pts_against",
            "eff_o", "eff_d", "efg", "tov", "orb", "ftr", "d_efg", "d_tov", "d_orb", "d_ftr", "team_home_away"]
    return t[keep].sort_values(["date", "game_id", "team_id"], kind="mergesort").reset_index(drop=True)


def _ratings(h: pd.DataFrame, d: pd.Timestamp, prev: dict | None):
    """Weighted alternating least squares on the window before d. Returns (lg, hca, O, D) as dicts."""
    age = (d - h.date).dt.days.to_numpy(float)
    w = 0.5 ** (age / HL_DAYS)
    ti = h.team_id.to_numpy(); oi = h.opponent_team_id.to_numpy(); y = h.eff_o.to_numpy(float); s = h.site.to_numpy(float)
    teams, inv = np.unique(np.concatenate([ti, oi]), return_inverse=True)
    a, b = inv[: len(ti)], inv[len(ti):]
    m = len(teams)
    O = np.array([prev["O"].get(t, 0.0) for t in teams]) if prev else np.zeros(m)
    D = np.array([prev["D"].get(t, 0.0) for t in teams]) if prev else np.zeros(m)
    lg = float(np.average(y, weights=w)); hca = prev["hca"] if prev else 0.0
    wsum_a = np.bincount(a, weights=w, minlength=m); wsum_b = np.bincount(b, weights=w, minlength=m)
    for _ in range(ITERS):
        r = y - lg - hca * s + D[b]
        O = np.bincount(a, weights=w * r, minlength=m) / (wsum_a + K_SHR)
        r = lg + O[a] + hca * s - y
        D = np.bincount(b, weights=w * r, minlength=m) / (wsum_b + K_SHR)
        res = y - lg - O[a] + D[b]
        nz = s != 0
        hca = float(np.sum((w * s * res)[nz]) / np.sum(w[nz])) if nz.any() else 0.0
        lg = float(np.average(y - O[a] + D[b] - hca * s, weights=w))
    return lg, hca, dict(zip(teams, O)), dict(zip(teams, D)), dict(zip(teams, wsum_a))


FACTORS = ["efg", "tov", "orb", "ftr", "d_efg", "d_tov", "d_orb", "d_ftr"]


def compute(raw: dict, dates: list | None = None) -> dict:
    """dates: optional subset of game dates to evaluate (truncation / verification). Values never depend on rows dated >= the date."""
    t = team_games(raw)
    out = []
    prev = None
    all_dates = sorted(t.date.unique()) if dates is None else sorted(pd.to_datetime(dates))
    for d in all_dates:
        d = pd.Timestamp(d)
        h = t[(t.date < d) & (t.date >= d - pd.Timedelta(days=WINDOW_DAYS))]
        rows = t[t.date == d]
        if rows.empty:
            continue
        if len(h) < 200:
            prev = None
            out.append(rows[["game_id", "team_id"]].assign(**{c: np.nan for c in ["adj_o_pre", "adj_d_pre", "adj_net_pre", "hca_pre", "tempo_pre", "n_pre", "conf_net_pre"] + [f + "_pre" for f in FACTORS]}))
            continue
        lg, hca, O, D, n = _ratings(h, d, prev if dates is None else None)
        prev = {"O": O, "D": D, "hca": hca}
        w = 0.5 ** ((d - h.date).dt.days.to_numpy(float) / HL_DAYS)
        hw = h.assign(_w=w, _wp=w * h.poss)
        g = hw.groupby("team_id")
        tempo = (g._wp.sum() / g._w.sum())
        fac = {f: (hw[f] * hw._wp).groupby(hw.team_id).sum() / g._wp.sum() for f in FACTORS}
        net = {k: O[k] + D[k] for k in O}
        conf = h.dropna(subset=["conf_id"]).drop_duplicates("team_id", keep="last").set_index("team_id").conf_id
        cn = pd.Series({k: v for k, v in net.items() if k in conf.index}).groupby(conf).mean() if len(conf) else pd.Series(dtype=float)
        r = rows[["game_id", "team_id", "conf_id"]].copy()
        r["adj_o_pre"] = r.team_id.map(lambda x: lg + O[x] if x in O else np.nan)
        r["adj_d_pre"] = r.team_id.map(lambda x: lg - D[x] if x in D else np.nan)       # points allowed per 100; lower is better
        r["adj_net_pre"] = r.adj_o_pre - r.adj_d_pre
        r["hca_pre"] = hca
        r["tempo_pre"] = r.team_id.map(tempo)
        r["n_pre"] = r.team_id.map(n)
        for f in FACTORS:
            r[f + "_pre"] = r.team_id.map(fac[f])
        r["conf_net_pre"] = r.conf_id.map(cn)
        out.append(r.drop(columns="conf_id"))
    f = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["game_id", "team_id"])
    return {"team": t.merge(f, on=["game_id", "team_id"], how="inner") if dates is None else t[t.date.isin(all_dates)].merge(f, on=["game_id", "team_id"], how="inner")}


PRE_COLS = ["adj_o_pre", "adj_d_pre", "adj_net_pre", "hca_pre", "tempo_pre", "n_pre", "conf_net_pre"] + [f + "_pre" for f in FACTORS]
