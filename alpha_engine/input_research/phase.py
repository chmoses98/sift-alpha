"""Phase control (RESEARCH_ONLY): predictive experimentation is paused while the candidate-input catalog is reviewed for completeness.

Every predictive entry point (combination search, model fitting, benchmark experiments) calls `assert_predictive_allowed` first. There is deliberately no override
flag or environment variable: resuming needs a human edit of research/input_research/phase_control.json after the user's approval is recorded in
research/input_research/completeness/approval.json. Existing results are untouched; only *new* runs are refused.
"""
from __future__ import annotations

import json
from pathlib import Path

PHASE = Path(__file__).resolve().parents[2] / "research/input_research/phase_control.json"


def state() -> dict:
    return json.loads(PHASE.read_text())


def predictive_paused() -> bool:
    return state()["predictive_experiments"]["state"] != "RUNNING"


def assert_predictive_allowed(name: str) -> None:
    if predictive_paused():
        raise SystemExit(f"{name}: predictive experimentation is PAUSED (phase {state()['current_phase']}). "
                         "Resuming needs an independently verified data-readiness assessment plus an explicit human edit of research/input_research/phase_control.json.")
