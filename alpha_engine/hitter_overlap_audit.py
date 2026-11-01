"""Hash-verified, bounded Aug 19/20 MLB hitter forecast overlap audit.

Historical archive presence does not prove publication at the original market
quote, a ModelEvaluation row, player-team truth, or a pregame opportunity.
This is a read-only extension of the issue #7 negative-control repair cycle.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from . import hitter_archive_gate as gate
from . import research_repair as rr

# Exact blob IDs and byte sizes from the cryptographically checked Git tree.
PINS = {
    "2026-08-19": ("6ab8d6e6a694e7b6485a6e63a779c737aa85871b", 5050542),
    "2026-08-20": ("e60edec7a7e2656c3b59574d07c0f7460cde5b17", 4087393),
}
MAX_ROWS_PER_DAY = 15000
MAX_TOTAL_BYTES = 9200000
FAMILIES = {"hitter_hits", "hitter_total_bases", "hitter_hits_runs_rbis", "hitter_rbis"}


def fetch_pinned(date):
    """Exactly two public, revision-pinned reads; fail closed on redirects/size."""
    if date not in PINS:
        raise ValueError("Unapproved historical date")
    sha, size = PINS[date]
    url = (f"https://raw.githubusercontent.com/{rr.REPO}/{rr.COMMIT}/"
           f"data/edgelab/hitter_projection_snapshots/{date}.jsonl")
    with urlopen(Request(url, headers={"User-Agent": "SIFT-Alpha-overlap-audit/1"}), timeout=25) as response:
        if response.geturl() != url:
            raise ValueError("Redirected historical source")
        raw = response.read(size + 1)
    if len(raw) != size or gate.git_hash("blob", raw) != sha:
        raise ValueError("Historical snapshot size/hash mismatch: " + date)
    return raw


def _clock(row, name):
    try:
        return gate._timestamp(row.get(name))
    except (ValueError, TypeError, AttributeError):
        return None


def audit_day(date, raw):
    """Partition every source row into evidence categories without dropping it."""
    if date not in PINS:
        raise ValueError("Unapproved historical date")
    sha, size = PINS[date]
    if not isinstance(raw, bytes) or len(raw) != size or gate.git_hash("blob", raw) != sha:
        raise ValueError("Historical snapshot size/hash mismatch: " + date)
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise ValueError("Non-UTF8 historical snapshot") from exc
    if not 0 < len(lines) <= MAX_ROWS_PER_DAY or any(not line.strip() for line in lines):
        raise ValueError("Missing, blank, or unbounded historical snapshot rows")
    counts, families = Counter(), Counter()
    family_candidates, family_non_candidates = Counter(), Counter()
    seen_ids, seen_tickers = set(), set()
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValueError("Invalid historical JSONL") from exc
        if not isinstance(row, dict):
            raise ValueError("Non-object historical forecast row")
        counts["all_rows"] += 1
        family = row.get("marketFamily")
        family_key = family if isinstance(family, str) else "<MISSING>"
        families[family_key] += 1
        ticker, ident = row.get("marketTicker"), row.get("hitterProjectionSnapshotId")
        valid_identity = (isinstance(ticker, str) and ticker.startswith("KXMLB")
                          and isinstance(ident, str) and len(ident) == 40
                          and all(c in "0123456789abcdef" for c in ident)
                          and isinstance(row.get("playerId"), str) and row["playerId"].isdigit()
                          and type(row.get("gameId")) is int and family in FAMILIES)
        if ticker in seen_tickers or ident in seen_ids:
            counts["duplicate_identity_rows"] += 1
            valid_identity = False
        if ticker is not None:
            seen_tickers.add(ticker)
        if ident is not None:
            seen_ids.add(ident)
        if not valid_identity:
            counts["identity_or_semantics_quarantined"] += 1
        observed = _clock(row, "marketObservedAt")
        forecast = _clock(row, "projectionGeneratedAt")
        snapshot = _clock(row, "snapshotGeneratedAt")
        if observed is None or forecast is None or snapshot is None:
            counts["missing_or_invalid_clock"] += 1
        else:
            if forecast > observed:
                counts["forecast_after_recorded_quote"] += 1
            if snapshot > observed:
                counts["snapshot_after_recorded_quote"] += 1
            if snapshot < forecast:
                counts["snapshot_before_forecast"] += 1
        p = row.get("modelProbability")
        probability_ok = type(p) in (int, float) and 0 <= p <= 1
        if row.get("projectionStatus") != "PROJECTED" or not probability_ok:
            counts["forecast_missing_or_invalid"] += 1
        if row.get("pricingStatus") != "PRICED":
            counts["price_not_priced"] += 1
        if (valid_identity and observed is not None and forecast is not None and snapshot is not None
                and forecast <= snapshot <= observed and probability_ok
                and row.get("projectionStatus") == "PROJECTED"
                and row.get("pricingStatus") == "PRICED"):
            counts["candidate_at_recorded_quote_only"] += 1
            family_candidates[family_key] += 1
        else:
            counts["not_candidate_at_recorded_quote"] += 1
            family_non_candidates[family_key] += 1
    if (counts["candidate_at_recorded_quote_only"] + counts["not_candidate_at_recorded_quote"] != len(lines)
            or any(family_candidates[f] + family_non_candidates[f] != n for f, n in families.items())):
        raise ValueError("Historical family denominator reconciliation failed")
    return {
        "date": date, "source_git_blob_sha1": sha, "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_bytes": size, "source_rows": len(lines),
        "family_source_rows": dict(sorted(families.items())),
        "family_candidate_rows_at_embedded_quote_clock": dict(sorted(family_candidates.items())),
        "family_non_candidate_rows": dict(sorted(family_non_candidates.items())),
        "row_evidence": dict(sorted(counts.items())),
        "original_publication_availability_verified": False,
        "physical_game_and_player_team_verified": False,
        "exact_historical_opportunity_join_verified": False,
    }


def analyze(report, blobs):
    before = rr.audit_mlb(report)
    dates = report["report"].get("datesWithObservations")
    if (before["opportunity_rows"], before["model_evaluated_rows"]) != (138158, 694):
        raise ValueError("Historical denominator/numerator changed")
    if not isinstance(dates, list) or sorted(dates) != [f"2026-08-{d:02d}" for d in range(1, 21)]:
        raise ValueError("Historical observation scope changed")
    if set(blobs) != set(PINS) or sum(len(x) for x in blobs.values()) > MAX_TOTAL_BYTES:
        raise ValueError("Missing/extra or unbounded historical evidence")
    daily = {date: audit_day(date, blobs[date]) for date in sorted(PINS)}
    total = sum(x["source_rows"] for x in daily.values())
    candidates = sum(x["row_evidence"].get("candidate_at_recorded_quote_only", 0) for x in daily.values())
    return {
        "schema_version": 1, "authority": "RESEARCH_ONLY_NO_BACKFILL",
        "source_repository": rr.REPO, "source_commit": rr.COMMIT,
        "source_scope": "PINNED_HITTER_SNAPSHOTS_AUG19_20_ONLY",
        "source_rows_examined": total,
        "candidate_forecast_rows_at_embedded_quote_clock": candidates,
        "independently_valid_historical_evaluations": None,
        "before": {"opportunity_rows": 138158, "evaluated_rows": 694,
                   "hitter_hits_observed": 23295, "hitter_hits_evaluated": 0},
        "after": {"opportunity_rows": 138158, "evaluated_rows": 694,
                  "hitter_hits_observed": 23295, "hitter_hits_evaluated": 0},
        "days": daily,
        "repair_result": "BLOCKED_NO_SAFE_HISTORICAL_REPAIR",
        "blocker": "Embedded timestamps and archived forecast rows do not independently establish forecast publication, original market-tape membership, game/player truth, or an exact ModelEvaluation join. No backfill.",
        "profitability_or_execution_authority": "NONE",
    }


def run():
    manifest = json.loads(Path("research/mlb_repair_source_pins.json").read_text())
    witnesses, _ = rr.load_sources(manifest)
    report = json.loads(witnesses["historical_quality"])
    blobs = {date: fetch_pinned(date) for date in sorted(PINS)}
    return analyze(report, blobs)


def main():
    report = run()
    out = Path("artifacts/mlb_hitter_overlap_audit.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("MLB original overlap snapshots:", report["source_rows_examined"],
          "rows; PIT candidates are NOT independently valid evaluations; original 694/138158 and 0/23295 unchanged.")
    for day in sorted(report["days"]):
        row = report["days"][day]
        print(day, "family_source_rows=", json.dumps(row["family_source_rows"], sort_keys=True),
              "candidate_by_family=", json.dumps(row["family_candidate_rows_at_embedded_quote_clock"], sort_keys=True),
              "noncandidate_by_family=", json.dumps(row["family_non_candidate_rows"], sort_keys=True),
              "row_evidence=", json.dumps(row["row_evidence"], sort_keys=True))
    print("Evidence:", out)


if __name__ == "__main__":
    main()
