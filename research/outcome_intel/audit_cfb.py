#!/usr/bin/env python3
"""Independent audit of the CFB 2026 outcome conclusions from PR #25 (RESEARCH_ONLY).

Deliberately does NOT import research/outcome_exec or sift_research: ticker parsing, settlement re-derivation, fees and the
cluster bootstrap are re-implemented here so agreement with the PR is evidence, not tautology.

usage: python3 -I research/outcome_intel/audit_cfb.py --root <cfb-edge-finder research-data checkout> --out reports/outcome_intel/cfb_audit.json
"""
from __future__ import annotations
import argparse, glob, hashlib, json, math, os, re
from collections import Counter, defaultdict
from datetime import datetime
import numpy as np

STATUS = "RESEARCH_ONLY"


def pdt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def read_jsonl(pattern):
    rows, hashes = [], {}
    for f in sorted(glob.glob(pattern)):
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for line in fh:
                h.update(line)
                if line.strip():
                    rows.append(json.loads(line))
        hashes[os.path.basename(os.path.dirname(f)) + "/" + os.path.basename(f)] = h.hexdigest()
    return rows, hashes


# ------------------------------------------------------------------ independent settlement re-derivation
def parse_ticker(ticker):
    """-> dict(family, event_code, strike, team) from a Kalshi NCAAF ticker. None if unparseable."""
    m = re.match(r"^KXNCAAF(GAME|SPREAD|TOTAL)-(\d{2}[A-Z]{3}\d{2})([A-Z0-9]+)-([A-Z0-9]+)$", ticker or "")
    if not m:
        return None
    kind, _, code, suffix = m.groups()
    if kind == "GAME":
        return dict(family="moneyline", code=code, team=suffix, strike=None)
    if kind == "TOTAL":
        return dict(family="total", code=code, team=None, strike=int(suffix) - 0.5) if suffix.isdigit() else None
    mm = re.match(r"^([A-Z]+)(\d+)$", suffix)
    return dict(family="spread", code=code, team=mm.group(1), strike=int(mm.group(2)) - 0.5) if mm else None


def side_of(code, team):
    """Event code is AWAY+HOME concatenated. Returns 'away'/'home'/None (ambiguous)."""
    a, h = code.startswith(team), code.endswith(team)
    return "away" if a and not h else "home" if h and not a else None


def rederive(ticker, away_pts, home_pts):
    p = parse_ticker(ticker)
    if p is None or away_pts is None or home_pts is None:
        return None
    if p["family"] == "total":
        return "yes" if away_pts + home_pts > p["strike"] else "no"
    side = side_of(p["code"], p["team"])
    if side is None:
        return None
    margin = (away_pts - home_pts) if side == "away" else (home_pts - away_pts)
    if p["family"] == "moneyline":
        return None if margin == 0 else ("yes" if margin > 0 else "no")
    return "yes" if margin > p["strike"] else "no"


# ------------------------------------------------------------------ independent statistics
def fee(price, lots=1):
    """Kalshi taker fee per contract: ceil_to_cent(0.07*C*P*(1-P)) / C."""
    return math.ceil(round(0.07 * lots * price * (1 - price) * 100, 9)) / 100 / lots


def cluster_mean(vals, clusters, n_boot=2000, seed=101):
    v = np.asarray(vals, float)
    _, inv = np.unique(np.asarray(clusters), return_inverse=True)
    k = inv.max() + 1
    s, n = np.bincount(inv, weights=v, minlength=k), np.bincount(inv, minlength=k).astype(float)
    idx = np.random.default_rng(seed).integers(0, k, size=(n_boot, k))
    b = s[idx].sum(1) / n[idx].sum(1)
    return dict(mean=float(s.sum() / n.sum()), lo=float(np.quantile(b, .025)), hi=float(np.quantile(b, .975)), n=int(v.size), n_games=int(k))


# ------------------------------------------------------------------ audit
def run(root):
    obs, oh = read_jsonl(os.path.join(root, "data/research/observations/*/*.jsonl"))
    sett, sh = read_jsonl(os.path.join(root, "data/research/settlements/*/*.jsonl"))
    A = dict(status=STATUS, schema="sift-outcome-intel-audit/1", inputs=dict(
        observation_files=len(oh), settlement_files=len(sh), observation_rows=len(obs), settlement_rows=len(sett),
        observations_sha256=hashlib.sha256("".join(oh[k] for k in sorted(oh)).encode()).hexdigest(),
        settlements_sha256=hashlib.sha256("".join(sh[k] for k in sorted(sh)).encode()).hexdigest()))

    # --- settlement table
    by_t = defaultdict(list)
    for r in sett:
        by_t[r["kalshi_market_ticker"]].append(r)
    settled = {}
    conflict = 0
    for t, rs in by_t.items():
        ok = [r for r in rs if r["status"] == "settled"]
        if len({r["derived_contract_settlement"] for r in ok}) > 1:
            conflict += 1
        if ok:
            settled[t] = max(ok, key=lambda r: r["settled_at"])
    A["settlement"] = dict(
        rows_by_status=dict(Counter(r["status"] for r in sett)), tickers=len(by_t), tickers_settled=len(settled),
        tickers_with_conflicting_settled_rows=conflict,
        official_kalshi_settlement_populated=sum(r.get("official_kalshi_settlement") is not None for r in sett),
        mismatch_flagged=sum(bool(r["settlement_mismatch_flagged"]) for r in sett),
        score_source=dict(Counter((r["game_result"] or {}).get("source") for r in settled.values())),
        went_to_overtime=sum(bool((r["game_result"] or {}).get("went_to_overtime")) for r in settled.values()),
        NOTE="official_kalshi_settlement is null on every row: outcomes are DERIVED from a final score + ticker rules, never confirmed against Kalshi's own settlement")

    # --- independent re-derivation of every settled contract
    agree = Counter()
    bad = []
    for t, r in settled.items():
        g = r["game_result"]
        mine = rederive(t, g["away_points"], g["home_points"])
        key = "unparseable_or_ambiguous" if mine is None else ("agree" if mine == r["derived_contract_settlement"] else "DISAGREE")
        agree[key] += 1
        if key != "agree" and len(bad) < 20:
            bad.append(dict(ticker=t, mine=mine, stored=r["derived_contract_settlement"], away=g["away_points"], home=g["home_points"]))
    A["settlement_rederivation"] = dict(counts=dict(agree), examples=bad)

    # --- observations: timing, PIT, duplicates, joins
    ev = [x for x in obs if x["observation"]["coverage_outcome"] == "evaluated"]
    kick = defaultdict(set)
    for x in obs:
        kick[x["observation"]["game_id"]].add(x["kickoff_utc_at_capture"])
    ev_game = defaultdict(set)
    for x in obs:
        o = x["observation"]
        if o.get("kalshi_event_ticker"):
            ev_game[o["kalshi_event_ticker"]].add(o["game_id"])
    t_viol = dict(captured_at_or_after_kickoff=0, captured_before_data_timestamp=0, hours_before_kickoff_inconsistent=0,
                  settled_before_kickoff_plus_2h=0, snapshot_after_settlement_capture=0, mapping_key_in_corpus_dupes=0)
    kdict = {g: min(v) for g, v in kick.items()}
    for x in ev:
        o = x["observation"]
        cap, ko = pdt(o["captured_at"]), pdt(x["kickoff_utc_at_capture"])
        t_viol["captured_at_or_after_kickoff"] += cap >= ko
        t_viol["captured_before_data_timestamp"] += pdt(o["provenance"]["data_timestamp"]) > cap
        h = o["snapshot_timing"]["hours_before_kickoff"]
        t_viol["hours_before_kickoff_inconsistent"] += abs((ko - cap).total_seconds() / 3600 - h) > 0.05
        s = settled.get(o["kalshi_market_ticker"])
        if s:
            t_viol["snapshot_after_settlement_capture"] += cap >= pdt(s["settled_at"])
    for t, s in settled.items():
        g = s["game_id"]
        if g in kdict:
            t_viol["settled_before_kickoff_plus_2h"] += (pdt(s["settled_at"]) - pdt(kdict[g])).total_seconds() < 2 * 3600
    keys = Counter((x["observation"]["kalshi_market_ticker"], x["observation"]["snapshot_timing"]["label"]) for x in ev)
    t_viol["mapping_key_in_corpus_dupes"] = sum(v - 1 for v in keys.values() if v > 1)
    A["timing"] = dict(violations=t_viol, games_with_multiple_kickoffs=sum(len(v) > 1 for v in kick.values()),
                       events_mapped_to_multiple_games=sum(len(v) > 1 for v in ev_game.values()),
                       evaluated_rows=len(ev), all_rows=len(obs))
    orphan_obs = {x["observation"]["kalshi_market_ticker"] for x in ev} - set(by_t)
    A["join"] = dict(evaluated_tickers=len({x["observation"]["kalshi_market_ticker"] for x in ev}),
                     evaluated_tickers_with_settlement_row=len({x["observation"]["kalshi_market_ticker"] for x in ev} & set(by_t)),
                     evaluated_tickers_without_any_settlement_row=len(orphan_obs),
                     settlement_tickers_without_observation=len(set(by_t) - {x["observation"]["kalshi_market_ticker"] for x in ev}),
                     settled_tickers_with_observation=len({x["observation"]["kalshi_market_ticker"] for x in ev} & set(settled)))

    # --- denominators (independent games)
    rows = []
    for x in ev:
        o = x["observation"]
        s = settled.get(o["kalshi_market_ticker"])
        if not s or o.get("model_probability") is None or o.get("executable_yes_price") is None or o.get("executable_no_price") is None:
            continue
        y = 1 if s["derived_contract_settlement"] == "yes" else 0
        rows.append(dict(t=o["kalshi_market_ticker"], g=o["game_id"], fam=o["family"], lab=o["snapshot_timing"]["label"], cap=o["captured_at"],
                         ko=x["kickoff_utc_at_capture"], p=o["model_probability"], mid=o["market_midpoint"], ay=o["executable_yes_price"],
                         an=o["executable_no_price"], y=y))
    for r in rows:
        r["spread"] = r["ay"] + r["an"] - 1
    games = sorted({r["g"] for r in rows})
    per_game = Counter(r["g"] for r in rows)
    tick_per_game = defaultdict(set)
    for r in rows:
        tick_per_game[r["g"]].add(r["t"])
    A["denominators"] = dict(
        usable_settled_rows=len(rows), usable_settled_tickers=len({r["t"] for r in rows}), independent_games=len(games),
        by_family={f: dict(rows=sum(r["fam"] == f for r in rows), tickers=len({r["t"] for r in rows if r["fam"] == f}),
                           games=len({r["g"] for r in rows if r["fam"] == f})) for f in ("moneyline", "spread", "total")},
        tickers_per_game=dict(zip(("min", "median", "max"), map(float, np.quantile([len(v) for v in tick_per_game.values()], [0, .5, 1])))),
        rows_per_game=dict(zip(("min", "median", "max"), map(float, np.quantile(list(per_game.values()), [0, .5, 1])))),
        note="rows are NOT independent: ~%d snapshot rows/game; the inferential unit is the game" % int(np.median(list(per_game.values()))))
    # kickoff-date split used by the PR (discovery/validation/holdout) -> independent games per period
    dates = sorted({r["ko"][:10] for r in rows})
    A["denominators"]["games_by_kickoff_date"] = {d: len({r["g"] for r in rows if r["ko"][:10] == d}) for d in dates}

    # --- independent recompute: model-vs-market Brier (spread<=0.10) and buy-all-at-ask
    ok = [r for r in rows if r["spread"] <= 0.10]
    d = [(r["p"] - r["y"]) ** 2 - (r["mid"] - r["y"]) ** 2 for r in ok]
    A["recompute_brier_model_minus_market"] = dict(cluster_mean(d, [r["g"] for r in ok]),
        brier_model=float(np.mean([(r["p"] - r["y"]) ** 2 for r in ok])), brier_market=float(np.mean([(r["mid"] - r["y"]) ** 2 for r in ok])),
        PR_reported=dict(n=31043, mean=0.012657, lo=0.003097, hi=0.022691))
    first = {}
    for r in sorted(rows, key=lambda r: r["cap"]):
        if r["spread"] <= 0.10:
            first.setdefault(r["t"], r)
    A["recompute_buy_every_side_at_ask"] = {}
    for name, sel in (("earliest_nonthin_snapshot_per_ticker", list(first.values())),
                      ("CLOSING_snapshot_nonthin", [r for r in rows if r["lab"] == "CLOSING" and r["spread"] <= 0.10])):
        for lots in (1, 100):
            pn, cl = [], []
            for r in sel:
                for price, win in ((r["ay"], r["y"]), (r["an"], 1 - r["y"])):
                    pn.append(win - price - fee(price, lots)); cl.append(r["g"])
            A["recompute_buy_every_side_at_ask"][f"{name}|fee_{lots}lot"] = cluster_mean(pn, cl)
    A["recompute_buy_every_side_at_ask"]["PR_reported_all_(1-lot fee)"] = dict(mean=-0.030864, lo=-0.032091, hi=-0.029708, n=9104)
    A["fee_note"] = ("cfb_outcome.side_pnl uses a 1-contract ceil-to-cent fee (matches the corpus' estimated_taker_fee field); "
                     "nfl_outcome uses 100 lots. The 100-lot variant is ~0.2-0.5c cheaper per contract; sign and significance of every CFB null is unchanged.")
    return A


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default="reports/outcome_intel/cfb_audit.json")
    a = ap.parse_args()
    res = run(a.root)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=1, sort_keys=True)
    print(json.dumps({k: res[k] for k in ("settlement_rederivation", "timing", "join", "recompute_brier_model_minus_market")}, indent=1)[:3500])


if __name__ == "__main__":
    main()
