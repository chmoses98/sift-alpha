"""Per-sport archive readers.  Each adapter exposes SPORT, specs(), and load(roots) -> (games, observations, notes).

`roots` maps a name to a local directory: the owner's sport repository checkout (or a data-branch worktree) and a
reference directory holding the league's own schedule, used ONLY as the expected-games denominator.  Adapters read;
they never write to an archive and never fetch from the network.
"""
import gzip
import json
from pathlib import Path


def jsonl(path):
    """Yield dict rows from .jsonl / .jsonl.gz; unparseable lines are skipped and counted by the caller if needed."""
    path = Path(path)
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def has(row, *fields):
    """Fields that are present and non-null on this row (0 is a value; None / '' are not)."""
    return {f for f in fields if row.get(f) not in (None, "")}


def need(roots, name):
    p = roots.get(name)
    if not p or not Path(p).exists():
        raise FileNotFoundError(f"root '{name}' not provided or missing: {p!r}")
    return Path(p)
