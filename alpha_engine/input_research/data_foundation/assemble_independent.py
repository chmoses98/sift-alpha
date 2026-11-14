"""Assemble blind re-implementation verdicts (agent JSON outputs) into verification/independent/<family>.json, keyed by input id and spec column (RESEARCH_ONLY).

    python -m alpha_engine.input_research.data_foundation.assemble_independent FAMILY OUT.json VERDICTS.json [LATER_VERDICTS.json ...] --module features.nfl_pbp_ext
Later verdict files override earlier ones for the metrics they name (a re-check after a defect fix). Spec column c maps to metric c minus a trailing '_pre'; if a metric is absent the column is MISSING (fail closed).
"""
import importlib
import json
import sys
from pathlib import Path


def main(a=None) -> int:
    a = a or sys.argv[1:]; mod = a[a.index("--module") + 1]; pos = [x for x in a if x != "--module" and x != mod]
    fam, out, files = pos[0], pos[1], pos[2:]
    m = importlib.import_module("alpha_engine." + mod); cols: dict = {}; notes: list = []
    for f in files:
        d = json.loads(Path(f).read_text()); cols.update(d["columns"]); notes += d.get("ambiguities", [])
    res = {}
    for s in m.specs():
        res[s.catalog_id] = {"columns": {c: cols.get(c) or cols.get(c[:-4] if c.endswith("_pre") else c) or cols.get(c[2:-4]) or {"verdict": "MISSING"} for c in s.columns}}
    Path(out).write_text(json.dumps({"family": fam, "verifier": "blind Claude agent re-implementation (agent verification, not human)", "verdict_files": [Path(f).name for f in files], "inputs": res, "ambiguities": notes}, indent=1) + "\n")
    print({k: sorted({c["verdict"] for c in v["columns"].values()}) for k, v in res.items()}); return 0


if __name__ == "__main__":
    raise SystemExit(main())
