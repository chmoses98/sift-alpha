"""NFL play-by-play builders, batch 3 (Phase 7 data acquisition, RESEARCH_ONLY): opponent-adjusted pass/run EPA for both sides and the per-carry rushing-yardage tail.

Source: nflverse play_by_play 1999-2026 and the nflverse schedule (rights: `nflverse` in rights_registry.json, WRAPPER_LICENCE_UPSTREAM_CAVEAT, collection allowed; internal research only).
Point in time: every value for a game dated d uses rows of games dated STRICTLY BEFORE d (both inputs are recomputed per distinct game date); nothing from the game itself or any later game enters.

nfl.pass_run_split_epa_both_sides  (table "team", key game_id + team)
  Plays: regular-season (season_type REG) pbp rows with pass == 1 or rush == 1 (nflfastR flags: pass = dropback incl. sacks/scrambles, rush = designed run), qb_kneel != 1, qb_spike != 1, epa present,
  0.05 <= wp <= 0.95 (wp = nflfastR pre-play win probability WITHOUT the spread). Kind = pass if pass == 1 else rush.
  For a cutoff date d every team's last 12 regular-season games dated before d get a rank r (0 = most recent). A game observation (game, offence O, defence D, kind) enters the cutoff's fit when the game is in
  O's OR D's last-12 list; weight = plays x 0.5 ** (min(rank_O, rank_D) / 6). Per kind a weighted ridge is solved in closed form: y = EPA per play of the observation, y ~ b0 + a_O + d_D, penalty LAMBDA on every
  a and d (not b0). Team offence rating = b0 + a_T, defence rating = b0 + d_T (EPA per play FACED; higher = worse defence). Shrink to the league mean b0 with weight n / (n + K), n = unweighted plays of the
  team's entering observations on that side, K = 150 (pass) / 100 (rush).
  Neutral pass rate pA = league expected pass rate + team PROE: neutral plays = the plays above with qtr <= 3, 0.20 <= wp <= 0.80 and xpass present; league rate = mean xpass over neutral plays of every game
  entering the cutoff's fit; PROE = sum over the team's own last-12 games of 0.5 ** (rank / 6) x sum(pass - xpass) divided by the same weights x neutral-play counts.
  Blended expected EPA per play of team A against opponent B (catalog formula with defence written as EPA prevented = league - allowed, so offA - prevB = offA + allowedB - league):
  pA x (offA_pass + defB_pass - b0_pass) + (1 - pA) x (offA_rush + defB_rush - b0_rush).

nfl.rush_yardage_tail  (table "rusher", key game_id + rusher gsis id in the `team` column, as in other player-keyed builders)
  Carries: pbp rows (all season types) with rush_attempt == 1, qb_kneel != 1, rusher_player_id present and rushing_yards present. Group: QB if the nflverse players file lists the rusher as QB, else RB.
  Rusher rate for k in {7, 10, 15, 20, 30, 40}: over the rusher's carries in seasons s-2..s dated before d, newest first with index c, weight 0.5 ** (c / 25); r_k = (sum w x [yards >= k] + 60 x P_k) / (sum w + 60),
  P_k = unweighted share of carries with yards >= k by the same group over seasons s-2..s dated before d.
  Opponent: the defence's carries faced in seasons s-1..s dated before d (unweighted), explosive-allowed rate e_k = (count[yards >= k] + 100 x L_k) / (n + 100) and stuff rate (yards <= 0) shrunk the same way;
  L = league rates over the same window. Output P(yards >= k) = min(1, r_k x e_k / L_k) and the opponent stuff factor stuff_D / L_stuff.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .nfl_ext import TEAM_FIX

S = "NFL"
FIRST = 1999
LAST_N, HL_G, LAMBDA = 12, 6.0, 50.0
K_SHR = {"pass": 150.0, "rush": 100.0}
KS = (7, 10, 15, 20, 30, 40)
HL_C, K_POS, K_DEF = 25.0, 60.0, 100.0
PBP_COLS = ["game_id", "play_id", "season", "season_type", "posteam", "defteam", "qtr", "pass", "rush", "qb_kneel", "qb_spike", "epa", "wp", "xpass",
            "rush_attempt", "rusher_player_id", "rushing_yards"]
CONTENT = ["qtr", "pass", "rush", "qb_kneel", "qb_spike", "epa", "wp", "xpass", "rush_attempt", "rusher_player_id", "rushing_yards", "posteam", "defteam"]


def load_raw(pbp_dir, games_file, players_file) -> dict:
    fs = sorted(glob.glob(str(Path(pbp_dir) / "pbp_*.parquet")))
    import pyarrow.parquet as pq
    pbp = pd.concat([pd.read_parquet(f, columns=[c for c in PBP_COLS if c in pq.read_schema(f).names]) for f in fs], ignore_index=True)
    games = pd.read_csv(games_file, usecols=["game_id", "season", "week", "game_type", "gameday", "home_team", "away_team", "home_score"])
    players = pd.read_parquet(players_file, columns=["gsis_id", "position"])
    return {"pbp": pbp, "games": games, "players": players}


def _norm(s: pd.Series) -> pd.Series:
    return s.astype("object").replace(TEAM_FIX)


def _num(d: pd.DataFrame, c: str) -> pd.Series:
    return pd.to_numeric(d[c], errors="coerce") if c in d else pd.Series(np.nan, index=d.index)


def _games(games: pd.DataFrame) -> pd.DataFrame:
    g = games[(games.season >= FIRST) & games.home_score.notna()].copy()
    g["date"] = pd.to_datetime(g.gameday)
    return g


def _team_rows(g: pd.DataFrame) -> pd.DataFrame:
    rows = [g.assign(team=_norm(g[a]), opp=_norm(g[b]))[["game_id", "season", "week", "game_type", "team", "opp", "date"]] for a, b in (("home_team", "away_team"), ("away_team", "home_team"))]
    return pd.concat(rows, ignore_index=True).sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)


# ----------------------------------------------------------------------------------------------- pass / run split EPA
def _ridge(obs: pd.DataFrame) -> tuple[float, dict, dict]:
    teams = sorted(set(obs.O) | set(obs.D)); ix = {t: i for i, t in enumerate(teams)}; m = len(teams)
    nrow = len(obs); X = np.zeros((nrow, 1 + 2 * m)); X[:, 0] = 1.0
    X[np.arange(nrow), 1 + obs.O.map(ix).to_numpy()] = 1.0; X[np.arange(nrow), 1 + m + obs.D.map(ix).to_numpy()] = 1.0
    w = obs.w.to_numpy(float); y = obs.y.to_numpy(float)
    A = X.T @ (X * w[:, None]); A[np.arange(1, 1 + 2 * m), np.arange(1, 1 + 2 * m)] += LAMBDA
    beta = np.linalg.solve(A, X.T @ (w * y))
    b0 = float(beta[0])
    return b0, {t: b0 + float(beta[1 + ix[t]]) for t in teams}, {t: b0 + float(beta[1 + m + ix[t]]) for t in teams}


def _pass_run_split(p: pd.DataFrame, g: pd.DataFrame, tr: pd.DataFrame) -> pd.DataFrame:
    reg = g[g.game_type == "REG"][["game_id", "date"]]
    q = p[p.season_type == "REG"].copy()
    for c in ("pass", "rush", "qb_kneel", "qb_spike"):
        q[c] = _num(q, c).fillna(0.0)
    for c in ("epa", "wp", "xpass", "qtr"):
        q[c] = _num(q, c)
    q = q[((q["pass"] == 1) | (q["rush"] == 1)) & (q.qb_kneel != 1) & (q.qb_spike != 1) & q.epa.notna() & (q.wp >= 0.05) & (q.wp <= 0.95) & q.posteam.notna() & q.defteam.notna()]
    q = q.assign(O=_norm(q.posteam), D=_norm(q.defteam), kind=np.where(q["pass"] == 1, "pass", "rush")).merge(reg, on="game_id", how="inner")
    ob = q.groupby(["game_id", "date", "O", "D", "kind"], sort=True).agg(n=("epa", "size"), s=("epa", "sum")).reset_index()
    neu = q[(q.qtr <= 3) & (q.wp >= 0.20) & (q.wp <= 0.80) & q.xpass.notna()]
    nz = neu.groupby(["game_id", "O"], sort=True).agg(nn=("xpass", "size"), sx=("xpass", "sum"), sp=("pass", "sum")).reset_index()
    # team regular-season game list (only games that have usable plays are irrelevant here: the list is the schedule's, as the catalog's "last 12 games")
    tg = _team_rows(g[g.game_type == "REG"])[["game_id", "team", "date"]]
    out = []
    for d in sorted(tr.date.unique()):
        prev = tg[tg.date < d].sort_values(["date", "game_id"], kind="mergesort")
        last = prev.groupby("team", sort=False).tail(LAST_N).copy()
        last["rank"] = last.groupby("team", sort=False).cumcount(ascending=False)
        rk = last.set_index(["game_id", "team"])["rank"]
        o = ob[ob.date < d]
        rO = pd.Series(list(zip(o.game_id, o.O))).map(rk).to_numpy(float); rD = pd.Series(list(zip(o.game_id, o.D))).map(rk).to_numpy(float)
        keep = ~(np.isnan(rO) & np.isnan(rD))
        o = o[keep].copy(); r = np.fmin(rO[keep], rD[keep])
        o["w"] = o.n * 0.5 ** (r / HL_G); o["y"] = o.s / o.n
        res = {"d": d}
        for kind in ("pass", "rush"):
            ok = o[o.kind == kind]
            if ok.empty:
                continue
            b0, off, de = _ridge(ok)
            nO = ok.groupby("O").n.sum(); nD = ok.groupby("D").n.sum(); K = K_SHR[kind]
            res[kind] = (b0, {t: b0 + nO.get(t, 0) / (nO.get(t, 0) + K) * (v - b0) for t, v in off.items()},
                         {t: b0 + nD.get(t, 0) / (nD.get(t, 0) + K) * (v - b0) for t, v in de.items()})
        gids = set(o.game_id)
        nzc = nz[nz.game_id.isin(gids)]
        lx = nzc.sx.sum() / nzc.nn.sum() if nzc.nn.sum() > 0 else np.nan
        own = last[["game_id", "team", "rank"]].merge(nz.rename(columns={"O": "team"}), on=["game_id", "team"], how="inner")
        own["wg"] = 0.5 ** (own["rank"] / HL_G)
        den = (own.wg * own.nn).groupby(own.team).sum(); num = (own.wg * (own.sp - own.sx)).groupby(own.team).sum()
        proe = (num / den.where(den > 0)).to_dict()
        rows = tr[tr.date == d]
        for t, u, gid in zip(rows.team, rows.opp, rows.game_id):
            rec = {"game_id": gid, "team": t}
            for kind in ("pass", "rush"):
                if kind in res:
                    b0, off, de = res[kind]
                    rec[f"off_{kind}"] = off.get(t, np.nan); rec[f"def_{kind}"] = de.get(t, np.nan); rec[f"oppdef_{kind}"] = de.get(u, np.nan); rec[f"b0_{kind}"] = b0
            pa = lx + proe.get(t, np.nan)
            rec["pa"] = pa
            out.append(rec)
    f = pd.DataFrame(out)
    for c in ("off_pass", "off_rush", "def_pass", "def_rush", "oppdef_pass", "oppdef_rush", "b0_pass", "b0_rush", "pa"):
        if c not in f:
            f[c] = np.nan
    f["prs_exp_epa_pre"] = f.pa * (f.off_pass + f.oppdef_pass - f.b0_pass) + (1 - f.pa) * (f.off_rush + f.oppdef_rush - f.b0_rush)
    f = f.rename(columns={"off_pass": "prs_off_pass_pre", "off_rush": "prs_off_rush_pre", "def_pass": "prs_def_pass_pre", "def_rush": "prs_def_rush_pre", "pa": "prs_pass_rate_pre"})
    return f[["game_id", "team", "prs_off_pass_pre", "prs_off_rush_pre", "prs_def_pass_pre", "prs_def_rush_pre", "prs_pass_rate_pre", "prs_exp_epa_pre"]]


# ----------------------------------------------------------------------------------------------- rushing yardage tail
def _cum_by_date(c: pd.DataFrame, key: str | None, cols: list[str]) -> pd.DataFrame:
    """Per (key, season, date): totals on that date. Used to form 'seasons a..b, dated before d' sums by cumulative differences."""
    by = ([key] if key else []) + ["season", "date"]
    return c.groupby(by, sort=True)[cols].sum().reset_index()


def _window_sum(tot: pd.DataFrame, key: str | None, rows: pd.DataFrame, rkey: str | None, cols: list[str], back: int) -> pd.DataFrame:
    """Sum of `cols` over tot rows with the same key, season in [s-back, s] and date < row date."""
    out = np.zeros((len(rows), len(cols)))
    t = tot.sort_values(([key] if key else []) + ["date"], kind="mergesort")
    groups = {k: (v.season.to_numpy(), v.date.to_numpy(), v[cols].to_numpy(float)) for k, v in (t.groupby(key, sort=False) if key else [(None, t)])}
    rk = rows[rkey].to_numpy() if rkey else np.array([None] * len(rows))
    rs = rows.season.to_numpy(); rd = rows.date.to_numpy()
    for i in range(len(rows)):
        gv = groups.get(rk[i])
        if gv is None:
            continue
        m = (gv[0] >= rs[i] - back) & (gv[0] <= rs[i]) & (gv[1] < rd[i])
        if m.any():
            out[i] = gv[2][m].sum(axis=0)
    return pd.DataFrame(out, columns=cols, index=rows.index)


def _rush_tail(p: pd.DataFrame, g: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    c = p.copy()
    for col in ("rush_attempt", "qb_kneel"):
        c[col] = _num(c, col).fillna(0.0)
    c["y"] = _num(c, "rushing_yards"); c["play_id"] = _num(c, "play_id")
    c = c[(c.rush_attempt == 1) & (c.qb_kneel != 1) & c.rusher_player_id.notna() & c.y.notna() & c.posteam.notna() & c.defteam.notna()]
    c = c.drop(columns=["season"]).merge(g[["game_id", "season", "date"]], on="game_id", how="inner")
    pos = players.drop_duplicates("gsis_id").set_index("gsis_id")["position"]
    c["grp"] = np.where(c.rusher_player_id.map(pos) == "QB", "QB", "RB")
    c["O"] = _norm(c.posteam); c["D"] = _norm(c.defteam)
    for k in KS:
        c[f"e{k}"] = (c.y >= k).astype(float)
    c["stuff"] = (c.y <= 0).astype(float); c["one"] = 1.0
    c = c.sort_values(["date", "game_id", "play_id"], kind="mergesort").reset_index(drop=True)
    ecols = [f"e{k}" for k in KS]
    # universe: one row per (game, rusher); team/opp from the rusher's first carry of the game
    u = c.drop_duplicates(["game_id", "rusher_player_id"])[["game_id", "rusher_player_id", "season", "date", "grp", "O", "D"]].rename(columns={"rusher_player_id": "team", "O": "pteam", "D": "opp"}).reset_index(drop=True)
    # rusher EW sums (carry index half-life) over seasons s-2..s, dated before d
    num = np.full((len(u), len(KS)), np.nan); W = np.zeros(len(u))
    cg = {k: (v.season.to_numpy(), v.date.to_numpy(), v[ecols].to_numpy(float)) for k, v in c.groupby("rusher_player_id", sort=False)}
    for i, (rid, s, d) in enumerate(zip(u.team, u.season, u.date.to_numpy())):
        xs, xd, xe = cg[rid]; m = (xs >= s - 2) & (xs <= s) & (xd < d)
        e = xe[m]
        if len(e) == 0:
            num[i] = 0.0; continue
        w = 0.5 ** (np.arange(len(e) - 1, -1, -1) / HL_C)
        num[i] = w @ e; W[i] = w.sum()
    pt = _cum_by_date(c, "grp", ecols + ["one"])
    P = _window_sum(pt, "grp", u, "grp", ecols + ["one"], 2)
    dt = _cum_by_date(c, "D", ecols + ["stuff", "one"])
    Dw = _window_sum(dt, "D", u, "opp", ecols + ["stuff", "one"], 1)
    lt = _cum_by_date(c, None, ecols + ["stuff", "one"])
    Lw = _window_sum(lt, None, u, None, ecols + ["stuff", "one"], 1)
    out = u[["game_id", "team"]].copy()
    for j, k in enumerate(KS):
        Pk = P[f"e{k}"] / P["one"].where(P["one"] > 0)
        rk = (num[:, j] + K_POS * Pk) / (W + K_POS)
        Lk = Lw[f"e{k}"] / Lw["one"].where(Lw["one"] > 0)
        ek = (Dw[f"e{k}"] + K_DEF * Lk) / (Dw["one"] + K_DEF)
        out[f"ryt_p{k}_pre"] = np.minimum(1.0, rk * (ek / Lk.where(Lk > 0)))
    Ls = Lw["stuff"] / Lw["one"].where(Lw["one"] > 0)
    out["ryt_opp_stuff_pre"] = ((Dw["stuff"] + K_DEF * Ls) / (Dw["one"] + K_DEF)) / Ls.where(Ls > 0)
    return out.merge(u[["game_id", "team", "season", "date"]], on=["game_id", "team"], how="left")


def compute(raw: dict) -> dict:
    g = _games(raw["games"]); p = raw["pbp"]
    tr = _team_rows(g)
    prs = _pass_run_split(p, g, tr)
    team = tr[["game_id", "season", "week", "team", "opp", "date"]].merge(prs, on=["game_id", "team"], how="left")
    return {"team": team.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


def compute_rusher(raw: dict) -> dict:
    """Rusher-keyed table (the replay harness reads the `team` key; here `team` holds the rusher gsis id)."""
    g = _games(raw["games"])
    return {"team": _rush_tail(raw["pbp"], g, raw["players"]).sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


PRS_COLS = ["prs_off_pass_pre", "prs_off_rush_pre", "prs_def_pass_pre", "prs_def_rush_pre", "prs_pass_rate_pre", "prs_exp_epa_pre"]
RYT_COLS = [f"ryt_p{k}_pre" for k in KS] + ["ryt_opp_stuff_pre"]


def specs() -> list[FeatureSpec]:
    return [s for s in all_specs() if s.table == "team"]


def specs_rusher() -> list[FeatureSpec]:
    return [s for s in all_specs() if s.table == "rusher"]


def all_specs() -> list[FeatureSpec]:
    return [
        FeatureSpec(S, "nfl.pass_run_split_epa_both_sides", "team", PRS_COLS, "FULL",
                    "Opponent-adjusted (weighted ridge, last 12 regular-season games, half-life 6 games) offence EPA per dropback and per rush and defence EPA per dropback / rush faced, shrunk n/(n+150) pass and n/(n+100) rush; "
                    "neutral pass rate = league xpass + team PROE; blended expected EPA per play against the opponent",
                    ["off/def pass and rush EPA, opponent-adjusted by ridge", "12-game half-life-6 window", "n/(n+150) and n/(n+100) shrinkage", "wp 0.05-0.95, kneel/spike exclusion", "pA = league xpass + PROE", "blended rate"],
                    [], ["nflverse play_by_play (epa, wp, xpass, pass, rush)", "nflverse schedule"], "pregame_rolling"),
        FeatureSpec(S, "nfl.rush_yardage_tail", "rusher", RYT_COLS, "FULL",
                    "Per rusher (QB and RB groups) P(rushing yards >= k) for k in 7/10/15/20/30/40 over 3 seasons of carries with a 25-carry half-life, shrunk to the group prior with k=60, times the opponent "
                    "explosive-allowed factor (k=100 carries); opponent stuff factor",
                    ["discrete tail at 6 thresholds", "3 seasons, half-life 25 carries", "QB/RB positional prior, k=60", "opponent explosive-allowed and stuff rates, k=100", "as of the previous game date"],
                    [], ["nflverse play_by_play (rusher_player_id, rushing_yards)", "nflverse players (position)", "nflverse schedule"], "pregame_rolling"),
    ]
