"""MLB batch 7, team rows (RESEARCH_ONLY): recent-lineup strikeout rate by pitcher hand, team offence by pitcher hand (wOBA index), and a negative-binomial team-runs
distribution. Built from the archived Stats API post-game feeds via mlb_pa_core (chronology, rights and table definitions there).

Output `team` keyed (game_id, team) for every team-game of season >= OUT_FIRST. Every value for a row dated d uses only games with avail_date < d (first-pitch dating;
suspended games withheld until completed); season windows are seasons S-1 and S of the row; league constants of season S come from season S-1 only.

Recent lineup of (g, T): batters with plate appearances for T in T's last LINEUP_GAMES games (avail < d, ordered by (date, game_id)); weight w_b = b's PA in those games / all PA.
The game's own lineup and the opposing starter's hand are NOT known pregame in this archive (no pre-game lineup or probable-pitcher vintages): both hands are output.

mlb.lineup_k_platoon  lkp_k_vs_{r,l}_pre = sum_b w_b (K_bh + 200 lgK_h)/(PA_bh + 200) over b's PAs (any team) vs pitchers throwing h in seasons S-1..S; lkp_k_vs_{r,l}_rel_pre = / lgK_h.
mlb.team_wrc_vs_hand  wrc_woba_vs_{r,l}_pre = sum_b w_b (num_bh + 300 lgW_h)/(den_bh + 300) (fixed linear weights, mlb_pa_core.WOBA_W); wrc_idx_vs_{r,l}_pre = 100 x woba / lgW_h;
                      wrc_team_split_vs_{r,l}_pre = the team's own raw wOBA vs h over its PAs as the batting team in seasons S-1..S (NaN if none).
mlb.run_dist          rd_mu_pre = off_T x def_O / lg_runs, off_T = EWM (half-life 30 games, games in completion order (avail, date, game_id)) of T's runs over its games with avail < d, def_O = EWM of O's runs allowed, lg_runs = S-1 runs per team-game;
                      rd_phi_pre = n/(n+50) phi_T + 50/(n+50) phi_lg, phi = max(var - mean, 0)/mean^2 of runs (T's games in S-1..S with avail < d, n games; league: all team-games of S-1);
                      rd_corr_pre = Pearson correlation of home and away runs over the games of S-1; rd_p_ge{3,4,5,6}_pre = P(runs >= k) under NB(mean rd_mu_pre, phi rd_phi_pre)
                      (Poisson when phi = 0).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from . import mlb_pa_core as C
from .core import FeatureSpec

S = "MLB"
FIRST_SEASON = 2022
OUT_FIRST = FIRST_SEASON + 1
LINEUP_GAMES = 10
K_K, K_WOBA = 200.0, 300.0
HL_RUNS = 30.0
PHI_K = 50.0
CONTENT = C.PA_CONTENT
load_raw = C.load_raw


def lineup_weights(tg: pd.DataFrame, p: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """rows (game_id, team, date): -> (game_id, team, bat, w)."""
    prev = C.last_n_games(tg, rows, LINEUP_GAMES)
    bt = p.groupby(["game_id", "bat_team", "bat"]).size().rename("n").reset_index().rename(columns={"game_id": "prev_gid", "bat_team": "team"})
    u = prev.merge(bt, on=["prev_gid", "team"], how="inner").groupby(["game_id", "team", "bat"], sort=True).n.sum().reset_index()
    u["w"] = u.n / u.groupby(["game_id", "team"]).n.transform("sum")
    return u.drop(columns="n")


def lineup_vs_hand(tg: pd.DataFrame, p: pd.DataFrame, rows: pd.DataFrame, lg: dict) -> pd.DataFrame:
    """rows (game_id, team, date, season) -> per row lineup K% and wOBA vs R and vs L (regressed per batter, PA-share weighted)."""
    w = lineup_weights(tg, p, rows).merge(rows[["game_id", "team", "date", "season"]], on=["game_id", "team"], how="left")
    w = w.reset_index(drop=True); w["row_id"] = np.arange(len(w))
    out = rows[["game_id", "team"]].copy()
    for h in ("R", "L"):
        ph = p[p.throws == h].assign(one=1.0)
        s = C.window_sums(ph, "bat", w[["row_id", "bat", "date", "season"]], ["one", "k", "woba_num", "woba_den"])
        lk = np.array([lg[x][f"k_{h}"] for x in w.season - 1]); lw = np.array([lg[x][f"woba_{h}"] for x in w.season - 1])
        s = s.loc[w.row_id]
        w[f"k_{h}"] = w.w.to_numpy() * ((s.k.to_numpy() + K_K * lk) / (s.one.to_numpy() + K_K))
        w[f"wo_{h}"] = w.w.to_numpy() * ((s.woba_num.to_numpy() + K_WOBA * lw) / (s.woba_den.to_numpy() + K_WOBA))
    agg = w.groupby(["game_id", "team"])[["k_R", "k_L", "wo_R", "wo_L"]].sum().reset_index()
    return out.merge(agg, on=["game_id", "team"], how="left")


def _ewm_state(tg: pd.DataFrame, col: str, hl: float) -> np.ndarray:
    r = 0.5 ** (1.0 / hl); out = np.empty(len(tg)); num = den = 0.0; prev = None
    for i, (t, x) in enumerate(zip(tg.team.to_numpy(), tg[col].to_numpy(float))):
        if t != prev:
            num = den = 0.0; prev = t
        num = num * r + x; den = den * r + 1.0; out[i] = num / den
    return out


LKP_COLS = ["lkp_k_vs_r_pre", "lkp_k_vs_l_pre", "lkp_k_vs_r_rel_pre", "lkp_k_vs_l_rel_pre"]
WRC_COLS = ["wrc_woba_vs_r_pre", "wrc_woba_vs_l_pre", "wrc_idx_vs_r_pre", "wrc_idx_vs_l_pre", "wrc_team_split_vs_r_pre", "wrc_team_split_vs_l_pre"]
RD_COLS = ["rd_mu_pre", "rd_phi_pre", "rd_corr_pre"] + [f"rd_p_ge{k}_pre" for k in (3, 4, 5, 6)]
ALL = LKP_COLS + WRC_COLS + RD_COLS


def compute(raw: dict) -> dict:
    g, p = C.prepared(raw)
    lg = {s: C.league(p, s) for s in sorted(p.season.unique())}
    tg = C.team_games(g)
    rows = tg[tg.season >= OUT_FIRST][["game_id", "team", "opp", "date", "season"]].sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    lv = lineup_vs_hand(tg, p, rows, lg)
    f = rows.merge(lv, on=["game_id", "team"], how="left")
    prevs = (f.season - 1).to_numpy()
    lgk = {h: np.array([lg[s][f"k_{h}"] for s in prevs]) for h in "RL"}; lgw = {h: np.array([lg[s][f"woba_{h}"] for s in prevs]) for h in "RL"}
    for h, hh in (("R", "r"), ("L", "l")):
        f[f"lkp_k_vs_{hh}_pre"] = f[f"k_{h}"]; f[f"lkp_k_vs_{hh}_rel_pre"] = f[f"k_{h}"] / lgk[h]
        f[f"wrc_woba_vs_{hh}_pre"] = f[f"wo_{h}"]; f[f"wrc_idx_vs_{hh}_pre"] = 100.0 * f[f"wo_{h}"] / lgw[h]
        ts = C.window_sums(p[p.throws == h], "bat_team", f.assign(row_id=np.arange(len(f)), bat_team=f.team)[["row_id", "bat_team", "date", "season"]], ["woba_num", "woba_den"])
        f[f"wrc_team_split_vs_{hh}_pre"] = np.where(ts.woba_den.to_numpy() > 0, ts.woba_num.to_numpy() / np.where(ts.woba_den.to_numpy() > 0, ts.woba_den.to_numpy(), 1.0), np.nan)
    # runs distribution
    # EWM in COMPLETION order (avail, date, game_id): a suspended game enters a team's state only once it is complete, so the state read at the last game with
    # avail < d never contains a game completed on/after d (ordering by first pitch would leak it through a later regular game)
    st = tg.sort_values(["team", "avail", "date", "game_id"], kind="mergesort").reset_index(drop=True)
    st["off"] = _ewm_state(st, "runs", HL_RUNS); st["dfn"] = _ewm_state(st, "runs_allowed", HL_RUNS)
    st = st.sort_values(["avail", "date", "game_id", "team"], kind="mergesort")
    o1 = pd.merge_asof(f[["date", "team"]].assign(i=np.arange(len(f))).sort_values("date"), st[["avail", "team", "off"]].rename(columns={"avail": "date"}), on="date", by="team",
                       allow_exact_matches=False, direction="backward").set_index("i").sort_index()
    o2 = pd.merge_asof(f[["date", "opp"]].assign(i=np.arange(len(f))).sort_values("date"), st[["avail", "team", "dfn"]].rename(columns={"avail": "date", "team": "opp"}), on="date", by="opp",
                       allow_exact_matches=False, direction="backward").set_index("i").sort_index()
    seas = {s: tg[tg.season == s] for s in sorted(tg.season.unique())}
    lg_runs = np.array([seas[s].runs.mean() for s in prevs])
    def _phi(m, v):
        return np.where(m > 0, np.maximum(v - m, 0.0) / np.where(m > 0, m, 1.0) ** 2, 0.0)
    lg_phi = np.array([float(_phi(seas[s].runs.mean(), seas[s].runs.var(ddof=1))) for s in prevs])
    gg = {s: g[g.season == s] for s in sorted(g.season.unique())}
    lg_corr = np.array([float(np.corrcoef(gg[s].h_r.to_numpy(float), gg[s].a_r.to_numpy(float))[0, 1]) for s in prevs])
    tg1 = tg.assign(one=1.0, r2=tg.runs ** 2)
    ws = C.window_sums(tg1.rename(columns={"team": "tm"}), "tm", f.assign(row_id=np.arange(len(f)), tm=f.team)[["row_id", "tm", "date", "season"]], ["one", "runs", "r2"])
    n = ws.one.to_numpy(); m = np.where(n > 0, ws.runs.to_numpy() / np.where(n > 0, n, 1.0), np.nan)
    v = np.where(n > 1, (ws.r2.to_numpy() - n * m ** 2) / np.where(n > 1, n - 1, 1.0), np.nan)
    phi_t = np.where(n > 1, _phi(m, v), 0.0)
    f["rd_mu_pre"] = o1.off.to_numpy() * o2.dfn.to_numpy() / lg_runs
    f["rd_phi_pre"] = n / (n + PHI_K) * phi_t + PHI_K / (n + PHI_K) * lg_phi
    f["rd_corr_pre"] = lg_corr
    mu = f.rd_mu_pre.to_numpy(float); ph = f.rd_phi_pre.to_numpy(float)
    for k in (3, 4, 5, 6):
        with np.errstate(divide="ignore", invalid="ignore"):
            nb = stats.nbinom.sf(k - 1, 1.0 / np.where(ph > 0, ph, 1.0), (1.0 / np.where(ph > 0, ph, 1.0)) / ((1.0 / np.where(ph > 0, ph, 1.0)) + mu))
        f[f"rd_p_ge{k}_pre"] = np.where(np.isnan(mu), np.nan, np.where(ph > 0, nb, stats.poisson.sf(k - 1, mu)))
    out = f[["game_id", "team", "opp", "date", "season"] + ALL].copy()
    for c in ALL:
        out[c] = out[c].astype("float64")
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


RAW = ["MLB Stats API post-game feed 2022-2026 (plays: batter, pitcher, hand, event, pitch codes; linescore; box starters), sift-data-vault archives/MLB/postgame_feed_compact"]
LINEUP_MISSING = ["confirmed batting order and slot PA weights (mlb.lineup_pit: prospective capture; the recent-lineup PA share is used)",
                  "the opposing starter's hand (no pre-game probable-pitcher vintages: both hands are output)"]


def specs() -> list[FeatureSpec]:
    return [
        FeatureSpec(S, "mlb.lineup_k_platoon", "team", LKP_COLS, "PARTIAL",
                    "Recent-lineup strikeout rate vs right- and left-handed pitchers: each batter's K% vs that hand over seasons S-1..S regressed to the S-1 league rate with 200 PA, weighted by his "
                    "share of the team's PA in its last 10 games; also relative to the league rate",
                    ["per-batter K% vs RHP / LHP regressed by PA", "weighted sum to a lineup K%", "comparison to the league baseline"], LINEUP_MISSING + ["scaling by the team's total PA"], RAW),
        FeatureSpec(S, "mlb.team_wrc_vs_hand", "team", WRC_COLS, "PARTIAL",
                    "Recent-lineup offence vs RHP and vs LHP: each batter's wOBA vs that hand (fixed linear weights) regressed to the S-1 league wOBA vs the hand with 300 PA, PA-share weighted; "
                    "index = 100 x lineup wOBA / league wOBA vs the hand; and the team's own raw wOBA split vs the hand",
                    ["batter splits by pitcher hand, regressed", "PA-weighted lineup sum", "comparison with the team-level split"],
                    LINEUP_MISSING + ["park adjustment (park factors not built)", "season-specific wOBA / wRC+ constants (fixed weights used)"], RAW),
        FeatureSpec(S, "mlb.run_dist", "team", RD_COLS, "PARTIAL",
                    "Negative-binomial team-runs distribution: mean = team runs EWM x opponent runs-allowed EWM / league (half-life 30 games), overdispersion = team dispersion over seasons S-1..S shrunk "
                    "(n/(n+50)) to the S-1 league value, between-team correlation of runs in S-1, and P(runs >= 3..6)",
                    ["negative-binomial team runs with overdispersion", "between-team correlation by season"],
                    ["park, weather and pitching covariates", "inning-level compound model / half-inning simulation", "correlation is not used inside the marginal probabilities"], RAW),
    ]
