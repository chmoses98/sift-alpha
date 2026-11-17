"""CFB head-to-head: the preregistered CFB study model (cfb_game_lines_v1, prereg 9fd26b882bcc) and its Holm-passing variants vs the
archived PRODUCTION pf-cfb game forecasts on identical 2026 games (RESEARCH_ONLY). Mirrors `production_h2h` (CBB).

    python -m alpha_engine.discovery.cfb_production_h2h build --cfbd CFBD_CACHE --espn ESPN_2026_SUMMARIES --out DS.parquet --evidence EV.json
    python -m alpha_engine.discovery.cfb_production_h2h prod --root PROJECTION_DATA_CHECKOUT --repo CFB_REPO --ref origin/projection-data \
        --espn ESPN_2026_SUMMARIES --out PROD.parquet [--lead-hours 4]
    python -m alpha_engine.discovery.cfb_production_h2h h2h --prereg research/discovery/cfb_production_h2h/prereg.json --dataset DS.parquet \
        --production PROD.parquet [--production-4h PROD4.parquet] --out research/discovery/cfb_production_h2h/results.json

Data rules
  * build: the certified v2 builder (`features.cfb_cfbd_v2`) run over the CFBD cache 2014-2026 with ONE overlay: 2026 game results
    (final score, kickoff) from the archived ESPN postgame summaries, joined on the shared ESPN/CFBD game id. The 2026 CFBD cache holds no
    advanced box or drives, so every in-season column of a 2026 game is computed from 2025 games only (stale) and the 2026 priors are
    the published preseason values. Rows for 2014-2025 must hash to the certified dataset (checked, recorded in the evidence).
  * prod: the LAST pf-cfb forecast run whose generated_utc, archived_utc AND git commit time on the data branch are all before
    kickoff - lead. Kickoff is the ESPN summary's competition date. Team identity is checked by ESPN team id (home/away).
  * h2h: season-level walk-forward exactly as the discovery engine (season 2026 fitted on 2014-2025 only; sigma from the 2017-2025
    out-of-sample residuals). No market data enters any fit; closing lines are not archived for 2026.
"""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

ESPN_SEASON = 2026


# ----------------------------------------------------------------------------------------------------------------- ESPN 2026 results
def espn_results(espn_dir: Path) -> pd.DataFrame:
    rows = []
    for f in sorted(Path(espn_dir).glob("*.json")):
        d = json.loads(f.read_text())
        comp = d["header"]["competitions"][0]
        st = ((comp.get("status") or {}).get("type") or {}).get("name")
        cs = {c["homeAway"]: c for c in comp["competitors"]}
        if set(cs) != {"home", "away"}:
            continue
        sc = lambda c: pd.to_numeric(c.get("score"), errors="coerce")
        rows.append({"game_id": str(d["header"]["id"]), "kickoff_utc": pd.Timestamp(comp["date"]).tz_convert("UTC") if pd.Timestamp(comp["date"]).tzinfo else pd.Timestamp(comp["date"], tz="UTC"),
                     "final": st == "STATUS_FINAL", "home_id": str(cs["home"]["team"]["id"]), "away_id": str(cs["away"]["team"]["id"]),
                     "home_pts": sc(cs["home"]), "away_pts": sc(cs["away"]), "espn_neutral": bool(comp.get("neutralSite", False))})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------------------------------- dataset build
def _load_raw_through(cache: Path, last: int) -> dict:
    from ..features import cfb_cfbd as V1
    old = V1.LAST
    V1.LAST = last
    try:
        return V1.load_raw(cache)
    finally:
        V1.LAST = old


def overlay_results(raw: dict, res: pd.DataFrame) -> tuple[dict, dict]:
    """Mark 2026 CFBD schedule rows completed with the ESPN final score. Identity check: CFBD homeId/awayId == ESPN home/away id."""
    r = res[res.final & res.home_pts.notna() & res.away_pts.notna()].set_index("game_id")
    games, n_set, n_swap, n_missing, n_conflict = [], 0, 0, 0, 0
    for g in raw["games"]:
        if g.get("season") != ESPN_SEASON:
            games.append(g); continue
        gid = str(g["id"]); g = dict(g)
        if gid in r.index:
            e = r.loc[gid]
            if (str(g["homeId"]), str(g["awayId"])) != (e.home_id, e.away_id):
                n_swap += 1; games.append(g); continue           # identity disagreement: never guess, leave the game out
            if g.get("completed") and g.get("homePoints") is not None and (g["homePoints"], g["awayPoints"]) != (e.home_pts, e.away_pts):
                n_conflict += 1
            g.update(completed=True, homePoints=float(e.home_pts), awayPoints=float(e.away_pts),
                     startDate=e.kickoff_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")); n_set += 1
        else:
            n_missing += 1
        games.append(g)
    out = dict(raw); out["games"] = games
    return out, {"espn_final_games": int(len(r)), "cfbd_2026_schedule_rows": int(sum(1 for g in raw["games"] if g.get("season") == ESPN_SEASON)),
                 "results_overlaid": n_set, "identity_disagreements_left_out": n_swap, "cfbd_rows_without_espn_final": n_missing,
                 "cfbd_espn_score_conflicts": n_conflict}


def build(cache: Path, espn_dir: Path) -> tuple[pd.DataFrame, dict]:
    from ..features import cfb_cfbd as V1, cfb_cfbd_v2 as V2
    from ..foundation import training_sets_multi as TM
    from ..foundation.training_sets import canonical_hash
    raw = _load_raw_through(cache, ESPN_SEASON)
    raw, ev = overlay_results(raw, espn_results(espn_dir))
    old = V1.LAST
    V1.LAST = ESPN_SEASON                                       # priors() loops FIRST..LAST
    try:
        out = V2.compute(raw)
    finally:
        V1.LAST = old
    t, g = out["team"], out["games"]
    fc0 = V2.PRE + V2.PRIOR
    gg = g.assign(home_team=g.homeTeam, away_team=g.awayTeam, cutoff_utc=g.start_utc, neutral=g.neutralSite.fillna(False).astype(float),
                  conference_game=g.conferenceGame.fillna(False).astype(float), postseason=(g.seasonType != "regular").astype(float))
    gg["y_home_margin"] = (g.homePoints - g.awayPoints).astype(float); gg["y_total"] = (g.homePoints + g.awayPoints).astype(float)
    gg["y_home_win"] = (gg.y_home_margin > 0).astype(float)
    d = TM._home_away(t[["game_id", "team"] + fc0], gg[["game_id", "season", "date", "cutoff_utc", "home_team", "away_team", "neutral", "conference_game",
                                                         "postseason", "y_home_margin", "y_total", "y_home_win"]], fc0)
    d["split"] = [TM._split(int(s), "CFB") for s in d.season]
    d = d.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    old_rows = d[d.season <= 2025].reset_index(drop=True)
    ev["hash_2014_2025_rows"] = canonical_hash(old_rows.drop(columns=["cutoff_utc"]))
    ev["certified_v2_sha256"] = "0b9226c089fad0e4b83770bb288c236c83e5fc830e42e288976214b96ec6d7eb"
    ev["reproduces_certified_rows"] = ev["hash_2014_2025_rows"] == ev["certified_v2_sha256"]
    n26 = d[d.season == ESPN_SEASON]
    ev.update({"rows_total": int(len(d)), "rows_2026": int(len(n26)), "dates_2026": [str(n26.date.min()), str(n26.date.max())],
               "in_season_2026_source": "none archived: CFBD 2026 cache holds games/talent/recruiting/returning production/portal/coaches/rankings "
                                        "only (no advanced box, no drives); 2026 in-season columns are computed from 2025 games in the 400-day window",
               "frac_2026_rows_with_adj_epa": round(float(n26.home_adj_epa_net_pre.notna().mean()), 4) if len(n26) else None,
               "frac_2026_rows_with_talent_prior": round(float(n26.home_talent_prior.notna().mean()), 4) if len(n26) else None,
               "dataset_sha256_2014_2026": canonical_hash(d.drop(columns=["cutoff_utc"]))})
    return d, ev


# ----------------------------------------------------------------------------------------------------------------- production table
def file_commit_times(repo: Path, ref: str, prefix: str = "forecasts/cfb") -> dict:
    """First commit (author of record = data-branch push) that added each file: path -> commit time (UTC)."""
    txt = subprocess.run(["git", "-C", str(repo), "log", "--reverse", "--diff-filter=A", "--format=C %cI", "--name-only", ref, "--", prefix],
                         capture_output=True, text=True, check=True).stdout
    out, cur = {}, None
    for line in txt.splitlines():
        if line.startswith("C "):
            cur = pd.Timestamp(line[2:]).tz_convert("UTC")
        elif line.strip() and line.strip() not in out:
            out[line.strip()] = cur
    return out


def _p_home(probs, lo) -> float:
    p = np.asarray(probs, float); p = p / p.sum(); m = lo + np.arange(len(p))
    return float(p[m > 0].sum() + 0.5 * p[m == 0].sum())


def forecast_runs(root: Path, commit_times: dict | None) -> pd.DataFrame:
    rows = []
    for f in sorted(Path(root).glob("forecasts/cfb/*/*.jsonl.gz")):
        rel = str(f.relative_to(root))
        ct = commit_times.get(rel) if commit_times is not None else None
        for line in gzip.open(f):
            r = json.loads(line)
            if r.get("family") not in ("margin", "game_total", "team_points"):
                continue
            rows.append({"file": rel, "commit_utc": ct, "model_id": r["model_id"], "model_version": r.get("model_version"), "family": r["family"],
                         "game_id": str(r["game_id"]), "entity_id": str(r["entity_id"]), "generated_utc": pd.Timestamp(r["generated_utc"]),
                         "archived_utc": pd.Timestamp(r["archived_utc"]), "prod_start_utc": pd.Timestamp(r["game_start_utc"]), "mean": float(r["mean"]),
                         "p_home": _p_home(r["probs"], r["lo"]) if r["family"] == "margin" and r.get("probs") else np.nan, "gate": r.get("gate_status")})
    return pd.DataFrame(rows)


def production_table(runs: pd.DataFrame, res: pd.DataFrame, lead_hours: float = 0.0, model_id: str = "pf-cfb") -> tuple[pd.DataFrame, dict]:
    k = res.set_index("game_id")
    r = runs[(runs.model_id == model_id) & runs.game_id.isin(k.index)].copy()
    r["kickoff_utc"] = r.game_id.map(k.kickoff_utc)
    cut = r.kickoff_utc - pd.Timedelta(hours=lead_hours)
    arch = r[["archived_utc", "commit_utc"]].max(axis=1) if r.commit_utc.notna().all() else r.archived_utc
    r = r[(r.generated_utc < cut) & (r.archived_utc < cut) & (arch < cut)]
    out, ev = [], {"games_with_any_eligible_run": 0, "identity_mismatch": 0, "missing_family": 0, "start_time_disagreement_gt_1h": 0}
    for gid, x in r.groupby("game_id"):                      # per family: the latest eligible record (runs can be partial)
        ev["games_with_any_eligible_run"] += 1
        e = k.loc[gid]
        lat = lambda fam: x[x.family == fam].sort_values("generated_utc", kind="mergesort").drop_duplicates("entity_id", keep="last").set_index("entity_id")
        tp, mg, tt = lat("team_points"), lat("margin"), lat("game_total")
        if not {e.home_id, e.away_id} <= set(tp.index):
            ev["identity_mismatch"] += 1; continue
        if model_id == "pf-cfb" and (mg.empty or tt.empty):
            ev["missing_family"] += 1; continue
        tpm = float(tp.loc[e.home_id, "mean"] - tp.loc[e.away_id, "mean"])
        margin = float(mg["mean"].iloc[0]) if not mg.empty else tpm
        same_run = not mg.empty and tp.loc[[e.home_id, e.away_id], "generated_utc"].eq(mg.generated_utc.iloc[0]).all()
        if same_run and abs(margin - tpm) > 1.0:              # margin family must be home - away of the same joint run
            ev["identity_mismatch"] += 1; continue
        ev["margin_sign_checked_same_run"] = ev.get("margin_sign_checked_same_run", 0) + int(same_run)
        src = mg if not mg.empty else tp
        if abs((src.prod_start_utc.iloc[0] - e.kickoff_utc).total_seconds()) > 3600:
            ev["start_time_disagreement_gt_1h"] += 1
        gen = src.generated_utc.max()
        out.append({"game_id": gid, "margin": margin, "total": float(tt["mean"].iloc[0]) if not tt.empty else float(tp.loc[[e.home_id, e.away_id], "mean"].sum()),
                    "p_home": float(mg["p_home"].iloc[0]) if not mg.empty else np.nan, "home_pts_prod": float(tp.loc[e.home_id, "mean"]),
                    "away_pts_prod": float(tp.loc[e.away_id, "mean"]), "generated_utc": gen,
                    "total_generated_utc": tt.generated_utc.max() if not tt.empty else gen, "archived_utc": src.archived_utc.max(), "commit_utc": src.commit_utc.max(),
                    "start_utc": e.kickoff_utc, "lead_hours_actual": round((e.kickoff_utc - gen).total_seconds() / 3600, 2),
                    "model_version": src.model_version.iloc[0], "gate": ",".join(sorted(set(src.gate.dropna())))})
    t = pd.DataFrame(out)
    ev["games"] = int(len(t)); ev["lead_hours_rule"] = lead_hours
    if len(t):
        ev["lead_hours_actual_quantiles"] = [round(float(q), 2) for q in t.lead_hours_actual.quantile([0, .25, .5, .75, 1])]
    return t, ev


# ----------------------------------------------------------------------------------------------------------------- head-to-head
def boot_ci(v: np.ndarray, clusters: np.ndarray, n_boot: int = 4000, seed: int = 7) -> list[float]:
    g = pd.DataFrame({"v": v, "c": clusters}).groupby("c")["v"].agg(["sum", "count"])
    s, n = g["sum"].to_numpy(), g["count"].to_numpy()
    idx = np.random.default_rng(seed).integers(0, len(s), size=(n_boot, len(s)))
    est = s[idx].sum(1) / n[idx].sum(1)
    return [round(float(np.quantile(est, .025)), 4), round(float(np.quantile(est, .975)), 4)]


def boot_p(v: np.ndarray, clusters: np.ndarray, n_boot: int = 4000, seed: int = 7) -> float:
    """Two-sided cluster-bootstrap p for mean(v) = 0 (re-centred)."""
    g = pd.DataFrame({"v": v, "c": clusters}).groupby("c")["v"].agg(["sum", "count"])
    s, n = g["sum"].to_numpy(), g["count"].to_numpy(); m = s.sum() / n.sum()
    idx = np.random.default_rng(seed).integers(0, len(s), size=(n_boot, len(s)))
    est = s[idx].sum(1) / n[idx].sum(1) - m
    return float((np.sum(np.abs(est) >= abs(m)) + 1) / (n_boot + 1))


def _calib_slope(p, y):
    from ..input_research.stats import calibration_slope
    return round(calibration_slope(p, y)["slope"], 4)


def _pt(e: pd.Series) -> dict:
    return {"mae": round(float(e.abs().mean()), 3), "rmse": round(float(np.sqrt((e ** 2).mean())), 3), "bias_pred_minus_actual": round(float(e.mean()), 3)}


def _prob(p: np.ndarray, y: np.ndarray) -> dict:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return {"brier": round(float(((p - y) ** 2).mean()), 4), "log_loss": round(float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()), 4),
            "calibration_slope": _calib_slope(p, y), "accuracy": round(float(((p > .5) == (y > .5)).mean()), 4), "mean_p": round(float(p.mean()), 4)}


def compare(d: pd.DataFrame, chal: dict, clusters: dict) -> dict:
    """d: identical games with y_home_margin, y_total, neutral and production margin/total/p_home. chal: name -> (margin_mu, margin_sigma, total_mu) columns."""
    y_m, y_t = d.y_home_margin, d.y_total
    yb = (y_m > 0).astype(float).to_numpy()
    pa = np.clip(d.p_home.to_numpy(float), 1e-4, 1 - 1e-4)
    out = {"n_games": int(len(d)), "dates": [str(d.date.min())[:10], str(d.date.max())[:10]],
           "production": {"margin": _pt(d.margin - y_m), "total": _pt(d.total - y_t), "winner": _prob(pa, yb)}}
    from scipy.stats import norm
    nonneu = d.neutral.to_numpy(float) == 0
    out["home_field"] = {"n_non_neutral": int(nonneu.sum()), "n_neutral": int((~nonneu).sum()),
                         "actual_mean_home_margin_non_neutral": round(float(y_m[nonneu].mean()), 3),
                         "production": {"mean_pred_margin_non_neutral": round(float(d.margin[nonneu].mean()), 3),
                                        "bias_non_neutral": [round(float((d.margin - y_m)[nonneu].mean()), 3), boot_ci((d.margin - y_m)[nonneu].to_numpy(), np.arange(nonneu.sum()))],
                                        "bias_neutral": round(float((d.margin - y_m)[~nonneu].mean()), 3) if (~nonneu).any() else None}}
    for name, (mc, sc, tc) in chal.items():
        pb = np.clip(norm.cdf(d[mc] / d[sc]), 1e-4, 1 - 1e-4)
        r = {"margin": _pt(d[mc] - y_m), "total": _pt(d[tc] - y_t), "winner": _prob(pb, yb), "paired": {}}
        diffs = {"margin_abs_err": (d[mc] - y_m).abs() - (d.margin - y_m).abs(), "margin_sq_err": (d[mc] - y_m) ** 2 - (d.margin - y_m) ** 2,
                 "total_abs_err": (d[tc] - y_t).abs() - (d.total - y_t).abs(), "total_sq_err": (d[tc] - y_t) ** 2 - (d.total - y_t) ** 2,
                 "brier": (pb - yb) ** 2 - (pa - yb) ** 2,
                 "log_loss": -(yb * np.log(pb) + (1 - yb) * np.log(1 - pb)) + (yb * np.log(pa) + (1 - yb) * np.log(1 - pa))}
        for k, v in diffs.items():
            v = np.asarray(v, float)
            r["paired"][k + "_challenger_minus_production"] = {"mean": round(float(v.mean()), 4),
                                                               **{f"ci95_{cn}": boot_ci(v, cl) for cn, cl in clusters.items()},
                                                               **{f"p_{cn}": round(boot_p(v, cl), 4) for cn, cl in clusters.items()}}
        r["home_field"] = {"mean_pred_margin_non_neutral": round(float(d[mc][nonneu].mean()), 3),
                           "bias_non_neutral": [round(float((d[mc] - y_m)[nonneu].mean()), 3), boot_ci((d[mc] - y_m)[nonneu].to_numpy(), np.arange(nonneu.sum()))],
                           "bias_neutral": round(float((d[mc] - y_m)[~nonneu].mean()), 3) if (~nonneu).any() else None}
        out[name] = r
    return out


def challenger_predictions(prereg: dict, study: dict, d: pd.DataFrame) -> pd.DataFrame:
    """Season-level walk-forward (discovery engine): 2026 fitted on 2014-2025 only. Returns one row per 2026 game per model."""
    from . import engine as E
    d = d[d.season >= study["first_season"]].sort_values(["season", "date", "game_id"], kind="mergesort").reset_index(drop=True)
    for t in study["targets"].values():                       # 2026 outcomes are never visible to a fit
        d[t["column"] + "_fit"] = d[t["column"]].where(d.season < 2026)
    cols = set(d.columns); seasons = sorted(set(study["walk_forward_seasons"]) | {2026})
    out = d.loc[d.season == 2026, ["game_id"]].copy()
    for name, groups in prereg["challengers"].items():
        feats = E.group_columns(study, groups, cols)
        for tn, t in study["targets"].items():
            mu, sig = E.walk_forward(d, feats, t["column"] + "_fit", seasons, study["min_train"])
            out[f"{name}__{tn}_mu"] = mu[d.season == 2026]; out[f"{name}__{tn}_sigma"] = sig[d.season == 2026]
    return out


def h2h(prereg: dict, study: dict, d: pd.DataFrame, prods: dict) -> dict:
    pred = challenger_predictions(prereg, study, d)
    base = d[d.season == 2026][["game_id", "date", "neutral", "y_home_margin", "y_total"]].dropna(subset=["y_home_margin", "y_total"])
    chal = {n: (f"{n}__margin_mu", f"{n}__margin_sigma", f"{n}__total_mu") for n in prereg["challengers"]}
    res = {}
    for lab, prod in prods.items():
        prod = prod.assign(game_id=prod.game_id.astype(str))
        x = base.assign(game_id=base.game_id.astype(str)).merge(pred.assign(game_id=pred.game_id.astype(str)), on="game_id").merge(prod, on="game_id").dropna(subset=["margin", "total", "p_home"])
        x = x.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
        cl = {"game": np.arange(len(x)), "isoweek": pd.to_datetime(x.date).dt.strftime("%G-%V").to_numpy()}
        r = compare(x, chal, cl)
        # Holm on the preregistered primary family (primary challenger x three squared/Brier contrasts, game-clustered, two-sided)
        pc = prereg["primary"]["challenger"]
        fam = [(k, r[pc]["paired"][k + "_challenger_minus_production"]["p_game"]) for k in prereg["primary"]["contrasts"]]
        order = sorted(range(len(fam)), key=lambda i: fam[i][1]); m = len(fam); adj, run = {}, 0.0
        for rank, i in enumerate(order):
            run = max(run, min(1.0, (m - rank) * fam[i][1])); adj[fam[i][0]] = round(run, 4)
        r["primary_holm"] = {"challenger": pc, "p_holm": adj}
        r["blend_exploratory"] = {"margin_mae_half_production_half_primary": round(float(((x.margin + x[f"{pc}__margin_mu"]) / 2 - x.y_home_margin).abs().mean()), 3)}
        res[lab] = r
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--cfbd", required=True); b.add_argument("--espn", required=True); b.add_argument("--out", required=True); b.add_argument("--evidence", required=True)
    p = sub.add_parser("prod"); p.add_argument("--root", required=True); p.add_argument("--repo"); p.add_argument("--ref", default="origin/projection-data")
    p.add_argument("--espn", required=True); p.add_argument("--out", required=True); p.add_argument("--lead-hours", type=float, default=0.0); p.add_argument("--model-id", default="pf-cfb")
    p.add_argument("--evidence")
    h = sub.add_parser("h2h"); h.add_argument("--prereg", required=True); h.add_argument("--dataset", required=True); h.add_argument("--production", required=True)
    h.add_argument("--production-4h"); h.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        d, ev = build(Path(a.cfbd), Path(a.espn)); d.to_parquet(a.out, index=False); Path(a.evidence).write_text(json.dumps(ev, indent=1, default=str) + "\n")
        print(json.dumps(ev, indent=1, default=str))
    elif a.cmd == "prod":
        ct = file_commit_times(Path(a.repo), a.ref) if a.repo else None
        res = espn_results(Path(a.espn))
        t, ev = production_table(forecast_runs(Path(a.root), ct), res[res.final], a.lead_hours, a.model_id)
        ev["commit_times_checked"] = ct is not None
        t.to_parquet(a.out, index=False)
        if a.evidence:
            Path(a.evidence).write_text(json.dumps(ev, indent=1, default=str) + "\n")
        print(json.dumps(ev, indent=1, default=str))
    else:
        from . import engine as E
        pp = Path(a.prereg); prereg = json.loads(pp.read_text())
        study_p = Path(prereg["study_prereg_path"]); study = json.loads(study_p.read_text())
        if E.prereg_hash(study)[:12] != prereg["study_prereg_sha256"][:12]:
            raise SystemExit("study preregistration hash changed")
        d = pd.read_parquet(a.dataset)
        from ..foundation.training_sets import canonical_hash
        h = canonical_hash(d.drop(columns=["cutoff_utc"]))
        if h != prereg["dataset"]["dataset_sha256_2014_2026"]:
            raise SystemExit(f"dataset {h[:12]} is not the preregistered extended dataset")
        prods = {"kickoff": pd.read_parquet(a.production)}
        if a.production_4h:
            prods["kickoff_minus_4h"] = pd.read_parquet(a.production_4h)
        r = {"schema": "cfb-production-h2h-1.0", "status": "RESEARCH_ONLY", "prereg_sha256": E.prereg_hash(prereg), "dataset_sha256": h, **h2h(prereg, study, d, prods)}
        Path(a.out).write_text(json.dumps(r, indent=1, default=str) + "\n")
        print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk in ("n_games", "production", "primary_holm")}) for k, v in r.items()}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
