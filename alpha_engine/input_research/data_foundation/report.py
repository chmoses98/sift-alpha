"""Human report (docs/DATA_FOUNDATION.md) and the independent-verification sample for the data-foundation audit (RESEARCH_ONLY).

    python -m alpha_engine.input_research.data_foundation.report

Reads the artifacts written by `audit.py`; deterministic (no timestamps), so `regenerate --check` can verify it.
"""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

from . import audit as A
from . import evidence as EV

ROOT = EV.ROOT
DF = EV.DF
DOC = ROOT / "docs/DATA_FOUNDATION.md"
BUCKETS = ("COMPUTABLE", "REQUIRES_COLLECTION", "BLOCKED", "EXCLUDED")
STATUS_LABEL = {
    "COMPUTED_FULL": "computed, full definition (earlier milestone, point-in-time perturbation test)", "COMPUTED_PARTIAL": "computed, partial definition (earlier milestone)", "COMPUTED_PROXY": "computed as a proxy (earlier milestone)",
    "DATA_IN_HAND": "data in hand (profiled archive), builder not yet written", "COLLECT_FREE_MEASURED": "free source fetched from the runner: pull and build", "COLLECT_FREE_UNVERIFIED": "free source documented, not verifiable from the runner (or rules to encode)",
    "COLLECT_PROSPECTIVE": "no backfillable history: record vintages from now on (or accept final-only leakage)", "BLOCKED_SAMPLE_ONLY": "blocked: only a free sample exists", "BLOCKED_PAID_ONLY": "blocked: commercial source only (not added without permission)",
    "BLOCKED_NO_FREE_SOURCE": "blocked: no free source found", "EXCLUDED_BENCHMARK_ONLY": "excluded: market-derived benchmark"}
SAMPLE_K = {"COMPUTABLE": 4, "REQUIRES_COLLECTION": 3, "BLOCKED": 3, "EXCLUDED": 1}
SEED = "data-foundation-verification-v1"


def rd(p):
    return json.loads(Path(p).read_text())


def _h(k: str) -> str:
    return hashlib.sha256((SEED + k).encode()).hexdigest()


def verification_sample(rows: list[dict], reg: dict) -> tuple[dict, dict]:
    """Deterministic stratified sample (sport x bucket) for an INDEPENDENT verifier, plus every dataset whose status rests on a probe or ledger.
    Returns (questions, answer_key). The verifier gets only the questions (catalog ids and labels, no claimed status); the answer key is a separate file they must not open until they have submitted."""
    q_in, k_in = [], {}
    for s in A.SPORTS:
        for b in BUCKETS:
            pool = sorted((r for r in rows if r["sport"] == s and r["bucket"] == b), key=lambda r: _h(r["key"]))
            for r in pool[:SAMPLE_K[b]]:
                q_in.append({"key": r["key"], "label": r["label"][:140], "stratum": f"{s}/sampled"})
                k_in[r["key"]] = {"claimed_bucket": r["bucket"], "claimed_status": r["status"], "claimed_pit": r["pit_verdict"], "requirements": [{"need": x["need"], "dataset": x["satisfied_by"]} for x in r["requirements"]]}
    q_ds, k_ds = [], {}
    for d, v in sorted(reg.items()):
        if v["evidence_measured"]:
            q_ds.append({"dataset": d, "title": v["title"][:140], "evidence_pointers": v["evidence_measured"][:3]})
            k_ds[d] = {"claimed_access_status": v["access_status"], "claimed_history": v["history"]}
    task = {"inputs": "Without looking at any claim: from the catalog definition (research/input_research/catalog/<SPORT>.json), decide which raw data the input needs, whether a free source holds those fields for the needed history at pregame timing, and name its bucket: COMPUTABLE / REQUIRES_COLLECTION / BLOCKED / EXCLUDED (market-derived).",
            "datasets": "Re-run the cited probe or open the cited ledger and confirm the access status, row counts and date range; for DOCUMENTED history, confirm against the provider's own documentation."}
    questions = {"schema_version": "data-foundation-verification-sample-1.0", "status": "RESEARCH_ONLY", "seed": SEED, "task": task, "sample_size_inputs": len(q_in), "inputs": q_in, "datasets": q_ds,
                 "acceptance_proposal": {"note": "Defaults proposed by the audit author; the owner decides the bar. Predictive experimentation stays PAUSED until an independent verification has been completed and accepted by the owner.",
                                         "bucket_agreement_overall_min": 0.85, "bucket_agreement_computable_min": 0.95, "computable_rated_worse_by_verifier_reopens_sport": True, "dataset_status_replays_must_match": 1.0,
                                         "independence": "verifier must not be the author or any sport reviewer of this audit; a human domain expert is preferred; record verifier identity and method in verification_results.json; do not open verification_answer_key.json before submitting"},
                 "results_template": {"verifier": None, "method": None, "date": None, "inputs": {"<key>": {"bucket": None, "notes": None}}, "datasets": {"<dataset id>": {"status_confirmed": None, "notes": None}}}}
    key = {"schema_version": "data-foundation-verification-answer-key-1.0", "status": "RESEARCH_ONLY", "DO_NOT_OPEN_BEFORE_SUBMITTING": True, "inputs": k_in, "datasets": k_ds}
    return questions, key


def score(results: dict, key: dict) -> dict:
    """Compare an independent verifier's results with the answer key (used once a verification is submitted)."""
    ins = results.get("inputs") or {}; agree = comp_total = comp_agree = 0; worse = []
    order = ["COMPUTABLE", "REQUIRES_COLLECTION", "BLOCKED", "EXCLUDED"]
    for k, a in key["inputs"].items():
        v = (ins.get(k) or {}).get("bucket")
        if v is None:
            continue
        ok = v == a["claimed_bucket"]; agree += ok
        if a["claimed_bucket"] == "COMPUTABLE":
            comp_total += 1; comp_agree += ok
            if not ok and v in order and order.index(v) > 0:
                worse.append(k)
    n = sum(1 for k in key["inputs"] if (ins.get(k) or {}).get("bucket") is not None)
    ds = results.get("datasets") or {}; dsn = sum(1 for d in key["datasets"] if (ds.get(d) or {}).get("status_confirmed") is not None); dsok = sum(1 for d in key["datasets"] if (ds.get(d) or {}).get("status_confirmed") is True)
    return {"inputs_answered": n, "bucket_agreement": (agree / n) if n else None, "computable_agreement": (comp_agree / comp_total) if comp_total else None, "computable_rated_worse": worse, "dataset_replays_answered": dsn, "dataset_replays_confirmed": dsok}


def _pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "–"


def render(b: dict, sample: dict) -> str:
    s = b["summary"]; rows = b["rows"]; reg = b["registry"]; n = s["n_inputs"]
    P = EV.probes(); pc = collections.Counter(p["result"] for p in P.values())
    denied = sorted(p["id"] for p in P.values() if p["result"] == "POLICY_DENIED")
    L = ["# SIFT Alpha data foundation: raw-data audit of every catalog input (RESEARCH_ONLY)", "",
         "Generated by `python -m alpha_engine.input_research.data_foundation.audit` and `.report`; do not edit by hand. Artifacts: `research/input_research/data_foundation/` (`input_audit.json` per-input rows, `coverage_matrix.csv`, `datasets.json`, `sources.json`, `probes.json`, `summary.json`, `verification_sample.json`).", "",
         "> **Status: NOT independently verified.** This assessment was built by a Claude agent from measured probes, repo ledgers and the catalog's own provenance" + (", and every input was then reviewed by a per-sport Claude reviewer. " if s["all_inputs_reviewed"] else f". **Only {s['reviewed_inputs']} of {n} inputs have a recorded reviewer verdict: the rest is the unreviewed regex draft and is optimistic in places.** ") + "That is agent work, **not** human expert verification and **not** the independent verification that must precede any predictive experiment. "
         "**Predictive experimentation remains PAUSED.** No paid service was added, no live order was placed and no betting authority changed.", "",
         f"The audited baseline is the approved catalog blueprint (commit `50dc65e`, pinned by `research/input_research/baseline_lock.json`): **{n} inputs, 170 archetypes, 1,030 declared gaps, all preserved**. Approval was of the blueprint only.", "",
         "## Headline: which inputs are computable, which need collection, which are blocked", "",
         "| Bucket | Inputs | Share | Meaning |", "|---|---|---|---|"]
    meaning = {"COMPUTABLE": "computed on real data by the earlier milestone (point-in-time perturbation test) or all needed data already sits in a profiled archive", "REQUIRES_COLLECTION": "a free source exists but data must still be pulled, encoded, or captured prospectively (vintages cannot be backfilled)",
               "BLOCKED": "no usable free source (paid-only, none found, or a partial sample only)", "EXCLUDED": "market-derived benchmark inputs: never market-free inputs, not assessed for data"}
    for bk in BUCKETS:
        c = s["by_bucket"].get(bk, 0); L.append(f"| {bk.replace('_', ' ').title()} | {c} | {_pct(c, n)} | {meaning[bk]} |")
    L += ["", f"Reviewer coverage: **{s['reviewed_inputs']} of {n} inputs** carry a recorded per-input reviewer verdict ({s.get('reviewer_verdicts')}). Evidence grades: {s['evidence_grade']}. Confidence of the mapping: {s['confidence']}.", "",
          "### Coverage matrix (sport x status)", "", "| Sport | " + " | ".join(x.replace("_", " ").lower() for x in A.STATUSES) + " |", "|---|" + "---|" * len(A.STATUSES)]
    for sp in A.SPORTS:
        v = s["by_sport_status"][sp]; L.append(f"| {sp} | " + " | ".join(str(v.get(x, 0)) for x in A.STATUSES) + " |")
    tot = s["by_status"]; L.append("| **all** | " + " | ".join(f"**{tot.get(x, 0)}**" for x in A.STATUSES) + " |")
    L += ["", "Status meanings: " + "; ".join(f"`{k}` {v}" for k, v in STATUS_LABEL.items()) + ".", "",
          "### Bucket by sport", "", "| Sport | Inputs | Computable | Requires collection | Blocked | Excluded (market-derived) |", "|---|---|---|---|---|---|"]
    for sp in A.SPORTS:
        v = s["by_sport_bucket"][sp]; t = sum(v.values()); L.append(f"| {sp} | {t} | {v.get('COMPUTABLE', 0)} | {v.get('REQUIRES_COLLECTION', 0)} | {v.get('BLOCKED', 0)} | {v.get('EXCLUDED', 0)} |")
    L += ["", "### Point-in-time computability (can the input be rebuilt strictly from what was knowable before the event?)", "", "| Sport | " + " | ".join(x.replace("_", " ").lower() for x in A.PIT_VERDICTS) + " |", "|---|" + "---|" * len(A.PIT_VERDICTS)]
    for sp in A.SPORTS:
        v = s["by_sport_pit"][sp]; L.append(f"| {sp} | " + " | ".join(str(v.get(x, 0)) for x in A.PIT_VERDICTS) + " |")
    L += ["", "`PIT_LEAKY_FINAL_ONLY` / `PIT_UNAVAILABLE_HISTORICALLY` mean the history that exists stores only final / as-played / current-snapshot values (lineups as played, final injury status, retrieval-time ranks, current projections): a backtest on it would leak. Genuine pregame history needs vintage capture from now on.", "",
          "## Real source availability (measured)", "",
          f"{len(P)} endpoints were probed from the research runner on 2026-11-09 with range requests, a generic user agent, no credentials and no retries on denials: **{pc.get('REACHABLE', 0)} reachable, {pc.get('POLICY_DENIED', 0)} denied by the egress policy, {pc.get('NOT_FOUND_AT_PATH', 0)} not found at the guessed path, {pc.get('UNRESOLVED', 0)} DNS failures**. "
          "A denied host is **not** evidence the data is absent: those datasets are graded `FREE_BLOCKED_FROM_RUNNER` (documented free, unverified here). A 404 on a GitHub repo path is an access-scope effect of this session, not proof of absence. Datasets already collected into repo archives were profiled from their ledgers.", "",
          "Hosts denied by the egress policy (candidates to allow if the owner wants them verified; each is free): " + ", ".join(f"`{d}`" for d in denied) + ".", "",
          "### Dataset registry (" + str(len(reg)) + " raw datasets)", "", "| Access status | Datasets |", "|---|---|"]
    for k, v in sorted(s["datasets"]["by_access_status"].items(), key=lambda kv: EV.RANK[kv[0]]):
        L.append(f"| `{k}` | {v} |")
    L += ["", "| Dataset | Access status | History | PIT class | Cost | ToS risk | Collected rows |", "|---|---|---|---|---|---|---|"]
    for d, v in sorted(reg.items()):
        h = v["history"]; L.append(f"| `{d}` | {v['access_status']} | {h['first'] or '?'}–{h['last'] or '?'} ({h['basis'].lower()}) | {v['pit']} | {v['cost']} | {v['tos_risk']} | {v['rows_collected'] or ''} |")
    L += ["", "## Collection plan (free sources only): datasets that limit the most inputs", "", "Ranked by the number of not-yet-computable inputs for which the dataset is the limiting requirement. `PROSPECTIVE_CAPTURE_ONLY` datasets accrue history only from the capture start date.", "",
          "| Dataset | Limits (inputs) | Access status | PIT | Cost | ToS risk | Sports |", "|---|---|---|---|---|---|---|"]
    for p in s["collection_priorities"][:30]:
        L.append(f"| `{p['dataset']}` {p['title'][:60]} | {p['inputs_limited_by_it']} | {p['access_status']} | {p['pit']} | {p['cost']} | {p['tos_risk']} | {', '.join(p['sports'])} |")
    free_key = sorted(d for d, v in reg.items() if v["cost"] == "free (key needed)" and v["access_status"] != "COLLECTED_ARCHIVE")
    paid = sorted(d for d, v in reg.items() if v["access_status"] == "PAID_ONLY")
    L += ["", "## Cost, permission and terms", "",
          f"* **Paid services added: {s['paid_services_added']}.** Paid-only datasets ({len(paid)}): " + ", ".join(f"`{d}`" for d in paid) + ". The inputs that need them are `BLOCKED_PAID_ONLY` and stay blocked unless the owner grants permission.",
          f"* **Free but needing the owner's registration (free account/API key, not a purchase):** " + (", ".join(f"`{d}`" for d in free_key) or "none") + ".",
          f"* **Terms-of-use risk:** {s['tos_high_collectable']} inputs that are computable or collectable rest on sources whose terms restrict automated/bulk access (flagged `tos_risk: high` per input). Obtain a permitted route (official API, licensed bulk download, own re-derivation from permitted data) before collecting.", "",
          "## Per-input detail", "",
          "Every input has a row in `input_audit.json` and `coverage_matrix.csv`: exact raw-data requirements (need -> satisfying dataset), the catalog provenance sources with canonical ids, status and bucket, the status of the full definition, point-in-time verdict, history coverage (first/last, measured vs documented), freshness, cost, ToS risk, known missingness, blockers, confidence, flags, the earlier computed result and the sibling-repo collection class where one exists, and the reviewer verdict.", "",
          "## What this assessment does NOT establish", "",
          "* It does not verify that any catalog definition is correct, that any input predicts anything, or that any collected row is accurate. Missingness is measured only where a ledger or computed table exists; elsewhere it is stated as documented or unmeasured.",
          "* `DATA_IN_HAND` means a profiled archive holds the needed datasets; it does not mean a builder exists or that its leak test has passed. `COLLECT_FREE_UNVERIFIED` rests on documentation, not on a measurement from the runner.",
          "* Sibling-repo archives (nba-edge-finder, NHL-edge-finder, Tennis-Edge-Finder) are credited from their committed ledgers, not re-read here.",
          "* Reviewers were Claude agents working from the registry; their corrections are recorded in `review/<SPORT>.json` with rationales. The registry's access facts were never editable by a reviewer.", "",
          "## Independent verification protocol (the gate before any predictive experiment)", "",
          f"`verification_sample.json` is a deterministic stratified sample of {sample['sample_size_inputs']} inputs (sport x bucket) plus {len(sample['datasets'])} dataset status replays; it contains the questions only. The claims live in a separate `verification_answer_key.json` that the verifier must not open before submitting. An independent verifier re-derives each answer and fills `verification_results.json` (template included); `report.score()` compares it with the key. Proposed bar (the owner decides): "
          f"bucket agreement >= {sample['acceptance_proposal']['bucket_agreement_overall_min']:.0%} overall and >= {sample['acceptance_proposal']['bucket_agreement_computable_min']:.0%} on COMPUTABLE; every dataset replay matches; any COMPUTABLE input the verifier rates worse reopens that sport. "
          "The verifier must not be the author or a sport reviewer; a human domain expert is preferred. Until a verification is completed and accepted, `research/input_research/phase_control.json` keeps predictive experimentation PAUSED.", ""]
    return "\n".join(L)


def main() -> int:
    b = A.build(write=True)
    sample, key = verification_sample(b["rows"], b["registry"])
    (DF / "verification_sample.json").write_text(json.dumps(sample, indent=0, sort_keys=True, ensure_ascii=False) + "\n")
    (DF / "verification_answer_key.json").write_text(json.dumps(key, indent=0, sort_keys=True, ensure_ascii=False) + "\n")
    DOC.write_text(render(b, sample))
    print("wrote", DOC.relative_to(ROOT), "and verification_sample.json:", sample["sample_size_inputs"], "inputs,", len(sample["datasets"]), "dataset replays")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
