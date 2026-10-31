"""Read-only research director and data-integrity audit CLI."""
import argparse
import json
from pathlib import Path

from .core import decide_next, fingerprint, load_json


def main() -> None:
    parser = argparse.ArgumentParser(description="SIFT Alpha research planning (does not run experiments)")
    parser.add_argument("--queue", default="research/queue.json")
    parser.add_argument("--sources", default="research/sources.json")
    parser.add_argument("--history", default=None, help="Optional JSON map of project IDs to selection counts")
    args = parser.parse_args()
    queue = load_json(args.queue)
    sources = load_json(args.sources)
    history = load_json(args.history) if args.history else {}
    result = decide_next(queue, sources, history)
    result["queue_sha256"] = fingerprint(queue)
    result["sources_sha256"] = fingerprint(sources)
    result["warning"] = "Plan only. No data was fetched, no experiment ran, and no evidence of profitability exists."
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
