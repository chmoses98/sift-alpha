"""Phase 15 NBA team-game builders (RESEARCH_ONLY): ratings-based blowout probability and starter-minutes curve, empirical final-margin probabilities, own-model team totals,
team-points-vs-expected-margin curve, wins versus a pre-season expectation, win-streak hazard and an availability-adjusted rating proxy.

Raw data: owner's nba-edge-finder ESPN box-score archive (team_games, player_games), regular season only. Output table ``team`` keyed (game_id, team). Every value for game G is built from games on
STRICTLY EARLIER DATES (a team plays at most once per date, so a per-team shift of one game is a strictly-earlier-date shift; league quantities are cumulative sums over earlier dates). Nothing of the
game's own box score, and no line, spread or price, enters its features. Every input is PARTIAL or PROXY: `missing` lists what the catalog definition asks for that is not implemented.
"""
from __future__ import annotations

import glob
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import erf

from .core import FeatureSpec

S = "NBA"
TG_COLS = ["game_id", "game_date_et", "season", "season_type", "team_id", "opp_team_id", "home", "pts", "opp_pts", "n_ot", "possessions"]
PG_COLS = ["game_id", "game_date_et", "season", "season_type", "team_id", "nba_id", "played", "started", "minutes", "plus_minus"]
TG_CONTENT = ["pts", "opp_pts", "possessions", "n_ot"]
PG_CONTENT = ["started", "minutes", "plus_minus"]


def load_raw(nba_dir) -> dict:
    h = Path(nba_dir) / "espn"
    cat = lambda pat, cols: pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(str(h / pat)))], ignore_index=True)
    return {"team_games": cat("team_games_*.parquet", TG_COLS), "player_games": cat("player_games_*.parquet", PG_COLS)}


def before(df: pd.DataFrame, val, by=()) -> np.ndarray:
    """Per row: sum of ``val`` (NaN counted as 0) over rows of ``df`` with a STRICTLY EARLIER date (within the same ``by`` keys when given). Rows whose ``by`` key is NaN get NaN."""
    keys = list(by) + ["date"]
    tmp = df[keys].copy(); tmp["v"] = np.nan_to_num(np.asarray(val, dtype=float))
    a = tmp.dropna(subset=keys).groupby(keys, sort=True).v.sum().reset_index()
    a["c"] = (a.groupby(list(by)).v.cumsum() if by else a.v.cumsum()) - a.v
    return tmp[keys].merge(a[keys + ["c"]], on=keys, how="left").c.to_numpy()


def _ewm(t, col, hl, mp):
    return t.groupby("team", sort=False)[col].transform(lambda s: s.shift(1).ewm(halflife=hl, min_periods=mp).mean())


def _prev(t, col, by=("team",)):
    """sum of col over the entity's earlier rows (NaN as 0)."""
    v = t[col].fillna(0.0)
    return v.groupby([t[k] for k in by], sort=False).cumsum() - v


def _opp(t: pd.DataFrame, cols) -> pd.DataFrame:
    o = t[["game_id", "team", *cols]].rename(columns={"team": "opp", **{c: f"o_{c}" for c in cols}})
    return t.merge(o, on=["game_id", "opp"], how="left")


def _phi(x):
    return 0.5 * (1.0 + erf(np.asarray(x, dtype=float) / math.sqrt(2.0)))


def _table(raw: dict) -> pd.DataFrame:
    t = raw["team_games"]; t = t[t.season_type == "regular"].copy(); t["date"] = pd.to_datetime(t.game_date_et)
    t = t.rename(columns={"team_id": "team", "opp_team_id": "opp"}); t["home"] = t.home.astype(bool)
    for c in ("pts", "opp_pts", "possessions", "n_ot"): t[c] = t[c].astype(float)
    t["sidx"] = t.season.astype(str).str[:4].astype(int)
    pg = raw["player_games"]; pg = pg[(pg.season_type == "regular") & (pg.played == True) & (pg.started == True)]   # noqa: E712
    st = pg.groupby(["game_id", "team_id"]).minutes.sum().rename("st_min").reset_index().rename(columns={"team_id": "team"})
    t = t.merge(st, on=["game_id", "team"], how="left")
    return t.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)


def _rating_blowout(t: pd.DataFrame) -> pd.DataFrame:
    t["margin"] = t.pts - t.opp_pts; t["net100"] = t.margin / t.possessions * 100.0
    t["nr_pre"] = _ewm(t, "net100", 25, 5); t["pace_pre"] = _ewm(t, "possessions", 20, 3)
    t = _opp(t, ["nr_pre", "pace_pre"])
    t["adj"] = t.net100 + t.o_nr_pre
    t["rb_adjnet_pre"] = _ewm(t, "adj", 25, 5)
    t = _opp(t, ["rb_adjnet_pre"])
    hs = before(t, np.where(t.home, t.margin, 0.0)); hn = before(t, t.home.astype(float))
    t["hadv"] = np.where(hn > 0, hs / np.where(hn > 0, hn, 1.0), np.nan)
    t["exp_pace"] = np.sqrt(t.pace_pre * t.o_pace_pre)
    t["rb_mu_pre"] = (t.rb_adjnet_pre - t.o_rb_adjnet_pre) * t.exp_pace / 100.0 + np.where(t.home, 1.0, -1.0) * t.hadv
    ok = (t.home & t.rb_mu_pre.notna()).to_numpy()
    ss = before(t, np.where(ok, (t.margin - t.rb_mu_pre) ** 2, 0.0)); sn = before(t, ok.astype(float))
    t["rb_sd_pre"] = np.where(sn >= 100, np.sqrt(ss / np.where(sn > 0, sn, 1.0)), np.nan)
    for k in (15, 20):
        t[f"rb_p{k}_pre"] = _phi((-(k - 0.5) - t.rb_mu_pre) / t.rb_sd_pre) + 1.0 - _phi(((k - 0.5) - t.rb_mu_pre) / t.rb_sd_pre)
    t["st_reg"] = t.st_min * 240.0 / (240.0 + 25.0 * t.n_ot)
    am = t.margin.abs()
    for nm, mask, need in (("close", am < 10, 5), ("blow", am >= 20, 3)):
        m = (mask & t.st_reg.notna()).astype(float)
        t["_v"] = t.st_reg.where(m == 1, 0.0); t["_m"] = m
        s, n = _prev(t, "_v"), _prev(t, "_m")
        t[f"rb_st_{nm}_pre"] = np.where(n >= need, s / np.where(n > 0, n, 1.0), np.nan)
    t["rb_exp_stmin_pre"] = (1.0 - t.rb_p20_pre) * t.rb_st_close_pre + t.rb_p20_pre * t.rb_st_blow_pre
    return t


def _final_margin(t: pd.DataFrame) -> pd.DataFrame:
    """Empirical probabilities from the standardised residuals z = (home margin - mu)/sd of home rows on strictly earlier dates."""
    hz = t[t.home & t.rb_mu_pre.notna() & t.rb_sd_pre.notna()]
    zd = hz.date.to_numpy(); zv = ((hz.margin - hz.rb_mu_pre) / hz.rb_sd_pre).to_numpy()
    out = {c: np.full(len(t), np.nan) for c in ("fm_p_win_pre", "fm_p_gt5_pre", "fm_p_gt10_pre")}
    dates = t.date.to_numpy(); mu = t.rb_mu_pre.to_numpy(); sd = t.rb_sd_pre.to_numpy(); home = t.home.to_numpy()
    for d in np.unique(dates):
        n = int(np.searchsorted(zd, d, side="left"))          # zd is sorted (t is chronological)
        if n < 200: continue
        z = zv[:n]
        for i in np.flatnonzero(dates == d):
            if np.isnan(mu[i]) or np.isnan(sd[i]): continue
            for c, thr in (("fm_p_win_pre", 0.0), ("fm_p_gt5_pre", 5.5), ("fm_p_gt10_pre", 10.5)):
                out[c][i] = float((z > (thr - mu[i]) / sd[i]).mean()) if home[i] else float((z < (mu[i] - thr) / sd[i]).mean())
    for c, v in out.items(): t[c] = v
    return t


def _wlast(x: np.ndarray, n: int, hl: float, minobs: int):
    """for each i: (weighted mean of x[i-n..i-1] with weight 0.5**(age/hl), age = 1 for x[i-1]; number of games used); NaN mean if fewer than minobs earlier games."""
    m = np.full(len(x), np.nan); k = np.zeros(len(x))
    for i in range(len(x)):
        seg = x[max(0, i - n):i][::-1]; k[i] = len(seg)
        if len(seg) >= minobs:
            w = 0.5 ** (np.arange(1, len(seg) + 1) / hl); m[i] = float((seg * w).sum() / w.sum())
    return m, k


def _own_totals(t: pd.DataFrame) -> pd.DataFrame:
    res = {}
    for _, g in t.groupby("team", sort=False):
        m, k = _wlast(g.possessions.to_numpy(float), 20, 8.0, 3)
        for i, a, b in zip(g.index, m, k): res[i] = (a, b)
    t["pace20"] = [res[i][0] for i in t.index]; t["n20"] = [res[i][1] for i in t.index]
    one = np.ones(len(t)); cnt = before(t, one)
    lg = lambda col: np.where(cnt > 0, before(t, t[col]) / np.where(cnt > 0, cnt, 1.0), np.nan)
    t["ppp"] = t.pts / t.possessions; t["dpp"] = t.opp_pts / t.possessions
    t["lg_pace"] = lg("possessions"); t["lg_ppp"] = lg("ppp")
    t["pace_s"] = (t.n20 * t.pace20 + 15.0 * t.lg_pace) / (t.n20 + 15.0)
    t["g40"] = t.groupby("team", sort=False).cumcount().clip(upper=40).astype(float)
    t["off_s"] = (t.g40 * _ewm(t, "ppp", 20, 3) + 20.0 * t.lg_ppp) / (t.g40 + 20.0)
    t["def_s"] = (t.g40 * _ewm(t, "dpp", 20, 3) + 20.0 * t.lg_ppp) / (t.g40 + 20.0)
    hn = before(t, t.home.astype(float)); hs = before(t, np.where(t.home, t.ppp - t.dpp, 0.0))
    t["hppp"] = np.where(hn > 0, hs / np.where(hn > 0, hn, 1.0), np.nan)
    t = _opp(t, ["pace_s", "def_s"])
    t["exp_poss"] = t.pace_s * t.o_pace_s / t.lg_pace
    t["ot_exp_pts_pre"] = t.exp_poss * (t.off_s + t.o_def_s - t.lg_ppp + np.where(t.home, 0.5, -0.5) * t.hppp)
    t = _opp(t, ["ot_exp_pts_pre"])
    t["ot_exp_total_pre"] = t.ot_exp_pts_pre + t.o_ot_exp_pts_pre; t["ot_exp_margin_pre"] = t.ot_exp_pts_pre - t.o_ot_exp_pts_pre
    t["resid"] = t.pts - t.ot_exp_pts_pre
    t["_r2"] = t.resid ** 2; t["_rn"] = t.resid.notna().astype(float)
    s, n = _prev(t, "_r2"), _prev(t, "_rn")
    t["ot_sd_team_pre"] = np.where(n >= 10, np.sqrt(s / np.where(n > 0, n, 1.0)), np.nan)
    rm = t.margin - t.ot_exp_margin_pre; rt = (t.pts + t.opp_pts) - t.ot_exp_total_pre
    ok = (t.home & rm.notna() & rt.notna()).to_numpy(); z = lambda v: np.where(ok, v, 0.0)
    n = before(t, ok.astype(float)); smm, stt, smt = before(t, z(rm ** 2)), before(t, z(rt ** 2)), before(t, z(rm * rt))
    good = n >= 100; den = np.where(n > 0, n, 1.0)
    sdm = np.sqrt(smm / den); sdt = np.sqrt(stt / den)
    t["ot_sd_margin_pre"] = np.where(good, sdm, np.nan); t["ot_sd_total_pre"] = np.where(good, sdt, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = (smt / den) / (sdm * sdt)
    t["ot_corr_mt_pre"] = np.where(good, np.where(t.home, 1.0, -1.0) * corr, np.nan)
    # team points versus expected margin, bins of 2 points
    b = np.floor(t.ot_exp_margin_pre / 2.0).clip(-8, 7)
    t["mbin"] = b
    okr = t.resid.notna() & b.notna()
    s = before(t, np.where(okr, t.resid, 0.0), by=("mbin",)); n = before(t, okr.astype(float), by=("mbin",))
    t["tm_resid_bin_pre"] = np.where(b.notna(), s / (n + 50.0), np.nan)
    t["tm_exp_pts_curve_pre"] = t.ot_exp_pts_pre + t.tm_resid_bin_pre
    return t


def _pyth(pf, pa):
    with np.errstate(invalid="ignore", divide="ignore"):
        return 1.0 / (1.0 + (pa / pf) ** 14)


def _p20(run: int, rem: int, p: float) -> float:
    """P(a run of >= 20 consecutive wins is reached within the next `rem` games | current run, constant per-game win probability p)."""
    if run >= 20: return 1.0
    f = np.zeros(21); f[20] = 1.0
    for _ in range(rem):
        nf = np.empty(21); nf[20] = 1.0
        nf[:20] = p * f[1:21] + (1.0 - p) * f[0]
        f = nf
    return float(f[run])


def _season(t: pd.DataFrame) -> pd.DataFrame:
    t["win"] = (t.pts > t.opp_pts).astype(float); t["one"] = 1.0
    ks = ("team", "sidx")
    gp, w, pf, pa = _prev(t, "one", ks), _prev(t, "win", ks), _prev(t, "pts", ks), _prev(t, "opp_pts", ks)
    tot = t.groupby(["team", "sidx"]).agg(ppf=("pts", "sum"), ppa=("opp_pts", "sum")).reset_index(); tot["sidx"] += 1
    t = t.merge(tot, on=["team", "sidx"], how="left")
    exp_pct = 0.5 + 0.7 * (_pyth(t.ppf, t.ppa) - 0.5)
    t["eo_exp_wins_pre"] = 82.0 * exp_pct
    t["eo_surprise_pre"] = (w - t.eo_exp_wins_pre * gp / 82.0) / 6.0
    cur = np.where(gp >= 5, _pyth(pf, pa), exp_pct)
    t["eo_proj_wins_pre"] = w + (82.0 - gp) * cur
    # win streak
    run = np.zeros(len(t)); last: dict = {}
    for i, (k, wn) in enumerate(zip(zip(t.team, t.sidx), t.win)):
        r = last.get(k, 0.0); run[i] = r; last[k] = r + 1.0 if wn == 1.0 else 0.0
    t["ws_run_pre"] = run
    t["ws_p_game_pre"] = (w + 5.0) / (gp + 10.0)
    t["ws_p20_pre"] = [_p20(int(r), int(max(82 - g, 0)), float(p)) for r, g, p in zip(run, gp, t.ws_p_game_pre)]
    return t


def _lineup(t: pd.DataFrame, raw: dict) -> pd.DataFrame:
    """Availability-adjusted rating PROXY: impact = shrunk box plus-minus per 48, baseline shares from the team's last 30 games, expected-active set = players who appeared in the team's previous game."""
    p = raw["player_games"]; p = p[(p.season_type == "regular") & (p.played == True) & (p.minutes > 0)].copy()   # noqa: E712
    p["date"] = pd.to_datetime(p.game_date_et); p = p.sort_values(["date", "game_id", "nba_id"], kind="mergesort")
    hist = {}
    for pid, g in p.groupby("nba_id", sort=False):
        hist[pid] = (g.date.to_numpy(), np.cumsum(g.plus_minus.to_numpy(float)), np.cumsum(g.minutes.to_numpy(float)))

    def impact(pid, d):
        dts, cpm, cmin = hist[pid]; j = int(np.searchsorted(dts, d, side="left"))
        return 0.0 if j == 0 else 48.0 * cpm[j - 1] / (cmin[j - 1] + 600.0)

    byg = {k: (g.nba_id.to_numpy(), g.minutes.to_numpy(float)) for k, g in p.groupby(["game_id", "team_id"], sort=False)}
    cols = ("la_ibar_pre", "la_adj_pre", "la_out_share_pre", "la_out_impact_pre"); out = {c: np.full(len(t), np.nan) for c in cols}
    for team, g in t.groupby("team", sort=False):
        gids = g.game_id.tolist(); idx = g.index.to_numpy(); dts = g.date.to_numpy()
        for i in range(len(gids)):
            if i < 5: continue
            M: dict = {}
            for gid in gids[max(0, i - 30):i]:
                ids, mins = byg.get((gid, team), ((), ()))
                for a, b in zip(ids, mins): M[a] = M.get(a, 0.0) + b
            tot = sum(M.values())
            if tot <= 0: continue
            A = set(byg.get((gids[i - 1], team), ((), ()))[0])
            imp = {a: impact(a, dts[i]) for a in M}
            ibar = sum(M[a] / tot * imp[a] for a in sorted(M))
            sa = sum(M[a] for a in sorted(M) if a in A)
            if sa <= 0: continue
            act = sum(M[a] / sa * imp[a] for a in sorted(M) if a in A)
            top8 = sorted(M, key=lambda a: (-M[a], a))[:8]; outp = [a for a in top8 if a not in A]
            j = idx[i]
            out["la_ibar_pre"][j] = ibar; out["la_adj_pre"][j] = act - ibar
            out["la_out_share_pre"][j] = sum(M[a] / tot for a in outp); out["la_out_impact_pre"][j] = sum(M[a] / tot * (imp[a] - ibar) for a in outp)
    for c in cols: t[c] = out[c]
    return t


def compute(raw: dict) -> dict:
    t = _table(raw)
    t = _rating_blowout(t); t = _final_margin(t); t = _own_totals(t); t = _season(t); t = _lineup(t, raw)
    t["season"] = t.sidx
    out = t[["game_id", "team", "date", "season"] + [c for s in specs() for c in s.columns]].copy()
    return {"team": out.loc[:, ~out.columns.duplicated()]}


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, lvl, d, done, miss, raw=("espn_team_games",): FeatureSpec(S, cid, "team", cols, lvl, d, done, miss, list(raw), "pregame_rolling")
    return [
        F("nba.rating_blowout_minutes_curve", ["rb_adjnet_pre", "rb_mu_pre", "rb_sd_pre", "rb_p15_pre", "rb_p20_pre", "rb_st_close_pre", "rb_st_blow_pre", "rb_exp_stmin_pre"], "PARTIAL",
          "one-step opponent-adjusted net rating per 100 possessions (EWMA half-life 25 games), expected margin = rating gap x geometric-mean pace / 100 + league home margin over earlier dates, league residual sd of the final margin versus that expectation, normal P(|margin| >= 15 / 20), and the team's mean regulation-normalised starter minutes in earlier close (<10) and blowout (>=20) games combined by the blowout probability",
          ["opponent-adjusted net rating with a 25-game half-life", "expected margin with home advantage from earlier games", "margin sd from residuals", "blowout probabilities at 15 and 20", "starter minutes versus final-margin class"],
          ["ridge regression rating and the pre-season prior", "adjustment for confirmed unavailable players", "heavy-tailed margin distribution", "per-player minutes-versus-margin curves and coach effects", "5-season fitting window (three seasons archived)"], ("espn_team_games", "espn_player_games")),
        F("nba.final_margin_pmf_empirical", ["fm_p_win_pre", "fm_p_gt5_pre", "fm_p_gt10_pre"], "PARTIAL",
          "empirical distribution of the standardised final margin z = (margin - own-model mean)/own-model sd over home rows of earlier dates (>= 200), read at this game's own mean and sd: P(win), P(margin > 5), P(margin > 10) from the team's side",
          ["standardisation by own-model mean and sd", "empirical band probabilities from earlier games only"], ["15-season sample (three seasons archived)", "kernel smoothing of the z density", "per-integer multiplicative correction in [-12, 12]", "held-out log-loss validation"]),
        F("nba.own_model_team_totals", ["ot_exp_pts_pre", "ot_exp_total_pre", "ot_exp_margin_pre", "ot_sd_team_pre", "ot_sd_margin_pre", "ot_sd_total_pre", "ot_corr_mt_pre"], "PARTIAL",
          "possessions = product of both teams' paces (last 20 games, half-life 8, shrunk to the league mean with k = 15) over the league mean; points per possession = offence (EWMA 20, shrunk k = 20) + opponent defence - league + half the league home edge; team points, total and margin; residual sd by team; league residual sd of margin and total and their correlation",
          ["pace composition with the stated window, half-life and shrinkage", "offence versus opponent defence with home adjustment and k = 20 shrinkage", "team points = possessions x ppp", "residual sd by team from own predictions", "joint margin/total second moments"],
          ["lineup-aware pace", "availability-adjusted offence and defence", "5 seasons of residuals (three archived)"]),
        F("nba.team_points_margin_curve", ["tm_resid_bin_pre", "tm_exp_pts_curve_pre"], "PARTIAL",
          "mean realised-minus-expected team points over earlier team rows in the same 2-point bin of the own-model expected margin (bins clipped to [-16, 16)), shrunk to zero with 50 pseudo-rows, and expected points plus that correction",
          ["residual team points by 2-point expected-margin bin", "ratings-based (not spread-based) expected margin from earlier games only"], ["monotone spline", "total environment covariate", "leave-one-season-out cross-validation", "confirmed-inactive adjustment", "5 seasons (three archived)"]),
        F("nba.expectation_overperformance", ["eo_exp_wins_pre", "eo_surprise_pre", "eo_proj_wins_pre"], "PARTIAL",
          "expected wins = 82 x pythagorean (exponent 14) win% of the previous season's points for/against regressed 30% to .500; surprise = (wins to date - expected wins x GP/82)/6; projected wins = wins to date + (82 - GP) x current pythagorean win% (pre-season value before 5 games)",
          ["pythagorean exponent 14", "30% regression to the league mean", "surprise formula in units of 6 wins", "projected wins from the current rating"], ["pre-season rating from the minutes-weighted projected rotation impact (previous-season team points used instead)", "0.6/0.4 last-season/career player weights", "current own rating from nba.ratings (season-to-date pythagorean used)"]),
        F("nba.team_win_streak_hazard", ["ws_run_pre", "ws_p_game_pre", "ws_p20_pre"], "PARTIAL",
          "current run of consecutive wins this season, shrunk season win probability (W + 5)/(GP + 10), and the exact run-length recursion (state 0..19, absorbing 20) for P(a 20-game winning streak within the remaining 82 - GP games) at that constant probability",
          ["current run carried in", "exact dynamic-programming recursion with an absorbing state at 20"], ["per-game probabilities from the shared season simulation (a constant team probability is used)", "Cup knockout games and schedule", "consistency across teams from shared paths"]),
        F("nba.lineup_adj_rating", ["la_ibar_pre", "la_adj_pre", "la_out_share_pre", "la_out_impact_pre"], "PROXY",
          "PROXY: player impact = box plus-minus per 48 minutes shrunk to zero with 600 minutes (all earlier games); baseline minute shares from the team's last 30 games; expected-active set = the players who appeared in the team's previous game; adj = share-weighted impact of that set minus the baseline rotation impact; minute share and impact of top-8 rotation players outside the set",
          ["adj = sum of minute share x (impact - baseline impact) over an expected-active set", "baseline rotation over the last 30 games"],
          ["multi-season ridge RAPM (shrunk box plus-minus used instead)", "tonight's expected-active set from the latest injury-report vintage (previous-game participants used instead)", "projected minutes from nba.minutes", "with/without validation"], ("espn_team_games", "espn_player_games")),
    ]
