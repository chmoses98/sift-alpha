"""Fail-closed market-family inventory from *actual pinned* eight-sport evidence.

Rows use source-native denominators. CBB is a coarse snapshot family breakdown,
MLB is historical opportunity rows, and CFB 1Q is one event shard; none are
summable into a universal contract count. Missing market families stay UNKNOWN.
This module never fetches unpinned current markets or certifies model quality.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from .all_sport_evidence import ALLOWED, manifest_entries, read_pinned, describe
from .sports_quality_evidence import check_sources, read as read_quality, audit_mlb
from .research_scheduler import WEIGHTS

CFB_REPO = "chmoses98/cfb-edge-finder"
CFB_COMMIT = "a244458a3cdf75f20f375f29ce23e2272f90f3f4"
CFB_PATH = "data/live/execution/games/26OCT30AUBMISS/events/KXNCAAF1QTOTAL-26OCT31AUBMISS.json"
CFB_SHA1 = "258bb81260d63b5d29b24fe1a298a747d269ca17"
CFB_MAX_BYTES = 50000
SPORTS = tuple(WEIGHTS)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp missing or invalid")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError("Explicit UTC required")
    return dt.astimezone(timezone.utc)


def git_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def cfb_source(downloader=None):
    url = f"https://raw.githubusercontent.com/{CFB_REPO}/{CFB_COMMIT}/{CFB_PATH}"
    if downloader is None:
        with urlopen(Request(url, headers={"User-Agent": "SIFT-Alpha-family-audit/1"}), timeout=15) as response:
            if response.geturl() != url:
                raise ValueError("Unapproved redirect")
            raw = response.read(CFB_MAX_BYTES + 1)
    else:
        raw = downloader()
    if not isinstance(raw, bytes) or not 0 < len(raw) <= CFB_MAX_BYTES or git_sha(raw) != CFB_SHA1:
        raise ValueError("CFB event shard missing, oversized, or hash mismatch")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def cfb_quarter_total(shard):
    """Only one *sampled event*, never the whole 13k-contract catalog."""
    if not isinstance(shard, dict) or shard.get("artifact") != "event_detail_shard":
        raise ValueError("CFB event shard artifact missing")
    event = shard.get("event", {})
    markets = shard.get("markets")
    if (not isinstance(event, dict) or event.get("series_ticker") != "KXNCAAF1QTOTAL"
            or event.get("event_ticker") != "KXNCAAF1QTOTAL-26OCT31AUBMISS"
            or not isinstance(markets, list) or not markets
            or type(shard.get("market_count")) is not int
            or shard["market_count"] != len(markets)
            or shard.get("event_market_count") != len(markets)):
        raise ValueError("CFB event-shard count/identity mismatch")
    tickers = set()
    for market in markets:
        if not isinstance(market, dict):
            raise ValueError("Invalid CFB market")
        ticker = market.get("market_ticker")
        if (not isinstance(ticker, str) or not ticker.startswith(event["event_ticker"] + "-")
                or ticker in tickers or market.get("event_ticker") != event["event_ticker"]
                or market.get("family") != "quarter_total"
                or market.get("period") != "first_quarter"
                or market.get("market_type") != "binary"
                or market.get("strike_type") != "greater"
                or type(market.get("floor_strike")) not in (int, float)
                or not 0 <= market["floor_strike"] <= 150
                or not isinstance(market.get("rules_primary"), str)
                or "1st quarter" not in market["rules_primary"].lower()
                or not isinstance(market.get("rules_secondary"), str)
                or "48 hours" not in market["rules_secondary"]
                or "fair price" not in market["rules_secondary"]):
            raise ValueError("CFB 1Q exact contract terms missing or inconsistent")
        tickers.add(ticker)
    return {
        "observed": len(markets),
        "denominator_unit": "contracts_in_one_event_shard",
        "sample_ticker": sorted(tickers)[0],
        "sample_rule_primary": next(x["rules_primary"] for x in markets if x["market_ticker"] == sorted(tickers)[0]),
        "sample_rule_secondary": markets[0]["rules_secondary"],
        "rule_text_status": "ARCHIVED_LITERAL_UNVERIFIED_SETTLEMENT",
        "projected_outcome": "first_quarter_combined_points_greater_than_contract_strike",
        "market_capture_at_utc": None,
    }


def row(sport, family, source, *, observed=None, unit="UNKNOWN",
        evaluated=None, settled=None, observed_at=None, scope="UNVERIFIED",
        rule_status="NOT_RECONSTRUCTED", projected_outcome=None,
        candidate_inputs=None, model_status="UNVERIFIED", rule_sample=None):
    if sport not in ALLOWED or not isinstance(family, str) or not family:
        raise ValueError("Unsupported sport/family")
    for count in (observed, evaluated, settled):
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError("Invalid denominator or numerator")
    if observed is not None and (evaluated is not None and evaluated > observed
                                 or settled is not None and settled > observed):
        raise ValueError("Numerator exceeds original observed denominator")
    return {
        "sport": sport, "family": family, "observation_scope": scope,
        "observed_denominator": observed, "denominator_unit": unit,
        "source_reported_model_evaluated": evaluated,
        "source_reported_settled": settled,
        "independently_valid_evaluations": None,
        "source_repository": source["repo"], "source_commit": source["commit"],
        "source_blob_sha1": source["sha"], "source_sha256": source["sha256"],
        "source_kind": source["kind"], "observed_at_utc": observed_at,
        "historical_availability": "UNVERIFIED_AT_FORECAST_CUTOFF",
        "source_provider_independence": "NOT_INDEPENDENTLY_VERIFIED",
        "exact_settlement_rule_status": rule_status, "rule_text_sample": rule_sample,
        "settlement_outcome_join": "NOT_INDEPENDENTLY_VERIFIED",
        "projected_outcome": projected_outcome,
        "candidate_inputs": candidate_inputs or [],
        "model_usage_status": model_status,
        "model_version_and_calibration": "UNVERIFIED",
        "point_in_time_pregame_eligibility": "UNVERIFIED",
        "full_checkpoint_delta_replay": "NOT_ESTABLISHED_BY_THESE_SOURCES",
    }


def compose(metadata, mlb_report, shard, now_utc):
    """Pure deterministic coverage matrix from validated source-backed objects."""
    now = timestamp(now_utc)
    if set(metadata) != set(SPORTS):
        raise ValueError("Eight distinct pinned sport metadata sources required")
    if not isinstance(mlb_report, dict) or not isinstance(shard, dict):
        raise ValueError("Missing verified source objects")
    rows = []
    for sport in SPORTS:
        record = metadata[sport]
        src, obj = record["source"], record["data"]
        if src["sport"] != sport or src["repo"] != ALLOWED[sport]:
            raise ValueError("Sport/source identity mismatch")
        # Validates the source-native metadata before any market-family claim.
        describe(sport, obj)
        if sport == "CBB":
            fam = obj["by_family"]
            if sum(fam.values()) != obj["n_markets"]:
                raise ValueError("CBB family denominator mismatch")
            at = obj["captured_at"]
            if timestamp(at) > now:
                raise ValueError("Future CBB capture")
            for name, count in sorted(fam.items()):
                rows.append(row(sport, name, src, observed=count,
                    unit="contracts_in_one_archived_snapshot",
                    observed_at=at, scope="2026-10-25_single_snapshot",
                    model_status="NOT_VERIFIED_FROM_SNAPSHOT",
                    rule_status="FAMILY_LABEL_ONLY_NO_CONTRACT_RULES"))
        elif sport == "MLB":
            audit = audit_mlb(mlb_report)
            fam = mlb_report["report"]["familyModelCoverage"]
            settled = mlb_report["report"]["familySettlementCoverage"]
            if sum(v["observed"] for v in fam.values()) != audit["opportunity_rows"]:
                raise ValueError("MLB source family rows do not reconcile")
            for name, counts in sorted(fam.items()):
                if settled[name]["observed"] != counts["observed"]:
                    raise ValueError("MLB family settlement denominator mismatch")
                rows.append(row(sport, name, record["quality_source"],
                    observed=counts["observed"], evaluated=counts["modelEvaluated"],
                    settled=settled[name]["settled"], unit="historical_opportunity_rows",
                    scope="2026-08-01_to_2026-08-20_historical_report",
                    model_status=("SOURCE_REPORTED_EVALUATIONS_NOT_INDEPENDENTLY_VALIDATED"
                                  if counts["modelEvaluated"] else "NO_EVALUATIONS_IN_SOURCE_REPORT"),
                    rule_status="FAMILY_LABEL_ONLY_NO_EXACT_SETTLEMENT_RULES"))
        else:
            if sport == "CFB":
                observed = obj["markets"]
                at = obj["captured_at"]
                if timestamp(at) > now:
                    raise ValueError("Future CFB catalog")
                unit = "contracts_in_catalog_snapshot"
            elif sport == "NFL":
                observed, at, unit = obj["n_open"], obj["observed_at"], "contracts_in_open_set"
                if timestamp(at) > now:
                    raise ValueError("Future NFL openset")
            elif sport == "TENNIS":
                observed, at, unit = obj["counts"]["open_markets"], None, "open_contracts_in_capture_manifest"
            else:
                observed, at, unit = None, None, "UNKNOWN_NO_CONTRACT_DENOMINATOR"
            rows.append(row(sport, "UNCLASSIFIED_FROM_THIS_SOURCE", src,
                observed=observed, unit=unit, observed_at=at,
                scope="SOURCE_METADATA_ONLY_NOT_FAMILY_BREAKDOWN",
                model_status="NOT_MEASURED_BY_SOURCE"))
    cfb = cfb_quarter_total(shard)
    src = metadata["CFB"]["cfb_source"]
    rows.append(row("CFB", "quarter_total", src, observed=cfb["observed"],
        unit=cfb["denominator_unit"], observed_at=cfb["market_capture_at_utc"],
        scope="ONE_EVENT_SHARD_NOT_FULL_CFB_CATALOG",
        rule_status=cfb["rule_text_status"],
        rule_sample={"primary": cfb["sample_rule_primary"], "secondary": cfb["sample_rule_secondary"],
                     "sample_ticker": cfb["sample_ticker"]},
        projected_outcome=cfb["projected_outcome"],
        candidate_inputs=[{"name": "first_quarter_possessions_and_pace",
                           "evidence": "CAUSAL_HYPOTHESIS_NOT_VERIFIED_IN_MODEL",
                           "historical_source": None, "available_at": None,
                           "model_used": "UNVERIFIED"},
                          {"name": "opponent_adjusted_first_quarter_scoring_efficiency",
                           "evidence": "CAUSAL_HYPOTHESIS_NOT_VERIFIED_IN_MODEL",
                           "historical_source": None, "available_at": None,
                           "model_used": "UNVERIFIED"}],
        model_status="NO_PIT_PROJECTION_JOIN_VERIFIED"))
    gaps = []
    for r in rows:
        missing = []
        if r["observed_denominator"] is None:
            missing.append("ORIGINAL_MARKET_FAMILY_DENOMINATOR")
        if r["family"] == "UNCLASSIFIED_FROM_THIS_SOURCE":
            missing.append("CONTRACT_LEVEL_FAMILY_ONTOLOGY")
        if r["exact_settlement_rule_status"] != "ARCHIVED_LITERAL_UNVERIFIED_SETTLEMENT":
            missing.append("LITERAL_CONTRACT_RULES")
        if r["point_in_time_pregame_eligibility"] == "UNVERIFIED":
            missing.append("INDEPENDENT_ACTUAL_START_AND_PIT_CAPTURE")
        if r["independently_valid_evaluations"] is None:
            missing.append("IMMUTABLE_FORECAST_TO_MARKET_AND_OUTCOME_JOIN")
        if r["candidate_inputs"]:
            missing.append("VERIFY_CANDIDATE_INPUTS_AND_PERIOD_PACE")
        if not missing:
            continue
        # Soft priority is explicitly not proof of currently available markets.
        priority = WEIGHTS[r["sport"]] + (10 if r["family"] == "quarter_total" else 0)
        if r["observed_denominator"] is not None:
            priority += min(10, len(str(r["observed_denominator"])))
        gaps.append({"sport": r["sport"], "family": r["family"],
                     "scope": r["observation_scope"], "denominator": r["observed_denominator"],
                     "denominator_unit": r["denominator_unit"], "missing": missing,
                     "priority_score": priority, "priority_authority": "HISTORICAL_EVIDENCE_ONLY",
                     "source_sha256": r["source_sha256"]})
    gaps.sort(key=lambda x: (-x["priority_score"], x["sport"], x["family"]))
    cbb_rows = [r for r in rows if r["sport"] == "CBB"]
    mlb_rows = [r for r in rows if r["sport"] == "MLB"]
    if sum(r["observed_denominator"] for r in cbb_rows) != 12209:
        raise ValueError("Pinned CBB snapshot denominator changed")
    if (sum(r["observed_denominator"] for r in mlb_rows) != 138158
            or sum(r["source_reported_model_evaluated"] for r in mlb_rows) != 694):
        raise ValueError("Pinned MLB source counts changed")
    hits = next(r for r in mlb_rows if r["family"] == "hitter_hits")
    if (hits["observed_denominator"], hits["source_reported_model_evaluated"]) != (23295, 0):
        raise ValueError("Pinned MLB hitter-hits denominator changed")
    return {"schema_version": 1, "authority": "RESEARCH_ONLY_NOT_LIVE_COLLECTION",
            "asof_utc": now_utc, "supported_sports": list(SPORTS),
            "family_rows": rows, "missing_input_queue": gaps,
            "verified_source_types": ["EIGHT_SPORT_METADATA", "MLB_HISTORICAL_QUALITY_REPORT",
                                      "CFB_ONE_EVENT_LITERAL_CONTRACT_RULES"],
            "distinct_denominators_must_not_be_summed": True,
            "all_market_families_certified": False, "live_capture_running": False,
            "independently_valid_forecast_or_profitability_claim": False,
            "checks": {"cbb_snapshot_contracts": 12209,
                       "mlb_historical_opportunities": 138158,
                       "mlb_source_reported_evaluations": 694,
                       "mlb_hitter_hits": [0, 23295],
                       "cfb_1q_sample_contracts": cfb["observed"]}}


def run(now_utc, *, metadata_downloader=None, quality_downloader=None, cfb_downloader=None):
    manifest = json.loads(Path("research/all_sport_metadata_pins.json").read_text())
    quality = json.loads(Path("research/sports_quality_evidence_sources.json").read_text())
    entries = manifest_entries(manifest)
    qentries = check_sources(quality)
    metadata = {}
    for x in entries:
        obj, digest = read_pinned(x, metadata_downloader)
        metadata[x["sport"]] = {"data": obj, "source": {
            "sport": x["sport"], "repo": x["repo"], "commit": x["commit"],
            "sha": x["sha"], "sha256": digest, "kind": x["kind"]}}
    mlb_pin = next(x for x in qentries if x["sport"] == "MLB")
    mlb, digest = read_quality(mlb_pin, quality_downloader)
    metadata["MLB"]["quality_source"] = {
        "sport": "MLB", "repo": mlb_pin["repository"], "commit": mlb_pin["commit"],
        "sha": mlb_pin["blob_sha1"], "sha256": digest, "kind": "historical_quality_report"}
    shard, digest = cfb_source(cfb_downloader)
    metadata["CFB"]["cfb_source"] = {
        "sport": "CFB", "repo": CFB_REPO, "commit": CFB_COMMIT,
        "sha": CFB_SHA1, "sha256": digest, "kind": "one_archived_event_shard"}
    return compose(metadata, mlb, shard, now_utc)


def main():
    # Fixed audit cutoff is reproducible; it is NOT a claim about today's markets.
    report = run("2026-11-01T23:59:59Z")
    target = Path("artifacts/market_family_input_coverage.json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("Source-verified market-family inventory:",
          len(report["family_rows"]), "rows across", len(report["supported_sports"]),
          "sports; CBB", report["checks"]["cbb_snapshot_contracts"],
          "MLB", report["checks"]["mlb_historical_opportunities"],
          "CFB sampled 1Q", report["checks"]["cfb_1q_sample_contracts"])
    print("All-family coverage, PIT forecast joins and live capture remain UNVERIFIED.")


if __name__ == "__main__":
    main()
