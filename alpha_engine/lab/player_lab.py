"""Player-level laboratory: passing / rushing / receiving yards, receptions and anytime-TD.  Market-free.

Inputs per (player, game) are strictly PRE-game: EWMA usage/production states as of the last earlier game (merge-as-of, so a player who missed games still gets features as of
the date), role shares, the team's offence and the opponent's defence ratings, our own game-script forecasts (predicted team points / margin / total from the game lab, never a
price), observed environment (partial) and the player's official injury-report status before kickoff (partial).
Search: feature-group subsets x EWMA windows -> ledger; walk-forward by season (test 2017-2024; selection 2017-2021, validation 2022-2024; 2025 reserved for the market comparison);
yardage/receptions use a negative binomial whose size comes from earlier out-of-sample residuals, TDs a Poisson.  The yardstick is the log score of the realised integer
outcome against the player's OWN rolling average (a strong naive baseline), so a gain means the context features add something beyond 'he averages X'."""
from __future__ import annotations
import itertools, re
from pathlib import Path
import numpy as np
import pandas as pd
from alpha_engine.input_research import stats as S
from . import dists, guard, ledger as L

PBP_COLS = ["game_id", "season", "season_type", "week", "game_date", "home_team", "posteam", "defteam", "play_id", "receiver_player_id", "rusher_player_id", "passer_player_id",
            "receiving_yards", "rushing_yards", "passing_yards", "air_yards", "complete_pass", "pass_attempt", "rush_attempt", "pass_touchdown", "rush_touchdown", "interception",
            "sack", "td_player_id", "two_point_attempt"]
USAGE = {"rec_yds": ["rec_yds", "rec", "tgt", "air", "rec_td"], "receptions": ["rec", "rec_yds", "tgt", "air", "rec_td"], "rush_yds": ["rush_yds", "car", "rush_td"],
         "pass_yds": ["pass_yds", "att", "comp", "pass_td", "int"], "td_any": ["td_any", "rec_td", "rush_td", "tgt", "car"]}
SPEC = {"rec_yds": dict(stat="rec_yds", floor=15.0, dist="nbinom", kalshi="receiving_yards", share="tgt_share"),
        "receptions": dict(stat="rec", floor=1.5, dist="nbinom", kalshi="receptions", share="tgt_share"),
        "rush_yds": dict(stat="rush_yds", floor=15.0, dist="nbinom", kalshi="rushing_yards", share="car_share"),
        "pass_yds": dict(stat="pass_yds", floor=100.0, dist="nbinom", kalshi="passing_yards", share=None),
        "td_any": dict(stat="td_any", floor=0.15, dist="poisson", kalshi="touchdowns", share="tgt_share")}
HL = {"3": [3], "8": [8], "3+8": [3, 8]}
OPTIONAL = ["share", "team_ctx", "opp_def", "script", "env", "injury"]
FIRST_TEST, SEL_END, VAL_END, HOLDOUT = 2017, 2021, 2024, 2025
STATUS = {"Out": 1.0, "Doubtful": 0.85, "Questionable": 0.25}
DIAGNOSTICS: dict = {}


def load_pbp_players(pbp_dir: Path, seasons) -> pd.DataFrame:
    fr = []
    for y in seasons:
        f = pd.read_parquet(Path(pbp_dir) / f"pbp_{y}.parquet", columns=PBP_COLS)
        fr.append(f[f["season_type"].isin(["REG", "POST"])])
    return pd.concat(fr, ignore_index=True)


def player_games(pbp: pd.DataFrame) -> pd.DataFrame:
    """One row per (game, player) who recorded an offensive touch, target or pass attempt."""
    base = ["game_id", "season", "week", "game_date", "home_team", "posteam", "defteam"]
    rec = pbp[pbp["receiver_player_id"].notna() & (pbp["pass_attempt"] == 1) & (pbp["sack"] != 1)]
    r = rec.groupby(["game_id", "receiver_player_id"]).agg(tgt=("play_id", "size"), rec=("complete_pass", "sum"), rec_yds=("receiving_yards", "sum"), air=("air_yards", "sum"),
                                                          rec_td=("pass_touchdown", "sum")).reset_index().rename(columns={"receiver_player_id": "pid"})
    ru = pbp[pbp["rusher_player_id"].notna() & (pbp["rush_attempt"] == 1)]
    u = ru.groupby(["game_id", "rusher_player_id"]).agg(car=("play_id", "size"), rush_yds=("rushing_yards", "sum"), rush_td=("rush_touchdown", "sum")).reset_index().rename(columns={"rusher_player_id": "pid"})
    pa = pbp[pbp["passer_player_id"].notna() & (pbp["pass_attempt"] == 1)]
    p = pa.groupby(["game_id", "passer_player_id"]).agg(att=("play_id", "size"), comp=("complete_pass", "sum"), pass_yds=("passing_yards", "sum"), pass_td=("pass_touchdown", "sum"),
                                                       int=("interception", "sum")).reset_index().rename(columns={"passer_player_id": "pid"})
    pg = r.merge(u, on=["game_id", "pid"], how="outer").merge(p, on=["game_id", "pid"], how="outer")
    pg = pg.fillna(0.0)
    meta = pbp.dropna(subset=["posteam"]).drop_duplicates(["game_id", "posteam"])[base]
    # a player's team in a game = the posteam of the plays he took part in
    who = pd.concat([rec[["game_id", "receiver_player_id", "posteam"]].rename(columns={"receiver_player_id": "pid"}), ru[["game_id", "rusher_player_id", "posteam"]].rename(columns={"rusher_player_id": "pid"}),
                     pa[["game_id", "passer_player_id", "posteam"]].rename(columns={"passer_player_id": "pid"})]).drop_duplicates(["game_id", "pid"])
    pg = pg.merge(who, on=["game_id", "pid"], how="left").merge(meta.drop(columns=["posteam"]).drop_duplicates("game_id")[["game_id", "season", "week", "game_date", "home_team"]], on="game_id", how="left")
    opp = meta.set_index(["game_id", "posteam"])["defteam"]
    pg["opp"] = [opp.get((g, t)) for g, t in zip(pg["game_id"], pg["posteam"])]
    pg["team"] = pg["posteam"]; pg["home"] = (pg["team"] == pg["home_team"]).astype(float)
    pg["date"] = pd.to_datetime(pg["game_date"])
    pg["td_any"] = pg["rec_td"] + pg["rush_td"]
    for col, s in (("tgt_share", "tgt"), ("car_share", "car")):
        tot = pg.groupby(["game_id", "team"])[s].transform("sum")
        pg[col] = pg[s] / tot.replace(0, np.nan)
    return pg.drop(columns=["posteam", "game_date"]).sort_values(["pid", "date"]).reset_index(drop=True)


STATE_COLS = ["tgt", "rec", "rec_yds", "air", "rec_td", "car", "rush_yds", "rush_td", "att", "comp", "pass_yds", "pass_td", "int", "td_any", "tgt_share", "car_share"]


def build_states(pg: pd.DataFrame) -> pd.DataFrame:
    """POST-game EWMA state per (player, game date) for each half-life.  A later game uses the latest state of an EARLIER date (merge-as-of, exact matches excluded)."""
    st = pg[["pid", "date"]].copy()
    st["games_n"] = pg.groupby("pid").cumcount() + 1
    for h in (3, 8):
        e = pg.groupby("pid")[STATE_COLS].transform(lambda s: s.ewm(halflife=h, adjust=False).mean())
        for c in STATE_COLS:
            st[f"ew{h}_{c}"] = e[c].to_numpy()
    return st.sort_values("date").reset_index(drop=True)


def features_asof(targets: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    """targets: pid, date.  Returns the states as of the last strictly-earlier game of each player (NaN for debutants), ROW-ALIGNED with ``targets``."""
    t = targets[["pid", "date"]].copy()
    t["_i"] = np.arange(len(t))
    m = pd.merge_asof(t.sort_values("date"), states, on="date", by="pid", direction="backward", allow_exact_matches=False)
    return m.sort_values("_i").drop(columns="_i").reset_index(drop=True)


def injury_status(inj_dir: Path, kickoffs: pd.DataFrame) -> pd.DataFrame:
    """Worst official report status per (season, week, gsis_id) published BEFORE kickoff.  Reports without a timestamp are not used (counted by the caller)."""
    fr = []
    for f in sorted(Path(inj_dir).glob("inj_*.csv")):
        d = pd.read_csv(f, low_memory=False)
        if "date_modified" not in d.columns:
            d["date_modified"] = pd.NaT          # no report timestamp in this release: cannot be shown to be pre-kickoff, so it is NOT used (counted in DIAGNOSTICS)
        fr.append(d[["season", "week", "team", "gsis_id", "report_status", "date_modified"]])
    d = pd.concat(fr, ignore_index=True)
    d = d.merge(kickoffs[["season", "week", "team", "kickoff"]], on=["season", "week", "team"], how="left")
    ts = pd.to_datetime(d["date_modified"], utc=True, errors="coerce")
    d["code"] = d["report_status"].map(STATUS)
    DIAGNOSTICS["injury_rows"] = int(len(d)); DIAGNOSTICS["injury_rows_without_timestamp"] = int((~ts.notna()).sum())
    d = d[ts.notna() & d["kickoff"].notna() & (ts < d["kickoff"]) & d["code"].notna()]
    return d.groupby(["season", "week", "gsis_id"])["code"].max().reset_index()


def norm_name(s: str) -> str:
    s = re.sub(r"[^a-z ]", "", str(s).lower())
    return re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s).split() and " ".join(re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s).split())


class PlayerLab:
    def __init__(self, pg: pd.DataFrame, states: pd.DataFrame, game_ctx: pd.DataFrame, inj: pd.DataFrame, ledger_path, n_boot=1000):
        self.pg, self.states, self.ctx, self.inj = pg, states, game_ctx, inj
        self.led = L.Ledger(ledger_path)
        self.n_boot = n_boot
        self._boots: dict = {}

    # ---------------------------------------------------------------------------------- design matrix
    def frame(self, target: str) -> pd.DataFrame:
        """Training/evaluation universe for one target with every candidate feature attached (pre-game only)."""
        sp = SPEC[target]
        f = features_asof(self.pg[["pid", "date"]].reset_index(drop=True), self.states)
        d = pd.concat([self.pg.reset_index(drop=True), f.drop(columns=["pid", "date"])], axis=1)
        d = d.merge(self.ctx, on=["game_id", "team"], how="left")
        d = d.merge(self.inj.rename(columns={"gsis_id": "pid", "code": "inj_code"}), on=["season", "week", "pid"], how="left")
        d["inj_q"] = (d["inj_code"] == 0.25).astype(float); d["inj_d"] = (d["inj_code"] == 0.85).astype(float)
        d["y"] = d[sp["stat"]]
        d["ew8_stat"] = d[f"ew8_{sp['stat']}"]
        keep = (d["games_n"].fillna(0) >= 0) & d["ew8_stat"].notna() & (d["ew8_stat"] >= sp["floor"])
        prior_n = d.groupby("pid").cumcount()
        d["games_prior"] = prior_n
        d = d[keep & (prior_n >= 4) & (d["season"] >= FIRST_TEST - 3)].reset_index(drop=True)
        d["key"] = d["season"] * 100 + d["week"]
        return d

    def columns(self, target: str, groups, hl: str) -> list[str]:
        sp = SPEC[target]
        cols = []
        for h in HL[hl]:
            cols += [f"ew{h}_{c}" for c in USAGE[target]]
        cols += ["games_prior"]
        if "share" in groups and sp["share"]:
            cols += [f"ew{h}_{sp['share']}" for h in HL[hl]]
        if "team_ctx" in groups:
            cols += ["team_off_epa_pass", "team_off_epa_rush", "team_off_neutral_pass", "team_off_plays", "home"]
        if "opp_def" in groups:
            cols += ["opp_def_epa_pass", "opp_def_epa_rush", "opp_def_sack_rate", "opp_def_sr"]
        if "script" in groups:
            cols += ["team_pts_pred", "opp_pts_pred", "margin_pred_team", "total_pred"]
        if "env" in groups:
            cols += ["dome", "wind_eff", "cold"]
        if "injury" in groups:
            cols += ["inj_q", "inj_d"]
        guard.assert_market_free(cols, allow_targets=())
        return [c for c in cols if c in self.ctx.columns or c in self.states.columns or c in ("games_prior", "home", "inj_q", "inj_d")]

    # ---------------------------------------------------------------------------------- walk-forward with NB / Poisson
    @staticmethod
    def wf(X, y, seasons, test_seasons, model="ridge"):
        if model == "ridge":
            return S.walk_forward_ridge(X, y, seasons, test_seasons, min_train=500)[0]
        if model == "gbm":
            return S.walk_forward_gbm(np.nan_to_num(X, nan=0.0), y, seasons, test_seasons, min_train=500)
        a = S.walk_forward_ridge(X, y, seasons, test_seasons, min_train=500)[0]
        return 0.5 * a + 0.5 * S.walk_forward_gbm(np.nan_to_num(X, nan=0.0), y, seasons, test_seasons, min_train=500)

    @staticmethod
    def disp_wf(y, mu, seasons, test_seasons, dist):
        """NB size per test season from EARLIER out-of-sample residual moments (Poisson needs none)."""
        out = np.full(len(y), np.nan)
        rs, ms = [], []
        for s in sorted(test_seasons):
            te = seasons == s
            if dist == "poisson":
                out[te] = 1.0
            else:
                out[te] = dists.nb_size(np.concatenate(ms), float(np.mean(np.concatenate(rs)))) if rs and sum(len(r) for r in rs) >= 300 else 5.0
            ok = te & ~np.isnan(mu)
            rs.append(((y[ok] - mu[ok]) ** 2)); ms.append(mu[ok])
        return out

    def boot(self, which, keys):
        if which not in self._boots:
            self._boots[which] = S.ClusterBoot(keys, n_boot=self.n_boot)
        return self._boots[which]

    def search_one(self, target, groups, hl, models):
        return self.search(target, models=models, only=(tuple(groups), hl))

    def search(self, target: str, limit=None, models=("ridge",), only=None) -> list[dict]:
        sp = SPEC[target]
        d = self.frame(target)
        seasons = d["season"].to_numpy(int); y = d["y"].to_numpy(float)
        tests = list(range(FIRST_TEST, VAL_END + 1))
        selm = np.isin(seasons, range(FIRST_TEST, SEL_END + 1)); valm = np.isin(seasons, range(SEL_END + 1, VAL_END + 1))
        keys = d["key"].to_numpy(int)
        # baseline: the player's own rolling average with the same dispersion procedure
        mu_b = np.maximum(d["ew8_stat"].to_numpy(float), 0.05)
        disp_b = self.disp_wf(y, np.where(np.isin(seasons, tests), mu_b, np.nan), seasons, tests, sp["dist"])
        ls_b = dists.int_logscore(sp["dist"], y, mu_b, disp_b)
        out, n = [], 0
        for hl in HL:
            for k in range(len(OPTIONAL) + 1):
                for groups in itertools.combinations(OPTIONAL, k):
                    if only is not None and (tuple(groups), hl) != only:
                        continue
                    for model in models:
                        cfg = dict(lab="player/1", stage=1 if model == "ridge" else 2, target=target, groups=list(groups), hl=hl, model=model, dist=sp["dist"], split=[FIRST_TEST, SEL_END, VAL_END])
                        if self.led.has(cfg):
                            out.append(self.led.get(cfg)); continue
                        cols = self.columns(target, groups, hl)
                        X = d[cols].to_numpy(float)
                        mu = np.maximum(self.wf(X, y, seasons, tests, model), 0.05)
                        disp = self.disp_wf(y, mu, seasons, tests, sp["dist"])
                        ls = dists.int_logscore(sp["dist"], y, mu, disp)
                        gain = ls - ls_b
                        def win(m, w):
                            dd = gain[m & ~np.isnan(gain)]
                            r = self.boot(w, keys[m]).summarize(dd) if len(dd) > 10 else dict(mean=float("nan"), n=0, n_clusters=0, p=1.0, **{"ci_0.05": [float("nan")] * 2})
                            p1 = r["p"] / 2 if r["mean"] > 0 else 1 - r["p"] / 2
                            return dict(mean=r["mean"], ci=r["ci_0.05"], p_one=float(p1), n=r["n"], clusters=r["n_clusters"])
                        m = dict(sel=win(selm, "sel"), val=win(valm, "val"), mae_val=float(np.nanmean(np.abs(y - mu)[valm])), mae_base_val=float(np.nanmean(np.abs(y - mu_b)[valm])), n_features=len(cols))
                        out.append(self.led.record(cfg, m, sample=dict(rows=int(len(d)), sel_n=int(selm.sum()), val_n=int(valm.sum())), fingerprint=L.data_fingerprint(len(d), target)))
                        n += 1
                        if limit and n >= limit:
                            return out
        return out
