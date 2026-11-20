"""NFL player-prop pre-game usage inputs, batch 5 (RESEARCH_ONLY): carry / target / red-zone shares, TD rates, target competition and stat variance, from
nflverse play-by-play only. Player-keyed view for the generic replay harness: compute(raw)["team"] returns rows keyed (game_id, team) where `team` holds the PLAYER
gsis id (as in nfl_rush_ext3); the player's actual team code is in `pteam`.

Source: nflverse play_by_play 2010-2026 and the nflverse schedule (rights: `nflverse`, WRAPPER_LICENCE_UPSTREAM_CAVEAT; internal research only).
Point in time: every value for a game dated d uses only plays of games dated STRICTLY BEFORE d; the row universe is built from PRIOR involvement only.

Common
  History: schedule games (games.csv) with season >= 2010, all game types; played = home_score present. Team codes OAK->LV, SD->LAC, STL->LA (schedule and posteam).
  Output rows only for schedule games with season >= 2011 (played or not); 2010 is warm-up history. Harness wiring: load_raw puts season 2010 in pbp_warm / games_warm
  (history before every replay cut, never truncated or permuted) so that every game in the truncated/permuted tables has output rows.
  Plays: pbp rows of played history games, posteam present, two_point_attempt != 1. Target: play_type == "pass" and receiver_player_id present. Run: play_type == "run"
  and rusher_player_id present. Carry (designed rush): a run with qb_scramble != 1. Goal line: yardline_100 <= 5; red zone: yardline_100 <= 20; passing down: down in {3, 4}.
  Involvement game of player p: a (game, team) in which p has >= 1 target or >= 1 carry. A player's history = his involvement games (any team), ordered (date, game_id).
  Row universe: (game g dated d, team T) -> every player with an involvement game for T among T's 4 most recent PLAYED games dated before d. A player qualifying for both
  teams of g keeps the team whose qualifying involvement game is the latest.
  EWM: over the player's involvement games dated before d, index k = 0 for the most recent, weight 0.5 ** (k / H); games where the per-game value is undefined are skipped
  (numerator and denominator), positions still count (pandas ewm halflife=H, adjust=True, ignore_na=False); NaN if no defined game. H = 4 (shares, aDOT), 8 (TD rates).

nfl.carries      pcr_carry_share_pre, pcr_gl_carry_share_pre, pcr_pd_carry_share_pre: EWM of per-game player carries / team carries (all, goal-line, passing-down).
nfl.targets      ptg_target_share_pre (targets), ptg_air_share_pre (air yards; undefined if team air yards <= 0), ptg_adot_pre = EWM-weighted air yards / EWM-weighted targets with air_yards.
nfl.rz_share     prz_rz_target_share_pre, prz_rz_carry_share_pre: EWM per-game red-zone target / carry shares.
nfl.td_rates     ptd_anytime_rate_pre: EWM of [p scored >= 1 rushing or receiving TD]; ptd_first_td_rate_pre: EWM of [p scored the game's first TD].
nfl.target_competition  ptc_teammate_share_sum_pre, ptc_share_rank_pre, ptc_team_hhi_pre (target-share concentration in the row universe).
nfl.player_stat_variance psv_{rec,rush}_yds_{mean,sd,cv}_pre over the player's last 16 involvement games (min 4), sample SD, CV = SD / mean (NaN if mean <= 0).
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .nfl_ext import TEAM_FIX

S = "NFL"
HIST_FIRST, OUT_FIRST = 2010, 2011
PREV_TEAM_GAMES = 4
HL_SHARE, HL_TD = 4.0, 8.0
VAR_WIN, VAR_MIN = 16, 4
GL_YD, RZ_YD = 5, 20
PBP_COLS = ["game_id", "play_id", "season", "posteam", "play_type", "two_point_attempt", "qb_scramble", "receiver_player_id", "rusher_player_id", "yardline_100", "down",
            "air_yards", "receiving_yards", "rushing_yards", "touchdown", "pass_touchdown", "rush_touchdown"]
CONTENT = ["receiver_player_id", "rusher_player_id", "yardline_100", "down", "air_yards", "receiving_yards", "rushing_yards", "touchdown", "pass_touchdown", "rush_touchdown"]
GAMES_COLS = ["game_id", "season", "week", "game_type", "gameday", "home_team", "away_team", "home_score"]


def load_raw(pbp_dir, games_file) -> dict:
    import pyarrow.parquet as pq
    fs = sorted(glob.glob(str(Path(pbp_dir) / "pbp_*.parquet")))
    pbp = pd.concat([pd.read_parquet(f, columns=[c for c in PBP_COLS if c in pq.read_schema(f).names]) for f in fs], ignore_index=True)
    games = pd.read_csv(games_file, usecols=GAMES_COLS)
    games = games[games.season >= HIST_FIRST]
    warm_ids = set(games.loc[games.season < OUT_FIRST, "game_id"])
    w = pbp.game_id.isin(warm_ids)
    return {"pbp": pbp[~w & pbp.game_id.isin(set(games.game_id))].reset_index(drop=True), "games": games[games.season >= OUT_FIRST].reset_index(drop=True),
            "pbp_warm": pbp[w].reset_index(drop=True), "games_warm": games[games.season < OUT_FIRST].reset_index(drop=True)}


def _norm(s: pd.Series) -> pd.Series:
    return s.astype("object").replace(TEAM_FIX)


def _num(d: pd.DataFrame, c: str) -> pd.Series:
    return pd.to_numeric(d[c], errors="coerce") if c in d else pd.Series(np.nan, index=d.index)


def _all(raw: dict, key: str) -> pd.DataFrame:
    parts = [raw[k] for k in (key + "_warm", key) if k in raw and raw[k] is not None and len(raw[k])]
    return pd.concat(parts, ignore_index=True) if parts else raw[key].iloc[:0]


def _classify(p: pd.DataFrame) -> pd.DataFrame:
    """Adds boolean columns tgt / run / car on a pbp frame (definitions in the module docstring)."""
    two = _num(p, "two_point_attempt").fillna(0.0) == 1
    ok = p["posteam"].notna() & ~two
    pt = p["play_type"].astype("object")
    tgt = ok & (pt == "pass") & p["receiver_player_id"].notna()
    run = ok & (pt == "run") & p["rusher_player_id"].notna()
    car = run & (_num(p, "qb_scramble").fillna(0.0) != 1)
    return p.assign(tgt=tgt.to_numpy(), run=run.to_numpy(), car=car.to_numpy())


def _ewm_state(pg: pd.DataFrame, x: np.ndarray, hl: float) -> np.ndarray:
    """pg sorted by (pid, date, game_id). Returns per row the EWM (adjust=True, ignore_na=False) of x over the player's rows up to and including this one."""
    r = 0.5 ** (1.0 / hl); pid = pg["pid"].to_numpy(); out = np.full(len(pg), np.nan)
    num = den = 0.0; prev = None
    for i in range(len(pg)):
        if pid[i] != prev:
            num = den = 0.0; prev = pid[i]
        num *= r; den *= r
        if not np.isnan(x[i]):
            num += x[i]; den += 1.0
        out[i] = num / den if den > 0 else np.nan
    return out


def _ewm_ratio(pg: pd.DataFrame, a: np.ndarray, b: np.ndarray, hl: float) -> np.ndarray:
    r = 0.5 ** (1.0 / hl); pid = pg["pid"].to_numpy(); out = np.full(len(pg), np.nan)
    num = den = 0.0; prev = None
    for i in range(len(pg)):
        if pid[i] != prev:
            num = den = 0.0; prev = pid[i]
        num = num * r + a[i]; den = den * r + b[i]
        out[i] = num / den if den > 0 else np.nan
    return out


def _window_stats(pg: pd.DataFrame, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per row: mean and sample SD (ddof=1) of x over the player's last VAR_WIN rows up to and including this one; NaN with fewer than VAR_MIN rows. Computed directly
    per window (no running sums), so an all-zero window gives exactly 0."""
    pid = pg["pid"].to_numpy(); m = np.full(len(pg), np.nan); sd = np.full(len(pg), np.nan); start = 0
    for i in range(len(pg)):
        if i == 0 or pid[i] != pid[i - 1]:
            start = i
        w = x[max(start, i - VAR_WIN + 1): i + 1]
        if len(w) >= VAR_MIN:
            m[i] = w.mean(); sd[i] = w.std(ddof=1)
    return m, sd


def _player_games(p: pd.DataFrame, sched: pd.DataFrame) -> pd.DataFrame:
    played = sched[sched.played][["game_id", "date"]].drop_duplicates("game_id")
    q = _classify(p.drop(columns=[c for c in ("season", "date") if c in p])).merge(played, on="game_id", how="inner")
    q["T"] = _norm(q.posteam)
    q = q[q.tgt | q.run].copy()
    q["pid"] = np.where(q.tgt, q.receiver_player_id, q.rusher_player_id)
    yl = _num(q, "yardline_100"); dn = _num(q, "down"); ay = _num(q, "air_yards")
    q["gl"] = q.car & (yl <= GL_YD); q["rzc"] = q.car & (yl <= RZ_YD); q["pd"] = q.car & dn.isin([3, 4])
    q["rzt"] = q.tgt & (yl <= RZ_YD)
    q["has_air"] = q.tgt & ay.notna(); q["air"] = np.where(q.has_air, ay, 0.0)
    q["recy"] = np.where(q.tgt, _num(q, "receiving_yards").fillna(0.0), 0.0)
    q["rushy"] = np.where(q.run, _num(q, "rushing_yards").fillna(0.0), 0.0)
    q["td"] = (q.tgt & (_num(q, "pass_touchdown") == 1)) | (q.run & (_num(q, "rush_touchdown") == 1))
    # the game's first TD: the touchdown == 1 play with the smallest play_id (any play type, any team)
    allp = p[["game_id", "play_id", "touchdown"]].copy(); allp["play_id"] = _num(allp, "play_id")
    ftd = allp[_num(allp, "touchdown") == 1].sort_values(["game_id", "play_id"], kind="mergesort").drop_duplicates("game_id")[["game_id", "play_id"]].rename(columns={"play_id": "ftd_play"})
    q["play_id"] = _num(q, "play_id")
    q = q.merge(ftd, on="game_id", how="left")
    q["ftd"] = q.td & (q.play_id == q.ftd_play)
    flags = ["tgt", "car", "gl", "pd", "rzt", "rzc", "has_air", "td", "ftd"]
    for c in flags:
        q[c] = q[c].astype(float)
    team = q.groupby(["game_id", "T"], sort=True).agg(n_tgt=("tgt", "sum"), n_car=("car", "sum"), n_gl=("gl", "sum"), n_pd=("pd", "sum"), n_rzt=("rzt", "sum"), n_rzc=("rzc", "sum"),
                                                     air_tot=("air", "sum")).reset_index()
    pg = q.groupby(["game_id", "T", "pid"], sort=True).agg(date=("date", "first"), tgt=("tgt", "sum"), car=("car", "sum"), gl=("gl", "sum"), pd=("pd", "sum"), rzt=("rzt", "sum"),
                                                          rzc=("rzc", "sum"), air=("air", "sum"), n_air=("has_air", "sum"), recy=("recy", "sum"), rushy=("rushy", "sum"),
                                                          td=("td", "max"), ftd=("ftd", "max")).reset_index()
    pg = pg[(pg.tgt + pg.car) >= 1].merge(team, on=["game_id", "T"], how="left")
    return pg.sort_values(["pid", "date", "game_id"], kind="mergesort").reset_index(drop=True)


def _shr(a: pd.Series, b: pd.Series) -> np.ndarray:
    b = b.to_numpy(float); a = a.to_numpy(float)
    ok = b > 0
    return np.where(ok, a / np.where(ok, b, 1.0), np.nan)


SHARES = {"pcr_carry_share_pre": ("car", "n_car"), "pcr_gl_carry_share_pre": ("gl", "n_gl"), "pcr_pd_carry_share_pre": ("pd", "n_pd"),
          "ptg_target_share_pre": ("tgt", "n_tgt"), "ptg_air_share_pre": ("air", "air_tot"),
          "prz_rz_target_share_pre": ("rzt", "n_rzt"), "prz_rz_carry_share_pre": ("rzc", "n_rzc")}


def _player_state(pg: pd.DataFrame) -> pd.DataFrame:
    """Per involvement game: every input's value AFTER including that game (the state a later row reads)."""
    st = pg[["pid", "date", "game_id", "T"]].copy()
    for col, (a, b) in SHARES.items():
        st[col] = _ewm_state(pg, _shr(pg[a], pg[b]), HL_SHARE)
    st["ptg_adot_pre"] = _ewm_ratio(pg, pg["air"].to_numpy(float), pg["n_air"].to_numpy(float), HL_SHARE)
    st["ptd_anytime_rate_pre"] = _ewm_state(pg, pg["td"].to_numpy(float), HL_TD)
    st["ptd_first_td_rate_pre"] = _ewm_state(pg, pg["ftd"].to_numpy(float), HL_TD)
    for src, nm in (("recy", "rec"), ("rushy", "rush")):
        m, sd = _window_stats(pg, pg[src].to_numpy(float))
        st[f"psv_{nm}_yds_mean_pre"] = m; st[f"psv_{nm}_yds_sd_pre"] = sd
        st[f"psv_{nm}_yds_cv_pre"] = np.where(m > 0, sd / np.where(m > 0, m, 1.0), np.nan)
    return st


def _schedule(raw: dict) -> pd.DataFrame:
    g = _all(raw, "games")
    g = g[g.season >= HIST_FIRST].drop_duplicates("game_id").copy()
    g["date"] = pd.to_datetime(g.gameday); g["played"] = g.home_score.notna()
    rows = [g.assign(team=_norm(g[a]), opp=_norm(g[b]))[["game_id", "season", "week", "game_type", "team", "opp", "date", "played"]] for a, b in (("home_team", "away_team"), ("away_team", "home_team"))]
    return pd.concat(rows, ignore_index=True).sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)


def _universe(tr: pd.DataFrame, pg: pd.DataFrame) -> pd.DataFrame:
    out_rows = tr[tr.season >= OUT_FIRST]
    pl = tr[tr.played].sort_values(["team", "date", "game_id"], kind="mergesort")
    prev = []
    for t, rows in out_rows.groupby("team", sort=True):
        h = pl[pl.team == t]; hd = h.date.to_numpy(); hg = h.game_id.to_numpy()
        n = np.searchsorted(hd, rows.date.to_numpy(), side="left")
        for o in range(1, PREV_TEAM_GAMES + 1):
            k = n - o; ok = k >= 0
            prev.append(pd.DataFrame({"game_id": rows.game_id.to_numpy()[ok], "pteam": t, "prev_gid": hg[k[ok]]}))
    pv = pd.concat(prev, ignore_index=True) if prev else pd.DataFrame(columns=["game_id", "pteam", "prev_gid"])
    inv = pg[["game_id", "T", "pid", "date"]].rename(columns={"game_id": "prev_gid", "T": "pteam", "date": "prev_date"})
    u = pv.merge(inv, on=["prev_gid", "pteam"], how="inner")
    u = u.groupby(["game_id", "pteam", "pid"], sort=True).prev_date.max().reset_index()
    u = u.sort_values(["game_id", "pid", "prev_date", "pteam"], ascending=[True, True, False, True], kind="mergesort").drop_duplicates(["game_id", "pid"])
    return u.drop(columns="prev_date").merge(out_rows[["game_id", "team", "opp", "season", "week", "date"]].rename(columns={"team": "pteam"}), on=["game_id", "pteam"], how="left")


VAL_COLS = list(SHARES) + ["ptg_adot_pre", "ptd_anytime_rate_pre", "ptd_first_td_rate_pre"] + [f"psv_{n}_yds_{s}_pre" for n in ("rec", "rush") for s in ("mean", "sd", "cv")]
PCR_COLS = ["pcr_carry_share_pre", "pcr_gl_carry_share_pre", "pcr_pd_carry_share_pre"]
PTG_COLS = ["ptg_target_share_pre", "ptg_air_share_pre", "ptg_adot_pre"]
PRZ_COLS = ["prz_rz_target_share_pre", "prz_rz_carry_share_pre"]
PTD_COLS = ["ptd_anytime_rate_pre", "ptd_first_td_rate_pre"]
PTC_COLS = ["ptc_teammate_share_sum_pre", "ptc_share_rank_pre", "ptc_team_hhi_pre"]
PSV_COLS = [f"psv_{n}_yds_{s}_pre" for n in ("rec", "rush") for s in ("mean", "sd", "cv")]


def compute(raw: dict) -> dict:
    tr = _schedule(raw)
    p = _all(raw, "pbp")
    pg = _player_games(p, tr)
    st = _player_state(pg)
    u = _universe(tr, pg)
    # state after the player's last involvement game dated strictly before the row date
    left = u.sort_values(["date", "game_id", "pid"], kind="mergesort").reset_index(drop=True)
    right = st.drop(columns=["game_id", "T"]).sort_values(["date", "pid"], kind="mergesort").reset_index(drop=True)
    f = pd.merge_asof(left, right, on="date", by="pid", allow_exact_matches=False, direction="backward")
    s = f["ptg_target_share_pre"].fillna(0.0)
    tot = s.groupby([f.game_id, f.pteam]).transform("sum"); sq = (s ** 2).groupby([f.game_id, f.pteam]).transform("sum")
    f["ptc_teammate_share_sum_pre"] = tot - s
    f["ptc_share_rank_pre"] = s.groupby([f.game_id, f.pteam]).rank(method="min", ascending=False).astype(float)
    f["ptc_team_hhi_pre"] = np.where(tot > 0, sq / np.where(tot > 0, tot, 1.0) ** 2, np.nan)
    f = f.rename(columns={"pid": "team"})
    cols = ["game_id", "team", "pteam", "opp", "season", "week", "date"] + PCR_COLS + PTG_COLS + PRZ_COLS + PTD_COLS + PTC_COLS + PSV_COLS
    f = f[cols]
    for c in PCR_COLS + PTG_COLS + PRZ_COLS + PTD_COLS + PTC_COLS + PSV_COLS:
        f[c] = f[c].astype("float64")
    return {"team": f.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


def perturb(raw: dict, block_ids, seed: int) -> dict:
    """Role-preserving perturbation used by every replay scramble (truncation-perturbation, own-game, non-vacuity). The (game, player) row universe is defined by WHO
    was involved (>= 1 target or carry) for each team in each game, so that per-(game, team) SET must stay fixed. Within each (game, posteam) of the block, the player id
    is permuted across that team's pooled target + carry plays (receiver_player_id on targets, rusher_player_id on carries): the multiset of ids over the pool is kept, so every
    involved player keeps >= 1 involvement, while who got which target / carry (and so every count, share, yardage, air yards, TD and first-TD credit) changes."""
    o = dict(raw); p = _classify(raw["pbp"].copy()); rng = np.random.default_rng(seed)
    m = (p.tgt | p.car).to_numpy() & p["game_id"].isin(block_ids).to_numpy()
    ix = np.flatnonzero(m)
    if len(ix):
        pid = np.where(p.tgt.to_numpy(), p["receiver_player_id"].to_numpy(dtype=object), p["rusher_player_id"].to_numpy(dtype=object))
        key = (p["game_id"].astype(str) + "|" + _norm(p["posteam"]).astype(str)).to_numpy()[ix]
        codes = pd.factorize(key)[0]
        a = ix[np.lexsort((ix, codes))]                     # grouped, original order
        b = ix[np.lexsort((rng.random(len(ix)), codes))]    # grouped, random order
        newpid = pid.copy(); newpid[a] = pid[b]
        rec = p["receiver_player_id"].to_numpy(dtype=object, copy=True); rus = p["rusher_player_id"].to_numpy(dtype=object, copy=True)
        tg = p.tgt.to_numpy() & m; cr = p.car.to_numpy() & m
        rec[tg] = newpid[tg]; rus[cr] = newpid[cr]
        p["receiver_player_id"] = rec; p["rusher_player_id"] = rus
    o["pbp"] = p.drop(columns=["tgt", "run", "car"])
    return o


perturb_nv = perturb


MISSING = ["injury / practice status and inactives (nfl.injuries_weekly not used)", "snap counts and snap share", "routes run / TPRR / FTN charting", "participation (personnel, routes)",
           "depth chart and roster moves (a traded or released player stays in the universe of his old team for up to 4 team games)", "opponent adjustment"]


def specs() -> list[FeatureSpec]:
    raw = ["nflverse play_by_play (play_type, receiver/rusher ids, yardline_100, down, air_yards, yards, TD flags)", "nflverse schedule"]
    return [
        FeatureSpec(S, "nfl.carries", "team", PCR_COLS, "PARTIAL",
                    "EWM (half-life 4 involvement games) of the player's per-game share of team designed carries, of goal-line (yardline_100 <= 5) carries and of 3rd/4th-down carries",
                    ["carry share", "goal-line carry share", "passing-down (3rd/4th down) carry share"], MISSING + ["early-down split", "carry share conditioned on game script"], raw),
        FeatureSpec(S, "nfl.targets", "team", PTG_COLS, "PARTIAL",
                    "EWM (half-life 4 involvement games) of the player's per-game target share and air-yards share; aDOT = EWM-weighted air yards / EWM-weighted targets with air yards",
                    ["target share", "air-yards share", "aDOT"], MISSING + ["TPRR (needs routes)"], raw),
        FeatureSpec(S, "nfl.rz_share", "team", PRZ_COLS, "PARTIAL",
                    "EWM (half-life 4 involvement games) of the player's per-game red-zone (yardline_100 <= 20) target share and carry share",
                    ["red-zone target share", "red-zone carry share"], MISSING + ["end-zone targets", "inside-10 split (goal-line carries are in nfl.carries)"], raw),
        FeatureSpec(S, "nfl.td_rates", "team", PTD_COLS, "PROXY",
                    "EWM (half-life 8 involvement games) of [player scored >= 1 rushing or receiving TD] and of [player scored the game's first TD]; raw rates, not regressed to a role mean",
                    ["anytime TD game rate", "first-TD-of-game rate"], MISSING + ["role-mean shrinkage", "team TD expectation"], raw),
        FeatureSpec(S, "nfl.target_competition", "team", PTC_COLS, "PROXY",
                    "Within the (game, team) row universe: sum of teammates' ptg_target_share_pre, the player's rank by target share (1 = highest, ties min), and the HHI of target shares",
                    ["teammate target-share sum", "rank within team", "target-share concentration (HHI)"], MISSING + ["teammate availability for the game", "teammate quality beyond share"], raw),
        FeatureSpec(S, "nfl.player_stat_variance", "team", PSV_COLS, "PARTIAL",
                    "Over the player's last 16 involvement games (min 4): mean, sample SD and CV (SD/mean) of receiving yards and of rushing yards",
                    ["game-to-game SD and CV of receiving and rushing yards", "window mean"], MISSING + ["receptions / carries count dispersion", "distribution shape beyond SD (skew, tails)"], raw),
    ]
