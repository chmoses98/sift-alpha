"""MLB pitch-event extension builders (RESEARCH_ONLY): team-game EWMA (half-life 15 games, >=5 prior games) of pitch-level rates from the public Stats API game feed, strictly earlier games only.

Raw: one row per pitch (mlb_pitch_collect.py). 'pitching' columns describe the team's staff when fielding; 'batting' columns describe its hitters. Every input is PARTIAL because the catalog definitions are
pitcher-/batter-/handedness-level or modelled, while this builder is TEAM level without shrinkage models; each spec lists what is missing. Tracking-derived columns (speed, spin, launch speed, zone) are MEASURED
by the league's tracking system and stored in the feed after the game: they enter only from games dated strictly before the one being featured. Pitches with missing tracking are excluded from tracking rates,
never imputed. The first pitch rows of a game are never used for that same game.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .core import FeatureSpec, prior_ewm

S = "MLB"
HL = 15.0
FB, BRK, OFF = {"FF", "FT", "SI", "FA", "FC"}, {"SL", "CU", "KC", "SV", "ST", "CS", "GY", "KN"}, {"CH", "FS", "FO", "SC", "EP"}
SWING, WHIFF = {"S", "W", "T", "M", "F", "L", "X", "D", "E", "O", "Q"}, {"S", "W", "T", "M", "Q"}
CONTENT = ["ab", "pitcher", "batter", "type", "call", "balls", "strikes", "speed", "zone", "ev", "la", "dist", "result", "last_pitch_of_pa", "in_play"]


def load_raw(pitch_dir, schedule_file) -> dict:
    import glob
    from pathlib import Path
    pit = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(Path(pitch_dir) / "pitches_*.parquet")))], ignore_index=True)
    pit = pit.rename(columns={"game_pk": "game_id"})
    g = pd.read_csv(schedule_file, usecols=["game_pk", "date", "season", "home_id", "away_id", "home_score"]).rename(columns={"game_pk": "game_id"})
    yrs = g.loc[g.game_id.isin(set(pit.game_id)), "season"].unique()
    return {"pitches": pit, "games": g[g.season.isin(yrs)]}


def _games(g: pd.DataFrame) -> pd.DataFrame:
    g = g[g.home_score.notna()].copy(); g["date"] = pd.to_datetime(g["date"])
    rows = [g.assign(team=g[a].astype(int), opp=g[b].astype(int))[["game_id", "season", "team", "opp", "date"]] for a, b in (("home_id", "away_id"), ("away_id", "home_id"))]
    t = pd.concat(rows, ignore_index=True).sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    t["week"] = 0
    return t


def _rates(p: pd.DataFrame, g: pd.DataFrame, side: str) -> pd.DataFrame:
    """Per (game, team) pitch-level aggregates; side='pit' groups by the FIELDING team, 'bat' by the BATTING team."""
    p = p.merge(g[["game_id", "home_id", "away_id"]].drop_duplicates("game_id"), on="game_id", how="inner")
    top = p["top"].astype(bool); bat = np.where(top, p.away_id, p.home_id); fld = np.where(top, p.home_id, p.away_id)
    p["team"] = (fld if side == "pit" else bat).astype(int)
    call = p["call"].astype(str); typ = p["type"].astype(str)
    p["fb"] = typ.isin(FB); p["brk"] = typ.isin(BRK); p["off"] = typ.isin(OFF); p["known"] = p.fb | p.brk | p.off
    p["swing"] = call.isin(SWING); p["whiff"] = call.isin(WHIFF); p["called"] = call.eq("C")
    zone = pd.to_numeric(p.zone, errors="coerce"); p["inzone"] = zone.between(1, 9); p["outzone"] = zone >= 11; p["zone_known"] = zone.notna()
    sp = pd.to_numeric(p.speed, errors="coerce"); ev = pd.to_numeric(p.ev, errors="coerce"); la = pd.to_numeric(p.la, errors="coerce")
    p["sp"] = sp; p["fb_sp"] = sp.where(p.fb)
    bip = ev.notna()
    p["hard"] = (ev >= 95).where(bip); p["ev_"] = ev; p["la_"] = la.where(bip)
    first = (pd.to_numeric(p.balls, errors="coerce") + pd.to_numeric(p.strikes, errors="coerce") == 1) & (p.groupby(["game_id", "ab"]).cumcount() == 0)
    p["first_pitch"] = p.groupby(["game_id", "ab"]).cumcount() == 0; p["first_strike"] = p.first_pitch & call.isin({"C", "S", "W", "F", "T", "L", "M", "X", "D", "E", "O", "Q"})
    pa = p.groupby(["game_id", "team", "ab"]).size().rename("pa_pitches").reset_index()
    ab_last = p[p.last_pitch_of_pa.astype(bool)]
    two = p.assign(two=(pd.to_numeric(p.strikes, errors="coerce") == 2)).groupby(["game_id", "team", "ab"]).two.any().rename("reached2").reset_index()
    k = ab_last.assign(k=ab_last.result.astype(str).str.startswith("strikeout")).groupby(["game_id", "team", "ab"]).k.max().rename("k").reset_index()
    pk = two.merge(k, on=["game_id", "team", "ab"], how="left"); pk = pk[pk.reached2]
    G = p.groupby(["game_id", "team"]); o = pd.DataFrame({"n": G.size()})
    d = lambda name, num, den: o.__setitem__(name, num / den.where(den > 0))
    fbn = G["fb"].sum(); kn = G["known"].sum(); sw = G["swing"].sum()
    d("fb_share", fbn, kn); d("brk_share", G["brk"].sum(), kn); d("off_share", G["off"].sum(), kn)
    o["velo_fb"] = G["fb_sp"].mean(); o["max_speed"] = G["sp"].max()
    d("whiff", G["whiff"].sum(), sw); d("csw", G["whiff"].sum() + G["called"].sum(), o["n"])
    z = p[p.zone_known]; Gz = z.groupby(["game_id", "team"])
    o["swing_out"] = Gz.apply(lambda x: x.loc[x.outzone, "swing"].mean() if x.outzone.any() else np.nan, include_groups=False)
    o["swing_in"] = Gz.apply(lambda x: x.loc[x.inzone, "swing"].mean() if x.inzone.any() else np.nan, include_groups=False)
    o["whiff_fb"] = p[p.fb & p.swing].groupby(["game_id", "team"]).whiff.mean(); o["whiff_brk"] = p[p.brk & p.swing].groupby(["game_id", "team"]).whiff.mean()
    o["pitches_pa"] = pa.groupby(["game_id", "team"]).pa_pitches.mean()
    o["first_strike"] = p[p.first_pitch].groupby(["game_id", "team"]).first_strike.mean()
    o["putaway"] = pk.groupby(["game_id", "team"]).k.mean(); o["hard_hit"] = p.groupby(["game_id", "team"]).hard.mean(); o["ev_mean"] = G["ev_"].mean(); o["la_mean"] = G["la_"].mean()
    return o.reset_index()


def compute(raw: dict) -> dict:
    tg = _games(raw["games"]); p = raw["pitches"]
    pit = _rates(p, raw["games"], "pit").drop(columns="n"); bat = _rates(p, raw["games"], "bat").drop(columns="n")
    t = tg.merge(pit.add_prefix("p_").rename(columns={"p_game_id": "game_id", "p_team": "team"}), on=["game_id", "team"], how="left").merge(bat.add_prefix("b_").rename(columns={"b_game_id": "game_id", "b_team": "team"}), on=["game_id", "team"], how="left")
    t = t.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    cols = [c for c in t.columns if c.startswith(("p_", "b_"))]; out = t[["game_id", "season", "week", "team", "opp", "date"]].copy()
    for c in cols:
        out[c + "_pre"] = prior_ewm(t, "team", c, hl=HL, min_periods=5)
    return {"team": out}


def specs() -> list[FeatureSpec]:
    def F(cid, cols, d, done, miss):
        return FeatureSpec(S, cid, "team", cols, "PARTIAL", d, done, miss, ["MLB Stats API game feed (pitch events)", "owner schedule archive"], "pregame_rolling")
    tl = "pitcher- and batter-level splits (team level only)"; sh = "shrinkage toward league / small-sample model"
    return [
        F("mlb.pitch_mix", ["p_fb_share_pre", "p_brk_share_pre", "p_off_share_pre", "p_velo_fb_pre"], "EWMA (half-life 15 games, >=5 prior) of the staff's fastball / breaking / offspeed share and mean fastball speed", ["pitch-type shares", "fastball velocity"], [tl, sh, "whiff and chase rates by type (see pitch_type_whiff)"]),
        F("mlb.pitch_type_whiff", ["p_whiff_pre", "p_csw_pre"], "EWMA staff whiff rate per swing and called+swinging-strike rate per pitch", ["whiff", "CSW"], ["split by pitch type and batter hand", tl, sh]),
        F("mlb.lineup_whiff_by_pitch", ["b_whiff_fb_pre", "b_whiff_brk_pre"], "EWMA of the team's hitters' whiff rate per swing against fastballs and against breaking pitches", ["whiff vs fastball / breaking"], ["confirmed-lineup weighting", "batter hand split", sh]),
        F("mlb.velo_trend", ["p_velo_fb_pre", "p_max_speed_pre"], "EWMA staff fastball speed and EWMA of the game's maximum pitch speed", ["velocity level"], ["spin and movement", "trend over recent starts (slope)", tl]),
        F("mlb.opp_pitches_per_pa", ["b_pitches_pa_pre", "b_swing_in_pre", "b_swing_out_pre"], "EWMA of the team's pitches seen per plate appearance and its swing rate on in-zone / out-of-zone pitches", ["pitches per PA", "zone and chase swing rates"], ["foul-ball rate", "confirmed lineup weighting"]),
        F("mlb.sp_two_strike_putaway", ["p_putaway_pre", "p_first_strike_pre"], "EWMA staff strikeout rate in plate appearances that reached two strikes, and first-pitch strike rate", ["two-strike putaway", "first-pitch strike"], ["pitcher-level model", "P(reach 2 strikes) decomposition by pitch type"]),
        F("mlb.batted_ball_outcome_model", ["b_hard_hit_pre", "b_ev_mean_pre", "b_la_mean_pre"], "EWMA hard-hit share (launch speed >= 95 mph), mean launch speed and mean launch angle of the team's tracked batted balls", ["exit-velocity and angle profile"], ["P(1B,2B,3B,HR | speed, angle) model", "park and spray context"]),
        F("mlb.max_velocity_extreme_distribution", ["p_max_speed_pre"], "EWMA of each game's maximum pitch speed thrown by the staff", ["max speed level"], ["extreme-value distribution fit", "pitcher level"]),
    ]
