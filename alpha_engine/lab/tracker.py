"""Connects the laboratory's measured findings to Alpha's EXISTING repair process (RESEARCH_ONLY).

* `research/audit/verification/repair_ledger.json` (issue #7 process; states OPEN / EVIDENCE_ADDED / BLOCKED / REPAIRED_VERIFIED; tests check every entry against the engine) receives
  APPEND-ONLY entries for engine tasks the lab actually measured.  An existing key is NEVER overwritten.  EVIDENCE_ADDED is only used where a measured source lifts the input out of
  UNKNOWN; nothing here is REPAIRED_VERIFIED because nothing is verified collection.
* the lab's own repair cases (`repair_cases.json`) are linked to engine task ids where one exists and ordered with the shared `alpha_engine.repair_queue.choose_next`, so there is one queue
  logic, not two."""
from __future__ import annotations
import json
from pathlib import Path
from .. import repair_queue as RQ

ENTRIES = {
    "NFL:nfl.ratings": ("EVIDENCE_ADDED",
        "alpha_engine/lab/ratings.py + game_lab.py compute opponent-adjusted rolling team ratings (EPA, success, explosive, tempo; half-life {4,8,16}, carry {0.4,0.8}, adjust on/off) from free nflverse play-by-play, strictly pre-game (state written before the game updates it). "
        "13,362 ledgered walk-forward experiments (research/audit/lab/ledger_*.jsonl.gz): ratings beat climatology out of sample (2022-24 totals +0.046 log-score, game CI above zero) but show NO advantage over Kalshi prices (totals +0.0016 [-0.015,+0.019]; spread/moneyline worse).",
        "Not VERIFIED collection: nflverse assets are unpinned latest releases (per-refresh sha256 only). No L3/L4 evidence of a gain over the market.",
        "Prospective 2026 test of the frozen strict point-in-time model (research/prospective/nfl_totals_v1, claim gate in alpha_engine/lab/prospective.py); pin nflverse release assets."),
    "NFL:nfl.script": ("EVIDENCE_ADDED",
        "Game-script inputs (predicted margin, total, team points) are produced by the market-free game lab and used by the player lab (player_run.build_game_ctx); never prices. Their predictive contribution to player props was ledgered (research/audit/lab/ledger_player_*.jsonl.gz).",
        "No in-game script simulation; the inputs are pre-game point estimates only. Player-prop probabilities remain worse than the market (best declared variant: pass yds -0.014 CI includes 0, others CI below 0).",
        "Evaluate the declared player variant v3_listed_emp prospectively as a separately labelled, market-selected-population experiment (research/prospective/nfl_player_v3)."),
    "NFL:nfl.qb": ("OPEN",
        "The lab's `qb` group uses the REALISED starting quarterback (partial point-in-time). Removing it (plus observed weather) from the totals model lowers 2022-24 log-score gain +0.046 -> +0.023 but keeps parity with the market (+0.0012), so the prospective model drops it.",
        "No free, timestamped pre-game expected-starter source is collected (depth chart / inactives lack publication times in nflverse).",
        "Collect expected-starter and official inactives with publication timestamps prospectively; then re-test the qb group point-in-time."),
    "NFL:nfl.snaps": ("OPEN",
        "Snap counts are collected by nflverse but not used by the lab. Player involvement is modelled from appearance history only (alpha_engine/lab/involvement.py): market-free logistic model, validated 2022-24 (log loss 0.41 vs 0.60 for the raw appearance rate), but P(involved) for players the exchange lists is ~0.86 vs 97-100% realised (listing is selection information).",
        "Snap share / routes not used; no pre-game inactive list with timestamps.",
        "Add snap-share state to the involvement model and capture official inactives (~90 min before kickoff) prospectively."),
}


def append_ledger(ledger_path: Path, entries: dict = ENTRIES) -> dict:
    """Textual append that preserves the existing file byte-for-byte (one compact entry per line, like the rest of the ledger); a key already present is never touched."""
    raw = Path(ledger_path).read_text()
    before = json.loads(raw)
    tail = "\n }\n}\n"
    assert raw.endswith(tail), "unexpected ledger layout"
    body, added, kept = raw[:-len(tail)], [], []
    for k, (state, found, remaining, nxt) in entries.items():
        if k in before["entries"]:
            kept.append(k); continue
        e = {"state": state, "searched": ["alpha_engine/lab (PR #59)", "research/audit/lab/*.json"], "found": found, "remaining": remaining, "next": nxt}
        body += ",\n  " + json.dumps(k) + ": " + json.dumps(e, ensure_ascii=False)
        added.append(k)
    if added:
        new = body + tail
        after = json.loads(new)
        assert all(after["entries"][k] == v for k, v in before["entries"].items()), "an existing entry changed"
        assert new.startswith(raw[:-len(tail)]), "existing text changed"
        Path(ledger_path).write_text(new)
    return {"added": added, "kept_existing": kept}


def link_cases(cases: list[dict], engine_task_ids: set[str], results: dict | None = None) -> dict:
    """Attach `alpha_task_id` where the engine tracks the same input, and pick the next actionable case with the shared repair_queue logic."""
    out = []
    for c in cases:
        cid = c["id"]; eng = None
        if cid.startswith("nfl:input:"):
            cand = "NFL:" + cid[len("nfl:input:"):]
            eng = cand if cand in engine_task_ids else None
        out.append({**c, "alpha_task_id": eng})
    results = results or {c["id"]: [{"status": "BLOCKED"}] for c in out if c.get("status") == "BLOCKED"}
    nxt = RQ.choose_next([{"id": c["id"]} for c in out], results)
    return {"cases": out, "next": nxt, "linked_to_engine": sum(1 for c in out if c["alpha_task_id"])}
