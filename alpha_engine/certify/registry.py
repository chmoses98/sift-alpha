"""Versioned dataset registry + per-game index joining postgame completeness and point-in-time features (RESEARCH_ONLY).

Two artefacts, both identifiers / hashes / status codes only (no provider rows):

* `research/certification/dataset_versions.json`: APPEND-ONLY. One entry per (sport, canonical_sha256) dataset version with
  its builder, spec version, row count and readiness status. A changed builder, spec or source produces a NEW entry
  (new hash); an existing entry is never edited except to set `superseded_by`. `tests/test_certify_registry.py` enforces
  the shape and uniqueness; git history makes any rewrite visible.
* `research/certification/game_index/<SPORT>.csv.gz`: one row per expected FINAL game from PR #80's ledger
  (postgame-completeness side) plus every dataset game, with `recon_class` (see reconcile.py), `dataset_version`
  (short hash of the version that holds the game's pre-game feature row) and `outcome_check`.
  A = dataset outcome agrees with an independent result table, D = disagrees, - = not checked.

The same historical game therefore resolves to (a) its postgame completeness status in PR #80's ledger and (b) an immutable
feature-row version. A model change cannot silently rewrite either one.

    python -m alpha_engine.certify.registry --reconcile R.json --datasets DIR --ledgers DIR --outcomes cbb=OUT.json,cfb=OUT.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .reconcile import SPORTS, reconcile

ROOT = Path(__file__).resolve().parents[2] / "research" / "certification"
VERSIONS = ROOT / "dataset_versions.json"


def load_versions() -> dict:
    return json.loads(VERSIONS.read_text()) if VERSIONS.exists() else {"schema": "dataset-versions-1.0", "status": "RESEARCH_ONLY",
                                                                      "policy": "append-only; a new builder/spec/source = a new entry; never edit an entry except superseded_by",
                                                                      "versions": []}


def register(v: dict, entry: dict) -> dict:
    """Append `entry` unless the same (sport, canonical_sha256) already exists. Never mutates an existing entry."""
    for e in v["versions"]:
        if e["sport"] == entry["sport"] and e["canonical_sha256"] == entry["canonical_sha256"]:
            return e
    v["versions"].append(entry)
    return entry


def build_index(sport: str, ledger: pd.DataFrame, d: pd.DataFrame, rec_cls: pd.Series, version: str, outcome_ok: set | None,
                outcome_bad: set | None) -> pd.DataFrame:
    L = ledger[ledger.state == "FINAL"][["season", "date", "game_id"]].copy(); L["game_id"] = L.game_id.astype(str)
    D = d[["game_id", "season", "date"]].assign(game_id=lambda x: x.game_id.astype(str), season=lambda x: x.season.astype(str),
                                                 date=lambda x: pd.to_datetime(x.date).dt.date.astype(str))
    g = pd.concat([L, D[~D.game_id.isin(set(L.game_id))]], ignore_index=True)
    g["recon_class"] = g.game_id.map(rec_cls).fillna("DATASET_ONLY")
    ids = set(D.game_id)
    g["dataset_version"] = [version if x in ids else "" for x in g.game_id]
    if outcome_ok is None:
        g["outcome_check"] = "-"
    else:
        g["outcome_check"] = ["D" if x in outcome_bad else ("A" if x in outcome_ok else "-") for x in g.game_id]
    return g.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)


def main(x=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--datasets", required=True); ap.add_argument("--ledgers", required=True)
    ap.add_argument("--outcomes", default="", help="SPORT=leakage.json,... (uses its outcomes block)")
    ap.add_argument("--entries", required=True, help="JSON file: list of version entries to register (sport, canonical_sha256, ...)")
    a = ap.parse_args(x)
    v = load_versions()
    for e in json.loads(Path(a.entries).read_text()):
        register(v, e)
    VERSIONS.parent.mkdir(parents=True, exist_ok=True); VERSIONS.write_text(json.dumps(v, indent=1) + "\n")
    outs = dict(kv.split("=", 1) for kv in a.outcomes.split(",") if kv)
    (ROOT / "game_index").mkdir(parents=True, exist_ok=True)
    for sport, (f, fam, _) in SPORTS.items():
        p = Path(a.datasets) / f
        if not p.exists():
            continue
        d = pd.read_parquet(p); led = pd.read_csv(Path(a.ledgers) / f"{sport}.games.csv.gz", dtype=str)
        cls = reconcile(sport, led, d, fam, per_game=True)
        cur = [e for e in v["versions"] if e["sport"] == sport and not e.get("superseded_by")]
        ver = cur[-1]["canonical_sha256"][:12] if cur else ""
        ok = bad = None
        if sport in outs:
            o = json.loads(Path(outs[sport]).read_text())["outcomes"]
            bad = {str(g) for g in o["disagree_all"]}; un = {str(g) for g in o["unchecked_all"]}
            ok = set(d.game_id.astype(str)) - bad - un
        g = build_index(sport, led, d, cls, ver, ok, bad)
        g.to_csv(ROOT / "game_index" / f"{sport}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
        print(sport, len(g), g.recon_class.value_counts().to_dict(), g.outcome_check.value_counts().to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
