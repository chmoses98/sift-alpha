"""Expected-starter rule vs production rules: top-1 accuracy (overall, back-to-backs) and log loss, point-in-time.

Splits: fit 2008-09..2020-21 | validate 2021-22..2023-24 | holdout 2024-25, 2025-26, 2026-27 (to 2026-11-17).
Candidates for team-game g (same set for every rule): goalies who started for the team in its previous 30 games.
Rules:
  RESOLVER   conditional logit on (share of last 10 starts, share of last 30, started previous game, previous-game starter on a
             back-to-back, log days since own last start), coefficients fitted on 2008-21 only
  V2_PROD    production V2 with no starter observation: weights = starts in the goalie's previous 82 appearances (any club) + 1
  MOST_RECENT  projection-foundation live fallback: the team's most recent starter
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy.optimize import minimize

HERE = Path(__file__).parent
sys.path.insert(0, "/home/user/NHL-edge-finder/src")

FEATS = ["s10", "s30", "prev", "prev_b2b", "lgap"]

def load():
    d = pd.read_csv(HERE / "data/starters_history.csv.gz")
    d["date"] = pd.to_datetime(d.game_date)
    return d.sort_values(["team_id", "date", "game_id"]).reset_index(drop=True)

def appearances():
    """(goalie, date) appearances incl. relief: MoneyPuck goalie game log 2008-25 + 2026-27 starters (relief not available, disclosed)."""
    from nhl_edge.features import goalie_talent as gt
    H = Path("/home/user/NHL-edge-finder/data/history")
    paths = sorted((H / "shots_extension").glob("shots_*.parquet")) + sorted((H / "moneypuck").glob("shots_*.parquet"))
    shots = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
    games = pd.concat([pd.read_parquet(p) for p in sorted((H / "nhl").glob("games_*.parquet"))])
    gl = gt.goalie_game_log(shots, games)
    a = gl[["goalie_id", "game_date", "game_id", "starter"]].rename(columns={"game_date": "date"})
    return a

def build_rows(d, app):
    app = app.copy(); app["date"] = pd.to_datetime(app.date)
    by_g = {g: x.sort_values("date") for g, x in app.groupby("goalie_id")}
    rows = []
    for tid, t in d.groupby("team_id"):
        t = t.reset_index(drop=True)
        st, dates = t.starter_id.to_numpy(), t.date.to_numpy()
        for i in range(1, len(t)):
            lo = max(0, i - 30)
            cands = list(dict.fromkeys(st[lo:i][::-1]))
            if not cands: continue
            b2b = (dates[i] - dates[i - 1]) / np.timedelta64(1, "D") == 1
            last10, last30 = st[max(0, i - 10):i], st[lo:i]
            for c in cands:
                idx = np.where(st[:i] == c)[0]; gap = (dates[i] - dates[idx[-1]]) / np.timedelta64(1, "D")
                ga = by_g.get(c)
                if ga is not None:
                    prev_apps = ga[ga.date < dates[i]].tail(82); v2w = float(prev_apps.starter.sum()) + 1.0
                else:
                    v2w = 1.0
                rows.append({"key": f"{t.game_id[i]}_{tid}", "game_id": int(t.game_id[i]), "season": int(t.season[i]), "team_id": int(tid), "cand": int(c),
                             "y": int(c == st[i]), "s10": float((last10 == c).mean()), "s30": float((last30 == c).mean()), "prev": float(st[i - 1] == c),
                             "b2b": bool(b2b), "prev_b2b": float(b2b and st[i - 1] == c), "lgap": float(np.log1p(min(gap, 365))), "v2w": v2w,
                             "most_recent": float(c == st[i - 1]), "actual_in_set": bool(st[i] in cands), "source": t.source[i]})
    return pd.DataFrame(rows)

def softmax_by(keys, z):
    z = z - pd.Series(z).groupby(keys).transform("max").to_numpy()
    e = np.exp(z); return e / pd.Series(e).groupby(keys).transform("sum").to_numpy()

def fit(R):
    X, y, k = R[FEATS].to_numpy(), R.y.to_numpy(), pd.factorize(R.key)[0]
    def nll(b):
        p = softmax_by(k, X @ b); return -np.sum(y * np.log(np.clip(p, 1e-12, 1))) + 0.5 * 1e-3 * b @ b
    return minimize(nll, np.zeros(len(FEATS)), method="L-BFGS-B").x

def score(R, prob_col):
    g = R.groupby("key")
    top = R.loc[g[prob_col].idxmax()]
    acc = top.y.to_numpy()
    p_act = g.apply(lambda x: float((x[prob_col] * x.y).sum()), include_groups=False).reindex(top.key).to_numpy()
    ll = -np.log(np.clip(p_act, 1e-6, 1))
    return acc, ll, top.b2b.to_numpy()

def boot_ci(x, n=2000, seed=7):
    r = np.random.default_rng(seed); m = [x[r.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [float(np.quantile(m, .025)), float(np.quantile(m, .975))]

def main():
    d = load(); app = appearances()
    # 2026-27 appearances: starters only (no relief available without new collection)
    a26 = d[d.season == 2026][["starter_id", "game_date", "game_id"]].rename(columns={"starter_id": "goalie_id", "game_date": "date"}).assign(starter=1)
    R = build_rows(d, pd.concat([app, a26]))
    R.to_parquet(HERE / "data/resolver_rows.parquet")
    fitR = R[R.season <= 2020]
    b = fit(fitR)
    R["p_res"] = softmax_by(pd.factorize(R.key)[0], R[FEATS].to_numpy() @ b)
    R["p_v2"] = R.v2w / R.groupby("key").v2w.transform("sum")
    R["p_mr"] = np.where(R.most_recent == 1, 0.999, 0.001); R["p_mr"] = R.p_mr / R.groupby("key").p_mr.transform("sum")
    out = {"coef": dict(zip(FEATS, map(float, b))), "fit_seasons": "2008-2020", "candidate_rule": "starters in the team's previous 30 games", "splits": {}}
    for name, sel in {"validation_2021_2023": R.season.between(2021, 2023), "holdout_2024_2025": R.season.between(2024, 2025), "holdout_2026_to_2026-11-17": R.season == 2026}.items():
        S = R[sel]; res = {"n_team_games": int(S.key.nunique()), "actual_in_candidate_set": float(S.groupby("key").actual_in_set.first().mean())}
        accs = {}
        for rule, col in (("RESOLVER", "p_res"), ("V2_PROD", "p_v2"), ("MOST_RECENT", "p_mr")):
            acc, ll, b2b = score(S, col); accs[rule] = (acc, ll)
            res[rule] = {"top1": float(acc.mean()), "top1_ci": boot_ci(acc.astype(float)), "top1_b2b": float(acc[b2b].mean()), "n_b2b": int(b2b.sum()),
                         "top1_non_b2b": float(acc[~b2b].mean()), "log_loss": float(ll.mean()) if rule != "MOST_RECENT" else None}
        for base in ("V2_PROD", "MOST_RECENT"):
            diff = accs["RESOLVER"][0].astype(float) - accs[base][0].astype(float)
            res[f"RESOLVER_minus_{base}_top1"] = {"d": float(diff.mean()), "ci": boot_ci(diff)}
        dll = accs["RESOLVER"][1] - accs["V2_PROD"][1]; res["RESOLVER_minus_V2_PROD_logloss"] = {"d": float(dll.mean()), "ci": boot_ci(dll)}
        out["splits"][name] = res
    (HERE / "results/resolver_eval.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
