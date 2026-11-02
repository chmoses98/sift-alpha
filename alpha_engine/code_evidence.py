"""Static code-reference evidence per (sport, input): where in each repo's code the input is referenced.

Usage: python -m alpha_engine.code_evidence SRC_ROOT. A reference is NOT proof of correct collection/use.
Absence of a reference (with the keyword regex recorded) is the evidence for "no code reference found"."""
import json, re, subprocess, sys
from pathlib import Path
from .input_catalog import INPUTS, COMMON
from .input_keywords import KW
from .master_inventory import REPO, head, AUDIT, SPORTS

DIRS = {"NFL": ["nfl_edge", "scripts", ".github"], "CFB": ["src", "scripts", ".github"], "NBA": ["src", "scripts", ".github"],
        "CBB": ["cbb_edge", "scripts", ".github"], "NHL": ["src", "scripts", ".github"], "MLB": ["lib", "scripts", ".github", "api"],
        "SOCCER": ["soccer_edge", "research", "scripts", ".github"], "TENNIS": ["tennis_edge", "scripts", ".github"]}
COLLECT = re.compile(r"ingest|fetch|collect|capture|download|probe|discover|archive|workflows|sources|provider|scrape|snapshot|adapter|harvest|pull|vintage", re.I)
MODEL = re.compile(r"model|feature|project|sim/|simulat|engine|predict|pricing|forecast|elo|rating|handicap|shadow|calibrat|distribution|signal", re.I)


def ids_for(sport):
    own = [l.split("|")[0] for l in INPUTS[sport].splitlines()]
    return own + [l.split("|")[0] for l in COMMON.splitlines()]


def scan(sport, repo_dir):
    out = {}
    dirs = [str(repo_dir / d) for d in DIRS[sport] if (repo_dir / d).exists()]
    for iid in ids_for(sport):
        rx = KW[iid]
        r = subprocess.run(["rg", "-l", "-i", "-g", "!*test*", "-g", "!*.json", "-g", "!*.md", "-e", rx, *dirs], capture_output=True, text=True)
        files = [f.replace(str(repo_dir) + "/", "") for f in r.stdout.split("\n") if f]
        col = [f for f in files if COLLECT.search(f)]; mod = [f for f in files if MODEL.search(f)]
        out[iid] = {"regex": rx, "files_total": len(files), "collect_files": len(col), "model_files": len(mod),
                    "collect_examples": col[:3], "model_examples": mod[:3], "other_examples": [f for f in files if f not in col and f not in mod][:2]}
    return out


def main(argv=None):
    src = Path((argv or sys.argv[1:])[0]); nfl = Path("/home/user/nfl-edge-finder")
    res = {"schema_version": "audit-1.0", "note": "keyword hits in code; a hit is NOT proof of correct use, absence is limited by the recorded regex", "sports": {}}
    for sp in SPORTS:
        d = nfl if sp == "NFL" else src / REPO[sp]
        res["sports"][sp] = {"repo": "chmoses98/" + REPO[sp], "commit": head(d), "inputs": scan(sp, d)}
        print(sp, sum(1 for v in res["sports"][sp]["inputs"].values() if v["files_total"]), "/", len(res["sports"][sp]["inputs"]), "inputs with code refs")
    (AUDIT / "code_evidence.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
