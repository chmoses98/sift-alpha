"""Price-aware selection evaluation shared by every sport (RESEARCH_ONLY; no orders, no recommendations published).

One contract table in, frozen rules applied, every number needed to judge a SELECTIVE strategy out. The question this module answers is not
"is the model better than the market on every contract" but "does a frozen, pre-declared subset of the model's selections win more often than its
fee-adjusted break-even at the prices actually available". Market-wide Brier / log loss are reported as DIAGNOSTICS beside it, never as the gate.

Contract table columns (one row per contract quote; prices on the YES axis, dollars):
  game_id, contract_id, family, yes_bid, yes_ask, model_p (P(YES)), y (1 if YES settled, 0 if NO; official settlement), optional: close_yes_bid,
  close_yes_ask (a two-sided pre-start close for CLV), size_yes_ask / size_yes_bid (displayed depth), group (any label for splits), date.
Rules (frozen dict; hash it with freeze()):
  {"name", "min_net_edge": 0.05, "price_lo": 0.0, "price_hi": 1.0, "max_abs_disagreement": None, "one_per": ["game_id", "family"], "families": None, "sides": ["YES","NO"]}
Costs: fee per contract is the Kalshi taker schedule 0.07*P*(1-P) (unrounded) for selection; P&L is reported unrounded AND with the per-order fee
rounded up to the cent (sift_clv.canonical.estimate_fee) at 1-contract orders and at min(qty, displayed size) orders.
CLV (sift_clv canonical definitions, side axis, never merged): selection_clv = close_mid - entry_mid (pure market movement: no fee, no spread);
quoted_execution_clv = close_mid - entry_ask (includes the half-spread paid). The entry fee is reported separately and is NOT a CLV loss: the ~1.7c
immediate mark-to-market drop after a taker fill at mid-range prices is mechanical (fee + half-spread), not predictive deterioration.
"""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal

import numpy as np
import pandas as pd

FEE_RATE = 0.07
VERSION = "sift-selection/1"


def fee_unrounded(p):
    p = np.asarray(p, float); return FEE_RATE * p * (1 - p)


def fee_order(p: float, n: int) -> float:
    """Per-order taker fee rounded up to the cent (same formula as sift_clv.canonical.estimate_fee)."""
    from sift_clv.canonical import estimate_fee
    return float(estimate_fee(Decimal(str(round(float(p), 6))), int(n)))


def freeze(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_frozen(spec: dict, sha: str) -> None:
    if freeze(spec) != sha:
        raise ValueError("frozen spec changed: a changed candidate is a NEW candidate and needs its own freeze before scoring")


def sides(c: pd.DataFrame) -> pd.DataFrame:
    """Two candidate positions per contract (YES at yes_ask, NO at 1 - yes_bid), each on its own axis."""
    base = c.reset_index(drop=True)
    yes = base.assign(side="YES", entry=base.yes_ask, entry_mid=(base.yes_bid + base.yes_ask) / 2, prob=base.model_p, won=base.y == 1,
                      depth=base.get("size_yes_ask", pd.Series(np.nan, index=base.index)))
    no = base.assign(side="NO", entry=1 - base.yes_bid, entry_mid=1 - (base.yes_bid + base.yes_ask) / 2, prob=1 - base.model_p, won=base.y == 0,
                     depth=base.get("size_yes_bid", pd.Series(np.nan, index=base.index)))
    out = pd.concat([yes, no], ignore_index=True)
    if "close_yes_bid" in out:
        cm = (out.close_yes_bid + out.close_yes_ask) / 2; out["close_mid"] = np.where(out.side == "YES", cm, 1 - cm)
    out["fee"] = fee_unrounded(out.entry); out["net_edge"] = out.prob - out.entry - out.fee
    return out


def select(c: pd.DataFrame, rule: dict) -> pd.DataFrame:
    s = sides(c); ok = (s.entry > 0) & (s.entry < 1) & s.prob.notna() & (s.net_edge >= rule.get("min_net_edge", 0.05))
    ok &= (s.entry >= rule.get("price_lo", 0.0)) & (s.entry <= rule.get("price_hi", 1.0)) & s.side.isin(rule.get("sides", ["YES", "NO"]))
    if rule.get("max_abs_disagreement") is not None:
        ok &= (s.prob - s.entry_mid).abs() <= rule["max_abs_disagreement"]
    if rule.get("families"):
        ok &= s.family.isin(rule["families"])
    b = s[ok]
    if rule.get("one_per"):
        b = b.sort_values(["net_edge", "contract_id", "side"], ascending=[False, True, True], kind="mergesort").drop_duplicates(rule["one_per"])
    return b.sort_values([c for c in ("date", "game_id", "contract_id") if c in b], kind="mergesort").reset_index(drop=True)


def wilson(k: int, n: int, z: float = 1.96) -> list:
    if n == 0:
        return [None, None]
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def poisson_binomial_p_at_least(k: int, ps: np.ndarray) -> float:
    """P(wins >= k) if each bet won exactly at its break-even probability (exact DP): small = the win count is hard to get by luck at break-even."""
    dist = np.zeros(len(ps) + 1); dist[0] = 1.0
    for p in ps:
        dist[1:] = dist[1:] * (1 - p) + dist[:-1] * p; dist[0] *= (1 - p)
    return float(dist[k:].sum())


def summarize(b: pd.DataFrame, boot: int = 2000, seed: int = 7) -> dict:
    n = len(b)
    if n == 0:
        return {"bets": 0}
    a = b.entry.to_numpy(float); w = b.won.to_numpy(float); f = b.fee.to_numpy(float); p = b.prob.to_numpy(float); net = w - a - f; cost = float((a + f).sum())
    f1 = np.array([fee_order(x, 1) for x in a]); be = a + f
    out = {"bets": n, "games": int(b.game_id.nunique()), "wins": int(w.sum()), "win_rate": round(float(w.mean()), 4), "win_rate_95ci": wilson(int(w.sum()), n),
           "expected_win_rate_model": round(float(p.mean()), 4), "avg_entry_price": round(float(a.mean()), 4), "avg_fee_unrounded": round(float(f.mean()), 4),
           "breakeven_win_prob": round(float(be.mean()), 4), "net_pnl_contracts": round(float(net.sum()), 3), "net_roi": round(float(net.sum() / cost), 4),
           "net_pnl_fee_rounded_1_contract_orders": round(float((w - a - f1).sum()), 3), "pnl_at_entry_mid_no_fee": round(float((w - b.entry_mid.to_numpy(float)).sum()), 3),
           "p_value_wins_at_breakeven": round(poisson_binomial_p_at_least(int(w.sum()), np.clip(be, 0, 1)), 4),
           "calibration_in_selection": {"expected_minus_observed": round(float(p.mean() - w.mean()), 4), "note": "positive = the model was overconfident on the bets it chose"}}
    if "depth" in b and b.depth.notna().any():
        q = np.minimum(10, b.depth.fillna(0).to_numpy(float)).astype(int); okq = q >= 1
        fq = np.array([fee_order(x, k) / k if k >= 1 else 0.0 for x, k in zip(a, q)])
        out["size_capped_10"] = {"bets_with_depth": int(okq.sum()), "contracts": int(q[okq].sum()), "net_pnl": round(float(((w - a - fq) * q)[okq].sum()), 3),
                                 "roi": round(float(((w - a - fq) * q)[okq].sum() / max(((a + fq) * q)[okq].sum(), 1e-9)), 4)}
    if "close_mid" in b and b.close_mid.notna().any():
        m = b.close_mid.notna().to_numpy()
        out["clv"] = {"n": int(m.sum()), "selection_clv_mean": round(float((b.close_mid - b.entry_mid)[m].mean()), 4), "quoted_execution_clv_mean": round(float((b.close_mid - b.entry)[m].mean()), 4),
                      "entry_spread_component_mean": round(float((b.entry - b.entry_mid)[m].mean()), 4), "entry_fee_mean_not_clv": round(float(b.fee[m].mean()), 4),
                      "basis": "sift-clv-canonical/1: selection = close_mid - entry_mid (market movement only); quoted = close_mid - ask; fee reported separately, never as CLV"}
    if boot and n > 1:
        g = b.game_id.to_numpy(); ug, inv = np.unique(g, return_inverse=True); gn = np.bincount(inv, weights=net); gc = np.bincount(inv, weights=a + f)
        rng = np.random.default_rng(seed); idx = rng.integers(0, len(ug), (boot, len(ug)))
        r = gn[idx].sum(1) / np.maximum(gc[idx].sum(1), 1e-12)
        out["net_roi_95ci_game_bootstrap"] = [round(float(np.quantile(r, .025)), 4), round(float(np.quantile(r, .975)), 4)]
    return out


def buckets(b: pd.DataFrame, edges=(0.05, 0.25, 0.5, 0.75, 0.95)) -> dict:
    lab = pd.cut(b.entry, list(edges), right=False, include_lowest=True)
    return {str(k): summarize(v, boot=0) for k, v in b.groupby(lab, observed=True)}


def diagnostics(c: pd.DataFrame) -> dict:
    """Market-wide diagnostics (NOT a promotion gate): Brier / log loss of model vs mid on every quoted contract."""
    mid = ((c.yes_bid + c.yes_ask) / 2).clip(1e-4, 1 - 1e-4).to_numpy(float); p = c.model_p.clip(1e-4, 1 - 1e-4).to_numpy(float); y = c.y.to_numpy(float)
    ll = lambda q: float(-(y * np.log(q) + (1 - y) * np.log(1 - q)).mean())
    return {"contracts": int(len(c)), "brier_model": round(float(((p - y) ** 2).mean()), 5), "brier_mid": round(float(((mid - y) ** 2).mean()), 5),
            "logloss_model": round(ll(p), 5), "logloss_mid": round(ll(mid), 5), "label": "diagnostic only; a selective strategy is judged on its own frozen selections"}


def evaluate(c: pd.DataFrame, rules: list, split_col: str | None = None, boot: int = 2000, seed: int = 7) -> dict:
    out = {"version": VERSION, "diagnostics": diagnostics(c), "rules": {}}
    for rule in rules:
        b = select(c, rule); r = {"rule": rule, "rule_sha256": freeze(rule), "all": summarize(b, boot, seed), "by_price_bucket": buckets(b),
                                  "by_family": {k: summarize(v, boot=0) for k, v in b.groupby("family")}, "by_side": {k: summarize(v, boot=0) for k, v in b.groupby("side")}}
        if split_col and split_col in b:
            r["by_split"] = {str(k): summarize(v, boot, seed) for k, v in b.groupby(split_col)}
        out["rules"][rule["name"]] = r
    return out
