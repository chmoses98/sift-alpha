"""Runner-side probe of tennis-data.co.uk (ATP + WTA yearly xlsx).

Licence: the site allows personal download but not redistribution, so this publishes ONLY derived coverage
statistics, file hashes and HTTP headers -- never match rows. Run on a GitHub runner (the authoring sandbox
cannot reach the host).
"""
import hashlib
import io
import json
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone

import openpyxl

SOURCES = {
    "ATP": "http://www.tennis-data.co.uk/{y}/{y}.xlsx",
    "WTA": "http://www.tennis-data.co.uk/{y}w/{y}.xlsx",
}
ODDS = ["B365W", "PSW", "MaxW", "AvgW"]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sift-alpha-research-probe"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(), dict(r.headers), r.status


def analyse(tour, year, out):
    url = SOURCES[tour].format(y=year)
    rec = {"tour": tour, "year": year, "url": url,
           "fetched_at": datetime.now(timezone.utc).isoformat()}
    try:
        raw, hdr, status = fetch(url)
    except Exception as e:  # record the failure; never fabricate
        rec.update(status="FETCH_FAILED", error=repr(e)[:300])
        out.append(rec)
        return
    rec.update(status="OK", http=status, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
               last_modified=hdr.get("Last-Modified"), etag=hdr.get("ETag"))
    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    head = [str(c) if c is not None else "" for c in next(rows)]
    ix = {h: i for i, h in enumerate(head)}
    rec["columns"] = head
    n = 0
    dates, months, comments = [], Counter(), Counter()
    nulls = Counter()
    for r in rows:
        if r is None or all(c is None for c in r):
            continue
        n += 1
        d = r[ix["Date"]] if "Date" in ix else None
        if isinstance(d, datetime):
            dates.append(d)
            months[d.strftime("%Y-%m")] += 1
        for col in ["Winner", "Loser", "W1", "L1", "Comment"] + ODDS:
            if col in ix and r[ix[col]] in (None, ""):
                nulls[col] += 1
        if "Comment" in ix and r[ix["Comment"]] not in (None, ""):
            comments[str(r[ix["Comment"]])] += 1
    rec.update(rows=n, first_date=min(dates).date().isoformat() if dates else None,
               last_date=max(dates).date().isoformat() if dates else None,
               rows_by_month=dict(sorted(months.items())),
               null_counts={k: nulls.get(k, 0) for k in ["Winner", "Loser", "W1", "L1"] + ODDS if k in ix},
               comment_counts=dict(comments.most_common(10)),
               has_serve_return_stats=any(c in ix for c in ("w_ace", "w_svpt", "W_Aces")))
    out.append(rec)


if __name__ == "__main__":
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    out = []
    for tour in SOURCES:
        for y in (year - 1, year):
            analyse(tour, y, out)
    print(json.dumps(out, indent=1)[:6000])
    with open("out/tennis_data_probe.json", "w") as f:
        json.dump({"schema": "tennis-data-probe-1", "results": out}, f, indent=1, sort_keys=True)
