"""Bounded, tree-hash-verified CFB event-directory discovery for the dashboard.

This is one historical upstream *game-key directory*, not a full CFB board,
an as-of pregame capture, or an independent exchange settlement audit.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

from .market_family_registry import git_sha

REPO = "chmoses98/cfb-edge-finder"
COMMIT = "a244458a3cdf75f20f375f29ce23e2272f90f3f4"
DIRECTORY = "data/live/execution/games/26OCT30AUBMISS/events"
TREE_SHA = "06fc6fb1523d13f6636d50ea22353f46f96000b3"
MAX_FILES = 27
MAX_BYTES = 1_500_000
MAX_SINGLE_FILE = 140_000
# Pinned from the 27 source Git blobs; Git tree hashes commit blob IDs and names,
# but deliberately do NOT commit file sizes. A changed size must fail here,
# before fetching, even if the underlying Git tree hash is unchanged.
EXPECTED_TOTAL_BYTES = 1_183_059
EXPECTED_SIZE_VECTOR_SHA256 = "434ed07591d488ad497f4d57d6ea39105608c7955dd19789a224f3df545e94ec"
CODE_PATHS = [
    "src/cfb_edge_finder/modeling/score_model.py",
    "src/cfb_edge_finder/projections/distribution.py",
    "src/cfb_edge_finder/kalshi/market_pricing.py",
    "src/cfb_edge_finder/kalshi/contract_semantics.py",
]
HYPOTHESIS = "CAUSAL_HYPOTHESIS_NOT_EMPIRICALLY_VALIDATED"
# Independent pinned source evidence: this is ONE generic full-game pricer,
# not a complete audit of all CFB pricing routes or of actual forecasts.
PRICER_PATH = "src/cfb_edge_finder/projections/distribution.py"
PRICER_BLOB_SHA1 = "7d73b0edce9dcc6ccdfb2375f001a1838f55a80e"
PRICER_MAX_BYTES = 12_000


def verify_generic_pricer(loader=None):
    """Verify pinned upstream source and its explicit first-half rejection."""
    if loader is None:
        url = "https://raw.githubusercontent.com/" + REPO + "/" + COMMIT + "/" + PRICER_PATH
        def loader():
            with urlopen(Request(url, headers={"User-Agent": "SIFT-Alpha-cfb-model-lineage/1"}), timeout=15) as response:
                if response.geturl() != url:
                    raise ValueError("Unapproved model source redirect")
                return response.read(PRICER_MAX_BYTES + 1)
    raw = loader()
    if not isinstance(raw, bytes) or len(raw) > PRICER_MAX_BYTES or git_sha(raw) != PRICER_BLOB_SHA1:
        raise ValueError("CFB model source missing, oversized or hash mismatch")
    source = raw.decode("utf-8")
    tree = ast.parse(source)
    families = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "_FIRST_HALF_FAMILIES"
                for target in node.targets):
            families = {part.attr for part in ast.walk(node.value)
                        if isinstance(part, ast.Attribute)
                        and isinstance(part.value, ast.Name) and part.value.id == "MarketFamily"}
    expected = {"FIRST_HALF_MONEYLINE", "FIRST_HALF_SPREAD", "FIRST_HALF_TOTAL"}
    if families != expected:
        raise ValueError("Pinned generic pricer first-half family contract changed")
    pricing = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "price_market"), None)
    if pricing is None:
        raise ValueError("Missing generic price_market function")
    def explicit_rejection(node):
        t = node.test
        return (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name)
                and t.left.id == "market_family" and len(t.ops) == 1
                and isinstance(t.ops[0], ast.In) and len(t.comparators) == 1
                and isinstance(t.comparators[0], ast.Name)
                and t.comparators[0].id == "_FIRST_HALF_FAMILIES"
                and any(isinstance(x, ast.Raise) and isinstance(x.exc, ast.Call)
                        and isinstance(x.exc.func, ast.Name)
                        and x.exc.func.id == "UnsupportedMarketFamilyError"
                        for statement in node.body for x in ast.walk(statement)))
    if not any(isinstance(node, ast.If) and explicit_rejection(node)
               for node in ast.walk(pricing)):
        raise ValueError("Generic pricer does not explicitly reject first-half markets")
    return {"repository": REPO, "commit": COMMIT, "path": PRICER_PATH,
            "source_git_blob_sha1": PRICER_BLOB_SHA1,
            "verified_scope": "GENERIC_GAME_DISTRIBUTION_PRICER_ONLY",
            "first_half_capability": "EXPLICIT_UNSUPPORTED_MARKET_FAMILY",
            "all_other_pricing_routes_audited": False}




def tree_sha(files):
    # Git's tree encoding, not a hash of JSON or the directory listing API.
    raw = b"".join(
        b"100644 " + x["name"].encode() + b"\0" + bytes.fromhex(x["sha"])
        for x in sorted(files, key=lambda v: v["name"].encode())
    )
    return hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def check_manifest(m):
    if (m.get("schema_version") != 1 or m.get("source_repository") != REPO
            or m.get("source_commit") != COMMIT or m.get("directory") != DIRECTORY
            or m.get("directory_tree_sha1") != TREE_SHA):
        raise ValueError("Unexpected source tree or repository")
    files = m.get("files")
    if not isinstance(files, list) or len(files) != MAX_FILES:
        raise ValueError("Incomplete or unbounded event directory")
    names = set()
    total = 0
    for entry in files:
        if (not isinstance(entry, dict) or set(entry) != {"name", "sha", "size"}
                or not isinstance(entry["name"], str)
                or not re.fullmatch(r"KXNCAAF[A-Z0-9]+-26OCT3[01]AUBMISS\.json", entry["name"])
                or entry["name"] in names
                or not isinstance(entry["sha"], str)
                or not re.fullmatch("[a-f0-9]{40}", entry["sha"])
                or type(entry["size"]) is not int or not 0 < entry["size"] <= MAX_SINGLE_FILE):
            raise ValueError("Invalid, duplicate or oversized manifest entry")
        names.add(entry["name"])
        total += entry["size"]
    ordered = sorted(files, key=lambda x: x["name"].encode())
    size_vector = ",".join(str(x["size"]) for x in ordered).encode("ascii")
    if (total != EXPECTED_TOTAL_BYTES
            or hashlib.sha256(size_vector).hexdigest() != EXPECTED_SIZE_VECTOR_SHA256
            or tree_sha(files) != TREE_SHA):
        raise ValueError("Incomplete or altered Git directory tree or source byte sizes")
    return sorted(files, key=lambda x: x["name"])


def download(entry):
    url = "https://raw.githubusercontent.com/" + REPO + "/" + COMMIT + "/" + DIRECTORY + "/" + entry["name"]
    with urlopen(Request(url, headers={"User-Agent": "SIFT-Alpha-cfb-shard-audit/1"}), timeout=15) as response:
        if response.geturl() != url:
            raise ValueError("Unapproved source redirect")
        return response.read(entry["size"] + 1)


def verified_shards(manifest, loader=download):
    result = []
    for entry in check_manifest(manifest):
        raw = loader(entry)
        if (not isinstance(raw, bytes) or len(raw) != entry["size"]
                or git_sha(raw) != entry["sha"]):
            raise ValueError("Source blob missing, truncated or altered: " + entry["name"])
        result.append((entry, json.loads(raw), hashlib.sha256(raw).hexdigest()))
    return result


def _candidate(name, transformation, distribution, key_numbers):
    return {"name": name, "transformation": transformation,
            "distribution": distribution, "key_number_effect": key_numbers,
            "evidence": HYPOTHESIS, "historical_source": None,
            "available_at": None, "model_used": "UNKNOWN",
            "validated_predictive_impact": None}


def hypotheses(family, period):
    # Hypotheses are deliberately NOT requirements, collected inputs, or
    # measured improvements. No first-quarter pace is claimed in the model.
    if "total" in family:
        return [
            _candidate("period_specific_possessions_and_pace",
                       "opponent_adjusted_drives_and_expected_plays_by_period",
                       "period_score_joint_distribution", "football_scoring_increments_and_half_point_strikes"),
            _candidate("period_specific_scoring_efficiency_and_kicking",
                       "opponent_adjusted_drive_outcomes_and_field_goal_range",
                       "period_score_joint_distribution", "3_7_10_14_17_21_point_masses"),
        ]
    if "spread" in family or "moneyline" in family:
        return [
            _candidate("opponent_adjusted_margin_and_game_state",
                       "home_away_strength_and_period_specific_score_difference",
                       "discrete_margin_distribution", "3_7_10_14_point_margin_masses"),
        ]
    if "stat_prop" in family or "touchdown" in family:
        return [
            _candidate("event_opportunity_and_identity",
                       "play_type_frequency_opponent_scheme_and_verified_participants",
                       "count_or_first_event_distribution", "integer_touchdown_thresholds"),
        ]
    return []


def _rule_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def audit(shards, *, model_evidence=None):
    if not shards or len(shards) > MAX_FILES:
        raise ValueError("Empty or unbounded source shards")
    if model_evidence is not None and (
            model_evidence.get("source_git_blob_sha1") != PRICER_BLOB_SHA1
            or model_evidence.get("verified_scope") != "GENERIC_GAME_DISTRIBUTION_PRICER_ONLY"
            or model_evidence.get("first_half_capability") != "EXPLICIT_UNSUPPORTED_MARKET_FAMILY"):
        raise ValueError("Unrecognized model-lineage evidence")
    all_tickers = set()
    all_events = set()
    rows = []
    by_family = Counter()
    date_labels = Counter()
    fingerprint = None
    for entry, shard, digest in shards:
        if not isinstance(shard, dict) or shard.get("artifact") != "event_detail_shard":
            raise ValueError("Not a real event-detail shard")
        event = shard.get("event")
        markets = shard.get("markets")
        if not isinstance(event, dict) or not isinstance(markets, list) or not markets:
            raise ValueError("Missing event or markets")
        event_ticker = event.get("event_ticker")
        series = event.get("series_ticker")
        if (not isinstance(event_ticker, str) or not isinstance(series, str)
                or event_ticker != shard.get("event_ticker")
                or not event_ticker.startswith(series + "-")
                or entry["name"] != event_ticker + ".json"
                or event_ticker in all_events
                or shard.get("game_key") != "26OCT30AUBMISS"
                or not isinstance(shard.get("game_fingerprint"), str)
                or not shard["game_fingerprint"]
                or type(shard.get("market_count")) is not int
                or shard["market_count"] != len(markets)
                or shard.get("event_market_count") != len(markets)
                or shard.get("part") != 1 or shard.get("parts") != 1):
            raise ValueError("Event identity, pagination or denominator mismatch")
        all_events.add(event_ticker)
        if fingerprint is None:
            fingerprint = shard["game_fingerprint"]
        elif fingerprint != shard["game_fingerprint"]:
            raise ValueError("Cross-game fingerprint mixed into one directory")
        date = event_ticker.split("-")[1][:7]
        date_labels[date] += 1
        contracts = []
        groups = set()
        for market in markets:
            if not isinstance(market, dict):
                raise ValueError("Malformed market")
            ticker = market.get("market_ticker")
            family = market.get("family")
            period = market.get("period")
            strike = market.get("strike_type")
            primary = market.get("rules_primary")
            secondary = market.get("rules_secondary")
            floor = market.get("floor_strike")
            if (not isinstance(ticker, str) or not ticker.startswith(event_ticker + "-")
                    or ticker in all_tickers or market.get("event_ticker") != event_ticker
                    or market.get("series_ticker") != series
                    or market.get("market_type") != "binary"
                    or not all(isinstance(v, str) and v for v in (family, period, strike, primary, secondary))
                    or (floor is not None and (type(floor) not in (float, int) or not -1000 <= floor <= 1000))):
                raise ValueError("Duplicate contract, semantic or market identity conflict")
            all_tickers.add(ticker)
            groups.add((family, period, strike))
            contracts.append({
                "ticker": ticker, "event_ticker": event_ticker,
                "family": family, "period": period, "strike_type": strike,
                "floor_strike": floor, "is_alternate_line": market.get("is_alternate_line"),
                "rules_primary_sha256": _rule_sha(primary),
                "rules_secondary_sha256": _rule_sha(secondary),
                "upstream_updated_time_not_capture_clock": market.get("updated_time"),
            })
        # Fail closed rather than silently collapsing multiple mechanisms.
        if len(groups) != 1:
            raise ValueError("Mixed family/period/strike semantics inside event shard")
        family, period, strike = next(iter(groups))
        by_family[(family, period)] += len(markets)
        sample = markets[0]
        rows.append({
            "sport": "CFB", "family": "SHARD:" + series,
            "native_market_family": family, "period": period, "strike_type": strike,
            "literal_series_ticker": series, "literal_event_ticker": event_ticker,
            "observation_scope": "PINNED_AUBMISS_EVENT_DIRECTORY_ONLY",
            "observed_denominator": len(contracts), "denominator_unit": "contracts_in_one_verified_event_shard",
            "source_reported_model_evaluated": None, "independently_valid_evaluations": None,
            "source_reported_settled": None,
            "source_repository": REPO, "source_commit": COMMIT,
            "source_blob_sha1": entry["sha"], "source_sha256": digest,
            "source_file_path": DIRECTORY + "/" + entry["name"],
            "source_code_paths": CODE_PATHS,
            "observed_at_utc": None,
            "historical_availability": "ARCHIVE_CAPTURE_CLOCK_UNKNOWN_NOT_PIT_VERIFIED",
            "market_collection_status": "COLLECTED_VALID",
            "input_collection_status": "UNKNOWN",
            "model_usage_status": "UNKNOWN",
            "model_version_and_calibration": "UNKNOWN",
            "generic_pricer_capability": (
                "EXPLICIT_UNSUPPORTED_FIRST_HALF_ONLY" if model_evidence is not None
                and period == "first_half" else "UNKNOWN"),
            "generic_pricer_evidence": (
                model_evidence if model_evidence is not None and period == "first_half" else None),
            "source_provider_independence": "KALSHI_DERIVED_ARCHIVE_NOT_INDEPENDENTLY_VERIFIED",
            "exact_settlement_rule_status": "ARCHIVED_LITERAL_RULE_TEXT_NOT_SETTLEMENT_VERIFICATION",
            "rule_text_sample": {"primary": sample["rules_primary"], "secondary": sample["rules_secondary"],
                                 "sample_ticker": sample["market_ticker"]},
            "settlement_outcome_join": "UNKNOWN",
            "projected_outcome": "CONTRACT_SPECIFIC_BINARY_EVENT_AS_LITERAL_RULE_TEXT",
            "candidate_inputs": hypotheses(family, period),
            "point_in_time_pregame_eligibility": "UNKNOWN",
            "full_checkpoint_delta_replay": "NOT_ESTABLISHED_SINGLE_EVENT_SHARD",
            "physical_game_join": "UNVERIFIED_EVENT_DATE_CONFLICT",
            "observed_contracts": contracts,
        })
    if sum(r["observed_denominator"] for r in rows) != len(all_tickers):
        raise ValueError("Observed ticker denominator mismatch")
    return {
        "n_event_shards": len(rows),
        "n_distinct_literal_events": len(all_events),
        "n_distinct_literal_series": len({r["literal_series_ticker"] for r in rows}),
        "n_distinct_market_tickers": len(all_tickers),
        "n_native_family_period_groups": len(by_family),
        "native_family_period_counts": [
            {"family": family, "period": period, "n_contracts": count}
            for (family, period), count in sorted(by_family.items())
        ],
        "event_date_labels": dict(sorted(date_labels.items())),
        "game_key": "26OCT30AUBMISS",
        "actual_game_start_verified": False,
        "event_date_vs_game_key_conflict": len(date_labels) > 1,
        "archive_capture_clock_verified": False,
        "settlement_join_verified": False,
        "full_cfb_market_coverage_verified": False,
        "rows": rows,
    }


def append(base, audited):
    if (base.get("authority") != "RESEARCH_ONLY_NOT_LIVE_COLLECTION"
            or base.get("live_capture_running") is not False
            or base.get("all_market_families_certified") is not False
            or base.get("schema_version") != 2
            or "cfb_event_shard_audit" in base):
        raise ValueError("Untrusted or already expanded dashboard artifact")
    result = json.loads(json.dumps(base))
    for row in audited["rows"]:
        result["family_rows"].append(row)
        result["missing_input_queue"].append({
            "sport": "CFB", "family": row["family"],
            "scope": row["observation_scope"],
            "denominator": row["observed_denominator"],
            "denominator_unit": row["denominator_unit"],
            "missing": ["INDEPENDENT_ACTUAL_START_AND_PIT_CAPTURE",
                        "FORECAST_TO_MARKET_LINEAGE_AND_MODEL_USE",
                        "INDEPENDENT_OUTCOME_AND_SETTLEMENT_JOIN",
                        "PERIOD_SPECIFIC_PACE_SOURCE_VERIFICATION"],
            "source_commit": COMMIT,
            "source_blob_sha1": row["source_blob_sha1"],
            "priority_authority": "HISTORICAL_DIRECTORY_ONLY",
        })
    result["cfb_event_shard_audit"] = {k: v for k, v in audited.items() if k != "rows"}
    result["all_market_families_certified"] = False
    result["live_capture_running"] = False
    return result


def main():
    manifest = json.loads(Path("research/cfb_aubmiss_event_shards.json").read_text())
    data = audit(verified_shards(manifest), model_evidence=verify_generic_pricer())
    target = Path("public/market-family-input-coverage.json")
    result = append(json.loads(target.read_text()), data)
    target.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print("Verified CFB event-directory:", data["n_event_shards"], "shards,",
          data["n_distinct_market_tickers"], "literal tickers,",
          data["n_native_family_period_groups"], "native family/period groups.")
    print("Not a pregame capture, full CFB board, verified start, forecast or settlement join.")


if __name__ == "__main__":
    main()
