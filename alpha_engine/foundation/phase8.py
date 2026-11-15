"""Phase 8 acquisition + training-dataset log for the Alpha dashboard (RESEARCH_ONLY).

    python -m alpha_engine.foundation.phase8        # writes research/data_foundation_ops/phase8_acquisition.json

Joins committed evidence only: the training-set manifests (research/data_foundation_ops/training_sets/*.json), the NFL upcoming-game
manifest, and research/data_foundation_ops/phase8_evidence.json (counts, hashes and timestamps recorded from this phase's collection runs;
no rows). Statuses are never merged: acquired < verified (independent check) < built < training-ready < model-active. Nothing here is
model-active and no rights tier changed.
"""
from __future__ import annotations

import json

from .contract import OPS, write_json

TS = OPS / "training_sets"
EVIDENCE = OPS / "phase8_evidence.json"


def _j(p):
    return json.loads(p.read_text()) if p.exists() else None


def _set_row(m: dict) -> dict:
    wf = m.get("walk_forward") or m.get("walk_forward_home_margin", {}).get("all_ready_inputs") or {}
    return {"sport": m["sport"], "admission": m.get("admission", "TRAINING_READY inputs only"), "rows": m["rows"], "rows_by_split": m["rows_by_split"],
            "seasons": m["seasons"], "n_inputs": m["n_inputs"], "n_feature_columns": m["n_feature_columns"],
            "deterministic": bool(m["checks"]["deterministic_regeneration"]), "keys_unique": bool(m["checks"]["keys_unique"]),
            "both_sides_share": m["checks"].get("home_and_away_features_present_share"), "canonical_sha256": m["checks"]["canonical_sha256"],
            "walk_forward_mean": wf.get("mean", {}), "truncation_check": (m.get("truncation_check") or {}).get("all_equal"),
            "file": f"research/data_foundation_ops/training_sets/{m['sport']}.json"}


def build() -> dict:
    ev = _j(EVIDENCE) or {}
    sets = [_set_row(m) for s in ("NFL", "NHL", "NBA", "CBB") if (m := _j(TS / f"{s}.json"))]
    up = _j(TS / "NFL_upcoming.json")
    out = {"schema": "phase8-acquisition-1.0", "status": "RESEARCH_ONLY",
           "notice": "Agent verification only, not human verified. No model retrained or promoted, no schedule created or activated, no purchase, credential or rights-tier change. "
                     "No raw or dataset row committed: counts, hashes and evidence only.",
           "stage_order": ["ACQUIRED", "VERIFIED", "BUILT", "TRAINING_READY", "MODEL_ACTIVE"],
           "weather": ev.get("weather", {}), "collected": ev.get("collected", []), "prepared_code": ev.get("prepared_code", []),
           "training_sets": sets,
           "upcoming": None if not up else {"sport": "NFL", "rows": up["rows"], "rows_pregame_at_build": up["rows_pregame_at_build"], "feature_coverage": up["feature_coverage"],
                                            "built_at_utc": up["built_at_utc"], "rows_inputs_complete": up.get("rows_inputs_complete"), "asof": up["features_asof_last_completed_game"], "inputs_complete": up["inputs_complete"],
                                            "equivalence_all_equal": up["equivalence_check"]["all_equal"],
                                            "equivalence_games": sum(v["games"] for v in up["equivalence_check"]["dates"].values()),
                                            "equivalence_dates": len(up["equivalence_check"]["dates"]), "n_feature_columns": up["n_feature_columns"]},
           "coverage": ev.get("coverage", []), "training_ready_by_sport": ev.get("training_ready_by_sport", {}),
           "totals": ev.get("totals", {}), "blockers": ev.get("blockers", []), "next": ev.get("next", []), "decisions": ev.get("decisions", [])}
    return out


def main() -> int:
    write_json(OPS / "phase8_acquisition.json", build())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
