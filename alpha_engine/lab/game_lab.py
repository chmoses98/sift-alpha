"""Game-level laboratory: independent distributions for margin, total and each team's points (-> moneyline, spread, total, team-total fair probabilities at ANY
threshold).  Market-free by construction (guard.assert_market_free).

Search space per target (every point is one ledger entry):
  rating config   half-life {4,8,16} games x offseason carry {0.4,0.8} x opponent adjustment {on,off}                      (12)
  feature groups  strength is always in; any subset of {protection, explosive, tempo, efficiency_luck, qb, schedule, environment, injuries}   (256)
  -> 3,072 ridge configurations per target (stage 1); the best few get GBM / Student-t / blend variants (stage 2).
Protocol: walk-forward by season (a season is predicted from earlier seasons only; ridge lambda chosen on the last TRAIN season; sigma from earlier OUT-OF-SAMPLE residuals).
SELECTION seasons 2014-2021 choose the model; VALIDATION seasons 2022-2024 confirm it once; 2025 is never scored here (it is the market-comparison holdout)."""
from __future__ import annotations
import itertools, json
from pathlib import Path
import numpy as np
import pandas as pd
from alpha_engine.input_research import stats as S, nfl_features as nf
from . import dists, guard, ledger as L, ratings as R

FIRST_TEST, SEL_END, VAL_END, HOLDOUT = 2014, 2021, 2024, 2025
RATING_GRID = [dict(half_life=h, carry=c, adjust=a) for h in (4, 8, 16) for c in (0.4, 0.8) for a in (True, False)]
REFERENCE = dict(rating=dict(half_life=8, carry=0.8, adjust=True), groups=["strength"])
METRIC_GROUPS = {"strength": ["epa_pass", "epa_rush", "sr"], "protection": ["sack_rate", "qbhit_rate"], "explosive": ["expl_pass", "expl_rush"],
                 "tempo": ["neutral_pass", "pass_oe", "sec_play", "plays"], "efficiency_luck": ["to_rate", "pen_rate", "score_drive", "third_conv"]}
TABLE_GROUPS = {"qb": ["diff_qb_epa", "sum_qb_epa", "h_qb_change", "a_qb_change"],
                "schedule": ["rest_diff", "short_week_any", "div_flag", "neutral_site", "late_season", "games_played_min"],
                "environment": ["dome", "wind_eff", "cold", "wind_x_pass"],
                "injuries": ["inj_diff_qb", "inj_sum_qb", "inj_diff_ol", "inj_sum_ol", "inj_diff_skill", "inj_sum_skill", "inj_diff_dl", "inj_sum_dl", "inj_diff_lb", "inj_sum_lb",
                             "inj_diff_db", "inj_sum_db"]}
OPTIONAL = ["protection", "explosive", "tempo", "efficiency_luck", "qb", "schedule", "environment", "injuries"]
# point-in-time status of each group (documented, not asserted by the data): qb/environment/injuries are PARTIAL (realised starter, observed weather, report timing)
GROUP_PIT = {"strength": "yes", "protection": "yes", "explosive": "yes", "tempo": "yes", "efficiency_luck": "yes", "qb": "partial", "schedule": "yes",
             "environment": "partial", "injuries": "partial"}
TARGETS = {"margin": lambda g: g["home_score"] - g["away_score"], "total": lambda g: g["home_score"] + g["away_score"],
           "home_pts": lambda g: g["home_score"], "away_pts": lambda g: g["away_score"]}


def groups_subsets():
    for k in range(len(OPTIONAL) + 1):
        for c in itertools.combinations(OPTIONAL, k):
            yield ["strength", *c]


def rating_key(r):
    return f"hl{r['half_life']}_c{r['carry']}_{'adj' if r['adjust'] else 'raw'}"


def matrix(gt: pd.DataFrame, rat: pd.DataFrame, groups) -> tuple[np.ndarray, list[str]]:
    """Feature matrix for a subset of groups.  Team-matchup features (home offence vs away defence, and vice versa) enter as DIFFERENCE and SUM."""
    d = gt[["game_id"]].merge(rat, on="game_id", how="left")
    cols: dict[str, np.ndarray] = {}
    for gname in groups:
        for m in METRIC_GROUPS.get(gname, []):
            eh = d[f"h_off_{m}"].to_numpy(float) + d[f"a_def_{m}"].to_numpy(float)
            ea = d[f"a_off_{m}"].to_numpy(float) + d[f"h_def_{m}"].to_numpy(float)
            cols[f"dif_{m}"], cols[f"sum_{m}"] = eh - ea, eh + ea
        for c in TABLE_GROUPS.get(gname, []):
            if c in gt.columns:
                cols[c] = gt[c].to_numpy(float)
    guard.assert_market_free(list(cols))
    names = list(cols)
    return np.column_stack([cols[n] for n in names]), names


# ------------------------------------------------------------------------------------------------ walk-forward machinery
def wf_mean(X, y, seasons, test_seasons, model="ridge"):
    if model == "ridge":
        mu, _ = S.walk_forward_ridge(X, y, seasons, test_seasons)
        return mu
    if model == "gbm":
        return S.walk_forward_gbm(np.nan_to_num(X, nan=0.0), y, seasons, test_seasons)
    if model == "blend":
        a, _ = S.walk_forward_ridge(X, y, seasons, test_seasons)
        return 0.5 * a + 0.5 * S.walk_forward_gbm(np.nan_to_num(X, nan=0.0), y, seasons, test_seasons)
    raise ValueError(model)


def sigma_wf(y, mu, seasons, test_seasons, floor=1.0):
    """sigma for season S = std of OUT-OF-SAMPLE residuals of seasons < S (expanding); the first test season falls back to the std of y before it."""
    sig = np.full(len(y), np.nan)
    res: list[np.ndarray] = []
    for s in sorted(test_seasons):
        te = seasons == s
        if res and sum(len(r) for r in res) >= 200:
            sd = float(np.std(np.concatenate(res)))
        else:
            sd = float(np.std(y[seasons < s])) if (seasons < s).any() else np.nan
        sig[te] = max(sd, floor)
        ok = te & ~np.isnan(mu)
        res.append(y[ok] - mu[ok])
    return sig


def climatology(y, seasons, test_seasons):
    mu = S.baseline_mean(y, seasons, test_seasons)
    return mu, sigma_wf(y, mu, seasons, test_seasons)


def logscore(kind, y, mu, sig):
    return dists.int_logscore(kind, y, mu, sig)


def summarize_window(d, boot):
    """Mean gain with a week-cluster bootstrap CI and a one-sided p (H1: gain > 0).  ``boot`` is ONE shared resample set per window, so experiments are comparable."""
    r = boot.summarize(d)
    p1 = r["p"] / 2 if r["mean"] > 0 else 1 - r["p"] / 2
    return dict(mean=r["mean"], ci=r["ci_0.05"], p_one=float(p1), n=r["n"], clusters=r["n_clusters"])


# ------------------------------------------------------------------------------------------------ the search
class GameLab:
    def __init__(self, gt: pd.DataFrame, tg: pd.DataFrame, ledger_path, cache_dir, n_boot: int = 1000):
        self.n_boot = n_boot
        self.gt = gt.sort_values(["gameday", "game_id"]).reset_index(drop=True)
        self.gt = self.gt[self.gt["home_score"].notna() | (self.gt["season"] >= HOLDOUT)].reset_index(drop=True)
        self.tg, self.cache = tg, Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.led = L.Ledger(ledger_path)
        self.seasons = self.gt["season"].to_numpy(int)
        self.weeks = self.gt["week"].to_numpy(int)
        self.keys = self.seasons * 100 + self.weeks
        self.fp = L.data_fingerprint(len(self.gt), self.gt["game_id"].iloc[0], self.gt["game_id"].iloc[-1], int(self.gt["home_score"].notna().sum()))
        self.rat: dict[str, pd.DataFrame] = {}
        self.sel_seasons = list(range(FIRST_TEST, SEL_END + 1))
        self.val_seasons = list(range(SEL_END + 1, VAL_END + 1))
        self.test_seasons = self.sel_seasons + self.val_seasons          # 2025 is NOT scored during the search
        self._boots: dict = {}

    def boot(self, which: str, mask):
        if which not in self._boots:
            self._boots[which] = S.ClusterBoot(self.keys[mask], n_boot=self.n_boot)
        return self._boots[which]

    def ratings(self, r) -> pd.DataFrame:
        k = rating_key(r)
        if k not in self.rat:
            p = self.cache / f"rat_{k}.parquet"
            if p.exists():
                self.rat[k] = pd.read_parquet(p)
            else:
                self.rat[k] = R.rolling_ratings_param(self.gt, self.tg, **r)
                self.rat[k].to_parquet(p)
        return self.rat[k]

    def target(self, name):
        return TARGETS[name](self.gt).to_numpy(float)

    def stage1(self, target: str, limit=None) -> list[dict]:
        """Every (rating config, group subset) ridge experiment for one target -> ledger.  Returns the new+cached ledger rows."""
        y = self.target(target)
        ok = ~np.isnan(y)
        mu0, sig0 = climatology(y, self.seasons, self.test_seasons)
        ls0 = np.where(ok, logscore("normal", y, mu0, sig0), np.nan)
        sel = np.isin(self.seasons, self.sel_seasons) & ok
        val = np.isin(self.seasons, self.val_seasons) & ok
        out = []
        n = 0
        for r in RATING_GRID:
            rat = self.ratings(r)
            for groups in groups_subsets():
                cfg = dict(lab="game/1", stage=1, target=target, rating=r, groups=groups, model="ridge", dist="normal", split=[FIRST_TEST, SEL_END, VAL_END])
                if self.led.has(cfg):
                    out.append(self.led.get(cfg)); continue
                X, names = matrix(self.gt, rat, groups)
                mu = wf_mean(X, np.where(ok, y, 0.0), self.seasons, self.test_seasons, "ridge")
                sig = sigma_wf(np.where(ok, y, 0.0), mu, self.seasons, self.test_seasons)
                ls = np.where(ok, logscore("normal", y, mu, sig), np.nan)
                gain = ls - ls0
                m = dict(sel=summarize_window(gain[sel], self.boot('sel', sel)), val=summarize_window(gain[val], self.boot('val', val)),
                         rmse_sel=float(np.sqrt(np.nanmean((y - mu)[sel] ** 2))), rmse_val=float(np.sqrt(np.nanmean((y - mu)[val] ** 2))),
                         n_features=len(names), pit={g: GROUP_PIT[g] for g in groups if GROUP_PIT[g] != "yes"})
                out.append(self.led.record(cfg, m, sample=dict(sel_n=int(sel.sum()), val_n=int(val.sum())), fingerprint=self.fp))
                n += 1
                if limit and n >= limit:
                    return out
        return out

    # -------------------------------------------------------------------------------------------- stage 2 and selection
    def stage2(self, target: str, top=8) -> list[dict]:
        y = self.target(target); ok = ~np.isnan(y)
        s1 = [r for r in self.led.select(lab="game/1", stage=1, target=target)]
        s1.sort(key=lambda r: -r["metrics"]["sel"]["mean"])
        mu0, sig0 = climatology(y, self.seasons, self.test_seasons)
        ls0 = np.where(ok, logscore("normal", y, mu0, sig0), np.nan)
        sel = np.isin(self.seasons, self.sel_seasons) & ok
        val = np.isin(self.seasons, self.val_seasons) & ok
        rows = []
        for base in s1[:top]:
            r, groups = base["config"]["rating"], base["config"]["groups"]
            X, _ = matrix(self.gt, self.ratings(r), groups)
            for model, kind in (("ridge", "t5"), ("gbm", "normal"), ("blend", "normal"), ("blend", "t5")):
                cfg = dict(lab="game/1", stage=2, target=target, rating=r, groups=groups, model=model, dist=kind, split=[FIRST_TEST, SEL_END, VAL_END])
                if self.led.has(cfg):
                    rows.append(self.led.get(cfg)); continue
                mu = wf_mean(X, np.where(ok, y, 0.0), self.seasons, self.test_seasons, model)
                sig = sigma_wf(np.where(ok, y, 0.0), mu, self.seasons, self.test_seasons)
                if kind == "t5":
                    sig = sig * np.sqrt(3.0 / 5.0)          # a t5 has variance 5/3 of its scale^2: keep the same overall variance
                ls = np.where(ok, logscore(kind, y, mu, sig), np.nan)
                gain = ls - ls0
                m = dict(sel=summarize_window(gain[sel], self.boot('sel', sel)), val=summarize_window(gain[val], self.boot('val', val)),
                         rmse_sel=float(np.sqrt(np.nanmean((y - mu)[sel] ** 2))), rmse_val=float(np.sqrt(np.nanmean((y - mu)[val] ** 2))), derived_from=base["id"])
                rows.append(self.led.record(cfg, m, sample=dict(sel_n=int(sel.sum()), val_n=int(val.sum())), fingerprint=self.fp))
        return rows

    def select(self, target: str) -> dict:
        """The ONE model per target chosen on the selection seasons, with its validation result, the reference model's validation result and a multiple-testing account."""
        rows = [r for r in self.led.select(lab="game/1", target=target)]
        pv = {r["id"]: r["metrics"]["sel"]["p_one"] for r in rows}
        q = S.benjamini_hochberg(pv)
        best = max(rows, key=lambda r: r["metrics"]["sel"]["mean"])
        ref = next((r for r in rows if r["config"]["stage"] == 1 and r["config"]["rating"] == REFERENCE["rating"] and r["config"]["groups"] == REFERENCE["groups"]), None)
        return dict(target=target, n_experiments=len(rows), n_stage1=sum(r["config"]["stage"] == 1 for r in rows), n_stage2=sum(r["config"]["stage"] == 2 for r in rows),
                    best=best, best_bh_q=q[best["id"]], n_bh_q05=sum(v < 0.05 for v in q.values()), reference=ref,
                    n_selection_positive=sum(r["metrics"]["sel"]["mean"] > 0 for r in rows), n_validation_positive=sum(r["metrics"]["val"]["mean"] > 0 for r in rows))

    def final_predictions(self, target: str, cfg: dict) -> pd.DataFrame:
        """Walk-forward mu/sigma for every season 2014-2025 from the chosen config (2025 predicted from <=2024 only), plus climatology for comparison."""
        y = self.target(target); ok = ~np.isnan(y)
        seasons_all = list(range(FIRST_TEST, HOLDOUT + 1))
        X, _ = matrix(self.gt, self.ratings(cfg["rating"]), cfg["groups"])
        mu = wf_mean(X, np.where(ok, y, 0.0), self.seasons, seasons_all, cfg["model"])
        sig = sigma_wf(np.where(ok, y, 0.0), mu, self.seasons, seasons_all)
        if cfg["dist"] == "t5":
            sig = sig * np.sqrt(3.0 / 5.0)
        mu0, sig0 = climatology(np.where(ok, y, 0.0), self.seasons, seasons_all)
        return pd.DataFrame(dict(game_id=self.gt["game_id"], season=self.seasons, week=self.weeks, target=target, dist=cfg["dist"], mu=mu, sigma=sig, mu0=mu0, sigma0=sig0, y=y))
