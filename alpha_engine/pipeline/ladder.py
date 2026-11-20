"""Input adoption ladder: one level per catalog input, every level above CERTIFIED backed by a committed evidence pointer (RESEARCH_ONLY).

    python -m alpha_engine.pipeline.ladder            # writes research/pipeline/input_ladder.json
    python -m alpha_engine.pipeline.ladder --check    # fails if the committed ladder is stale or any registry claim fails its evidence check

Levels (never merged; an input sits at the HIGHEST level whose requirements are met, and every lower level must hold too):
  0 EXISTS                    in the approved catalog (distinct_inputs.csv)
  1 CALCULATED                a builder computed it (certified, downgraded, PIT-quarantined, or the derived engine's own checks passed)
  2 CERTIFIED                 VERIFIED_FULL / PARTIAL / PROXY in the data-foundation ledger (replay + blind exact match). Read from the ledger, never claimed.
  3 EXPERIMENTAL_ADOPTION     an experiment whose frozen spec NAMES this input's columns consumed it (registry entry; the spec file must contain the column names)
  4 PREDICTION_VERIFIED       a frozen experiment showed better outcome prediction than the existing projection on chronologically unseen games
                              (registry entry; evidence pointer must hold a paired difference whose 95% CI excludes zero in the improving direction)
  5 PRICE_AWARE_VERIFIED      a frozen selection rule using it beat fee-adjusted executable prices on an independent forward sample (ROI 95% CI lower bound > 0)
  6 PRODUCTION_CONSUMED       a producer repository consumes it in published output (owner-approved activation; evidence = producer path). None today.
Keyword matches in source code are NOT adoption: only an explicit registry entry whose evidence check passes moves an input above level 2.
Columns that experiments consumed but that are NOT catalog inputs (e.g. intermediate base columns of a certified builder) are listed separately and
never counted as certified adoption.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REG = ROOT / "research/pipeline/adoption_registry.json"
OUT = ROOT / "research/pipeline/input_ladder.json"
SUMMARY = ROOT / "research/pipeline/ladder_summary.json"     # compact copy for the dashboard
LEVELS = ("EXISTS", "CALCULATED", "CERTIFIED", "EXPERIMENTAL_ADOPTION", "PREDICTION_VERIFIED", "PRICE_AWARE_VERIFIED", "PRODUCTION_CONSUMED")
CERT = {"VERIFIED_FULL", "VERIFIED_PARTIAL", "VERIFIED_PROXY"}
CALC = CERT | {"DOWNGRADED_BY_VERIFIER", "PIT_QUARANTINED"}


def pointer(doc, ptr: str):
    for part in [p for p in ptr.split("/") if p]:
        doc = doc[int(part)] if isinstance(doc, list) else doc[part]
    return doc


def check_claim(c: dict) -> list[str]:
    """Return problems with one registry claim (empty list = evidence holds)."""
    bad = []; ev = c.get("evidence") or {}; f = ROOT / ev.get("file", "")
    if not ev.get("file") or not f.exists():
        return [f"evidence file missing: {ev.get('file')}"]
    lvl = c["level"]
    if lvl == "EXPERIMENTAL_ADOPTION":
        txt = f.read_text(errors="ignore")
        bad += [f"column {col} not named in {ev['file']}" for col in c.get("columns", []) if col not in txt]
        if not c.get("columns"):
            bad.append("no columns named")
    elif lvl in ("PREDICTION_VERIFIED", "PRICE_AWARE_VERIFIED"):
        try:
            v = pointer(json.loads(f.read_text()), ev["pointer"])
        except (KeyError, IndexError, ValueError, TypeError) as e:
            return [f"pointer {ev.get('pointer')} unresolved: {e}"]
        lo, hi = (v if isinstance(v, list) else (None, None))
        if lvl == "PREDICTION_VERIFIED" and not (hi is not None and ((ev.get("direction") == "lower_is_better" and hi < 0) or (ev.get("direction") == "higher_is_better" and lo > 0))):
            bad.append(f"CI {v} does not exclude zero in direction {ev.get('direction')}")
        if lvl == "PRICE_AWARE_VERIFIED" and not (lo is not None and lo > 0):
            bad.append(f"ROI CI {v} lower bound is not > 0")
        if not ev.get("frozen_spec_sha256"):
            bad.append("no frozen spec hash recorded")
    elif lvl == "PRODUCTION_CONSUMED":
        if not ev.get("producer_repo") or not ev.get("owner_approval"):
            bad.append("production claim needs producer_repo and owner_approval")
    else:
        bad.append(f"level {lvl} cannot be claimed in the registry")
    return bad


def build() -> dict:
    inp = list(csv.DictReader((ROOT / "research/input_research/market_input_map/distinct_inputs.csv").open()))
    derived = {(r["sport"], r["id"]): r for r in json.loads((ROOT / "research/audit/derived_inputs.json").read_text())["inputs"]}
    reg = json.loads(REG.read_text()); claims = reg.get("claims", []); problems = {}
    held: dict = {}
    for i, c in enumerate(claims):
        p = check_claim(c)
        if p:
            problems[f"claims[{i}] {c.get('level')} {c.get('inputs')}"] = p
            continue
        for key in c.get("inputs", []):
            held.setdefault(key, set()).add(c["level"])
    rows = []
    for r in inp:
        key = r["input_key"]; vs = r["verified_status"]; lv = "EXISTS"
        if vs in CALC or str((derived.get((r["sport"], r["input_id"])) or {}).get("status", "")).startswith("COMPUTED"):
            lv = "CALCULATED"
        if vs in CERT:
            lv = "CERTIFIED"
            for nxt in LEVELS[3:]:                       # a higher level counts only if every level between holds
                if nxt in held.get(key, set()):
                    lv = nxt
                else:
                    break
        rows.append({"input_key": key, "sport": r["sport"], "verified_status": vs, "level": lv, "claims": sorted(held.get(key, set()))})
    orphan = sorted(k for k in held if k not in {r["input_key"] for r in inp})
    if orphan:
        problems["claims for inputs not in the catalog"] = orphan
    uncert = sorted(k for k, s in held.items() if k in {r["input_key"]: r for r in rows} and {r["input_key"]: r for r in rows}[k]["verified_status"] not in CERT)
    if uncert:
        problems["claims above CERTIFIED for uncertified inputs (not counted)"] = uncert
    cnt = Counter(r["level"] for r in rows); at_least = {L: sum(cnt[x] for x in LEVELS[i:]) for i, L in enumerate(LEVELS)}
    by_sport = {}
    for r in rows:
        s = by_sport.setdefault(r["sport"], {L: 0 for L in LEVELS}); s[r["level"]] += 1
    return {"schema": "input-ladder-1.0", "status": "RESEARCH_ONLY", "levels": list(LEVELS), "counts_at_level": {L: cnt.get(L, 0) for L in LEVELS},
            "counts_at_least": at_least, "by_sport": by_sport, "registry_problems": problems, "non_catalog_columns_consumed": reg.get("non_catalog_columns_consumed", []),
            "note": "Levels 3-6 move only through explicit registry claims whose evidence check passes; keyword matches never count.", "inputs": rows}


def main(a=None) -> int:
    a = a or sys.argv[1:]; d = build(); txt = json.dumps(d, indent=1) + "\n"; stxt = json.dumps({k: v for k, v in d.items() if k != "inputs"}, indent=1) + "\n"
    if "--check" in a:
        if d["registry_problems"]:
            raise SystemExit(f"registry claims fail their evidence checks: {d['registry_problems']}")
        if not OUT.exists() or OUT.read_text() != txt or not SUMMARY.exists() or SUMMARY.read_text() != stxt:
            raise SystemExit("input_ladder.json is stale: run python -m alpha_engine.pipeline.ladder")
        print("ladder up to date"); return 0
    OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text(txt); SUMMARY.write_text(stxt)
    print(d["counts_at_least"], "problems:", d["registry_problems"] or "none"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
