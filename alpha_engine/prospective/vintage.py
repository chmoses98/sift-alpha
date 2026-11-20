"""Immutable vintage archiver for prospective capture (RESEARCH_ONLY, DISABLED by default).

One capture = one fetch of one feed. Stored, never rewritten:
  <root>/<feed>/dt=YYYY-MM-DD/<feed>_<capture UTC>.json.gz      the ORIGINAL payload bytes (gzip)
  <root>/MANIFEST.jsonl                                           one record per attempt (success or failure):
      feed, source_id, rights_tier, url, capture_utc, http, attempts, errors[], bytes, sha256, file,
      source_published_utc (from the payload when the feed provides one), entity_ids (sorted), n_entities,
      completeness {field: share present}, parser_version
A point-in-time reader (as_of) returns the latest vintage whose capture_utc <= T and never a later one; freshness = T - capture_utc.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
RIGHTS = ROOT / "research" / "input_research" / "data_foundation" / "rights_registry.json"
MAX_BYTES = 30_000_000


class CaptureRefused(RuntimeError):
    """Raised when a capture is not authorised (disabled, not activated by the owner, or rights do not allow collection)."""


@dataclass
class Feed:
    name: str                       # e.g. "nfl.injury_report_vintages"
    source_id: str                  # rights_registry source id
    url_template: str               # formatted with the kwargs passed to capture()
    parse: Callable[[dict], list[dict]]          # payload -> normalized entity rows (each with an "entity_id")
    published: Callable[[dict], str | None] = lambda p: None   # payload -> source publication time (ISO, UTC) when provided
    fields: list[str] = field(default_factory=list)            # fields whose completeness is recorded
    parser_version: str = "1"
    notes: str = ""


def rights_entry(source_id: str, path: Path = RIGHTS) -> dict:
    d = json.loads(Path(path).read_text())
    for s in d["sources"]:
        if s.get("id") == source_id:
            return s
    return {"id": source_id, "tier": "UNREGISTERED", "collection_allowed": False}


def activation_check(feed: Feed, env: dict | None = None, rights_path: Path = RIGHTS) -> dict:
    """Returns the activation record if the capture is authorised, else raises CaptureRefused with every failed condition."""
    env = os.environ if env is None else env; bad = []
    if env.get("SIFT_PROSPECTIVE_ENABLED") != "1":
        bad.append("SIFT_PROSPECTIVE_ENABLED is not '1' (disabled by default)")
    act = None; ap = env.get("SIFT_PROSPECTIVE_ACTIVATION")
    if not ap or not Path(ap).exists():
        bad.append("no owner activation file (SIFT_PROSPECTIVE_ACTIVATION)")
    else:
        a = json.loads(Path(ap).read_text()); act = (a.get("feeds") or {}).get(feed.name)
        if not act or not act.get("owner") or not act.get("approved_utc"):
            bad.append(f"feed {feed.name} not activated by the owner (needs owner and approved_utc)")
    r = rights_entry(feed.source_id, rights_path)
    if r.get("collection_allowed") is not True:
        bad.append(f"rights registry: source {feed.source_id} tier {r.get('tier')} has collection_allowed != true")
    if bad:
        raise CaptureRefused("; ".join(bad))
    return {"activation": act, "rights_tier": r.get("tier")}


def _completeness(rows: list[dict], fields: list[str]) -> dict:
    if not rows:
        return {f: 0.0 for f in fields}
    return {f: round(sum(r.get(f) not in (None, "") for r in rows) / len(rows), 4) for f in fields}


def store(root: Path, feed: Feed, body: bytes, url: str, capture_utc: dt.datetime, http: int, attempts: int, errors: list[str], rights_tier: str) -> dict:
    """Write one vintage (payload + manifest line). Pure apart from the filesystem: used by capture() and by tests with fixture payloads."""
    rec = {"feed": feed.name, "source_id": feed.source_id, "rights_tier": rights_tier, "url": url, "capture_utc": capture_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "http": http,
           "attempts": attempts, "errors": errors, "parser_version": feed.parser_version}
    if http == 200 and body is not None:
        if len(body) > MAX_BYTES:
            rec["errors"] = errors + ["response larger than cap; not stored"]
        else:
            d = root / feed.name / f"dt={capture_utc:%Y-%m-%d}"; d.mkdir(parents=True, exist_ok=True)
            f = d / f"{feed.name}_{capture_utc:%Y%m%dT%H%M%S%fZ}.json.gz"
            if f.exists():
                raise FileExistsError(f"vintage already exists (immutable): {f}")
            with gzip.open(f, "wb") as g:
                g.write(body)
            payload = json.loads(body)
            rows = feed.parse(payload)
            rec.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), file=str(f.relative_to(root)), source_published_utc=feed.published(payload),
                       entity_ids=sorted({str(x["entity_id"]) for x in rows}), n_entities=len(rows), completeness=_completeness(rows, feed.fields))
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "MANIFEST.jsonl", "a") as m:
        m.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def capture(root: Path, feed: Feed, fetch: Callable[[str], tuple[int, bytes | None]] | None = None, tries: int = 3, env: dict | None = None, rights_path: Path = RIGHTS, **url_kw) -> dict:
    """Authorise, fetch (with bounded retries on transient errors only; never on 403/429), store. Raises CaptureRefused when not authorised: nothing is fetched."""
    auth = activation_check(feed, env, rights_path)
    url = feed.url_template.format(**url_kw)
    fetch = fetch or _http_get
    errors: list[str] = []; http = 0; body = None; n = 0
    for n in range(1, tries + 1):
        try:
            http, body = fetch(url)
        except Exception as e:                                   # record, never hide
            errors.append(type(e).__name__); http = 0; body = None
        if http == 200 or http in (403, 404, 429):
            break
        errors.append(f"http {http}"); time.sleep(min(2 ** n, 30))
    return store(Path(root), feed, body, url, dt.datetime.now(dt.timezone.utc), http, n, errors, auth["rights_tier"])


def _http_get(url: str) -> tuple[int, bytes | None]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "sift-alpha-research/1.0 (research-only vintage capture)", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        return e.code, None


def manifest(root: Path) -> list[dict]:
    p = Path(root) / "MANIFEST.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def as_of(root: Path, feed: Feed, t_utc: str) -> dict | None:
    """Latest SUCCESSFUL vintage of `feed` captured at or before t_utc (ISO 'YYYY-MM-DDTHH:MM:SSZ'): {record, rows, freshness_minutes}. Never returns a later capture."""
    ok = [r for r in manifest(root) if r["feed"] == feed.name and r.get("file") and r["capture_utc"] <= t_utc]
    if not ok:
        return None
    r = max(ok, key=lambda x: (x["capture_utc"], x["file"]))
    body = gzip.open(Path(root) / r["file"]).read()
    if hashlib.sha256(body).hexdigest() != r["sha256"]:
        raise ValueError(f"vintage hash mismatch: {r['file']}")
    t = dt.datetime.strptime(t_utc, "%Y-%m-%dT%H:%M:%SZ"); c = dt.datetime.strptime(r["capture_utc"], "%Y-%m-%dT%H:%M:%SZ")
    return {"record": r, "rows": feed.parse(json.loads(body)), "freshness_minutes": (t - c).total_seconds() / 60.0}
