"""Run the completeness verifier for one or more sports and write evidence artifacts.

    python -m alpha_engine.game_completeness.cli MLB --root mlb=../edge-finder-api --root mlb_ref=REF/mlb

Writes research/game_completeness/<SPORT>/summary.json (denominators, status counts per dataset and season, reasons,
dependent inputs / markets from the approved map) and games.csv.gz (one row per expected game, one status column per
dataset).  Game identifiers and status codes only: no raw statistic, price or provider row is written.
"""
import argparse
import csv
import gzip
import hashlib
import importlib
import io
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .engine import evaluate, game_status, rollup
from .impact import InputMap
from .model import NOT_APPLICABLE, STATUSES

OUT = Path(__file__).resolve().parents[2] / "research" / "game_completeness"
ADAPTERS = {"MLB": "mlb", "NFL": "nfl", "NBA": "nba", "NHL": "nhl", "CBB": "cbb", "CFB": "cfb"}
CODE = {"COMPLETE": "C", "PARTIAL": "P", "MISSING": "M", "STALE": "S", "UNVERIFIED": "U", "RIGHTS_BLOCKED": "R",
        "NOT_APPLICABLE": "-"}


def run(sport, roots, out=OUT, imap=None, as_of=None):
    ad = importlib.import_module(f"{__package__}.adapters.{ADAPTERS[sport]}")
    specs = ad.specs()
    games, obs, notes = ad.load(roots)
    cells = evaluate(games, specs, obs)
    imap = imap or InputMap()
    datasets = rollup(cells, specs)
    for d in datasets:
        imp = imap.impact(d["map_datasets"])
        d["impact"] = {k: imp[k] for k in ("n_inputs", "n_predictive_inputs", "inputs_by_map_category", "n_markets",
                                           "n_markets_primary", "unknown_map_datasets")}
    gs = game_status(cells)
    states = Counter(g.state for g in games)
    by_game = {}
    for c in cells:
        by_game.setdefault(c["game_id"], {})[c["dataset"]] = CODE[c["status"]]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    keys = [s.key for s in specs]
    w.writerow(["season", "date", "game_id", "state", "overall"] + keys)
    for g in sorted(games, key=lambda g: (g.season, g.date, g.game_id)):
        w.writerow([g.season, g.date, g.game_id, g.state, CODE.get(gs.get(g.game_id), "-")] + [by_game[g.game_id][k] for k in keys])
    raw = buf.getvalue().encode()
    d = Path(out) / sport
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "games.csv.gz", "wb") as fh:
        with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:        # mtime=0: byte-identical on re-run
            gz.write(raw)
    summary = {
        "schema": "game-completeness-1.0", "status": "RESEARCH_ONLY",
        "verification": "agent-run, not human verified; every count is a read-back of archived records",
        "sport": sport, "as_of": as_of or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expected_games": {"total": len(games), "by_state": dict(states),
                           "by_season": dict(sorted(Counter(g.season for g in games).items()))},
        "games_overall": dict(Counter(gs.values())),
        "status_codes": CODE, "statuses": list(STATUSES) + [NOT_APPLICABLE],
        "datasets": datasets, "adapter_notes": notes,
        "ledger": {"file": "games.csv.gz", "rows": len(games), "sha256_uncompressed": hashlib.sha256(raw).hexdigest()},
    }
    (d / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    return summary


def table(summary):
    rows = ["dataset                        cat        expected  COMPLETE  PARTIAL  MISSING  STALE  UNVERIF  RIGHTS  rate"]
    for d in summary["datasets"]:
        rows.append(f"{d['dataset']:<30} {d['category']:<10} {d['expected']:>8} {d['COMPLETE']:>9} {d['PARTIAL']:>8} "
                    f"{d['MISSING']:>8} {d['STALE']:>6} {d['UNVERIFIED']:>8} {d['RIGHTS_BLOCKED']:>7}  {d['complete_rate']}")
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sports", nargs="+", choices=sorted(ADAPTERS))
    ap.add_argument("--root", action="append", default=[], metavar="NAME=PATH")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--as-of", default=None)
    a = ap.parse_args(argv)
    roots = dict(r.split("=", 1) for r in a.root)
    imap = InputMap()
    for s in a.sports:
        sm = run(s, roots, a.out, imap, a.as_of)
        print(f"\n== {s}: {sm['expected_games']['total']} expected games {sm['expected_games']['by_state']}")
        print(table(sm))


if __name__ == "__main__":
    main()
