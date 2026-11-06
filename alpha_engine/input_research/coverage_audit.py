"""Cross-sport input-catalog completeness and data-readiness audit (RESEARCH_ONLY).

Three questions, answered from the committed catalogs/artifacts only (plus an optional live reachability probe of the free-source URLs):
  1. MECHANISM COVERAGE: for each market archetype, which mechanism categories that its market KIND requires are absent from its candidate inputs? (A rule table, i.e. a
     completeness check, not proof that the present inputs are sufficient.)
  2. MARKET-DERIVED INPUTS: which catalog inputs are lines/prices/odds-based. They are BENCHMARK-ONLY and must never feed a primary model (marketfree policy).
  3. DATA READINESS: per input, collected / partial / missing / unverified from the availability audit, and reachability of its free sources.
"""
from __future__ import annotations

import collections
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAT = ROOT / "research/input_research/catalog"
IR = ROOT / "research/audit/input_research"
OUT = ROOT / "research/audit/input_research/coverage_audit.json"
SPORTS = ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"]

# What a predictive model of each market kind must account for. Categories are the catalog's own `category` values.
REQUIRED = {
    "winner": {"team_strength", "availability", "matchup", "schedule_context", "game_state"},
    "spread": {"team_strength", "availability", "matchup", "distribution", "schedule_context"},
    "total": {"pace_volume", "team_strength", "environment", "variance_luck", "distribution", "availability"},
    "team_total": {"pace_volume", "team_strength", "matchup", "availability", "distribution"},
    "player_stat": {"player_role", "availability", "pace_volume", "matchup", "game_state", "distribution"},
    "player_scorer": {"player_role", "availability", "pace_volume", "matchup", "game_state"},
    "period": {"pace_volume", "team_strength", "game_state", "distribution"},
    "season": {"team_strength", "availability", "schedule_context", "distribution", "motivation"},
    "other": {"distribution"},
}
KIND_BY_BLUEPRINT = [(r"player|prop|scorer|stat", "player_stat"), (r"team_total", "team_total"), (r"total|ou|over", "total"), (r"spread|handicap|margin", "spread"),
                     (r"half|quarter|period|inning|first", "period"), (r"season|futures|award|outright|champion|draft|mvp", "season"), (r"win|moneyline|match|game", "winner")]
MARKET_WORDS = re.compile(r"(\bodds\b|\bprices?\b|moneyline|\bvig\b|devig|closing (line|price)|kalshi|sportsbook|bookmaker|market[- ]implied|market lines?|implied prob|reference prices?)", re.I)
# m.* ids are "market structure" inputs. Price/quote/depth-derived ones are BENCHMARK-ONLY; contract definitions and realised-outcome frequencies are not price-derived.
PRICE_M = re.compile(r"^m\.(external_lines|quote_history|orderbook_depth|trade_tape|volume_oi|ladder_structure|combo_pricing|fees)$")


def kind_of(name: str, rec: dict) -> str:
    t = f"{name} {rec.get('label', '')} {rec.get('blueprint', '')}".lower()
    for rx, k in KIND_BY_BLUEPRINT:
        if re.search(rx, t):
            return k
    return "other"


def is_market_derived(iid: str, rec: dict) -> bool:
    """True = derived from lines/prices/quotes/depth: usable only to benchmark a finished model, never as a predictor."""
    if iid.startswith("m."):
        return bool(PRICE_M.match(iid))
    return bool(MARKET_WORDS.search(rec["label"]))


def mechanism_matrix() -> dict:
    out = {}
    for s in SPORTS:
        c = json.loads((CAT / f"{s}.json").read_text())
        rows = []
        for a, rec in c["archetypes"].items():
            bp = (c["blueprints"].get(rec.get("blueprint")) or {}).get("inputs", [])
            ids = {i["id"] for i in rec["inputs"]} | {i["id"] for i in bp}      # parent-blueprint inputs count: the archetype inherits them
            cats = collections.Counter(c["inputs"][i]["category"] for i in ids if not is_market_derived(i, c["inputs"][i]))
            k = kind_of(a, rec)
            miss = sorted(REQUIRED[k] - set(cats))
            rows.append({"archetype": a, "kind": k, "n_inputs": len(rec["inputs"]), "n_market_derived": sum(is_market_derived(i, c["inputs"][i]) for i in ids),
                         "categories_present": dict(cats), "required_categories_missing": miss})
        out[s] = rows
    return out


def market_derived() -> dict:
    out = {}
    for s in SPORTS:
        c = json.loads((CAT / f"{s}.json").read_text())
        md = sorted(i for i, r in c["inputs"].items() if is_market_derived(i, r))
        out[s] = {"inputs_total": len(c["inputs"]), "market_derived_benchmark_only": len(md), "ids": md}
    return out


def readiness() -> dict:
    out = {}
    for s in SPORTS:
        d = json.loads((IR / f"sport_{s}.json").read_text())
        c = json.loads((CAT / f"{s}.json").read_text())
        cnt = collections.Counter()
        usable = collections.Counter()
        for i, rec in d["inputs"].items():
            md = is_market_derived(i, c["inputs"][i]) if i in c["inputs"] else False
            st = rec["availability"]["overall"]
            cls = {"PIT_ARCHIVED": "collected_pit", "COMPUTED_IN_RESEARCH_PATH": "collected_pit", "COLLECTED_NOT_PIT_ARCHIVED": "partial", "PARTIAL_OR_STALE": "partial", "DERIVED": "derived",
                   "SOURCE_AVAILABLE_NOT_COLLECTED": "missing_source_exists", "NOT_IN_REGISTRY": "unverified_not_in_registry", "NO_FREE_SOURCE_FOUND": "missing_no_free_source",
                   "NO_REFERENCE_FOUND": "missing_no_free_source", "CODE_REFERENCE_ONLY": "unverified_code_only"}.get(st, "unverified")
            cnt[cls] += 1
            if not md:
                usable[cls] += 1
        out[s] = {"all_inputs": dict(cnt), "primary_model_eligible_inputs": dict(usable)}
    return out


def probe_sources(timeout=12) -> dict:
    urls = collections.defaultdict(set)
    for s in SPORTS:
        c = json.loads((CAT / f"{s}.json").read_text())
        for i, r in c["inputs"].items():
            for f in r["free_sources"]:
                for u in re.findall(r"https?://[^\s;,)\]]+", f) + ["https://" + x for x in re.findall(r"\(?((?:[a-z0-9\-]+\.)+(?:com|org|net|io|co\.uk|gov)(?:/[^\s;,)\]]*)?)", f)]:
                    urls[u.rstrip(".")].add(s)
    res = {}
    for u in sorted(urls):
        try:
            req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": "sift-alpha-research/1"})
            code = urllib.request.urlopen(req, timeout=timeout).status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:
            code = type(e).__name__
        res[u] = {"status": code, "sports": sorted(urls[u])}
    ok = sum(1 for v in res.values() if isinstance(v["status"], int) and v["status"] < 400)
    return {"n_urls": len(res), "reachable_2xx_3xx": ok, "note": "HEAD from a cloud runner: 403/405/429 often mean the site blocks automated clients, NOT that the data is unavailable; reachability is not licence review, coverage or point-in-time quality.", "urls": res}


def main():
    out = {"schema_version": "coverage-audit-1.0", "status": "RESEARCH_ONLY", "mechanism_matrix": mechanism_matrix(), "market_derived_inputs": market_derived(), "readiness": readiness()}
    if "--probe" in sys.argv:
        out["source_probe"] = probe_sources()
    elif OUT.exists():
        prev = json.loads(OUT.read_text())
        if "source_probe" in prev:
            out["source_probe"] = prev["source_probe"]
    OUT.write_text(json.dumps(out, indent=0, sort_keys=True))
    gaps = sum(len(r["required_categories_missing"]) > 0 for rows in out["mechanism_matrix"].values() for r in rows)
    tot = sum(len(rows) for rows in out["mechanism_matrix"].values())
    print(f"archetypes with a missing required mechanism category: {gaps}/{tot}")
    print({s: v["market_derived_benchmark_only"] for s, v in out["market_derived_inputs"].items()})


if __name__ == "__main__":
    main()
