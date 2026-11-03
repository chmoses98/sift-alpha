"""Collect REPO-REPORTED model readiness per family from sport repos' projection-data branches (verbatim, with
repo/branch/commit/sha256 provenance). Alpha does NOT reproduce these; it only records what is reported.
Usage: python -m alpha_engine.model_validation SPORT=CHECKOUT_DIR [SPORT=CHECKOUT_DIR ...]
(CHECKOUT_DIR is a checkout of the repo's projection-data branch.)"""
import hashlib, json, subprocess, sys
from pathlib import Path

REPOS = {"NBA": "chmoses98/nba-edge-finder", "NHL": "chmoses98/NHL-edge-finder"}
PATHS = {"NBA": "projections/nba/latest.json", "NHL": "projections/nhl/latest.json"}
OUT = Path(__file__).resolve().parent.parent / "research" / "audit" / "model_validation.json"


def read(sport, d):
    d = Path(d); f = d / PATHS[sport]
    raw = f.read_bytes(); doc = json.loads(raw)
    commit = subprocess.check_output(["git", "-C", str(d), "rev-parse", "HEAD"], text=True).strip()
    fam = {k: {"model": v.get("model"), "readiness": v.get("readiness"), "reported": v.get("reason")} for k, v in doc["families"].items()}
    src = {"sport": sport, "repo": REPOS[sport], "branch": "projection-data", "commit": commit, "path": PATHS[sport],
           "sha256": hashlib.sha256(raw).hexdigest(), "data_asof_utc": doc.get("data_asof_utc")}
    return src, fam


def main(argv=None):
    out = {"schema_version": "validation-1.0",
           "note": "REPO-REPORTED holdout/prospective results, copied verbatim; NOT independently reproduced by Alpha. Family-level readiness says nothing about any single input (no ablation here). Player families are conditional on the player playing.",
           "sources": [], "sports": {}}
    for a in (argv or sys.argv[1:]):
        sport, d = a.split("=", 1)
        src, fam = read(sport, d)
        out["sources"].append(src); out["sports"][sport] = {"families": fam}
    OUT.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    o = main()
    for s, v in o["sports"].items():
        print(s, {k: x["readiness"] for k, x in v["families"].items()})
