"""Human report (docs/DATA_FOUNDATION.md) and the independent-verification sample for the data-foundation audit (RESEARCH_ONLY).

    python -m alpha_engine.input_research.data_foundation.report

Reads the artifacts written by `audit.py`; deterministic (no timestamps), so `regenerate --check` can verify it.
"""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

from . import access_proposal as AP
from . import capture_plan as CAPP
from . import audit as A
from . import collection_plan as CP
from . import evidence as EV
from . import verified_coverage as VC

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


def render_verified(vc: dict) -> list[str]:
    s = vc["summary"]; rows = vc["rows"]; n = s["n"]; V = s["by_verified_status"]; B = s["by_verified_bucket"]
    VD = VC.VD
    L = ["## VERIFIED COVERAGE (the one authoritative matrix: `coverage_matrix.csv` / `verified_coverage.json`)", "",
         "Every figure below comes from committed verification evidence under `research/input_research/data_foundation/verification/`: feature replays on re-collected raw data (all eight sports), blind verifier verdicts on real column schemas (two rounds), a blind sample of the other buckets, and two blind rechecks of every drafted-BLOCKED input (the second under the owner's explicit access policy). "
         "Verifiers are Claude agents, so this is **agent verification, not human expert verification**, and it does not by itself authorise predictive modelling.", "",
         "| Bucket | Inputs | Meaning |", "|---|---|---|"]
    meaning = {"FULL": "computed AND replayed: every independent test passed, no forbidden-as-pregame field, whole definition implemented, coverage and provenance checked",
               "PARTIAL": "replayed and clean, but only part of the catalog definition is implemented or coverage is limited", "PROXY": "replayed and clean, but measures a different quantity for the same mechanism",
               "DATA_IN_HAND": "no builder yet; two blind verifiers confirmed from REAL re-read columns that it can be built point-in-time (a verdict resting on a table not re-read this session does not count)",
               "CAVEAT": "replayed; depends on schedule structure (e.g. games left) valid only if the fixture list is known before the event",
               "UNVERIFIED": "a claim with no replay or real-column check (schema-only, or a blocked/computable dispute the two blind rounds did not settle)",
               "FAILED": "a replay or blind verifier showed the claim fails, or it depends on a field the point-in-time policy forbids (quarantined)",
               "REQUIRES_COLLECTION": "a permitted source exists but data must still be pulled/encoded, or captured prospectively", "BLOCKED": "no permitted usable source (policy-blocked, none found, sample-only, or blind-confirmed)", "EXCLUDED": "market-derived benchmark inputs"}
    for k in VC.BUCKET_ORDER:
        L.append(f"| {k.replace('_', ' ').title()} | {B.get(k, 0)} | {meaning[k]} |")
    vtot = sum(B.get(k, 0) for k in ("FULL", "PARTIAL", "PROXY", "DATA_IN_HAND"))
    L += ["", f"Total {n} inputs. At the draft, **{s['claimed_computable_at_draft']}** inputs were called potentially computable; **{vtot}** are verified computable now (FULL {B.get('FULL', 0)}, PARTIAL {B.get('PARTIAL', 0)}, PROXY {B.get('PROXY', 0)}, DATA_IN_HAND {B.get('DATA_IN_HAND', 0)}). "
          "These are counted separately everywhere: a FULL is never averaged with a DATA_IN_HAND.", "",
          "### Verified status by sport", "", "| Sport | " + " | ".join(x.replace("_", " ").lower() for x in VC.HEADLINE) + " |", "|---|" + "---|" * len(VC.HEADLINE)]
    for sp in A.SPORTS:
        v = s["by_sport_verified_status"][sp]; L.append(f"| {sp} | " + " | ".join(str(v.get(x, 0)) for x in VC.HEADLINE) + " |")
    L.append("| **all** | " + " | ".join(f"**{V.get(x, 0)}**" for x in VC.HEADLINE) + " |")
    L += ["", "### Point-in-time policy and quarantine", "", "Owner's rules: observed weather never replaces a pregame forecast; final lineups, game-day outcomes and revised / retrieval-time rankings never appear as pregame inputs. `alpha_engine/features/pit_policy.py` classifies the forbidden raw fields; any replayed input whose features depend on one is **quarantined** (`pit_quarantine.json`) and the feature framework now marks it `final_postgame` (never pregame-eligible). "
          "In the draft layer any pregame weather need is forced onto the forecast-vintage dataset, whatever a reviewer mapped. Quarantined inputs:", ""]
    qf = DF / "pit_quarantine.json"
    if qf.exists():
        q = json.loads(qf.read_text())["specs"]
        L += [f"* `{k}`: {', '.join(v['classes'])} ({', '.join(v['fields'][:3])})" for k, v in sorted(q.items())] or ["* none"]
    L.append("")
    # replay evidence
    L += ["", "### Feature replay (previously computed inputs, re-collected raw data, independent tests)", "",
          "Tests that do **not** reuse the earlier run's seeds, cut dates or protected-column lists: determinism; coverage replay vs the recorded values; **truncation** (recompute on data cut before date D, earlier rows must be identical); outcome perturbation at new cuts/seeds; own-game perturbation at a mid-history date; **vintage dependence** (scramble as-played / retrieval-time fields and see which computed columns move).", "",
          "| Sport | Specs replayed (mode) | Determinism | Truncation | Perturbation | Own-game | Depend on as-played fields | Re-collected raw rows | Provenance vs ledger |", "|---|---|---|---|---|---|---|---|---|"]
    reps = VC.load_replays()
    for sp in A.SPORTS:
        if sp not in reps:
            L.append(f"| {sp} | **not replayed** | | | | | | | {'replay not completed'} |"); continue
        ins = reps[sp]["inputs"].values(); t = lambda f: sum(1 for i in ins if f(i["tests"]))
        pv = s["provenance_checks"].get(sp) or {}
        L.append(f"| {sp} | {len(ins)} ({'quick: 1 truncation cut, 1 perturbation' if reps[sp].get('quick') else 'full: 3 truncation cuts, 3 perturbations'}) | {t(lambda x: x['determinism']['ok'])} | {t(lambda x: all(y['ok'] for y in x['truncation']))} | {t(lambda x: all(y['ok'] for y in x['perturbation']))} | {t(lambda x: x['own_game']['ok'])} | {t(lambda x: any(x.get('vintage_dependence', {}).values()))} | {pv.get('replay_rows')} | {'ok' if pv.get('ok') else 'MISMATCH'} ({pv.get('basis', '')[:60]}) |")
    # failed checks
    fails = []
    for sp, rp in reps.items():
        for iid, r in rp["inputs"].items():
            t = r["tests"]; bad = []
            if not t["determinism"]["ok"]: bad.append("determinism")
            for x in t["truncation"]:
                if not x["ok"]: bad.append(f"truncation@{x['cut']}: {x['bad_columns'][:3]}"); break
            for x in t["perturbation"]:
                if not x["ok"]: bad.append(f"perturbation@{x['cut']}: {x['bad_columns'][:3]}"); break
            if not t["own_game"]["ok"]: bad.append(f"own-game@{t['own_game'].get('date')}: {t['own_game'].get('bad_columns')}")
            vd = [k for k, v in (t.get("vintage_dependence") or {}).items() if v]
            if vd: bad.append("depends on as-played fields " + ", ".join(vd))
            if bad: fails.append((f"{sp}:{iid}", bad))
    L += ["", "**Failed or caveated replay checks (all of them):**", ""] + ([f"* `{k}`: {'; '.join(b)}" for k, b in fails] or ["* none"]) + [""]
    # bucket sample + blocked recheck + dih
    ks = VD / "bucket_sample"
    if ks.exists():
        key = json.loads((ks / "key.json").read_text()); ans = {}
        for f in sorted(ks.glob("answers_*.json")): ans.update(json.loads(f.read_text())["answers"])
        ag = collections.Counter(); tot = collections.Counter()
        for k_, a in key.items():
            tot[a["claimed_bucket"]] += 1; ag[a["claimed_bucket"]] += int(ans[k_]["bucket"] == a["claimed_bucket"])
        L += ["### Blind verification of the other buckets", "", f"A stratified blind sample of {len(key)} inputs (verifiers saw only the catalog definition, never the claim): overall agreement **{sum(ag.values())}/{len(key)} = {sum(ag.values()) / len(key):.0%}**; " + "; ".join(f"{b}: {ag[b]}/{tot[b]}" for b in tot) + ". "
              "The draft's BLOCKED calls did not survive: see the next paragraph. The sample is evidence about the draft's reliability by bucket; **85% overall agreement is not a licence to start predictive modelling**.", ""]
    bk = VD / "blocked_recheck"
    if bk.exists():
        c = collections.Counter(("RECLASSIFIED_TO_REQUIRES_COLLECTION" if v["verified_status"] == "REQUIRES_COLLECTION" else v["verified_status"]) for v in vc["rows"] if v["draft_bucket"] == "BLOCKED")
        L += [f"**Two blind rechecks of every drafted-BLOCKED input ({sum(c.values())}); round 2 under the owner's explicit access policy (no restricted scraping, no paid services, no accounts):** " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())) + ". "
              "`BLOCKED_CONFIRMED` = both rounds say blocked; `BLOCKED_BY_POLICY` = round 2 finds the only route is one the policy forbids (round 1 had no policy); `RECLASSIFIED_TO_REQUIRES_COLLECTION` = both rounds find a permitted route; `BLOCKED_CONTESTED` = unresolved disagreement (counted as UNVERIFIED, never as blocked or computable). "
              "Round-2 verifiers reported low diligence on several keys (some did not open the catalog), so their answers are evidence, not proof.", ""]
    dih = VC.load_dih(); dih2 = VC.load_dir_answers("data_in_hand_round2")
    if dih2:
        c = collections.Counter(v["verified_status"] for v in vc["rows"] if v["draft_status"] == "DATA_IN_HAND")
        L += [f"**Blind verification of the {len(c and [1 for v in vc['rows'] if v['draft_status'] == 'DATA_IN_HAND'])} data-in-hand inputs (no builder existed), two rounds:** " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())) + ". NBA and NHL were re-judged in round 2 on REAL re-read columns (authorized read-only access to the owner's archive repos); a CONFIRMED that rests on a table whose rows were not re-read this session (NBA play-by-play and stints, NHL shot events) is downgraded to schema-only. For the others a downgrade in either round wins and CONFIRMED needs both.", ""]
    return L


def render(b: dict, sample: dict, vc: dict) -> str:
    s = b["summary"]; rows = b["rows"]; reg = b["registry"]; n = s["n_inputs"]
    P = EV.probes(); pc = collections.Counter(p["result"] for p in P.values())
    denied = sorted(p["id"] for p in P.values() if p["result"] == "POLICY_DENIED")
    L = ["# SIFT Alpha data foundation: raw-data audit of every catalog input (RESEARCH_ONLY)", "",
         "Generated by `python -m alpha_engine.input_research.data_foundation.audit` and `.report`; do not edit by hand. Artifacts: `research/input_research/data_foundation/` (`input_audit.json` per-input rows, `coverage_matrix.csv`, `datasets.json`, `sources.json`, `probes.json`, `summary.json`, `verification_sample.json`).", "",
         "> **Status: agent-verified in part; NOT human-verified; the readiness gate is the owner's.** Built by a Claude agent from measured probes, repo ledgers and the catalog's own provenance; every input then got a per-sport Claude reviewer verdict; then a feature replay on re-collected data, blind verifiers on the data-in-hand inputs, a blind sample of the other buckets and a blind recheck of every BLOCKED input (see VERIFIED COVERAGE). "
         "All verifiers are Claude agents: this is **not** human expert verification, many claims remain unverified (see the matrix), and **nothing here authorises predictive experimentation**, which remains PAUSED. No paid service was added, no live order was placed and no betting authority changed.", "",
         "The audited baseline is the approved catalog blueprint (commit `50dc65e`, pinned by `research/input_research/baseline_lock.json`): **{n} inputs, 170 archetypes, 1,030 declared gaps, all preserved**. Approval was of the blueprint only.", "",
         "VERIFIED_PLACEHOLDER", "",
         "## Draft buckets before verification (reconciliation only; superseded by the verified matrix above)", "",
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
    L += [""] + CP.render(CP.build()) + ["", "Capture progress (what the owner's workflows already record) and the inactive capture proposals: `docs/CAPTURE_PROPOSAL.md`. Network host proposal under the owner's access policy: `docs/NETWORK_ACCESS_PROPOSAL.md`.", ""]
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
    i = L.index("VERIFIED_PLACEHOLDER"); L[i:i + 1] = render_verified(vc)
    return "\n".join(L)


def main() -> int:
    b = A.build(write=True)
    vc = VC.build(write=True)
    (DF / "collection_plan.json").write_text(json.dumps(CP.build(), indent=0, sort_keys=True, ensure_ascii=False) + "\n")
    AP.main()
    CAPP.main()
    sample, key = verification_sample(b["rows"], b["registry"])
    (DF / "verification_sample.json").write_text(json.dumps(sample, indent=0, sort_keys=True, ensure_ascii=False) + "\n")
    (DF / "verification_answer_key.json").write_text(json.dumps(key, indent=0, sort_keys=True, ensure_ascii=False) + "\n")
    DOC.write_text(render(b, sample, vc))
    print("wrote", DOC.relative_to(ROOT), "and verification_sample.json:", sample["sample_size_inputs"], "inputs,", len(sample["datasets"]), "dataset replays")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
