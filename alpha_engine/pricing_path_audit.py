"""Family-specific pricing-path audit: is each driver input referenced anywhere in the code that PRICES this market family?

The path is an explicit, reviewable list of module globs per family (repo pinned by commit). An input's regex is matched against
identifiers/string keys (docstrings excluded). REFERENCED = at least one hit; NOT_FOUND = zero hits in the listed modules. NOT_FOUND
is a static, bounded negative (config-driven column names or modules outside the listed path can hide use), so it is reported as
`NOT_FOUND_IN_PRICING_PATH`, never as proof of non-use, and REFERENCED is never proof of correct use."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .model_use_probe import extract

REPOS = {"NFL": "chmoses98/nfl-edge-finder", "NBA": "chmoses98/nba-edge-finder", "CBB": "chmoses98/cbb-edge-finder"}
CBB_GAME = ["cbb_edge/app/project.py", "cbb_edge/app/sift.py", "cbb_edge/backtest/walkforward.py", "cbb_edge/model/*.py", "cbb_edge/ratings/*.py", "cbb_edge/rosters/overlay.py",
            "cbb_edge/rosters/prospective_score.py", "cbb_edge/sim/*.py", "cbb_edge/pricing/*.py"]
PATHS = {
    "NFL/TOTAL": ["nfl_edge/pricing/game_env.py", "nfl_edge/sim/prospective.py"],
    "NFL/TEAM_TOTAL": ["nfl_edge/pricing/game_env.py", "nfl_edge/sim/prospective.py"],
    "NFL/PLAYER_STAT": ["nfl_edge/engines/player/v5/*.py", "research/projection_foundation/**/*.py"],
    "NBA/player_points": ["research/projection_foundation/**/*.py"], "NBA/player_rebounds": ["research/projection_foundation/**/*.py"],
    "NBA/player_assists": ["research/projection_foundation/**/*.py"], "NBA/player_threes": ["research/projection_foundation/**/*.py"],
    "NBA/player_pra": ["research/projection_foundation/**/*.py"], "NBA/team_total": ["research/projection_foundation/**/*.py"],
    "NBA/period_total": ["research/projection_foundation/**/*.py"],
    "CBB/TOTAL": CBB_GAME,
    "CBB/HALF": CBB_GAME,
    "CBB/TEAM_TOTAL": CBB_GAME,
    "CBB/PLAYER_PROP": ["cbb_edge/players/*.py", "cbb_edge/model/*.py", "cbb_edge/pricing/*.py"],
}


def audit_family(fkey, repo_dir, drivers, regexes):
    repo_dir = Path(repo_dir)
    commit = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    files = sorted({p for g in PATHS[fkey] for p in repo_dir.glob(g) if p.is_file() and "test" not in p.name})
    ids = {str(p.relative_to(repo_dir)): extract(p) for p in files}
    out = {}
    for i, tier in drivers.items():
        rx = regexes.get(i)
        if not rx or i.startswith("m."):
            continue
        r = re.compile(rx, re.I)
        refs = []
        for f, ents in ids.items():
            hs = sorted({ln for n, k, ln in ents if r.search(n)})
            if hs:
                refs.append({"file": f, "lines": hs[:4]})
        out[i] = {"tier": tier, "state": "REFERENCED" if refs else "NOT_FOUND_IN_PRICING_PATH", "refs": refs[:4]}
    return {"repo": REPOS[fkey.split("/")[0]], "commit": commit, "path_globs": PATHS[fkey], "n_files": len(files), "files_total_lines": sum(len(p.read_text(errors="replace").splitlines()) for p in files), "inputs": out}
