"""Build the eight-sport master market inventory from pinned source artifacts.

Usage: python -m alpha_engine.master_inventory SRC_ROOT   (SRC_ROOT holds the cloned sport repos; the NFL clone
path is SRC_ROOT/../nfl-edge-finder when absent from SRC_ROOT).  Output: research/audit/inventory/*.json.

Counts always carry their own basis + as_of. Different sports use different denominators (current archived
snapshot, open-set, prior discovery) - they are never summed across sports. A family with 0 markets is
"not observed in that snapshot", never "does not exist".
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .audit_schema import SCHEMA_VERSION, SPORTS
from .taxonomy import classify

AUDIT = Path(__file__).resolve().parents[1] / "research" / "audit"
SNAP = AUDIT / "snapshots"
REPO = {"NFL": "nfl-edge-finder", "CFB": "cfb-edge-finder", "NBA": "nba-edge-finder", "CBB": "cbb-edge-finder",
        "NHL": "NHL-edge-finder", "MLB": "edge-finder-api", "SOCCER": "soccer-edge-finder", "TENNIS": "Tennis-Edge-Finder"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def head(repo_dir):
    return subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def asof(path):
    m = re.search(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", path)
    return "%s-%s-%sT%s:%s:%sZ" % m.groups() if m else None


def blob(sport, commit, path):
    return f"https://github.com/chmoses98/{REPO[sport]}/blob/{commit}/{path}"


def row(sport, native, series, *, state, markets_now=None, basis, as_of, settlement=None, evidence=(), extra=None, title=None):
    tick = series[0]["ticker"] if series else ""
    cl = classify(sport, native, tick, title or "")
    periods = sorted({classify(sport, native, s["ticker"])["period"] for s in series} or {cl["period"]})
    r = {"id": f"{sport}/{native}", "sport": sport, "native_family": native,
         "canonical": {"kind": cl["kind"], "scope": cl["scope"], "periods": periods},
         "observed": {"state": state, "markets_now": markets_now, "basis": basis, "as_of": as_of},
         "series": series, "settlement": settlement or {"text": None, "source": None, "status": "UNKNOWN"},
         "evidence": list(evidence)}
    if extra:
        r.update(extra)
    return r


def snap_rows(sport, fam_of, settle_of, *, extra_series=()):
    s = json.loads((SNAP / f"{sport}_series_snapshot.json").read_text())
    src = s["source"]
    ev = [{"label": f"{sport} full-market snapshot {src['path']}", "url": blob(sport, src["commit"], src["path"])}]
    fams = collections.defaultdict(list)
    for t, v in s["series"].items():
        fams[fam_of(t, v)].append({"ticker": t, "title": v.get("sample_title"), "markets_now": v["markets"], "status": v["status"]})
    return s, fams, ev, src


def finish(sport, s, fams, ev, settle_of, now_basis, extras=None):
    rows = []
    for fam, ser in sorted(fams.items()):
        n = sum(x["markets_now"] for x in ser)
        rows.append(row(sport, fam, ser, state="OBSERVED_NOW" if n else "DEFINED_NOT_OBSERVED", markets_now=n,
                        basis=now_basis, as_of=asof(s["source"]["path"]), settlement=settle_of(fam, ser), evidence=ev,
                        title=ser[0].get("title") if ser else None))
    return rows


def rules_settle(ser, rules):
    t = next((rules.get(x["ticker"]) for x in ser if rules.get(x["ticker"])), None)
    return {"text": t, "source": "rules_primary of a sampled market in the snapshot", "status": "SAMPLED_CONTRACT_TEXT"} if t else None


def ontology_rows(sport, repo_dir, summary_key):
    onto = yaml.safe_load(open(repo_dir / "data/catalog/market_ontology.yaml"))["families"]
    s = json.loads((SNAP / f"{sport}_series_snapshot.json").read_text())
    src = s["source"]
    t2f = {t: f for f, v in onto.items() for t in v.get("series_tickers", [])}
    pats = [(re.compile(rx), f) for f, v in onto.items() for rx in v.get("series_patterns", [])]
    ev = [{"label": f"{sport} full-market snapshot", "url": blob(sport, src["commit"], src["path"])},
          {"label": "market ontology", "url": blob(sport, head(repo_dir), "data/catalog/market_ontology.yaml")}]
    by = collections.defaultdict(list)
    rules = {}
    for t, v in s["series"].items():
        fam = t2f.get(t) or next((f for rx, f in pats if rx.search(t)), None)
        if fam is None:
            fam = "UNMAPPED_SERIES"
        by[fam].append({"ticker": t, "title": v.get("sample_title"), "markets_now": v["markets"], "status": v["status"]})
        rules[t] = v.get("rules_sample")
    rows = []
    for fam, v in onto.items():
        ser = by.get(fam, [])
        # ontology tickers with no market in the snapshot are listed as defined, 0 now
        for t in v.get("series_tickers", []):
            if t not in {x["ticker"] for x in ser}:
                ser.append({"ticker": t, "title": None, "markets_now": 0, "status": {}})
        n = sum(x["markets_now"] for x in ser)
        r = row(sport, fam, ser, state="OBSERVED_NOW" if n else "DEFINED_NOT_OBSERVED", markets_now=n,
                basis="markets in latest archived full snapshot", as_of=asof(s["source"]["path"]),
                settlement={"text": v.get("settlement_notes") or rules_settle(ser, rules) and rules_settle(ser, rules)["text"],
                            "source": "market_ontology.yaml settlement_notes" if v.get("settlement_notes") else "sampled rules_primary",
                            "status": "REPO_ASSERTED"},
                evidence=ev, title=v.get("description"),
                extra={"repo_support": v.get("support"), "ontology": {"scope": v.get("scope"), "stat": v.get("stat"), "period": v.get("period")}})
        # ontology scope/stat refine the shared classification
        r["canonical"]["scope"] = {"game": "game", "player": "player", "season": "season"}.get(v.get("scope"), r["canonical"]["scope"])
        rows.append(r)
    if by.get("UNMAPPED_SERIES"):
        ser = by["UNMAPPED_SERIES"]
        rows.append(row(sport, "UNMAPPED_SERIES", ser, state="OBSERVED_NOW", markets_now=sum(x["markets_now"] for x in ser),
                        basis="series in snapshot absent from the repo's own ontology (collection/model blind spot)",
                        as_of=asof(s["source"]["path"]), evidence=ev))
    return rows, s


def build_nfl(repo_dir):
    reg = json.loads((repo_dir / "config/kalshi_nfl_series.json").read_text())["series"]
    s = json.loads((SNAP / "NFL_series_snapshot.json").read_text())
    sem = json.loads((SNAP / "NFL_semantics_catalog.json").read_text())
    semf = collections.defaultdict(list)
    for e in sem["entries"]:
        semf[e["family"]].append(e)
    src = s["source"]
    ev = [{"label": "series registry", "url": blob("NFL", head(repo_dir), "config/kalshi_nfl_series.json")},
          {"label": "open-set snapshot", "url": blob("NFL", src["commit"], src["path"])}]
    by = collections.defaultdict(list)
    for t, v in reg.items():
        now = s["series"].get(t, {}).get("markets", 0)
        by[v["family"]].append({"ticker": t, "title": v["title"], "markets_now": now, "markets_prior_snapshot": v.get("markets_seen", 0), "status": s["series"].get(t, {}).get("status", {})})
    for t, v in s["series"].items():
        if t not in reg:
            by["UNREGISTERED_SERIES"].append({"ticker": t, "title": None, "markets_now": v["markets"], "markets_prior_snapshot": None, "status": v["status"]})
    rows = []
    for fam, ser in sorted(by.items()):
        n = sum(x["markets_now"] for x in ser); prior = sum(x.get("markets_prior_snapshot") or 0 for x in ser)
        ents = semf.get(fam, [])
        st = {"text": "; ".join(sorted({f"{e['period']}: {e['yes_rule']} | push: {e['push_rule']} | OT: {e['overtime']}" for e in ents}))[:900] or None,
              "source": "nfl_edge/semantics/catalog.py FAMILY_CATALOG", "status": "REPO_ASSERTED"} if ents else None
        state = "OBSERVED_NOW" if n else ("OBSERVED_PRIOR_SNAPSHOT_ONLY" if prior else "DEFINED_NOT_OBSERVED")
        rows.append(row("NFL", fam, ser, state=state, markets_now=n, basis="open markets in latest full open-set (no closed/settled)",
                        as_of=json.loads((SNAP / "NFL_series_snapshot.json").read_text())["note"].split("observed_at ")[1].split(",")[0],
                        settlement=st, evidence=ev, extra={"markets_prior_registry_snapshot": prior, "prior_snapshot_date": "2026-09-04"}))
    return rows, s


def build_cbb(repo_dir):
    s = json.loads((SNAP / "CBB_series_snapshot.json").read_text()); src = s["source"]
    ev = [{"label": "CBB archived snapshot", "url": blob("CBB", src["commit"], src["path"])},
          {"label": "cbb_edge/kalshi/taxonomy.py", "url": blob("CBB", head(repo_dir), "cbb_edge/kalshi/taxonomy.py")}]
    by = collections.defaultdict(list); rules = {}
    for t, v in s["series"].items():
        by[v.get("native_family") or "UNKNOWN"].append({"ticker": t, "title": v.get("sample_title"), "markets_now": v["markets"], "status": v["status"]}); rules[t] = v.get("rules_sample")
    rows = [row("CBB", fam, ser, state="OBSERVED_NOW", markets_now=sum(x["markets_now"] for x in ser), basis="markets (all statuses) in latest archived CBB snapshot",
                as_of="2026-11-02T00:18:46Z", settlement=rules_settle(ser, rules), evidence=ev) for fam, ser in sorted(by.items())]
    return rows, s


def build_cfb(repo_dir):
    p = repo_dir / "data/live/cfb_market_catalog.json"; d = json.loads(p.read_text())
    fam = collections.defaultdict(lambda: {"n": 0, "series": collections.Counter(), "status": collections.Counter(), "rules": {}, "title": {}})
    for g in d["games"]:
        for m in json.loads((repo_dir / "data/live" / g["markets_file"]).read_text()).get("markets", []):
            f = fam[m.get("family")]; sr = m.get("series_ticker") or m.get("event_ticker", "").split("-")[0]
            f["n"] += 1; f["series"][sr] += 1; f["status"][m.get("status", "?")] += 1
            f["rules"].setdefault(sr, (m.get("rules_primary") or "")[:400] or None); f["title"].setdefault(sr, m.get("title"))
    ev = [{"label": "CFB market catalog", "url": blob("CFB", head(repo_dir), "data/live/cfb_market_catalog.json")}]
    cap = d["capture"]["captured_at"]
    rows = []
    for f, v in sorted(fam.items()):
        ser = [{"ticker": t, "title": v["title"].get(t), "markets_now": n, "status": {}} for t, n in v["series"].items()]
        rows.append(row("CFB", f, ser, state="OBSERVED_NOW", markets_now=v["n"], basis="markets (active+finalized) across the games in the catalog", as_of=cap,
                        settlement=rules_settle(ser, v["rules"]), evidence=ev, extra={"status_counts": dict(v["status"])}))
    for e in d["season_level_events"][:0]:
        pass
    sl = collections.Counter((e.get("event_ticker") or "").split("-")[0] for e in d["season_level_events"])
    if sl:
        ser = [{"ticker": t, "title": None, "markets_now": None, "status": {}} for t in sorted(sl)]
        rows.append(row("CFB", "season_level_events", ser, state="OBSERVED_NOW", markets_now=None, basis=f"{len(d['season_level_events'])} season-level events; market counts not in catalog", as_of=cap, evidence=ev))
    return rows, {"source": {"commit": head(repo_dir), "path": "data/live/cfb_market_catalog.json", "sha256": sha(p)}, "totals": d["totals"], "completeness": d["completeness"]["capture_complete"]}


def build_mlb(repo_dir):
    day = "2026-10-28"; base = repo_dir / "data/kalshi/discovery"
    d = json.loads((base / f"{day}.json").read_text()); cat = json.loads((base / f"{day}_series_catalogue.json").read_text())
    ev = [{"label": "MLB discovery", "url": blob("MLB", head(repo_dir), f"data/kalshi/discovery/{day}.json")},
          {"label": "MLB series catalogue", "url": blob("MLB", head(repo_dir), f"data/kalshi/discovery/{day}_series_catalogue.json")}]
    by = collections.defaultdict(lambda: {"n": 0, "series": collections.Counter(), "periods": set(), "t": {}})
    for c in d["contracts"]:
        f = by[c.get("marketFamily") or "unknown"]; f["n"] += 1; f["series"][c["seriesTicker"]] += 1; f["periods"].add(c.get("period")); f["t"].setdefault(c["seriesTicker"], c.get("marketTitle"))
    rows = []
    known = set()
    for f, v in sorted(by.items()):
        ser = [{"ticker": t, "title": v["t"].get(t), "markets_now": n, "status": {}} for t, n in v["series"].items()]
        known |= set(v["series"])
        r = row("MLB", f, ser, state="OBSERVED_NOW", markets_now=v["n"], basis=f"contracts discovered for slate date {day} (one day, MLB season ended)", as_of=cat["generatedAt"], evidence=ev, extra={"native_periods": sorted(p for p in v["periods"] if p)})
        r["canonical"]["kind"] = classify("MLB", f, ser[0]["ticker"])["kind"]
        rows.append(r)
    rest = [x for x in cat["mlbAssociatedSeries"] if x["seriesTicker"] not in known]
    ser = [{"ticker": x["seriesTicker"], "title": x["title"], "markets_now": x.get("marketCount"), "status": {}, "query_skipped": x.get("perSeriesQuerySkippedReason")} for x in rest]
    rows.append(row("MLB", "SERIES_LISTED_NOT_QUERIED", ser, state="SERIES_LISTED_COUNTS_UNKNOWN", markets_now=None,
                    basis=f"{len(ser)} MLB-associated series on the exchange whose markets were not enumerated ({cat['seriesSkippedCount']} skipped, e.g. NOT_IN_STRICT_SINGLE_GAME_REGISTRY)", as_of=cat["generatedAt"], evidence=ev))
    return rows, {"source": {"commit": head(repo_dir), "path": f"data/kalshi/discovery/{day}.json"}, "summary": json.loads((base / f"{day}_summary.json").read_text()), "series_listed": cat["mlbAssociatedSeriesCount"]}


def build_soccer(repo_dir):
    p = repo_dir / "data/catalog/latest_index.json"; d = json.loads(p.read_text()); c = d["counters"]
    ev = [{"label": "soccer discovery index", "url": blob("SOCCER", head(repo_dir), "data/catalog/latest_index.json")},
          {"label": "market map", "url": blob("SOCCER", head(repo_dir), "docs/KALSHI_MARKET_MAP.md")}]
    note = {"match_result_3way": "Settles after 90 minutes plus stoppage; excludes extra time and penalties (docs/KALSHI_MARKET_MAP.md, from rules_primary)",
            "total_goals": "Regulation (90 min + stoppage) goals vs floor_strike line", "team_total": "Regulation team goals vs floor_strike line",
            "handicap": "Regulation margin vs floor_strike line", "btts": "Regulation both teams score", "exact_score": "Regulation exact score",
            "first_to_score": "FTTS counts regulation, stoppage and extra time"}
    rows = []
    for f, n in sorted(c["contracts_by_family"].items(), key=lambda kv: -kv[1]):
        st = {"text": note[f], "source": "docs/KALSHI_MARKET_MAP.md (verified from rules_primary by repo)", "status": "REPO_ASSERTED"} if f in note else None
        rows.append(row("SOCCER", f, [], state="OBSERVED_PRIOR_SNAPSHOT_ONLY", markets_now=None, basis="contracts discovered in the 2026-09-27 discovery (swept soccer series only)",
                        as_of=d.get("finished_at"), settlement=st, evidence=ev, extra={"markets_prior_snapshot": n, "prior_snapshot_date": "2026-09-27"}))
    return rows, {"source": {"commit": head(repo_dir), "path": "data/catalog/latest_index.json", "sha256": sha(p)},
                  "series_swept": c["series_swept"], "series_ambiguous_unswept": c["series_ambiguous_unswept"], "contracts_discovered": c["contracts_discovered"], "run_id": c["run_id"]}


def build_tennis(repo_dir):
    p = repo_dir / "config/kalshi_tennis_series.json"; d = json.loads(p.read_text())
    ev = [{"label": "tennis series inventory", "url": blob("TENNIS", head(repo_dir), "config/kalshi_tennis_series.json")},
          {"label": "tennis taxonomy", "url": blob("TENNIS", head(repo_dir), "docs/KALSHI_MARKET_TAXONOMY.md")}]
    by = collections.defaultdict(list)
    for s in d["tennis_series"]:
        live = sum((s.get("markets_by_status") or {}).values())
        by[s["family"]].append({"ticker": s["ticker"], "title": s["title"], "markets_now": live, "markets_historical_archived_tier": s.get("historical_markets"), "status": s.get("markets_by_status") or {}})
    rows = []
    for f, ser in sorted(by.items()):
        live = sum(x["markets_now"] for x in ser); hist = sum(x.get("markets_historical_archived_tier") or 0 for x in ser)
        rows.append(row("TENNIS", f, ser, state="OBSERVED_PRIOR_SNAPSHOT_ONLY" if (live or hist) else "DEFINED_NOT_OBSERVED", markets_now=live,
                        basis="live-tier markets (open/unopened/closed/settled) at the 2026-09-11 discovery; historical archived-tier counted separately", as_of=d["snapshot_started_at"],
                        evidence=ev, extra={"markets_historical_archived_tier": hist, "projectable_per_repo": any(s.get("projectable") for s in d["tennis_series"] if s["family"] == f)}))
    return rows, {"source": {"commit": head(repo_dir), "path": "config/kalshi_tennis_series.json", "sha256": sha(p)}, "series_total_on_exchange": d["series_total_on_exchange"], "coverage": d.get("coverage")}


def main(argv=None):
    src = Path((argv or sys.argv[1:])[0])
    nfl = Path("/home/user/nfl-edge-finder")
    out = AUDIT / "inventory"; out.mkdir(exist_ok=True)
    builders = {"NFL": lambda: build_nfl(nfl), "CFB": lambda: build_cfb(src / REPO["CFB"]), "CBB": lambda: build_cbb(src / REPO["CBB"]),
                "NBA": lambda: ontology_rows("NBA", src / REPO["NBA"], "nba_series"), "NHL": lambda: ontology_rows("NHL", src / REPO["NHL"], "nhl_series"),
                "MLB": lambda: build_mlb(src / REPO["MLB"]), "SOCCER": lambda: build_soccer(src / REPO["SOCCER"]), "TENNIS": lambda: build_tennis(src / REPO["TENNIS"])}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    master = {"schema_version": SCHEMA_VERSION, "generated_utc": now, "sports": {}, "families": []}
    for sp in SPORTS:
        rows, meta = builders[sp]()
        sp_doc = {"schema_version": SCHEMA_VERSION, "sport": sp, "generated_utc": now, "source_meta": meta, "families": rows}
        (out / f"{sp}.json").write_text(json.dumps(sp_doc, indent=1))
        unc = [r["id"] for r in rows if r["canonical"]["kind"] == "unclassified"]
        master["sports"][sp] = {"families": len(rows), "families_observed_now": sum(r["observed"]["state"] == "OBSERVED_NOW" for r in rows),
                                "series": sum(len(r["series"]) for r in rows), "unclassified_families": unc,
                                "markets_now_basis_sum": sum((r["observed"]["markets_now"] or 0) for r in rows)}
        master["families"] += [{k: r[k] for k in ("id", "sport", "native_family", "canonical", "observed", "settlement")} | {k: r[k] for k in ("markets_prior_snapshot", "prior_snapshot_date", "markets_prior_registry_snapshot", "markets_historical_archived_tier", "repo_support") if k in r} | {"series_count": len(r["series"]), "series_sample": [s["ticker"] for s in r["series"][:6]]} for r in rows]
        print(sp, master["sports"][sp]["families"], "families", master["sports"][sp]["markets_now_basis_sum"], "markets", "unclassified:", unc)
    (AUDIT / "master_inventory.json").write_text(json.dumps(master, indent=1))


if __name__ == "__main__":
    main()
