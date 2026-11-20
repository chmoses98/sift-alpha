"""CBB player-prop pre-game inputs, batch 6 (RESEARCH_ONLY): usage and per-40 rates, shooting regression, per-stat count distributions, three-point volume,
compound threes-made distribution, assist creation and rebound pool, from archived ESPN men's college basketball PLAYER box scores only.

Player-keyed view for the generic replay harness (same convention as nfl_player_ext5): compute(raw)["team"] returns rows keyed (game_id, team) where `team` holds the
PLAYER athlete_id (int64); the player's actual team id is in `pteam` and the opponent's in `opp`.

Source: sift-data-vault archives/CBB/espn_player_box_pbp_early_seasons (sportsdataverse espn_mens_college_basketball_player_boxscores, player_box_<season>.parquet).
Rights: ESPN-derived, UNRESOLVED_INTERNAL_ONLY (internal research only). No line, spread or price enters anywhere.

DEFINITIONS (the blind brief restates these; every value for a row dated d uses only box rows of games dated STRICTLY BEFORE d)
  Box rows: season_type in {2, 3}, HIST_FIRST <= season. date = calendar date of game_date. Stats with NaN are 0.
  Appearance: a box row with athlete_id present and minutes > 0. Appearances are ordered per player by (date, game_id) across all seasons and teams.
  Team-game (game_id, team_id): every distinct pair in the box rows; opp = opponent_team_id; team totals = sums over ALL the team's box rows in that game
  (fgm, fga, fg3m, fg3a, ftm, fta, oreb, dreb, reb, ast, tov, min); opp_* = the opponent's totals in the same game. Team-games ordered per team by (date, game_id).
  Role of a player: from athlete_position_abbreviation of his LATEST appearance before d: C -> "C"; F, F-C, PF, SF -> "F"; G, G-F, PG, SG -> "G"; anything else -> "X".
  League priors for season S: from appearances of season S-1 only (so output starts at OUT_FIRST = HIST_FIRST + 1): per-minute rate of a stat by role = sum(stat)/sum(min);
  percentages by role = sum(makes)/sum(attempts); role "X" uses all roles pooled. Team-level league constants of season S likewise from all team-games of S-1.
  Row universe: output rows for every team-game (g, T) with season >= OUT_FIRST: every player with an appearance for T in one of T's last PREV_TEAM_GAMES team-games dated
  before d. A player qualifying for both teams keeps the team of his latest qualifying appearance (ties: lower team id).
  EWM SUM with half-life H over a player's appearances (or a team's team-games) up to and including item i: W_i(x) = sum_{j<=i} r^(i-j) x_j, r = 0.5 ** (1/H).
  A row reads the state after the player's (team's) LAST appearance (team-game) dated strictly before d. EWM mean = W(x) / W(1).

cbb.player_usage        pu_usg_pre = (W(pu) + 0.20*E0)/(W(exp_pu) + E0), pu = fga + 0.44 fta + tov, exp_pu = team_pu * min / (team_min / 5), E0 = 20, H = 10;
                        pu_{pts,reb,ast,fga,fta}40_pre = 40 * (W(stat) + M0 * prior_rate_role) / (W(min) + M0), M0 = 200 minutes, H = 10.
cbb.player_shooting_regression  for s in fg3, fg2 (fgm-fg3m / fga-fg3a), ft: career (all appearances, unweighted) makes C_m and attempts C_a;
                        psr_s_shrunk_pre = (C_m + K_s * pct_role)/(C_a + K_s), K = 100 / 80 / 60; psr_s_luck_pre = (R_m / R_a) - shrunk over the last 10 appearances (NaN if R_a = 0).
cbb.stat_dist           for x in pts, reb, ast, fg3m over the last 15 appearances (min 5): psd_x_mean_pre = mean; phi_raw = max(var - mean, 0)/mean^2 (0 if mean = 0; var ddof = 1);
                        psd_x_phi_pre = n/(n+10) * phi_raw + 10/(n+10) * phi_prior_role, phi_prior_role = mean of phi_raw over players of that role with >= 10 appearances in S-1 (their
                        season mean / variance), all roles pooled for "X". NB size = 1/phi.
cbb.player_three_volume pv_fg3a40_pre (as pu rates, M0 = 200); pv_fg3_rate_pre = (W(fg3a) + 50 * rate_role)/(W(fga) + 50), H = 10; pv_opp_fg3a_rel_pre = opponent O's EWM ratio (H = 10 over
                        O's team-games) W(opp_fg3a)/W(opp_fga) divided by league fg3a/fga of S-1 (NaN if O has no earlier team-game); pv_fg3a_exp_pre = pv_fg3a40_pre * min_ewm / 40 * rel
                        (rel = 1 when NaN), min_ewm = EWM mean of minutes, H = 5.
cbb.three_makes_compound_distribution  attempts N ~ NegBin(mean mu = pv_fg3a_exp_pre, var 1.5 mu) (n = 2 mu, p = 2/3), truncated at N <= NMAX (mass above NMAX dropped; mu = 0 -> N = 0);
                        p ~ Beta(a, b), a = 100 * pct3_role + C3_m, b = 100 * (1 - pct3_role) + C3_a - C3_m; makes | N ~ BetaBinomial(N, a, b).
                        pc_p_ge{1,2,3,4}_pre = sum_{N=0..NMAX} NB(N) * P(makes >= k | N); pc_mean_makes_pre = mu * a / (a + b).
cbb.assist_creation     pa_team_ast_share_pre = W(ast)/W(team_ast); pa_ast_pct_pre = W(ast)/W(team_fgm - fgm) (NaN if denominator 0), H = 10;
                        pa_opp_tov_forced_rel_pre = O's EWM ratio W(opp_tov)/W(opp_pu) (H = 10) / league tov / pu of S-1.
cbb.rebound_pool        live_miss = (fga - fgm) + FT_LIVE * (fta - ftm) per team-game; pr_pool_pre = EWM mean (H = 10) of T's live_miss + EWM mean of O's live_miss;
                        pr_reb_share_pre = W(reb)/W(team_reb + opp_reb) over the player's appearances (H = 10); pr_exp_reb_pre = share * pool * reb_per_miss_lg (S-1 total reb / total live_miss);
                        pr_opp_orb_rate_pre = O's EWM ratio W(oreb)/W(oreb + opp_dreb) (H = 10).
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import betaln, gammaln

from .core import FeatureSpec

S = "CBB"
HIST_FIRST = 2012
OUT_FIRST = HIST_FIRST + 1
PREV_TEAM_GAMES = 5
H_RATE, H_MIN, H_TEAM = 10.0, 5.0, 10.0
M0, E0 = 200.0, 20.0
K_PCT = {"fg3": 100.0, "fg2": 80.0, "ft": 60.0}
RECENT = 10
DIST_WIN, DIST_MIN, DIST_K = 15, 5, 10.0
PHI_MIN_APPS = 10
FG3_RATE_K = 50.0
NB_VAR_RATIO = 1.5
XP_STRENGTH = 100.0
NMAX = 40
FT_LIVE = 0.5
STATS = {"pts": "points", "reb": "rebounds", "oreb": "offensive_rebounds", "dreb": "defensive_rebounds", "ast": "assists", "tov": "turnovers", "fgm": "field_goals_made",
         "fga": "field_goals_attempted", "fg3m": "three_point_field_goals_made", "fg3a": "three_point_field_goals_attempted", "ftm": "free_throws_made", "fta": "free_throws_attempted"}
BOX_COLS = ["game_id", "season", "season_type", "game_date", "athlete_id", "team_id", "opponent_team_id", "minutes", "athlete_position_abbreviation"] + list(STATS.values())
# outcome-bearing columns per game (what the replay truncates and permutes); ids, dates, season type and position are pre-game facts
CONTENT = ["minutes"] + list(STATS.values())
ROLE = {"C": "C", "F": "F", "F-C": "F", "PF": "F", "SF": "F", "G": "G", "G-F": "G", "PG": "G", "SG": "G"}


def load_raw(root) -> dict:
    """root: the directory restored from the vault archive (contains espn_mens_college_basketball_player_boxscores/)."""
    fs = sorted(glob.glob(str(Path(root) / "espn_mens_college_basketball_player_boxscores" / "player_box_*.parquet")))
    fs = [f for f in fs if int(Path(f).stem.rsplit("_", 1)[1]) >= HIST_FIRST]
    b = pd.concat([pd.read_parquet(f, columns=BOX_COLS) for f in fs], ignore_index=True)
    b["game_date"] = pd.to_datetime(b["game_date"].astype(str)).dt.normalize()
    # harness wiring (same as nfl_player_ext5): history-only seasons (< OUT_FIRST) go to box_warm, which precedes every replay cut and is never truncated or permuted
    w = b.season < OUT_FIRST
    return {"box": b[~w].reset_index(drop=True), "box_warm": b[w].reset_index(drop=True)}


def _prep(raw: dict) -> pd.DataFrame:
    b = pd.concat([x for x in (raw.get("box_warm"), raw["box"]) if x is not None and len(x)], ignore_index=True) if raw.get("box_warm") is not None else raw["box"]
    b = b[b.season_type.isin([2, 3]) & (b.season >= HIST_FIRST)].copy()
    out = pd.DataFrame({"game_id": b.game_id.astype("int64").to_numpy(), "season": b.season.astype(int).to_numpy(), "date": pd.to_datetime(b.game_date).dt.normalize().to_numpy(),
                        "pid": b.athlete_id.astype(float).to_numpy(), "T": b.team_id.astype("int64").to_numpy(), "O": b.opponent_team_id.astype("int64").to_numpy(),
                        "min": pd.to_numeric(b.minutes, errors="coerce").to_numpy(float), "pos": b.athlete_position_abbreviation.astype(object).to_numpy()})
    for k, v in STATS.items():
        out[k] = pd.to_numeric(b[v], errors="coerce").fillna(0.0).to_numpy(float)
    out["fg2m"] = out.fgm - out.fg3m; out["fg2a"] = out.fga - out.fg3a
    out["pu"] = out.fga + 0.44 * out.fta + out.tov
    return out


def _team_games(bx: pd.DataFrame) -> pd.DataFrame:
    sums = ["fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "reb", "ast", "tov", "pu"]
    t = bx.assign(min=bx["min"].fillna(0.0)).groupby(["game_id", "T"], sort=True).agg(date=("date", "min"), season=("season", "min"), O=("O", "first"),
                                                                                       **{c: (c, "sum") for c in sums + ["min"]}).reset_index()
    o = t[["game_id", "T"] + sums].rename(columns={"T": "O", **{c: "opp_" + c for c in sums}})
    t = t.merge(o, on=["game_id", "O"], how="left")
    for c in sums:
        t["opp_" + c] = t["opp_" + c].fillna(0.0)
    t["live_miss"] = (t.fga - t.fgm) + FT_LIVE * (t.fta - t.ftm)
    t["opp_live_miss"] = (t.opp_fga - t.opp_fgm) + FT_LIVE * (t.opp_fta - t.opp_ftm)
    return t.sort_values(["T", "date", "game_id"], kind="mergesort").reset_index(drop=True)


def _wsum(keys: np.ndarray, x: np.ndarray, hl: float) -> np.ndarray:
    """Segmented EWM sum W_i = r * W_{i-1} + x_i, reset when the key changes (rows sorted by key, then time)."""
    r = 0.5 ** (1.0 / hl); out = np.empty(len(x)); acc = 0.0; prev = None
    xs = np.asarray(x, float); ks = keys.tolist()
    for i in range(len(xs)):
        k = ks[i]
        if k != prev:
            acc = 0.0; prev = k
        acc = acc * r + xs[i]; out[i] = acc
    return out


def _roll(keys: np.ndarray, x: np.ndarray, win: int) -> tuple[np.ndarray, np.ndarray]:
    """Sum of x over the last `win` rows of the key (including this one) and the number of rows in that window."""
    s = pd.Series(np.asarray(x, float)); g = s.groupby(keys, sort=False)
    return g.rolling(win, min_periods=1).sum().reset_index(level=0, drop=True).sort_index().to_numpy(), g.rolling(win, min_periods=1).count().reset_index(level=0, drop=True).sort_index().to_numpy()


def _role(pos) -> np.ndarray:
    return np.array([ROLE.get(p, "X") if isinstance(p, str) else "X" for p in pos], dtype=object)


def _league_priors(app: pd.DataFrame, tg: pd.DataFrame) -> tuple[dict, dict]:
    """{(season, role): {name: value}} for player priors of season S (from S-1), and {season: {name: value}} for team-level constants."""
    pr, tl = {}, {}
    a = app.assign(role=_role(app.pos))
    for S_ in sorted(set(app.season) | set(tg.season)):
        prev = a[a.season == S_ - 1]
        if len(prev) == 0:
            continue
        for role in ("C", "F", "G", "X"):
            q = prev if role == "X" else prev[prev.role == role]
            if len(q) == 0 or q["min"].sum() <= 0:
                q = prev
            d = {f"rate_{k}": q[k].sum() / q["min"].sum() for k in ("pts", "reb", "ast", "fga", "fta", "fg3a")}
            for s, (m, at) in {"fg3": ("fg3m", "fg3a"), "fg2": ("fg2m", "fg2a"), "ft": ("ftm", "fta")}.items():
                d[f"pct_{s}"] = q[m].sum() / q[at].sum()
            d["fg3_share"] = q["fg3a"].sum() / q["fga"].sum()
            # dispersion prior: players with >= PHI_MIN_APPS appearances in S-1, per-player season mean / sample variance
            g = q.groupby("pid")
            n = g.size(); keep = n[n >= PHI_MIN_APPS].index
            qq = q[q.pid.isin(keep)]
            for x in ("pts", "reb", "ast", "fg3m"):
                st = qq.groupby("pid")[x].agg(["mean", "var"])
                m_, v_ = st["mean"].to_numpy(float), st["var"].to_numpy(float)
                phi = np.where(m_ > 0, np.maximum(v_ - m_, 0.0) / np.where(m_ > 0, m_, 1.0) ** 2, 0.0)
                d[f"phi_{x}"] = float(phi.mean()) if len(phi) else 0.0
            pr[(S_, role)] = d
        tp = tg[tg.season == S_ - 1]
        if len(tp):
            tl[S_] = {"fg3a_rate": tp.fg3a.sum() / tp.fga.sum(), "tov_per_pu": tp.tov.sum() / tp.pu.sum(),
                      "reb_per_miss": (tp.reb.sum() + tp.opp_reb.sum()) / (tp.live_miss.sum() + tp.opp_live_miss.sum())}
    return pr, tl


def _player_state(app: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
    a = app.merge(tg[["game_id", "T", "fgm", "ast", "reb", "opp_reb", "pu", "min"]].rename(columns={"fgm": "t_fgm", "ast": "t_ast", "reb": "t_reb", "opp_reb": "t_opp_reb", "pu": "t_pu", "min": "t_min"}),
                  on=["game_id", "T"], how="left")
    a = a.sort_values(["pid", "date", "game_id"], kind="mergesort").reset_index(drop=True)
    k = a.pid.to_numpy()
    st = a[["pid", "date", "game_id", "T"]].copy(); st["role"] = _role(a.pos)
    st["W_min"] = _wsum(k, a["min"], H_RATE)
    for x in ("pts", "reb", "ast", "fga", "fta", "fg3a"):
        st["W_" + x] = _wsum(k, a[x], H_RATE)
    exp_pu = np.where(a.t_min > 0, a.t_pu * a["min"] / (a.t_min / 5.0), 0.0)
    st["W_pu"] = _wsum(k, a.pu, H_RATE); st["W_exp_pu"] = _wsum(k, exp_pu, H_RATE)
    st["W_tast"] = _wsum(k, a.t_ast, H_RATE); st["W_tfgm_o"] = _wsum(k, a.t_fgm - a.fgm, H_RATE)
    st["W_greb"] = _wsum(k, a.t_reb + a.t_opp_reb, H_RATE)
    st["min_ewm"] = _wsum(k, a["min"], H_MIN) / _wsum(k, np.ones(len(a)), H_MIN)
    for s, (m, at) in {"fg3": ("fg3m", "fg3a"), "fg2": ("fg2m", "fg2a"), "ft": ("ftm", "fta")}.items():
        st[f"C_{s}_m"] = a.groupby("pid", sort=False)[m].cumsum().to_numpy(); st[f"C_{s}_a"] = a.groupby("pid", sort=False)[at].cumsum().to_numpy()
        st[f"R_{s}_m"], _ = _roll(k, a[m].to_numpy(), RECENT); st[f"R_{s}_a"], _ = _roll(k, a[at].to_numpy(), RECENT)
    for x in ("pts", "reb", "ast", "fg3m"):
        v = pd.Series(a[x].to_numpy(float)); g = v.groupby(k, sort=False)
        st[f"D_{x}_n"] = g.rolling(DIST_WIN, min_periods=1).count().reset_index(level=0, drop=True).sort_index().to_numpy()
        st[f"D_{x}_m"] = g.rolling(DIST_WIN, min_periods=1).mean().reset_index(level=0, drop=True).sort_index().to_numpy()
        st[f"D_{x}_v"] = g.rolling(DIST_WIN, min_periods=2).var(ddof=1).reset_index(level=0, drop=True).sort_index().to_numpy()
    st["n_app"] = a.groupby("pid", sort=False).cumcount().to_numpy() + 1
    return st


def _team_state(tg: pd.DataFrame) -> pd.DataFrame:
    k = tg["T"].to_numpy(); st = tg[["T", "date", "game_id"]].copy()
    for c in ("opp_fg3a", "opp_fga", "opp_tov", "opp_pu", "live_miss", "oreb", "opp_dreb"):
        st["W_" + c] = _wsum(k, tg[c], H_TEAM)
    st["W_one"] = _wsum(k, np.ones(len(tg)), H_TEAM)
    st["miss_ewm"] = st.W_live_miss / st.W_one
    st["fg3a_allowed"] = st.W_opp_fg3a / st.W_opp_fga.where(st.W_opp_fga > 0)
    st["tov_forced"] = st.W_opp_tov / st.W_opp_pu.where(st.W_opp_pu > 0)
    st["orb_rate"] = st.W_oreb / (st.W_oreb + st.W_opp_dreb).where((st.W_oreb + st.W_opp_dreb) > 0)
    return st[["T", "date", "miss_ewm", "fg3a_allowed", "tov_forced", "orb_rate"]]


def _universe(tg: pd.DataFrame, app: pd.DataFrame) -> pd.DataFrame:
    out = tg[tg.season >= OUT_FIRST][["game_id", "T", "O", "season", "date"]]
    t = tg[["T", "date", "game_id"]]
    prev = []
    for team, rows in out.groupby("T", sort=True):
        h = t[t["T"] == team]; hd = h.date.to_numpy(); hg = h.game_id.to_numpy()
        n = np.searchsorted(hd, rows.date.to_numpy(), side="left")
        for o in range(1, PREV_TEAM_GAMES + 1):
            kk = n - o; ok = kk >= 0
            prev.append(pd.DataFrame({"game_id": rows.game_id.to_numpy()[ok], "T": team, "prev_gid": hg[kk[ok]]}))
    pv = pd.concat(prev, ignore_index=True)
    inv = app[["game_id", "T", "pid", "date"]].rename(columns={"game_id": "prev_gid", "date": "prev_date"})
    u = pv.merge(inv, on=["prev_gid", "T"], how="inner").groupby(["game_id", "T", "pid"], sort=True).prev_date.max().reset_index()
    u = u.sort_values(["game_id", "pid", "prev_date", "T"], ascending=[True, True, False, True], kind="mergesort").drop_duplicates(["game_id", "pid"])
    return u.drop(columns="prev_date").merge(out, on=["game_id", "T"], how="left")


def _bb_ge(nmax: int, mu: np.ndarray, a: np.ndarray, b: np.ndarray, ks=(1, 2, 3, 4)) -> np.ndarray:
    """P(makes >= k) for each row: sum over N = 0..nmax of NB(N; n = 2mu, p = 2/3) * P(BetaBinomial(N, a, b) >= k)."""
    out = np.zeros((len(mu), len(ks)))
    nb_n = mu / (NB_VAR_RATIO - 1.0); p = 1.0 / NB_VAR_RATIO
    pos = mu > 0
    for N in range(0, nmax + 1):
        # NB pmf: Gamma(N + n)/(Gamma(n) N!) p^n (1-p)^N
        with np.errstate(divide="ignore", invalid="ignore"):
            lp = gammaln(N + nb_n) - gammaln(nb_n) - gammaln(N + 1.0) + nb_n * np.log(p) + N * np.log1p(-p)
        w = np.where(pos, np.exp(lp), 1.0 if N == 0 else 0.0)
        cdf_lt = np.zeros((len(mu), len(ks)))       # P(makes <= k - 1 | N)
        for x in range(0, max(ks)):
            if x > N:
                break
            px = np.exp(gammaln(N + 1.0) - gammaln(x + 1.0) - gammaln(N - x + 1.0) + betaln(x + a, N - x + b) - betaln(a, b))
            for j, k in enumerate(ks):
                if x <= k - 1:
                    cdf_lt[:, j] += px
        out += w[:, None] * (1.0 - cdf_lt)
    return out


PU_COLS = ["pu_usg_pre", "pu_pts40_pre", "pu_reb40_pre", "pu_ast40_pre", "pu_fga40_pre", "pu_fta40_pre"]
PSR_COLS = [f"psr_{s}_{t}_pre" for s in ("fg3", "fg2", "ft") for t in ("shrunk", "luck")]
PSD_COLS = [f"psd_{x}_{t}_pre" for x in ("pts", "reb", "ast", "fg3m") for t in ("mean", "phi")]
PV_COLS = ["pv_fg3a40_pre", "pv_fg3_rate_pre", "pv_opp_fg3a_rel_pre", "pv_fg3a_exp_pre"]
PC_COLS = ["pc_p_ge1_pre", "pc_p_ge2_pre", "pc_p_ge3_pre", "pc_p_ge4_pre", "pc_mean_makes_pre"]
PA_COLS = ["pa_team_ast_share_pre", "pa_ast_pct_pre", "pa_opp_tov_forced_rel_pre"]
PR_COLS = ["pr_pool_pre", "pr_reb_share_pre", "pr_exp_reb_pre", "pr_opp_orb_rate_pre"]
ALL_COLS = PU_COLS + PSR_COLS + PSD_COLS + PV_COLS + PC_COLS + PA_COLS + PR_COLS
AUX_COLS = ["aux_min_ewm_pre", "aux_n_app_pre", "aux_role"]       # not certified (cbb.player_minutes needs pregame availability: prospective)


def _div(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float); ok = b > 0
    return np.where(ok, a / np.where(ok, b, 1.0), np.nan)


def compute(raw: dict) -> dict:
    bx = _prep(raw)
    tg = _team_games(bx)
    app = bx[bx.pid.notna() & (bx["min"] > 0)].copy()
    pri, tl = _league_priors(app, tg)
    pst = _player_state(app, tg)
    tst = _team_state(tg)
    u = _universe(tg, app)
    left = u.sort_values(["date", "pid"], kind="mergesort").reset_index(drop=True)
    f = pd.merge_asof(left, pst.drop(columns=["game_id", "T"]).sort_values(["date", "pid"], kind="mergesort"), on="date", by="pid", allow_exact_matches=False, direction="backward")
    ts = tst.sort_values(["date", "T"], kind="mergesort")
    f = pd.merge_asof(f.sort_values(["date", "T"], kind="mergesort"), ts.rename(columns={c: "own_" + c for c in ("miss_ewm", "fg3a_allowed", "tov_forced", "orb_rate")}),
                      on="date", by="T", allow_exact_matches=False, direction="backward")
    f = pd.merge_asof(f.sort_values(["date", "O"], kind="mergesort"), ts.rename(columns={"T": "O", **{c: "opp_" + c for c in ("miss_ewm", "fg3a_allowed", "tov_forced", "orb_rate")}}),
                      on="date", by="O", allow_exact_matches=False, direction="backward")
    f = f.sort_values(["date", "game_id", "pid"], kind="mergesort").reset_index(drop=True)
    pkey = pd.Series(list(zip(f.season.astype(int), f.role)))
    tkey = f.season.astype(int)
    P = lambda name: pkey.map({k: v[name] for k, v in pri.items()}).to_numpy(float)  # noqa: E731
    L = lambda name: tkey.map({k: v[name] for k, v in tl.items()}).to_numpy(float)  # noqa: E731
    f["pu_usg_pre"] = (f.W_pu + 0.20 * E0) / (f.W_exp_pu + E0)
    for x in ("pts", "reb", "ast", "fga", "fta"):
        f[f"pu_{x}40_pre"] = 40.0 * (f["W_" + x] + M0 * P("rate_" + x)) / (f.W_min + M0)
    for s in ("fg3", "fg2", "ft"):
        sh = (f[f"C_{s}_m"] + K_PCT[s] * P("pct_" + s)) / (f[f"C_{s}_a"] + K_PCT[s])
        f[f"psr_{s}_shrunk_pre"] = sh
        f[f"psr_{s}_luck_pre"] = _div(f[f"R_{s}_m"], f[f"R_{s}_a"]) - sh
    for x in ("pts", "reb", "ast", "fg3m"):
        n = f[f"D_{x}_n"].to_numpy(float); m = f[f"D_{x}_m"].to_numpy(float); v = f[f"D_{x}_v"].to_numpy(float)
        ok = n >= DIST_MIN
        phi_raw = np.where(m > 0, np.maximum(v - m, 0.0) / np.where(m > 0, m, 1.0) ** 2, 0.0)
        f[f"psd_{x}_mean_pre"] = np.where(ok, m, np.nan)
        f[f"psd_{x}_phi_pre"] = np.where(ok, n / (n + DIST_K) * phi_raw + DIST_K / (n + DIST_K) * P("phi_" + x), np.nan)
    f["pv_fg3a40_pre"] = 40.0 * (f.W_fg3a + M0 * P("rate_fg3a")) / (f.W_min + M0)
    f["pv_fg3_rate_pre"] = (f.W_fg3a + FG3_RATE_K * P("fg3_share")) / (f.W_fga + FG3_RATE_K)
    f["pv_opp_fg3a_rel_pre"] = f.opp_fg3a_allowed / L("fg3a_rate")
    f["pv_fg3a_exp_pre"] = f.pv_fg3a40_pre * f.min_ewm / 40.0 * f.pv_opp_fg3a_rel_pre.fillna(1.0)
    pct3 = P("pct_fg3"); a = XP_STRENGTH * pct3 + f.C_fg3_m.to_numpy(float); b = XP_STRENGTH * (1 - pct3) + (f.C_fg3_a - f.C_fg3_m).to_numpy(float)
    mu = f.pv_fg3a_exp_pre.to_numpy(float)
    ge = np.vstack([_bb_ge(NMAX, mu[i:i + 200000], a[i:i + 200000], b[i:i + 200000]) for i in range(0, len(mu), 200000)]) if len(mu) else np.zeros((0, 4))
    for j in range(4):
        f[f"pc_p_ge{j + 1}_pre"] = ge[:, j]
    f["pc_mean_makes_pre"] = mu * a / (a + b)
    f["pa_team_ast_share_pre"] = _div(f.W_ast, f.W_tast)
    f["pa_ast_pct_pre"] = _div(f.W_ast, f.W_tfgm_o)
    f["pa_opp_tov_forced_rel_pre"] = f.opp_tov_forced / L("tov_per_pu")
    f["pr_pool_pre"] = f.own_miss_ewm + f.opp_miss_ewm
    f["pr_reb_share_pre"] = _div(f.W_reb, f.W_greb)
    f["pr_exp_reb_pre"] = f.pr_reb_share_pre * f.pr_pool_pre * L("reb_per_miss")
    f["pr_opp_orb_rate_pre"] = f.opp_orb_rate
    f["aux_min_ewm_pre"] = f.min_ewm; f["aux_n_app_pre"] = f.n_app.astype(float); f["aux_role"] = f.role
    f = f.rename(columns={"pid": "team", "T": "pteam", "O": "opp"})
    cols = ["game_id", "team", "pteam", "opp", "season", "date"] + ALL_COLS + AUX_COLS
    f = f[cols].copy(); f["team"] = f["team"].astype("int64")
    for c in ALL_COLS:
        f[c] = f[c].astype("float64")
    return {"team": f.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


MISSING_COMMON = ["pregame availability / injury status (cbb.injuries: prospective capture)", "minutes projection beyond an EWM of past minutes (cbb.player_minutes: prospective)",
                  "opponent-level adjustment of player rates", "transfer / freshman cold-start prior (cbb.transfer_role_cold_start_prior)"]
RAW = ["ESPN men's college basketball player box scores 2012-2027 (sportsdataverse release, sift-data-vault archives/CBB/espn_player_box_pbp_early_seasons)"]


def specs() -> list[FeatureSpec]:
    return [
        FeatureSpec(S, "cbb.player_usage", "team", PU_COLS, "PARTIAL",
                    "Usage rate (player possessions used per expected possessions at his minutes share) and per-40 points, rebounds, assists, FGA and FTA: EWM sums (half-life 10 appearances) shrunk to the "
                    "previous season's league role (G/F/C) per-minute rate with a 200-minute prior (usage: prior 0.20, strength 20 possessions)",
                    ["per-40 rates with exponential recency", "usage", "shrinkage to a role-based prior (position bucket)"],
                    MISSING_COMMON + ["home/away and conference/non-conference splits", "role prior uses the box-score position bucket, not a usage-derived role"], RAW),
        FeatureSpec(S, "cbb.player_shooting_regression", "team", PSR_COLS, "PARTIAL",
                    "Beta-binomial shrinkage of career 3P%, 2P% and FT% to the previous season's role mean (prior strength 100 / 80 / 60 attempts) and the recent-minus-shrunk residual over the last 10 appearances",
                    ["beta-binomial shrinkage with role prior", "recent vs shrunk comparison"], ["shot openness proxies (needs play-by-play / tracking)", "prior strength tuned per stat (fixed constants used)",
                                                                                                    "career expectation spans 2012+ only"], RAW),
        FeatureSpec(S, "cbb.stat_dist", "team", PSD_COLS, "PARTIAL",
                    "Negative-binomial moments per player-stat (points, rebounds, assists, threes made): mean over the last 15 appearances (min 5) and the overdispersion phi = (var - mean)/mean^2, "
                    "partially pooled to the previous season's role mean phi with weight n/(n+10)",
                    ["negative-binomial count model per stat", "role-level prior and partial pooling of dispersion"],
                    ["mixture models", "rung calibration check", "parameter uncertainty in the predictive distribution", "minutes / availability conditioning"] + MISSING_COMMON[:1], RAW),
        FeatureSpec(S, "cbb.player_three_volume", "team", PV_COLS, "PARTIAL",
                    "3PA per 40 (EWM, role-prior shrunk), share of FGA from three, opponent's 3PA-allowed rate relative to the previous season's league rate, and expected attempts = rate x EWM minutes x "
                    "opponent factor (the negative-binomial mean)",
                    ["3PA per 40 (EWMA)", "share of FGA from three", "opponent 3PA allowed relative to league", "negative-binomial attempts mean"],
                    ["catch-and-shoot share (needs play-by-play / tracking)", "3P% is in cbb.player_shooting_regression", "attempts dispersion fitted by role (fixed var = 1.5 mean)"] + MISSING_COMMON[:2], RAW),
        FeatureSpec(S, "cbb.three_makes_compound_distribution", "team", PC_COLS, "PARTIAL",
                    "P(threes made >= 1..4) and mean makes from attempts ~ NB(mean = expected attempts, var = 1.5 mean) truncated at 40, make rate ~ Beta(100 x role 3P% + career makes, 100 x (1 - role 3P%) + "
                    "career misses), makes | attempts Beta-binomial (analytic mixture)",
                    ["attempts negative binomial with var = 1.5 mean", "Beta-uncertain make rate with a 100-attempt prior", "analytic Beta-binomial mixture for P(makes >= k)"],
                    ["minutes drawn from a minutes mixture (point EWM minutes used)", "pace factor", "xP from shot context (league role 3P% used; cbb.three_shot_quality_xp is contested)",
                     "dispersion fitted from the last 3 seasons by role"] + MISSING_COMMON[:1], RAW),
        FeatureSpec(S, "cbb.assist_creation", "team", PA_COLS, "PARTIAL",
                    "Share of team assists, assist percentage (assists per teammate field goal made, EWM half-life 10 appearances) and the opponent's forced-turnover rate relative to the previous season's league",
                    ["assist rate (share of team assists, assists per teammate FGM)", "opponent turnover profile"],
                    ["teammate eFG on assisted attempts (needs play-by-play)", "adjustment for absences (needs availability)", "opponent switch profile", "per-40 assist rate is in cbb.player_usage"], RAW),
        FeatureSpec(S, "cbb.rebound_pool", "team", PR_COLS, "PARTIAL",
                    "Expected rebound pool = team + opponent EWM live misses (missed FGA + 0.5 x missed FTA; half-life 10 team games); the player's share of all game rebounds (EWM, half-life 10 appearances); "
                    "expected rebounds = share x pool x previous-season rebounds per live miss; opponent offensive-rebound rate (EWM)",
                    ["pool of both teams' missed shots from shooting expectation", "player share of the pool", "opponent ORB crash rate"],
                    ["on-floor rebound rate (needs lineup stints)", "pool from a tempo x shooting model (team EWM misses used)", "exact last-FT miss count (0.5 x missed FTA approximation)"] + MISSING_COMMON[:1], RAW),
    ]


def perturb_nv(raw: dict, block_ids, seed: int) -> dict:
    """Role-preserving non-vacuity perturbation (precedent nfl_player_ext5.perturb): within the block's games, the content vectors (minutes and every stat) of APPEARANCE rows
    (athlete present, minutes > 0) are permuted jointly across appearances, so every appearance stays an appearance (the row universe of later games is unchanged) while every
    rate, share, window and prior of later rows must move."""
    o = dict(raw); b = raw["box"].copy(); rng = np.random.default_rng(seed)
    m = (b.game_id.isin(block_ids) & b.athlete_id.notna() & (pd.to_numeric(b.minutes, errors="coerce") > 0)).to_numpy()
    ix = np.flatnonzero(m); perm = rng.permutation(ix)
    for c in CONTENT:
        v = b[c].to_numpy(copy=True); v[ix] = v[perm]; b[c] = v
    o["box"] = b
    return o
