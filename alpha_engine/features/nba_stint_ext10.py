"""NBA batch 10 (RESEARCH_ONLY): on-court player inputs from five-man stints and play-by-play events (2024-25 and 2025-26), the nba-edge-finder history archive
(data/history/espn_pbp: pbp_games, pbp_events, stints; ESPN-derived, UNRESOLVED_INTERNAL_ONLY). No line or price anywhere.

Rows keyed (game_id, team) where `team` holds the PLAYER id (ESPN athlete id as stored, negative ints); `pteam` = his club.

DEFINITIONS (every value for a row dated d uses only games dated strictly before d)
  Games: pbp_games rows with status_completed true; date = start_time_utc converted to America/New_York, calendar date; ordered (date, game_id).
  Stint of an event: the stint of the same game with start_order <= order < end_order. Only CERTIFIED stints are used for on-court quantities.
  Events (team = the event's team_id): FG attempt = shooting_play true and type_text not starting with "Free Throw"; made = scoring_play true; three = made with score_value == 3, or a miss
  whose text contains "three point" (case-insensitive). Assisted made FG: made with p2 present (assister p2). Rebound: type_text "Offensive Rebound" / "Defensive Rebound" (p1 missing =
  team rebound). Live free throw = type_text in {"Free Throw - 1 of 1", "Free Throw - 2 of 2", "Free Throw - 3 of 3"}; a miss = scoring_play false. Points of an event: score_value when scoring.
  Per certified stint and on-court player (his side = home/away of the stint; his club = that side's team id):
    sec, poss (that side's possessions), tm_fgm, tm_ast_fgm (made FG of his club in the stint, assisted ones), ast (his assists), own_miss / opp_miss (FG misses + live FT misses of his club /
    of the opponent in the stint), oreb / dreb (his offensive / defensive rebounds), pts (points of his own scoring events). Summed per (game, player): a "stint game".
  Player EWM: over his stint games ordered (date, game_id), half-life H = 25, W(x) = sum r^(i-j) x_j; a row reads the state after his last stint game dated before d.
  Universe: players with a stint game for club T in T's last 5 completed games dated before d (a player for both clubs keeps the latest; ties: smaller club id).
  League priors: cumulative over all stint games dated before d (league aggregate ratios).
nba.on_court_assist_share  ocas_share_pre = (W(ast) + 300 L_share)/(W(tm_ast_fgm) + 300), L_share = sum ast / sum tm_ast_fgm over earlier dates; ocas_tm_ast_fgm_per48_pre = 2880 W(tm_ast_fgm)/W(sec);
                           ocas_exp_ast_pre = share x per48 x m / 48 with m = W(sec)/W(1)/60 (EWM minutes on court).
nba.pairing_adjusted_reb_share  prs_oreb_pct_pre = (W(oreb) + 200 L_or)/(W(own_miss) + 200); prs_dreb_pct_pre = (W(dreb) + 200 L_dr)/(W(opp_miss) + 200) (league ratios as above).
nba.lineup_conditional_component_rates  lcr_{pts,reb,ast}100_pre = 100 (W(x) + 400 L_x)/(W(poss) + 400), reb = oreb + dreb, L_x = league sum x / sum poss over earlier dates.
nba.assisted_three_passer_map   over the shooter's stint-free events (all of his made threes, any stint) in games dated before d of the same and previous season label: atp_assisted3_share_pre =
                           assisted made threes / made threes (missing if none); atp_top_passer_share_pre = max over passers p of (n_sp + 40 q_p)/(n_s + 40), n_sp = his made threes assisted by p,
                           n_s = his assisted made threes, q_p = share of the assisted made threes of p's club (the club of the latest assisted three he passed in the window) that p assisted (missing if n_s = 0).
nba.creditable_rebound_pool (club level, repeated on every player row of the club). Per completed team-game: misses = the club's FG misses + live FT misses; team_reb = its rebound
                           events with p1 missing; g_miss / g_treb = both clubs' misses / team rebounds in the game. Club EWM over its games (half-life 40):
                           crp_proj_misses_pre = W(misses)/W(1) of T + of O; crp_leakage_pre = mean over T and O of W(g_treb)/W(g_miss); crp_pool_pre = proj x (1 - leakage).
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec

S = "NBA"
H_P, H_T = 25.0, 40.0
K_SHARE, K_REB, K_100, K_PASS = 300.0, 200.0, 400.0, 40.0
PREV = 5
LIVE_FT = {"Free Throw - 1 of 1", "Free Throw - 2 of 2", "Free Throw - 3 of 3"}
EV_COLS = ["game_id", "order", "type_text", "text", "team_id", "p1", "p2", "scoring_play", "score_value", "shooting_play"]
EV_CONTENT = ["type_text", "text", "team_id", "p1", "p2", "scoring_play", "score_value", "shooting_play"]
ST_CONTENT = ["seconds", "home_poss", "away_poss", "home_pts", "away_pts"]
G_CONTENT = ["home_pts", "away_pts"]


def load_raw(hist_dir) -> dict:
    d = Path(hist_dir) / "espn_pbp"
    cat = lambda pat, cols=None: pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(str(d / pat)))], ignore_index=True)  # noqa: E731
    g = cat("pbp_games_*.parquet", ["game_id", "season", "start_time_utc", "home_team_id", "away_team_id", "home_pts", "away_pts", "status_completed"])
    g = g[g.status_completed == True].drop_duplicates("game_id").copy()  # noqa: E712
    g["game_date"] = pd.to_datetime(g.start_time_utc, utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    e = cat("pbp_events_*.parquet", EV_COLS); s = cat("stints_*.parquet")
    ids = set(g.game_id)
    return {"games": g.reset_index(drop=True), "events": e[e.game_id.isin(ids)].reset_index(drop=True), "stints": s[s.game_id.isin(ids)].reset_index(drop=True)}


def _events(e: pd.DataFrame) -> pd.DataFrame:
    e = e.copy(); tt = e.type_text.astype(str)
    sp = e.shooting_play.fillna(False).astype(bool); sc = e.scoring_play.fillna(False).astype(bool); sv = pd.to_numeric(e.score_value, errors="coerce").fillna(0)
    fga = sp & ~tt.str.startswith("Free Throw")
    e["fgm"] = (fga & sc).astype(float); e["fgmiss"] = (fga & ~sc).astype(float)
    e["three_m"] = (fga & sc & (sv == 3)).astype(float)
    e["ast_fgm"] = (fga & sc & e.p2.notna()).astype(float)
    e["ft_live_miss"] = (tt.isin(LIVE_FT) & ~sc).astype(float)
    e["oreb"] = (tt == "Offensive Rebound").astype(float); e["dreb"] = (tt == "Defensive Rebound").astype(float)
    e["team_reb"] = ((e.oreb + e.dreb > 0) & e.p1.isna()).astype(float)
    e["pts"] = np.where(sc, sv, 0).astype(float)
    e["miss"] = e.fgmiss + e.ft_live_miss
    return e


def _assign(e: pd.DataFrame, s: pd.DataFrame) -> pd.DataFrame:
    """Stint index of every event (certified stints only; -1 if none)."""
    s = s.reset_index(drop=True).copy(); s["sid"] = np.arange(len(s))
    out = np.full(len(e), -1)
    eg = e.groupby("game_id").indices; sg = s.groupby("game_id").indices
    for gid, ix in eg.items():
        if gid not in sg:
            continue
        ss = s.iloc[sg[gid]].sort_values("start_order"); so = ss.start_order.to_numpy(); eo = ss.end_order.to_numpy(); sid = ss.sid.to_numpy(); cert = ss.certified.fillna(False).to_numpy(bool)
        o = e.order.to_numpy()[ix]; k = np.searchsorted(so, o, side="right") - 1
        ok = (k >= 0) & (o < eo[np.clip(k, 0, None)]) & cert[np.clip(k, 0, None)]
        out[ix[ok]] = sid[k[ok]]
    return out


def _player_games(raw: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    g = raw["games"]; e = _events(raw["events"]); s = raw["stints"].reset_index(drop=True).copy(); s["sid"] = np.arange(len(s))
    e["sid"] = _assign(e, s)
    sc = s.merge(g[["game_id", "home_team_id", "away_team_id"]], on="game_id", how="inner")
    sc = sc[sc.certified.fillna(False).astype(bool)]
    ev = e[e.sid >= 0]
    tm = ev.groupby(["sid", "team_id"])[["fgm", "ast_fgm", "miss"]].sum().reset_index()
    rows = []
    for side, other in (("home", "away"), ("away", "home")):
        base = sc[["sid", "game_id", "seconds", f"{side}_poss", f"{side}_team_id", f"{other}_team_id"] + [f"{side}_p{i}" for i in range(1, 6)]].rename(
            columns={f"{side}_poss": "poss", f"{side}_team_id": "club", f"{other}_team_id": "oclub"})
        own = tm.rename(columns={"team_id": "club", "fgm": "tm_fgm", "ast_fgm": "tm_ast_fgm", "miss": "own_miss"})
        opp = tm.rename(columns={"team_id": "oclub", "miss": "opp_miss"})[["sid", "oclub", "opp_miss"]]
        base = base.merge(own, on=["sid", "club"], how="left").merge(opp, on=["sid", "oclub"], how="left")
        long = base.melt(id_vars=["sid", "game_id", "seconds", "poss", "club", "tm_fgm", "tm_ast_fgm", "own_miss", "opp_miss"], value_vars=[f"{side}_p{i}" for i in range(1, 6)], value_name="pid")
        rows.append(long.drop(columns="variable"))
    ps = pd.concat(rows, ignore_index=True).dropna(subset=["pid"])
    ps["pid"] = ps.pid.astype("int64")
    for c in ("tm_fgm", "tm_ast_fgm", "own_miss", "opp_miss"):
        ps[c] = ps[c].fillna(0.0)
    pe = ev[ev.p1.notna()].assign(pid=lambda x: x.p1.astype("int64")).groupby(["sid", "pid"])[["oreb", "dreb", "pts"]].sum().reset_index()
    pa = ev[ev.p2.notna() & (ev.fgm == 1)].assign(pid=lambda x: x.p2.astype("int64")).groupby(["sid", "pid"]).size().rename("ast").reset_index()
    ps = ps.merge(pe, on=["sid", "pid"], how="left").merge(pa, on=["sid", "pid"], how="left")
    for c in ("oreb", "dreb", "pts", "ast"):
        ps[c] = ps[c].fillna(0.0)
    sg = ps.groupby(["game_id", "pid", "club"], as_index=False)[["seconds", "poss", "tm_fgm", "tm_ast_fgm", "own_miss", "opp_miss", "oreb", "dreb", "pts", "ast"]].sum()
    sg = sg.merge(g[["game_id", "game_date", "season"]], on="game_id", how="inner").rename(columns={"seconds": "sec"})
    return sg.sort_values(["pid", "game_date", "game_id", "club"], kind="mergesort").reset_index(drop=True), e, g


def _wsum(keys, x, hl):
    r = 0.5 ** (1.0 / hl); out = np.empty(len(x)); acc = 0.0; prev = None
    for i, (k, v) in enumerate(zip(keys.tolist(), np.asarray(x, float).tolist())):
        if k != prev:
            acc = 0.0; prev = k
        acc = acc * r + v; out[i] = acc
    return out


OCAS = ["ocas_share_pre", "ocas_tm_ast_fgm_per48_pre", "ocas_exp_ast_pre"]
PRS = ["prs_oreb_pct_pre", "prs_dreb_pct_pre"]
LCR = ["lcr_pts100_pre", "lcr_reb100_pre", "lcr_ast100_pre"]
ATP = ["atp_assisted3_share_pre", "atp_top_passer_share_pre"]
CRP = ["crp_proj_misses_pre", "crp_leakage_pre", "crp_pool_pre"]
ALL = OCAS + PRS + LCR + ATP + CRP


def _league_cum(sg: pd.DataFrame, dates: pd.Series, num: str, den: str) -> np.ndarray:
    """League aggregate num/den over stint games dated strictly before each date (missing before any)."""
    tot = sg.groupby("game_date")[[num, den]].sum().sort_index().cumsum()
    idx = np.searchsorted(tot.index.to_numpy(), dates.to_numpy(), side="left") - 1
    a = np.where(idx >= 0, tot[num].to_numpy()[np.clip(idx, 0, None)], 0.0); b = np.where(idx >= 0, tot[den].to_numpy()[np.clip(idx, 0, None)], 0.0)
    return np.where(b > 0, a / np.where(b > 0, b, 1.0), np.nan)


def compute(raw: dict) -> dict:
    sg, e, g = _player_games(raw)
    k = sg.pid.to_numpy(); st = sg[["pid", "game_date"]].copy()
    for c in ("sec", "poss", "tm_ast_fgm", "own_miss", "opp_miss", "oreb", "dreb", "pts", "ast"):
        st["W_" + c] = _wsum(k, sg[c], H_P)
    st["W_one"] = _wsum(k, np.ones(len(sg)), H_P)
    # team-games and universe
    tg = pd.concat([g.assign(team=g.home_team_id, opp=g.away_team_id), g.assign(team=g.away_team_id, opp=g.home_team_id)])[["game_id", "season", "game_date", "team", "opp"]]
    tg = tg.sort_values(["team", "game_date", "game_id"], kind="mergesort").reset_index(drop=True)
    prev = []
    for team, rows in tg.groupby("team", sort=True):
        hd = rows.game_date.to_numpy(); hg = rows.game_id.to_numpy(); n = np.searchsorted(hd, hd, side="left")
        for o in range(1, PREV + 1):
            kk = n - o; ok = kk >= 0
            prev.append(pd.DataFrame({"game_id": hg[ok], "team": team, "prev_gid": hg[kk[ok]]}))
    pv = pd.concat(prev, ignore_index=True)
    inv = sg[["game_id", "club", "pid", "game_date"]].rename(columns={"game_id": "prev_gid", "club": "team", "game_date": "pd"})
    u = pv.merge(inv, on=["prev_gid", "team"], how="inner").groupby(["game_id", "team", "pid"], sort=True)["pd"].max().reset_index()
    u = u.sort_values(["game_id", "pid", "pd", "team"], ascending=[True, True, False, True], kind="mergesort").drop_duplicates(["game_id", "pid"]).drop(columns="pd")
    u = u.merge(tg[["game_id", "team", "opp", "season", "game_date"]], on=["game_id", "team"], how="left").sort_values(["game_date", "pid"], kind="mergesort")
    f = pd.merge_asof(u, st.sort_values("game_date", kind="mergesort"), on="game_date", by="pid", allow_exact_matches=False, direction="backward")
    f = f.sort_values(["game_date", "game_id", "pid"], kind="mergesort").reset_index(drop=True)
    dts = f.game_date
    sg2 = sg.assign(reb=sg.oreb + sg.dreb)
    L = {"share": _league_cum(sg2, dts, "ast", "tm_ast_fgm"), "or": _league_cum(sg2, dts, "oreb", "own_miss"), "dr": _league_cum(sg2, dts, "dreb", "opp_miss"),
         "pts": _league_cum(sg2, dts, "pts", "poss"), "reb": _league_cum(sg2, dts, "reb", "poss"), "ast": _league_cum(sg2, dts, "ast", "poss")}
    f["ocas_share_pre"] = (f.W_ast + K_SHARE * L["share"]) / (f.W_tm_ast_fgm + K_SHARE)
    f["ocas_tm_ast_fgm_per48_pre"] = 2880.0 * f.W_tm_ast_fgm / f.W_sec.where(f.W_sec > 0)
    f["ocas_exp_ast_pre"] = f.ocas_share_pre * f.ocas_tm_ast_fgm_per48_pre * (f.W_sec / f.W_one / 60.0) / 48.0
    f["prs_oreb_pct_pre"] = (f.W_oreb + K_REB * L["or"]) / (f.W_own_miss + K_REB)
    f["prs_dreb_pct_pre"] = (f.W_dreb + K_REB * L["dr"]) / (f.W_opp_miss + K_REB)
    for x, w in (("pts", f.W_pts), ("reb", f.W_oreb + f.W_dreb), ("ast", f.W_ast)):
        f[f"lcr_{x}100_pre"] = 100.0 * (w + K_100 * L[x]) / (f.W_poss + K_100)
    # assisted-three passer map (counts over the same and previous season label, games before d)
    th = e[(e.three_m == 1) & e.p1.notna()].merge(g[["game_id", "game_date", "season"]], on="game_id", how="inner")
    th = th.assign(pid=th.p1.astype("int64"), passer=th.p2.astype("Int64"))
    seasons = sorted(g.season.unique()); prev_s = {s_: (seasons[i - 1] if i > 0 else None) for i, s_ in enumerate(seasons)}
    a3, top = np.full(len(f), np.nan), np.full(len(f), np.nan)
    for (s_, d_), idx in f.groupby(["season", "game_date"]).indices.items():
        w = th[(th.game_date < d_) & th.season.isin([s_, prev_s[s_]])]
        if not len(w):
            continue
        tot = w.groupby("pid").size(); asd = w[w.passer.notna()]
        nas = asd.groupby("pid").size(); nsp = asd.groupby(["pid", "passer"]).size()
        club_of = asd.sort_values(["game_date", "game_id", "order"], kind="mergesort").groupby("passer").team_id.last()     # the passer's club = club of his latest assisted three
        q_all = asd.groupby(["team_id", "passer"]).size(); q_tot = asd.groupby("team_id").size()
        q = (q_all / q_tot.reindex(q_all.index.get_level_values(0)).to_numpy())
        rows = f.iloc[idx]
        for j, pid in zip(idx, rows.pid.to_numpy()):
            if pid not in tot.index:
                continue
            ns = float(nas.get(pid, 0)); a3[j] = ns / float(tot[pid])
            if ns == 0:
                continue
            best = 0.0
            for p, n_sp in nsp.loc[pid].items():
                c = club_of.get(p); qp = float(q.get((c, p), 0.0)) if c is not None else 0.0
                best = max(best, (float(n_sp) + K_PASS * qp) / (ns + K_PASS))
            top[j] = best
    f["atp_assisted3_share_pre"] = a3; f["atp_top_passer_share_pre"] = top
    # team-level creditable rebound pool
    tgm = e.groupby(["game_id", "team_id"]).agg(misses=("miss", "sum"), team_reb=("team_reb", "sum")).reset_index().rename(columns={"team_id": "team"})
    t2 = tg.merge(tgm, on=["game_id", "team"], how="left").fillna({"misses": 0.0, "team_reb": 0.0})
    om = t2[["game_id", "team", "misses", "team_reb"]].rename(columns={"team": "opp", "misses": "opp_misses", "team_reb": "opp_team_reb"})
    t2 = t2.merge(om, on=["game_id", "opp"], how="left").fillna({"opp_misses": 0.0, "opp_team_reb": 0.0})
    t2["g_miss"] = t2.misses + t2.opp_misses; t2["g_treb"] = t2.team_reb + t2.opp_team_reb
    t2 = t2.sort_values(["team", "game_date", "game_id"], kind="mergesort").reset_index(drop=True); kt = t2.team.to_numpy()
    ts = t2[["team", "game_date"]].copy()
    for c in ("misses", "g_miss", "g_treb"):
        ts["W_" + c] = _wsum(kt, t2[c], H_T)
    ts["W_one"] = _wsum(kt, np.ones(len(t2)), H_T); ts = ts.sort_values("game_date", kind="mergesort")
    T_ = pd.merge_asof(f[["game_date", "team"]].assign(i=np.arange(len(f))).sort_values("game_date"), ts, on="game_date", by="team", allow_exact_matches=False).set_index("i").sort_index()
    O_ = pd.merge_asof(f[["game_date", "opp"]].assign(i=np.arange(len(f))).sort_values("game_date"), ts.rename(columns={"team": "opp"}), on="game_date", by="opp", allow_exact_matches=False).set_index("i").sort_index()
    f["crp_proj_misses_pre"] = (T_.W_misses / T_.W_one + O_.W_misses / O_.W_one).to_numpy()
    lt = (T_.W_g_treb / T_.W_g_miss.where(T_.W_g_miss > 0)).to_numpy(); lo = (O_.W_g_treb / O_.W_g_miss.where(O_.W_g_miss > 0)).to_numpy()
    f["crp_leakage_pre"] = 0.5 * (lt + lo)
    f["crp_pool_pre"] = f.crp_proj_misses_pre * (1 - f.crp_leakage_pre)
    f = f.rename(columns={"team": "pteam"}).rename(columns={"pid": "team", "game_date": "date"})
    out = f[["game_id", "team", "pteam", "opp", "season", "date"] + ALL].copy()
    for c in ALL:
        out[c] = out[c].astype("float64")
    out["season"] = out.season.astype(str).str.slice(0, 4).astype(int) + 1
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


RAW = ["nba-edge-finder data/history/espn_pbp: pbp_games, pbp_events (event type, players, scoring), stints (five-man units with certification flag), 2024-25 and 2025-26"]


def specs() -> list[FeatureSpec]:
    two = "history is two seasons (2024-25, 2025-26); the catalog asks for 60 games / 2 seasons of lineup data"
    return [
        FeatureSpec(S, "nba.on_court_assist_share", "team", OCAS, "PARTIAL",
                    "Player assists / club assisted field goals while he is on court (certified stints), EWM half-life 25 games, shrunk to the league aggregate with 300 on-court assisted FGM; club "
                    "assisted FGM per 48 on-court minutes; projected assists = share x rate x EWM on-court minutes", ["share of on-court team assisted FGM", "half-life 25 games", "shrinkage k = 300",
                    "projected assists from expected team assisted FGM in projected minutes"], ["split with and without the top co-creator", "role prior (league aggregate used)", "last-60-game cap", two], RAW),
        FeatureSpec(S, "nba.pairing_adjusted_reb_share", "team", PRS, "PROXY",
                    "On-court offensive and defensive rebound percentages (own rebounds / club or opponent misses while on court, certified stints), EWM half-life 25, shrunk to the league with 200 misses",
                    ["OREB% and DREB% separately", "on-court opportunity base from stint data"], ["ridge on teammate pairing indicators", "opponent offensive-rebounding covariate",
                    "projected stint mix with availability", "standard error", two], RAW),
        FeatureSpec(S, "nba.lineup_conditional_component_rates", "team", LCR, "PROXY",
                    "On-court per-100-possession points, rebounds and assists (certified stints), EWM half-life 25, shrunk to the league rate with 400 possessions",
                    ["per-100 PTS / REB / AST", "empirical-Bayes shrinkage k = 400 possessions"], ["rates by partner set (with / without each top-3 teammate)", "tonight's expected lineup", two], RAW),
        FeatureSpec(S, "nba.assisted_three_passer_map", "team", ATP, "PROXY",
                    "Share of the shooter's made threes that were assisted, and the largest single-passer share (n_sp + 40 q_p)/(n_s + 40) with q_p the passer's share of his club's assisted threes, over "
                    "the current and previous season before the game", ["passer shares with the 40-assist prior", "assist credit from play-by-play"],
                    ["expected assisted-three makes lost given P(passer out) (needs injury-report vintages)", "replacement factor from with/without games", two], RAW),
        FeatureSpec(S, "nba.creditable_rebound_pool", "team", CRP, "PARTIAL",
                    "Club-level projected combined misses (both clubs' EWM FG + live-FT misses, half-life 40 games), team-rebound leakage ratio, and the creditable pool = misses x (1 - leakage)",
                    ["pool = FG misses + live FT misses - team rebounds", "team-level leakage over the clubs' games", "projection from both clubs' miss rates (no market total)"],
                    ["leakage regression on FT trips and out-of-bounds counts", "opponent foul-rate and arena effects", "shot-quality-based miss projection", two], RAW),
    ]
