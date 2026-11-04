"""Eight-sport real archive metadata diagnostics, immutable and $0.

These snapshots prove archives are discoverable and validate file provenance,
NOT that every market can be joined to games/settlements or yields profitable
opportunities. Never query Kalshi here. No credentials or write access.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

VALID_SHA = re.compile(r"^[0-9a-f]{40}$")
ALLOWED = {
    "CFB": "chmoses98/cfb-edge-finder",
    "NFL": "chmoses98/nfl-edge-finder",
    "NBA": "chmoses98/nba-edge-finder",
    "NHL": "chmoses98/NHL-edge-finder",
    "MLB": "chmoses98/edge-finder-api",
    "CBB": "chmoses98/cbb-edge-finder",
    "SOCCER": "chmoses98/soccer-edge-finder",
    "TENNIS": "chmoses98/Tennis-Edge-Finder",
}
EXPECTED_KIND = {
    "CFB": "market_catalog_status",
    "NFL": "market_open_set",
    "NBA": "settlement_status",
    "NHL": "settlement_status",
    "MLB": "replay_status",
    "CBB": "market_snapshot_summary",
    "SOCCER": "fixture_context_status",
    "TENNIS": "market_capture_manifest",
}

def manifest_entries(manifest):
    if manifest.get("schema_version") != 1 or type(manifest.get("total_limit_bytes")) is not int:
        raise ValueError("Bad manifest version/budget")
    entries = manifest.get("sources")
    if not isinstance(entries, list) or len(entries) != 8:
        raise ValueError("All eight current sport sources required")
    if {x.get("sport") for x in entries} != set(ALLOWED):
        raise ValueError("Duplicate, missing or unknown sport")
    total = 0
    for x in entries:
        if x.get("repo") != ALLOWED[x["sport"]] or x.get("kind") != EXPECTED_KIND[x["sport"]]:
            raise ValueError("Unapproved source")
        if not VALID_SHA.fullmatch(x.get("commit", "")) or not VALID_SHA.fullmatch(x.get("sha", "")):
            raise ValueError("Unpinned source")
        path = x.get("path", "")
        if not re.fullmatch(r"[A-Za-z0-9_./=-]+", path) or ".." in path.split("/") or not path.endswith(".json"):
            raise ValueError("Untrusted or non-JSON source path")
        size = x.get("max_bytes")
        if type(size) is not int or size < 1 or size > 50000:
            raise ValueError("Unbounded file read")
        total += size
    if total > min(manifest["total_limit_bytes"], 140000):
        raise ValueError("Aggregate source budget exceeded")
    return entries

def source_url(x):
    return f"https://raw.githubusercontent.com/{x['repo']}/{x['commit']}/{x['path']}"

def read_pinned(x, downloader=None):
    if downloader:
        data = downloader(x)
    else:
        url = source_url(x)
        request = Request(url, headers={"User-Agent":"SIFT-Alpha-all-sport-public-audit/1"})
        with urlopen(request, timeout=15) as response:
            if response.geturl() != url:
                raise ValueError("Source redirected to unauthorized URL")
            data = response.read(x["max_bytes"] + 1)
    if not data or len(data) > x["max_bytes"]:
        raise ValueError("Source exceeded read budget")
    digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if digest != x["sha"]:
        raise ValueError("Git blob content mismatch")
    obj = json.loads(data)
    if not isinstance(obj, dict):
        raise ValueError("Metadata must be object")
    return obj, hashlib.sha256(data).hexdigest()

def positive_int(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"Invalid {name}")
    return value

def describe(sport, obj):
    if sport=="CFB":
        markets=positive_int(obj["markets"],"markets")
        games=positive_int(obj["physical_games"],"games")
        return {"n_observed_contracts_in_catalog_snapshot":markets,
                "n_physical_games_in_catalog":games,
                "collector_complete":obj["capture_complete"] is True,
                "catalog_health":obj["health_state"]}
    if sport=="NFL":
        return {"n_open_contracts_in_observed_openset":positive_int(obj["n_open"],"n_open"),
                "snapshot_time":obj["observed_at"],
                "openset_schema":obj["schema_version"]}
    if sport=="NBA":
        return {"n_total_settlement_archive_records_reported":positive_int(obj["n_settlements_total"],"n_settlements_total"),
                "n_new_settlements_in_status_run":positive_int(obj["n_new_settlements"],"n_new_settlements"),
                "n_unsettleable_in_status_run":positive_int(obj["n_unsettleable"],"n_unsettleable"),
                "n_settlement_disagreements_reported":len(obj["disagreements"])}
    if sport=="NHL":
        return {"n_candidate_settlement_records_in_status_run":positive_int(obj["n_candidates"],"n_candidates"),
                "n_new_result_records_in_status_run":positive_int(obj["n_new_records"],"n_new_records"),
                "n_settlement_disagreements_reported":len(obj["disagreements"])}
    if sport=="MLB":
        counter=Counter()
        for key,row in obj.items():
            if not isinstance(row,dict) or row.get("date")!=key: raise ValueError("MLB date identity mismatch")
            value=row.get("outcome")
            if value not in ("completed","rejected_ineligible","not_applicable_no_decision","no_snapshot"):
                raise ValueError("Unrecognized replay status")
            counter[value]+=1
        return {"n_historical_replay_status_records":len(obj),
                "replay_status_breakdown":dict(sorted(counter.items()))}
    if sport=="CBB":
        families=obj["by_family"]
        if not isinstance(families,dict) or not families: raise ValueError("Missing contract family ontology")
        if sum(positive_int(x,"family contract count") for x in families.values())!=positive_int(obj["n_markets"],"n_markets"):
            raise ValueError("Family totals do not equal snapshot count")
        return {"n_market_contracts_in_snapshot":obj["n_markets"],
                "n_events_in_snapshot":positive_int(obj["n_events"],"n_events"),
                "n_game_winner_contracts":families.get("GAME_WINNER",0),
                "n_futures_other_contracts":families.get("FUTURES_OTHER",0)}
    if sport=="SOCCER":
        return {"n_mapped_fixtures_in_status":positive_int(obj["fixtures_mapped"],"fixtures_mapped"),
                "n_unpublished_lineups":positive_int(obj["lineups"]["unpublished"],"unpublished"),
                "source_health":obj["health"]["state"]}
    if sport=="TENNIS":
        counts=obj["counts"]
        return {"n_open_market_contracts_in_capture":positive_int(counts["open_markets"],"open_markets"),
                "n_changed_quotes_written":positive_int(counts["quotes_written"],"quotes_written"),
                "n_unchanged_quotes_reported":positive_int(counts["quotes_unchanged"],"quotes_unchanged"),
                "n_tennis_trades_reported":positive_int(counts["trades_tennis"],"trades_tennis")}
    raise ValueError("Unsupported sport")

def run(manifest, downloader=None):
    entries = manifest_entries(manifest)
    results=[]
    for x in entries:
        obj,sha256=read_pinned(x,downloader)
        results.append({
            "sport":x["sport"],"role":x["kind"],"status":"PINNED_METADATA_AUDITED",
            "source_commit":x["commit"],"source_blob_sha1":x["sha"],
            "source_sha256":sha256,"source_url":source_url(x),
            "indicators":describe(x["sport"],obj),
            "market_tape": "NOT_FULLY_RECONSTRUCTED",
            "game_outcome_join":"NOT_ESTABLISHED_BY_METADATA",
            "statistical_conclusion":"NONE",
        })
    return {"schema_version":1,"authority":"RESEARCH_ONLY","n_sports":len(results),
            "sources":results,
            "limitations":[
                "Metadata snapshots are heterogeneous and do not represent comparable sample denominators.",
                "All figures are per-source observed archival metadata, not unique independent bets or games.",
                "Full market-time-series, event rule, official outcome and orderbook joins need verification.",
                "No profitable patterns, predictive model improvements or live trades were proven by this audit.",
            ]}
