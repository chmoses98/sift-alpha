"""Index and report of every preregistered discovery study (RESEARCH_ONLY).

    python -m alpha_engine.discovery.report

Reads research/discovery/<study>/{prereg,results,holdout}.json; writes research/discovery/index.json (dashboard) and docs/DISCOVERY_REPORT.md.
Sentences are generated from the numbers; a study with no holdout.json is reported as sealed.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "research/discovery"


def _rng(x):
    return f"{x[0]}-{x[-1]}" if len(x) > 1 else str(x[0])


def study(p: Path) -> dict | None:
    if not (p / "results.json").exists():
        return None
    pr = json.loads((p / "prereg.json").read_text()); r = json.loads((p / "results.json").read_text())
    h = json.loads((p / "holdout.json").read_text()) if (p / "holdout.json").exists() else None
    full, ref = pr["full_model"], pr["reference_model"]; f = []; rows = []
    for split, src in (("test", r["test"]), ("holdout", h["holdout"] if h else None)):
        if not src:
            continue
        for tn, t in src["targets"].items():
            m = t["models"]; vm = t.get("vs_market"); w = t.get("win_prob_vs_market")
            row = {"split": split, "target": tn, "n": t["n"], "rmse_climatology": m["climatology"]["rmse"], "rmse_reference": m[ref]["rmse"], "rmse_full": m[full]["rmse"],
                   "mae_full": m[full]["mae"], "signed_error_full": m[full]["signed_error_pred_minus_actual"], "ref_minus_full_sq_err_ci95": m[ref]["sq_err_minus_full"]["ci95"],
                   "win_brier_full": (m[full].get("win_prob") or {}).get("brier"), "win_accuracy_full": (m[full].get("win_prob") or {}).get("accuracy"),
                   "win_calibration_slope_full": (m[full].get("win_prob") or {}).get("calibration_slope")}
            if vm:
                row.update(market_mae=vm["market_line"]["mae"], model_mae_on_market_games=vm["model"]["mae"], sq_err_model_minus_market_ci95=vm["sq_err_model_minus_market"]["ci95"],
                           side_decisions=vm["side_vs_line"]["decisions"], side_hit_rate=round(0.5 + vm["side_vs_line"]["hit_rate"]["mean"], 4),
                           side_hit_rate_ci95=[round(0.5 + x, 4) for x in vm["side_vs_line"]["hit_rate"]["ci95"]])
            if w:
                row.update(win_brier_market=w["market_devig"]["brier"], win_brier_model_minus_market_ci95=w["brier_model_minus_market"]["ci95"])
            rows.append(row)
    hy = r["hypotheses_test"]; vc = Counter(x["verdict"] for x in hy)
    t = {x["target"]: x for x in rows if x["split"] == "test"}
    mg = t.get("margin")
    if mg:
        f.append(f"Test seasons, margin: full model RMSE {mg['rmse_full']} vs reference {mg['rmse_reference']} vs climatology {mg['rmse_climatology']} (n={mg['n']:,}); winner picked {round(100 * mg['win_accuracy_full'], 1)}% of the time, win-probability Brier {mg['win_brier_full']}.")
        if "market_mae" in mg:
            lo, hi = mg["sq_err_model_minus_market_ci95"]
            f.append(f"Against the closing spread: model MAE {mg['model_mae_on_market_games']} vs line {mg['market_mae']}; squared-error gap 95% CI [{lo}, {hi}] ({'the line is more accurate' if lo > 0 else 'no reliable difference'}). "
                     f"Side picked against the line was right {round(100 * mg['side_hit_rate'], 1)}% of {mg['side_decisions']:,} decisions (95% CI {round(100 * mg['side_hit_rate_ci95'][0], 1)}-{round(100 * mg['side_hit_rate_ci95'][1], 1)}%; 52.4% is break-even at -110).")
    tt = t.get("total")
    if tt:
        s = f"Test seasons, total: full model RMSE {tt['rmse_full']} vs reference {tt['rmse_reference']} (n={tt['n']:,})"
        if "market_mae" in tt:
            s += f"; MAE {tt['model_mae_on_market_games']} vs closing total {tt['market_mae']}; side hit rate {round(100 * tt['side_hit_rate'], 1)}% (95% CI {round(100 * tt['side_hit_rate_ci95'][0], 1)}-{round(100 * tt['side_hit_rate_ci95'][1], 1)}%)"
        f.append(s + ".")
    dem = [f"{x['group']} ({x['target']})" for x in hy if x["verdict"] == "DEMONSTRATED_INCREMENTAL"]
    f.append("Inputs that improve on the reference after Holm correction: " + (", ".join(dem) if dem else "none") + ".")
    if h:
        hm = next((x for x in rows if x["split"] == "holdout" and x["target"] == "margin"), None)
        if hm:
            s = f"Holdout ({_rng(pr['splits']['holdout'])}, scored once, n={hm['n']:,}): margin RMSE {hm['rmse_full']} vs reference {hm['rmse_reference']}"
            if "market_mae" in hm:
                s += f"; MAE {hm['model_mae_on_market_games']} vs line {hm['market_mae']}; side hit rate {round(100 * hm['side_hit_rate'], 1)}% (95% CI {round(100 * hm['side_hit_rate_ci95'][0], 1)}-{round(100 * hm['side_hit_rate_ci95'][1], 1)}%)"
            f.append(s + ".")
        ol = h.get("official_labels")
        if ol and ol.get("families"):
            c = ol["official_vs_score_derived"]
            f.append(f"Kalshi official results on the holdout: {sum(v['markets'] for v in ol['families'].values()):,} contracts scored; official label equals the score-derived outcome on {c['agree']:,} of {c['compared']:,}. "
                     + " ".join(f"{k}: model Brier {v['model']['brier']}" + (f" vs closing-line benchmark {v['closing_line_benchmark']['brier']}" if "closing_line_benchmark" in v else "") + "." for k, v in ol["families"].items()))
    return {"study": pr["study"], "sport": pr["sport"], "title": pr["market_family"], "dataset": pr["dataset_sha256"][:12], "prereg_sha256": r["prereg_sha256"][:12],
            "dev": _rng(pr["splits"]["dev"]), "test": _rng(pr["splits"]["test"]), "holdout": _rng(pr["splits"]["holdout"]), "holdout_scored": bool(h),
            "hypotheses": {"tested": len(hy), "demonstrated": vc.get("DEMONSTRATED_INCREMENTAL", 0), "suggestive": vc.get("SUGGESTIVE_UNCONFIRMED", 0), "worse": vc.get("WORSE_THAN_BASELINE", 0),
                           "not_demonstrated": vc.get("NOT_DEMONSTRATED", 0)},
            "hypothesis_rows": [{k: x.get(k) for k in ("group", "target", "gain_sq_err", "ci95", "p_holm", "seasons_positive", "verdict")} for x in hy],
            "rows": rows, "findings": f, "not_claimed": pr["not_claimed"], "labels": pr["labels"]}


def main() -> int:
    studies = [s for p in sorted(DIR.iterdir()) if p.is_dir() and (s := study(p))]
    order = {"NFL": 0, "CFB": 1, "NBA": 2, "NHL": 3, "CBB": 4, "MLB": 5}
    studies.sort(key=lambda s: (order.get(s["sport"], 9), s["study"]))
    joint = {p.stem.split("_")[-1]: json.loads(p.read_text()) for p in sorted(DIR.glob("joint_dependence_*.json"))}
    (DIR / "index.json").write_text(json.dumps({"schema": "discovery-index-1.0", "status": "RESEARCH_ONLY", "studies": studies,
                                                "joint": {k: {"games": v["games"], "pairs": v["pairs"]} for k, v in joint.items()}}, indent=1) + "\n")
    L = ["# Discovery report (preregistered, out-of-sample)", "",
         "Generated by `python -m alpha_engine.discovery.report` from `research/discovery/*/`. RESEARCH_ONLY. Agent-run, not human verified.",
         "Accuracy evidence only: no executable price, liquidity or fee data is used anywhere, so nothing here is a claim of betting value.",
         "Every study: registered dataset hash, features market-free, walk-forward by season, hypotheses frozen in git before scoring, Holm correction, holdout scored once.", ""]
    for s in studies:
        L += [f"## {s['sport']}: {s['title']}", "", f"Study `{s['study']}` · dataset `{s['dataset']}` · preregistration `{s['prereg_sha256']}` · dev {s['dev']} · test {s['test']} · holdout {s['holdout']} ({'scored once' if s['holdout_scored'] else 'sealed'})", ""]
        L += [f"* {x}" for x in s["findings"]] + ["", f"Labels: {s['labels']}", "", "| Hypothesis (added to the reference) | Target | Squared-error gain | 95% CI | Holm p | Seasons better | Verdict |", "|---|---|---|---|---|---|---|"]
        L += [f"| {x['group']} | {x['target']} | {x['gain_sq_err']} | {x['ci95']} | {x['p_holm']} | {x['seasons_positive']} | {str(x['verdict']).replace('_', ' ').lower()} |" for x in s["hypothesis_rows"]]
        L += ["", f"Not claimed: {s['not_claimed']}", ""]
    if joint:
        L += ["## Dependence between game-line outcomes", "", "`python -m alpha_engine.discovery.joint`. Events against the sportsbook closing line; pushes excluded; season-week cluster bootstrap.",
              "A ratio of 1.00 means multiplying the two leg probabilities gives the right joint probability.", "", "| Sport | Pair | Games | Joint | Product of legs | Joint / product | 95% CI | phi |", "|---|---|---|---|---|---|---|---|"]
        for k, v in joint.items():
            L += [f"| {k} | {n} | {x['n']:,} | {x['p_joint']} | {x['p_product']} | {x['joint_over_product']} | {x['joint_over_product_ci95']} | {x['phi']} |" for n, x in v["pairs"].items()]
        L += [""]
    (ROOT / "docs/DISCOVERY_REPORT.md").write_text("\n".join(L) + "\n")
    print("studies", [s["study"] for s in studies])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
