"""NBA Projection Foundation (frozen) vs archived Kalshi player-prop prices, 2025-26 regular season.

RESEARCH ONLY. Single entry point:
    venv/bin/python run.py            # stage 1 (model reproduction, ~25 min, cached in out/) + stages 2-4
Pre-registered protocol: protocol.json (sha256 in protocol.json.sha256). Writes report.json.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parent
OUT = WORK / "out"
PF = WORK / "repo" / "research" / "projection_foundation"
KAL = Path("/home/user/nba-edge-finder/data/history/kalshi")
SETTLE = WORK / "raw" / "settle" / "NBA"
BOX26 = WORK / "raw" / "hoopr" / "espn_nba_player_boxscores" / "player_box_2026.parquet"
sys.path.insert(0, str(PF))

SERIES = {"KXNBAPTS": ("points", "pts"), "KXNBAREB": ("rebounds", "reb"), "KXNBAAST": ("assists", "ast"),
          "KXNBA3PT": ("threes", "fg3m")}
HALF_CUT = pd.Timestamp("2026-02-01")
BUCKETS = [(0.05, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 0.95 + 1e-9)]
BUCKET_NAMES = ["[0.05,0.25)", "[0.25,0.5)", "[0.5,0.75)", "[0.75,0.95]"]
N_BOOT, SEED = 2000, 7


# ------------------------------------------------------------------------------------------------ helpers
def fee_u(p):
    p = np.asarray(p, float)
    return 0.07 * p * (1 - p)


def fee_r(p):
    p = np.asarray(p, float)
    return np.ceil(np.round(100 * 0.07 * p * (1 - p), 9)) / 100


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", " ", s.replace("-", " ").replace(".", "").replace("'", ""))
    toks = [t for t in s.split() if t not in ("jr", "sr", "ii", "iii", "iv")]
    return " ".join(toks)


def classify_quote(bid, ask) -> str:
    """nba.live.kalshi_report.classify_quote applied to a candle close (dollars)."""
    if bid is None and ask is None:
        return "NO_QUOTE"
    bid, ask = bid or 0.0, ask if ask is not None else 1.0
    if ask < bid or ask > 1.0 or bid < 0.0:
        return "INVALID"
    if bid <= 0.0 and (ask <= 0.0 or ask >= 1.0):
        return "NO_QUOTE"
    if bid <= 0.02 and ask >= 0.98:
        return "PLACEHOLDER"
    if bid <= 0.0 or ask >= 1.0:
        return "ONE_SIDED"
    return "TWO_SIDED"


def _f(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def bucket_of(p):
    for (a, b), n in zip(BUCKETS, BUCKET_NAMES):
        if a <= p < b:
            return n
    return "outside"


def jround(o, nd=5):
    if isinstance(o, dict):
        return {str(k): jround(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jround(v, nd) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), nd)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


# ------------------------------------------------------------------------------------------------ stage 1
def stage_model():
    need = [OUT / f"pmf_{f}.npz" for f, _ in SERIES.values()] + [OUT / "repro_check.json"]
    if not all(p.exists() for p in need):
        import model_repro
        model_repro.main()
    chk = json.loads((OUT / "repro_check.json").read_text())
    ok = True
    for fam, c in chk["families"].items():
        h = c["holdout"]
        ok &= c["best"]["recomputed"] == c["best"]["frozen"] and c["dist"]["recomputed"] == c["dist"]["frozen"]
        ok &= h["n"] == h["published"]["n"] and abs(h["crps"] - h["published"]["crps"]) <= 0.005
        ok &= abs(c["holdout_frozen_params"]["crps"] - h["published"]["crps"]) <= 0.005
    ok &= chk["best_minutes_model"]["recomputed"] == chk["best_minutes_model"]["frozen"]
    chk["faithful"] = bool(ok)
    if not ok:
        raise SystemExit("frozen model NOT reproduced faithfully; see out/repro_check.json. Stopping (protocol).")
    pm = {}
    for fam, _ in SERIES.values():
        z = np.load(OUT / f"pmf_{fam}.npz")
        zr = np.load(OUT / f"pmf_refit_{fam}.npz")
        assert (zr["game_id"] == z["game_id"]).all() and (zr["pid"] == z["pid"]).all()
        pm[fam] = {"P": z["P"].astype(float), "P_refit": zr["P"].astype(float), "lo": int(z["lo"]), "y": z["y"],
                   "idx": {(int(g), int(p)): i for i, (g, p) in enumerate(zip(z["game_id"], z["pid"]))}}
    return chk, pm


# ------------------------------------------------------------------------------------------------ stage 2
def load_box():
    from nba import data as D
    _, ab2tri = D.team_maps()
    d = pd.read_parquet(BOX26)
    d = d[d["season_type"] == 2].copy()
    d = d[d["team_abbreviation"].isin(ab2tri.keys()) & d["athlete_id"].notna()]
    d["team"] = d["team_abbreviation"].map(ab2tri)
    d["opp"] = d["opponent_team_abbreviation"].map(ab2tri)
    d["tip_utc"] = pd.to_datetime(d["game_date_time"]).dt.tz_convert("UTC")
    d["date_et"] = d["tip_utc"].dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    d["minutes"] = d["minutes"].where(~d["did_not_play"].fillna(False), 0).fillna(0).astype(float)
    d["played"] = d["minutes"] > 0
    d = d.rename(columns={"points": "pts", "rebounds": "reb", "assists": "ast",
                          "three_point_field_goals_made": "fg3m"})
    d["nname"] = d["athlete_display_name"].map(norm_name)
    d["game_id"] = d["game_id"].astype(np.int64)
    d["pid"] = d["athlete_id"].astype(np.int64)
    return d.drop_duplicates(["game_id", "pid"])


def load_settlements():
    out = {}
    for s in SERIES:
        for tier in ("live", "historical"):          # historical wins on conflict (read last)
            p = SETTLE / f"{s}.{tier}.jsonl"
            if p.exists():
                for line in open(p):
                    r = json.loads(line)
                    out[r["ticker"]] = {"result": r.get("result"), "status": r.get("status"), "tier": tier,
                                        "floor_strike": r.get("floor_strike")}
    return out


def load_candles(series):
    c = {}
    with gzip.open(KAL / f"candles_{series}.jsonl.gz", "rt") as f:
        for line in f:
            r = json.loads(line)
            c.setdefault(r["ticker"], []).append((int(r["end_period_ts"]), _f((r.get("yes_bid") or {}).get("close")),
                                                  _f((r.get("yes_ask") or {}).get("close"))))
    for k in c:
        c[k].sort()
    return c


EV_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})([A-Z]{3})([A-Z]{3})$")
MON = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def build_contracts(box, settle, pm):
    games = box.drop_duplicates(["game_id", "team"])[["game_id", "team", "opp", "home_away", "tip_utc", "date_et"]]
    home = games[games["home_away"] == "home"].rename(columns={"team": "home", "opp": "away"})
    gkey = {(r.date_et, r.away, r.home): (r.game_id, r.tip_utc) for r in home.itertuples()}
    gpair = {}
    for r in home.itertuples():
        gpair.setdefault(frozenset((r.away, r.home)), []).append((r.date_et, r.game_id, r.tip_utc, r.away))
    players = {g: df for g, df in box.groupby("game_id")}
    rows, funnel, unmatched = [], Counter(), Counter()
    for series, (fam, col) in SERIES.items():
        cand = load_candles(series)
        with gzip.open(KAL / f"markets_{series}.jsonl.gz", "rt") as f:
            for line in f:
                m = json.loads(line)
                funnel[(fam, "0_markets_in_metadata")] += 1
                tk = m["ticker"]
                if tk not in cand:
                    continue
                funnel[(fam, "1_has_candles")] += 1
                ev = m["event_ticker"].split("-")[1]
                mm = EV_RE.match(ev)
                if not mm:
                    funnel[(fam, "x_bad_event_ticker")] += 1
                    continue
                d = pd.Timestamp(2000 + int(mm[1]), MON[mm[2]], int(mm[3]))
                away, homet = mm[4], mm[5]
                g = gkey.get((d, away, homet))
                orient = "exact"
                if g is None:      # tolerate a +-1 day / orientation mismatch, unique candidate only
                    c = [x for x in gpair.get(frozenset((away, homet)), []) if abs((x[0] - d).days) <= 1]
                    if len(c) == 1:
                        g, orient = (c[0][1], c[0][2]), "fuzzy"
                if g is None:
                    funnel[(fam, "x_not_regular_season_game")] += 1
                    continue
                funnel[(fam, "2_regular_season_game")] += 1
                funnel[(fam, f"game_match_{orient}")] += 1
                gid, tip = g
                name = (m.get("yes_sub_title") or "").split(":")[0].strip()
                nn = norm_name(name)
                pl = players[gid]
                hit = pl[pl["nname"] == nn]
                if len(hit) != 1:
                    toks = nn.split()
                    if toks:
                        fi, ln = toks[0][0], toks[-1]
                        hit = pl[pl["nname"].map(lambda s: bool(s.split()) and s.split()[0][0] == fi and s.split()[-1] == ln)]
                if len(hit) != 1:
                    funnel[(fam, "x_player_unmatched")] += 1
                    so = settle.get(tk)
                    funnel[(fam, f"x_player_unmatched_official_{so['result'] if so else 'missing'}")] += 1
                    unmatched[name] += 1
                    continue
                funnel[(fam, "3_player_matched")] += 1
                h = hit.iloc[0]
                s = settle.get(tk)
                res = s["result"] if s else None
                strike = float(m["floor_strike"])
                k = int(math.ceil(strike))
                if abs(k - strike - 0.5) > 1e-9:
                    funnel[(fam, "x_nonhalf_strike")] += 1
                    continue
                stat = float(h[col]) if h["played"] else np.nan
                row = {"ticker": tk, "family": fam, "game_id": int(gid), "pid": int(h["pid"]), "name": name,
                       "espn_name": h["athlete_display_name"], "team": h["team"], "tip_utc": tip,
                       "date_et": h["date_et"], "strike": strike, "k": k, "result_official": res,
                       "result_metadata": m.get("result"), "settle_found": s is not None,
                       "played": bool(h["played"]), "stat": stat,
                       "exp_exp_minus_tip_h": (pd.Timestamp(m["expected_expiration_time"]) - tip).total_seconds() / 3600}
                # entry quote
                lo_ts, hi_ts = tip.timestamp() - 24 * 3600, tip.timestamp() - 3600
                cs = [c for c in cand[tk] if lo_ts <= c[0] <= hi_ts]
                if cs:
                    end, bid, ask = cs[-1]
                    row.update(entry_end=end, hours_before_tip=(tip.timestamp() - end) / 3600, bid=bid, ask=ask,
                               quote_class=classify_quote(bid, ask))
                else:
                    row.update(entry_end=None, hours_before_tip=np.nan, bid=np.nan, ask=np.nan, quote_class="NO_CANDLE_IN_WINDOW")
                # model probability (conditional frame)
                pmd = pm[fam]
                i = pmd["idx"].get((int(gid), int(h["pid"])))
                if i is not None:
                    P = pmd["P"][i]
                    j = k - pmd["lo"]
                    row["p_model"] = float(np.clip(1.0 - P[:j].sum(), 0.0, 1.0)) if j > 0 else 1.0
                    Pr = pmd["P_refit"][i]
                    row["p_model_refit"] = float(np.clip(1.0 - Pr[:j].sum(), 0.0, 1.0)) if j > 0 else 1.0
                    row["model_row"] = i
                else:
                    row["p_model"], row["model_row"] = np.nan, -1
                rows.append(row)
    return pd.DataFrame(rows), funnel, unmatched


# ------------------------------------------------------------------------------------------------ stage 3
def logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def diagnostics(Q):
    import statsmodels.api as sm
    y = Q["y"].to_numpy(float)
    out = {"n_contracts": int(len(Q)), "n_games": int(Q["game_id"].nunique()),
           "n_player_games": int(Q[["game_id", "pid"]].drop_duplicates().shape[0]), "base_rate": float(y.mean())}
    for nm, col in (("model", "p_model"), ("mid", "mid")):
        p = np.clip(Q[col].to_numpy(float), 1e-4, 1 - 1e-4)
        out[f"brier_{nm}"] = float(np.mean((p - y) ** 2))
        out[f"logloss_{nm}"] = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
        out[f"mean_p_{nm}"] = float(p.mean())
        try:
            r = sm.Logit(y, sm.add_constant(logit(p))).fit(disp=0, cov_type="cluster", cov_kwds={"groups": Q["game_id"].to_numpy()})
            out[f"calib_{nm}"] = {"intercept": float(r.params[0]), "slope": float(r.params[1]),
                                  "slope_se_cluster": float(r.bse[1])}
        except Exception as e:  # noqa: BLE001
            out[f"calib_{nm}"] = {"error": str(e)[:200]}
    out["brier_diff_model_minus_mid"] = out["brier_model"] - out["brier_mid"]
    # cluster bootstrap CI of the Brier difference (informational)
    d = (np.clip(Q["p_model"], 1e-4, 1 - 1e-4) - y) ** 2 - (Q["mid"].to_numpy() - y) ** 2
    out["brier_diff_ci95"] = boot_mean_ci(np.asarray(d), Q["game_id"].to_numpy())
    try:
        X = sm.add_constant(np.column_stack([logit(Q["p_model"]), logit(Q["mid"])]))
        r = sm.Logit(y, X).fit(disp=0, cov_type="cluster", cov_kwds={"groups": Q["game_id"].to_numpy()})
        out["joint_logit"] = {"terms": ["const", "logit_model", "logit_mid"], "coef": r.params.tolist(),
                              "se_cluster": r.bse.tolist(), "z": (r.params / r.bse).tolist(), "p": r.pvalues.tolist()}
    except Exception as e:  # noqa: BLE001
        out["joint_logit"] = {"error": str(e)[:200]}
    edges = np.linspace(0, 1, 11)
    b = np.clip(np.digitize(Q["p_model"].to_numpy(), edges) - 1, 0, 9)
    tab = []
    for i in range(10):
        mk = b == i
        if mk.sum():
            tab.append({"bin": f"{edges[i]:.1f}-{edges[i+1]:.1f}", "n": int(mk.sum()),
                        "mean_model": float(Q["p_model"].to_numpy()[mk].mean()),
                        "mean_mid": float(Q["mid"].to_numpy()[mk].mean()), "hit_rate": float(y[mk].mean())})
    out["reliability_by_model_bin"] = tab
    return out


def boot_mean_ci(x, g):
    gi, gu = pd.factorize(g)
    G = len(gu)
    s = np.bincount(gi, weights=x, minlength=G)
    n = np.bincount(gi, minlength=G).astype(float)
    rng = np.random.default_rng(SEED)
    W = np.stack([np.bincount(rng.integers(0, G, G), minlength=G) for _ in range(N_BOOT)])
    v = (W @ s) / (W @ n)
    return [float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))]


def boot_roi_ci(pnl, cost, g):
    if len(pnl) == 0:
        return [None, None]
    gi, gu = pd.factorize(g)
    G = len(gu)
    ps = np.bincount(gi, weights=pnl, minlength=G)
    cs = np.bincount(gi, weights=cost, minlength=G)
    rng = np.random.default_rng(SEED)
    W = np.stack([np.bincount(rng.integers(0, G, G), minlength=G) for _ in range(N_BOOT)])
    v = (W @ ps) / (W @ cs)
    return [float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))]


def candidates(Q):
    """One row per contract with its better side and net edge (unrounded fee)."""
    C = Q.copy()
    C["yes_price"], C["no_price"] = C["ask"], 1 - C["bid"]
    e_yes = C["p_model"] - C["yes_price"] - fee_u(C["yes_price"])
    e_no = (1 - C["p_model"]) - C["no_price"] - fee_u(C["no_price"])
    yes = e_yes >= e_no
    C["side"] = np.where(yes, "YES", "NO")
    C["price"] = np.where(yes, C["yes_price"], C["no_price"])
    C["p_side"] = np.where(yes, C["p_model"], 1 - C["p_model"])
    C["net_edge"] = np.where(yes, e_yes, e_no)
    C["win"] = np.where(yes, C["y"] == 1, C["y"] == 0).astype(int)
    C["fee_u"] = fee_u(C["price"])
    C["fee_r"] = fee_r(C["price"])
    C["bucket"] = C["price"].map(bucket_of)
    C["half"] = np.where(C["date_et"] < HALF_CUT, "H1_Oct-Jan", "H2_Feb-Apr")
    return C


def select(C, rule):
    X = C[C["net_edge"] >= 0.05]
    if rule == "R2":
        X = X[(X["price"] >= 0.25) & (X["price"] <= 0.75)]
    if rule == "R3":
        X = X[(X["p_model"] - X["mid"]).abs() <= 0.15]
    X = X.sort_values(["net_edge", "ticker"], ascending=[False, True])
    return X.drop_duplicates(["game_id", "pid", "family"], keep="first")


def summarize_bets(X):
    if len(X) == 0:
        return {"bets": 0}
    out = {"bets": int(len(X)), "wins": int(X["win"].sum()), "win_rate": float(X["win"].mean()),
           "avg_price": float(X["price"].mean()), "avg_model_p_side": float(X["p_side"].mean()),
           "avg_net_edge": float(X["net_edge"].mean()), "n_games": int(X["game_id"].nunique())}
    from scipy.stats import binomtest
    for tag, fc in (("unrounded", "fee_u"), ("rounded_C1", "fee_r")):
        cost = X["price"] + X[fc]
        pnl = X["win"] - cost
        be = float(X["price"].mean() + X[fc].mean())
        out[tag] = {"avg_fee": float(X[fc].mean()), "break_even": be, "net_pnl": float(pnl.sum()),
                    "roi": float(pnl.sum() / cost.sum()),
                    "roi_ci95": boot_roi_ci(pnl.to_numpy(), cost.to_numpy(), X["game_id"].to_numpy()),
                    "binom_p_one_sided": float(binomtest(int(X["win"].sum()), len(X), min(max(be, 1e-6), 1 - 1e-6),
                                                         alternative="greater").pvalue)}
    return out


def rule_report(X):
    r = {"all": summarize_bets(X)}
    for key in ("family", "side", "bucket", "half"):
        r[f"by_{key}"] = {k: summarize_bets(g) for k, g in X.groupby(key)}
    return r


def explore_confirm(X1):
    grid = []
    for fam in sorted(X1["family"].unique()):
        grid.append((f"family={fam}", X1["family"] == fam))
    for sd in ("YES", "NO"):
        grid.append((f"side={sd}", X1["side"] == sd))
    for b in BUCKET_NAMES:
        grid.append((f"bucket={b}", X1["bucket"] == b))
    for fam in sorted(X1["family"].unique()):
        for sd in ("YES", "NO"):
            grid.append((f"family={fam}&side={sd}", (X1["family"] == fam) & (X1["side"] == sd)))
    h1 = X1["half"] == "H1_Oct-Jan"
    res = []
    for name, mk in grid:
        a, b = summarize_bets(X1[mk & h1]), summarize_bets(X1[mk & ~h1])
        n1 = a.get("bets", 0)
        roi1 = a["unrounded"]["roi"] if n1 else None
        lo1 = a["unrounded"]["roi_ci95"][0] if n1 else None
        strict = bool(n1 >= 30 and roi1 > 0 and lo1 is not None and lo1 > 0)
        lenient = bool(n1 >= 30 and roi1 >= 0.05)
        e = {"subgroup": name, "first_half": a, "selected_strict": strict, "selected_lenient": lenient}
        if strict or lenient:      # scored once on the second half only when selected on the first half
            e["second_half"] = b
            n2 = b.get("bets", 0)
            e["survived_point"] = bool(n2 > 0 and b["unrounded"]["roi"] > 0)
            e["survived_ci"] = bool(n2 > 0 and b["unrounded"]["roi_ci95"][0] is not None and b["unrounded"]["roi_ci95"][0] > 0)
        res.append(e)
    return res


def prediction_quality(Q, pm):
    from pf_core import dists
    out = {}
    for fam, g in Q.groupby("family"):
        pg = g.drop_duplicates(["game_id", "pid"])
        P = pm[fam]["P"][pg["model_row"].to_numpy()]
        d = dists.DistBatch(pm[fam]["lo"], P)
        y = pg["stat"].to_numpy()
        out[fam] = {"player_games": int(len(pg)), "crps_model": float(np.mean(d.crps(y))),
                    "mae_model_mean": float(np.mean(np.abs(d.mean - y))), "bias_model_mean": float(np.mean(d.mean - y)),
                    "contracts": int(len(g)),
                    "rung_brier_model": float(np.mean((g["p_model"] - g["y"]) ** 2)),
                    "rung_brier_mid": float(np.mean((g["mid"] - g["y"]) ** 2))}
    return out


def main() -> int:
    proto_sha = hashlib.sha256((WORK / "protocol.json").read_bytes()).hexdigest()
    recorded = (WORK / "protocol.json.sha256").read_text().split()[0]
    chk, pm = stage_model()
    box = load_box()
    settle = load_settlements()
    T, funnel, unmatched = build_contracts(box, settle, pm)
    T.to_parquet(OUT / "contracts.parquet")
    rep = {"protocol_sha256": proto_sha, "protocol_sha256_recorded": recorded, "protocol_unchanged": proto_sha == recorded,
           "model_reproduction": chk}
    # ---- coverage funnel
    fam_f = {}
    for (fam, k), v in sorted(funnel.items()):
        fam_f.setdefault(fam, {})[k] = v
    T["res_known"] = T["result_official"].isin(["yes", "no"])
    cov = {}
    for fam, g in T.groupby("family"):
        c = fam_f.get(fam, {})
        c["4_official_yes_no"] = int(g["res_known"].sum())
        c["x_official_scalar_void"] = int((g["result_official"] == "scalar").sum())
        c["x_official_missing_or_other"] = int((~g["res_known"] & (g["result_official"] != "scalar")).sum())
        gk = g[g["res_known"]]
        c["x_yes_no_but_dnp_in_box"] = int((~gk["played"]).sum())
        c["x_played_but_no_model_row"] = int((gk["played"] & (gk["model_row"] < 0)).sum())
        gm = gk[gk["model_row"] >= 0]
        c["5_with_model_row"] = int(len(gm))
        c["quote_class_at_entry"] = gm["quote_class"].value_counts().to_dict()
        c["6_quoted_executable"] = int((gm["quote_class"] == "TWO_SIDED").sum())
        cov[fam] = c
    rep["coverage_funnel"] = cov
    rep["unmatched_player_names_top"] = dict(unmatched.most_common(40))
    # ---- settlement checks
    K = T[T["res_known"] & T["played"]]
    agree = (K["stat"] >= K["k"]).astype(int) == (K["result_official"] == "yes").astype(int)
    scal = T[T["result_official"] == "scalar"]
    rep["settlement_checks"] = {
        "official_vs_box_yes_no_played_n": int(len(K)), "official_vs_box_disagree": int((~agree).sum()),
        "disagree_examples": K[~agree][["ticker", "stat", "k", "result_official"]].head(20).astype(str).to_dict("records"),
        "official_yes_no_but_box_dnp": int((T["res_known"] & ~T["played"]).sum()),
        "official_scalar_n": int(len(scal)), "official_scalar_but_box_played": int(scal["played"].sum()),
        "official_missing": int((~T["settle_found"]).sum()),
        "official_vs_metadata_result_differs": int((T["settle_found"] & (T["result_official"] != T["result_metadata"])).sum()),
        "semantics": "YES iff stat >= ceil(floor_strike); agreement rate above verifies it"}
    rep["tip_sanity"] = {"expected_expiration_minus_espn_tip_hours_quantiles":
                         T["exp_exp_minus_tip_h"].quantile([0.01, 0.1, 0.5, 0.9, 0.99]).round(2).to_dict()}
    # ---- quoted set
    Q = T[T["res_known"] & (T["model_row"] >= 0) & (T["quote_class"] == "TWO_SIDED")].copy()
    Q["y"] = (Q["result_official"] == "yes").astype(int)
    Q["mid"] = (Q["bid"] + Q["ask"]) / 2
    Q["half"] = np.where(Q["date_et"] < HALF_CUT, "H1_Oct-Jan", "H2_Feb-Apr")
    rep["quoted_set"] = {"contracts": int(len(Q)), "player_games": int(Q[["game_id", "pid"]].drop_duplicates().shape[0]),
                         "player_game_families": int(Q[["game_id", "pid", "family"]].drop_duplicates().shape[0]),
                         "games": int(Q["game_id"].nunique()), "players": int(Q["pid"].nunique()),
                         "date_min": str(Q["date_et"].min().date()), "date_max": str(Q["date_et"].max().date()),
                         "by_family": Q["family"].value_counts().to_dict(), "by_half": Q["half"].value_counts().to_dict(),
                         "hours_before_tip_quantiles": Q["hours_before_tip"].quantile([0.1, 0.5, 0.9]).round(2).to_dict(),
                         "spread_quantiles": (Q["ask"] - Q["bid"]).quantile([0.1, 0.5, 0.9]).round(3).to_dict()}
    rep["diagnostics"] = {"all": diagnostics(Q)}
    for fam, g in Q.groupby("family"):
        rep["diagnostics"][fam] = diagnostics(g)
    for h, g in Q.groupby("half"):
        rep["diagnostics"][h] = diagnostics(g)
    rep["prediction_quality_quoted_player_games"] = prediction_quality(Q, pm)
    # ---- rules
    C = candidates(Q)
    C.to_parquet(OUT / "candidates.parquet")
    rep["rules"] = {}
    sel = {}
    for rule in ("R1", "R2", "R3"):
        sel[rule] = select(C, rule)
        rep["rules"][rule] = rule_report(sel[rule])
        sel[rule].to_parquet(OUT / f"bets_{rule}.parquet")
    rep["exploratory_confirmation"] = explore_confirm(sel["R1"])
    # sensitivity: pmfs with stack weights / distribution parameters refit on the recomputed development predictions
    Qr = Q.assign(p_model=Q["p_model_refit"])
    Cr = candidates(Qr)
    rep["sensitivity_refit_pmfs"] = {"diagnostics_all": {k: v for k, v in diagnostics(Qr).items() if k != "reliability_by_model_bin"},
                                     "rules_all": {r: summarize_bets(select(Cr, r)) for r in ("R1", "R2", "R3")}}
    rep["notes"] = [
        "protocol.json field written_utc says 05:20Z but the file was hashed (and made read-only) at 2026-11-20T05:14:32Z, "
        "before the model export finished and before any price/settlement join; the field was an approximate pre-filled time.",
        "No exploratory subgroup met either pre-declared first-half selection rule (n >= 30 plus ROI/CI condition), so nothing "
        "was scored as a confirmation; all subgroup numbers are EXPLORATORY.",
        "Price-bucket [0.75,0.95] cells have n <= 20 and almost all wins; their bootstrap CIs are degenerate and uninformative.",
        "Bootstrap CIs are percentile intervals over ESPN games (2,000 resamples, numpy default_rng(7) freshly seeded per interval)."]
    rep["amendments"] = [{
        "id": "A1", "stage": "model export, before any model probability was joined to a price or settlement",
        "change": "primary pmfs use frozen_params.json verbatim for F stack weights (rebounds, threes), the points empirical "
                  "distribution parameters, minutes residual quantiles and alpha, applied to the recomputed A-E ladder means. "
                  "The protocol's faithfulness check (recomputed fit) is kept and reported; the fully refit pmfs are reported as "
                  "sensitivity_refit_pmfs.",
        "reason": "the recomputed development fit gives slightly different stack weights (e.g. rebounds E weight 0.343 vs "
                  "frozen 0.333) because LightGBM predictions differ marginally across library versions (pinned version unknown; "
                  "4.7.0 used); using the frozen numbers is the closest reading of 'frozen champion configuration exactly'."}]
    (WORK / "report.json").write_text(json.dumps(jround(rep), indent=1, default=str))
    print(json.dumps(jround({"quoted": rep["quoted_set"], "diag_all": {k: v for k, v in rep["diagnostics"]["all"].items()
                                                                     if k != "reliability_by_model_bin"},
                             "R": {r: rep["rules"][r]["all"] for r in rep["rules"]}}, 4), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
