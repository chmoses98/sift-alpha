"""NBA player-prop challenger from the PURE shadow store (branch nba-shadow-pure): market-independent forecasts (frozen V1 simulator `sim_rotation`
and the EWM5 statistical baseline) priced against Kalshi player-prop listings observed at or before the forecast's as_of. RESEARCH_ONLY.

A forecast row carries P(stat >= rung) for a fixed ladder; a listing is only paired when its `at_least` equals a ladder rung exactly (no interpolation).
Forecasts are CONDITIONAL on playing (DNP contracts are void), so rows are paired with outcomes only for players who played.
Rows (dict): game, t=as_of, mid, q, y, fam, hor=slot, ticker, spread, bid_size, ask_size, stale, hb.
"""
from __future__ import annotations
import collections, glob, gzip, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nba_nhl_common as C

ARMS = ("sim_rotation", "ewm5")
STATS = ("points", "rebounds", "assists", "threes")
MAX_SPREAD = 0.10
MID_LO, MID_HI = 0.03, 0.97


def _read(root, pat):
    for f in sorted(glob.glob(os.path.join(root, pat))):
        with gzip.open(f, "rt") as fh:
            for l in fh:
                if l.strip():
                    yield json.loads(l)


def build(root):
    """-> (rows, info). Nothing from after as_of is used as a feature: quote board_observed_at <= as_of, listed_by_as_of True."""
    info = collections.Counter()
    outcomes = {}
    for r in _read(root, "outcomes/gate/dt=*/*.jsonl.gz"):
        outcomes[(r["game_id"], str(r["player_id"]), r["statistic"])] = (r["actual"], r["played"], C.ts(r["observed_at"]))
    info["outcome_rows"] = len(outcomes)
    listings = {}
    for r in _read(root, "market/listings/dt=*/*.jsonl.gz"):
        info["listing_rows"] += 1
        if r.get("record") != "market_listing":
            continue
        listings[(r["game_id"], str(r["player_id"]), r["statistic"], r["pure_as_of"], r["at_least"])] = r
    info["listing_keys"] = len(listings)
    rows = []
    for arm in ARMS:
        for r in _read(root, f"projections/{arm}/conditional/dt=*/*.jsonl.gz"):
            st = r["statistic"]
            if st not in STATS:
                continue
            info[f"{arm}_forecast_rows_{st}"] += 1
            for th in r["projection"]["thresholds"]:
                lk = listings.get((r["game_id"], str(r["player_id"]), st, r["as_of"], th["at_least"]))
                if lk is None:
                    info["rung_without_listing"] += 1
                    continue
                if not lk.get("listed_by_as_of"):
                    info["not_listed_by_as_of"] += 1
                    continue
                as_of, obs, kick = C.ts(r["as_of"]), C.ts(lk["board_observed_at"]), C.ts(r["kickoff"])
                if obs > as_of or as_of >= kick or C.ts(r["source_max_observed_at"]) > as_of:
                    info["time_invalid_dropped"] += 1
                    continue
                oc = outcomes.get((r["game_id"], str(r["player_id"]), st))
                if oc is None:
                    info["no_outcome_yet"] += 1
                    continue
                actual, played, _ = oc
                if not played:
                    info["dnp_void"] += 1
                    continue
                yb, ya = lk.get("yes_bid_cents"), lk.get("yes_ask_cents")
                if not yb or not ya or ya < yb or (ya - yb) / 100 > MAX_SPREAD:
                    info["not_two_sided_or_wide"] += 1
                    continue
                mid = (yb + ya) / 200
                p = float(th["probability"])
                if not (MID_LO <= mid <= MID_HI) or not (0 < p < 1):
                    info["tail_or_degenerate_dropped"] += 1
                    continue
                rows.append(dict(game=r["game_id"], t=as_of, mid=mid, q=p, y=int(actual >= th["at_least"]), fam=f"player_{st}[shadow:{arm}]", hor="SLOT_" + r["x_slot"],
                                 ticker=lk["ticker"], spread=(ya - yb) / 100, bid_size=None, ask_size=None, stale=as_of - obs, hb=(kick - as_of) / 3600, arm=arm))
    info["rows"] = len(rows)
    return rows, dict(info)
