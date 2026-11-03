"""Verified prospective open-series capture -> market-first dashboard row.

Only consumes immutable pages already collected by explicit opt-in. No network
requests, forecast inference, actual-start inference, or settlement promotion.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .series_pagination import verify_capture

SPORTS = {"NFL", "CFB", "NBA", "NHL", "CBB", "MLB", "SOCCER", "TENNIS"}


def _utc(value):
    if not isinstance(value, str):
        raise ValueError("Missing source receipt clock")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Malformed source receipt clock") from exc
    if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError("Non-UTC source receipt clock")
    return dt


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if isinstance(value, str) else None


def audit_capture(directory, manifest, sport):
    if sport not in SPORTS:
        raise ValueError("Unsupported sport")
    verified = verify_capture(directory, manifest)
    series = manifest["series"]
    rows, tickers, clocks = [], set(), []
    for page in manifest["pages"]:
        clock = _utc(page["received_at_utc"])
        clocks.append(clock)
        source_path = str(Path(series) / page["file"])
        source = json.loads((Path(directory) / source_path).read_bytes())
        for contract in source["markets"]:
            ticker = contract["ticker"]
            if ticker in tickers:
                raise ValueError("Duplicate contract across original pages")
            tickers.add(ticker)
            rules_primary, rules_secondary = contract.get("rules_primary"), contract.get("rules_secondary")
            if any(v is not None and not isinstance(v, str) for v in (rules_primary, rules_secondary)):
                raise ValueError("Malformed literal contract rule text")
            rows.append({
                "ticker": ticker,
                "literal_event_ticker": contract.get("event_ticker"),
                "title": contract.get("title"),
                "strike_type": contract.get("strike_type"),
                "floor_strike": contract.get("floor_strike"),
                # Preserve literal market mechanism fields; these are exchange
                # claims at receipt, not independently verified settlements.
                "cap_strike": contract.get("cap_strike"),
                "yes_sub_title": contract.get("yes_sub_title"),
                "no_sub_title": contract.get("no_sub_title"),
                "expiration_time": contract.get("expiration_time"),
                "close_time": contract.get("close_time"),
                "expected_expiration_time": contract.get("expected_expiration_time"),
                "status_at_receipt": contract.get("status"),
                "result_at_receipt_unverified": contract.get("result"),
                "settlement_value_at_receipt_unverified": contract.get("settlement_value"),
                "rules_primary_sha256": _sha(rules_primary),
                "rules_secondary_sha256": _sha(rules_secondary),
                "rules_primary": rules_primary,
                "rules_secondary": rules_secondary,
                "literal_rule_text_available": bool(rules_primary and rules_secondary),
                "source_page_sha256": page["sha256"],
                "source_page_path": source_path,
                "source_received_at_utc": page["received_at_utc"],
                "source_http_date_unverified": page["server_date"],
            })
    if len(tickers) != verified["observed_denominator"]:
        raise ValueError("Capture denominator mismatch")
    if any(a > b for a, b in zip(clocks, clocks[1:])):
        raise ValueError("Page receipt clocks moved backward")
    captured = _utc(manifest["captured_at_utc"])
    # The requested capture clock is NOT a trustworthy exchange observation
    # clock. A future request timestamp must not masquerade as past evidence.
    if captured > clocks[0]:
        raise ValueError("Requested capture clock later than first receipt")
    page_names = [x["file"] for x in manifest["pages"]]
    if len(page_names) != len(set(page_names)):
        raise ValueError("Reused immutable page path")
    return {
        "sport": sport, "family": "CAPTURE:" + series + "@" + manifest["captured_at_utc"],
        "literal_series_ticker": series,
        "observation_scope": "OPT_IN_PUBLIC_OPEN_SERIES_PAGES_ONLY",
        "observed_denominator": len(rows),
        "denominator_unit": "distinct_tickers_in_this_verified_capture",
        "source_reported_model_evaluated": None,
        "independently_valid_evaluations": None,
        "source_reported_settled": None,
        "source_repository": "KALSHI_PUBLIC_API_NOT_GIT_PINNED",
        "source_commit": None,
        "source_url": manifest["source_url"],
        "source_page_sha256": [p["sha256"] for p in manifest["pages"]],
        "source_code_paths": [
            "alpha_engine/free_market_capture.py",
            "alpha_engine/series_pagination.py",
            "alpha_engine/series_inventory_bridge.py",
        ],
        "observed_at_utc": clocks[0].isoformat().replace("+00:00", "Z"),
        "last_page_received_at_utc": clocks[-1].isoformat().replace("+00:00", "Z"),
        "capture_requested_at_utc": manifest["captured_at_utc"],
        "market_collection_status": "COLLECTED_VALID",
        "input_collection_status": "UNKNOWN",
        "model_usage_status": "UNKNOWN",
        "model_version_and_calibration": "UNKNOWN",
        "historical_availability": "SOURCE_RECEIPT_CLOCK_ONLY_NO_FORECAST_JOIN",
        "source_provider_independence": "KALSHI_PUBLIC_API_ORIGINAL_PAGES",
        "exact_settlement_rule_status": (
            "LITERAL_RULES_CAPTURED_NOT_INDEPENDENTLY_VERIFIED"
            if all(x["literal_rule_text_available"] for x in rows) and rows
            else "UNKNOWN_PARTIAL_OR_MISSING_LITERAL_RULES"),
        "settlement_outcome_join": "UNKNOWN",
        "projected_outcome": None,
        "candidate_inputs": [],
        "point_in_time_pregame_eligibility": "UNKNOWN",
        "full_checkpoint_delta_replay": "NOT_ESTABLISHED_SINGLE_OPEN_SERIES_CAPTURE",
        "pagination": manifest["pagination"],
        "all_reported_pages_retrieved": verified["all_reported_pages_retrieved"],
        "complete_series_or_market_tape": False,
        "observed_contracts": rows,
    }


def append(matrix, row):
    if (matrix.get("authority") != "RESEARCH_ONLY_NOT_LIVE_COLLECTION"
            or matrix.get("live_capture_running") is not False
            or matrix.get("all_market_families_certified") is not False
            or not isinstance(matrix.get("family_rows"), list)
            or not isinstance(matrix.get("missing_input_queue"), list)
            or row.get("sport") not in SPORTS
            or row.get("observation_scope") != "OPT_IN_PUBLIC_OPEN_SERIES_PAGES_ONLY"):
        raise ValueError("Untrusted dashboard matrix or capture")
    if any(x["sport"] == row["sport"] and x["family"] == row["family"]
           for x in matrix["family_rows"]):
        raise ValueError("Capture already added")
    result = json.loads(json.dumps(matrix))
    result["family_rows"].append(row)
    result["missing_input_queue"].append({
        "sport": row["sport"], "family": row["family"],
        "scope": row["observation_scope"],
        "denominator": row["observed_denominator"],
        "denominator_unit": row["denominator_unit"],
        "missing": [
            "PREGAME_GAME_START_AND_HISTORICAL_AVAILABILITY",
            "SPORT_REPO_INGESTION_FEATURE_MODEL_OUTPUT_JOIN",
            "INDEPENDENT_OUTCOME_AND_SETTLEMENT",
            "CALIBRATED_FORECAST_DISTRIBUTION",
            *([] if row["all_reported_pages_retrieved"] else ["REMAINING_SERIES_PAGES"]),
        ],
        "priority_authority": "OBSERVED_CAPTURE_ONLY_NO_MODEL_VALIDATION",
        "source_page_sha256": row["source_page_sha256"],
    })
    result["live_capture_running"] = False
    result["all_market_families_certified"] = False
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Offline audit of original, explicitly captured public pages")
    p.add_argument("--root", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--sport", required=True, choices=sorted(SPORTS))
    p.add_argument("--matrix", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    m = json.loads(Path(args.manifest).read_text())
    row = audit_capture(args.root, m, args.sport)
    result = append(json.loads(Path(args.matrix).read_text()), row)
    target = Path(args.out)
    if target.resolve() == Path(args.matrix).resolve():
        raise ValueError("Refuse to overwrite existing historical audit artifact")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"sport": args.sport, "contracts": row["observed_denominator"],
                      "pages": len(m["pages"]), "full_series_tape": False,
                      "output": str(target)}, sort_keys=True))
