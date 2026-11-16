"""Phase 10 progress log for the Alpha dashboard: preservation, certification, official outcomes, collection (RESEARCH_ONLY).

    python -m alpha_engine.foundation.phase10      # writes research/data_foundation_ops/phase10_progress.json

Joins committed evidence only; no number is typed here:
  research/phase10/vault_catalog.json        copy of the private vault's generated CATALOG.json + verify / restore results (metadata only)
  research/phase10/kalshi_official.json      counts from the official-settlement snapshot (no market rows)
  research/phase10/collection.json           content-verified collection results per sport (counts) and gaps closed against PR #80's ledger
  research/phase10/settlement_repair.json    NBA 2H-overtime reconciliation numbers (nba-edge-finder draft PR)
  research/certification/*.json              certification verdicts, append-only dataset versions
  research/data_foundation_ops/acquisition_plan.json / acquisition_inputs.json   the generated catalog

Statuses are never merged: collected < durably archived (hash-verified) < certified dataset < training-ready input < model-active.
Nothing here is model-active; no model was trained or promoted.
"""
from __future__ import annotations

import json

from .contract import OPS, ROOT, write_json

P10 = ROOT / "research/phase10"
CERT = ROOT / "research/certification"
SPORTS = ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB"]
BASELINE = {"as_of": "2026-11-16 before Phase 10 (certification branch, catalog not regenerated)", "training_ready_inputs": 41}


def _j(p):
    return json.loads(p.read_text()) if p.exists() else None


def build() -> dict:
    plan = _j(OPS / "acquisition_plan.json"); inputs = _j(OPS / "acquisition_inputs.json")["inputs"]
    vault = _j(P10 / "vault_catalog.json") or {}; kal = _j(P10 / "kalshi_official.json") or {}; col = _j(P10 / "collection.json") or {}
    rep = _j(P10 / "settlement_repair.json") or {}; versions = _j(CERT / "dataset_versions.json")["versions"]
    ready = {s: sorted(k.split(":", 1)[1] for k, v in inputs.items() if v["s"] == s and v["tr"]["state"] == "TRAINING_READY") for s in SPORTS}
    certified = sorted(k for k, v in inputs.items() if "cert" in v["tr"])
    arch = vault.get("archives", [])
    by_sport = {}
    for s in SPORTS:
        rows = [a for a in arch if a["sport"] == s]
        by_sport[s] = {"archives": sum(a["kind"] == "ARCHIVE" for a in rows), "pins": sum(a["kind"] == "PIN_ONLY" for a in rows),
                       "stored_bytes": sum(a["stored_bytes"] for a in rows), "raw_bytes": sum(a["uncompressed_bytes"] for a in rows if a["kind"] == "ARCHIVE"),
                       "datasets": [{"dataset": a["dataset"], "season": a["season"], "source": a["source"], "version": a["version"], "kind": a["kind"], "files": a["n_files"],
                                     "stored_bytes": a["stored_bytes"]} for a in rows]}
    after = plan["totals"]["training_ready_inputs"]
    return {
        "schema": "phase10-progress-1.0", "status": "RESEARCH_ONLY",
        "notice": "Agent-run, not human verified. Every number is read from committed evidence files. No model trained, promoted or activated; no trading change.",
        "stage_order": ["COLLECTED", "ARCHIVED_VERIFIED", "CERTIFIED_DATASET", "TRAINING_READY", "MODEL_ACTIVE"],
        "training_ready": {"baseline": BASELINE, "after": after, "by_sport": {s: len(v) for s, v in ready.items()}, "inputs": ready,
                           "promoted_by_certification": certified, "model_active": 0},
        "dataset_versions": [{"sport": e["sport"], "hash": e["canonical_sha256"][:12], "builder": e["builder"], "rows": e["rows"], "registered": e["registered"],
                              "training_ready": bool((e.get("tiers") or {}).get("training_ready")), "superseded_by": e.get("superseded_by"),
                              "verified": (e.get("tiers") or {}).get("independently_verified"), "complete": (e.get("tiers") or {}).get("historically_complete")} for e in versions],
        "vault": {"repository": "chmoses98/sift-data-vault (private)", "totals": vault.get("totals", {}), "verify": vault.get("verify", {}), "restore_test": vault.get("restore_test", {}),
                  "by_sport": by_sport},
        "official_settlements": kal, "settlement_repair": rep,
        "collection": col.get("collected", []), "gaps_closed": col.get("gaps_closed", []), "remaining_gaps": col.get("remaining_gaps", []),
        "completeness": col.get("completeness", []), "coverage_kind": col.get("coverage_kind", []),
        "blockers": col.get("blockers", []), "next": col.get("next", []),
    }


def main() -> int:
    out = build(); write_json(OPS / "phase10_progress.json", out)
    print("phase10: training-ready", out["training_ready"]["baseline"]["training_ready_inputs"], "->", out["training_ready"]["after"], "| vault", out["vault"]["totals"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
