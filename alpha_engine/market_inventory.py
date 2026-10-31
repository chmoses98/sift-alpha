"""SIFT Alpha's free, read-only archive LOCATION inventory.

This inventories files and directories only. It DOES NOT parse market
prices, reconstruct movements, infer settlement, evaluate betting results,
or enable scheduled jobs.

No credentials, no Kalshi API requests, no billed service. Public GitHub
metadata, bounded 1 request per manifest entry; graceful rate-limit error.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

SUPPORTED_REPOS = {
    "chmoses98/nfl-edge-finder", "chmoses98/cfb-edge-finder",
    "chmoses98/nba-edge-finder", "chmoses98/edge-finder-api",
    "chmoses98/NHL-edge-finder", "chmoses98/soccer-edge-finder",
    "chmoses98/Tennis-Edge-Finder", "chmoses98/cbb-edge-finder",
}
VALID = re.compile(r"^[A-Za-z0-9_./=-]+$")
BRANCH = re.compile(r"^[A-Za-z0-9_/-]+$")


def check_entry(entry):
    if entry.get("repo") not in SUPPORTED_REPOS:
        raise ValueError("Unknown repository (fail closed)")
    if not VALID.fullmatch(entry.get("path", "")) or ".." in entry["path"].split("/"):
        raise ValueError("Unsafe path")
    if not BRANCH.fullmatch(entry.get("branch", "")):
        raise ValueError("Invalid branch")
    if entry.get("verified") != "directory_exists":
        raise ValueError("Archive entry not verified")
    if not entry.get("role") or not entry.get("sport"):
        raise ValueError("Missing sport or archive role")


def check_manifest(manifest):
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("sources"), list):
        raise ValueError("Unexpected archive registry format")
    keys = set()
    for entry in manifest["sources"]:
        check_entry(entry)
        key = (entry["repo"], entry["branch"], entry["path"])
        if key in keys:
            raise ValueError("Duplicate archive location")
        keys.add(key)
    return manifest["sources"]


def api_url(entry):
    check_entry(entry)
    ref = urllib.parse.quote(entry["branch"], safe="")
    return "https://api.github.com/repos/" + entry["repo"] + "/contents/" + entry["path"] + "?ref=" + ref


def summarize_listing(entry, children):
    if not isinstance(children, list):
        raise ValueError("GitHub path does not resolve to a directory listing")
    if len(children) >= 1000:
        raise ValueError("GitHub Contents API response may be truncated; use Git Trees pagination or targeted partitions")
    types = defaultdict(int)
    total_bytes = 0
    for child in children:
        if child.get("type") not in ("dir", "file") or not isinstance(child.get("name"), str):
            raise ValueError("Malformed GitHub metadata")
        types[child["type"]] += 1
        if child["type"] == "file":
            size = child.get("size")
            if not isinstance(size, int) or size < 0:
                raise ValueError("Missing file size")
            total_bytes += size
    return {
        "sport": entry["sport"], "repo": entry["repo"], "branch": entry["branch"],
        "path": entry["path"], "role": entry["role"],
        "status": "LOCATION_VERIFIED_ONLY",
        "immediate_subdirectory_count": types["dir"],
        "immediate_file_count": types["file"],
        "immediate_file_bytes": total_bytes,
        "no_market_row_count_inferred": True,
        "historical_price_reconstruction": "NOT_RUN",
        "settlement_join": "NOT_RUN",
    }


def inventory(path, *, loader=None):
    registry = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = check_manifest(registry)
    results = []
    for entry in entries:
        try:
            if loader is not None:
                children = loader(entry)
            else:
                request = urllib.request.Request(api_url(entry), headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "sift-alpha-market-archive-inventory/1.0",
                })
                with urllib.request.urlopen(request, timeout=12) as resp:
                    if urllib.parse.urlparse(resp.geturl()).netloc != "api.github.com":
                        raise ValueError("Unexpected redirect")
                    data = resp.read(2_000_000 + 1)
                if len(data) > 2_000_000:
                    raise ValueError("Listing too large")
                children = json.loads(data.decode("utf-8"))
            results.append(summarize_listing(entry, children))
        except Exception as exc:
            results.append({
                "sport": entry["sport"], "repo": entry["repo"], "branch": entry["branch"],
                "path": entry["path"], "role": entry["role"],
                "status": "UNVERIFIED_OR_UNAVAILABLE",
                "reason": str(exc)[:250],
            })
    return {
        "schema_version": 1, "artifact_type": "archive_location_inventory",
        "authority": "RESEARCH_ONLY", "cost": "PUBLIC_GITHUB_METADATA_ONLY",
        "requires_outcome_join": True,
        "requires_ticker_time_series": True,
        "sources": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="research/kalshi_archive_sources.json")
    parser.add_argument("--out", default="artifacts/market_archive_inventory.json")
    args = parser.parse_args()
    report = inventory(args.manifest)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_paths": len(report["sources"]), "verified": sum(x["status"] == "LOCATION_VERIFIED_ONLY" for x in report["sources"]), "out": str(target), "authority": "RESEARCH_ONLY"}))


if __name__ == "__main__":
    main()
