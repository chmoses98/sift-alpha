"""python -m alpha_eval {report|coverage|example}. File IO only; no network; no writes outside --out-dir."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import coverage as cov
from .grading import grade_all
from .report import build_report, to_markdown
from .schema import SCHEMA_VERSION


def _jsonl(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()] if p else []


def _write(out: Path, stem: str, rep: dict):
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.json").write_text(json.dumps(rep, indent=1, sort_keys=True, default=str) + "\n")
    (out / f"{stem}.md").write_text(to_markdown(rep))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="alpha_eval", description=f"SIFT Alpha evaluation standard {SCHEMA_VERSION} (RESEARCH_ONLY)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("--forecasts", required=True); r.add_argument("--outcomes", required=True)
    r.add_argument("--quotes"); r.add_argument("--fills")
    r.add_argument("--kind", choices=("daily", "cumulative"), default="cumulative"); r.add_argument("--date")
    r.add_argument("--title", default=""); r.add_argument("--out-dir", required=True)
    c = sub.add_parser("coverage"); c.add_argument("--out-dir", required=True)
    e = sub.add_parser("example"); e.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    if a.cmd == "report":
        g = grade_all(_jsonl(a.forecasts), _jsonl(a.outcomes), _jsonl(a.quotes), _jsonl(a.fills))
        _write(out, f"{a.kind}_{a.date or 'all'}", build_report(g, kind=a.kind, date=a.date, title=a.title))
    elif a.cmd == "coverage":
        m = cov.build()
        out.mkdir(parents=True, exist_ok=True)
        (out / "coverage_matrix.json").write_text(json.dumps(m, indent=1, sort_keys=True) + "\n")
        (out / "COVERAGE_MATRIX.md").write_text(cov.to_markdown(m))
    else:
        from .synthetic import generate
        F, O, Q, X = generate()
        g = grade_all(F, O, Q, X)
        t = "SYNTHETIC FIXTURE - exercises code paths; NOT evidence about any real model or market"
        _write(out, "example_cumulative", build_report(g, kind="cumulative", title=t))
        _write(out, "example_daily_2026-11-03", build_report(g, kind="daily", date="2026-11-03", title=t))
    return 0
