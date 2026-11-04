"""Pinned Kalshi-collector Tennis settlement-result fields, no synthetic winners.

These are *archived Kalshi result fields*, not independently authenticated
exchange audit records. In particular scalar/0.5 payouts are NOT wins or losses.
Occurrence timestamps are not independently verified actual match starts.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import gzip
import io
import json
from .tennis_capture import read_pinned, utc, REPO, ROOT, RUN, SHA

EXPECTED_RUNS=("20261025T004543Z","20261025T014543Z","20261025T035705Z")
RESULT_VALUES={"yes":Decimal("1"),"no":Decimal("0"),"scalar":Decimal("0.5")}

def validate_pins(spec):
    if (spec.get("schema_version")!=1 or spec.get("sport")!="TENNIS"
        or spec.get("repository")!=REPO or not SHA.fullmatch(spec.get("commit",""))
        or spec.get("max_total_bytes")!=40000
        or spec.get("max_expanded_bytes_per_file")!=150000):
        raise ValueError("Unapproved Tennis settlement source")
    caps=spec.get("captures")
    if not isinstance(caps,list) or tuple(x.get("run_id") for x in caps)!=EXPECTED_RUNS:
        raise ValueError("Unverified settlement run sequence")
    total=0
    for cap in caps:
        run=cap["run_id"]
        if not RUN.fullmatch(run): raise ValueError("Bad run id")
        day=f"{run[:4]}-{run[4:6]}-{run[6:8]}"
        for kind,suffix in (("manifest",".manifest.json"),("settlements",".settlements.jsonl.gz")):
            entry=cap.get(kind)
            if not isinstance(entry,dict): raise ValueError("Missing source")
            if entry.get("path")!=f"{ROOT}{day}/{run}{suffix}":
                raise ValueError("Unapproved path")
            if not SHA.fullmatch(entry.get("sha","")): raise ValueError("Unpinned source")
            size=entry.get("bytes")
            if type(size)!=int or not 0<size<=15000: raise ValueError("Unbounded source")
            total+=size
    if total>40000: raise ValueError("Aggregate source budget exceeded")
    return caps

def read_rows(spec,cap,downloader=None):
    manifest=json.loads(read_pinned(spec,cap["manifest"],downloader))
    if (not isinstance(manifest,dict) or manifest.get("run_id")!=cap["run_id"]
        or manifest.get("incomplete")!=[]
        or manifest.get("client_stats",{}).get("failures")!=0):
        raise ValueError("Bad upstream manifest")
    start,finish=utc(manifest.get("started_at")),utc(manifest.get("finished_at"))
    if not start<finish or (finish-start).total_seconds()>1800:
        raise ValueError("Invalid capture time window")
    expected=manifest.get("counts",{}).get("settlements")
    if type(expected)!=int or expected<0:
        raise ValueError("Unreconciled upstream settlement count")
    compressed=read_pinned(spec,cap["settlements"],downloader)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        expanded=stream.read(spec["max_expanded_bytes_per_file"]+1)
    if len(expanded)>spec["max_expanded_bytes_per_file"]:
        raise ValueError("Unbounded settlement gzip expansion")
    records=[]
    seen=set()
    for line in expanded.splitlines():
        if not line.strip(): continue
        row=json.loads(line)
        if not isinstance(row,dict) or row.get("run_id")!=cap["run_id"]:
            raise ValueError("Wrong run in settlement row")
        ticker=row.get("ticker")
        event=row.get("event_ticker")
        if not isinstance(ticker,str) or not ticker or ticker in seen or not isinstance(event,str) or not event:
            raise ValueError("Missing or duplicate literal contract identity")
        seen.add(ticker)
        if row.get("status")!="finalized" or row.get("result") not in RESULT_VALUES:
            raise ValueError("Non-final or unknown exchange result")
        try: payout=Decimal(row["settlement_value_dollars"])
        except (InvalidOperation,KeyError,TypeError) as exc:
            raise ValueError("Missing or invalid settlement payout") from exc
        if not payout.is_finite() or payout!=RESULT_VALUES[row["result"]]:
            raise ValueError("Result/payout contradiction")
        at=utc(row.get("captured_at"))
        settled=utc(row.get("settlement_ts"))
        opened=utc(row.get("open_time"))
        closed=utc(row.get("close_time"))
        occurrence=utc(row.get("occurrence_datetime"))
        if not (start<=at<=finish and opened<=closed<=settled<=at):
            raise ValueError("Settlement timing contradiction or future leakage")
        records.append({
            "sport":"TENNIS","ticker":ticker,"event_ticker":event,
            "run_id":cap["run_id"],"observed_at_utc":at.isoformat().replace("+00:00","Z"),
            "exchange_reported_settlement_ts":settled.isoformat().replace("+00:00","Z"),
            "exchange_reported_result":row["result"],
            "exchange_reported_payout_dollars":str(payout),
            "exchange_reported_expiration_value":row.get("expiration_value"),
            "exchange_reported_occurrence_datetime":row.get("occurrence_datetime"),
            "occurrence_later_than_settlement":occurrence>settled,
            "source_path":cap["settlements"]["path"],
            "source_blob_sha1":cap["settlements"]["sha"],
            "source_manifest_sha1":cap["manifest"]["sha"],
            "source_authority":"PINNED_ARCHIVED_KALSHI_COLLECTOR_FIELDS",
            "independently_authenticated_exchange_result":False,
            "actual_match_start_verified":False,
            "contract_to_physical_match":"NOT_ESTABLISHED",
            "pregame_or_execution_authority":"NONE",
        })
    if len(records)!=expected:
        raise ValueError("Settlement records do not reconcile with upstream manifest")
    return records,{"run_id":cap["run_id"],"n_settlement_records":len(records),
                    "source_manifest_sha1":cap["manifest"]["sha"],
                    "source_settlement_sha1":cap["settlements"]["sha"]}

def audit(spec,downloader=None):
    caps=validate_pins(spec)
    rows=[]
    reports=[]
    seen={}
    last_finish=None
    for cap in caps:
        manifest=json.loads(read_pinned(spec,cap["manifest"],downloader))
        start,finish=utc(manifest["started_at"]),utc(manifest["finished_at"])
        if last_finish is not None and start<=last_finish:
            raise ValueError("Capture windows overlap or reverse")
        last_finish=finish
        new,report=read_rows(spec,cap,downloader)
        for row in new:
            if row["ticker"] in seen:
                raise ValueError("Duplicate ticker across sampled settlement captures; requires revision-aware ledger")
            seen[row["ticker"]]=row
        rows.extend(new)
        reports.append(report)
    result_counts=Counter(x["exchange_reported_result"] for x in rows)
    events=defaultdict(list)
    for row in rows: events[row["event_ticker"]].append(row)
    # Do not infer all event families are binary; count exact observed event IDs.
    return {
        "schema_version":1,"authority":"RESEARCH_ONLY","sport":"TENNIS",
        "source_commit":spec["commit"],"captures":reports,
        "n_settlement_rows":len(rows),"n_distinct_settled_tickers":len(seen),
        "n_distinct_exchange_event_tickers":len(events),
        "exchange_result_counts":dict(sorted(result_counts.items())),
        "n_occurrence_timestamps_after_reported_settlement":sum(x["occurrence_later_than_settlement"] for x in rows),
        "exchange_result_source":"PINNED_ARCHIVED_KALSHI_COLLECTOR_FIELDS",
        "independently_authenticated_exchange_result":False,
        "physical_match_identity":"NOT_ESTABLISHED",
        "actual_match_start":"NOT_VERIFIED",
        "pregame_or_execution_authority":"NONE",
        "profitability_authority":"NONE",
        "limitations":[
            "Collector archives Kalshi result fields but does not cryptographically authenticate the exchange response.",
            "A scalar payout of 0.5 is neither a binary YES win nor a binary NO loss.",
            "Occurrence datetime can occur after settlement; never treat it as actual start.",
            "Distinct event tickers are not independently established physical matches.",
            "Sampled settlements cannot imply full-day or season settlement completeness.",
            "No proven pregame observations, fees, fills, calibration, or profitable strategy."
        ],
    },rows

def join_prior_quotes(settlements,quote_rows):
    """Exact-ticker historical quote match; NO inference of pregame eligibility."""
    by_ticker=defaultdict(list)
    for q in quote_rows:
        if q.get("sport")!="TENNIS" or not isinstance(q.get("ticker"),str):
            raise ValueError("Untrusted quote identity")
        at=utc(q.get("observed_at_utc"))
        by_ticker[q["ticker"]].append(at)
    matched=0
    prior_rows=0
    after_rows=0
    for s in settlements:
        settlement_at=utc(s["exchange_reported_settlement_ts"])
        observations=by_ticker.get(s["ticker"],[])
        prior=[at for at in observations if at<=settlement_at]
        after=[at for at in observations if at>settlement_at]
        if prior: matched+=1
        prior_rows+=len(prior)
        after_rows+=len(after)
    return {"n_settled_tickers_with_quote_observed_before_settlement":matched,
            "n_settled_tickers_without_prior_quote":len(settlements)-matched,
            "n_quote_observations_at_or_before_settlement":prior_rows,
            "n_quote_observations_after_settlement_excluded":after_rows,
            "pregame_eligibility":"NOT_VERIFIED_ACTUAL_MATCH_START",
            "execution_or_profitability_authority":"NONE"}
