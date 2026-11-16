"""Six-sport official-vs-computed settlement reconciliation over the private vault (RESEARCH_ONLY, read-only).

    python -m alpha_engine.game_completeness.settlement_reconcile \
        --official-root RESTORED --as-of <ts> --out research/settlement_reconcile \
        --computed MLB='EFA/data/edgelab/settlements/*.jsonl*' NBA='DA_NBA/settlements/*/*.jsonl.gz' \
                   NHL='DA_NHL/settlements/*/*.jsonl.gz' NFL='MD/data/shadow/v2/settlements/*/*.jsonl.gz' \
        --overlay MLB=corrections.json --known research/settlement_discrepancies/nhl_nba_20261116.json ...

RESTORED holds one folder per sport restored from the vault's `kalshi_official_settlements` archives
(`python tools/vault.py restore`).  Nothing is fetched and no Kalshi row is written to the output: evidence files
carry counts, series names and contract tickers only.

Three layers stay separate and none is ever relabelled as another:
  1. OFFICIAL: the exchange's own result (vault archive).
  2. COMPUTED: the result our engines archived (each sport repo's settlement archive), unmodified.
  3. COMPUTED+OVERLAY: layer 2 with a versioned correction overlay applied in memory (e.g. the MLB regrade).
Independently observed sports results (box scores) are a fourth source, used by `official_values` / `prop_review`.

Official rows are bucketed by settlement class before any comparison, so administrative, fair-price and void
settlements are never counted as agreement or disagreement with a box-score-derived result.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA = "settlement-reconcile-1.0"
SPORTS = ("MLB", "CFB", "CBB", "NFL", "NBA", "NHL")
# Official classes whose result is decided by the sports outcome (comparable with a computed result).
COMPARABLE = ("VALUE_SETTLED", "LITERAL_VALUE_TRADED", "NO_EXPIRATION_VALUE")
NONSTANDARD = ("ADMIN_LITERAL_UNTRADED", "FAIR_PRICE_SETTLEMENT", "VOID_OR_SCALAR", "NO_RESULT")


def official_class(m):
    """Same classes as the vault's `tools/kalshi_settlements.py summarize` (kept identical on purpose)."""
    res, sv = m.get("result"), m.get("settlement_value_dollars")
    ev = str(m.get("expiration_value") or "").strip().lower()
    try:
        vol = float(m.get("volume_fp") or 0)
    except (TypeError, ValueError):
        vol = 0.0
    if res not in ("yes", "no"):
        return "VOID_OR_SCALAR" if res else "NO_RESULT"
    if sv not in (None, "0.0000", "1.0000", "0", "1"):
        return "FAIR_PRICE_SETTLEMENT"
    if ev in ("yes", "no"):
        return "ADMIN_LITERAL_UNTRADED" if vol == 0 else "LITERAL_VALUE_TRADED"
    return "NO_EXPIRATION_VALUE" if ev == "" else "VALUE_SETTLED"


def _open(path):
    return gzip.open(path, "rt", encoding="utf-8") if str(path).endswith(".gz") else open(path, encoding="utf-8")


def iter_official(root, sport):
    """Yield (series, row) for every official row of a sport; a live-tier row replaces a historical one."""
    base = Path(root) / sport
    files = sorted(list(base.glob("**/*.jsonl")) + list(base.glob("**/*.jsonl.gz")),
                   key=lambda p: (".live." in p.name, p.name))  # historical first, live last
    for f in files:
        series = f.name.split(".")[0]
        with _open(f) as fh:
            for line in fh:
                if line.strip():
                    yield series, json.loads(line)


def load_official(root, sport, stats_out=None):
    """{ticker: (result, class, expiration_value, settled_day, series)}: the minimum needed to compare."""
    out = {}
    stats = Counter()
    for series, m in iter_official(root, sport):
        row = (m.get("result") or "", official_class(m), m.get("expiration_value"),
               (m.get("settlement_ts") or m.get("close_time") or "")[:10], series)
        stats["rows"] += 1
        prev = out.get(m["ticker"])
        if prev is not None:
            stats["served_by_both_tiers"] += 1
            if prev[0] != row[0] or str(prev[2]) != str(row[2]):
                stats["tiers_disagree_on_result_or_value"] += 1
        out[m["ticker"]] = row
    if stats_out is not None:
        stats_out.update(stats)
    return out


def _side(r):
    """One computed row -> 'YES' | 'NO' | other label.  Handles the four archive dialects without guessing."""
    if "settled_yes" in r or "settlement_status" in r:  # NFL shadow-v2 corpus
        if r.get("settlement_status") != "SETTLED" or r.get("settlement_kind", "binary") != "binary":
            return str(r.get("settlement_status") or "UNSETTLED")
        y = r.get("settled_yes")
        return "YES" if y == 1 else "NO" if y == 0 else "NON_BINARY"
    v = r.get("outcome") if r.get("outcome") is not None else r.get("result")
    return str(v).upper() if v is not None else "NONE"


def load_computed(pattern):
    """Latest row per ticker (files in name order, rows in order).  Returns ({ticker: side}, meta counters).
    A ticker settled more than once with different sides is counted in `self_conflict` (latest still wins)."""
    out, meta, seen = {}, Counter(), {}
    for f in sorted(glob.glob(pattern, recursive=True)):
        meta["files"] += 1
        with _open(f) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    meta["unparseable_rows"] += 1
                    continue
                t = r.get("ticker") or r.get("marketTicker")
                if not t:
                    continue
                meta["rows"] += 1
                s = _side(r)
                if s in ("YES", "NO") and seen.get(t, s) != s:
                    meta["self_conflict"] += 1
                if s in ("YES", "NO"):
                    seen[t] = s
                out[t] = s
                ver = r.get("engine_version") or r.get("settlement_rule_version")
                if ver:
                    meta[f"engine:{ver}"] += 1
    return out, meta


def apply_overlay(computed, overlay):
    """Layer 3.  Refuses a stale overlay (archived side differs from the archive read here)."""
    out, applied = dict(computed), 0
    for t, c in overlay["corrections"].items():
        if t in out:
            if out[t] != c["archived"]:
                raise ValueError(f"overlay is stale for {t}: archive {out[t]}, overlay expected {c['archived']}")
            out[t] = c["regraded"]
            applied += 1
    return out, applied


def compare(official, computed):
    """Per-series join of one computed layer against the official layer."""
    by = defaultdict(Counter)
    disagree, recoverable = [], Counter()
    for t, side in computed.items():
        ser = t.split("-")[0]
        o = official.get(t)
        if o is None:
            by[ser]["computed_without_official"] += 1
            continue
        res, cls = o[0], o[1]
        by[ser]["joined"] += 1
        if cls not in COMPARABLE:
            by[ser]["official_nonstandard"] += 1
            by[ser][f"official_nonstandard:{cls}"] += 1
            if side in ("YES", "NO") and res in ("yes", "no") and side.lower() != res:
                by[ser]["nonstandard_differs_from_computed"] += 1
        elif side not in ("YES", "NO"):
            by[ser]["computed_unsettled_official_settled"] += 1
            recoverable[side] += 1
        elif side.lower() == res:
            by[ser]["agree"] += 1
        else:
            by[ser]["disagree"] += 1
            disagree.append(t)
    return by, sorted(disagree), recoverable


def reconcile_sport(sport, official, computed=None, meta=None, overlay=None, known=None):
    """Evidence block for one sport.  `known`: {ticker: cause} from earlier committed research."""
    series = defaultdict(Counter)
    days = Counter()
    for t, (res, cls, _ev, day, ser) in official.items():
        series[ser]["official"] += 1
        series[ser][f"class:{cls}"] += 1
        days[day[:7]] += 1
    tot = Counter()
    for c in series.values():
        tot.update(c)
    out = {"official": {"contracts": len(official), "series": len(series),
                        "by_class": {k[6:]: v for k, v in sorted(tot.items()) if k.startswith("class:")},
                        "nonstandard": sum(v for k, v in tot.items() if k[6:] in NONSTANDARD),
                        "by_settlement_month": dict(sorted(days.items()))}}
    if computed is None:
        out["computed"] = None
        out["by_series"] = {s: dict(sorted(c.items())) for s, c in sorted(series.items())}
        return out
    by, dis, rec = compare(official, computed)
    comp_series = {t.split("-")[0] for t in computed}
    tc = Counter()
    for c in by.values():
        tc.update(c)
    binary = sum(1 for s in computed.values() if s in ("YES", "NO"))
    out["computed"] = {"contracts": len(computed), "binary": binary, "series": len(comp_series),
                       "archive": {k: v for k, v in sorted((meta or {}).items())},
                       "counts": {k: v for k, v in sorted(tc.items()) if ":" not in k},
                       "official_nonstandard_joined": {k.split(":", 1)[1]: v for k, v in sorted(tc.items()) if ":" in k},
                       "unsettled_labels_recoverable_from_official": dict(rec.most_common()),
                       "agreement_rate": round(tc["agree"] / max(1, tc["agree"] + tc["disagree"]), 6),
                       "official_in_computed_series_without_computed":
                           sum(1 for t, o in official.items() if o[4] in comp_series and t not in computed),
                       "official_series_never_computed": sorted(set(series) - comp_series)}
    known = known or {}
    causes = Counter(known.get(t, "NOT_PREVIOUSLY_RESEARCHED") for t in dis)
    out["disagreements"] = {"n": len(dis), "by_series": dict(Counter(t.split("-")[0] for t in dis).most_common()),
                            "by_prior_research_cause": dict(causes.most_common()),
                            "by_official_settlement_month": dict(sorted(Counter(official[t][3][:7] for t in dis).items())),
                            "tickers": dis,
                            "not_previously_researched": [t for t in dis if t not in known]}
    out["historical_evaluations_that_would_change"] = {
        "labels_flipped_if_official_adopted": len(dis),
        "labels_gained_if_official_adopted": tc["computed_unsettled_official_settled"],
        "note": "A flip changes every evaluation row that scored that contract; a gain adds a label where the "
                "engine left the contract unsettled.  Nonstandard official settlements are excluded from both."}
    if overlay is not None:
        corrected, applied = apply_overlay(computed, overlay)
        by2, dis2, _ = compare(official, corrected)
        t2 = Counter()
        for c in by2.values():
            t2.update(c)
        fixed = sorted(set(dis) - set(dis2))
        out["with_overlay"] = {"corrections_in_overlay": len(overlay["corrections"]), "applied": applied,
                               "agree": t2["agree"], "disagree": t2["disagree"],
                               "disagreements_fixed": len(fixed), "disagreements_introduced": sorted(set(dis2) - set(dis)),
                               "overlay_rows_not_disagreeing_before": applied - len(fixed),
                               "remaining_by_series": dict(Counter(t.split("-")[0] for t in dis2).most_common()),
                               "remaining_tickers": dis2}
    keep = {}
    for s in sorted(set(series) | set(by)):
        row = dict(sorted(series[s].items()))
        row.update({k: v for k, v in sorted(by[s].items())})
        keep[s] = row
    out["by_series"] = keep
    return out


def load_known(paths):
    """Causes recorded by earlier committed research, keyed by ticker (first file wins)."""
    known = {}
    for p in paths or []:
        d = json.loads(Path(p).read_text())
        for r in d.get("tickers") or d.get("items") or []:
            if isinstance(r, dict) and r.get("ticker"):
                known.setdefault(r["ticker"], r.get("cause") or r.get("class") or "RESEARCHED")
    return known


def _kv(items):
    return dict(i.split("=", 1) for i in items or [])


def run(official_root, computed_globs, overlays, known_paths, as_of, sports=SPORTS):
    known = load_known(known_paths)
    doc = {"schema": SCHEMA, "as_of": as_of, "research_only": True,
           "notice": "Agent-run, not human verified. Official rows are read from the private vault and are not "
                     "reproduced here: counts, series and contract tickers only. Layers are never merged.",
           "official_classes": {"comparable": COMPARABLE, "nonstandard": NONSTANDARD}, "sports": {}}
    for sport in sports:
        ostats = Counter()
        official = load_official(official_root, sport, ostats)
        computed = meta = overlay = None
        if sport in computed_globs:
            computed, meta = load_computed(computed_globs[sport])
        if sport in overlays:
            raw = Path(overlays[sport]).read_bytes()
            overlay = json.loads(raw)
        blk = reconcile_sport(sport, official, computed, meta, overlay, known)
        blk["official"]["archive_rows"] = dict(sorted(ostats.items()))
        if overlay is not None:
            blk["with_overlay"]["overlay_sha256"] = hashlib.sha256(raw).hexdigest()
        doc["sports"][sport] = blk
    return doc


def summary_md(doc):
    L = ["# Official vs computed settlements, six sports (RESEARCH_ONLY)", "",
         f"As of {doc['as_of']}. Generated by `alpha_engine.game_completeness.settlement_reconcile`. Agent-run, not "
         "human verified. Counts only; official rows stay in the private vault.", "",
         "| Sport | Official contracts | Nonstandard (admin / fair-price / void) | Computed | Joined | Agree | Disagree "
         "| Agreement | Engine unsettled, exchange settled | Disagree after overlay |", "|---|---|---|---|---|---|---|---|---|---|"]
    for s, b in doc["sports"].items():
        o, c = b["official"], b["computed"]
        if not c:
            L.append(f"| {s} | {o['contracts']:,} | {o['nonstandard']:,} | none archived | | | | | | |")
            continue
        k = c["counts"]
        ov = b.get("with_overlay")
        L.append(f"| {s} | {o['contracts']:,} | {o['nonstandard']:,} | {c['contracts']:,} | {k.get('joined', 0):,} | "
                 f"{k.get('agree', 0):,} | {k.get('disagree', 0):,} | {100 * c['agreement_rate']:.3f}% | "
                 f"{k.get('computed_unsettled_official_settled', 0):,} | {ov['disagree'] if ov else ''} |")
    for s, b in doc["sports"].items():
        d = b.get("disagreements")
        if not d:
            continue
        L += ["", f"## {s}: {d['n']} disagreements", "",
              "By series: " + ", ".join(f"{k} {v}" for k, v in d["by_series"].items()) + ".", "",
              "By earlier research cause: " + ", ".join(f"{k} {v}" for k, v in d["by_prior_research_cause"].items()) + "."]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--official-root", required=True)
    ap.add_argument("--computed", nargs="*", default=[], metavar="SPORT=GLOB")
    ap.add_argument("--overlay", nargs="*", default=[], metavar="SPORT=FILE")
    ap.add_argument("--known", nargs="*", default=[])
    ap.add_argument("--sports", nargs="*", default=list(SPORTS))
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    doc = run(a.official_root, _kv(a.computed), _kv(a.overlay), a.known, a.as_of, a.sports)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for s, b in doc["sports"].items():
        (out / f"{s}.json").write_text(json.dumps({"schema": SCHEMA, "as_of": a.as_of, "sport": s, **b}, indent=1, sort_keys=True) + "\n")
    brief = {k: v for k, v in doc.items() if k != "sports"}
    brief["sports"] = {s: {"official": b["official"], "computed": b["computed"],
                           "disagreements": b.get("disagreements", {}).get("n"),
                           "disagree_after_overlay": (b.get("with_overlay") or {}).get("disagree")}
                       for s, b in doc["sports"].items()}
    (out / "overview.json").write_text(json.dumps(brief, indent=1, sort_keys=True) + "\n")
    (out / "SUMMARY.md").write_text(summary_md(doc))
    print(summary_md(doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
