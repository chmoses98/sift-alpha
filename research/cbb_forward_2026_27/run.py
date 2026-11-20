"""SIFT CBB forward test (RESEARCH_ONLY): frozen candidate C2 vs incumbent pure-0.2.0 on 2026-27 games, outcome-only and price-aware
(Kalshi full-game winner + spread contracts). No orders, no pushes, no recommendations.

    PYTHONDONTWRITEBYTECODE=1 python run.py [--stage all|extract|build|score]

extract : parse kalshi-archive snapshots (GAME/SPREAD series only) into compact quote + metadata tables
build   : games, Kalshi mapping, entry/close quotes, incumbent projection rows, certified features, model P(YES). NO outcomes are read.
score   : refuses unless protocol.json matches protocol.sha256; joins official settlements + ESPN finals; evaluates; writes report.json

Reads (never writes) /home/user/cbb-edge-finder, /home/user/sift-alpha-ops, /home/user/sift-data-vault and the previous study at ../cbb_pred.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import math
import os
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parent
PRED = WORK.parent / "cbb_pred"
os.environ.setdefault("CBB_DATA_DIR", str(WORK / "cbbtmp"))       # incumbent code logs unresolved names here
sys.dont_write_bytecode = True
sys.path.insert(0, str(WORK / "sift"))                            # copied selection.py + canonical.py
sys.path.insert(0, str(WORK / "cbb_code"))                        # copy of cbb-edge-finder code (mapping, semantics, team registry)

KALSHI = WORK / "kalshi" / "snapshots" / "2026" / "11"
PROJ = WORK / "proj" / "projections" / "2027"
SCHED = WORK / "vault" / "espn_team_box_schedules" / "schedules" / "mbb_schedule_2027.parquet"
FEAT = WORK / "feat" / "cbb_derived_team.parquet"
SETTLE = WORK / "settle" / "CBB"
OUT = WORK / "out"
SERIES = {"KXNCAAMBGAME": "GAME_WINNER", "KXNCAAMBSPREAD": "SPREAD"}
WIN_LO, WIN_HI = "2026-11-03", "2026-11-15"
MX = ["mx_efg_pre", "mx_tov_pct_pre", "mx_orb_pct_pre", "mx_ftr100_pre", "exp_ft_pts_pre"]
PROT = json.loads((WORK / "protocol.json").read_text())
C2 = PROT["candidate"]["coef"]
SIG_C2 = PROT["candidate"]["sigma"]
RULES = PROT["evaluation"]["rules"]
META_KEYS = ("title", "yes_sub_title", "no_sub_title", "rules_primary", "floor_strike", "strike_type", "event_ticker", "custom_strike")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


# ------------------------------------------------------------------ extract
def _parse_snapshot(path: str):
    quotes, meta, res, cap = [], {}, {}, None
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if cap is None:
                cap = json.loads(line)["captured_at"]
            if "KXNCAAMBGAME" not in line and "KXNCAAMBSPREAD" not in line:
                continue
            r = json.loads(line)
            st = r.get("series_ticker")
            if st not in SERIES:
                continue
            m = r["market"]
            tk = m["ticker"]
            meta[tk] = {"series": st, **{k: m.get(k) for k in META_KEYS},
                        "event_title": (r.get("event") or {}).get("title"), "event_sub_title": (r.get("event") or {}).get("sub_title")}
            status = m.get("status")
            if m.get("result") in ("yes", "no"):
                res[tk] = {"status": status, "result": m["result"], "settlement_ts": m.get("settlement_ts")}
            if status == "active":
                quotes.append((r["captured_at"], tk, st, fnum(m.get("yes_bid_dollars")), fnum(m.get("yes_ask_dollars")),
                               fnum(m.get("yes_bid_size_fp")), fnum(m.get("yes_ask_size_fp"))))
    return path, cap, quotes, meta, res


def stage_extract() -> None:
    OUT.mkdir(exist_ok=True)
    files = sorted(glob.glob(str(KALSHI / "*" / "kalshi_cbb_*.jsonl.gz")))
    stamps, Q, META, RES = [], [], {}, {}
    with Pool(4) as pool:
        for path, cap, q, meta, res in pool.imap(_parse_snapshot, files, chunksize=4):   # chronological order preserved
            name = Path(path).name
            stamps.append({"file": name, "stamp": pd.Timestamp(cap), "file_stamp": pd.Timestamp(name.split("_")[-1].split(".")[0])})
            Q.extend(q)
            for tk, v in meta.items():
                META.setdefault(tk, v)          # first-seen metadata (identity fields are immutable)
            for tk, v in res.items():
                RES[tk] = {**v, "snapshot": name}   # latest snapshot wins
    q = pd.DataFrame(Q, columns=["captured_at", "ticker", "series", "yes_bid", "yes_ask", "size_yes_bid", "size_yes_ask"])
    q["captured_at"] = pd.to_datetime(q.captured_at, utc=True, format="ISO8601")
    q.to_parquet(OUT / "quotes.parquet", index=False)
    pd.DataFrame(stamps).to_parquet(OUT / "snapshots.parquet", index=False)
    (OUT / "meta.json").write_text(json.dumps(META))
    (OUT / "archive_results.json").write_text(json.dumps(RES))   # outcome info: only read in stage 'score'
    print(json.dumps({"snapshots": len(files), "quote_rows": len(q), "tickers": len(META)}))


# ------------------------------------------------------------------ build (no outcomes)
def schedule(cols_extra=()) -> pd.DataFrame:
    s = pd.read_parquet(SCHED, columns=["game_id", "date", "status_type_name", "home_id", "away_id", "neutral_site", "home_display_name", "away_display_name", *cols_extra])
    s["tip"] = pd.to_datetime(s["date"], utc=True, format="ISO8601")
    s["et_date"] = s.tip.dt.tz_convert("America/New_York").dt.date.astype(str)
    return s


def proj_index() -> pd.DataFrame:
    rows = []
    for p in sorted(PROJ.glob("*/G*/*.json")):
        d = json.loads(p.read_text())
        pr = d.get("projection") or {}
        rows.append({"path": str(p.relative_to(WORK)), "game_id": int(d["game"]["espn_game_id"]), "as_of": d["prospective"]["as_of"],
                     "rec_start": d["game"]["start_time_utc"], "rec_home": d["home"]["team_id"], "rec_away": d["away"]["team_id"],
                     "margin": pr.get("margin"), "margin_sd": pr.get("margin_sd"), "home_win_prob": pr.get("home_win_prob"),
                     "version": d["model"]["version"], "role": d["prospective"].get("role")})
    df = pd.DataFrame(rows)
    df["as_of"] = pd.to_datetime(df.as_of, utc=True, format="ISO8601")
    df["rec_start"] = pd.to_datetime(df.rec_start, utc=True, format="ISO8601")
    return df


def ncdf(x):
    x = np.asarray(x, float)
    return 0.5 * (1 + np.vectorize(math.erf)(x / math.sqrt(2)))


def p_yes(mu, sd, side, k):
    """P(YES): subject=home -> P(M > k); subject=away -> P(M < -k). M ~ N(mu, sd) is the home margin."""
    mu, sd, k = np.asarray(mu, float), np.asarray(sd, float), np.asarray(k, float)
    return np.where(np.asarray(side) == "home", ncdf((mu - k) / sd), ncdf((-k - mu) / sd))


def stage_build() -> dict:
    from cbb_edge.data.ids import teams
    from cbb_edge.kalshi.mapping import map_market
    from cbb_edge.kalshi.semantics import parse_contract
    s = schedule()
    s["home_tid"] = [teams.canonical_from_espn(x) for x in s.home_id]
    s["away_tid"] = [teams.canonical_from_espn(x) for x in s.away_id]
    gm = s.assign(game_date_et=pd.to_datetime(s.et_date).dt.date, home_team_id=s.home_tid, away_team_id=s.away_tid)[["game_id", "game_date_et", "home_team_id", "away_team_id"]]
    gm = gm[gm.home_team_id.notna() & gm.away_team_id.notna()]
    meta = json.loads((OUT / "meta.json").read_text())
    by_id = s.set_index("game_id")
    cache, cm = {}, []
    for tk, m in meta.items():
        ev = m["event_ticker"]
        if ev not in cache:
            cache[ev] = map_market({**m, "ticker": tk}, gm, {"title": m.get("event_title"), "sub_title": m.get("event_sub_title")})
        gid, why = cache[ev]
        row = {"ticker": tk, "series": m["series"], "family": SERIES[m["series"]], "event_ticker": ev, "game_id": gid, "map_reason": why}
        if gid is not None:
            g = by_id.loc[gid]
            sem = parse_contract(m["series"], m, g.home_tid, g.away_tid)
            row.update(parse_status=sem["status"], subject_side=sem["subject_side"], strike=sem["strike"], yes_condition=sem["yes_condition"],
                       sem=json.dumps(sem))
        cm.append(row)
    cm = pd.DataFrame(cm)
    # --- games in window
    g = s[(s.et_date >= WIN_LO) & (s.et_date <= WIN_HI)].copy()
    cov = {"espn_games_in_window": int(len(g)), "status_final": int((g.status_type_name == "STATUS_FINAL").sum()),
           "status_counts": g.status_type_name.value_counts().to_dict()}
    g = g[g.status_type_name == "STATUS_FINAL"].copy()
    snaps = pd.read_parquet(OUT / "snapshots.parquet").sort_values("stamp")
    st = snaps.stamp.to_numpy()
    i = np.searchsorted(st, (g.tip - pd.Timedelta(minutes=30)).to_numpy(), side="right") - 1
    g["entry_ts"] = [snaps.stamp.iloc[j] if j >= 0 else pd.NaT for j in i]
    # --- incumbent row
    pj = proj_index()
    cov["projection_records"] = int(len(pj))
    cov["projection_versions"] = pj.version.value_counts().to_dict()
    gm_has_contracts = set(cm.loc[cm.game_id.notna() & (cm.parse_status == "parsed"), "game_id"].astype(int))
    g["has_kalshi"] = g.game_id.isin(gm_has_contracts)
    g["cutoff"] = np.where(g.has_kalshi & g.entry_ts.notna(), g.entry_ts, g.tip - pd.Timedelta(minutes=30))
    g["cutoff"] = pd.to_datetime(g.cutoff, utc=True)
    pj = pj.merge(g[["game_id", "cutoff", "tip", "home_tid", "away_tid"]], on="game_id", how="inner")
    pj = pj[pj.as_of <= pj.cutoff].sort_values(["game_id", "as_of"]).drop_duplicates("game_id", keep="last")
    pj["orient"] = np.select([(pj.rec_home == pj.home_tid) & (pj.rec_away == pj.away_tid), (pj.rec_home == pj.away_tid) & (pj.rec_away == pj.home_tid)], ["same", "swapped"], "mismatch")
    cov["incumbent_row"] = {"games_with_row": int(len(pj)), "orientation": pj.orient.value_counts().to_dict(),
                            "rec_start_eq_espn_tip": float((pj.rec_start == pj.tip).mean()),
                            "hours_tip_minus_as_of": pj.assign(h=(pj.tip - pj.as_of).dt.total_seconds() / 3600).h.describe().round(2).to_dict()}
    pj = pj[pj.orient != "mismatch"].copy()
    pj["inc_margin"] = np.where(pj.orient == "swapped", -pj.margin, pj.margin)
    pj["inc_hwp_published"] = np.where(pj.orient == "swapped", 1 - pj.home_win_prob, pj.home_win_prob)
    g = g.merge(pj[["game_id", "path", "as_of", "inc_margin", "margin_sd", "inc_hwp_published", "orient"]], on="game_id", how="inner")
    # --- certified features
    f = pd.read_parquet(FEAT, columns=["game_id", "team", "home", "neutral", "exp_pts_pre"] + MX)
    f = f.astype({"game_id": "int64", "team": "int64"})
    fh = f.add_suffix("_h").rename(columns={"game_id_h": "game_id", "team_h": "home_id"})
    fa = f.add_suffix("_a").rename(columns={"game_id_a": "game_id", "team_a": "away_id"})
    g = g.astype({"home_id": "int64", "away_id": "int64", "game_id": "int64"}).merge(fh, on=["game_id", "home_id"], how="left").merge(fa, on=["game_id", "away_id"], how="left")
    g["d_exp_pts"] = g.exp_pts_pre_h - g.exp_pts_pre_a
    for c in MX:
        g[f"d_{c}"] = g[f"{c}_h"] - g[f"{c}_a"]
    cols = [c for c in C2 if c != "intercept"]
    ok = g[cols].notna().all(axis=1) & np.isfinite(g[cols].to_numpy(float)).all(axis=1)
    cov["certified"] = {"games_before_feature_join": int(len(g)), "complete_c2_inputs": int(ok.sum()),
                        "home_flag_on_home_row": float(g.loc[ok, "home_h"].mean()), "home_flag_on_away_row": float(g.loc[ok, "home_a"].mean())}
    g = g[ok].reset_index(drop=True)
    g["c2_margin"] = C2["intercept"] + sum(C2[c] * g[c] for c in cols)
    g["c2_sd"] = SIG_C2
    cov["universe_games"] = int(len(g))
    cov["universe_dates"] = sorted(g.et_date.unique().tolist())
    g.drop(columns=[c for c in g.columns if c in ("home_score", "away_score")], errors="ignore").to_parquet(OUT / "games.parquet", index=False)
    # --- contracts
    q = pd.read_parquet(OUT / "quotes.parquet")
    two = (q.yes_bid > 0) & (q.yes_ask < 1) & (q.yes_ask > q.yes_bid)
    q = q[two]
    c = cm[cm.game_id.notna() & (cm.parse_status == "parsed")].astype({"game_id": "int64"})
    c = c.merge(g[["game_id", "tip", "entry_ts", "et_date", "inc_margin", "margin_sd", "c2_margin", "c2_sd"]], on="game_id", how="inner")
    e = c.merge(q, left_on=["ticker", "entry_ts", "series"], right_on=["ticker", "captured_at", "series"], how="inner")
    assert (e.captured_at < e.tip).all() and (e.captured_at <= e.tip - pd.Timedelta(minutes=30)).all()
    later = c[["ticker", "entry_ts", "tip"]].merge(q[["ticker", "captured_at", "yes_bid", "yes_ask"]], on="ticker")
    later = later[(later.captured_at > later.entry_ts) & (later.captured_at < later.tip)].sort_values("captured_at").drop_duplicates("ticker", keep="last")
    e = e.merge(later[["ticker", "captured_at", "yes_bid", "yes_ask"]].rename(columns={"captured_at": "close_ts", "yes_bid": "close_yes_bid", "yes_ask": "close_yes_ask"}), on="ticker", how="left")
    k = np.where(e.family == "GAME_WINNER", 0.0, e.strike.astype(float))
    e["p_inc"] = p_yes(e.inc_margin, e.margin_sd, e.subject_side, k)
    e["p_c2"] = p_yes(e.c2_margin, e.c2_sd, e.subject_side, k)
    e = e.rename(columns={"ticker": "contract_id", "et_date": "date"})
    e.to_parquet(OUT / "contracts.parquet", index=False)
    lag = (e.drop_duplicates("game_id").pipe(lambda d: (d.tip - d.entry_ts).dt.total_seconds() / 60))
    cov["kalshi"] = {
        "tickers_in_archive": int(len(cm)), "events": int(cm.event_ticker.nunique()),
        "map_reason_by_event": cm.drop_duplicates("event_ticker").map_reason.value_counts().to_dict(),
        "parse_status": cm.parse_status.value_counts(dropna=False).to_dict(),
        "universe_games_with_parsed_contracts": int(g.game_id.isin(c.game_id).sum()),
        "games_with_entry_quotes": int(e.game_id.nunique()), "contracts_at_entry": int(len(e)),
        "contracts_by_family": e.family.value_counts().to_dict(),
        "games_by_family": e.groupby("family").game_id.nunique().to_dict(),
        "contracts_with_close_quote": int(e.close_yes_bid.notna().sum()),
        "minutes_tip_minus_entry": lag.describe().round(1).to_dict(),
        "entry_dates": sorted(e.date.unique().tolist()),
    }
    (OUT / "build_coverage.json").write_text(json.dumps(cov, indent=1, default=str))
    print(json.dumps(cov, indent=1, default=str))
    return cov


# ------------------------------------------------------------------ score (outcomes joined here only)
def official_results() -> pd.DataFrame:
    rows = []
    for f in sorted(SETTLE.glob("KXNCAAMB*.jsonl")):
        if f.name.split(".")[0] not in SERIES:
            continue
        for line in f.read_text().splitlines():
            r = json.loads(line)
            rows.append({"contract_id": r["ticker"], "vault_result": r.get("result"), "vault_status": r.get("status"), "vault_file": f.name})
    v = pd.DataFrame(rows).drop_duplicates("contract_id", keep="last")
    a = json.loads((OUT / "archive_results.json").read_text())
    arc = pd.DataFrame([{"contract_id": k, "archive_result": x["result"], "archive_status": x["status"], "archive_snapshot": x["snapshot"]} for k, x in a.items()])
    return v.merge(arc, on="contract_id", how="outer")


def boot_mean_ci(d: np.ndarray, keys: np.ndarray, n: int = 2000, seed: int = 7) -> list:
    uk, inv = np.unique(keys, return_inverse=True)
    s, cnt = np.bincount(inv, weights=d), np.bincount(inv).astype(float)
    idx = np.random.default_rng(seed).integers(0, len(uk), (n, len(uk)))
    m = s[idx].sum(1) / cnt[idx].sum(1)
    return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]


def pt(y, p) -> dict:
    e = y - p
    return {"rmse": round(float(np.sqrt(np.mean(e ** 2))), 4), "mae": round(float(np.mean(np.abs(e))), 4), "bias_actual_minus_pred": round(float(np.mean(e)), 4)}


def cover(y, mu, sd) -> dict:
    z = np.abs(y - mu) / sd
    return {"cov50": round(float(np.mean(z <= 0.6744897501960817)), 4), "cov80": round(float(np.mean(z <= 1.2815515655446004)), 4), "mean_sd": round(float(np.mean(sd)), 3)}


def stage_score() -> None:
    if sha(WORK / "protocol.json") != (WORK / "protocol.sha256").read_text().split()[0]:
        raise SystemExit("STOP: protocol.json hash mismatch")
    from alpha_engine.pipeline import selection as S
    from cbb_edge.kalshi.semantics import settle
    cov = json.loads((OUT / "build_coverage.json").read_text())
    g = pd.read_parquet(OUT / "games.parquet")
    sc = schedule(("home_score", "away_score"))[["game_id", "home_score", "away_score"]].astype({"game_id": "int64"})
    g = g.merge(sc, on="game_id", how="left")
    g["y_margin"] = (g.home_score - g.away_score).astype(float)
    rep: dict = {"status": "COMPLETE", "label": "RESEARCH_ONLY forward test; hypothetical taker entries; no orders", "protocol_sha256": sha(WORK / "protocol.json"),
                 "inputs": {"kalshi_archive_commit": "ecb674dbeab37e1afc7e3772a51000ca99bee5de", "projections_archive_commit": "1929f14396736a405c0ea673d1a964ec3132b960",
                            "feat_sha256": sha(FEAT), "schedule_2027_sha256": sha(SCHED),
                            "feat_equal_to_cbb_pred_season2027_rows": True},
                 "coverage": cov}
    # ---------------- outcome-only
    y = g.y_margin.to_numpy(float)
    pi, pc = g.inc_margin.to_numpy(float), g.c2_margin.to_numpy(float)
    d = (y - pc) ** 2 - (y - pi) ** 2
    gk, dk = g.game_id.to_numpy(), g.et_date.to_numpy()
    rep["outcome"] = {
        "n_games": int(len(g)), "n_dates": int(g.et_date.nunique()), "dates": [g.et_date.min(), g.et_date.max()],
        "incumbent": pt(y, pi), "c2": pt(y, pc),
        "rmse_delta_c2_minus_inc": round(float(np.sqrt(np.mean((y - pc) ** 2)) - np.sqrt(np.mean((y - pi) ** 2))), 4),
        "paired_delta_sq_err_mean": round(float(d.mean()), 4), "paired_delta_sq_err_95ci_game_bootstrap": boot_mean_ci(d, gk),
        "paired_delta_sq_err_95ci_date_cluster": boot_mean_ci(d, dk),
        "c2_better_share_games": round(float(np.mean(d < 0)), 4),
        "winner_accuracy": {"incumbent": round(float(np.mean(np.sign(pi) == np.sign(y))), 4), "c2": round(float(np.mean(np.sign(pc) == np.sign(y))), 4)},
        "calibration": {"incumbent": cover(y, pi, g.margin_sd.to_numpy(float)), "c2": cover(y, pc, np.full(len(g), SIG_C2)),
                        "realised_sd_of_c2_residual": round(float(np.std(y - pc, ddof=1)), 3), "realised_sd_of_inc_residual": round(float(np.std(y - pi, ddof=1)), 3)},
        "corr_c2_minus_inc_vs_inc": round(float(np.corrcoef(pc - pi, pi)[0, 1]), 4), "mean_abs_c2_minus_inc": round(float(np.mean(np.abs(pc - pi))), 3),
        "label": "paired Δ = mean over games of (C2 sq err − incumbent sq err); negative = C2 better",
    }
    # ---------------- contracts + settlement
    c = pd.read_parquet(OUT / "contracts.parquet")
    res = official_results()
    c = c.merge(res, on="contract_id", how="left")
    c["result"] = np.where(c.vault_result.isin(["yes", "no"]), c.vault_result, np.where(c.archive_result.isin(["yes", "no"]), c.archive_result, None))
    c["result_source"] = np.where(c.vault_result.isin(["yes", "no"]), "vault_official_settlements_20261116",
                                  np.where(c.archive_result.isin(["yes", "no"]), "kalshi_archive_market_result", "none"))
    both = c.vault_result.isin(["yes", "no"]) & c.archive_result.isin(["yes", "no"])
    c = c.merge(g[["game_id", "home_score", "away_score"]], on="game_id", how="left")
    c["espn_expected"] = [settle(json.loads(s), int(h), int(a))[0] for s, h, a in zip(c["sem"], c.home_score, c.away_score)]
    settled = c.result.notna()
    agree = settled & (c.espn_expected == c.result)
    dis = settled & (c.espn_expected != c.result)
    rep["settlement"] = {"contracts": int(len(c)), "with_official_result": int(settled.sum()), "by_source": c.result_source.value_counts().to_dict(),
                         "vault_vs_archive_both_present": int(both.sum()), "vault_vs_archive_agree": int((both & (c.vault_result == c.archive_result)).sum()),
                         "semantics_check_espn_final_vs_kalshi": {"checked": int(settled.sum()), "agree": int(agree.sum()), "disagree": int(dis.sum()),
                                                                   "by_family": c[settled].assign(ok=agree[settled]).groupby("family").ok.agg(["sum", "count"]).to_dict("index"),
                                                                   "disagreements": c.loc[dis, ["contract_id", "result", "espn_expected", "home_score", "away_score", "yes_condition"]].head(20).to_dict("records")}}
    c = c[settled & ~dis].copy()
    c["y"] = (c.result == "yes").astype(int)
    base = c[["game_id", "contract_id", "family", "yes_bid", "yes_ask", "y", "close_yes_bid", "close_yes_ask", "size_yes_ask", "size_yes_bid", "date"]]
    rep["price_aware"] = {"n_contracts": int(len(c)), "n_games": int(c.game_id.nunique()), "dates": [c.date.min(), c.date.max()],
                          "contracts_by_family": c.family.value_counts().to_dict(), "entry_mid_quantiles": c.eval("(yes_bid+yes_ask)/2").quantile([.1, .25, .5, .75, .9]).round(3).to_dict(),
                          "entry_spread_mean": round(float((c.yes_ask - c.yes_bid).mean()), 4)}
    sel = {}
    for name, col in (("c2", "p_c2"), ("incumbent", "p_inc")):
        cc = base.assign(model_p=c[col].to_numpy())
        ev = S.evaluate(cc, RULES, boot=2000, seed=7)
        ev["diagnostics_by_family"] = {k: S.diagnostics(v) for k, v in cc.groupby("family")}
        rep["price_aware"][name] = ev
        sel[name] = {r["name"]: S.select(cc, r) for r in RULES}
    rep["price_aware"]["overlap"] = {r["name"]: {"c2_bets": len(sel["c2"][r["name"]]), "inc_bets": len(sel["incumbent"][r["name"]]),
                                                 "same_contract_and_side": int(sel["c2"][r["name"]][["contract_id", "side"]].merge(sel["incumbent"][r["name"]][["contract_id", "side"]]).shape[0])}
                                     for r in RULES}
    post = {"label": "POST HOC (not in protocol): ROI(C2 bets) - ROI(incumbent bets), games resampled jointly (union of games with a bet), 2000 resamples, seed 7"}
    for r in RULES:
        a, b = sel["c2"][r["name"]], sel["incumbent"][r["name"]]
        ug = np.union1d(a.game_id.unique(), b.game_id.unique())
        def agg(x):
            t = x.assign(net=x.won.astype(float) - x.entry - x.fee, cost=x.entry + x.fee).groupby("game_id")[["net", "cost"]].sum().reindex(ug, fill_value=0.0)
            return t.net.to_numpy(), t.cost.to_numpy()
        na, ca = agg(a); nb, cb = agg(b)
        idx = np.random.default_rng(7).integers(0, len(ug), (2000, len(ug)))
        dd = na[idx].sum(1) / ca[idx].sum(1) - nb[idx].sum(1) / cb[idx].sum(1)
        post[r["name"]] = {"roi_diff": round(float(na.sum() / ca.sum() - nb.sum() / cb.sum()), 4), "95ci": [round(float(np.quantile(dd, .025)), 4), round(float(np.quantile(dd, .975)), 4)], "games": int(len(ug))}
    rep["price_aware"]["post_hoc_paired_roi_diff"] = post
    rep["price_aware"]["model_vs_mid_gap"] = {n: round(float((c[col] - c.eval("(yes_bid+yes_ask)/2")).abs().mean()), 4) for n, col in (("c2", "p_c2"), ("incumbent", "p_inc"))}
    pd.concat([v.assign(model=m, rule=r) for m in sel for r, v in sel[m].items()]).to_parquet(OUT / "selections.parquet", index=False)
    (WORK / "report.json").write_text(json.dumps(rep, indent=1, default=str))
    short = {"outcome": {k: rep["outcome"][k] for k in ("n_games", "incumbent", "c2", "paired_delta_sq_err_mean", "paired_delta_sq_err_95ci_game_bootstrap", "winner_accuracy", "calibration")},
             "settlement": {k: v for k, v in rep["settlement"].items() if k != "semantics_check_espn_final_vs_kalshi"} | {"sem": {k: rep["settlement"]["semantics_check_espn_final_vs_kalshi"][k] for k in ("checked", "agree", "disagree")}},
             "price": {m: {"diag": rep["price_aware"][m]["diagnostics"], **{r: {k: rep["price_aware"][m]["rules"][r]["all"].get(k) for k in ("bets", "games", "win_rate", "breakeven_win_prob", "net_roi", "net_roi_95ci_game_bootstrap", "size_capped_10", "clv")} for r in ("R1", "R2", "R3")}} for m in ("c2", "incumbent")},
             "overlap": rep["price_aware"]["overlap"]}
    print(json.dumps(short, indent=1, default=str))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["all", "extract", "build", "score"])
    a = ap.parse_args()
    if a.stage in ("all", "extract"):
        stage_extract()
    if a.stage in ("all", "build"):
        stage_build()
    if a.stage in ("all", "score"):
        stage_score()


if __name__ == "__main__":
    main()
