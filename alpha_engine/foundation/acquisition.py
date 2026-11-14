"""Buy-versus-build data acquisition plan and training-readiness view (RESEARCH_ONLY).

    python -m alpha_engine.foundation.acquisition

Joins artifacts that already exist; it does no new research, collection or scoring of models:
  * the approved Market & Input Map (archetypes, input -> data-need -> dataset edges, missing PRIMARY slots),
  * the data-foundation dataset and source registries (access status, history, point-in-time, cost labels),
  * the source-acquisition board (terms readings, reachability),
  * the hand-curated provider catalog (research/provider_licensing/provider_catalog.json: links, tiers, verified prices),
  * the pipeline ledger (stage of every input, built features, challengers).

Writes research/data_foundation_ops/acquisition_plan.json (summary, rendered first) and acquisition_inputs.json (per-input detail,
loaded on demand by the dashboard).

Counting rules (tested in tests/test_acquisition.py):
  * An input needs one dataset for EACH of its data needs (TEAM_BOX, EVENT, AVAIL, ...); any SATISFIED_BY dataset for a need is an
    alternative. An input is "data-complete" only when every need has at least one dataset we hold.
  * "Held" = data already in an owner archive (access COLLECTED_ARCHIVE). Holding data is not permission: rights stay visible.
  * Unlock counts are DISTINCT inputs: an input that appears in many markets or behind several provider options counts once.
  * The roadmap is a greedy set cover inside each cost tier (free -> low cost -> higher cost), so each step reports only the inputs it
    newly completes given every earlier step. Utility weights are an ESTIMATE (documented in WEIGHTS) and never a predicted model gain.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict

from .contract import OPS, ROOT, write_json

MAP = ROOT / "research/input_research/market_input_map"
DF = ROOT / "research/input_research/data_foundation"
CATALOG = ROOT / "research/provider_licensing/provider_catalog.json"

SPORT_TIER = {"NBA": "P0", "CBB": "P0", "NHL": "P0", "NFL": "P1", "CFB": "P1", "MLB": "P2", "SOCCER": "P2", "TENNIS": "P2"}
SPORTS = ["NBA", "CBB", "NHL", "NFL", "CFB", "MLB", "SOCCER", "TENNIS"]
TIER_W = {"P0": 4.0, "P1": 2.0, "P2": 1.0}
# Core = game lines, totals, periods and player/stat props: the markets a projection model prices every day. Everything else
# (awards, drafts, futures, specials, exhibitions) still counts, at weight 1.
CORE_RE = re.compile(r"(game|player|total|spread|moneyline|margin|half|quarter|period|props|passing|rushing|receiving|skater|goalie|pitcher|hitter|"
                     r"match_|set_|inning|f5|corners|cards|first_basket|race_to|team_total|anytime|shots|points|rebounds|assists|threes)")
NOT_CORE_RE = re.compile(r"(award|draft|futures|season|all_star|coach|off_|summer|parlay|mvp|cup|bracket|tournament|escalator|special|exhibition|portal|recruit)")
WEIGHTS = {
    "basis": "ESTIMATE",
    "input_weight": "sport tier (P0 4, P1 2, P2 1) x (1 + log2(1 + markets where the input is a missing PRIMARY slot)) x 1.5 if any of those markets is a core market",
    "partial_credit": "a dataset that resolves some but not all outstanding needs of an input earns input_weight x 0.35 x (needs it resolves / needs outstanding)",
    "quality": "point-in-time (native/event-time 1.0, coarse 0.7, unavailable/unknown 0.45) x history (>=5 seasons 1.0, 3-4 0.85, <3 or unknown 0.6, forward capture only 0.5)",
    "difficulty": "divide by (1 + access_rank)^0.3 from the dataset registry (archived 0, reachable 1, ... blocked 6)",
    "cost": "divide by 1 (free), 1.5 (low cost, <= $50/month), 3 (higher cost) or 4 (price unknown)",
    "not_a_claim": "No weight is a predicted accuracy or profit gain. It orders work by breadth, priority sport and data quality only.",
}
LOW_COST_MONTHLY = 50.0
HELD = {"COLLECTED_ARCHIVE"}
FORWARD_ONLY = {"PROSPECTIVE_CAPTURE_ONLY"}
TIERS = ["FREE", "LOW_COST", "HIGHER_COST", "UNRESOLVED"]
TIER_LABEL = {"FREE": "Free: acquire or reconstruct without a purchase", "LOW_COST": "Low cost: affordable subscription or API",
              "HIGHER_COST": "Higher cost: only if models show promise", "UNRESOLVED": "Unresolved: blocked by rights, access, history or verification"}


def is_held(ds, sources):
    """Held = in an owner archive, or a static bulk release we can re-download reproducibly (free_download source, reachable)."""
    if ds["access_status"] in HELD:
        return True
    return ds["access_status"] == "FREE_REACHABLE" and all((sources.get(s) or {}).get("kind") == "free_download" for s in ds["sources"])


def _csv(p):
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def _years(h):
    try:
        return int(str(h.get("last"))[:4]) - int(str(h.get("first"))[:4]) + 1
    except (TypeError, ValueError):
        return None


def _pit_factor(pit):
    return 1.0 if pit in ("PIT_NATIVE", "EVENT_TIME", "PIT_SAFE") else 0.7 if pit in ("PIT_COARSE",) else 0.45


def _hist_factor(ds):
    if ds["access_status"] in FORWARD_ONLY:
        return 0.5
    y = _years(ds.get("history") or {})
    return 0.6 if y is None or y < 3 else 0.85 if y < 5 else 1.0


def load():
    m = json.load(open(MAP / "map.json"))
    datasets = json.load(open(DF / "datasets.json"))["datasets"]
    sources = json.load(open(DF / "sources.json"))["sources"]
    board = {r["source"]: r for r in json.load(open(OPS / "source_acquisition.json"))["sources"]}
    ledger = json.load(open(OPS / "pipeline_ledger.json"))
    summary = json.load(open(OPS / "summary.json"))
    catalog = json.load(open(CATALOG)) if CATALOG.exists() else {"providers": []}
    return m, datasets, sources, board, ledger, summary, catalog


def provider_index(catalog, datasets):
    by_ds = defaultdict(list)
    for p in catalog["providers"]:
        serves = set(p.get("datasets", []))
        for d, ds in datasets.items():
            if set(ds["sources"]) & set(p.get("source_ids", [])):
                serves.add(d)
        p["_serves"] = sorted(serves)
        for d in serves:
            by_ds[d].append(p)
    return by_ds


def monthly(price):
    if not price:
        return None
    if price.get("monthly_usd") is not None:
        return float(price["monthly_usd"])
    if price.get("annual_usd") is not None:
        return round(float(price["annual_usd"]) / 12, 2)
    return None


def classify(d, ds, provs, board):
    """Cost tier and the blocker that keeps the dataset from being acquired today."""
    access = ds["access_status"]
    terms = [board.get(s, {}).get("terms") or {} for s in ds["sources"]]
    prohibited = [s for s, t in zip(ds["sources"], terms) if (t.get("assessment") or {}).get("internal_noncommercial_research") == "PROHIBITED"]
    paid_label = ds["cost"] == "paid" or access in ("PAID_ONLY", "NO_FREE_SOURCE")
    priced = [p for p in provs if p.get("price", {}).get("status") in ("VERIFIED", "ESTIMATE") and monthly(p["price"]) is not None]
    free_prov = [p for p in provs if p.get("price", {}).get("status") in ("VERIFIED", "ESTIMATE") and monthly(p["price"]) == 0]
    cheapest = min((monthly(p["price"]) for p in priced), default=None)
    blockers = []
    if prohibited:
        blockers.append("RIGHTS: the terms we read prohibit even internal research use (" + ", ".join(prohibited) + ")")
    if access == "FREE_BLOCKED_FROM_RUNNER":
        blockers.append("ACCESS: host blocked from the research environment; needs a network-policy decision or a local run")
    if access == "SAMPLE_ONLY":
        blockers.append("HISTORY: only a sample is public; full history unverified")
    if access == "NO_FREE_SOURCE" and not priced:
        blockers.append("SOURCE: no free source and no verified paid provider")
    if access in FORWARD_ONLY:
        blockers.append("HISTORY: forward capture only; history accumulates from the first collection")
    if access in ("FREE_UNPROBED", "FREE_PATH_UNCONFIRMED"):
        blockers.append("VERIFICATION: free path documented but not yet probed")
    if paid_label and not free_prov:
        if cheapest is None:
            tier = "UNRESOLVED"
            blockers.append("PRICE: paid source with no verified price")
        else:
            tier = "LOW_COST" if cheapest <= LOW_COST_MONTHLY else "HIGHER_COST"
    else:
        tier = "FREE"
    if prohibited or access in ("SAMPLE_ONLY",) or (access == "NO_FREE_SOURCE" and not priced):
        tier = "UNRESOLVED"
    return tier, blockers, cheapest


def build():
    m, datasets, sources, board, ledger, summary, catalog = load()
    prov_by_ds = provider_index(catalog, datasets)
    arche = {a["k"]: a for a in m["archetypes"]}
    medges = _csv(MAP / "market_input_edges.csv")
    dedges = _csv(MAP / "dataset_input_edges.csv")
    inputs_csv = {r["input_key"]: r for r in _csv(MAP / "distinct_inputs.csv")}

    # Missing PRIMARY slots -> distinct inputs with their markets.
    slots = [e for e in medges if e["is_missing_primary_slot"] == "1"]
    miss_markets = defaultdict(set)
    for e in slots:
        miss_markets[e["input_key"]].add(e["sport"] + ":" + e["archetype"])
    core = lambda ak: bool(CORE_RE.search(ak.split(":", 1)[1])) and not NOT_CORE_RE.search(ak.split(":", 1)[1])
    weight = {}
    for i, mk in miss_markets.items():
        s = i.split(":", 1)[0]
        weight[i] = round(TIER_W[SPORT_TIER[s]] * (1 + math.log2(1 + len(mk))) * (1.5 if any(core(a) for a in mk) else 1.0), 4)

    needs = defaultdict(lambda: defaultdict(set))
    alts = defaultdict(set)
    for d in dedges:
        if d["dataset_id"] not in datasets:
            continue
        if d["edge_type"] == "SATISFIED_BY":
            needs[d["input_key"]][d["need"]].add(d["dataset_id"])
        else:
            alts[d["input_key"]].add(d["dataset_id"])

    held = {d for d, ds in datasets.items() if is_held(ds, sources)}

    def outstanding(i, have):
        return {n for n, opts in needs[i].items() if not (opts & have)}

    targets = sorted(miss_markets)
    complete0 = {i for i in targets if needs[i] and not outstanding(i, held)}

    # Per-dataset standalone value (given held data only).
    info = {}
    for d, ds in datasets.items():
        provs = prov_by_ds.get(d, [])
        tier, blockers, cheapest = classify(d, ds, provs, board)
        comp, part, comp_w, part_w = [], [], 0.0, 0.0
        if d not in held:
            for i in targets:
                if i in complete0 or not needs[i]:
                    continue
                out = outstanding(i, held)
                res = {n for n in out if d in needs[i][n]}
                if not res:
                    continue
                if res == out:
                    comp.append(i); comp_w += weight[i]
                else:
                    part.append(i); part_w += weight[i] * 0.35 * len(res) / len(out)
        quality = _pit_factor(ds.get("pit")) * _hist_factor(ds)
        diff = (1 + (ds.get("access_rank") or 0)) ** 0.3
        costf = {"FREE": 1.0, "LOW_COST": 1.5, "HIGHER_COST": 3.0, "UNRESOLVED": 4.0}[tier]
        score = round((comp_w + part_w) * quality / diff / costf, 3)
        # Inputs (missing PRIMARY) this dataset feeds at all, held or not: the breadth figure shown on cards.
        feeds = sorted(i for i in targets if any(d in o for o in needs[i].values()))
        mkts = sorted({a for i in feeds for a in miss_markets[i]})
        paid_alt = min((monthly(p["price"]) for p in provs if p.get("price", {}).get("status") in ("VERIFIED", "ESTIMATE") and (monthly(p["price"]) or 0) > 0), default=None)
        info[d] = dict(dataset=d, title=ds["title"], sports=ds["sports"], tier=tier, blockers=blockers, cheapest_monthly_usd=0.0 if tier == "FREE" else cheapest,
                       paid_alternative_monthly_usd=paid_alt, held_kind=("ARCHIVE" if ds["access_status"] in HELD else "BULK_DOWNLOAD") if d in held else None,
                       access_status=ds["access_status"], held=d in held, cost_label=ds["cost"], pit=ds.get("pit"), freshness=ds.get("freshness"),
                       history=ds.get("history"), history_years=_years(ds.get("history") or {}), missingness=ds.get("missingness"), sources=ds["sources"],
                       tos_risk=ds.get("tos_risk"), rights=sorted({(board.get(s) or {}).get("rights_tiers", ["UNKNOWN"])[0] for s in ds["sources"]}),
                       terms=[{"source": s, **(((board.get(s) or {}).get("terms") or {}).get("assessment") or {})} for s in ds["sources"] if (board.get(s) or {}).get("terms")],
                       reachability=sorted({(board.get(s) or {}).get("reachability", "NOT_PROBED") for s in ds["sources"]}),
                       providers=[p["id"] for p in provs], completes=sorted(comp), advances=sorted(part), feeds_missing_inputs=len(feeds),
                       feeds_by_sport={s: sum(1 for i in feeds if i.startswith(s + ":")) for s in SPORTS if any(i.startswith(s + ":") for i in feeds)},
                       market_families=len(mkts), markets_sample=mkts[:12], score=score, quality=round(quality, 3))

    # Greedy roadmap (set cover inside each tier), so no input is counted twice.
    have = set(held); done = set(complete0); steps = []; cum = {s: 0 for s in SPORTS}
    for i in complete0:
        cum[i.split(":")[0]] += 1
    for tier in ["FREE", "LOW_COST", "HIGHER_COST"]:
        pool = {d for d, x in info.items() if x["tier"] == tier and not x["held"]}
        while pool:
            best, best_v, best_new = None, 0.0, []
            for d in sorted(pool):
                x = info[d]
                new, v = [], 0.0
                for i in targets:
                    if i in done or not needs[i]:
                        continue
                    out = outstanding(i, have)
                    res = {n for n in out if d in needs[i][n]}
                    if not res:
                        continue
                    if res == out:
                        new.append(i); v += weight[i]
                    else:
                        v += weight[i] * 0.35 * len(res) / len(out)
                v = v * x["quality"]
                if v > best_v + 1e-9:
                    best, best_v, best_new = d, v, new
            if best is None or best_v < 0.5:
                break
            pool.discard(best); have.add(best); done |= set(best_new)
            for i in best_new:
                cum[i.split(":")[0]] += 1
            x = info[best]
            steps.append(dict(step=len(steps) + 1, dataset=best, tier=tier, newly_complete=len(best_new),
                              newly_complete_by_sport={s: sum(1 for i in best_new if i.startswith(s + ":")) for s in SPORTS if any(i.startswith(s + ":") for i in best_new)},
                              cumulative_complete=len(done), cumulative_by_sport=dict(cum), monthly_usd=x["cheapest_monthly_usd"] if tier != "FREE" else 0.0,
                              value=round(best_v, 3)))
    cost_run = 0.0
    for s in steps:
        cost_run += s["monthly_usd"] or 0.0
        s["cumulative_monthly_usd"] = round(cost_run, 2)

    # Shortlist: by score within priority; a dataset must feed at least one missing input.
    ranked = sorted((x for x in info.values() if x["feeds_missing_inputs"] and not x["held"]), key=lambda x: (-x["score"], x["dataset"]))
    for r, x in enumerate(ranked, 1):
        x["rank"] = r
        x["next_step"], x["decision"], x["why"] = next_step(x, catalog)
    held_rows = sorted((x for x in info.values() if x["held"] and x["feeds_missing_inputs"]), key=lambda x: -x["feeds_missing_inputs"])
    for x in held_rows:
        x["next_step"], x["decision"], x["why"] = next_step(x, catalog)

    # Per-input detail (every predictive input, compact) + training readiness.
    L = ledger
    dsL = L["datasets"]
    inputs_out = {}
    ready_counts = defaultdict(lambda: defaultdict(int))
    for k, inp in L["inputs"].items():
        if not inp.get("predictive"):
            continue
        s = inp["sport"]
        need_rows = []
        for n, opts in sorted(needs[k].items()):
            opts_sorted = sorted(opts, key=lambda d: (d not in held, info[d]["tier"] != "FREE", -info[d]["score"]))
            need_rows.append([n, bool(opts & held), opts_sorted])
        tr = readiness(inp, needs[k], held, datasets)
        ready_counts[s][tr["state"]] += 1
        out = outstanding(k, held) if needs[k] else set()
        blocker = ("No dataset recorded" if not needs[k] else
                   "Data needed: " + ", ".join(sorted(out)) if out else tr["blocker"])
        inputs_out[k] = dict(l=inp["label"], s=s, w=weight.get(k), mm=sorted(miss_markets.get(k, [])), n=need_rows, alt=sorted(alts.get(k, set())),
                             pit=inp.get("pit"), at=inp["at"], tr=tr, b=blocker)

    sport_rows = {}
    for s in SPORTS:
        miss = [i for i in targets if i.startswith(s + ":")]
        free_steps = [st for st in steps if st["tier"] == "FREE"]
        after_free = free_steps[-1]["cumulative_by_sport"][s] if free_steps else cum[s]
        after_low = max([st["cumulative_by_sport"][s] for st in steps if st["tier"] in ("FREE", "LOW_COST")] or [after_free])
        after_all = max([st["cumulative_by_sport"][s] for st in steps] or [after_low])
        sport_rows[s] = dict(tier=SPORT_TIER[s], missing_primary_inputs=len(miss), missing_primary_slots=sum(1 for e in slots if e["sport"] == s),
                             complete_with_archives=sum(1 for i in complete0 if i.startswith(s + ":")), complete_after_free=after_free,
                             complete_after_low_cost=after_low, complete_after_all_priced=after_all,
                             never_completable_without_unresolved=len(miss) - after_all,
                             top_datasets=[x["dataset"] for x in ranked if s in x["feeds_by_sport"]][:6],
                             readiness=dict(ready_counts[s]), training=sport_training(s, L, datasets, summary, held))

    plan = dict(schema="sift-acquisition-plan/1", status="RESEARCH_ONLY",
                notice=("Buy-versus-build plan joined from the approved catalog, dataset registry, terms readings and a hand-curated provider catalog. "
                        "Prices are shown only where the catalog marks them VERIFIED (read on the provider's own page) or ESTIMATE (with its source); everything else is UNKNOWN. "
                        "Holding data or buying an API does not grant redistribution or commercial rights. Nothing here spends money or starts a collector."),
                weights=WEIGHTS, tiers=TIERS, tier_label=TIER_LABEL, sports_order=SPORTS, sport_tier=SPORT_TIER,
                totals=dict(inputs=len(inputs_csv), archetypes=len(m["archetypes"]), datasets=len(datasets), missing_primary_slots=len(slots),
                            missing_primary_inputs=len(targets), complete_with_archives=len(complete0),
                            complete_after_free=max([st["cumulative_complete"] for st in steps if st["tier"] == "FREE"] or [len(complete0)]),
                            complete_after_low_cost=max([st["cumulative_complete"] for st in steps if st["tier"] in ("FREE", "LOW_COST")] or [len(complete0)]),
                            complete_after_all_priced=max([st["cumulative_complete"] for st in steps] or [len(complete0)]),
                            built_inputs=len(summary.get("built_inputs", [])),
                            training_ready_inputs=sum(v.get("TRAINING_READY", 0) for v in ready_counts.values()),
                            proxy_ready_inputs=sum(v.get("PROXY_READY", 0) for v in ready_counts.values()),
                            predictive_inputs=sum(sum(v.values()) for v in ready_counts.values()),
                            by_tier={t: sum(1 for x in ranked if x["tier"] == t) for t in TIERS}),
                roadmap=steps, shortlist=[slim(x) for x in ranked], held=[slim(x) for x in held_rows],
                providers=[{k: v for k, v in p.items() if not k.startswith("_")} | {"serves": p["_serves"]} for p in catalog["providers"]],
                provider_catalog_checked=catalog.get("checked_utc"), sports=sport_rows,
                readiness_criteria=READINESS_CRITERIA)
    return plan, {"schema": "sift-acquisition-inputs/1", "status": "RESEARCH_ONLY", "inputs": inputs_out,
                  "datasets": {d: {"t": x["title"], "tier": x["tier"], "held": x["held"], "hk": x["held_kind"], "a": x["access_status"], "c": x["cheapest_monthly_usd"],
                                   "h": x["history_years"], "pit": x["pit"], "src": x["sources"], "p": x["providers"]} for d, x in info.items()}}


def slim(x):
    keep = ["dataset", "title", "sports", "tier", "blockers", "cheapest_monthly_usd", "access_status", "held", "cost_label", "pit", "freshness", "history",
            "history_years", "missingness", "sources", "paid_alternative_monthly_usd", "held_kind", "tos_risk", "rights", "terms", "reachability", "providers", "feeds_missing_inputs", "feeds_by_sport",
            "market_families", "markets_sample", "score", "quality", "rank", "next_step", "decision", "why"]
    out = {k: x.get(k) for k in keep}
    out["completes"] = len(x["completes"]); out["advances"] = len(x["advances"])
    out["completes_sample"] = x["completes"][:15]
    return out


def next_step(x, catalog):
    a, t = x["access_status"], x["tier"]
    if x["held"] and x.get("held_kind") == "BULK_DOWNLOAD":
        return ("Download the release into the research cache (no collector needed) and write builders for the inputs it feeds.",
                "None for personal research beyond the recorded licence; keep attribution.",
                f"Static open release; feeds {x['feeds_missing_inputs']} missing PRIMARY inputs at no cost.")
    if x["held"]:
        return ("Write and blind-verify builders for the inputs this archive feeds; record a rights reading before any public output.",
                "Confirm personal-research use of the archived provider data (rights stay UNRESOLVED_INTERNAL_ONLY until read).",
                f"Already in an owner archive; feeds {x['feeds_missing_inputs']} missing PRIMARY inputs at no cost.")
    step = {"FREE_REACHABLE": "Write a call-capped collector (manual run only), backfill history, then the replay and blind-match gates.",
            "FREE_UNPROBED": "Probe the documented free path once (one request), record history depth and fields, then decide on a collector.",
            "FREE_PATH_UNCONFIRMED": "Confirm the free path (one probe) before writing a collector.",
            "FREE_BLOCKED_FROM_RUNNER": "Run the probe from your own machine or allow the host for this environment; then backfill.",
            "PROSPECTIVE_CAPTURE_ONLY": "Design a timestamped forward capture; it cannot be backfilled, so starting date matters.",
            "REFERENCE_DOCUMENT": "Transcribe the reference document into a versioned rules table.",
            "PAID_ONLY": "Compare provider tiers; run any free trial against our identity crosswalk before paying.",
            "NO_FREE_SOURCE": "Price the paid providers; check whether a derived proxy from held data is good enough first.",
            "SAMPLE_ONLY": "Check whether the full history exists anywhere; otherwise treat as forward capture."}.get(a, "Review the dataset record.")
    decision = {"FREE": "Approve a manual, call-capped collection (no schedule) under personal-research use.",
                "LOW_COST": f"Approve or decline a subscription (cheapest priced tier ${x['cheapest_monthly_usd']:.0f}/month equivalent)." if x["cheapest_monthly_usd"] is not None else "Approve or decline a subscription.",
                "HIGHER_COST": "Defer until a challenger shows promise on the markets this dataset feeds.",
                "UNRESOLVED": "Decide whether to pursue: " + ("; ".join(x["blockers"]) or "verification incomplete")}[t]
    why = f"Feeds {x['feeds_missing_inputs']} missing PRIMARY inputs across {x['market_families']} markets; completes {len(x['completes'])} on its own given held data" + \
          (f" and advances {len(x['advances'])} more." if x["advances"] else ".")
    return step, decision, why


READINESS_CRITERIA = [
    ["data", "Raw data held for every data need (in an owner archive)"],
    ["verified", "Archive verified against the requirement (FULL; PARTIAL/PROXY counts as proxy only)"],
    ["built", "Feature code built, replay-gated and blind-matched"],
    ["pit", "Point-in-time safe: knowable before the event from timestamps we hold (no future leakage)"],
    ["history", "At least 3 seasons of history in the held data"],
    ["evaluated", "Used in a chronological (walk-forward) challenger evaluation"],
]


def readiness(inp, needs_i, held, datasets):
    """Training readiness is separate from availability: code that runs is not enough, and archived data is not enough."""
    ch = inp["chain"]
    held_ds = [d for opts in needs_i.values() for d in opts if d in held]
    years = max([_years(datasets[d].get("history") or {}) or 0 for d in held_ds] or [0])
    c = {"data": "OK" if needs_i and all(o & held for o in needs_i.values()) else ("PARTIAL" if held_ds else "MISSING"),
         "verified": ch[3] if len(ch) > 3 else "MISSING", "built": ch[4] if len(ch) > 4 else "MISSING",
         "pit": "OK" if inp.get("pit") in ("PIT_SAFE", "NOT_APPLICABLE") else "PARTIAL" if inp.get("pit") == "PIT_COARSE" else "FAILED",
         "history": "OK" if years >= 3 else "PARTIAL" if years else "MISSING", "evaluated": ch[6] if len(ch) > 6 else "MISSING"}
    core = ["data", "verified", "built", "pit", "history"]
    if all(c[k] == "OK" for k in core):
        state = "TRAINING_READY"
    elif all(c[k] in ("OK", "PARTIAL") for k in core) and c["built"] in ("OK", "PARTIAL"):
        state = "PROXY_READY"
    elif c["built"] in ("OK", "PARTIAL"):
        state = "BUILT_NOT_READY"
    elif c["data"] == "OK":
        state = "DATA_HELD_NOT_BUILT"
    else:
        state = "DATA_MISSING"
    first_bad = next((k for k in core if c[k] not in ("OK",)), None)
    blocker = {None: "None of the core checks fail; next is a chronological evaluation." if c["evaluated"] != "OK" else "Ready.",
               "data": "Raw data not held for every need", "verified": "Archive not verified FULL against the requirement",
               "built": "Feature not built and blind-matched", "pit": f"Point-in-time not safe ({inp.get('pit')})",
               "history": "Less than 3 seasons of held history"}[first_bad]
    return {"state": state, "c": c, "blocker": blocker}


def sport_training(s, L, datasets, summary, held):
    """Sport-level reliable-training-dataset checklist from recorded evidence only."""
    ds_s = {d: x for d, x in datasets.items() if s in x["sports"]}
    held_s = [d for d in ds_s if d in held]
    years = {d: _years(ds_s[d].get("history") or {}) for d in held_s}
    outcome_ds = [d for d in held_s if re.search(r"(game|result|match|team_games|scores|box|player_games)", d)]
    challengers = [c for c in L["challengers"].values() if c.get("sport") == s]
    built = [b for b in summary.get("built_inputs", []) if b["sport"] == s]
    inputs = [i for i in L["inputs"].values() if i["sport"] == s and i.get("predictive")]
    leaky = sum(1 for i in inputs if i.get("pit") in ("PIT_LEAKY_FINAL_ONLY", "NOT_PREGAME_KNOWABLE"))
    unavailable = sum(1 for i in inputs if i.get("pit") == "PIT_UNAVAILABLE_HISTORICALLY")
    crosswalk = [d for d in ds_s if re.search(r"(crosswalk|register|id_map|identity|people)", d + " " + ds_s[d]["title"].lower())]
    fwd = [d for d in ds_s if ds_s[d]["access_status"] in FORWARD_ONLY]
    fwd_held = [d for d in fwd if d in held]
    maxy = max([y or 0 for y in years.values()] or [0])
    checks = [
        ["Historical outcomes held (game and player results)", "OK" if outcome_ds else "MISSING",
         (", ".join(f"{d} ({years.get(d) or '?'} seasons)" for d in outcome_ds) or "no results dataset in an owner archive")],
        ["Sample size: seasons of held history", "OK" if maxy >= 5 else "PARTIAL" if maxy >= 3 else "MISSING", f"longest held history {maxy or 'unknown'} seasons"],
        ["Correct timestamps / no future leakage", "OK" if not leaky else "PARTIAL",
         f"{leaky} predictive inputs are final-only or not knowable pre-event; {unavailable} have no point-in-time history"],
        ["Team/player identity consistency", "OK" if crosswalk and any(d in held for d in crosswalk) else "PARTIAL" if crosswalk else "MISSING",
         ("crosswalk datasets: " + ", ".join(crosswalk)) if crosswalk else "no identity crosswalk dataset recorded; joins rely on provider IDs"],
        ["Reproducible feature generation (replay + blind match)", "OK" if built else "MISSING", f"{len(built)} inputs built with replay gate and blind match"],
        ["Chronological train/validation/test splits", "OK" if challengers else "MISSING", f"{len(challengers)} walk-forward challenger evaluations committed"],
        ["Missingness and data-quality checks", "OK" if any(f.get("checks_total") for c in challengers for f in c.get("features", [])) else "MISSING",
         f"{sum(f.get('checks_passed', 0) for c in challengers for f in c.get('features', []))} feature checks passed across challengers"],
        ["Feature availability at real prediction time (forward capture)", "OK" if fwd and len(fwd_held) == len(fwd) else "PARTIAL" if fwd_held else "MISSING",
         f"{len(fwd_held)} of {len(fwd)} forward-capture datasets held"],
    ]
    score = sum(1 for c in checks if c[1] == "OK") + 0.5 * sum(1 for c in checks if c[1] == "PARTIAL")
    blockers = [c[0] + ": " + c[2] for c in checks if c[1] != "OK"]
    return {"checks": checks, "score": score, "of": len(checks), "blockers": blockers}


def main():
    plan, inputs = build()
    write_json(OPS / "acquisition_plan.json", plan)
    write_json(OPS / "acquisition_inputs.json", inputs)
    (ROOT / "docs/DATA_ACQUISITION_ROADMAP.md").write_text(roadmap_md(json.loads((OPS / "acquisition_plan.json").read_text())))
    t = plan["totals"]
    print(json.dumps(t, indent=1))



def roadmap_md(plan):
    """Human-readable roadmap regenerated with the JSON, so the document never drifts from the data."""
    T, S = plan["totals"], plan["sports"]
    money = lambda m: "free" if m == 0 else ("unknown" if m is None else f"${m:,.2f}/mo")
    def top(group, n=6):
        sp = {"P0": ["NBA", "CBB", "NHL"], "P1": ["NFL", "CFB"], "P2": ["MLB", "SOCCER", "TENNIS"]}.get(group, [group])
        rows = []
        for r in plan["shortlist"]:
            tot = sum(r["feeds_by_sport"].values()) or 1
            share = sum(r["feeds_by_sport"].get(s, 0) for s in sp) / tot
            if share:
                rows.append((r["score"] * share, r))
        return [r for _, r in sorted(rows, key=lambda x: -x[0])[:n]]
    L = ["# SIFT Alpha data acquisition roadmap (generated)", "",
         "_Generated by `python -m alpha_engine.foundation.acquisition` from the approved catalog, dataset registry, terms readings and "
         f"`research/provider_licensing/provider_catalog.json` (prices checked {plan.get('provider_catalog_checked')}). RESEARCH ONLY: nothing here spends money or starts a collector._", "",
         "## Verified counts", "",
         f"* {T['inputs']:,} distinct candidate inputs · {T['archetypes']} market archetypes · {T['datasets']} datasets · 8 sports",
         f"* {T['missing_primary_slots']} missing PRIMARY slots = **{T['missing_primary_inputs']} distinct inputs** (an input missing in several markets counts once)",
         f"* {T['built_inputs']} archive-built partial/proxy inputs · **{T['training_ready_inputs']} training-ready** and {T['proxy_ready_inputs']} proxy-ready of {T['predictive_inputs']:,} predictive inputs", "",
         "## How much the plan unlocks (distinct missing PRIMARY inputs with every raw dataset)", "",
         "| Sport | Tier | Missing inputs | Held now | After free plan | After low cost | After every priced option | Still unresolved |", "|---|---|---|---|---|---|---|---|"]
    for s in plan["sports_order"]:
        d = S[s]
        L.append(f"| {s} | {d['tier']} | {d['missing_primary_inputs']} | {d['complete_with_archives']} | {d['complete_after_free']} | {d['complete_after_low_cost']} | {d['complete_after_all_priced']} | {d['never_completable_without_unresolved']} |")
    L += [f"| **All** | | **{T['missing_primary_inputs']}** | **{T['complete_with_archives']}** | **{T['complete_after_free']}** | **{T['complete_after_low_cost']}** | **{T['complete_after_all_priced']}** | **{T['missing_primary_inputs'] - T['complete_after_all_priced']}** |", "",
          "\"Held\" means an owner archive or an open bulk release. Having raw data is availability, not training readiness, and not permission: rights stay as recorded.", ""]
    for g in ["P0", "P1", "P2"]:
        L += [f"## Top datasets for {g}", "", "| Dataset | Tier | Cost | Completes / advances | Feeds | Blocker | Next step |", "|---|---|---|---|---|---|---|"]
        for r in top(g):
            L.append(f"| `{r['dataset']}` {r['title'][:60]} | {r['tier']} | {money(r['cheapest_monthly_usd'])}{' (paid option ' + money(r['paid_alternative_monthly_usd']) + ')' if r['tier'] == 'FREE' and r['paid_alternative_monthly_usd'] else ''} | "
                     f"{r['completes']} / {r['advances']} | {', '.join(f'{k} {v}' for k, v in r['feeds_by_sport'].items())} | {(r['blockers'] or ['none'])[0]} | {r['next_step']} |")
        L.append("")
    L += ["## Paid and unresolved datasets", "", "| Dataset | Tier | Planning cost | Providers | Blockers |", "|---|---|---|---|---|"]
    for r in plan["shortlist"]:
        if r["tier"] != "FREE":
            L.append(f"| `{r['dataset']}` | {r['tier']} | {money(r['cheapest_monthly_usd'])} | {', '.join(r['providers']) or '—'} | {'; '.join(r['blockers']) or '—'} |")
    L += ["", "## Providers and prices", "", "Status: VERIFIED = read on the provider's own page during the check; ESTIMATE = search snippet or third party (see evidence in the catalog); UNKNOWN = not found.", "",
          "| Provider | Planning tier | Monthly | Annual | Status | Redistribution | Commercial licence needed | Link |", "|---|---|---|---|---|---|---|---|"]
    for p in plan["providers"]:
        pr = p["price"]
        L.append(f"| {p['name']} | {pr.get('tier')} | {pr.get('monthly_usd') if pr.get('monthly_usd') is not None else '—'} | {pr.get('annual_usd') if pr.get('annual_usd') is not None else '—'} | {pr.get('status')} | {p.get('redistribution')} | {p.get('commercial_license_needed')} | {p.get('url') or '—'} |")
    L += ["", "## Training readiness by sport", "", "| Sport | Dataset checks passed | Training-ready inputs | Proxy-ready | Main blockers |", "|---|---|---|---|---|"]
    for s in plan["sports_order"]:
        d = S[s]
        L.append(f"| {s} | {d['training']['score']} / {d['training']['of']} | {d['readiness'].get('TRAINING_READY', 0)} | {d['readiness'].get('PROXY_READY', 0)} | {' · '.join(d['training']['blockers'][:2])} |")
    L += ["", "## Ranking method (estimate)", ""] + [f"* **{k}**: {v}" for k, v in plan["weights"].items()] + [""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
