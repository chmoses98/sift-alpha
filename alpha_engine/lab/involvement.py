"""P(involved) model for player props (market-free).  A yards/receptions/attempt contract settles NO for a player with no recorded involvement, so
    P(YES) = P(involved) * P(stat >= k | involved)
and the conditional part is what the player lab models.  The previous factor was the raw appearance rate over the team's last 8 games over EVERY player who appeared, which
(a) mixes fringe players with regulars and (b) ignores report status, so it discounted the regulars that markets list by ~12%.  Here a logistic model is fitted on seasons strictly
before the predicted one, on the at-risk universe (players with >=1 appearance for the team in its previous 8 games).  Published 'Out' => 0 (unchanged rule)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

FEATS = ["rate8", "rate3", "last1", "use8", "inj_q", "inj_d", "rate8_use8", "use_rank", "use_share", "top3"]


def at_risk_table(pg: pd.DataFrame, window: int = 8) -> pd.DataFrame:
    pg = pg.copy()
    pg["usage"] = pg[["tgt", "car", "att"]].fillna(0).sum(axis=1)
    rows = []
    for team, g in pg.groupby("team"):
        games = g.drop_duplicates("game_id").sort_values(["date", "game_id"])[["game_id", "date", "season", "week"]].reset_index(drop=True)
        pids = np.sort(g["pid"].unique()); pi = {p: i for i, p in enumerate(pids)}; gi = {gid: j for j, gid in enumerate(games["game_id"])}
        A = np.zeros((len(pids), len(games)), dtype=bool); U = np.zeros((len(pids), len(games)))
        a = g["pid"].map(pi).to_numpy(); b = g["game_id"].map(gi).to_numpy()
        A[a, b] = True; U[a, b] = g["usage"].to_numpy()
        for j in range(1, len(games)):
            w = slice(max(0, j - window), j)
            n = A[:, w].sum(1)
            m = n > 0
            if not m.any():
                continue
            w3 = slice(max(0, j - 3), j)
            use = U[:, w].sum(1)[m] / np.maximum(n[m], 1)
            rows.append(pd.DataFrame({"pid": pids[m], "team": team, "game_id": games.at[j, "game_id"], "date": games.at[j, "date"], "season": games.at[j, "season"], "week": games.at[j, "week"],
                                      "rate8": n[m] / (j - w.start), "rate3": A[m][:, w3].sum(1) / (j - w3.start), "last1": A[m][:, j - 1].astype(float),
                                      "use8": use, "y": A[m][:, j].astype(float)}))
    return pd.concat(rows, ignore_index=True)


def add_injury(t: pd.DataFrame, inj: pd.DataFrame) -> pd.DataFrame:
    x = t.merge(inj.rename(columns={"gsis_id": "pid", "code": "inj_code"}), on=["season", "week", "pid"], how="left")
    x["inj_q"] = (x["inj_code"] == 0.25).astype(float); x["inj_d"] = (x["inj_code"] == 0.85).astype(float); x["inj_out"] = (x["inj_code"] == 1.0)
    # role within the team's own at-risk pool (pre-game information only): usage rank / share among teammates, and "top-3 by usage"
    raw = x["use8"].copy()
    grp = x.groupby(["game_id", "team"])
    x["use_rank"] = np.log1p(grp["use8"].rank(ascending=False, method="first"))
    x["use_share"] = raw / grp["use8"].transform("sum").clip(lower=1e-6)
    x["top3"] = (grp["use8"].rank(ascending=False, method="first") <= 3).astype(float)
    x["use8"] = np.log1p(x["use8"]); x["rate8_use8"] = x["rate8"] * x["use8"]
    return x


def fit(t: pd.DataFrame, seasons) -> LogisticRegression:
    d = t[t["season"].isin(seasons) & ~t["inj_out"]]
    return LogisticRegression(C=1.0, max_iter=500).fit(d[FEATS].to_numpy(float), d["y"].to_numpy(float))


def predict(m: LogisticRegression, t: pd.DataFrame) -> np.ndarray:
    p = m.predict_proba(t[FEATS].to_numpy(float))[:, 1]
    return np.where(t["inj_out"], 0.0, p)
