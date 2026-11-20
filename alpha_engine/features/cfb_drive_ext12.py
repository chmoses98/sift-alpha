"""CFB batch 12 (RESEARCH_ONLY): drive-clock and scoring-timeline inputs from the archived ESPN post-game summaries (drives.previous, scoringPlays).
Source: sift-data-vault archives/CFB/espn_summary_postgame (2014-2025, 2026). ESPN-derived, UNRESOLVED_INTERNAL_ONLY. No market price enters.
The catalog names CFBD play-by-play; the ESPN drive list carries the same drive start period, duration and result, so it is used instead (stated in every spec).

EXTRACTION (load_raw)
  Game: header.competitions[0] status.type.completed true; game_id = header.id; season = header.season.year; date = (competition date UTC - 10 h) normalised (cfb_espn_ext rule);
  home / away team ids. Drives (in list order, idx 0..): team = team.id (int); period = start.period.number; secs = timeElapsed.displayValue "m:ss" in seconds (missing if absent);
  result = displayResult lower-cased; start_margin = |homeScore - awayScore| of the drive's first play (missing if no play). Scoring plays (list order): period, clock = clock.displayValue
  "m:ss" in seconds remaining, home_score, away_score (after the play).
DEFINITIONS (every row dated d uses only games dated strictly before d; constants of season S from season S-1)
  Eligible drive: team is home or away, secs present, result does not start with "end of", and start_margin < 28 or missing (garbage time excluded).
  Team-game: own_n / own_secs = its eligible drives and their seconds; opp_n / opp_secs = the opponent's; the same restricted to drives starting in period k = 1..4.
  Team window: its last 10 team-games dated before d, weight 0.8 ** j (j = 0 newest). d_own = sum w own_secs / sum w own_n; n_g = games in the window with own_n > 0;
  shrunk = (n_g d + 5 lg)/(n_g + 5), lg = season S-1 mean eligible drive seconds (per period for period values). d_allowed likewise from opp_*.
  Matchup duration D = mean of (d_own_A, d_allowed_B, d_own_B, d_allowed_A); per period D_k likewise.
  Game actuals: drives = every drive of the game whose team is home or away (any result); per period by start period; T_game = sum of secs present over those drives.
cfb.expected_possessions      raw = T_eff / D, T_eff = mean T_game over games of S-1; cep_exp_drives_pre = raw + bias, bias = mean over S-1 home rows of (actual drives - raw);
                              cep_sd_pre = SD (ddof 1) of that residual; cep_drive_secs_pre = D.
cfb.period_drive_clock_budget pdc_q{k}_exp_pre = 900 / D_k + bias_k (bias_k as above per period); pdc_q{k}_p_le4_pre = Phi((4.5 - exp)/sd_k).
cfb.period_possession_allocation  recv = 1 if the team had the game's first drive in period 1; recv2 = 1 if it had the first drive starting in period 3.
                              f = weighted (0.8 ** j, last 10 games with a first drive) mean of recv, shrunk (n f + 5 x 0.5)/(n + 5); ppa_p_receive_first_pre = 0.5 f_T + 0.5 (1 - f_O);
                              ppa_exp_drives_q1_pre = P r1 + (1 - P) k1 with r1 / k1 = S-1 mean own period-1 drives of first receivers / kickers; q3 the same with P3 = 1 - P and second-half
                              receivers; ppa_exp_drives_q2_pre / q4 = S-1 mean own drives per team-game in period 2 / 4.
cfb.leader_scoring_persistence  scoring timeline (periods 1-4): t = (period - 1) 900 + 900 - clock, margin_home after each play, state segments over [900, 3600] (Q2-Q4). For a team: minutes
                              leading by >= 14 and within one score (|margin| <= 8); its points scored on plays at t in [900, 3600] from those pre-play states. Weights 1 (season S, games before d)
                              and 0.5 (season S-1). lsp_ppm_lead14_pre = (sum w pts + 60 L)/(sum w min + 60), L = S-1 league points per minute in that state; lsp_ppm_close_pre likewise;
                              lsp_ratio_pre = lead14 / close.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec

S = "CFB"
HIST_FIRST, OUT_FIRST = 2014, 2016
WIN, DECAY, K_G = 10, 0.8, 5.0
GARBAGE = 28
DR_CONTENT = ["team", "period", "secs", "result", "start_margin"]
SC_CONTENT = ["period", "clock", "home_score", "away_score"]


def _mmss(v):
    try:
        m, s = str(v).split(":"); return float(int(m) * 60 + int(s))
    except (ValueError, TypeError, AttributeError):
        return np.nan


def _parse(j: dict):
    try:
        hd = j["header"]; co = hd["competitions"][0]
        if not co["status"]["type"]["completed"]:
            return None
        cs = {c["homeAway"]: c for c in co["competitors"]}
        g = {"game_id": int(hd["id"]), "season": int(hd["season"]["year"]), "game_date": (pd.Timestamp(co["date"]).tz_localize(None) - pd.Timedelta(hours=10)).normalize(),
             "home": int(cs["home"]["team"]["id"]), "away": int(cs["away"]["team"]["id"])}
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    dr = []
    for i, d in enumerate(((j.get("drives") or {}).get("previous")) or []):
        pl = d.get("plays") or []
        sm = abs(float(pl[0].get("homeScore") or 0) - float(pl[0].get("awayScore") or 0)) if pl else np.nan
        try:
            tm = int((d.get("team") or {}).get("id"))
        except (TypeError, ValueError):
            tm = -1
        dr.append({"game_id": g["game_id"], "idx": i, "team": tm, "period": float(((d.get("start") or {}).get("period") or {}).get("number") or np.nan),
                   "secs": _mmss((d.get("timeElapsed") or {}).get("displayValue")), "result": str(d.get("displayResult") or "").lower(), "start_margin": sm})
    sc = []
    for i, p in enumerate(j.get("scoringPlays") or []):
        sc.append({"game_id": g["game_id"], "idx": i, "period": float((p.get("period") or {}).get("number") or np.nan), "clock": _mmss((p.get("clock") or {}).get("displayValue")),
                   "home_score": float(p.get("homeScore") or 0), "away_score": float(p.get("awayScore") or 0)})
    return g, dr, sc


def load_raw(dirs) -> dict:
    d0 = Path(str(dirs).split(",")[0])
    if (d0 / "games.parquet").exists():
        r = {k: pd.read_parquet(d0 / f"{k}.parquet") for k in ("games", "drives", "scores")}
    else:
        G, D, SC = [], [], []
        for d in str(dirs).split(","):
            for f in sorted(Path(d).glob("*.json")):
                if f.name.startswith("_"):
                    continue
                x = _parse(json.loads(f.read_text()))
                if x:
                    G.append(x[0]); D.extend(x[1]); SC.extend(x[2])
        g = pd.DataFrame(G).drop_duplicates("game_id"); ids = set(g.game_id)
        r = {"games": g.reset_index(drop=True), "drives": pd.DataFrame(D).pipe(lambda x: x[x.game_id.isin(ids)]).drop_duplicates(["game_id", "idx"]).reset_index(drop=True),
             "scores": pd.DataFrame(SC).pipe(lambda x: x[x.game_id.isin(ids)]).drop_duplicates(["game_id", "idx"]).reset_index(drop=True)}
    g = r["games"]; g = g[g.season >= HIST_FIRST]; warm = set(g.game_id[g.season < OUT_FIRST])
    out = {"games": g[~g.game_id.isin(warm)].reset_index(drop=True), "games_warm": g[g.game_id.isin(warm)].reset_index(drop=True)}
    for k in ("drives", "scores"):
        x = r[k][r[k].game_id.isin(set(g.game_id))]
        out[k] = x[~x.game_id.isin(warm)].reset_index(drop=True); out[k + "_warm"] = x[x.game_id.isin(warm)].reset_index(drop=True)
    return out


def cache(dirs, out) -> None:
    r = load_raw(dirs); Path(out).mkdir(parents=True, exist_ok=True)
    for k in ("games", "drives", "scores"):
        _all(r, k).to_parquet(Path(out) / f"{k}.parquet", index=False)


def _all(raw, key):
    parts = [raw[k] for k in (key + "_warm", key) if raw.get(k) is not None and len(raw[k])]
    return pd.concat(parts, ignore_index=True) if parts else raw[key]


def _phi(x):
    return 0.5 * (1.0 + np.vectorize(math.erf)(np.asarray(x, float) / math.sqrt(2.0)))


CEP = ["cep_exp_drives_pre", "cep_sd_pre", "cep_drive_secs_pre"]
PDC = [f"pdc_q{k}_exp_pre" for k in (1, 2, 3, 4)] + [f"pdc_q{k}_p_le4_pre" for k in (1, 2, 3, 4)]
PPA = ["ppa_p_receive_first_pre"] + [f"ppa_exp_drives_q{k}_pre" for k in (1, 2, 3, 4)]
LSP = ["lsp_ppm_lead14_pre", "lsp_ppm_close_pre", "lsp_ratio_pre"]
ALL = CEP + PDC + PPA + LSP
PS = ["", "1", "2", "3", "4"]


def _team_games(raw):
    g = _all(raw, "games").drop_duplicates("game_id").copy(); g["date"] = pd.to_datetime(g.game_date)
    d = _all(raw, "drives").merge(g[["game_id", "home", "away"]], on="game_id", how="inner")
    d = d[(d.team == d.home) | (d.team == d.away)].copy()
    elig = d.secs.notna() & ~d.result.astype(str).str.startswith("end of") & ~(d.start_margin >= GARBAGE)
    rows = []
    for side, oth in (("home", "away"), ("away", "home")):
        t = g[["game_id", "season", "date", side, oth]].rename(columns={side: "team", oth: "opp"})
        rows.append(t)
    tg = pd.concat(rows, ignore_index=True)
    e = d[elig]
    for p in PS:
        ee = e if p == "" else e[e.period == int(p)]
        a = ee.groupby(["game_id", "team"]).secs.agg(["size", "sum"]).rename(columns={"size": f"n{p}", "sum": f"s{p}"}).reset_index()
        tg = tg.merge(a, on=["game_id", "team"], how="left")
        b = a.rename(columns={"team": "opp", f"n{p}": f"on{p}", f"s{p}": f"os{p}"}); tg = tg.merge(b, on=["game_id", "opp"], how="left")
    for p in PS:
        for c in (f"n{p}", f"s{p}", f"on{p}", f"os{p}"):
            tg[c] = tg[c].fillna(0.0)
    # game actuals and kick order
    act = d.groupby("game_id").agg(drv=("idx", "size"), tgame=("secs", lambda x: x.sum(min_count=0))).reset_index()
    for k in (1, 2, 3, 4):
        act = act.merge(d[d.period == k].groupby("game_id").size().rename(f"drv{k}").reset_index(), on="game_id", how="left")
    own = d.groupby(["game_id", "team"]).size().rename("own_drv").reset_index()
    for k in (1, 2, 3, 4):
        own = own.merge(d[d.period == k].groupby(["game_id", "team"]).size().rename(f"own_drv{k}").reset_index(), on=["game_id", "team"], how="left")
    first1 = d[d.period == 1].sort_values(["game_id", "idx"]).drop_duplicates("game_id")[["game_id", "team"]].rename(columns={"team": "recv_team"})
    first3 = d[d.period == 3].sort_values(["game_id", "idx"]).drop_duplicates("game_id")[["game_id", "team"]].rename(columns={"team": "recv2_team"})
    tg = tg.merge(act, on="game_id", how="left").merge(own, on=["game_id", "team"], how="left").merge(first1, on="game_id", how="left").merge(first3, on="game_id", how="left")
    for k in (1, 2, 3, 4):
        tg[f"drv{k}"] = tg[f"drv{k}"].fillna(0.0); tg[f"own_drv{k}"] = tg[f"own_drv{k}"].fillna(0.0)
    tg["recv"] = np.where(tg.recv_team.notna(), (tg.recv_team == tg.team).astype(float), np.nan)
    tg["recv2"] = np.where(tg.recv2_team.notna(), (tg.recv2_team == tg.team).astype(float), np.nan)
    tg["is_home"] = tg.team.to_numpy() == tg.merge(g[["game_id", "home"]], on="game_id", how="left").home.to_numpy()
    # scoring timeline states (Q2-Q4)
    sc = _all(raw, "scores").merge(g[["game_id", "home", "away"]], on="game_id", how="inner")
    sc = sc[sc.period.between(1, 4) & sc.clock.notna()].copy(); sc["t"] = (sc.period - 1) * 900 + 900 - sc.clock
    sc = sc.sort_values(["game_id", "t", "idx"], kind="mergesort")
    st = []
    for gid, x in sc.groupby("game_id", sort=True):
        t = x.t.to_numpy(); hs = x.home_score.to_numpy(); as_ = x.away_score.to_numpy()
        m_before = np.r_[0.0, (hs - as_)[:-1]]; dh = np.diff(np.r_[0.0, hs]); da = np.diff(np.r_[0.0, as_])
        bounds = np.r_[0.0, t, 3600.0]; marg = np.r_[0.0, hs - as_]
        out = {}
        for sgn, side in ((1.0, "h"), (-1.0, "a")):
            ml = mc = 0.0
            for i in range(len(marg)):
                lo, hi = max(bounds[i], 900.0), min(bounds[i + 1], 3600.0)
                if hi > lo:
                    if sgn * marg[i] >= 14: ml += hi - lo
                    if abs(marg[i]) <= 8: mc += hi - lo
            mine = dh if side == "h" else da; inw = (t >= 900) & (t <= 3600)
            pl = float(mine[inw & (sgn * m_before >= 14)].sum()); pc = float(mine[inw & (np.abs(m_before) <= 8)].sum())
            out[side] = (ml / 60.0, pl, mc / 60.0, pc)
        st.append((gid, *out["h"], *out["a"]))
    stt = pd.DataFrame(st, columns=["game_id", "h_ml", "h_pl", "h_mc", "h_pc", "a_ml", "a_pl", "a_mc", "a_pc"])
    tg = tg.merge(stt, on="game_id", how="left")
    for k in ("ml", "pl", "mc", "pc"):
        tg[k] = np.where(tg.is_home, tg[f"h_{k}"], tg[f"a_{k}"])
    return tg.sort_values(["team", "date", "game_id"], kind="mergesort").reset_index(drop=True), g


def _window(tg: pd.DataFrame, rows: pd.DataFrame, cols: list[str], cond: str | None = None) -> pd.DataFrame:
    """Per row: sums over the team's last WIN team-games dated before d (optionally only games with `cond` present) of w x col (w = 0.8^j) and n_g = number of games with own_n > 0."""
    out = {c: np.zeros(len(rows)) for c in cols}; out["_w"] = np.zeros(len(rows)); out["_ng"] = np.zeros(len(rows))
    by = {t: x for t, x in tg.groupby("team", sort=False)}
    for i, (t, d) in enumerate(zip(rows.team.to_numpy(), rows.date.to_numpy())):
        h = by.get(t)
        if h is None:
            continue
        h = h[h.date.to_numpy() < d]
        if cond is not None:
            h = h[h[cond].notna()]
        h = h.tail(WIN)
        if not len(h):
            continue
        w = DECAY ** np.arange(len(h) - 1, -1, -1)
        for c in cols:
            out[c][i] = float((w * h[c].to_numpy(float)).sum())
        out["_w"][i] = float(w.sum()); out["_ng"][i] = float((h["n"].to_numpy() > 0).sum())
    return pd.DataFrame(out, index=rows.index)


def compute(raw: dict) -> dict:
    tg, g = _team_games(raw)
    rows = tg[tg.season >= HIST_FIRST + 1][["game_id", "team", "opp", "season", "date", "is_home", "drv", "drv1", "drv2", "drv3", "drv4"]].copy().reset_index(drop=True)
    sea = {s_: tg[tg.season == s_] for s_ in sorted(tg.season.unique())}
    gsea = {s_: x.drop_duplicates("game_id") for s_, x in sea.items()}
    lg = {s_ + 1: {**{f"d{p}": (x[f"s{p}"].sum() / x[f"n{p}"].sum()) for p in PS}, "teff": float(gsea[s_].tgame.mean()),
                   "r1": float(x[x.recv == 1].own_drv1.mean()), "k1": float(x[x.recv == 0].own_drv1.mean()), "r3": float(x[x.recv2 == 1].own_drv3.mean()),
                   "k3": float(x[x.recv2 == 0].own_drv3.mean()), "q2": float(x.own_drv2.mean()), "q4": float(x.own_drv4.mean()),
                   "L_lead": float(x.pl.sum() / x.ml.sum()), "L_close": float(x.pc.sum() / x.mc.sum())} for s_, x in sea.items()}
    LG = lambda k, ss: np.array([lg[s_][k] if s_ in lg else np.nan for s_ in ss])  # noqa: E731
    wc = [f"s{p}" for p in PS] + [f"n{p}" for p in PS] + [f"os{p}" for p in PS] + [f"on{p}" for p in PS]
    WT = _window(tg, rows, wc); WO = _window(tg, rows.assign(team=rows.opp), wc)
    ss = rows.season.to_numpy()
    def shr(W, num, den, p):
        d_ = np.where(W[den] > 0, W[num] / np.where(W[den] > 0, W[den], 1.0), np.nan); ng = W["_ng"].to_numpy(); L = LG(f"d{p}", ss)
        d_ = np.where(np.isnan(d_), L, d_)
        return (ng * d_ + K_G * L) / (ng + K_G)
    D = {p: 0.25 * (shr(WT, f"s{p}", f"n{p}", p) + shr(WO, f"os{p}", f"on{p}", p) + shr(WO, f"s{p}", f"n{p}", p) + shr(WT, f"os{p}", f"on{p}", p)) for p in PS}
    rows["raw"] = LG("teff", ss) / D[""]
    for k in (1, 2, 3, 4):
        rows[f"raw{k}"] = 900.0 / D[str(k)]
    rows["cep_drive_secs_pre"] = D[""]
    # receiving tendency
    WR2 = _window(tg.assign(n=1.0), rows.assign(team=rows.opp), ["recv"], cond="recv")       # n = 1: every window game counts toward n_g
    def frecv(W):
        n = W["_w"].to_numpy(); cnt = W["_ng"].to_numpy()
        f = np.where(n > 0, W["recv"].to_numpy() / np.where(n > 0, n, 1.0), 0.5)
        return (cnt * f + K_G * 0.5) / (cnt + K_G)
    WR = _window(tg.assign(n=1.0), rows, ["recv"], cond="recv")
    P = 0.5 * frecv(WR) + 0.5 * (1 - frecv(WR2))
    rows["ppa_p_receive_first_pre"] = P
    rows["ppa_exp_drives_q1_pre"] = P * LG("r1", ss) + (1 - P) * LG("k1", ss)
    rows["ppa_exp_drives_q3_pre"] = (1 - P) * LG("r3", ss) + P * LG("k3", ss)
    rows["ppa_exp_drives_q2_pre"] = LG("q2", ss); rows["ppa_exp_drives_q4_pre"] = LG("q4", ss)
    # bias / SD from season S-1 home rows
    for s_ in sorted(rows.season.unique()):
        ref = rows[(rows.season == s_ - 1) & rows.is_home]; cur = (rows.season == s_).to_numpy()
        if not len(ref):
            continue
        r0 = (ref.drv - ref.raw).dropna(); rows.loc[cur, "cep_exp_drives_pre"] = rows.loc[cur, "raw"] + r0.mean(); rows.loc[cur, "cep_sd_pre"] = r0.std(ddof=1)
        for k in (1, 2, 3, 4):
            rk = (ref[f"drv{k}"] - ref[f"raw{k}"]).dropna(); e = rows.loc[cur, f"raw{k}"] + rk.mean()
            rows.loc[cur, f"pdc_q{k}_exp_pre"] = e; rows.loc[cur, f"pdc_q{k}_p_le4_pre"] = _phi((4.5 - e.to_numpy()) / rk.std(ddof=1))
    # leader scoring persistence: seasons S (w 1) and S-1 (w 0.5), games before d
    acc = {c: np.zeros(len(rows)) for c in ("ml", "pl", "mc", "pc")}
    by = {t: x for t, x in tg.groupby("team", sort=False)}
    for i, (t, d, s_) in enumerate(zip(rows.team.to_numpy(), rows.date.to_numpy(), ss)):
        h = by.get(t)
        if h is None:
            continue
        h = h[(h.date.to_numpy() < d) & h.season.isin([s_, s_ - 1]).to_numpy() & h.ml.notna().to_numpy()]
        w = np.where(h.season.to_numpy() == s_, 1.0, 0.5)
        for c in acc:
            acc[c][i] = float((w * h[c].to_numpy(float)).sum())
    rows["lsp_ppm_lead14_pre"] = (acc["pl"] + 60 * LG("L_lead", ss)) / (acc["ml"] + 60)
    rows["lsp_ppm_close_pre"] = (acc["pc"] + 60 * LG("L_close", ss)) / (acc["mc"] + 60)
    rows["lsp_ratio_pre"] = rows.lsp_ppm_lead14_pre / rows.lsp_ppm_close_pre
    out = rows[rows.season >= OUT_FIRST][["game_id", "team", "opp", "season", "date"] + ALL].copy()
    for c in ALL:
        out[c] = out[c].astype("float64")
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


RAW = ["ESPN college-football post-game summaries 2014-2026 (drives: team, start period, time elapsed, result, first-play score; scoring plays: period, clock, score), sift-data-vault"]
SRC = "source: ESPN drive list instead of CFBD play-by-play (same drive start, duration and result fields)"


def specs() -> list[FeatureSpec]:
    return [
        FeatureSpec(S, "cfb.expected_possessions", "team", CEP, "PARTIAL",
                    "Expected combined drives = previous-season mean timed seconds per game / matchup drive duration (own and allowed mean seconds per non-garbage drive of both teams, last 10 "
                    "games with 0.8 decay, shrunk to the league with 5 games), bias-corrected and with residual SD from the previous season",
                    ["mean drive duration excluding end-of-half drives and garbage time", "last 10 games with 0.8 weights, k = 5 shrinkage", "T_eff from the season clock data", "mean and SD from residuals"],
                    ["clock-regime covariate and no-huddle regressor", SRC], RAW),
        FeatureSpec(S, "cfb.period_drive_clock_budget", "team", PDC, "PARTIAL",
                    "Combined drives per quarter = 900 / matchup per-quarter drive duration (own and allowed, last 10 games with 0.8 decay, shrunk) plus the previous season's mean residual (end-of-period "
                    "truncation), and P(combined drives <= 4) from a normal with the previous season's residual SD",
                    ["per-period seconds per non-garbage drive", "end-of-period truncation as an empirical bias", "mean, SD and P(drives <= 4)"],
                    ["2023+ running-clock regime covariate", SRC], RAW),
        FeatureSpec(S, "cfb.period_possession_allocation", "team", PPA, "PROXY",
                    "P(team receives the opening kickoff) = 0.5 x its shrunk recent frequency of receiving first + 0.5 x (1 - the opponent's), and expected own drives per quarter from the previous "
                    "season's receiver / kicker drive means (Q1, Q3) and league means (Q2, Q4)",
                    ["P(team A receives first) with P(win toss) = 0.5", "second-half receiver = complement", "quarter drive allocation adjusted for receiving"],
                    ["head-coach defer preference (no toss or coach data: the team's realised receive frequency is used)", SRC], RAW),
        FeatureSpec(S, "cfb.leader_scoring_persistence", "team", LSP, "PARTIAL",
                    "Points per minute when leading by 14+ in Q2-Q4 and when within one score (scoring-play timeline), seasons S and S-1 weighted 1 / 0.5, shrunk with 60 minutes to the league rate, "
                    "and their ratio", ["points per minute leading by 14+ (Q2-Q4)", "relative to within one score", "2 seasons with 0.5 season decay", "k = 60 minutes shrinkage"],
                    ["backup substitution timing (depth-chart snaps not held)", "probability of reaching a 14-point lead from the rating gap and the expected own points", SRC], RAW),
    ]
