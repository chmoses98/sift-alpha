"""Coverage + adoption matrices, GENERATED from pinned Alpha evidence (master_inventory.json = 275 native families across 8
sports; coverage_ledger.json = existing per-cell outcome-intel statuses) plus an explicit, human-reviewed adoption table.
Nothing is inferred about producers Alpha cannot read: where a repo was not inspected it says so."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .families import classify_contract
from .schema import SPORTS

ROOT = Path(__file__).resolve().parent.parent

# Human-reviewed from the files named in each row (Alpha repo + pure-contract); producer repos other than
# sift-sports-intelligence were NOT readable in this session, so their rows cite only what Alpha's archived audits recorded.
_KALSHI_RIGHTS = (" Kalshi data rights UNRESOLVED (storage, public aggregate reports, commercial use): see docs/ALPHA_EVALUATION_STANDARD_V1.md §7;"
                  " no authorization claimed.")
ADOPTION = {
    "NFL": dict(producer="chmoses98/nfl-edge-finder", existing="research/outcome_intel/audit_nfl.py + incremental.py (moneyline/spread/total vs near-close line); sift_clv (canonical/executable CLV, linkage); sift_exec + shadow ledger; nfl-prospective-ops workflow (prospective capture)",
                gaps="no calibrated PIT forecast export in sift-alpha-eval/1 form; player props: only QB passing yards has a predictive test; alt lines/ladders not evaluated as correlated groups",
                blockers="verified fills exist only for a small owner-wager set (see sift_clv.linkage); maker fee schedule unobserved", integration="NFL forecast+outcome+quote JSONL read-only export (P1: reuse prospective capture)", status="ROADMAP (not started in the v1 closeout)"),
    "CFB": dict(producer="chmoses98/cfb-edge-finder", existing="research/outcome_intel/audit_cfb.py, cfb_incremental.py, cfb_q1_* (quarter-total chain/ablation)",
                gaps="quarter/half/team-total models beyond 1Q total; no frozen-version registry export", blockers="thin holdouts (ledger: mostly INCONCLUSIVE_UNDERPOWERED); FCS has no engine", integration="CFB export of frozen projections with as_of + model_version", status="ROADMAP (not started in the v1 closeout)"),
    "NBA": dict(producer="chmoses98/nba-edge-finder", existing="alpha_eval/nba_shadow.py + nba_games.py + nba_universe.py (read-only PURE shadow-store adapter, derived game-level forecasts, all-families universe reconciliation; PR #65 merged); alpha_engine/nba_forecast_eval.py; research/outcome_intel/nba_audit.py",
                gaps="coverage INCOMPLETE: 33,905 of 145,981 in-window game-bound markets graded (23.2%); 16,214 player-prop tickers in forecast games never linked to a player (producer listing archive covers 111 of 182 forecast games)", blockers="Kalshi official result absent in archive (settlement derived from ESPN); player props OVERCONFIDENT and moneyline UNDERCONFIDENT (model issues, not evaluation issues)." + _KALSHI_RIGHTS, integration="done: baseline docs/alpha_eval/NBA_POSTMORTEM_001.md + reports/alpha_eval/nba/; next is model improvement (calibration) and producer listing coverage", status="INTEGRATED - BASELINE NBA-001 (PR #65 merged)"),
    "CBB": dict(producer="chmoses98/cbb-edge-finder", existing="research/outcome_intel/cbb_audit.py + cbb_common.py (game winner/spread/total vs mid, holdout)",
                gaps="no half / team-total / OT / race distributions in the frozen model (ledger MISSING_DATA); ongoing CBB model research continues independently and is NOT touched here", blockers="short archive (2026-10-05..11-04), 36-109 holdout games", integration="export frozen pure-0.2.0 + shadow versions through the adapter", status="ROADMAP (Wave 14 model research continues separately in cbb-edge-finder PR #48, collecting prospective evidence)"),
    "NHL": dict(producer="chmoses98/NHL-edge-finder", existing="alpha_eval/nhl_archive.py (read-only data-archive adapter: git-chain freeze attestation, official NHL API outcomes, board-replay quotes); research/outcome_intel/nhl_audit.py",
                gaps="coverage INCOMPLETE: 65,037 of 74,564 in-window game-bound markets graded (87.2%); unsupported families game_overtime (frozen input not mapped) and game_early_goal (no source); near-close horizon only (T-6h not graded)", blockers="39 shootout totals blocked (Kalshi rule text silent); 41 stat-correction conflicts blocked; 620 player tickers not independently resolvable blocked; freeze clock checked against GitHub on 6 of 371 capture runs; Kalshi official result absent." + _KALSHI_RIGHTS, integration="baseline docs/alpha_eval/NHL_POSTMORTEM_001.md (revision 1) + reports/alpha_eval/nhl/; next is model improvement", status="INTEGRATED - BASELINE NHL-001 rev 1 (PR #66, awaiting owner approval to merge)"),
    "MLB": dict(producer="chmoses98/edge-finder-api", existing="research/outcome_intel/mlb_audit.py, mlb_pinnacle.py, mlb_incremental.py",
                gaps="no timestamped probability for game total / run line / hitter props", blockers="Kalshi history 2026 only; settlement derived (game_total disagreements flagged); 35.5% two-sided quote coverage near first pitch; no per-input availability stamps", integration="export ML/F5/YRFI/team-total probabilities with run time", status="ROADMAP (not started in the v1 closeout)"),
    "SOCCER": dict(producer="chmoses98/soccer-edge-finder", existing="research/outcome_intel/soccer_audit.py (329 cells, 13 families, per-contract binary)",
                   gaps="3-way result should be graded CATEGORICAL (multiclass Brier), not three binary Briers; lineups unknown pregame", blockers="441 settled fixtures; most cells underpowered", integration="export per-fixture categorical probs + totals pmf", status="ROADMAP (not started in the v1 closeout)"),
    "TENNIS": dict(producer="chmoses98/Tennis-Edge-Finder", existing="research/outcome_intel/tennis_audit.py, tennis_capture*, tennis_settlement*",
                   gaps="Kalshi `scalar` (fair-price) contracts are non-binary: UNSUPPORTED for economics in v1; only MATCH_WINNER has model probabilities", blockers="only 3.1% of settled observations are STRICT_PREGAME (start time unknown); capture pins limited", integration="export match/set probabilities with validated start times", status="ROADMAP (not started in the v1 closeout)"),
}


def build(root: Path = ROOT) -> dict:
    inv = json.loads((root / "research/audit/master_inventory.json").read_text())
    led = json.loads((root / "reports/outcome_intel/coverage_ledger.json").read_text())
    cells = defaultdict(lambda: dict(native_families=0, markets_now=0, scorable_native=0, unsupported_native=0, reasons=Counter(), allowed=set(), natives=[]))
    for f in inv["families"]:
        c = classify_contract(f["sport"], f["native_family"], "")
        d = cells[(f["sport"], c["family"])]
        d["native_families"] += 1
        d["markets_now"] += (f.get("observed") or {}).get("markets_now") or 0
        d["allowed"].update(c["allowed_scoring"])
        if c["support"] == "SCORABLE":
            d["scorable_native"] += 1
        else:
            d["unsupported_native"] += 1
            d["reasons"][c["reason"]] += 1
        d["natives"].append(f["native_family"])
    led_by = defaultdict(Counter)
    for r in led["ledger"]:
        for s, n in r["statuses"].items():
            led_by[r["sport"]][s] += n
    return dict(
        schema="sift-alpha-eval-coverage/1", inventory_generated_utc=inv["generated_utc"], ledger_schema=led["schema"],
        families=[dict(sport=s, family=fam, native_families=d["native_families"], markets_now=d["markets_now"],
                       evaluator_scorable_native=d["scorable_native"], evaluator_unsupported_native=d["unsupported_native"],
                       unsupported_reasons=dict(d["reasons"]), allowed_scoring=sorted(d["allowed"]))
                  for (s, fam), d in sorted(cells.items())],
        existing_cell_status_by_sport={s: dict(led_by.get(s, {})) for s in SPORTS},
        adoption=ADOPTION)


def to_markdown(m: dict) -> str:
    L = ["# Alpha Universal Evaluation Standard v1: coverage and adoption matrices", "",
         f"Generated by `python -m alpha_eval coverage` from `research/audit/master_inventory.json` (generated {m['inventory_generated_utc']}) and "
         f"`reports/outcome_intel/coverage_ledger.json` (`{m['ledger_schema']}`). **Evaluator support** means Alpha has a valid scoring rule for the "
         "contract shape; it does NOT mean any producer yet exports forecasts for it or that any model has been shown to beat its market. "
         "`markets_now` is the pinned open-market count at inventory time, not a settled-evaluation count.", "",
         "## 1. Market-family coverage (evaluator rules vs the 275 inventoried native families)", "",
         "| sport | eval family | native families | markets now | scorable | unsupported (reason) | allowed scoring |", "|---|---|---|---|---|---|---|"]
    for r in m["families"]:
        un = ", ".join(f"{k}×{v}" for k, v in r["unsupported_reasons"].items()) or "–"
        L.append(f"| {r['sport']} | {r['family']} | {r['native_families']} | {r['markets_now']} | {r['evaluator_scorable_native']} | {r['evaluator_unsupported_native']} ({un}) | {', '.join(r['allowed_scoring']) or '–'} |")
    L += ["", "## 2. What the existing outcome-intel ledger already shows (cell counts, per sport; none validated)", "",
          "| sport | INCONCLUSIVE_UNDERPOWERED | NO_DEMONSTRATED_IMPROVEMENT | MISSING_DATA | PROMISING_INSUFFICIENT | INVALID_EVIDENCE |", "|---|---|---|---|---|---|"]
    for s, c in m["existing_cell_status_by_sport"].items():
        L.append(f"| {s} | " + " | ".join(str(c.get(k, 0)) for k in ("INCONCLUSIVE_UNDERPOWERED", "NO_DEMONSTRATED_IMPROVEMENT", "MISSING_DATA", "PROMISING_INSUFFICIENT", "INVALID_EVIDENCE")) + " |")
    L += ["", "## 3. Sport-by-sport adoption matrix", "",
          "Producer repos other than `sift-sports-intelligence` were not readable from this session; their rows cite only what Alpha's archived audits recorded. "
          "No producer prediction engine is modified; integration is by read-only JSONL export (see spec §9).", "",
          "| sport | status | producer repo | existing implementation reused | gaps | blockers | required integration |", "|---|---|---|---|---|---|---|"]
    for s, a in m["adoption"].items():
        L.append(f"| {s} | {a['status']} | {a['producer']} | {a['existing']} | {a['gaps']} | {a['blockers']} | {a['integration']} |")
    L += ["", "_RESEARCH_ONLY. Generated file: edit `alpha_eval/coverage.py::ADOPTION`, not this table._", ""]
    return "\n".join(L)
