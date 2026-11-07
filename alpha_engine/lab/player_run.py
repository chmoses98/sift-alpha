"""Player-lab runner: context tables, availability, name mapping, the search, and 2025 contract probabilities.  RESEARCH_ONLY, market-free.
usage: python -m alpha_engine.lab.player_run --data DIR --work DIR --out research/audit/lab"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import numpy as np
import pandas as pd
from alpha_engine.input_research import nfl_features as nf, stats as S
from . import identity as IDN
from . import dists, player_lab as PL, market as MK

K2N = {"JAC": "JAX"}


def build_game_ctx(gt: pd.DataFrame, gpred: pd.DataFrame) -> pd.DataFrame:
    p = gpred.pivot_table(index="game_id", columns="target", values="mu").add_prefix("mu_").reset_index()
    g = gt.merge(p, on="game_id", how="left")
    rows = []
    for tag, other, sign in (("h", "a", 1.0), ("a", "h", -1.0)):
        team = g["home_team"] if tag == "h" else g["away_team"]
        rows.append(pd.DataFrame(dict(
            game_id=g["game_id"], team=team,
            team_off_epa_pass=g[f"{tag}_off_epa_pass"], team_off_epa_rush=g[f"{tag}_off_epa_rush"], team_off_neutral_pass=g[f"{tag}_off_neutral_pass"], team_off_plays=g[f"{tag}_off_plays"],
            opp_def_epa_pass=g[f"{other}_def_epa_pass"], opp_def_epa_rush=g[f"{other}_def_epa_rush"], opp_def_sack_rate=g[f"{other}_def_sack_rate"], opp_def_sr=g[f"{other}_def_sr"],
            team_pts_pred=g["mu_home_pts"] if tag == "h" else g["mu_away_pts"], opp_pts_pred=g["mu_away_pts"] if tag == "h" else g["mu_home_pts"],
            margin_pred_team=sign * g["mu_margin"], total_pred=g["mu_total"], dome=g["dome"], wind_eff=g["wind_eff"], cold=g["cold"])))
    return pd.concat(rows, ignore_index=True)


def kickoffs(gt: pd.DataFrame) -> pd.DataFrame:
    """(season, week, team) -> kickoff as tz-aware UTC (nflverse gametime is US Eastern)."""
    k = nf.kickoff_table(gt).copy()
    k["kickoff"] = pd.to_datetime(k["ko"]).dt.tz_localize("UTC")
    return k[["season", "week", "team", "kickoff"]]


class Availability:
    """P(active) from the player's appearances in the team's last 8 games BEFORE the date (pre-game information only); a published 'Out' status sets it to 0."""
    def __init__(self, pg: pd.DataFrame):
        self.team_dates = {t: np.sort(g["date"].unique()) for t, g in pg.groupby("team")}
        self.app = {p: np.sort(g["date"].to_numpy()) for p, g in pg.groupby("pid")}

    def rate(self, pid, team, date, window=8):
        td = self.team_dates.get(team)
        if td is None:
            return np.nan
        before = td[td < date]
        if len(before) == 0:
            return np.nan
        last = before[-window:]
        ap = self.app.get(pid)
        if ap is None:
            return 0.0
        n = int(np.isin(ap, last).sum())
        return n / len(last)


def name_map(players: pd.DataFrame, pg: pd.DataFrame) -> dict:
    names = players.dropna(subset=["gsis_id", "display_name"]).copy()
    names["nn"] = names["display_name"].map(PL.norm_name)
    team_of = pg.sort_values("date").groupby("pid")["team"].last().to_dict()
    out: dict = {}
    for nn, g in names.groupby("nn"):
        out[nn] = [(r.gsis_id, team_of.get(r.gsis_id)) for r in g.itertuples()]
    return out


def resolve(contracts: pd.DataFrame, nm: dict) -> pd.DataFrame:
    pid = []
    for r in contracts.itertuples(index=False):
        c = nm.get(PL.norm_name(r.player), [])
        same = [p for p, t in c if t == r.team]
        pid.append(same[0] if len(same) == 1 else (c[0][0] if len(c) == 1 and c[0][1] in (None, r.team) else None))
    out = contracts.copy(); out["pid"] = pid
    return out


def final_player_predictions(lab: PL.PlayerLab, target: str, cfg: dict, contracts: pd.DataFrame, avail: Availability) -> pd.DataFrame:
    """Fit the chosen config on every season <= 2024 and predict 2025 contracts (one row per contract: pid, game, floor).  Adds p_act and the fair P(YES)."""
    sp = PL.SPEC[target]
    d = lab.frame(target)
    seasons = d["season"].to_numpy(int); y = d["y"].to_numpy(float)
    cols = lab.columns(target, cfg["groups"], cfg["hl"])
    X = d[cols].to_numpy(float)
    tests = list(range(PL.FIRST_TEST, PL.VAL_END + 1))
    mu_wf = np.maximum(lab.wf(X, y, seasons, tests, cfg["model"]), 0.05)
    ok = ~np.isnan(mu_wf)
    disp = 1.0 if sp["dist"] == "poisson" else dists.nb_size(mu_wf[ok], float(np.mean(((y - mu_wf) ** 2)[ok])))
    tr = seasons <= PL.VAL_END
    if cfg["model"] == "ridge":
        lam = S.fit_ridge_lambda(X, y, np.where(tr, seasons, 9999), PL.VAL_END + 1)
        f, _, _ = S.ridge_fit(X[tr], y[tr], lam); predict = f
    else:
        gb = S.make_gbm().fit(np.nan_to_num(X[tr], nan=0.0), y[tr]); predict = lambda Z: gb.predict(np.nan_to_num(Z, nan=0.0))
        if cfg["model"] == "blend":
            lam = S.fit_ridge_lambda(X, y, np.where(tr, seasons, 9999), PL.VAL_END + 1); f, _, _ = S.ridge_fit(X[tr], y[tr], lam)
            predict = lambda Z, f=f, g=predict: 0.5 * f(Z) + 0.5 * g(Z)
    c = contracts.copy().reset_index(drop=True)
    feats = PL.features_asof(c[["pid", "date"]], lab.states)
    c = pd.concat([c, feats.drop(columns=["pid", "date"]).reset_index(drop=True)], axis=1)
    c = c.merge(lab.ctx, on=["game_id", "team"], how="left").merge(lab.inj.rename(columns={"gsis_id": "pid", "code": "inj_code"}), on=["season", "week", "pid"], how="left")
    c["inj_q"] = (c["inj_code"] == 0.25).astype(float); c["inj_d"] = (c["inj_code"] == 0.85).astype(float)
    c["games_prior"] = c["games_n"].fillna(0)
    c["mu"] = np.maximum(predict(c[cols].to_numpy(float)), 0.05)
    c["p_act"] = [0.0 if ic == 1.0 else (avail.rate(p, t, dt) if not (isinstance(p, float) and np.isnan(p)) else np.nan) for p, t, dt, ic in zip(c["pid"], c["team"], c["date"], c["inj_code"].fillna(0.0))]
    kind = sp["dist"]
    c["p_cond"] = dists.prob_gt(kind, c["mu"].to_numpy(), disp, c["floor"].to_numpy(float))
    c["model_p"] = c["p_act"] * c["p_cond"]
    c["disp"] = disp
    return c


def run(data: Path, work: Path, out: Path, targets=("rec_yds", "receptions", "rush_yds", "pass_yds", "td_any"), n_boot=1000):
    gpred = pd.read_parquet(work / "game_predictions.parquet")
    gt = pd.read_parquet(work / "game_table.parquet")
    pgp, stp = work / "pg.parquet", work / "states.parquet"
    if pgp.exists() and stp.exists():
        pg, st = pd.read_parquet(pgp), pd.read_parquet(stp)
    else:
        pbp = PL.load_pbp_players(data / "pbp", range(2010, 2026))
        pg = PL.player_games(pbp); st = PL.build_states(pg); pg.to_parquet(pgp); st.to_parquet(stp)
    ctx = build_game_ctx(gt, gpred)
    inj = PL.injury_status(data / "inj", kickoffs(gt))
    players = pd.read_csv(data / "players.csv", low_memory=False)
    report = {"lab": "player/1", "targets": {}}
    for t in targets:
        t0 = time.time()
        lab = PL.PlayerLab(pg, st, ctx, inj, out / f"ledger_player_{t}.jsonl", n_boot=n_boot)
        s1 = lab.search(t)
        top = sorted(s1, key=lambda r: -r["metrics"]["sel"]["mean"])[:5]
        # stage 2 on the best five: GBM and ridge+GBM blend
        for r in top:
            lab.search_one(t, r["config"]["groups"], r["config"]["hl"], ("gbm", "blend")) if hasattr(lab, "search_one") else None
        rows = list(lab.led.select(lab="player/1", target=t))
        q = S.benjamini_hochberg({r["id"]: r["metrics"]["sel"]["p_one"] for r in rows})
        best = max(rows, key=lambda r: r["metrics"]["sel"]["mean"])
        report["targets"][t] = dict(n_experiments=len(rows), n_selection_positive=sum(r["metrics"]["sel"]["mean"] > 0 for r in rows), n_validation_positive=sum(r["metrics"]["val"]["mean"] > 0 for r in rows),
                                    n_bh_q05=sum(v < 0.05 for v in q.values()), selected=dict(config=best["config"], selection=best["metrics"]["sel"], validation=best["metrics"]["val"], bh_q=q[best["id"]],
                                                                                           mae_val=best["metrics"]["mae_val"], mae_base_val=best["metrics"]["mae_base_val"]),
                                    top10=[dict(model=r["config"]["model"], groups=r["config"]["groups"], hl=r["config"]["hl"], sel=r["metrics"]["sel"]["mean"], val=r["metrics"]["val"]["mean"])
                                           for r in sorted(rows, key=lambda r: -r["metrics"]["sel"]["mean"])[:10]], seconds=round(time.time() - t0))
        print(t, len(rows), "best sel", round(best["metrics"]["sel"]["mean"], 4), "val", round(best["metrics"]["val"]["mean"], 4), round(time.time() - t0), "s", flush=True)
    (out / "player_lab_report.json").write_text(json.dumps(report, indent=1, default=float))
    return report


def selected_config(out: Path, target: str):
    from . import ledger as L
    led = L.Ledger(out / f"ledger_player_{target}.jsonl")
    rows = led.select(lab="player/1", target=target)
    return max(rows, key=lambda r: r["metrics"]["sel"]["mean"])["config"]


def contract_probs(kalshi: Path, data: Path, work: Path, out: Path) -> tuple[pd.DataFrame, dict]:
    """Fair P(YES) for every priced 2025 player contract (one frame row per contract x horizon), plus resolution diagnostics (never silently dropped)."""
    horizons = sorted(Path(kalshi / "horizons").glob("*.jsonl"))
    games = pd.read_csv(data / "games.csv"); rstats: dict = {}
    d = MK.load_contracts([str(h) for h in horizons], games=games, stats=rstats)
    d = d[d["family"].isin(list(MK.KALSHI_STAT.values()))].copy()
    gt = pd.read_parquet(work / "game_table.parquet"); gpred = pd.read_parquet(work / "game_predictions.parquet")
    pg, st = pd.read_parquet(work / "pg.parquet"), pd.read_parquet(work / "states.parquet")
    ctx = build_game_ctx(gt, gpred); inj = PL.injury_status(data / "inj", kickoffs(gt))
    players = pd.read_csv(data / "players.csv", low_memory=False)
    nm, av = name_map(players, pg), Availability(pg)
    date = pd.to_datetime(gt.set_index("game_id")["gameday"])
    wk = gt.set_index("game_id")["week"]
    u = d.drop_duplicates("ticker")[["ticker", "game_id", "family", "team", "player", "floor", "home", "away"]].copy()
    u = IDN.resolve(u.assign(season=2025), players, pg)
    idr = IDN.report(u)
    diag = {"recovered_records": rstats.get("recovered", 0), "contracts": int(len(u)), "unresolved_player": int(u["pid"].isna().sum()), "identity": idr,
            "unresolved_real_player": int((u["pid"].isna() & ~u["id_reason"].str.startswith("NON_PLAYER")).sum())}
    u = u.dropna(subset=["pid"]).copy()
    miss = ~u["game_id"].isin(date.index)
    diag["no_game_in_table"] = int(miss.sum()); diag["no_game_ids"] = sorted(u.loc[miss, "game_id"].unique().tolist())
    u = u[~miss].copy()
    u["date"] = u["game_id"].map(date); u["season"] = 2025; u["week"] = u["game_id"].map(wk).astype(int)
    u["home"] = (u["team"] == u["home"]).astype(float)
    res = []
    for fam, x in u.groupby("family"):
        cfg = selected_config(out, fam)
        lab = PL.PlayerLab(pg, st, ctx, inj, out / f"ledger_player_{fam}.jsonl")
        p = final_player_predictions(lab, fam, cfg, x[["ticker", "pid", "team", "game_id", "season", "week", "date", "home", "floor"]], av)
        diag[f"{fam}_p_act_missing"] = int(p["p_act"].isna().sum())
        res.append(p[["ticker", "model_p", "p_act", "mu", "pid"]])
    pp = pd.concat(res)
    d = d.merge(pp[["ticker", "model_p", "p_act", "mu", "pid"]], on="ticker", how="left")
    return d, diag


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--data", required=True); ap.add_argument("--work", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(); run(Path(a.data), Path(a.work), Path(a.out))
