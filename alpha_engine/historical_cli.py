"""Run reproducible, pinned real-data audits. Research only, never place orders."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audits import audit_cfb, audit_mlb
from .pinned import load_manifest, parsed_source, read_source, verify_blob, source_url
from .review import independent_review


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit pinned free historical CFB and MLB source evidence")
    parser.add_argument("--manifest", default="research/pinned_sources.json")
    parser.add_argument("--out", default="artifacts/historical_diagnostics.json")
    parser.add_argument("--offline-dir", default=None, help="Offline raw files must still match pinned Git blob hash")
    args = parser.parse_args()
    entries = load_manifest(Path(args.manifest))
    inputs = {}
    provenance = {}
    for entry in entries:
        offline_path = Path(args.offline_dir) / (entry["id"] + (".jsonl" if entry["format"] == "jsonl" else ".json")) if args.offline_dir else None
        payload = read_source(entry, offline_path=offline_path)
        inputs[entry["id"]] = parsed_source(payload, entry)
        provenance[entry["id"]] = {
            "pinned_commit": entry["commit"],
            "git_blob_sha1": entry["git_blob_sha1"],
            "raw_sha256": verify_blob(payload, entry)["sha256"],
            "source_url": source_url(entry),
            "data_rights": entry["rights"],
            "source_independent_verification": "PENDING",
        }
    studies = {
        "cfb_prospective_settlements": audit_cfb(inputs["cfb_prospective_settlements"]),
        "mlb_replay_status": audit_mlb(inputs["mlb_replay_status"]),
    }
    report = {
        "version": 1,
        "authority": "RESEARCH_ONLY",
        "source_evidence": provenance,
        "studies": studies,
        "limitations": [
            "No point-in-time MLB pitch mix or NBA guard tracking dataset qualified",
            "This is a historical diagnostic, not prospective independent strategy validation",
            "Public derived-record source rights and upstream truth need independent verification",
            "No profit or betting recommendations are authorized",
        ],
    }
    verdict = independent_review(report, inputs)
    if not verdict["passed"]:
        raise RuntimeError("Independent audit rejected report: " + verdict["reason"])
    report["independent_review"] = verdict
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(destination), "independent_review": verdict, "CFB_n": studies["cfb_prospective_settlements"]["n_independent_games"], "MLB_n": studies["mlb_replay_status"]["n_archived_dates"], "authority": "RESEARCH_ONLY"}, sort_keys=True))


if __name__ == "__main__":
    main()
