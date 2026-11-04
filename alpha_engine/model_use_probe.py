"""Static source-to-model use probe over a sport-repo checkout (read-only, offline).

For each registry input with a recorded code regex, parse every .py file with `ast` and record IDENTIFIER-level hits (names,
attributes, keyword args, string keys) -- docstrings and comments are ignored, so prose mentions never count. Hits are classified
by path role:
  collector : path mentions collect/capture/fetch/source/ingest/archive/scrape
  model     : path mentions model/engine/sim/pricing/predict/projection/feature/signal
  test      : tests/
A model-role READ of the identifier is a *static consumption candidate*. It is NOT proof that the value reaches a published
projection (that needs an executed run); consumers must treat it as PARTIAL evidence (scope STATIC_CANDIDATE). Pins the checkout commit.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

ROLE_RX = {"collector": re.compile(r"collect|capture|fetch|source|ingest|archive|scrape", re.I),
           "model": re.compile(r"model|engine|sim|pricing|predict|projection|feature|signal", re.I)}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist"}
MAX_REFS = 12


def role(rel: str) -> str:
    parts = rel.lower().split("/")
    if "tests" in parts or parts[-1].startswith("test_"):
        return "test"
    if ROLE_RX["collector"].search(rel):
        return "collector"
    if ROLE_RX["model"].search(rel):
        return "model"
    return "other"


def extract(path: Path) -> list[tuple[str, str, int]]:
    """Parse a file ONCE: [(identifier_or_key, kind, line)]. Docstrings are excluded (prose is not use)."""
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except (SyntaxError, ValueError, RecursionError):
        return []
    doc = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(getattr(n.body[0], "value", None), ast.Constant) and isinstance(n.body[0].value.value, str):
            doc.add(id(n.body[0].value))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            out.append((n.id, "read" if isinstance(n.ctx, ast.Load) else "write", n.lineno))
        elif isinstance(n, ast.Attribute):
            out.append((n.attr, "read" if isinstance(n.ctx, ast.Load) else "write", n.lineno))
        elif isinstance(n, ast.arg):
            out.append((n.arg, "param", n.lineno))
        elif isinstance(n, ast.keyword) and n.arg:
            out.append((n.arg, "kwarg", getattr(n, "lineno", 0)))
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((n.name, "def", n.lineno))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc and len(n.value) < 60:
            out.append((n.value, "key", n.lineno))
    return out


def probe(repo_dir: Path, inputs: dict[str, str]) -> dict:
    """inputs: {input_id: regex}. Returns {input_id: {...refs by role...}}."""
    repo_dir = Path(repo_dir)
    commit = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    rxs = {i: re.compile(r, re.I) for i, r in inputs.items() if r}
    out = {i: {"collector": [], "model": [], "test": [], "other": []} for i in rxs}
    files = [p for p in repo_dir.rglob("*.py") if not (set(p.relative_to(repo_dir).parts) & SKIP_DIRS)]
    for p in sorted(files):
        rel = str(p.relative_to(repo_dir))
        r = role(rel)
        ids = extract(p)
        if not ids:
            continue
        uniq = {}
        for name, kind, line in ids:
            uniq.setdefault(name, []).append((kind, line))
        for i, rx in rxs.items():
            hs = [(k, ln) for name, v in uniq.items() if rx.search(name) for k, ln in v]
            if hs:
                out[i][r].append({"file": rel, "n": len(hs), "lines": sorted({ln for _, ln in hs})[:6], "kinds": sorted({k for k, _ in hs})})
    res = {}
    for i, d in out.items():
        reads = [f for f in d["model"] if {"read", "kwarg", "key", "param"} & set(f["kinds"])]
        res[i] = {"commit": commit, "collector_files": len(d["collector"]), "model_files": len(d["model"]), "model_read_files": len(reads), "test_files": len(d["test"]),
                  "refs": {k: sorted(v, key=lambda f: -f["n"])[:MAX_REFS] for k, v in d.items() if k != "other"},
                  "static_consumption_candidate": bool(reads and d["collector"])}
    return res
