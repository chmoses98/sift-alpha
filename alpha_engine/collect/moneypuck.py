"""MoneyPuck listed-download ingestion (NON-COMMERCIAL research only; owner-reported terms: listed downloads, attribution required). No key, no spend, never auto-run.

    python -m alpha_engine.collect.moneypuck listing --out listing.json     # ONE GET of the public data page (manual workflow); records which downloads are actually linked there
    python -m alpha_engine.collect.moneypuck ingest --listing listing.json --src F.csv --kind season_teams --out-dir research/input_research/non_commercial/moneypuck

A file family is ingestible only if (a) it is in LISTED_EVIDENCED (owner's production use) or (b) a listing.json produced from the live page names it. Outputs go ONLY under `non_commercial/`
and carry tier CLEARED_NONCOMMERCIAL_RESEARCH + attribution; the commercial-cleared datasets never read this directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PAGE = "https://www.moneypuck.com/data.htm"
BASE = "https://moneypuck.com/moneypuck/"
TIER = "CLEARED_NONCOMMERCIAL_RESEARCH"
ATTRIBUTION = "Data: MoneyPuck.com (non-commercial research use of listed downloads)"
# evidenced as downloaded by the owner's nhl-edge-finder (moneypuck.py at de1c36a); the data page itself has not been read by the agent
LISTED_EVIDENCED = {
    "season_teams": "playerData/seasonSummary/{year}/regular/teams.csv",
    "season_goalies": "playerData/seasonSummary/{year}/regular/goalies.csv",
    "careers_game_by_game_all_teams": "playerData/careers/gameByGame/all_teams.csv",
}
# remembered, NOT evidenced: ingestible only after listing.json names them
REMEMBERED_UNVERIFIED = ["shots_{year}.zip", "seasonSummary/{year}/regular/skaters.csv", "seasonSummary/{year}/regular/lines.csv", "seasonSummary/{year}/regular/pairings.csv", "playerData/allPlayersLookup.csv"]
LINK = re.compile(r'href=["\']([^"\']+\.(?:csv|zip))["\']', re.I)


def parse_listing(html: str) -> list[str]:
    """Download links on the data page, normalised to paths relative to /moneypuck/ (pure; tested on fixtures)."""
    out = set()
    for h in LINK.findall(html):
        h = re.sub(r"^(?:https?://(?:www\.)?moneypuck\.com)?/?(?:moneypuck/)?", "", h).lstrip("/")
        out.add(re.sub(r"(?<!\d)(?:19|20)\d{2}(?!\d)", "{year}", h))
    return sorted(out)


def allowed(path_tpl: str, listing: list[str] | None) -> bool:
    return path_tpl in LISTED_EVIDENCED.values() or bool(listing and path_tpl in listing)


def ingest(src: Path, kind: str, listing: list[str] | None, out_dir: Path) -> dict:
    tpl = LISTED_EVIDENCED.get(kind) or kind
    if not allowed(tpl, listing): raise PermissionError(f"{tpl} is not an evidenced or page-listed MoneyPuck download")
    out_dir = Path(out_dir); parts = out_dir.resolve().parts
    if "non_commercial" not in parts: raise PermissionError("MoneyPuck-derived output must live under a non_commercial/ directory")
    raw = Path(src).read_bytes(); out_dir.mkdir(parents=True, exist_ok=True)
    man = {"source": "moneypuck_listed_downloads", "file_family": tpl, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "tier": TIER, "commercial_use": False, "attribution": ATTRIBUTION}
    (out_dir / (re.sub(r"\W+", "_", tpl) + ".manifest.json")).write_text(json.dumps(man, indent=1, sort_keys=True)); return man


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("listing"); l.add_argument("--out", required=True)
    i = sub.add_parser("ingest"); i.add_argument("--listing"); i.add_argument("--src", required=True); i.add_argument("--kind", required=True); i.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "listing":
        import urllib.request
        html = urllib.request.urlopen(urllib.request.Request(PAGE, headers={"User-Agent": "research-client"}), timeout=60).read().decode("utf-8", "replace")   # single GET
        Path(a.out).write_text(json.dumps({"page": PAGE, "page_sha256": hashlib.sha256(html.encode()).hexdigest(), "downloads": parse_listing(html)}, indent=1)); return 0
    lst = json.loads(Path(a.listing).read_text())["downloads"] if a.listing else None
    print(json.dumps(ingest(Path(a.src), a.kind, lst, Path(a.out_dir)))); return 0


if __name__ == "__main__":
    sys.exit(main())
