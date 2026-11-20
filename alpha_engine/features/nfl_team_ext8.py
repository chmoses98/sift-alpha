"""NFL batch 8, team rows (RESEARCH_ONLY): market-free drive-model team points and touchdown means, conditional margin spread, total-plays expectation, quarter-total
order statistics, paired-score residual correlation and a per-drive result lattice. nflverse play-by-play + schedule only; no spread, total, moneyline or price anywhere.

Source: sift-data-vault archives/NFL/pbp/2010-2026 (play_by_play_<season>.parquet) and archives/NFL/inseason_player_team (schedules/games.csv). Rights: nflverse,
WRAPPER_LICENCE_UPSTREAM_CAVEAT (internal research only).

COMMON
  Games: schedule rows with home_score present, season >= HIST_FIRST, all game types; codes OAK->LV, SD->LAC, STL->LA (relocated-team fix of NFL amendment 1: the same
  map is applied to pbp posteam, so the schedule join can never drop a relocated home game). date = gameday. Team-game rows: (team, opp, home flag s = +1 home, -1 away,
  0 when location == "Neutral"; points, points allowed). Ordered per team by (date, game_id).
  Per team-game from pbp (posteam = team, codes fixed): drives = number of distinct fixed_drive values; td_drives / fg_drives = drives whose fixed_drive_result is
  "Touchdown" / "Field goal"; plays = rows with play_type in {pass, run}. Opponent counterparts (opp_drives, opp_td_drives, opp_fg_drives) from the opponent's rows.
  Quarter totals of a game (regulation only): Q_q = (max total_home_score + max total_away_score over rows with qtr <= q) - same for qtr <= q-1 (missing scores -> 0).
  State: EWM sums over the team's earlier team-games, half-life 8 games, W(x) = sum r^(i-j) x_j; a row of date d reads the state after the team's last team-game dated < d.
  League constants of season S from the team-games of season S-1: drives per team-game, points per drive, TD and FG per drive; home edge h = mean(home - away points) over
  non-neutral games of S-1.
  Shrink a team rate x with effective games n = W(1) toward the league value: n/(n+8) x + 8/(n+8) lg.
  Output rows: team-games with season >= OUT_FIRST (seasons HIST_FIRST .. OUT_FIRST-1 are history: rows are computed internally for the reference windows).
  Reference window of season S: the computed team-game rows of seasons S-3 .. S-1 (seasons >= HIST_FIRST + 1), with their realised outcomes.

nfl.model_team_points_mean  E_drives = 0.5 (shr(off drives/game, T) + shr(drives allowed/game, O)); E_ppd = shr(off ppd, T) x shr(def ppd allowed, O) / lg_ppd;
                            mtp_mean_pre = E_drives x E_ppd + 0.5 h s; mtp_margin_pre = mean_T - mean_O; mtp_total_pre = mean_T + mean_O;
                            mtp_sd_pre = SD (ddof 1) of (points - mtp_mean) over reference rows in the row's tercile of mtp_mean (cut points = 1/3, 2/3 quantiles of the reference mtp_mean).
nfl.model_team_td_mean      mtd_lambda_pre = E_drives x shr(TD/drive, T) x shr(TD/drive allowed, O) / lg_tdpd; dispersion D = var(td_drives - lambda)/mean(lambda) over reference rows
                            in the row's lambda tercile; mtd_var_pre = lambda D; mtd_p_ge1_pre = 1 - exp(-lambda) if D <= 1 else 1 - (k/(k+lambda))^k, k = lambda/(D-1).
nfl.heteroskedastic_margin_sd  cells = |mtp_margin| tercile x mtp_total tercile (reference cut points); hms_sd_pre = n/(n+100) SD_cell + 100/(n+100) SD_pooled of (margin - mtp_margin);
                            hms_q05_mult_pre / hms_q95_mult_pre = 5% / 95% quantiles of the pooled standardized residual (residual / its cell's shrunk SD).
nfl.total_plays_state_model x1 = EWM plays/game of T + of O, x2 = |mtp_margin|; OLS of the game's total plays on (1, x1, x2) over reference rows; tps_exp_plays_pre = fit; tps_sd_pre = residual SD.
nfl.quarter_total_order_statistics  Gaussian kernel (bandwidth 3 points) on mtp_total over reference HOME rows: qos_argmax_q{1..4}_pre = weighted mean of 1{Q_q = max}/#argmax; qos_min0_pre = weighted
                            mean of 1{min_q Q_q = 0}.
nfl.paired_score_covariance_own  over reference HOME rows: residuals (home points - mean_home, away points - mean_away); bins = mtp_total tercile; psc_rho_pre = n/(n+150) rho_bin + 150/(n+150) rho_pooled.
nfl.drive_result_lattice    drl_p_td_pre = shr(TD/drive, T) x shr(TD allowed/drive, O) / lg_tdpd; drl_p_fg_pre likewise with FG; drl_p_none_pre = max(0, 1 - td - fg);
                            drl_exp_points_pre = E_drives x (7 td + 3 fg).
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
HL = 8.0
K_SHR = 8.0
REF_SEASONS = 3
K_CELL, K_RHO = 100.0, 150.0
BW_QOS = 3.0
PBP_COLS = ["game_id", "posteam", "fixed_drive", "fixed_drive_result", "play_type", "qtr", "total_home_score", "total_away_score"]
CONTENT = ["posteam", "fixed_drive", "fixed_drive_result", "play_type", "qtr", "total_home_score", "total_away_score"]
GAMES_COLS = ["game_id", "season", "game_type", "week", "gameday", "home_team", "away_team", "home_score", "away_score", "location"]
GAMES_CONTENT = ["home_score", "away_score"]


def load_raw(pbp_dir, games_file) -> dict:
    fs = sorted(glob.glob(str(Path(pbp_dir) / "play_by_play_*.parquet"))) or sorted(glob.glob(str(Path(pbp_dir) / "pbp_*.parquet")))
    pbp = pd.concat([pd.read_parquet(f, columns=PBP_COLS) for f in fs], ignore_index=True)
    g = pd.read_csv(games_file, usecols=GAMES_COLS)
    g = g[(g.season >= HIST_FIRST) & g.home_score.notna()].drop_duplicates("game_id")
    warm = set(g.game_id[g.season < OUT_FIRST]); pw = pbp.game_id.isin(warm)
    pbp = pbp[pbp.game_id.isin(set(g.game_id))]; pw = pbp.game_id.isin(warm)
    # harness wiring (precedent nfl_player_ext5): history seasons in *_warm precede every replay cut and are never truncated or permuted
    return {"pbp": pbp[~pw].reset_index(drop=True), "games": g[g.season >= OUT_FIRST].reset_index(drop=True),
            "pbp_warm": pbp[pw].reset_index(drop=True), "games_warm": g[g.season < OUT_FIRST].reset_index(drop=True)}


def _all(raw: dict, key: str) -> pd.DataFrame:
    parts = [raw[k] for k in (key + "_warm", key) if raw.get(k) is not None and len(raw[k])]
    return pd.concat(parts, ignore_index=True) if parts else raw[key]


def _fix(s: pd.Series) -> pd.Series:
    return s.astype("object").replace(TEAM_FIX)


def _team_games(raw: dict) -> pd.DataFrame:
    g = _all(raw, "games")
    g = g[(g.season >= HIST_FIRST) & g.home_score.notna()].drop_duplicates("game_id").copy()
    g["date"] = pd.to_datetime(g.gameday); g["home_team"] = _fix(g.home_team); g["away_team"] = _fix(g.away_team)
    neu = (g.location.astype(str) == "Neutral").to_numpy()
    rows = []
    for a, b, pa, pb, s in (("home_team", "away_team", "home_score", "away_score", 1), ("away_team", "home_team", "away_score", "home_score", -1)):
        rows.append(pd.DataFrame({"game_id": g.game_id.to_numpy(), "season": g.season.to_numpy(), "date": g.date.to_numpy(), "team": g[a].to_numpy(), "opp": g[b].to_numpy(),
                                  "s": np.where(neu, 0, s), "is_home": int(s == 1), "pts": g[pa].to_numpy(float), "pts_a": g[pb].to_numpy(float)}))
    t = pd.concat(rows, ignore_index=True)
    p = _all(raw, "pbp"); p = p[p.game_id.isin(set(g.game_id))].copy(); p["T"] = _fix(p.posteam)
    pp = p[p["T"].notna()]
    dr = pp[pp.fixed_drive.notna()].groupby(["game_id", "T", "fixed_drive"], sort=True).fixed_drive_result.first().reset_index()
    d = dr.groupby(["game_id", "T"]).agg(drives=("fixed_drive", "size"), td=("fixed_drive_result", lambda x: float((x == "Touchdown").sum())),
                                         fg=("fixed_drive_result", lambda x: float((x == "Field goal").sum()))).reset_index()
    pl = pp[pp.play_type.isin(["pass", "run"])].groupby(["game_id", "T"]).size().rename("plays").reset_index()
    t = t.merge(d.rename(columns={"T": "team"}), on=["game_id", "team"], how="left").merge(pl.rename(columns={"T": "team"}), on=["game_id", "team"], how="left")
    for c in ("drives", "td", "fg", "plays"):
        t[c] = t[c].fillna(0.0).astype(float)
    o = t[["game_id", "team", "drives", "td", "fg", "plays"]].rename(columns={"team": "opp", "drives": "o_drives", "td": "o_td", "fg": "o_fg", "plays": "o_plays"})
    t = t.merge(o, on=["game_id", "opp"], how="left")
    # quarter totals (regulation)
    sc = p[["game_id", "qtr", "total_home_score", "total_away_score"]].copy()
    sc["tot"] = sc.total_home_score.fillna(0.0) + sc.total_away_score.fillna(0.0)
    qmax = sc[sc.qtr.between(1, 4)].groupby(["game_id", "qtr"]).tot.max().unstack()
    qmax = qmax.reindex(columns=[1, 2, 3, 4]).ffill(axis=1).fillna(0.0)
    cum = qmax.cummax(axis=1).to_numpy(); q = np.diff(np.concatenate([np.zeros((len(cum), 1)), cum], axis=1), axis=1)
    qd = pd.DataFrame(q, columns=["q1", "q2", "q3", "q4"]); qd["game_id"] = qmax.index.to_numpy()
    t = t.merge(qd, on="game_id", how="left")
    return t.sort_values(["team", "date", "game_id"], kind="mergesort").reset_index(drop=True)


def _wsum(keys: np.ndarray, x: np.ndarray, hl: float) -> np.ndarray:
    r = 0.5 ** (1.0 / hl); out = np.empty(len(x)); acc = 0.0; prev = None
    for i, (k, v) in enumerate(zip(keys.tolist(), np.asarray(x, float).tolist())):
        if k != prev:
            acc = 0.0; prev = k
        acc = acc * r + v; out[i] = acc
    return out


def _state(t: pd.DataFrame) -> pd.DataFrame:
    k = t.team.to_numpy(); st = t[["team", "date"]].copy()
    for c in ("drives", "o_drives", "pts", "pts_a", "td", "o_td", "fg", "o_fg", "plays"):
        st["W_" + c] = _wsum(k, t[c], HL)
    st["W_one"] = _wsum(k, np.ones(len(t)), HL)
    return st


def _league(t: pd.DataFrame) -> dict:
    out = {}
    for s_ in sorted(t.season.unique()):
        q = t[t.season == s_]
        h = q[(q.is_home == 1) & (q.s != 0)]
        out[s_ + 1] = {"dpg": q.drives.mean(), "ppd": q.pts.sum() / q.drives.sum(), "tdpd": q.td.sum() / q.drives.sum(), "fgpd": q.fg.sum() / q.drives.sum(),
                       "h": float((h.pts - h.pts_a).mean())}
    return out


def _shr(n, x, lg):
    return n / (n + K_SHR) * x + K_SHR / (n + K_SHR) * lg


def _div(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float); ok = b > 0
    return np.where(ok, a / np.where(ok, b, 1.0), np.nan)


def _terc(ref: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c1, c2 = np.quantile(ref, [1 / 3, 2 / 3]); f = lambda v: np.where(v <= c1, 0, np.where(v <= c2, 1, 2))  # noqa: E731
    return f(ref), f(x)


MTP = ["mtp_mean_pre", "mtp_margin_pre", "mtp_total_pre", "mtp_sd_pre"]
MTD = ["mtd_lambda_pre", "mtd_var_pre", "mtd_p_ge1_pre"]
HMS = ["hms_sd_pre", "hms_q05_mult_pre", "hms_q95_mult_pre"]
TPS = ["tps_exp_plays_pre", "tps_sd_pre"]
QOS = [f"qos_argmax_q{q}_pre" for q in (1, 2, 3, 4)] + ["qos_min0_pre"]
PSC = ["psc_rho_pre"]
DRL = ["drl_p_td_pre", "drl_p_fg_pre", "drl_p_none_pre", "drl_exp_points_pre"]
ALL = MTP + MTD + HMS + TPS + QOS + PSC + DRL


def _rows(raw: dict) -> pd.DataFrame:
    """Every team-game row of season >= HIST_FIRST + 1 with the state-based columns (section 4 of the brief) and its realised outcomes; no reference-window column."""
    t = _team_games(raw); st = _state(t); lg = _league(t)
    rows = t[t.season >= HIST_FIRST + 1].copy()
    stl = st.sort_values(["date", "team"], kind="mergesort")
    rows = rows.sort_values(["date", "team"], kind="mergesort")
    a = pd.merge_asof(rows, stl.add_prefix("T_").rename(columns={"T_team": "team", "T_date": "date"}), on="date", by="team", allow_exact_matches=False, direction="backward")
    a = pd.merge_asof(a.sort_values(["date", "opp"], kind="mergesort"), stl.add_prefix("O_").rename(columns={"O_team": "opp", "O_date": "date"}), on="date", by="opp",
                      allow_exact_matches=False, direction="backward")
    a = a.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    L = lambda k: a.season.map(lambda s_: lg[s_][k]).to_numpy(float)  # noqa: E731
    nT = a.T_W_one.fillna(0.0).to_numpy(); nO = a.O_W_one.fillna(0.0).to_numpy()
    sh = lambda n, num, den, lgv: _shr(n, np.nan_to_num(_div(num, den), nan=0.0), lgv)  # noqa: E731
    e_dr = 0.5 * (sh(nT, a.T_W_drives, a.T_W_one, L("dpg")) + sh(nO, a.O_W_o_drives, a.O_W_one, L("dpg")))
    off_ppd = sh(nT, a.T_W_pts, a.T_W_drives, L("ppd")); def_ppd = sh(nO, a.O_W_pts_a, a.O_W_o_drives, L("ppd"))
    td_o = sh(nT, a.T_W_td, a.T_W_drives, L("tdpd")); td_d = sh(nO, a.O_W_o_td, a.O_W_o_drives, L("tdpd"))
    fg_o = sh(nT, a.T_W_fg, a.T_W_drives, L("fgpd")); fg_d = sh(nO, a.O_W_o_fg, a.O_W_o_drives, L("fgpd"))
    a["mtp_mean_pre"] = e_dr * off_ppd * def_ppd / L("ppd") + 0.5 * L("h") * a.s.to_numpy()
    a["mtd_lambda_pre"] = e_dr * td_o * td_d / L("tdpd")
    a["drl_p_td_pre"] = td_o * td_d / L("tdpd"); a["drl_p_fg_pre"] = fg_o * fg_d / L("fgpd")
    a["drl_p_none_pre"] = np.maximum(0.0, 1.0 - a.drl_p_td_pre - a.drl_p_fg_pre)
    a["drl_exp_points_pre"] = e_dr * (7.0 * a.drl_p_td_pre + 3.0 * a.drl_p_fg_pre)
    a["x_plays"] = _div(a.T_W_plays, a.T_W_one) + _div(a.O_W_plays, a.O_W_one)
    m = a[["game_id", "team", "mtp_mean_pre"]].rename(columns={"team": "opp", "mtp_mean_pre": "o_mean"})
    a = a.merge(m, on=["game_id", "opp"], how="left")
    a["mtp_margin_pre"] = a.mtp_mean_pre - a.o_mean; a["mtp_total_pre"] = a.mtp_mean_pre + a.o_mean
    a["tot_plays"] = a.plays + a.o_plays
    return a


def compute(raw: dict) -> dict:
    a = _rows(raw)
    for c in MTP[3:] + MTD[1:] + HMS + TPS + QOS + PSC:
        a[c] = np.nan
    for s_ in sorted(a.season.unique()):
        if s_ < OUT_FIRST:
            continue
        ref = a[(a.season >= s_ - REF_SEASONS) & (a.season <= s_ - 1)].dropna(subset=["mtp_mean_pre", "o_mean"])
        cur = (a.season == s_).to_numpy(); c = a[cur]
        # mtp_sd by tercile of mtp_mean
        rt, ct = _terc(ref.mtp_mean_pre.to_numpy(), c.mtp_mean_pre.to_numpy()); res = (ref.pts - ref.mtp_mean_pre).to_numpy()
        sd = np.array([res[rt == k].std(ddof=1) for k in range(3)]); a.loc[cur, "mtp_sd_pre"] = sd[ct]
        # TD dispersion by lambda tercile
        rt, ct = _terc(ref.mtd_lambda_pre.to_numpy(), c.mtd_lambda_pre.to_numpy()); r2 = (ref.td - ref.mtd_lambda_pre).to_numpy(); lam_r = ref.mtd_lambda_pre.to_numpy()
        D = np.array([r2[rt == k].var(ddof=1) / lam_r[rt == k].mean() for k in range(3)])[ct]; lam = c.mtd_lambda_pre.to_numpy()
        a.loc[cur, "mtd_var_pre"] = lam * D
        with np.errstate(divide="ignore", invalid="ignore"):
            kk = lam / (D - 1.0); nb = 1.0 - (kk / (kk + lam)) ** kk
        a.loc[cur, "mtd_p_ge1_pre"] = np.where(D <= 1.0, 1.0 - np.exp(-lam), nb)
        # conditional margin SD
        ra, ca = _terc(np.abs(ref.mtp_margin_pre.to_numpy()), np.abs(c.mtp_margin_pre.to_numpy())); rtt, ctt = _terc(ref.mtp_total_pre.to_numpy(), c.mtp_total_pre.to_numpy())
        rc = ra * 3 + rtt; cc = ca * 3 + ctt; mr = (ref.pts - ref.pts_a - ref.mtp_margin_pre).to_numpy(); pooled = mr.std(ddof=1)
        cell = np.array([(lambda v: (len(v) / (len(v) + K_CELL)) * (v.std(ddof=1) if len(v) > 1 else 0.0) + (K_CELL / (len(v) + K_CELL)) * pooled)(mr[rc == k]) for k in range(9)])
        z = mr / cell[rc]
        a.loc[cur, "hms_sd_pre"] = cell[cc]; a.loc[cur, "hms_q05_mult_pre"] = float(np.quantile(z, 0.05)); a.loc[cur, "hms_q95_mult_pre"] = float(np.quantile(z, 0.95))
        # total plays OLS
        rr = ref.dropna(subset=["x_plays"]); X = np.column_stack([np.ones(len(rr)), rr.x_plays.to_numpy(), np.abs(rr.mtp_margin_pre.to_numpy())])
        b, *_ = np.linalg.lstsq(X, rr.tot_plays.to_numpy(float), rcond=None); e = rr.tot_plays.to_numpy(float) - X @ b
        Xc = np.column_stack([np.ones(len(c)), c.x_plays.to_numpy(), np.abs(c.mtp_margin_pre.to_numpy())])
        a.loc[cur, "tps_exp_plays_pre"] = Xc @ b; a.loc[cur, "tps_sd_pre"] = float(np.sqrt((e ** 2).sum() / (len(e) - 3)))
        # quarter order statistics and paired residual correlation (home rows of the reference window)
        h = ref[ref.is_home == 1].dropna(subset=["q1"])
        Q = h[["q1", "q2", "q3", "q4"]].to_numpy(float); mx = Q.max(axis=1, keepdims=True); arg = (Q == mx) / (Q == mx).sum(axis=1, keepdims=True); mn0 = (Q.min(axis=1) == 0).astype(float)
        xr = h.mtp_total_pre.to_numpy(); xc = c.mtp_total_pre.to_numpy()
        K = np.exp(-0.5 * ((xc[:, None] - xr[None, :]) / BW_QOS) ** 2); ks = K.sum(axis=1)
        for q in range(4):
            a.loc[cur, f"qos_argmax_q{q + 1}_pre"] = K @ arg[:, q] / ks
        a.loc[cur, "qos_min0_pre"] = K @ mn0 / ks
        hr = h.dropna(subset=["o_mean"]); u = (hr.pts - hr.mtp_mean_pre).to_numpy(); v = (hr.pts_a - hr.o_mean).to_numpy()
        rb, cb = _terc(hr.mtp_total_pre.to_numpy(), c.mtp_total_pre.to_numpy()); rp = np.corrcoef(u, v)[0, 1]
        rho = np.array([(lambda m_: (m_.sum() / (m_.sum() + K_RHO)) * np.corrcoef(u[m_], v[m_])[0, 1] + (K_RHO / (m_.sum() + K_RHO)) * rp)(rb == k) for k in range(3)])
        a.loc[cur, "psc_rho_pre"] = rho[cb]
    out = a[a.season >= OUT_FIRST][["game_id", "team", "opp", "season", "date"] + ALL].copy()
    for c in ALL:
        out[c] = out[c].astype("float64")
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


RAW = ["nflverse play_by_play 2010-2026 (posteam, fixed_drive, fixed_drive_result, play_type, qtr, cumulative scores)", "nflverse schedule (scores, location)"]
NOT_USED = ["weather / dome / wind (env.weather_forecast_pit not collected)", "starting-QB status (nfl.qb: prospective)", "injuries"]


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, lvl, d, done, miss: FeatureSpec(S, cid, "team", cols, lvl, d, done, miss + NOT_USED, RAW)  # noqa: E731
    return [
        F("nfl.model_team_points_mean", MTP, "PROXY", "Drive-model team points: expected drives (team's drives and opponent's drives allowed, EWM half-life 8 games, shrunk to the S-1 league at 8 games) x "
          "expected points per drive (own offensive x opponent defensive points per drive / league) + half the S-1 home edge; margin and total by difference and sum; SD of residuals by tercile of the mean "
          "over the previous 3 seasons", ["E[drives] x E[points per drive]", "opponent adjustment and shrinkage at 8 games", "home term", "team SD from residuals by tercile", "margin and total"],
          ["neutral seconds-per-play drive count model", "ridge regression of points per drive on EPA per play, red-zone TD rate, kicker rating", "prior-season carryover schedule (EWM spans seasons instead)"]),
        F("nfl.model_team_td_mean", MTD, "PROXY", "Team touchdown mean = expected drives x opponent-adjusted TD-per-drive (shrunk at 8 games); variance from the TD-count overdispersion of the previous 3 seasons by tercile; "
          "P(N >= 1) with a negative-binomial correction", ["drives x P(TD | drive)", "overdispersion from tercile residuals", "P(N >= 1) with NB correction"],
          ["logistic ridge on EPA, red-zone trips and TD rate, 4th-and-goal rate"]),
        F("nfl.heteroskedastic_margin_sd", HMS, "PARTIAL", "Conditional SD of the final margin given the market-free model mean margin and total (3 x 3 tercile cells of the previous 3 seasons, shrunk to the pooled SD "
          "with n/(n+100)), and 5% / 95% tail multipliers of the standardized residual", ["conditional SD on model mean margin and total", "5/95% tail multipliers", "annual refit", "no betting line"],
          ["quantile / location-scale regression (binned cells)", "wind, dome, backup-QB and divisional covariates"]),
        F("nfl.total_plays_state_model", TPS, "PARTIAL", "Expected total offensive plays from an OLS (previous 3 seasons) on both teams' EWM plays per game and the absolute model margin, with residual SD",
          ["expected plays and SD", "both teams' tempo", "expected absolute margin from the own model", "walk-forward fit"],
          ["neutral seconds per play, PROE, run rate, completion and penalty rates", "team / opponent random effects"]),
        F("nfl.quarter_total_order_statistics", QOS, "PROXY", "Kernel-conditional (on model expected total, bandwidth 3 points; previous 3 seasons) probability that each quarter has the highest combined points (dead heats "
          "split) and that the lowest quarter total is zero", ["argmax-quarter shares with dead-heat credit", "P(minimum quarter = 0)", "calibrated to empirical frequencies by expected total"],
          ["drive-level simulation of period drive counts and scoring rates"]),
        F("nfl.paired_score_covariance_own", PSC, "PROXY", "Correlation of home and away score residuals against the own model means, by model-total tercile of the previous 3 seasons, shrunk to the pooled "
          "correlation with n/(n+150)", ["residual correlation of paired scores from own-model means", "expected-total bins with shrinkage to pooled"],
          ["wind bins", "Student-t copula (rho, nu) and tail dependence", "simulation through the score marginals"]),
        F("nfl.drive_result_lattice", DRL, "PROXY", "Per-drive P(TD), P(FG), P(no score) from the team's offensive and the opponent's defensive drive-result rates (opponent-adjusted, shrunk at 8 games) and expected "
          "points = expected drives x (7 P(TD) + 3 P(FG))", ["drive result probabilities TD / FG / none", "offence and defence ratings", "shrinkage of team deviations"],
          ["start-yard-line dependence (multinomial logit)", "convolution to the discrete points distribution with XP / 2-point outcomes"]),
    ]
