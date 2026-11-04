"""Verify PUBLISHED per-period scoring records (the data branch) - a successful workflow is not successful data collection.

Checks per league: manifest hashes, schema completeness, duplicate event_ids, period/final reconciliation, file-date vs
start time (ESPN queries by US-Eastern calendar day), observed_at vs game start, source URL shape, coverage dates, and the
regulation-period scoring means. Output is a summary only (no raw rows). Nothing here claims predictive value.
Usage: python -m alpha_engine.period_scoring_verify DATA_DIR [OUT_JSON]   (DATA_DIR contains MANIFEST.sha256.json + <league>/*.jsonl)"""
import hashlib, json, sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

REQUIRED = ("league", "event_id", "start_time_utc", "home", "away", "home_periods", "away_periods", "home_final", "away_final",
            "observed_at", "source", "source_url", "reconciliation", "n_periods", "regulation_periods", "overtime")
REG = {"nfl": 4, "cfb": 4, "nba": 4, "cbb": 2, "nhl": 3}
URL_PREFIX = "https://site.api.espn.com/apis/site/v2/sports/"


def et_date(start_utc: str) -> str:
    t = datetime.strptime(start_utc, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    off = 4 if 3 <= t.month <= 10 else 5    # EDT Mar-Oct; Nov-Feb EST (2026 DST ends Nov 1 06:00Z; no scoring games start in that gap)
    return (t - timedelta(hours=off)).strftime("%Y-%m-%d")


def verify(data_dir):
    d = Path(data_dir)
    man = json.loads((d / "MANIFEST.sha256.json").read_text())
    bad = [f for f, h in man.items() if hashlib.sha256((d / f).read_bytes()).hexdigest() != h]
    unlisted = sorted(str(p.relative_to(d)) for p in d.glob("*/*.jsonl") if str(p.relative_to(d)) not in man)
    out = {"manifest_files": len(man), "hash_mismatches": bad, "files_not_in_manifest": unlisted, "leagues": {}}
    for lg, reg in REG.items():
        rows, issues, seen = [], Counter(), set()
        for f in sorted((d / lg).glob("*.jsonl")):
            for ln in f.read_text().splitlines():
                if not ln.strip():
                    continue
                try:
                    r = json.loads(ln)
                except ValueError:
                    issues["unparseable_line"] += 1
                    continue
                r["_file_date"] = f.stem
                rows.append(r)
                if any(r.get(k) is None for k in REQUIRED):
                    issues["missing_required_field"] += 1
                    continue
                if r["event_id"] in seen:
                    issues["duplicate_event_id"] += 1
                seen.add(r["event_id"])
                if r["league"] != lg: issues["league_mismatch"] += 1
                if not r["source_url"].startswith(URL_PREFIX) or f.stem.replace("-", "") not in r["source_url"]: issues["source_url_unexpected"] += 1
                if len(r["home_periods"]) != r["n_periods"] or len(r["away_periods"]) != r["n_periods"]: issues["n_periods_mismatch"] += 1
                if r["n_periods"] < reg: issues["fewer_than_regulation"] += 1
                if r["observed_at"][:19] <= r["start_time_utc"][:16] + ":00": issues["observed_not_after_start"] += 1
                if et_date(r["start_time_utc"]) != f.stem: issues["start_et_date_ne_file_date"] += 1
                if (sum(r["home_periods"]), sum(r["away_periods"])) != (r["home_final"], r["away_final"]) and r["reconciliation"] == "RECONCILED": issues["flag_reconciled_but_sums_differ"] += 1
        good = [r for r in rows if r.get("reconciliation") == "RECONCILED" and not any(r.get(k) is None for k in REQUIRED)]
        dates = sorted({r["_file_date"] for r in rows})
        means = []
        for i in range(reg):
            v = [r["home_periods"][i] + r["away_periods"][i] for r in good]
            means.append({"period": i + 1, "n": len(v), "mean_combined": round(sum(v) / len(v), 3) if v else None,
                          "p_zero_combined": round(sum(1 for x in v if x == 0) / len(v), 4) if v else None})
        out["leagues"][lg] = {"rows": len(rows), "reconciled": len(good), "unreconciled": len(rows) - len(good), "overtime_games": sum(bool(r.get("overtime")) for r in rows),
                              "file_dates": len(dates), "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None,
                              "observed_at_range": [min((r["observed_at"] for r in rows), default=None), max((r["observed_at"] for r in rows), default=None)],
                              "issues": dict(issues), "regulation_period_means": means}
    return out


if __name__ == "__main__":
    res = verify(sys.argv[1])
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(res, indent=1, sort_keys=True))
    print(json.dumps(res, indent=1, sort_keys=True))
