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
                           "promoted_by_certification": certified,
                           "promoted_by_archived_data": sorted(k for k, v in inputs.items() if v["s"] in SPORTS and v["tr"]["state"] == "TRAINING_READY" and "cert" not in v["tr"]
                                                               and k in PHASE12_DATA_PROMOTIONS), "model_active": 0},
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


def md(o: dict) -> str:
    T, V, K, R = o["training_ready"], o["vault"], o["official_settlements"], o["settlement_repair"]
    mb = lambda b: f"{b / 1e6:,.1f} MB"
    L = ["# Phase 10: data preservation, certification and acquisition (RESEARCH_ONLY)", "",
         "Generated by `python -m alpha_engine.foundation.phase10` from committed evidence (`research/phase10/`, `research/certification/`, the generated catalog). "
         + o["notice"], "",
         "## Training-ready inputs", "", f"**{T['baseline']['training_ready_inputs']} -> {T['after']}** ({len(T['promoted_by_certification'])} promoted by dataset certification: "
         + ", ".join(T["promoted_by_certification"]) + f"). Model-active: {T['model_active']}.", "", "| Sport | Training-ready inputs |", "|---|---|"]
    L += [f"| {s} | {n} |" for s, n in T["by_sport"].items()]
    L += ["", "## Dataset versions (append-only)", "", "| Sport | Hash | Rows | Training-ready | Builder |", "|---|---|---|---|---|"]
    L += [f"| {v['sport']} | `{v['hash']}` | {v['rows']:,} | {'yes' if v['training_ready'] else 'no'} | {v['builder']} |" for v in o["dataset_versions"]]
    L += ["", "## Private vault", "", f"{V['repository']}: **{mb(V['totals'].get('stored_bytes', 0))}** stored in {V['totals'].get('archives', 0)} archives, {V['totals'].get('pins', 0)} hash-only pins. "
          f"Verification: {V['verify'].get('summary', 'not recorded')}. Restore test: {V['restore_test'].get('summary', 'not recorded')}.", "",
          "| Sport | Archives | Stored | Datasets |", "|---|---|---|---|"]
    L += [f"| {s} | {x['archives']} | {mb(x['stored_bytes'])} | {'; '.join(d['dataset'] + ' ' + d['season'] for d in x['datasets'])} |" for s, x in V["by_sport"].items()]
    L += ["", "## Official Kalshi settlements recovered", "", K.get("note", ""), "", f"Total: **{K.get('total_markets', 0):,} markets**, {K.get('total_events', 0):,} events. Settlement cutoff between the historical and live tiers: {(K.get('cutoff') or {}).get('market_settled_ts')}.", "",
          "| Sport | Markets | Events | First | Last | Value-settled | Administrative (literal, untraded) | Literal, traded | Fair-price | Other |", "|---|---|---|---|---|---|---|---|---|---|"]
    for x in K.get("sports", []):
        c = x["classes"]; known = ("VALUE_SETTLED", "ADMIN_LITERAL_UNTRADED", "LITERAL_VALUE_TRADED", "FAIR_PRICE_SETTLEMENT")
        L.append(f"| {x['sport']} | {x['markets']:,} | {x['events']:,} | {x['first']} | {x['last']} | " + " | ".join(f"{c.get(k, 0):,}" for k in known) + f" | {sum(v for k, v in c.items() if k not in known):,} |")
    if R:
        L += ["", "## NBA 2nd-half overtime settlement repair", "", f"Status: {R['status']}. {R['pr']}.", "", R["summary"], "", f"Tests: {R['tests']}."]
    for title, key, f in (("Collected this phase (content-verified)", "collection", lambda c: f"* **{c['id']}** ({c['sport']}, {c['kind'].lower()}, {'archived' if c['archived'] else 'NOT archived'}): {c['detail']}"),
                          ("Postgame gaps closed (against PR #80's per-game ledger)", "gaps_closed", lambda g: f"* **{g['sport']} {g['category']}**: {g['games']:,} games. {g['detail']}"),
                          ("Remaining gaps", "remaining_gaps", lambda g: f"* **{g['sport']} {g['category']}** ({g['kind'].lower()}): {g['detail']}"),
                          ("Complete versus partial datasets", "completeness", lambda c: f"* **{c['sport']}** {c['dataset']}: {c['status'].lower()}, {c['coverage'].lower()}. {c['detail']}"),
                          ("Blockers", "blockers", lambda b: f"* ({b['kind'].lower()}; {', '.join(b['sports'])}) {b['text']}")):
        L += ["", f"## {title}", ""] + [f(x) for x in o[key]]
    L += ["", "## Next steps", ""] + [f"{i + 1}. {t}" for i, t in enumerate(o["next"])]
    return "\n".join(L) + "\n"


# Inputs already built and verified FULL before Phase 12 whose only failing check was "raw data held"; the vault ledger closed it.
PHASE12_DATA_PROMOTIONS = {"CFB:cfb.pythag_luck"}


def main() -> int:
    out = build(); write_json(OPS / "phase10_progress.json", out)
    (ROOT / "docs/PHASE10_DATA_PRESERVATION.md").write_text(md(out))
    print("phase10: training-ready", out["training_ready"]["baseline"]["training_ready_inputs"], "->", out["training_ready"]["after"], "| vault", out["vault"]["totals"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
