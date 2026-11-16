"""Do "protected" player props settle like their base family?  (MANUAL, RESEARCH_ONLY, read-only.)

Kalshi lists a protected twin for most NBA player-prop series (KXNBAPTSPROT next to KXNBAPTS, ...).  Its rules
text says the contract settles on the actual statistic like the base contract, except that it resolves to the pre-tip
fair price when the player entered in the first half, never re-entered after half-time and did not reach the line.
The NBA engine marks every protected contract UNSETTLEABLE ("semantics not proven").  This module measures the
claim on settled results: each protected contract is paired with the engine's own result for the base contract of
the same event, player and line.

    engine YES / NO vs exchange yes / no  ->  agree / disagree
    exchange resolved to a fair price     ->  fair_price (cross-tabbed with the engine's base result)

Output: counts per series only.

    python -m alpha_engine.game_completeness.protected_props --official LIVE/NBA HIST/NBA \
        --computed 'DA/settlements/*/*.jsonl.gz' --as-of <ts> --out research/game_completeness/protected_props_NBA.json
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .kalshi_official import _computed, load_official


def base_ticker(ticker):
    """'KXNBAPTSPROT-EV-PLAYER-25' -> 'KXNBAPTS-EV-PLAYER-25'; None when the series is not a protected twin."""
    series, sep, rest = ticker.partition("-")
    return series[:-4] + sep + rest if series.endswith("PROT") and sep else None


def resolution(row):
    """'yes' | 'no' | 'fair_price' | 'other' for one official row."""
    res = (row.get("result") or "").lower()
    try:
        v = float(row.get("settlement_value_dollars"))
    except (TypeError, ValueError):
        v = None
    if v is not None and 0 < v < 1:
        return "fair_price"
    return res if res in ("yes", "no") else "other"


def measure(official, engine):
    """official: {ticker: row}; engine: {ticker: 'YES'|'NO'|other} computed results (base families)."""
    by = defaultdict(Counter)
    for t, row in official.items():
        b = base_ticker(t)
        if not b:
            continue
        c = by[t.split("-")[0]]
        res, eng = resolution(row), engine.get(b)
        eng_l = eng.lower() if eng in ("YES", "NO") else ("engine_no_base_row" if eng is None else "engine_unsettleable")
        if res == "fair_price":
            c[f"fair_price|engine_{eng_l}" if eng in ("YES", "NO") else f"fair_price|{eng_l}"] += 1
        elif res == "other":
            c["exchange_not_binary"] += 1
        elif eng not in ("YES", "NO"):
            c[eng_l] += 1
        else:
            c["agree" if res == eng_l else f"disagree|exchange_{res}_engine_{eng_l}"] += 1
    total = Counter()
    for c in by.values():
        total.update(c)
    return {"totals": dict(sorted(total.items())), "by_series": {s: dict(sorted(c.items())) for s, c in sorted(by.items())}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--official", nargs="+", required=True)
    ap.add_argument("--computed", required=True)
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    official = {}
    for folder in a.official:
        official.update(load_official(folder))
    doc = {"schema": "protected-props-equivalence-1.0", "as_of": a.as_of,
           "notice": "Agent-run, not human verified. Counts only.", **measure(official, _computed(a.computed))}
    Path(a.out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(json.dumps(doc["totals"], indent=1))


if __name__ == "__main__":
    main()
