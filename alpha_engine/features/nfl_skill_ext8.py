"""NFL batch 8, skill-position availability (RESEARCH_ONLY): usage vacated by WR / TE / RB players listed Out or Doubtful on the final weekly injury report published
BEFORE kickoff. nflverse injuries + play-by-play + schedule only; no line or price.

Point in time (same rule as the certified nfl.injuries_pit builder, alpha_engine.features.nfl_ext): an injury row is used only if its date_modified <= kickoff (kickoff =
gameday + gametime in America/New_York; a missing gametime is taken as 09:00, the earliest slot, so doubt can only exclude a row). The file keeps only the LAST status of each
player-week; 2025-2026 files have no date_modified, so those team-games are missing (never assumed). Usage shares come from games dated strictly before the game.

DEFINITIONS
  Games: schedule rows with home_score present, season >= 2010, codes OAK->LV, SD->LAC, STL->LA (schedule, pbp posteam, injury team). Rows: team-games with season >= OUT_FIRST.
  Plays (as nfl_player_ext5): posteam present, two_point_attempt != 1; target = play_type "pass" with receiver_player_id; carry = play_type "run" with rusher_player_id and qb_scramble != 1;
  red-zone target: target with yardline_100 <= 20; air = air_yards of targets (missing -> 0).
  Per player-game (game, team, player with >= 1 target or carry): shares of the team-game totals: target, air (undefined if team air <= 0), red-zone target (undefined if team has none),
  carry (undefined if team has none). Player EWM: over his involvement games (any team) ordered (date, game_id), half-life 4, pandas ewm(adjust=True, ignore_na=False) semantics
  (undefined games skipped but keep their position); a row reads the value after his last involvement game dated before d (missing -> 0 contribution).
  Listed: injury rows of the team-game (season, week, team) with report_status in {Out, Doubtful}, position in {WR, TE, RB, FB}, date_modified <= kickoff.
  usable(team-game) = at least one injury row of any status with date_modified <= kickoff; otherwise every column is missing.
nfl.skill_avail  ska_vac_target_share_pre, ska_vac_air_share_pre, ska_vac_rz_target_share_pre, ska_vac_carry_share_pre = sums over listed players of their EWM shares;
                 ska_n_listed_pre = number of listed players.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .nfl_ext import TEAM_FIX

S = "NFL"
HIST_FIRST, OUT_FIRST = 2010, 2013
HL = 4.0
OUT_STATUS = {"Out", "Doubtful"}
SKILL = {"WR", "TE", "RB", "FB"}
PBP_COLS = ["game_id", "posteam", "play_type", "two_point_attempt", "qb_scramble", "receiver_player_id", "rusher_player_id", "yardline_100", "air_yards"]
CONTENT = ["receiver_player_id", "rusher_player_id", "yardline_100", "air_yards"]
INJ_CONTENT = ["gsis_id", "report_status", "date_modified"]
GAMES_COLS = ["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team", "away_team", "home_score"]


def _fix(s):
    return s.astype("object").replace(TEAM_FIX)


def load_raw(pbp_dir, games_file, inj_dir) -> dict:
    fs = sorted(glob.glob(str(Path(pbp_dir) / "play_by_play_*.parquet"))) or sorted(glob.glob(str(Path(pbp_dir) / "pbp_*.parquet")))
    pbp = pd.concat([pd.read_parquet(f, columns=PBP_COLS) for f in fs], ignore_index=True)
    g = pd.read_csv(games_file, usecols=GAMES_COLS)
    g = g[(g.season >= HIST_FIRST) & g.home_score.notna()].drop_duplicates("game_id")
    pbp = pbp[pbp.game_id.isin(set(g.game_id))]
    inj = []
    for f in sorted(glob.glob(str(Path(inj_dir) / "injuries_*.parquet"))):
        d = pd.read_parquet(f)
        inj.append(d.reindex(columns=["season", "game_type", "team", "week", "gsis_id", "position", "report_status", "date_modified"]))
    inj = pd.concat(inj, ignore_index=True)
    inj["team"] = _fix(inj.team.astype(str)); inj["date_modified"] = inj.date_modified.astype(str).where(inj.date_modified.notna(), None)
    slots = pd.concat([g.assign(team=_fix(g[a]))[["game_id", "season", "week", "team"]] for a in ("home_team", "away_team")], ignore_index=True)
    inj = inj.merge(slots, on=["season", "week", "team"], how="inner")          # injury rows carry the game id of their team-game (harness truncates / permutes by game)
    warm = set(g.game_id[g.season < OUT_FIRST])
    return {"pbp": pbp[~pbp.game_id.isin(warm)].reset_index(drop=True), "games": g[g.season >= OUT_FIRST].reset_index(drop=True), "injuries": inj[~inj.game_id.isin(warm)].reset_index(drop=True),
            "pbp_warm": pbp[pbp.game_id.isin(warm)].reset_index(drop=True), "games_warm": g[g.season < OUT_FIRST].reset_index(drop=True)}


def _all(raw, key):
    parts = [raw[k] for k in (key + "_warm", key) if raw.get(k) is not None and len(raw[k])]
    return pd.concat(parts, ignore_index=True) if parts else raw[key]


def _ewm_after(pg: pd.DataFrame, col: str) -> np.ndarray:
    return pg.groupby("pid", sort=False)[col].transform(lambda s: s.ewm(halflife=HL, adjust=True, ignore_na=False).mean()).to_numpy()


COLS = ["ska_vac_target_share_pre", "ska_vac_air_share_pre", "ska_vac_rz_target_share_pre", "ska_vac_carry_share_pre", "ska_n_listed_pre"]


def compute(raw: dict) -> dict:
    g = _all(raw, "games").drop_duplicates("game_id").copy(); g["date"] = pd.to_datetime(g.gameday)
    t = g.gametime.fillna("09:00").astype(str).str.slice(0, 5)
    g["kickoff"] = pd.to_datetime(g.gameday + " " + t, errors="coerce").dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    g["home_team"] = _fix(g.home_team); g["away_team"] = _fix(g.away_team)
    tg = pd.concat([g.assign(team=g[a])[["game_id", "season", "week", "team", "date", "kickoff"]] for a in ("home_team", "away_team")], ignore_index=True)
    # player usage shares
    p = _all(raw, "pbp").merge(g[["game_id", "date"]], on="game_id", how="inner")
    num = lambda c: pd.to_numeric(p[c], errors="coerce")  # noqa: E731
    ok = p.posteam.notna() & (num("two_point_attempt").fillna(0) != 1)
    pt = p.play_type.astype(object)
    tgt = ok & (pt == "pass") & p.receiver_player_id.notna(); car = ok & (pt == "run") & p.rusher_player_id.notna() & (num("qb_scramble").fillna(0) != 1)
    q = p[tgt | car].copy(); q["tgt"] = tgt[tgt | car].astype(float).to_numpy(); q["car"] = car[tgt | car].astype(float).to_numpy()
    q["T"] = _fix(q.posteam); q["pid"] = np.where(q.tgt == 1, q.receiver_player_id, q.rusher_player_id)
    q["rzt"] = q.tgt * (pd.to_numeric(q.yardline_100, errors="coerce") <= 20).astype(float)
    q["air"] = q.tgt * pd.to_numeric(q.air_yards, errors="coerce").fillna(0.0)
    tm = q.groupby(["game_id", "T"]).agg(n_tgt=("tgt", "sum"), n_car=("car", "sum"), n_rzt=("rzt", "sum"), n_air=("air", "sum")).reset_index()
    pg = q.groupby(["game_id", "T", "pid"]).agg(date=("date", "first"), tgt=("tgt", "sum"), car=("car", "sum"), rzt=("rzt", "sum"), air=("air", "sum")).reset_index().merge(tm, on=["game_id", "T"])
    d = lambda a, b: np.where(pg[b] > 0, pg[a] / pg[b].where(pg[b] > 0), np.nan)  # noqa: E731
    pg["s_tgt"] = d("tgt", "n_tgt"); pg["s_air"] = d("air", "n_air"); pg["s_rzt"] = d("rzt", "n_rzt"); pg["s_car"] = d("car", "n_car")
    pg = pg.sort_values(["pid", "date", "game_id", "T"], kind="mergesort").reset_index(drop=True)
    st = pg[["pid", "date"]].copy()
    for c in ("s_tgt", "s_air", "s_rzt", "s_car"):
        st[c] = _ewm_after(pg, c)
    # injury listings usable before kickoff
    inj = raw["injuries"].merge(tg[["game_id", "team", "kickoff", "date", "season"]], on=["game_id", "team"], how="inner")
    inj["mod"] = pd.to_datetime(inj.date_modified, errors="coerce", utc=True)
    inj = inj[inj["mod"].notna() & (inj["mod"] <= inj["kickoff"])]
    usable = inj.groupby(["game_id", "team"]).size().rename("_u").reset_index()
    lst = inj[inj.report_status.isin(OUT_STATUS) & inj.position.isin(SKILL) & inj.gsis_id.notna()].drop_duplicates(["game_id", "team", "gsis_id"]).rename(columns={"gsis_id": "pid"})
    lst = lst.sort_values("date", kind="mergesort")
    m = pd.merge_asof(lst[["game_id", "team", "date", "pid"]], st.sort_values("date", kind="mergesort"), on="date", by="pid", allow_exact_matches=False, direction="backward")
    agg = m.groupby(["game_id", "team"]).agg(**{"ska_vac_target_share_pre": ("s_tgt", lambda x: x.fillna(0).sum()), "ska_vac_air_share_pre": ("s_air", lambda x: x.fillna(0).sum()),
                                               "ska_vac_rz_target_share_pre": ("s_rzt", lambda x: x.fillna(0).sum()), "ska_vac_carry_share_pre": ("s_car", lambda x: x.fillna(0).sum()),
                                               "ska_n_listed_pre": ("pid", "size")}).reset_index()
    out = tg[tg.season >= OUT_FIRST].merge(usable, on=["game_id", "team"], how="left").merge(agg, on=["game_id", "team"], how="left")
    for c in COLS:
        out[c] = np.where(out._u.notna(), out[c].fillna(0.0), np.nan).astype("float64")
    out = out[["game_id", "team", "season", "date"] + COLS]
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


def specs() -> list[FeatureSpec]:
    return [FeatureSpec(S, "nfl.skill_avail", "team", COLS, "PARTIAL",
                        "Usage vacated by WR/TE/RB players listed Out or Doubtful on the last injury report modified at or before kickoff: the sum of their pre-game EWM (half-life 4 games) target, "
                        "air-yards, red-zone-target and carry shares, and the number listed",
                        ["vacated target share, air yards and red-zone targets of unavailable players (plus carries)"],
                        ["allocation of the vacated usage to teammates (with-or-without splits)", "replacement-quality efficiency adjustment", "opponent coverage update",
                         "Questionable players (probability of playing not modelled)", "intra-week report vintages (only the last status per player-week exists)",
                         "2025-2026 injury files carry no timestamp: those team-games are missing"],
                        ["nflverse injuries (report_status, date_modified)", "nflverse play_by_play 2010-2026", "nflverse schedule"])]


def post_kickoff_mask(raw: dict) -> np.ndarray:
    """Injury rows whose date_modified is AFTER kickoff (or missing) of their team-game: they must never move a feature (used by the replay check pit_check_post_kickoff_injuries)."""
    g = _all(raw, "games").drop_duplicates("game_id")
    t = g.gametime.fillna("09:00").astype(str).str.slice(0, 5)
    ko = pd.Series(pd.to_datetime(g.gameday + " " + t, errors="coerce").dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC").to_numpy(), index=g.game_id.to_numpy())
    inj = raw["injuries"]; mod = pd.to_datetime(inj.date_modified, errors="coerce", utc=True)
    k = pd.to_datetime(inj.game_id.map(ko), utc=True)
    return (~(mod.notna() & (mod <= k))).to_numpy()


def perturb_nv(raw: dict, block_ids, seed: int) -> dict:
    """Non-vacuity perturbation: the block's play content (standard scramble) AND the report_status / gsis_id of the block's injury rows are permuted, so both the usage shares and
    the listing counts of later rows must move."""
    from ..input_research.data_foundation import replay_generic as G
    rng = np.random.default_rng(seed); o = dict(raw)
    o["pbp"] = G._perm(raw["pbp"], raw["pbp"].game_id.isin(block_ids).to_numpy(), CONTENT, rng)
    o["injuries"] = G._perm(raw["injuries"], raw["injuries"].game_id.isin(block_ids).to_numpy(), ["report_status", "gsis_id", "position"], rng)
    return o
