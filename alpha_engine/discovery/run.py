"""Run a preregistered discovery study (RESEARCH_ONLY).

    python -m alpha_engine.discovery.run --prereg research/discovery/<study>/prereg.json --dataset DS.parquet [--market PATH] [--official DIR] [--holdout]

Writes next to the preregistration: results.json (dev + test + hypotheses), official_labels.json (Kalshi official results as labels,
only seasons outside the holdout unless --holdout), and with --holdout: holdout.json (one-shot; stamped with the preregistration hash).
No dataset row, provider row or price is written. Predictions go to --pred-out (scratch) only when asked.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import engine as E, kalshi_labels as K
from ..input_research import stats as S
from .adapters import ADAPTERS, MARKET_NOTE


def official_eval(sport: str, d: pd.DataFrame, pred: pd.DataFrame, mkt: pd.DataFrame | None, official_dir: Path, prereg: dict, seasons: list[int], aux=None) -> dict:
    A = ADAPTERS[sport]
    off = K.read_official(official_dir, A["series"])
    if off.empty:
        return {"markets": 0, "note": "no official records for the mapped series"}
    o = K.join_games(off, A["schedule"](d, aux), A["alias"])
    act = d[["game_id", "season"] + [t["column"] for t in prereg["targets"].values()]].rename(columns={t["column"]: f"{tn}_actual" for tn, t in prereg["targets"].items()})
    o = K.yes_probability(o, pred.drop(columns=["season"]).merge(act, on="game_id"), A["family_target"])
    out = {"markets_read": int(len(o)), "events_read": int(o.event.nunique()), "events_joined_to_dataset_games": int(o[o.game_id.notna()].event.nunique()),
           "events_not_joined": int(o[o.game_id.isna()].event.nunique()), "not_joined_note": "events with no dataset game within one day (e.g. preseason games, which the dataset excludes)",
           "result_counts": o.result.value_counts().to_dict(), "seasons_scored": seasons, "families": {}}
    o = o[o.game_id.notna() & o.season.isin(seasons)]
    out["excluded_non_binary_result"] = int((~o.result.isin(["yes", "no"])).sum())
    out["excluded_no_side_or_prediction"] = int((o.result.isin(["yes", "no"]) & o.p_model.isna()).sum())
    both = o[o.y_official.notna() & o.y_derived.notna()]
    out["official_vs_score_derived"] = {"compared": int(len(both)), "agree": int((both.y_official == both.y_derived).sum()),
                                        "disagree_tickers": both[both.y_official != both.y_derived].ticker.head(40).tolist(),
                                        "note": "the official result is the label; disagreements are listed for settlement review, not corrected"}
    o = o[o.y_official.notna() & o.p_model.notna()].copy()
    if mkt is not None:                           # sportsbook-derived ladder benchmark: normal around the closing line, sigma from earlier seasons only
        m = mkt.reindex(o.game_id).reset_index(drop=True); o = o.reset_index(drop=True)
        from scipy.stats import norm
        dd = d.merge(mkt, left_on="game_id", right_index=True, how="left"); q = np.full(len(o), np.nan)
        for fam, (kind, tn) in A["family_target"].items():
            t = prereg["targets"][tn]; line = t.get("market_line")
            for s in sorted(o.season.unique()):
                k = ((o.family == fam) & (o.season == s)).to_numpy()
                past = dd[(dd.season < s) & dd[t["column"]].notna() & dd[line].notna()] if line in dd else dd.iloc[:0]
                if not k.any() or len(past) < 500:
                    continue
                sg = float(np.std(past[t["column"]] - past[line])); L = m[line].to_numpy(float)
                x = o.strike.to_numpy(float) if kind != "winner" else np.zeros(len(o)); sgn = np.where(o.side == "away", -1.0, 1.0) if kind != "total" else 1.0
                q[k] = (1 - norm.cdf((x - sgn * L) / sg))[k]
        o["p_line"] = q
    for fam in sorted(o.family.unique()):
        f = o[o.family == fam]; boot = S.ClusterBoot(f.game_id.to_numpy())
        r = {"markets": int(len(f)), "games": int(f.game_id.nunique()), "model": E.prob_metrics(f.p_model, f.y_official),
             "by_season": {str(s): {"markets": int((f.season == s).sum()), "model_brier": round(float(((f.p_model - f.y_official) ** 2)[f.season == s].mean()), 5)} for s in sorted(f.season.unique())}}
        if "p_line" in f and f.p_line.notna().any():
            g = f[f.p_line.notna()]; bg = S.ClusterBoot(g.game_id.to_numpy())
            r["closing_line_benchmark"] = E.prob_metrics(g.p_line, g.y_official)
            r["brier_model_minus_line_benchmark"] = E._ci(bg, ((g.p_model - g.y_official) ** 2 - (g.p_line - g.y_official) ** 2).to_numpy())
            r["by_benchmark_price"] = [{"p_line": [lo, hi], "markets": int(b.sum()), "yes_rate": round(float(g.y_official[b].mean()), 4), "line_mean_p": round(float(g.p_line[b].mean()), 4),
                                        "model_mean_p": round(float(g.p_model[b].mean()), 4), "model_brier": round(float(((g.p_model - g.y_official) ** 2)[b].mean()), 5),
                                        "line_brier": round(float(((g.p_line - g.y_official) ** 2)[b].mean()), 5)}
                                       for lo, hi in prereg.get("price_buckets", []) if (b := ((g.p_line >= lo) & (g.p_line < hi)).to_numpy()).sum() >= 30]
        out["families"][fam] = r
    out["benchmark_note"] = ("closing_line_benchmark = normal distribution centred on the sportsbook closing line (sigma from earlier seasons): a DERIVED probability, not a Kalshi quote. "
                             "No contemporaneous Kalshi price is in the vault snapshot, so no price, CLV or fee-inclusive result is computed.")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--prereg", required=True); ap.add_argument("--dataset", required=True); ap.add_argument("--market"); ap.add_argument("--official")
    ap.add_argument("--holdout", action="store_true"); ap.add_argument("--pred-out")
    a = ap.parse_args(argv)
    pp = Path(a.prereg); prereg = json.loads(pp.read_text()); sport = prereg["sport"]; ph = E.prereg_hash(prereg)
    hold = pp.parent / "holdout.json"
    if hold.exists() and json.loads(hold.read_text())["prereg_sha256"] != ph:
        raise SystemExit("holdout.json was produced under a different preregistration: a changed study needs a new study directory (the holdout is one-shot)")
    if a.holdout and not (pp.parent / "results.json").exists():
        raise SystemExit("run dev/test first: the holdout is scored only after results.json exists for this preregistration")
    if a.holdout and json.loads((pp.parent / "results.json").read_text())["prereg_sha256"] != ph:
        raise SystemExit("results.json belongs to a different preregistration hash")
    d = E.load_dataset(Path(a.dataset), prereg)
    mkt = ADAPTERS[sport]["market"](a.market) if a.market else None
    res = E.run(prereg, d, mkt, holdout=a.holdout)
    pred = res.pop("_predictions")
    res["market_note"] = MARKET_NOTE.get(sport) if mkt is not None else "no market side-table supplied"
    seasons = prereg["splits"]["holdout"] if a.holdout else sorted(set(prereg["splits"]["dev"]) | set(prereg["splits"]["test"]))
    if a.official and ADAPTERS[sport]["series"]:
        dd = d.copy()
        if not a.holdout:
            for t in prereg["targets"].values():
                dd.loc[dd.season.isin(prereg["splits"]["holdout"]), t["column"]] = np.nan
        res["official_labels"] = official_eval(sport, dd, pred, mkt, Path(a.official), prereg, seasons, aux=a.market)
    out = hold if a.holdout else pp.parent / "results.json"
    out.write_text(json.dumps(res, indent=1) + "\n")
    if a.pred_out:
        pred.to_parquet(a.pred_out, index=False)
    print("wrote", out, "prereg", ph[:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
