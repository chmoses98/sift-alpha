"""Bounded, source-verified MLB research repair attempt (issue #7).

This is an *executable negative-control cycle*: detect -> diagnose from pinned
source code -> attempt safe diagnostic correction -> independently re-check.
It cannot reconstruct missing historical forecasts from an aggregate report.
No writes to sport repos, forecasts, market archives, orders, or credentials.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

from .sports_quality_evidence import audit_mlb

REPO = "chmoses98/edge-finder-api"
COMMIT = "de1798270c6a7fa53ea0ed3cc0dae287bf58584c"
EXPECTED = {
    "historical_quality": ("data/edgelab/analytics/latest_research_research_data_quality.json", "2c63cbee32c78bd47cd4586e19766c4c7723dccd"),
    "report_writer": ("scripts/edgelab/run_research_reports.py", "172322fe97517182d738b3e9c92539f7d4d6452d"),
    "research_join": ("lib/edgelab/research_dataset.py", "5050d1a57eed786b0fbad71bcd2b371497d82e50"),
    "generic_adapter": ("lib/kalshi_probability_adapters.py", "8da20e0afea5cd5dd149cd3a5b7b6b58742cf937"),
    "hitter_bridge": ("lib/edgelab/hitter_board_bridge.py", "7d56e0165ab6bebc58918d31af3324d766d459df"),
    "model_ledger": ("lib/edgelab/model_evaluation.py", "513f7f6df8fc896fc454eca67a19236d2cf51ff2"),
}
MAX_BYTES = 160000


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("Unexpected repair manifest version")
    if manifest.get("repository") != REPO or manifest.get("source_commit") != COMMIT:
        raise ValueError("Source revision/repository not approved")
    if type(manifest.get("max_bytes_total")) is not int or manifest["max_bytes_total"] != MAX_BYTES:
        raise ValueError("Repair byte budget changed")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or len(sources) != len(EXPECTED):
        raise ValueError("All exact code and report witnesses required")
    found = {}
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"id", "path", "blob_sha1", "max_bytes"}:
            raise ValueError("Unexpected source fields")
        ident = source["id"]
        if ident not in EXPECTED or ident in found or (source["path"], source["blob_sha1"]) != EXPECTED[ident]:
            raise ValueError("Unapproved/duplicate source witness")
        if type(source["max_bytes"]) is not int or not 0 < source["max_bytes"] <= 61000:
            raise ValueError("Unbounded source")
        found[ident] = source
    if set(found) != set(EXPECTED) or sum(s["max_bytes"] for s in sources) > MAX_BYTES:
        raise ValueError("Missing witness or exceeded total budget")
    return found


def load_sources(manifest, downloader=None):
    """Downloader receives a source descriptor and must return original bytes."""
    entries = validate_manifest(manifest)
    data, provenance = {}, []
    for ident in sorted(entries):
        source = entries[ident]
        if downloader is not None:
            raw = downloader(source)
        else:
            url = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{source['path']}"
            with urlopen(Request(url, headers={"User-Agent": "SIFT-Alpha-repair-audit/1"}), timeout=15) as response:
                if response.geturl() != url:
                    raise ValueError("Redirected source")
                raw = response.read(source["max_bytes"] + 1)
        if not isinstance(raw, bytes) or not raw or len(raw) > source["max_bytes"]:
            raise ValueError("Missing, oversized or non-byte witness: " + ident)
        git_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\\0" + raw).hexdigest()
        if git_sha != source["blob_sha1"]:
            raise ValueError("Git blob witness mismatch: " + ident)
        data[ident] = raw
        provenance.append({"id": ident, "repository": REPO, "commit": COMMIT,
                           "path": source["path"], "git_blob_sha1": git_sha,
                           "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    return data, provenance


def _function(tree, name):
    matches = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(matches) != 1:
        raise ValueError("Expected exact function missing: " + name)
    return matches[0]


def _call_names(node):
    return {n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
            for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))}


def code_diagnosis(witnesses):
    """Validate executable source structure; a text mention alone is not proof."""
    trees = {}
    for name in ("report_writer", "research_join", "generic_adapter", "hitter_bridge", "model_ledger"):
        try:
            trees[name] = ast.parse(witnesses[name].decode("utf-8"))
        except (UnicodeError, SyntaxError, KeyError) as exc:
            raise ValueError("Unparseable code witness: " + name) from exc
    writer = trees["report_writer"]
    load = _function(writer, "_load_universe")
    main = _function(writer, "main")
    load_calls = _call_names(load)
    if "read_partition" not in load_calls or "build_opportunity_rows" not in _call_names(main):
        raise ValueError("Research report source path not established")
    # Explicitly check the partition names in the loader AST. A hitter
    # projection artifact is NOT interchangeable with a ModelEvaluation.
    load_literals = {n.value for n in ast.walk(load) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    if "model_evaluations" not in load_literals or "hitter_projection_snapshots" in load_literals:
        raise ValueError("Report source partition contract changed")
    research_join = _function(trees["research_join"], "build_opportunity_rows")
    if "select_temporally_valid_evaluation" not in _call_names(research_join):
        raise ValueError("Point-in-time model join not established")
    bridge = _function(trees["hitter_bridge"], "load_hitter_board_lookup")
    if "stage_artifact_exists" not in _call_names(bridge):
        raise ValueError("Separate hitter-board bridge not established")
    ledger = _function(trees["model_ledger"], "extend_full_universe_evaluations")
    if "_discovery_extension_fields" not in _call_names(ledger):
        raise ValueError("Model evaluation extension bridge not established")
    adapter = trees["generic_adapter"]
    unsupported = None
    for n in adapter.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_NEVER_MODELED_FAMILIES" for t in n.targets):
            unsupported = ast.literal_eval(n.value)
    if not isinstance(unsupported, dict) or "hitter_hits" not in unsupported:
        raise ValueError("Generic adapter support cannot be established")
    return {
        "generic_adapter_hitter_hits": "UNSUPPORTED_IN_GENERIC_ADAPTER_AT_PIN",
        "separate_hitter_board_bridge": "PRESENT_IN_PINNED_CODE_NOT_PROOF_OF_ARCHIVED_FORECAST",
        "historical_research_report_inputs": "MARKET_OBSERVATIONS_AND_MODEL_EVALUATIONS_NO_HITTER_SNAPSHOT_PARTITION",
        "historical_model_join": "EXACT_TICKER_AND_NONFUTURE_EVALUATION_TIMESTAMP",
        "root_cause_certainty": "HISTORICAL_EVALUATION_JOIN_GAP_VERIFIED; WHETHER_VALID_HITTER_FORECASTS_EXISTED_UNRESOLVED",
        "source_revision": COMMIT,
    }


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def independent_verify(original, after):
    """A second, independently coded reducer guards against denominator games."""
    report = original["report"]
    families = report["familyModelCoverage"]
    observed = sum(v["observed"] for v in families.values())
    evaluated = sum(v["modelEvaluated"] for v in families.values())
    if observed != report["totalOpportunityRows"] or evaluated != observed - report["rowsLackingModelEvaluation"]:
        raise ValueError("Independent coverage reconciliation failed")
    if after["opportunity_rows"] != observed or after["model_evaluated_rows"] != evaluated:
        raise ValueError("Repair changed historical denominator/numerator")
    if after["families"] != {k: {"observed": v["observed"], "model_evaluated": v["modelEvaluated"]}
                            for k, v in sorted(families.items())}:
        raise ValueError("Repair modified market-family coverage")
    if after["independently_valid_evaluations"] is not None:
        raise ValueError("Original forecast-level evidence absent; cannot certify")
    return True


def run(manifest, downloader=None):
    """One deterministic, bounded attempt; no retries, source mutation or trades."""
    witnesses, provenance = load_sources(manifest, downloader)
    try:
        original = json.loads(witnesses["historical_quality"])
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Malformed historical audit") from exc
    before = audit_mlb(original)  # existing strict family/global checks
    code = code_diagnosis(witnesses)
    families = {k: {"observed": v["observed"], "model_evaluated": v["modelEvaluated"]}
                for k, v in sorted(original["report"]["familyModelCoverage"].items())}
    if before["opportunity_rows"] != 138158 or before["model_evaluated_rows"] != 694 or families.get("hitter_hits") != {"observed": 23295, "model_evaluated": 0}:
        raise ValueError("Pinned historical pilot counts changed; do not silently rebaseline")
    # Safe automatic *diagnostic* repair: replace the unsupported assertion
    # 'no hitter model exists' with a source-proven separation of generic
    # adapter, separate hitter board, and unproven historical PIT joins.
    # Do NOT create or backfill a ModelEvaluation row from later data.
    after = {
        "opportunity_rows": before["opportunity_rows"],
        "model_evaluated_rows": before["model_evaluated_rows"],
        "families": families,
        "independently_valid_evaluations": None,
        "historical_forecasts_backfilled": 0,
    }
    independent_verify(original, after)
    return {
        "schema_version": 1, "authority": "RESEARCH_ONLY",
        "cycle": ["DETECT", "DIAGNOSE", "SAFE_DIAGNOSTIC_RECLASSIFICATION", "INDEPENDENT_VERIFY", "RECORD"],
        "defect": {"sport": "MLB", "family": "hitter_hits", "severity": "P0",
                   "category": "MISSING_VERIFIABLE_HISTORICAL_MODEL_TO_MARKET_JOIN",
                   "observed": 23295, "model_evaluated": 0,
                   "source": "historical_quality", "historical_only": True},
        "source_code_diagnosis": code,
        "before": after.copy(), "after": after,
        "coverage_change_rows": 0, "independently_valid_evaluation_change": None,
        "diagnostic_repair_verified": True,
        "historical_model_repair_performed": False,
        "result": "BLOCKED_NO_SAFE_HISTORICAL_REPAIR",
        "blocker": "Need original timestamped hitter forecast snapshots, exact contract/line/player/game identity, original availability clocks and archived ModelEvaluation rows. Aggregate source report cannot prove eligible missing forecasts or safe retroactive repair.",
        "source_evidence": provenance,
        "source_digest_sha256": hashlib.sha256(_canonical(original)).hexdigest(),
        "certified_model_or_profitability": False,
    }


def main():
    manifest = json.loads(Path("research/mlb_repair_source_pins.json").read_text(encoding="utf-8"))
    report = run(manifest)
    out = Path("artifacts/mlb_repair_cycle.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\\n", encoding="utf-8")
    print(f"MLB repair: {report['result']}; {report['after']['model_evaluated_rows']}/{report['after']['opportunity_rows']} historical source-reported evaluations; hitter hits 0/23295; independent validity unverified.")
    print("Evidence:", out)


if __name__ == "__main__":
    main()
