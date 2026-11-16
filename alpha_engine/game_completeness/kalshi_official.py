"""Recover Kalshi's OWN settlement result per contract and cross-check it against a repo's computed settlements.

Why: the MLB, NBA and NHL archives store settlements computed by each repo's own engine from the box score; their
market snapshots hold active markets only, so the exchange's `result` is never preserved.  The public market-data
API still serves it for recently settled markets, but older settled markets leave that listing, so the window is
finite.

MANUAL, RESEARCH_ONLY.  No schedule, no credentials (public read-only endpoint), writes only to --out (a local
directory outside any repository unless the owner chooses otherwise).  Nothing here places or prices an order.

    python -m alpha_engine.game_completeness.kalshi_official fetch --series KXNHLGAME KXNHLTOTAL --out OUT
    python -m alpha_engine.game_completeness.kalshi_official compare --official OUT --computed 'ARCHIVE/settlements/*/*.jsonl.gz'
"""
import argparse
import glob
import hashlib
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.elections.kalshi.com/trade-api/v2"
API = BASE + "/markets"
# Markets settled before the exchange's historical cutoff (GET /historical/cutoff -> market_settled_ts) leave the
# live listing and are served, unauthenticated, from /historical/markets instead.  Both are needed for full history.
HISTORICAL_API = BASE + "/historical/markets"
KEEP = ("ticker", "event_ticker", "status", "result", "expiration_value", "settlement_value_dollars", "close_time",
        "settlement_ts")
RULES = ("rules_primary", "rules_secondary")
# Rules text is the same template for thousands of contracts; each row carries its sha256 and the distinct texts are
# written once per series to <series>[__historical].rules.json, so the semantics stay auditable at a fraction of
# the size.


def rules_sha(m):
    return hashlib.sha256(json.dumps([m.get(k) or "" for k in RULES]).encode()).hexdigest()


def fetch_series(series, out, max_pages=200, pause=1.0, opener=urllib.request.urlopen, historical=False):
    """Page through settled markets of one series; one JSONL row per contract with the retrieval timestamp.
    historical=True reads /historical/markets (pre-cutoff settlements) into <series>__historical.jsonl."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cursor, n, pages = "", 0, 0
    api = HISTORICAL_API if historical else API
    stem = f"{series}__historical" if historical else series
    rules = {}
    with open(out / f"{stem}.jsonl", "w", encoding="utf-8") as fh:
        while pages < max_pages:
            q = {"series_ticker": series, "limit": 1000}
            if not historical:
                q["status"] = "settled"
            if cursor:
                q["cursor"] = cursor
            req = urllib.request.Request(api + "?" + urllib.parse.urlencode(q), headers={"User-Agent": "research-readonly"})
            for attempt in range(6):                              # back off on rate limiting; never hammer
                try:
                    with opener(req, timeout=60) as r:
                        d = json.loads(r.read())
                    break
                except urllib.error.HTTPError as e:
                    if e.code != 429 or attempt == 5:
                        raise
                    time.sleep(pause and 5 * (attempt + 1))
            got = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for m in d.get("markets", []):
                h = rules_sha(m)
                rules.setdefault(h, {k: m.get(k) for k in RULES})
                fh.write(json.dumps({**{k: m.get(k) for k in KEEP}, "rules_sha256": h, "_retrieved_at_utc": got,
                                     "_source": api}) + "\n")
                n += 1
            pages += 1
            cursor = d.get("cursor") or ""
            if not cursor or not d.get("markets"):
                break
            time.sleep(pause)
    (out / f"{stem}.rules.json").write_text(json.dumps(rules, indent=0, sort_keys=True), encoding="utf-8")
    return {"series": series, "contracts": n, "pages": pages, "truncated": bool(cursor)}


def file_summary(path):
    """Provenance for one fetched series file: row count, sha256, close-time span and result mix (no row content)."""
    h, n, lo, hi, res = hashlib.sha256(), 0, None, None, Counter()
    with open(path, "rb") as fh:
        for line in fh:
            h.update(line)
            r = json.loads(line)
            n += 1
            ct = (r.get("close_time") or "")[:10] or None
            if ct:
                lo = ct if lo is None or ct < lo else lo
                hi = ct if hi is None or ct > hi else hi
            res[(r.get("result") or "").lower() or "none"] += 1
    return {"rows": n, "sha256": h.hexdigest(), "close_min": lo, "close_max": hi, "results": dict(res)}


def fetch_scope(scope, out, sports=None, max_pages=200, pause=1.0, fetch=None, historical=False):
    """Fetch every series in a scope file ({"sports": {SPORT: [series, ...]}}) into OUT/<SPORT>/, resumably.

    A series is skipped when OUT/<SPORT>/<series>.done exists (written only after a complete, untruncated fetch).
    OUT/manifest.json records, per series, the provenance summary so a later archive step can verify read-back."""
    fetch = fetch or fetch_series
    out = Path(out)
    man_path = out / "manifest.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else {"schema": "kalshi-official-manifest-1.0",
                                                                     "source": API, "series": {}}
    for sport, series in sorted(scope["sports"].items()):
        if sports and sport not in sports:
            continue
        d = out / sport
        for s0 in series:
            s = f"{s0}__historical" if historical else s0
            done = d / f"{s}.done"
            if done.exists():
                continue
            try:
                r = fetch(s0, d, max_pages=max_pages, pause=pause, **({"historical": True} if historical else {}))
            except Exception as e:                                # record and move on; never mark as done
                man["series"][f"{sport}/{s}"] = {"error": repr(e)[:300]}
                man_path.write_text(json.dumps(man, indent=1, sort_keys=True))
                continue
            entry = {**file_summary(d / f"{s}.jsonl"), "pages": r["pages"], "truncated": r["truncated"],
                     "fetched_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            man["series"][f"{sport}/{s}"] = entry
            if not r["truncated"]:
                done.write_text(entry["sha256"])
            man_path.write_text(json.dumps(man, indent=1, sort_keys=True))
    return man


def verify_manifest(out):
    """Re-hash every series file against the manifest: the read-back check used before and after archiving."""
    out = Path(out)
    man = json.loads((out / "manifest.json").read_text())
    bad = []
    for key, e in man["series"].items():
        if "sha256" not in e:
            bad.append((key, "not fetched"))
            continue
        f = out / f"{key}.jsonl"
        if not f.exists():
            bad.append((key, "missing file"))
        elif file_summary(f)["sha256"] != e["sha256"]:
            bad.append((key, "hash mismatch"))
    return {"series": len(man["series"]), "problems": bad}


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(roots, archive):
    """Pack verified fetch folders ({tag: folder}, e.g. live / historical) into one .tar.gz plus a sidecar
    <archive>.sha256.json.  Refuses to pack a folder whose read-back fails.  Member order and mtimes are fixed, so
    the same input gives the same tar stream.  The archive holds exchange data: PRIVATE storage only."""
    import tarfile
    archive = Path(archive)
    summary = {}
    for tag, root in sorted(roots.items()):
        v = verify_manifest(root)
        if v["problems"]:
            raise ValueError(f"{tag}: read-back failed before packing: {v['problems'][:5]}")
        man = json.loads((Path(root) / "manifest.json").read_text())
        summary[tag] = {"series": len(man["series"]), "rows": sum(e.get("rows", 0) for e in man["series"].values()),
                        "manifest_sha256": _sha_file(Path(root) / "manifest.json")}
    with open(archive, "wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0, compresslevel=6) as gz, \
            tarfile.open(fileobj=gz, mode="w") as tar:
        for tag, root in sorted(roots.items()):
            for f in sorted(p for p in Path(root).rglob("*") if p.is_file()):
                info = tar.gettarinfo(str(f), arcname=f"{tag}/{f.relative_to(root).as_posix()}")
                info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
                with open(f, "rb") as fh:
                    tar.addfile(info, fh)
    side = {"schema": "kalshi-official-snapshot-1.0", "archive": archive.name, "bytes": archive.stat().st_size,
            "sha256": _sha_file(archive), "roots": summary,
            "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    Path(str(archive) + ".sha256.json").write_text(json.dumps(side, indent=1, sort_keys=True) + "\n")
    return side


def restore(archive, dest):
    """Check the archive against its sidecar, unpack into an EMPTY dest and re-hash every series file against the
    packed manifests.  A snapshot counts as protected only after this passes on a copy read back from storage."""
    import tarfile
    archive, dest = Path(archive), Path(dest)
    side = json.loads(Path(str(archive) + ".sha256.json").read_text())
    if _sha_file(archive) != side["sha256"]:
        raise ValueError("archive sha256 does not match its sidecar")
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("restore target must be empty")
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest, filter="data")                       # refuses absolute paths, links and traversal
    out = {"archive_sha256": side["sha256"], "roots": {}}
    for tag, meta in side["roots"].items():
        v = verify_manifest(dest / tag)
        man = json.loads((dest / tag / "manifest.json").read_text())
        rows = sum(e.get("rows", 0) for e in man["series"].values())
        out["roots"][tag] = {"series": v["series"], "rows": rows, "problems": v["problems"],
                             "matches_sidecar": (v["series"], rows) == (meta["series"], meta["rows"])}
    out["ok"] = all(not r["problems"] and r["matches_sidecar"] for r in out["roots"].values())
    return out


def load_official(folder):
    off = {}
    for f in sorted(Path(folder).glob("**/*.jsonl")):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            off[r["ticker"]] = r
    return off


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compare(official, computed, values=None):
    """official: {ticker: row with 'result'}; computed: {ticker: 'YES'|'NO'|other}; values: optional
    {ticker: computed stat value}.  Only YES/NO vs yes/no pairs are judged; anything else is reported, never
    forced into agree/disagree.  Computed results are never relabelled as official, and vice versa."""
    c = Counter()
    by_series = {}
    disagree = []
    deltas = Counter()
    for t, out in computed.items():
        ser = t.split("-")[0]
        bs = by_series.setdefault(ser, Counter())
        o = official.get(t)
        if o is None:
            c["computed_without_official"] += 1
            bs["computed_without_official"] += 1
            continue
        res = (o.get("result") or "").lower()
        if out not in ("YES", "NO"):
            hit = res in ("yes", "no")
            c["official_available_for_unsettleable"] += hit
            bs["official_available_for_unsettleable"] += hit
            c["computed_not_binary"] += 1
        elif res not in ("yes", "no"):
            c["official_not_binary"] += 1
            bs["official_not_binary"] += 1
        elif res == out.lower():
            c["agree"] += 1
            bs["agree"] += 1
        else:
            c["disagree"] += 1
            bs["disagree"] += 1
            disagree.append(t)
            if values is not None:
                a, b = _num(o.get("expiration_value")), _num(values.get(t))
                deltas[f"{ser}:{'n/a' if a is None or b is None else round(a - b, 1)}"] += 1
    c["official_without_computed"] = sum(1 for t in official if t not in computed)
    out = {"counts": dict(c), "by_series": {k: dict(v) for k, v in sorted(by_series.items())},
           "disagreements": sorted(disagree)}
    if values is not None:
        out["official_minus_computed_value_on_disagreement"] = dict(sorted(deltas.items()))
    return out


def _computed(pattern, ticker="ticker", outcome=("outcome", "result"), values=None):
    """Latest row per ticker wins (files sorted by name, rows in order).  values: optional dict to fill with the
    computed stat value per ticker."""
    out = {}
    for f in sorted(glob.glob(pattern, recursive=True)):
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                t = r.get(ticker) or r.get("marketTicker")
                v = next((r[k] for k in outcome if r.get(k) is not None), None)
                if t:
                    out[t] = v
                    if values is not None:
                        values[t] = r.get("value")
    return out


def _computed_rows(pattern, ticker="ticker"):
    """Latest full row per ticker (same ordering rule as _computed)."""
    out = {}
    for f in sorted(glob.glob(pattern, recursive=True)):
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get(ticker):
                    out[r[ticker]] = r
    return out


def report(live, hist, computed_globs, as_of):
    """Evidence file: per sport, what official data was recovered (counts, close-date span, truncation, read-back)
    and, where a computed archive exists, the cross-check.  Identifiers and counts only; no rules text, no prices."""
    out = {"schema": "kalshi-official-crosscheck-2.0", "as_of": as_of,
           "notice": "Agent-run, not human verified. Official rows fetched to a local directory (not archived on any "
                     "branch). Computed results are never relabelled as official.",
           "source": {"live": API, "historical": HISTORICAL_API}, "sports": {}}
    for root, tag in ((live, "live"), (hist, "historical")):
        if not root:
            continue
        man = json.loads((Path(root) / "manifest.json").read_text())
        rb = verify_manifest(root)
        for key, e in sorted(man["series"].items()):
            sport, series = key.split("/")
            sp = out["sports"].setdefault(sport, {"official": {}})
            o = sp["official"].setdefault(tag, {"series": 0, "contracts": 0, "close_min": None, "close_max": None,
                                                "truncated": [], "errors": [], "readback_problems": 0})
            if "error" in e:
                o["errors"].append(series)
                continue
            o["series"] += 1
            o["contracts"] += e["rows"]
            for k, f in (("close_min", min), ("close_max", max)):
                if e[k]:
                    o[k] = e[k] if o[k] is None else f(o[k], e[k])
            if e.get("truncated"):
                o["truncated"].append(series)
        for key, why in rb["problems"]:
            out["sports"][key.split("/")[0]]["official"][tag]["readback_problems"] += 1
    for sport, pattern in computed_globs.items():
        official = {}
        for root in (live, hist):
            if root and (Path(root) / sport).exists():
                official.update(load_official(Path(root) / sport))
        vals = {}
        comp = _computed(pattern, values=vals)
        r = compare(official, comp, vals)
        out["sports"].setdefault(sport, {})["crosscheck"] = {
            "computed_contracts": len(comp), "counts": r["counts"],
            "by_series_with_disagreement_or_recoverable": {k: v for k, v in r["by_series"].items()
                                                         if v.get("disagree") or v.get("official_available_for_unsettleable")},
            "official_minus_computed_value_on_disagreement": r["official_minus_computed_value_on_disagreement"],
            "disagreement_tickers": r["disagreements"]}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--series", nargs="+", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--max-pages", type=int, default=200)
    c = sub.add_parser("compare")
    c.add_argument("--official", required=True, help="folder, or comma-separated folders (live, historical)")
    c.add_argument("--computed", required=True, help="glob of computed settlement .jsonl[.gz]")
    fs = sub.add_parser("fetch-scope")
    fs.add_argument("--scope", required=True)
    fs.add_argument("--out", required=True)
    fs.add_argument("--sports", nargs="*")
    fs.add_argument("--max-pages", type=int, default=2000)
    fs.add_argument("--historical", action="store_true", help="read /historical/markets (pre-cutoff settlements)")
    rp = sub.add_parser("report")
    rp.add_argument("--live", required=True)
    rp.add_argument("--historical")
    rp.add_argument("--computed", nargs="*", default=[], help="SPORT=glob of computed settlements")
    rp.add_argument("--as-of", required=True)
    rp.add_argument("--out", required=True)
    sn = sub.add_parser("snapshot", help="pack verified folders into one archive + sha256 sidecar (private storage only)")
    sn.add_argument("--root", nargs="+", required=True, metavar="TAG=FOLDER")
    sn.add_argument("--archive", required=True)
    rs = sub.add_parser("restore", help="unpack a snapshot into an empty folder and re-verify every file")
    rs.add_argument("--archive", required=True)
    rs.add_argument("--dest", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "fetch-scope":
        man = fetch_scope(json.loads(Path(a.scope).read_text()), a.out, a.sports, a.max_pages,
                          historical=a.historical)
        print(json.dumps({"series": len(man["series"])}))
    elif a.cmd == "report":
        r = report(a.live, a.historical, dict(x.split("=", 1) for x in a.computed), a.as_of)
        Path(a.out).write_text(json.dumps(r, indent=1, sort_keys=True) + "\n")
    elif a.cmd == "snapshot":
        print(json.dumps(snapshot(dict(x.split("=", 1) for x in a.root), a.archive), indent=1))
    elif a.cmd == "restore":
        r = restore(a.archive, a.dest)
        print(json.dumps(r, indent=1))
        raise SystemExit(0 if r["ok"] else 1)
    elif a.cmd == "verify":
        print(json.dumps(verify_manifest(a.out), indent=1))
    elif a.cmd == "fetch":
        for s in a.series:
            print(json.dumps(fetch_series(s, a.out, a.max_pages)))
    else:
        official = {}
        for folder in a.official.split(","):
            official.update(load_official(folder))
        vals = {}
        print(json.dumps(compare(official, _computed(a.computed, values=vals), vals), indent=1))


if __name__ == "__main__":
    main()
