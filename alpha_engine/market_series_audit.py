"""Source-verified literal Kalshi series inventory for the NBA/NHL tape prefix.

A series ticker is a discovered exchange grouping, NOT a certified settlement
family or a physical game. Only the existing pinned checkpoint+delta replay
may supply observations. No forecasts, fills or profitability are inferred.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

from .schedule_timeline import verified_tape_ticks
from .verified_chains import check_manifest
from .contract_lineage import _validate


def _utc(value):
    if not isinstance(value, str):
        raise ValueError("Missing observation clock")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise ValueError("Observation clock must be UTC")
    return dt


def audit_series(tape, observations, manifest, *, verify=verified_tape_ticks):
    """Audit all unique observed tickers; quarantine ambiguous series identities."""
    chains = check_manifest(manifest)
    if tape.get("authority") != "RESEARCH_ONLY" or tape.get("full_day_or_season") is not False:
        raise ValueError("Not a bounded verified research tape")
    if set(tape.get("sports", {})) != set(chains):
        raise ValueError("Tape/manifest sport mismatch")
    if not isinstance(observations, list) or not 0 < len(observations) <= 120000:
        raise ValueError("Missing or unbounded tape")
    verify(observations, tape)  # source paths, tick clocks, hash and tick completeness
    histories = defaultdict(list)
    for observation in observations:
        _validate(observation)
        sport = observation.get("sport")
        if sport not in chains:
            raise ValueError("Unexpected sport")
        ticker = observation.get("ticker")
        if not isinstance(ticker, str) or not ticker:
            raise ValueError("Invalid literal ticker")
        _utc(observation.get("observed_at_utc"))
        histories[(sport, ticker)].append(observation)
    by_sport = {}
    for sport, chain in sorted(chains.items()):
        window = tape["sports"][sport]
        allowed = {(x["path"], x["sha"]) for x in [chain["checkpoint"], *chain["deltas"]]}
        if {(x["path"], x["blob_sha1"]) for x in window["source_files"]} != allowed:
            raise ValueError("Tape provenance differs from immutable manifest")
        grouped = defaultdict(list)
        quarantined = []
        unique = [(ticker, rows) for (s, ticker), rows in histories.items() if s == sport]
        for ticker, rows in sorted(unique):
            rows.sort(key=lambda x: _utc(x["observed_at_utc"]))
            if len({_utc(r["observed_at_utc"]) for r in rows}) != len(rows):
                raise ValueError("Duplicate ticker in one observation tick")
            if any((r["source_path"], r["source_blob_sha1"]) not in allowed for r in rows):
                raise ValueError("Unpinned observation provenance")
            if _utc(rows[0]["observed_at_utc"]) < _utc(window["base_at"]) or _utc(rows[-1]["observed_at_utc"]) > _utc(window["last_verified_at"]):
                raise ValueError("Observation outside verified window")
            series = set()
            for r in rows:
                terms = r["contract_terms_as_observed"]
                if terms is not None:
                    literal = terms.get("series_ticker")
                    if isinstance(literal, str) and literal:
                        series.add(literal)
            if len(series) != 1:
                quarantined.append({"ticker": ticker, "reason": "CONFLICTING_OR_MISSING_LITERAL_SERIES"})
                continue
            if rows[-1]["lifecycle"] == "REMOVED":
                lifecycle = "REMOVED_AT_PREFIX_END"
            else:
                lifecycle = "PRESENT_AT_PREFIX_END"
            grouped[next(iter(series))].append({
                "ticker": ticker, "lifecycle": lifecycle,
                "first_observed_at_utc": rows[0]["observed_at_utc"],
                "last_ticker_observed_at_utc": rows[-1]["observed_at_utc"],
                "n_observations": len(rows),
                "source_paths": sorted({r["source_path"] for r in rows}),
                "sample_terms": next((r["contract_terms_as_observed"] for r in rows if r["contract_terms_as_observed"] is not None), {}),
            })
        n_classified = sum(len(v) for v in grouped.values())
        if n_classified + len(quarantined) != len(unique):
            raise ValueError("Ticker denominator reconciliation failed")
        entries = []
        for series, contracts in sorted(grouped.items()):
            first = min(_utc(c["first_observed_at_utc"]) for c in contracts)
            entries.append({
                "sport": sport, "family": "SERIES:" + series,
                "literal_series_ticker": series,
                "observation_scope": "VERIFIED_2026_10_25_CHECKPOINT_PLUS_THREE_DELTAS",
                "observed_denominator": len(contracts),
                "denominator_unit": "distinct_tickers_in_verified_prefix",
                "present_at_prefix_end": sum(c["lifecycle"] == "PRESENT_AT_PREFIX_END" for c in contracts),
                "source_reported_model_evaluated": None,
                "independently_valid_evaluations": None,
                "source_reported_settled": None,
                "source_repository": chain["repository"],
                "source_commit": chain["commit"],
                "source_blobs": window["source_files"],
                "source_code_paths": [
                    "alpha_engine/verified_chains.py",
                    "alpha_engine/verified_tape.py",
                    "alpha_engine/market_series_audit.py",
                ],
                "observed_at_utc": first.isoformat().replace("+00:00", "Z"),
                "last_verified_board_tick_utc": window["last_verified_at"],
                "market_collection_status": "COLLECTED_VALID",
                "model_usage_status": "UNKNOWN",
                "input_collection_status": "UNKNOWN",
                "exact_settlement_rule_status": "UNKNOWN_NO_INDEPENDENT_CONTRACT_RULES",
                "settlement_outcome_join": "UNKNOWN",
                "projected_outcome": None,
                "candidate_inputs": [],
                "sample_contract": {
                    "ticker": contracts[0]["ticker"],
                    "terms_as_observed": contracts[0]["sample_terms"],
                    "last_ticker_observed_at_utc": contracts[0]["last_ticker_observed_at_utc"],
                },
                "historical_availability": "VERIFIED_BOARD_OBSERVATION_ONLY_NOT_FORECAST_AVAILABILITY",
                "source_provider_independence": "NOT_INDEPENDENTLY_VERIFIED",
                "point_in_time_pregame_eligibility": "UNKNOWN",
                "full_checkpoint_delta_replay": "VERIFIED_PREFIX_ONLY",
            })
        by_sport[sport] = {
            "n_unique_tickers_in_prefix": len(unique),
            "n_tickers_with_literal_series": n_classified,
            "n_tickers_quarantined": len(quarantined),
            "quarantined_examples": quarantined[:10],
            "n_literal_series": len(entries),
            "series_rows": entries,
            "prefix_only": True,
        }
    return by_sport


def combine(matrix, audited):
    if matrix.get("authority") != "RESEARCH_ONLY_NOT_LIVE_COLLECTION" or matrix.get("all_market_families_certified") is not False:
        raise ValueError("Original evidence matrix has unsupported authority")
    if set(audited) != {"NBA", "NHL"}:
        raise ValueError("Only pinned NBA/NHL tape supported")
    # Retain original source-native rows; they are not interchangeable with the
    # additional distinct-ticker series denominator.
    result = json.loads(json.dumps(matrix))
    result["schema_version"] = 2
    result["literal_series_audit"] = {
        sport: {k: v for k, v in row.items() if k != "series_rows"}
        for sport, row in audited.items()
    }
    for sport, audit in audited.items():
        for r in audit["series_rows"]:
            result["family_rows"].append(r)
            result["missing_input_queue"].append({
                "sport": sport, "family": r["family"],
                "scope": r["observation_scope"],
                "denominator": r["observed_denominator"],
                "denominator_unit": r["denominator_unit"],
                "missing": ["EXACT_CONTRACT_SETTLEMENT_RULES", "SPORT_SPECIFIC_INPUT_LINEAGE",
                            "IMMUTABLE_PREGAME_FORECAST_JOIN", "INDEPENDENT_GAME_START_AND_OUTCOME"],
                "priority_authority": "HISTORICAL_PREFIX_ONLY",
                "source_commit": r["source_commit"],
            })
    result["discovered_literal_series_count"] = sum(x["n_literal_series"] for x in audited.values())
    result["literal_series_are_not_certified_market_families"] = True
    result["dashboard_data_source"] = "CI_VERIFIED_PINNED_ARCHIVES_NOT_LIVE"
    result["live_capture_running"] = False
    result["all_market_families_certified"] = False
    return result


def main():
    base = json.loads(Path("artifacts/market_family_input_coverage.json").read_text())
    tape = json.loads(Path("artifacts/verified_sparse_tape_status.json").read_text())
    manifest = json.loads(Path("research/verified_chain_pilot.json").read_text())
    with gzip.open("artifacts/verified_sparse_quote_tape.jsonl.gz", "rt", encoding="utf-8") as f:
        observations = [json.loads(line) for line in f]
    audited = audit_series(tape, observations, manifest)
    result = combine(base, audited)
    target = Path("public/market-family-input-coverage.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    for sport, row in audited.items():
        print(sport, "literal series", row["n_literal_series"],
              "classified", row["n_tickers_with_literal_series"],
              "quarantined", row["n_tickers_quarantined"])
    print("Research-only dashboard artifact:", target)


if __name__ == "__main__":
    main()
