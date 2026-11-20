"""Freeze every CFB forward candidate BEFORE any 2026 week >= 6 outcome or quote is scored (RESEARCH_ONLY).

Fit data: 2024-2025 seasons only (projection -> outcome mappings and sigmas), plus 2026 weeks 1-5 Kalshi WIN/SPREAD quotes
for the single market-recalibration candidate (those weeks were already scored by PR #98; weeks >= 6 never were).
Output: frozen_specs.json with a sha256 over its content. score_forward.py refuses to run if the hash does not match.

Projection sources (all pre-game, no market price):
  incumbent   cfb-edge-finder scoring baseline (adjust.fit_metric points_per_game, unchanged)
  blend97     PR #97 blend (coefficients read from report_2026_corrected.json, not refit)
  frozenA98   PR #98 frozen forward candidate A (coefficients read from audit_report_2026.json, not refit)
  he          cfb-edge-finder experimental venue-only home effect (FROZEN_CANDIDATE, chosen on 2015-2023)
  he_blend    he + PR #96 cfbx inputs, OLS on 2024-2025

Distribution per (source, period P, quantity q): q_P ~ Normal(alpha + beta * proj_q, sigma), fitted by OLS on 2024-2025,
P in {FG, 1H, 2H, 1Q}, q in {margin, total, home_pts, away_pts}. For the full game the existing approach is kept for the
margin of incumbent/blend97/frozenA98 (alpha = 0, beta = 1 for incumbent and blend97, i.e. the projection itself) so the
"existing recommendation process" is scored as it was specified.

  python research/cfb_forward_validation/freeze.py --he-records <cfb-edge-finder>/data/scripting/validation/home_effect_experimental/records.jsonl.gz \
      --cfbd-root <research-data>/data/research_cache/v2 --team-cache team.pkl --cfb <cfb-edge-finder> --espn RAW/a,RAW/b \
      --out research/cfb_forward_validation/frozen_specs.json
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "research" / "cfb_bet_selection"))

SOURCES = ("incumbent", "blend97", "frozenA98", "he", "he_blend")
PERIODS = ("FG", "1H", "2H", "1Q")
QUANTS = ("margin", "total", "home_pts", "away_pts")
FIT_SEASONS = (2024, 2025)
LAST_SEEN_WEEK_2026 = 5


def jl(p):
    with gzip.open(p, "rt") as fh:
        return [json.loads(x) for x in fh]


def period_actuals_cfbd(root: Path, season: int) -> pd.DataFrame:
    g = json.load(gzip.open(root / str(season) / "games.json.gz", "rt"))
    rows = []
    for x in g:
        h, a = x.get("homeLineScores") or [], x.get("awayLineScores") or []
        if len(h) < 4 or len(a) < 4 or x.get("homePoints") is None:
            continue
        rows.append({"game_id": str(x["id"]), "h1q": h[0], "a1q": a[0], "h1h": h[0] + h[1], "a1h": a[0] + a[1], "h2h": sum(h[2:]), "a2h": sum(a[2:]), "hfg": x["homePoints"], "afg": x["awayPoints"]})
    return pd.DataFrame(rows)


def projections(he_records: Path, team_cache: Path) -> pd.DataFrame:
    """One row per game with every source's pre-game margin and total."""
    r = pd.DataFrame(jl(he_records))
    r["he_margin"] = r.selected.map(lambda v: None if v is None else v[0]); r["he_total"] = r.selected.map(lambda v: None if v is None else v[1])
    r = r.rename(columns={"inc_margin": "incumbent_margin", "inc_total": "incumbent_total"})
    t = pd.read_pickle(team_cache); h = t[t.is_home == 1][["game_id", "cfbx_mar_pre", "cfbx_tot_pre"]].copy(); h["game_id"] = h.game_id.astype(str)
    r = r.merge(h, on="game_id", how="left")
    rep97 = json.loads((ROOT / "research/cfb_bet_selection/report_2026_corrected.json").read_text())["fit"]
    bm, bt = rep97["mar"]["blend_coef"], rep97["tot"]["blend_coef"]
    r["blend97_margin"] = bm[0] + bm[1] * r.incumbent_margin + bm[2] * r.cfbx_mar_pre
    r["blend97_total"] = bt[0] + bt[1] * r.incumbent_total + bt[2] * r.cfbx_tot_pre
    fa = json.loads((ROOT / "research/cfb_bet_selection/audit_report_2026.json").read_text())["frozen_forward_candidate"]
    c = fa["coef"]["coef_[1,inc_minus_2h,h,cfbx]"]; hh = r.inc_2h / 2
    r["frozenA98_margin"] = c[0] + c[1] * (r.incumbent_margin - 2 * hh) + c[2] * hh + c[3] * r.cfbx_mar_pre
    r["frozenA98_total"] = r.blend97_total  # A changes the margin only
    return r


def fit_he_blend(r: pd.DataFrame) -> dict:
    tr = r[r.season.isin(FIT_SEASONS)].dropna(subset=["he_margin", "cfbx_mar_pre", "he_total", "cfbx_tot_pre"])
    out = {}
    for q, a, b in (("margin", "he_margin", "cfbx_mar_pre"), ("total", "he_total", "cfbx_tot_pre")):
        A = np.c_[np.ones(len(tr)), tr[a], tr[b]]; y = tr[f"actual_{q}"]
        out[q] = np.linalg.lstsq(A, y, rcond=None)[0].round(5).tolist()
    return out


def add_he_blend(r: pd.DataFrame, coef: dict) -> pd.DataFrame:
    r["he_blend_margin"] = coef["margin"][0] + coef["margin"][1] * r.he_margin + coef["margin"][2] * r.cfbx_mar_pre
    r["he_blend_total"] = coef["total"][0] + coef["total"][1] * r.he_total + coef["total"][2] * r.cfbx_tot_pre
    return r


def proj(r: pd.DataFrame, s: str, q: str) -> pd.Series:
    m, t = r[f"{s}_margin"], r[f"{s}_total"]
    return {"margin": m, "total": t, "home_pts": (t + m) / 2, "away_pts": (t - m) / 2}[q]


def actual(df: pd.DataFrame, p: str, q: str) -> pd.Series:
    k = {"FG": "fg", "1H": "1h", "2H": "2h", "1Q": "1q"}[p]
    h, a = df[f"h{k}"], df[f"a{k}"]
    return {"margin": h - a, "total": h + a, "home_pts": h, "away_pts": a}[q]


def fit_distributions(r: pd.DataFrame, per: pd.DataFrame) -> dict:
    d = r[r.season.isin(FIT_SEASONS)].merge(per, on="game_id", how="inner")
    spec = {}
    for s in SOURCES:
        for p in PERIODS:
            for q in QUANTS:
                x = proj(d, s, q); y = actual(d, p, q); ok = x.notna() & y.notna()
                x, y = x[ok].to_numpy(float), y[ok].to_numpy(float)
                if p == "FG" and q == "margin" and s in ("incumbent", "blend97", "frozenA98", "he_blend"):
                    a, b = 0.0, 1.0  # the source's own margin, as specified by its PR / fit
                else:
                    b, a = np.polyfit(x, y, 1)
                sig = float(np.std(y - (a + b * x), ddof=2))
                spec[f"{s}|{p}|{q}"] = {"alpha": round(float(a), 5), "beta": round(float(b), 5), "sigma": round(sig, 5), "n": int(len(x))}
    return spec


def market_recal(args) -> dict:
    """Candidate C frozen: logit(y) = a + b*logit(p_frozenA98) + c*logit(mid), fit once on ALL 2026 weeks 1-5 WIN/SPREAD contracts."""
    import audit_calibration as A
    import evaluate as E
    ns = argparse.Namespace(espn=args.espn, cfb=args.cfb, cache=args.team_cache)
    d, V = E.frame(ns); dec = A.fit_decoupled(d); q = A.quote_table(V, d)
    q = q[q.week <= LAST_SEEN_WEEK_2026]
    p = A.p_yes(q, q.decoup_mar, dec["sigma_train"])
    b = A.irls(np.c_[np.ones(len(q)), A.lg(p), A.lg(q.mid)], q.y.to_numpy())
    return {"coef_[1,logit_model,logit_mid]": b.round(5).tolist(), "fit_contracts": int(len(q)), "fit_games": int(q.game_id.nunique()), "fit_weeks": sorted(int(w) for w in q.week.unique()),
            "model_for_logit": "frozenA98 full-game margin, sigma_train", "applies_to": "all families (the same logit map), scored weeks >= 6 only"}


def main() -> None:
    ap = argparse.ArgumentParser()
    for k in ("--he-records", "--cfbd-root", "--team-cache", "--cfb", "--espn", "--out"):
        ap.add_argument(k, required=True)
    a = ap.parse_args()
    r = projections(Path(a.he_records), Path(a.team_cache))
    hb = fit_he_blend(r); r = add_he_blend(r, hb)
    per = pd.concat([period_actuals_cfbd(Path(a.cfbd_root), s) for s in FIT_SEASONS])
    spec = {
        "label": "RESEARCH_ONLY_FROZEN_FORWARD_SPECS",
        "frozen_at_utc": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fit_seasons": list(FIT_SEASONS), "last_2026_week_seen": LAST_SEEN_WEEK_2026,
        "selection_rule": {"edge_min": 0.05, "ask_open_interval": [0.02, 0.98], "one_bet_per": "game x family (largest net edge)", "entry": "last catalog snapshot 15 min - 24 h pre-kickoff",
                           "fee": "Kalshi taker ceil(0.07*C*P*(1-P)*100)/100 per order; C = 1, 10 and min(10, displayed size) reported"},
        "he_blend_coef_[1,he,cfbx]": hb,
        "distributions": fit_distributions(r, per),
        "market_recalibration_C": market_recal(a),
        "contract_rules": {
            "game_moneyline": "P(team margin > 0); full game has no ties (overtime), so P(home) + P(away) = 1",
            "period_moneyline": "P(team period margin >= 1) = 1 - Phi((0.5 - mu)/sigma); a tied period settles NO for both teams",
            "spread": "YES iff team margin > floor_strike", "total": "YES iff total > floor_strike", "team_total": "YES iff team points > floor_strike",
        },
    }
    body = json.dumps(spec, sort_keys=True)
    spec["sha256"] = hashlib.sha256(body.encode()).hexdigest()
    Path(a.out).write_text(json.dumps(spec, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"sha256": spec["sha256"], "market_recalibration_C": spec["market_recalibration_C"], "he_blend": hb}, indent=1))


if __name__ == "__main__":
    main()
