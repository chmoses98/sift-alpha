"""Reproduce pinned Kalshi market observation timelines from two public archives."""
import argparse
import json
from pathlib import Path

from .unified_timeline import run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="research/timeline_pilot_sources.json")
    parser.add_argument("--out", default="artifacts/unified_timeline_pilot.json")
    args = parser.parse_args()
    doc = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = run(doc)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    for sport, data in result["sport_tapes"].items():
        print(sport, json.dumps(data["counts"], sort_keys=True))
    print(f"RESEARCH_ONLY: {output}")


if __name__ == "__main__":
    main()
