"""Market-free systematic search for soccer match totals and goal difference (RESEARCH_ONLY).

Data: football-data.co.uk results CSVs (free). ONLY a whitelist of result/shot/corner/foul/card columns is read; every bookmaker odds column is dropped before any feature is built
(marketfree.assert_market_free also guards the feature names). Features are pregame EWMAs of each team's past matches (no match sees itself). Baseline for totals = the running league mean
total goals before the match. Targets: total goals (totals markets) and home-minus-away goals (match result / handicap markets).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import marketfree as MF, search as SR

OUT = Path(__file__).resolve().parents[2] / "research/audit/input_research/experiments"
KEEP = ["Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "HS", "AS", "HST", "AST", "HC", "AC", "HF", "AF", "HY", "AY", "HR", "AR"]
HL = 8.0   # EWMA half-life in matches
GROUPS = {"attack_form": ["gf_h", "gf_a", "sotf_h", "sotf_a"], "defence_form": ["ga_h", "ga_a", "sota_h", "sota_a"], "matchup_expected_goals": ["exp_h", "exp_a", "exp_total"],
          "team_strength_elo": ["elo_diff", "elo_h", "elo_a"], "tempo_set_pieces": ["cor_h", "cor_a", "shots_h", "shots_a"], "discipline": ["foul_h", "foul_a", "card_h", "card_a"],
          "rest_schedule": ["rest_h", "rest_a"], "league_context": ["lg_home_adv", "lg_goals"]}


def load(d: Path) -> pd.DataFrame:
    rows = []
    for f in sorted(d.glob("*.csv")):
        lg, yr = f.stem.split("_")
        x = pd.read_csv(f, encoding="utf-8-sig", usecols=lambda c: c in KEEP, on_bad_lines="skip")
        if "FTHG" not in x:
            continue
        x = x.dropna(subset=["FTHG", "FTAG", "HomeTeam", "AwayTeam", "Date"])
        x["Date"] = pd.to_datetime(x["Date"], dayfirst=True, errors="coerce")
        x["league"] = lg
        x["season"] = 2000 + int(yr[:2])
        rows.append(x)
    d = pd.concat(rows, ignore_index=True).dropna(subset=["Date"]).sort_values(["Date", "league", "HomeTeam"]).reset_index(drop=True)
    for c in KEEP[5:]:
        if c not in d:
            d[c] = np.nan
    return d


def features(m: pd.DataFrame) -> pd.DataFrame:
    lam = 0.5 ** (1 / HL)
    st: dict = {}
    elo: dict = {}
    last: dict = {}
    lg_tot = {}; lg_ha = {}
    rows = []
    METR = ["gf", "ga", "sotf", "sota", "cor", "shots", "foul", "card"]
    for r in m.itertuples(index=False):
        h, a = (r.league, r.HomeTeam), (r.league, r.AwayTeam)
        sh, sa = st.get(h), st.get(a)
        def g(s, k): return s[k][0] / s[k][1] if s and s[k][1] > 0 else np.nan
        n = min(sh["n"] if sh else 0, sa["n"] if sa else 0)
        lt = lg_tot.get(r.league); lh = lg_ha.get(r.league)
        f = {"gf_h": g(sh, "gf"), "ga_h": g(sh, "ga"), "gf_a": g(sa, "gf"), "ga_a": g(sa, "ga"), "sotf_h": g(sh, "sotf"), "sota_h": g(sh, "sota"), "sotf_a": g(sa, "sotf"), "sota_a": g(sa, "sota"),
             "cor_h": g(sh, "cor"), "cor_a": g(sa, "cor"), "shots_h": g(sh, "shots"), "shots_a": g(sa, "shots"), "foul_h": g(sh, "foul"), "foul_a": g(sa, "foul"), "card_h": g(sh, "card"), "card_a": g(sa, "card"),
             "elo_h": elo.get(h, 1500.0), "elo_a": elo.get(a, 1500.0), "n_min": n, "lg_goals": lt[0] / lt[1] if lt else np.nan, "lg_home_adv": lh[0] / lh[1] if lh else np.nan,
             "rest_h": min((r.Date - last[h]).days, 14) if h in last else np.nan, "rest_a": min((r.Date - last[a]).days, 14) if a in last else np.nan}
        f["elo_diff"] = f["elo_h"] - f["elo_a"]
        f["exp_h"] = (f["gf_h"] + f["ga_a"]) / 2; f["exp_a"] = (f["gf_a"] + f["ga_h"]) / 2; f["exp_total"] = f["exp_h"] + f["exp_a"]
        rows.append(f)
        # update AFTER the row is emitted
        def upd(team, gf, ga, sotf, sota, cor, sh_, foul, card):
            s = st.setdefault(team, {k: [0.0, 0.0] for k in METR} | {"n": 0})
            for k, v in zip(METR, (gf, ga, sotf, sota, cor, sh_, foul, card)):
                if v == v:
                    s[k][0] = s[k][0] * lam + v; s[k][1] = s[k][1] * lam + 1.0
            s["n"] += 1
        upd(h, r.FTHG, r.FTAG, r.HST, r.AST, r.HC, r.HS, r.HF, r.HY + 2 * r.HR if r.HY == r.HY else np.nan)
        upd(a, r.FTAG, r.FTHG, r.AST, r.HST, r.AC, r.AS, r.AF, r.AY + 2 * r.AR if r.AY == r.AY else np.nan)
        exp_d = (elo.get(h, 1500.0) + 60 - elo.get(a, 1500.0)) / 400.0
        pw = 1 / (1 + 10 ** (-exp_d)); res = 1.0 if r.FTHG > r.FTAG else (0.5 if r.FTHG == r.FTAG else 0.0)
        k = 20.0 * (1 + 0.25 * min(abs(r.FTHG - r.FTAG), 3))
        elo[h] = elo.get(h, 1500.0) + k * (res - pw); elo[a] = elo.get(a, 1500.0) - k * (res - pw)
        last[h] = last[a] = r.Date
        t = lg_tot.setdefault(r.league, [0.0, 0.0]); t[0] = t[0] * 0.999 + r.FTHG + r.FTAG; t[1] = t[1] * 0.999 + 1
        ha = lg_ha.setdefault(r.league, [0.0, 0.0]); ha[0] = ha[0] * 0.999 + r.FTHG - r.FTAG; ha[1] = ha[1] * 0.999 + 1
    return pd.concat([m.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def study(d: pd.DataFrame, target: str, n_configs=120, null_reps=1) -> dict:
    MF.assert_market_free([c for g in GROUPS.values() for c in g])
    d = d[(d.n_min >= 5) & d.lg_goals.notna()].copy()
    y = (d.FTHG + d.FTAG) if target == "total_goals" else (d.FTHG - d.FTAG)
    base = d.lg_goals if target == "total_goals" else d.lg_home_adv
    r = (y - base).to_numpy(float)
    d = d.reset_index(drop=True)
    keys = (d.season.astype(str) + "-" + d.Date.dt.isocalendar().week.astype(str)).to_numpy()
    tests = range(int(d.season.min()) + 6, int(d.season.max()) + 1)
    res = SR.nested_search(d, r, GROUPS, tests, n_configs=n_configs)
    gain = SR.summarize_gain(d, r, res["pred"], keys)
    null = SR.permutation_null(d, r, GROUPS, tests, keys, reps=null_reps, n_configs=n_configs)
    ch = res["chosen"]
    imp = {}
    for g in GROUPS:
        dl = np.array([c["core_inner_rel_mse"][f"drop:{g}"] - c["core_inner_rel_mse"]["full"] for c in ch])
        imp[g] = {"mean_rel_mse_increase_when_dropped": round(float(dl.mean()), 5), "folds_where_dropping_hurts": int((dl > 0).sum()), "folds": int(len(dl)), "se": round(float(dl.std(ddof=1) / np.sqrt(len(dl))), 5)}
    return {"target": target, "baseline": "running league mean total goals" if target == "total_goals" else "running league home advantage", "n_matches": int(len(d)), "nested_gain": gain,
            "permutation_null": null, "group_importance_leave_one_group_out_inner": imp,
            "group_selection_frequency": {g: round(float(np.mean([g in c["config"]["groups"] for c in ch])), 3) for g in GROUPS},
            "model_structure_frequency": {k: round(float(np.mean([c["config"]["model"] == k for c in ch])), 3) for k in ("ridge", "gbm")}}


def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--data-dir", required=True); ap.add_argument("--n-configs", type=int, default=120); a = ap.parse_args()
    m = features(load(Path(a.data_dir)))
    out = {"schema_version": "search-soccer-1.0", "status": "RESEARCH_ONLY", "market_free": True, "source": "football-data.co.uk results CSVs (E0, SP1, D1, I1, F1; 2015/16-2025/26); odds columns never read",
           "leagues": ["E0", "SP1", "D1", "I1", "F1"], "groups": GROUPS, "n_configs_per_fold": a.n_configs,
           "studies": {t: study(m, t, a.n_configs) for t in ("total_goals", "goal_difference")}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "search_soccer_v1.json").write_text(json.dumps(out, indent=1, default=float))
    for t, s in out["studies"].items():
        g = s["nested_gain"]
        print(t, s["n_matches"], f"gain {g['pct_gain']:.2f}% CI {g['ci_0.05']} seasons+ {g['seasons_positive']}/{len(g['seasons'])} null {[round(x['pct_gain'],2) for x in s['permutation_null']]}")


if __name__ == "__main__":
    main()
