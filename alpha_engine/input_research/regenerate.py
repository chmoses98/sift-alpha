"""Canonical, verified regeneration of the catalog layer and its generated artifacts (RESEARCH_ONLY).

    python -m alpha_engine.input_research.regenerate --check            # run the pipeline in a scratch copy; fail if ANY tracked artifact would change
    python -m alpha_engine.input_research.regenerate --apply            # run the pipeline in this checkout (writes catalogs, reviews, gate, tracker)
    python -m alpha_engine.input_research.regenerate --derive-overlay   # (re)derive completeness/baseline_overlay from the approved catalogs; deliberate, reviewed action

Pipeline order (each stage reads the previous stage's output; the order is part of the contract):
  1 completeness.integrate        merge review records into the catalog (new inputs, interactions, mechanism, required data)
  2 input_audit.apply             audit verdicts -> raw_data / market_free / provenance / audit_flag (a later OK/FIXED verdict CLEARS an earlier flag)
  3 input_audit.apply_patches     input-definition patches
  4 input_audit.apply_archetype_patches   archetype re-homing, detach/attach, role changes
  5 baseline_overlay.apply        restore the approved baseline wherever it deliberately differs from the source layers (guarded by hashes; raises on drift)
  6 completeness gate             gate.json, summary.json, series_remap_proposals.json
  7 data_foundation.report        research/input_research/data_foundation/*, docs/DATA_FOUNDATION.md (from committed probes, ledgers, reviewer files)
  8 tracker                       progress.json, docs/RESEARCH_TRACKER.md
The one-shot bootstrap scripts (catalog_expand, catalog_unregistered, register_new_inputs) are NOT part of the pipeline and must not be re-run: they overwrite catalogs.
`--check` is what makes the approved baseline impossible to regress silently; baseline_lock.py additionally pins the catalogs' content hashes and the 1,649 / 170 / 1,030 totals.
"""
from __future__ import annotations

import filecmp
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COPY = ("alpha_engine", "research", "docs")
# everything the pipeline may write; compared byte-for-byte by --check
TRACKED = ("research/input_research", "research/audit/input_research", "docs/RESEARCH_TRACKER.md", "docs/DATA_FOUNDATION.md", "docs/NETWORK_ACCESS_PROPOSAL.md", "docs/CAPTURE_PROPOSAL.md")
SKIP_DIRS = {"__pycache__"}


def run_pipeline() -> dict:
    from . import baseline_overlay, completeness, input_audit
    stats = {"integrate": completeness.integrate(write=True)}
    stats["audit_apply"] = input_audit.apply()
    stats["patches"] = input_audit.apply_patches()
    stats["archetype_patches"] = input_audit.apply_archetype_patches()
    stats["baseline_overlay"] = baseline_overlay.apply()
    saved = sys.argv
    sys.argv = [saved[0]]            # completeness.main reads --evidence from argv: never regenerate pre-review evidence packs here
    try:
        completeness.main()
    finally:
        sys.argv = saved
    from .data_foundation import report as df_report
    df_report.main()                 # data-foundation audit artifacts + docs/DATA_FOUNDATION.md (reads the committed probes, ledgers, review files)
    from . import tracker
    p = tracker.compute()
    (tracker.IR / "progress.json").write_text(json.dumps(p, indent=0, sort_keys=True))
    (ROOT / "docs/RESEARCH_TRACKER.md").write_text(tracker.render(p))
    return stats


def _files(base: Path) -> dict[str, Path]:
    out = {}
    for t in TRACKED:
        p = base / t
        if p.is_file():
            out[t] = p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not (set(f.parts) & SKIP_DIRS):
                    out[str(f.relative_to(base))] = f
    return out


def scratch_copy() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="sift-regen-"))
    for d in COPY:
        shutil.copytree(ROOT / d, tmp / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return tmp


def diff_trees(a: Path, b: Path) -> dict:
    fa, fb = _files(a), _files(b)
    changed = sorted(k for k in fa.keys() & fb.keys() if not filecmp.cmp(fa[k], fb[k], shallow=False))
    return {"changed": changed, "added_by_pipeline": sorted(fb.keys() - fa.keys()), "removed_by_pipeline": sorted(fa.keys() - fb.keys())}


def check(keep: bool = False) -> dict:
    """Run the pipeline twice in a scratch copy (second run proves idempotence) and report every tracked file that differs from this checkout."""
    tmp = scratch_copy()
    try:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        runs = []
        for i in (1, 2):
            r = subprocess.run([sys.executable, "-m", "alpha_engine.input_research.regenerate", "--apply"], cwd=tmp, capture_output=True, text=True, env=env)
            if r.returncode != 0:
                return {"ok": False, "stage": f"pipeline run {i} failed", "stderr": r.stderr[-3000:], "changed": [], "added_by_pipeline": [], "removed_by_pipeline": []}
            runs.append(diff_trees(ROOT, tmp))
        d = runs[0]
        idem = runs[0] == runs[1]
        return {"ok": not (d["changed"] or d["added_by_pipeline"] or d["removed_by_pipeline"]) and idem, "idempotent_second_run": idem, **d}
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def derive_overlay() -> dict:
    """Derive the baseline overlay in a SCRATCH copy (the pipeline also rewrites review records) and copy only the overlay files back into this checkout."""
    tmp = scratch_copy()
    try:
        r = subprocess.run([sys.executable, "-m", "alpha_engine.input_research.regenerate", "--derive-overlay-here"], cwd=tmp, capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        if r.returncode != 0:
            raise SystemExit(r.stderr[-3000:])
        dst = ROOT / "research/input_research/completeness/baseline_overlay"
        shutil.rmtree(dst, ignore_errors=True)
        src = tmp / "research/input_research/completeness/baseline_overlay"
        if src.exists():
            shutil.copytree(src, dst)
        return json.loads(r.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _derive_overlay_here() -> dict:
    """Regenerate the catalog from the source layers (stages 1-4) and record every field where the approved catalog differs."""
    from . import baseline_overlay as BO
    from . import catalog as cat
    from . import completeness, input_audit
    approved = {s: cat.load(s) for s in completeness.SPORTS}
    # the overlay itself must not influence the derivation
    old = {}
    if BO.OD.exists():
        for f in BO.OD.glob("*.json"):
            old[f] = f.read_text(); f.unlink()
    completeness.integrate(write=True); input_audit.apply(); input_audit.apply_patches(); input_audit.apply_archetype_patches()
    BO.OD.mkdir(parents=True, exist_ok=True)
    stats = {}
    for s in completeness.SPORTS:
        gen = cat.load(s)
        ov = BO.derive_sport(gen, approved[s])
        ov = {"schema_version": "baseline-overlay-1.0", "sport": s, "approved_commit": "50dc65e32e0a2c57a700905ceb986d6198ecf219", **ov}
        if any(ov[k] for k in ("inputs", "archetypes", "blueprints", "top_level")):
            (BO.OD / f"{s}.json").write_text(json.dumps(ov, indent=1, ensure_ascii=False) + "\n")
        stats[s] = {"inputs": len(ov["inputs"]), "archetypes": len(ov["archetypes"]), "archetype_fields": sum(len(v) for v in ov["archetypes"].values())}
        (cat.CATALOG_DIR / f"{s}.json").write_text(json.dumps(approved[s], indent=1, ensure_ascii=False) + "\n")   # leave the checkout's catalogs exactly as approved
    return stats


def main(argv=None) -> int:
    a = (argv if argv is not None else sys.argv)[1:]
    if "--apply" in a:
        print(json.dumps(run_pipeline(), indent=1, default=str)); return 0
    if "--derive-overlay-here" in a:
        print(json.dumps(_derive_overlay_here())); return 0
    if "--derive-overlay" in a:
        print(json.dumps(derive_overlay(), indent=1)); return 0
    r = check(keep="--keep" in a)
    print(json.dumps(r, indent=1))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
