"""Slim, dashboard-sized summaries of the two milestone-2 artifacts (RESEARCH_ONLY): verified computable inputs and the scaled ledger-logged search.
Reads research/input_research/computable_inputs.json and research/audit/input_research/scaled_search/*.json; writes computable_summary.json and scaled_search_summary.json."""
from __future__ import annotations

import collections
import gzip
import json
from pathlib import Path

from . import ledger as L
from . import scaled_search as SS

ROOT = Path(__file__).resolve().parents[2]
IN = ROOT / "research/input_research"
AUD = ROOT / "research/audit/input_research"
OK = ("COMPUTED_FULL", "COMPUTED_PARTIAL", "COMPUTED_PROXY", "COMPUTED_LIMITED_FULL", "COMPUTED_LIMITED_PARTIAL", "COMPUTED_LIMITED_PROXY")


def computable_summary() -> dict:
    d = json.load(open(IN / "computable_inputs.json"))
    rows, blockers = [], collections.Counter()
    for k, v in d["inputs"].items():
        cov = v.get("coverage") or {}
        cmin = min((c["coverage"] for c in cov.values() if c.get("present")), default=None)
        firsts = [c["first"] for c in cov.values() if c.get("first")]; lasts = [c["last"] for c in cov.values() if c.get("last")]
        rows.append({"k": k, "s": v["status"], "lv": v.get("level"), "cov": cmin, "from": min(firsts) if firsts else None, "to": max(lasts) if lasts else None, "why": v.get("reason", ""), "miss": v.get("missing", []), "cols": len(v.get("columns", []))})
        if v["status"] == "NOT_COMPUTED":
            for b in v.get("blockers") or ["builder_not_written"]:
                blockers[b] += 1
    verified = [r for r in rows if r["s"] in OK]
    non_market = [r for r in rows if r["s"] != "EXCLUDED_BENCHMARK_ONLY"]
    return {"schema_version": "computable-summary-1.0", "status": "RESEARCH_ONLY", "generated": d["generated"], "n_inputs": d["n_inputs"], "n_non_market": len(non_market), "verified_computed": len(verified),
            "verified_by_level": dict(collections.Counter(r["lv"] for r in verified)), "totals": d["totals"], "by_sport": d["by_sport"], "blocker_classes": dict(blockers.most_common()),
            "verification": "point-in-time perturbation (future outcomes + own-game outcomes randomised, earlier/own-row features must be bit-identical) + non-constant + coverage; never keyword matching", "inputs": rows}


def scaled_summary() -> dict:
    rows, led_rows = [], 0
    results = []
    for f in sorted((AUD / "scaled_search").glob("*.json")):
        r = json.load(open(f)); results.append(r)
    fin = SS.finalize(results) if results else {}
    for r in results:
        if r["status"] != "TESTED":
            rows.append({"market": r["market"], "status": r["status"], "why": r.get("reason", "")}); continue
        g = r["gain"]; led_rows += r["ledger_rows"]
        rows.append({"market": r["market"], "status": "TESTED", "unit": r["meta"]["unit"], "n": r["meta"]["n"], "mode": r["meta"]["mode"], "baseline": r["meta"]["baseline"], "groups": r["n_groups"], "blocks": len(g["seasons"]), "cfg": r["n_configs_per_fold"],
                     "gain": g["pct_gain"], "ci": g["ci_0.05"], "p": g["p"], "holm_p": r["holm_p"], "pos": g["seasons_positive"], "halves": g.get("halves_pct"), "null": [n["pct_gain"] for n in r["nulls"]], "verdict": r["verdict"],
                     "top": list(r["importance_drop_group"].items())[:3], "sec": r["seconds"]})
    lab = L.count_lab59()
    ld = AUD / "scaled_search/ledger"
    ledger_files = sorted(list(ld.glob("*.jsonl")) + list(ld.glob("*.jsonl.gz"))) if ld.exists() else []
    n_cfg = n_unique = 0
    for f in ledger_files:
        ids = set()
        for l in (gzip.open(f, "rt") if f.suffix == ".gz" else open(f)):
            if l.strip():
                r = json.loads(l); n_cfg += 1; ids.add(json.dumps(r["config"].get("cfg"), sort_keys=True) + r["config"].get("market", ""))
        n_unique += len(ids)
    return {"schema_version": "scaled-search-1.0", "status": "RESEARCH_ONLY", "totals": {"markets": len(results), **fin}, "ledger": {"rows_logged": n_cfg, "unique_market_configurations": n_unique, "files": len(ledger_files), "lab59_experiments_read_only": lab.get("total")},
            "multiple_testing": "permutation null (2 reps through the identical nested procedure), cluster-bootstrap p per market, Holm across ALL tested markets, halves and block-positivity required, real gain must exceed 2x the null gain",
            "rows": sorted(rows, key=lambda x: (x.get("verdict") != "VALIDATED", x.get("verdict") != "SUGGESTIVE", x["market"]))}


def build():
    (IN / "computable_summary.json").write_text(json.dumps(computable_summary(), separators=(",", ":")))
    (AUD / "scaled_search_summary.json").write_text(json.dumps(scaled_summary(), separators=(",", ":"), default=float))


def compress_ledgers():
    """Ledger JSONL -> .jsonl.gz (same convention as #59: fresh checkouts carry only gzipped ledgers; ledger.Ledger reads either)."""
    for f in (AUD / "scaled_search/ledger").glob("*.jsonl"):
        gz = Path(str(f) + ".gz"); gz.write_bytes(gzip.compress(f.read_bytes(), 9)); f.unlink()


if __name__ == "__main__":
    build()
