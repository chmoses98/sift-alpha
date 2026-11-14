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

# What a predictive model of each market kind must account for. Categories are the catalog's own `category` values. This is a REVIEW CHECKLIST: a missing category is a
# prompt to adjudicate (genuine gap vs inapplicable), recorded in research/input_research/gap_adjudication.json, never an automatic verdict.
REQUIRED = {
    "game_winner": {"team_strength", "availability", "matchup", "schedule_context", "game_state"},
    "game_spread": {"team_strength", "availability", "matchup", "distribution", "schedule_context"},
    "game_total": {"pace_volume", "team_strength", "environment", "variance_luck", "availability", "matchup"},
    "team_total": {"pace_volume", "team_strength", "matchup", "availability", "distribution"},
    "period": {"pace_volume", "team_strength", "game_state", "availability", "variance_luck"},
    "player_game_stat": {"player_role", "availability", "pace_volume", "matchup", "game_state", "distribution"},
    "player_scorer": {"player_role", "availability", "pace_volume", "matchup", "distribution"},
    "availability_event": {"availability", "schedule_context", "player_role", "motivation"},
    "season_team": {"team_strength", "availability", "schedule_context", "distribution"},
    "season_player": {"player_role", "availability", "team_strength", "distribution"},
    "in_game_event": {"game_state", "variance_luck", "team_strength"},
    "special_event": {"distribution"},
}
# ordered: first matching token wins
KIND_TOKENS = [("availability_event", {"availability", "participation"}),
               ("season_team", {"futures", "champion", "conference", "seed", "relegation", "advancement", "qualification", "winner_and_top", "series_and_cup", "competition_winner", "win_totals", "points_and_margin"}),
               ("season_player", {"awards", "award", "leaders", "leader", "draft", "escalator", "ranking", "majors", "season_stat_markets", "season_stats"}),
               ("special_event", {"mentions", "transactions", "off_field", "off_court", "announcer", "host", "special", "retirement", "walkover", "nationality", "combo"}),
               ("in_game_event", {"overtime", "events", "tiebreak", "sweep", "delay", "extras", "game_events"}),
               ("team_total", {"team_total"}),
               ("period", {"first_half", "half", "quarter", "inning", "period", "periods", "first5", "set_winner", "exact_set_score"}),
               ("player_scorer", {"scorer", "td_scorer", "home_runs", "anytime"}),
               ("player_game_stat", {"props", "points", "rebounds", "assists", "threes", "steals", "yards", "receptions", "strikeouts", "hits", "rbis", "aces", "free_throws", "milestones", "h2h", "stat", "stats", "earned_runs", "passing", "rushing", "receiving", "player"}),
               ("game_spread", {"spread", "spreads", "margin", "moneyline_spread"}),
               ("game_total", {"total", "totals", "goals"}),
               ("game_winner", {"moneyline", "winner", "match", "result", "3way"})]
MARKET_WORDS = re.compile(r"(\bodds\b|\bprices?\b|moneyline|\bvig\b|devig|closing (line|price)|kalshi|sportsbook|bookmaker|market[- ]implied|market lines?|implied prob|reference prices?)", re.I)
# m.* ids are "market structure" inputs. Price/quote/depth-derived ones are BENCHMARK-ONLY; contract definitions and realised-outcome frequencies are not price-derived.
PRICE_M = re.compile(r"^m\.(external_lines|quote_history|orderbook_depth|trade_tape|volume_oi|ladder_structure|combo_pricing|fees)$")


def kind_of(name: str, rec: dict) -> str:
    toks = set(name.lower().split("_"))
    joined = name.lower()
    for kind, words in KIND_TOKENS:
        if any((w in toks) if "_" not in w else (w in joined) for w in words):
            return kind
    return "special_event"


def is_market_derived(iid: str, rec: dict) -> bool:
    """True = BENCHMARK-ONLY (price/line-derived): never a predictor. Hybrids are separate (market_dependency.HYBRID_REBUILD: usable only after a market-free rebuild)."""
    from . import market_dependency as MD
    return MD.kind(iid) == "benchmark_only"


def adjudications() -> dict:
    f = ROOT / "research/input_research/gap_adjudication.json"
    return {(a["sport"], a["archetype"], a["category"]): a["verdict"] for a in json.loads(f.read_text())["adjudications"]} if f.exists() else {}


def mechanism_matrix() -> dict:
    adj = adjudications()
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
            unresolved = [c for c in miss if (s, a, c) not in adj]
            rows.append({"archetype": a, "kind": k, "checklist_missing_adjudicated": {c: adj[(s, a, c)] for c in miss if (s, a, c) in adj}, "unadjudicated_missing": unresolved, "n_inputs": len(rec["inputs"]), "n_market_derived": sum(is_market_derived(i, c["inputs"][i]) for i in ids),
                         "categories_present": dict(cats), "required_categories_missing": miss})
        out[s] = rows
    return out


def market_derived() -> dict:
    out = {}
    for s in SPORTS:
        c = json.loads((CAT / f"{s}.json").read_text())
        from . import market_dependency as MD
        md = sorted(i for i, r in c["inputs"].items() if is_market_derived(i, r))
        hy = sorted(i for i in c["inputs"] if MD.kind(i) == "hybrid_rebuild")
        out[s] = {"inputs_total": len(c["inputs"]), "market_derived_benchmark_only": len(md), "ids": md, "hybrid_rebuild_required": len(hy), "hybrid_ids": hy}
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
        vs = verified_sources()
        ids = set(d["inputs"])
        out[s] = {"all_inputs": dict(cnt), "primary_model_eligible_inputs": dict(usable), "with_measured_free_source": sorted(i for i in ids if i in vs["verified"]),
                  "snapshot_only_source": sorted(i for i in ids if i in vs["snapshot_only"])}
    return out


def verified_sources() -> dict:
    """Inputs served by a free source MEASURED reachable and populated (source_verify.py): {'verified': {id: [sources]}, 'snapshot_only': [ids]}."""
    f = ROOT / "research/input_research/source_verification.json"
    if not f.exists():
        return {"verified": {}, "snapshot_only": []}
    v = json.loads(f.read_text())
    ver: dict[str, list[str]] = {}
    def add(ids, src):
        for i in ids:
            ver.setdefault(i, []).append(src)
    for tag, rec in v["nflverse"].items():
        if rec.get("earliest_ok_probed") or rec.get("status") == 200:
            add(rec["serves_catalog_inputs"], f"nflverse/{tag}" + (f" {rec['earliest_ok_probed']}-{rec['latest_ok_probed']}" if rec.get("earliest_ok_probed") else ""))
    if any(g.get("pitches_with_pitchData") for g in v["mlb_statsapi"]["sampled_games"].values()):
        add(v["mlb_statsapi"]["serves_catalog_inputs"], "MLB StatsAPI (pitch/hit data 2008+, lineups, umpires, observed weather)")
    if any(g.get("plays") for g in v["nhl_api"]["sampled_games"].values()):
        add(v["nhl_api"]["serves_catalog_inputs"], "NHL API play-by-play (2015+ sampled)")
    if v["football_data"].get("files"):
        add([i for i in v["football_data"]["serves_catalog_inputs"] if i != "soc.referee"], "football-data.co.uk 2015/16-2025/26 (5 leagues, team level)")
        add(["soc.referee"], "football-data.co.uk (Premier League only)")
    return {"verified": ver, "snapshot_only": v["espn"]["serves_catalog_inputs"]}


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
    gaps = sum(len(r["unadjudicated_missing"]) > 0 for rows in out["mechanism_matrix"].values() for r in rows)
    tot = sum(len(rows) for rows in out["mechanism_matrix"].values())
    print(f"archetypes with an UNADJUDICATED missing mechanism category: {gaps}/{tot}")
    print({s: v["market_derived_benchmark_only"] for s, v in out["market_derived_inputs"].items()})


if __name__ == "__main__":
    main()
