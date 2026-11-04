#!/usr/bin/env python3
"""CBB (men's college basketball) market-first evidence audit + incremental-prediction test (RESEARCH_ONLY; never trades).

Inputs (public archives of chmoses98/cbb-edge-finder, checked out under --data):
  cbb_kalshi-panel-archive (panels: as-of-capture Kalshi quotes + frozen projection probabilities), cbb_kalshi-archive (raw quotes, cross-check),
  cbb_projections-archive (frozen projection records), cbb_schedule-archive (ESPN final scores), cbb_period-scores-archive (halves / OT),
  cbb_market-research (derived universe, used for family inventory only).
usage: python3 -I research/outcome_intel/cbb_audit.py --data /home/user/data --out reports/outcome_intel/cbb_audit.json [--cache file.pkl]
"""
from __future__ import annotations
import argparse, collections, glob, gzip, json, os, pickle, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import cbb_common as C
import incremental as I

FAMS_GAME = ("GAME_WINNER", "SPREAD", "TOTAL", "HALF", "TEAM_TOTAL", "OTHER")
VERSIONS = ("pure-0.2.0", "pure-0.3.0", "pure-0.4.0", "pure-0.5.0", "pure-0.5.0+roster")
PRIMARY_VERSION = "pure-0.2.0"          # incumbent / production SIFT model; the rest are shadow challengers
HORIZONS = {"H24": (24.0, 30.0), "H6": (6.0, 7.5), "H1": (1.0, 2.0), "CLOSE": (0.0, 1.0)}   # [min,max] hours before tip of the quote used
MAX_SPREAD = 0.10


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def head_sha(d):
    try:
        return subprocess.check_output(["git", "-C", d, "rev-parse", "FETCH_HEAD"], text=True).strip()
    except Exception:
        return None


# ----------------------------------------------------------------------------------------------- loading
def load_panels(root):
    rows, files = [], {}
    for fp in sorted(glob.glob(os.path.join(root, "panels/*/*/*/*.panel.jsonl.gz"))):
        files[os.path.relpath(fp, root)] = C.sha256_file(fp)
        with gzip.open(fp, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                if r["family"] not in FAMS_GAME:
                    continue
                s = r.get("contract_semantics") or {}
                mo = r.get("models_as_of_capture") or {}
                probs = r.get("market_specific_model_probability") or {}
                vers = mo.get("versions") or {}
                rows.append(dict(
                    tk=r["kalshi_ticker"], ev=r["kalshi_event_ticker"], fam=r["family"], mt=s.get("market_type"), per=s.get("period"),
                    dirn=s.get("direction"), strike=s.get("strike"), side=s.get("subject_side"), sstat=s.get("status"), gap=s.get("model_gap"),
                    gid=r.get("espn_game_id"), start=r.get("game_start_utc"), cap=r["captured_at"], phase=r["market_phase"], status=r["status"],
                    res=r["result"], yb=f(r["yes_bid_dollars"]), ya=f(r["yes_ask_dollars"]), nb=f(r["no_bid_dollars"]), na=f(r["no_ask_dollars"]),
                    ybs=f(r["yes_bid_size_fp"]), yas=f(r["yes_ask_size_fp"]), vol=f(r["volume_fp"]), mstate=mo.get("state"),
                    q={k: (v or {}).get("probability") for k, v in probs.items()},
                    asof={k: v.get("as_of") for k, v in vers.items()},
                    mu={k: (v.get("margin"), v.get("margin_sd"), v.get("total"), v.get("total_sd")) for k, v in vers.items()},
                    sha={k: v.get("sha256") for k, v in vers.items()}, mapping=r.get("mapping_reason")))
    return rows, files


def load_schedule(root):
    """ESPN schedule rows -> per-game final scores (conflicts flagged) and latest start time."""
    fin, starts, status_seen = collections.defaultdict(set), {}, collections.defaultdict(set)
    nrows, files = 0, {}
    for fp in sorted(glob.glob(os.path.join(root, "rows/*/*/*/*.jsonl"))):
        files[os.path.relpath(fp, root)] = C.sha256_file(fp)
        for line in open(fp):
            r = json.loads(line)
            nrows += 1
            g = int(r["game_id"])
            status_seen[g].add(r.get("status_type_name"))
            if r.get("status_type_completed") and r.get("status_type_name") == "STATUS_FINAL" and r.get("home_score") is not None:
                fin[g].add((int(r["home_score"]), int(r["away_score"])))
            starts.setdefault(g, []).append((r["observed_at"], r.get("start_date")))
    return dict(final=fin, starts=starts, status=status_seen, n_rows=nrows), files


def load_periods(root):
    out, files = {}, {}
    for fp in sorted(glob.glob(os.path.join(root, "periods/*/*/*/*"))):
        if not os.path.isfile(fp):
            continue
        files[os.path.relpath(fp, root)] = C.sha256_file(fp)
        for line in open(fp):
            r = json.loads(line)
            if r.get("completed") and r.get("verified"):
                out.setdefault(int(r["espn_game_id"]), []).append(r)
    return out, files


# ----------------------------------------------------------------------------------------------- settlement re-derivation
def derive_y(row, final, per):
    """Independent outcome from final score / period scores using only the parsed contract semantics. None if not derivable."""
    mt, p, side, k, d = row["mt"], row["per"], row["side"], row["strike"], row["dirn"]
    if final is None:
        return None
    H, A = final
    if p == "FULL":
        h, a = H, A
    elif p in ("1H", "2H") and per:
        h1, a1 = per["first_half_home"], per["first_half_away"]
        if p == "1H":
            h, a = h1, a1
        else:
            # Kalshi 2H markets include overtime (panel semantics overtime='included'): 2H = final - first half
            h, a = per["final_home"] - h1, per["final_away"] - a1
    else:
        return None
    if mt == "WINNER":
        if h == a:
            return None
        return int((h > a) if side == "home" else (a > h))
    if mt == "MARGIN":
        m = (h - a) if side == "home" else (a - h)
        return int(m > k) if d == "greater" else None
    if mt == "TOTAL":
        return int((h + a) > k) if d == "greater" else None
    if mt == "TEAM_TOTAL":
        return int((h if side == "home" else a) > k) if d == "greater" else None
    return None


def kalshi_y(res):
    return {"yes": 1, "no": 0}.get(res)


# ----------------------------------------------------------------------------------------------- build
def build(args):
    P = lambda n: os.path.join(args.data, n)
    if args.cache and os.path.exists(args.cache):
        rows, pfiles = pickle.load(open(args.cache, "rb"))
    else:
        rows, pfiles = load_panels(P("cbb_kalshi-panel-archive"))
        if args.cache:
            pickle.dump((rows, pfiles), open(args.cache, "wb"))
    sched, sfiles = load_schedule(P("cbb_schedule-archive"))
    pers, perfiles = load_periods(P("cbb_period-scores-archive"))
    return rows, pfiles, sched, sfiles, pers, perfiles


def settlement_table(rows, sched, pers):
    """Per ticker: Kalshi result(s), derived result, agreement."""
    res_by_tk = collections.defaultdict(set)
    meta = {}
    for r in rows:
        if r["res"]:
            res_by_tk[r["tk"]].add(r["res"])
        meta.setdefault(r["tk"], r)
    out = {}
    for tk, m in meta.items():
        rs = res_by_tk.get(tk, set())
        gid = m["gid"]
        fs = sched["final"].get(gid, set()) if gid else set()
        final = next(iter(fs)) if len(fs) == 1 else None
        pl = pers.get(gid, [])
        per = pl[-1] if pl else None
        yd = derive_y(m, final, per) if gid else None
        out[tk] = dict(results=sorted(rs), y_kalshi=kalshi_y(next(iter(rs))) if len(rs) == 1 else None, y_derived=yd, conflicting_final=len(fs) > 1,
                       has_final=final is not None, has_period=per is not None, fam=m["fam"], mt=m["mt"], per=m["per"], gid=gid)
    return out


def recompute_model_prob(r, ver):
    """Independent recomputation of the market-specific model probability from the frozen margin/total + sd (normal approximation)."""
    mu = r["mu"].get(ver)
    if not mu or r["sstat"] != "parsed":
        return None
    margin, msd, total, tsd = mu
    if r["mt"] == "MARGIN" and r["per"] == "FULL" and margin is not None:
        m = margin if r["side"] == "home" else -margin
        return C.phi((m - r["strike"]) / msd)
    if r["mt"] == "TOTAL" and r["per"] == "FULL" and total is not None:
        return C.phi((total - r["strike"]) / tsd)
    return None


def pick_quotes(rows):
    """Per (ticker, horizon): the latest pre-tip capture inside the horizon window with a valid two-sided quote. Returns list of candidate dicts + counters."""
    by_tk = collections.defaultdict(list)
    for r in rows:
        by_tk[r["tk"]].append(r)
    cnt = collections.Counter()
    picked = []
    for tk, lst in by_tk.items():
        lst.sort(key=lambda r: r["cap"])
        for r in lst:
            if not r["start"] or not r["gid"]:
                cnt["no_game_mapping_row"] += 1
        for hname, (lo, hi) in HORIZONS.items():
            best = None
            for r in lst:
                if not r["start"]:
                    continue
                hrs = (C.pdt(r["start"]) - C.pdt(r["cap"])).total_seconds() / 3600.0
                if lo <= hrs <= hi:
                    best = (r, hrs)       # latest in window (list sorted ascending by capture time)
            if best is None:
                cnt["no_capture_in_window:" + hname] += 1
                continue
            r, hrs = best
            if r["yb"] is None or r["ya"] is None or not (0.0 < r["yb"] < r["ya"] < 1.0) or r["ya"] - r["yb"] > MAX_SPREAD + 1e-9:
                cnt["invalid_or_wide_quote:" + hname] += 1
                continue
            picked.append(dict(r, h=hname, hrs=hrs))
    return picked, cnt


def projection_audit(root):
    """Check the frozen projection archive itself: as_of <= tip, file stamp == as_of, no overwritten duplicates."""
    n = viol = stamp_bad = 0
    lead, seen = [], collections.Counter()
    shas = {}
    for fp in glob.glob(os.path.join(root, "projections/**/*.json"), recursive=True):
        if "/manifests/" in fp or "/schedule_" in fp:
            continue
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        if "prospective" not in d or "game" not in d:
            continue
        n += 1
        asof, tip = C.pdt(d["prospective"]["as_of"]), C.pdt(d["game"]["start_time_utc"])
        shas[fp.split("/projections/")[1]] = C.sha256_file(fp)
        seen[(d["model"]["version"], d["game"]["game_id"], d["prospective"]["as_of"])] += 1
        if asof > tip:
            viol += 1
        lead.append((tip - asof).total_seconds() / 3600)
        stamp = os.path.basename(fp).replace(".json", "")
        if stamp.replace("T", " ")[:10] != d["prospective"]["as_of"][:10]:
            stamp_bad += 1
    return dict(records=n, as_of_after_tip=viol, filename_date_mismatch=stamp_bad, duplicate_keys=sum(1 for v in seen.values() if v > 1),
                lead_hours=dict(min=float(np.min(lead)), median=float(np.median(lead)), max=float(np.max(lead))) if lead else None), shas


def raw_crosscheck(rows, raw_root, n_files=3):
    """Compare panel quotes with the raw Kalshi snapshot for a few capture times (panel must be a faithful join)."""
    caps = sorted({r["cap"] for r in rows})
    sel = [caps[len(caps) // 4], caps[len(caps) // 2], caps[-1]][:n_files]
    mism = chk = 0
    for cap in sel:
        stamp = cap[:19].replace("-", "").replace(":", "").replace("T", "T") + "Z"
        fp = glob.glob(os.path.join(raw_root, "snapshots/*/*/*/kalshi_cbb_%s.jsonl.gz" % stamp))
        if not fp:
            continue
        raw = {}
        with gzip.open(fp[0], "rt") as fh:
            for line in fh:
                m = json.loads(line)["market"]
                raw[m["ticker"]] = (f(m["yes_bid_dollars"]), f(m["yes_ask_dollars"]), m.get("result"))
        for r in rows:
            if r["cap"] == cap and r["tk"] in raw:
                chk += 1
                if (raw[r["tk"]][0], raw[r["tk"]][1]) != (r["yb"], r["ya"]):
                    mism += 1
    return dict(captures_checked=sel, quotes_checked=chk, mismatches=mism)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/home/user/data")
    ap.add_argument("--out", default="reports/outcome_intel/cbb_audit.json")
    ap.add_argument("--cache", default=None)
    a = ap.parse_args()
    rows, pfiles, sched, sfiles, pers, perfiles = build(a)
    P = lambda n: os.path.join(a.data, n)
    sett = settlement_table(rows, sched, pers)
    proj, pshas = projection_audit(P("cbb_projections-archive"))
    xchk = raw_crosscheck(rows, P("cbb_kalshi-archive"))

    # ---- panel-level integrity
    integ = dict(panel_rows_game_families=len(rows), panel_files=len(pfiles), tickers=len(sett),
                 duplicate_ticker_capture_rows=len(rows) - len({(r["tk"], r["cap"]) for r in rows}),
                 yes_no_book_inconsistent=sum(1 for r in rows if r["yb"] is not None and r["na"] is not None and abs((1 - r["yb"]) - r["na"]) > 0.0051),
                 phase_vs_tip_mismatch=sum(1 for r in rows if r["start"] and ((C.pdt(r["cap"]) < C.pdt(r["start"])) != (r["phase"] == "PRETIP"))),
                 model_asof_after_capture=sum(1 for r in rows for v in r["asof"].values() if v and C.pdt(v) > C.pdt(r["cap"])),
                 model_asof_after_tip_on_pretip_rows=sum(1 for r in rows if r["phase"] == "PRETIP" and r["start"] for v in r["asof"].values() if v and C.pdt(v) > C.pdt(r["start"])),
                 conflicting_kalshi_results=sum(1 for s in sett.values() if len(s["results"]) > 1),
                 conflicting_espn_finals=sum(1 for g, s in sched["final"].items() if len(s) > 1),
                 raw_vs_panel=xchk, projection_archive=proj)
    # tip-time agreement: panel game_start vs latest ESPN start_date observed
    tipmis = tipchk = 0
    gtip = {}
    for r in rows:
        if r["gid"] and r["start"]:
            gtip.setdefault(r["gid"], set()).add(r["start"])
    integ["games_with_multiple_tip_times_in_panel"] = sum(1 for v in gtip.values() if len(v) > 1)
    for g, v in gtip.items():
        st = sched["starts"].get(g)
        if st:
            tipchk += 1
            es = C.pdt(sorted(st)[-1][1]); ps = C.pdt(sorted(v)[-1])
            tipmis += abs((es - ps).total_seconds()) > 600
    integ["panel_tip_vs_espn_start"] = dict(games_checked=tipchk, differing_gt_10min=int(tipmis))

    # ---- settlement coverage per family bucket (game-linked tickers)
    def bucket(m):
        return m["fam"] if m["fam"] in ("GAME_WINNER", "SPREAD", "TOTAL", "TEAM_TOTAL") else "HALF:%s:%s" % (m["mt"], m["per"]) if m["fam"] == "HALF" else "OTHER:%s" % m["mt"]
    sb = collections.defaultdict(collections.Counter)
    for tk, s in sett.items():
        b = bucket(s)
        sb[b]["tickers"] += 1
        if s["gid"] is None:
            sb[b]["unmapped_no_game"] += 1
        if s["y_kalshi"] is not None:
            sb[b]["kalshi_settled_yes_no"] += 1
        if s["results"] and s["y_kalshi"] is None:
            sb[b]["kalshi_nonbinary_or_void:" + ",".join(s["results"])] += 1
        if s["y_derived"] is not None:
            sb[b]["independently_derived"] += 1
        if s["y_kalshi"] is not None and s["y_derived"] is not None:
            sb[b]["both"] += 1
            sb[b]["agree"] += int(s["y_kalshi"] == s["y_derived"])
            sb[b]["disagree"] += int(s["y_kalshi"] != s["y_derived"])
        if s["conflicting_final"]:
            sb[b]["conflicting_espn_final"] += 1
    # ---- quotes and cells
    pre = [r for r in rows if r["phase"] == "PRETIP" and r["gid"] and r["start"]]
    picked, pcnt = pick_quotes(pre)
    pos_games = {}  # model-probability integrity
    chk = [(r, v) for r in pre for v in VERSIONS if r["q"].get(v) is not None and recompute_model_prob(r, v) is not None]
    diffs = [abs(r["q"][v] - recompute_model_prob(r, v)) for r, v in chk[:200000]]
    integ["model_prob_recompute"] = dict(checked=len(diffs), max_abs_diff=float(max(diffs)) if diffs else None, gt_1e3=int(sum(d > 1e-3 for d in diffs)))

    # rows for tests
    def mk(r, ver, bad):
        s = sett[r["tk"]]
        if s["y_kalshi"] is None:
            bad["no_kalshi_binary_settlement"] += 1
            return None
        if s["y_derived"] is not None and s["y_derived"] != s["y_kalshi"]:
            bad["kalshi_vs_derived_disagree"] += 1
            return None
        if s["y_derived"] is None and r["fam"] in ("GAME_WINNER", "SPREAD", "TOTAL"):
            bad["no_independent_derivation(kept_on_kalshi_only)"] += 1
        q = r["q"].get(ver) if ver else None
        if ver and q is None:
            bad["no_model_prob"] += 1
            return None
        if ver:
            if not r["asof"].get(ver) or C.pdt(r["asof"][ver]) > C.pdt(r["cap"]) or C.pdt(r["asof"][ver]) > C.pdt(r["start"]):
                bad["model_asof_not_before_capture"] += 1
                return None
        return dict(game=r["gid"], t=C.pdt(r["start"]).isoformat(), mid=(r["yb"] + r["ya"]) / 2, q=q, y=s["y_kalshi"], tk=r["tk"], hrs=r["hrs"],
                    lag=((C.pdt(r["cap"]) - C.pdt(r["asof"][ver])).total_seconds() / 3600 if ver and r["asof"].get(ver) else None))

    cells_meta, cell_rows = {}, {}
    bad_all = {}
    for fam in ("GAME_WINNER", "SPREAD", "TOTAL"):
        for h in HORIZONS:
            for ver in (None,) + VERSIONS:
                bad = collections.Counter()
                sel = [r for r in picked if r["fam"] == fam and r["h"] == h and (r["mt"] is not None) and r["sstat"] == "parsed"]
                if fam == "GAME_WINNER":
                    sel = [r for r in sel if r["side"] == "home"]     # the two sides of one game are exact complements: keep one (home) to avoid duplicate rows
                rr = [x for x in (mk(r, ver, bad) for r in sel) if x is not None]
                # dedupe (ticker,horizon) guaranteed by pick_quotes; assert
                assert len({x["tk"] for x in rr}) == len(rr)
                cell_rows[(fam, h, ver)] = rr
                bad_all[(fam, h, ver)] = dict(bad, candidates=len(sel))
    # Holm over every challenger cell tried
    chal = {}
    for (fam, h, ver), rr in cell_rows.items():
        if ver is None:
            continue
        chal["%s|%s|%s" % (fam, h, ver)] = C.run_challenger(rr)
    holm_all = C.holm_over(chal)
    prim = {k: v for k, v in chal.items() if k.endswith("|" + PRIMARY_VERSION)}
    holm_prim = C.holm_over(prim)

    cells = []
    for fam in ("GAME_WINNER", "SPREAD", "TOTAL"):
        for h in HORIZONS:
            base_rows = cell_rows[(fam, h, None)]
            for ver in VERSIONS:
                key = "%s|%s|%s" % (fam, h, ver)
                rr = cell_rows[(fam, h, ver)]
                c = chal[key]
                st, why = C.classify(c, holm_all.get(key))
                gb = C.gain_block(c, holm_all.get(key))
                gb["holm_p_primary_family_only"] = holm_prim.get(key)
                cells.append(dict(
                    sport="CBB", family=fam, horizon=h, challenger=ver, is_primary_challenger=(ver == PRIMARY_VERSION),
                    inputs_available=dict(kalshi_quote=True, frozen_projection=True, projection_available_time="established: record as_of precedes tip (checked row-wise)",
                                          espn_dk_line="partial (espn-lines-archive, sparse); not used in this cell", roster_availability="availability-archive exists, not joined"),
                    n_games=len({x["game"] for x in rr}), n_contracts=len(rr),
                    price_coverage=dict(candidates=bad_all[(fam, h, ver)]["candidates"], window_hours=list(HORIZONS[h]), max_quote_spread=MAX_SPREAD,
                                        exclusions={k: v for k, v in bad_all[(fam, h, ver)].items() if k != "candidates"}),
                    settlement_source="Kalshi result (official, in raw snapshots) cross-checked against ESPN final score re-derived from contract semantics",
                    market_metrics=C.market_only(rr), model_metrics=C.model_metrics(rr),
                    lag_hours_model_asof_to_capture=(dict(median=float(np.median([x["lag"] for x in rr])), max=float(np.max([x["lag"] for x in rr]))) if rr else None),
                    calibration_bins=C.calibration_bins(rr),
                    challenger_detail={k: v for k, v in c.items() if k in ("status", "train_games", "holdout_games", "n_train", "n_holdout", "logloss", "brier", "coef_challenger",
                                                                          "negative_control_gain", "positive_control_gain", "calibration_gain_of_market_alone_logloss", "gain_vs_raw_market_logloss")},
                    incremental_gain=gb, status=st, reason=why))
    # no-model cells (market-only)
    nomodel = []
    groups = collections.defaultdict(list)
    for r in picked:
        if r["fam"] in ("HALF", "TEAM_TOTAL") or (r["fam"] == "OTHER" and r["mt"] in ("OVERTIME", "RACE")):
            groups[(r["fam"] + ":" + str(r["mt"]) + ":" + str(r["per"]), r["h"])].append(r)
    for (g, h), lst in sorted(groups.items()):
        bad = collections.Counter()
        rr = [x for x in (mk(r, None, bad) for r in lst) if x is not None]
        gaps = collections.Counter(r["gap"] for r in lst)
        derived = sum(1 for r in lst if sett[r["tk"]]["y_derived"] is not None)
        nomodel.append(dict(
            sport="CBB", family=g, horizon=h, inputs_available=dict(kalshi_quote=True, frozen_projection=False), n_games=len({x["game"] for x in rr}), n_contracts=len(rr),
            price_coverage=dict(candidates=len(lst), exclusions=dict(bad)), settlement_source="Kalshi result; independent derivation available for %d of %d candidates (period-scores-archive)" % (derived, len(lst)),
            market_metrics=C.market_only(rr), model_metrics=None, incremental_gain=dict(mean=None, lo=None, hi=None, holm_p=None),
            status="MISSING_DATA", reason="no SIFT model probability for this market: %s. Repair: frozen model has no half / team-score / overtime / race distribution; add one and archive it pregame" % dict(gaps)))
    # inventory of non-game families from the derived universe
    inv = collections.Counter()
    try:
        for line in gzip.open(os.path.join(P("cbb_market-research"), "latest/universe.jsonl.gz"), "rt"):
            u = json.loads(line)
            inv[(u["family"], u["status"]["outcome"])] += 1
    except Exception as e:
        inv["error:" + str(e)] += 1

    report = dict(
        schema="sift-outcome-intel-sport-audit/1", status="RESEARCH_ONLY", sport="CBB",
        protocol=dict(split="chronological by tip time: earliest 2/3 games train, latest 1/3 holdout", ridge=1.0, statistic="holdout logloss gain over train-calibrated market (positive = challenger better)",
                      ci="game-cluster bootstrap 2000", multiplicity="Holm over all %d challenger cells tried (3 families x 4 horizons x 5 model versions); primary-family-only Holm also reported" % len(chal),
                      horizons=HORIZONS, quote="mid of yes bid/ask of the last pre-tip capture in window; two-sided; spread<=0.10", dedup="one row per (ticker,horizon); GAME_WINNER keeps only the home contract",
                      primary_challenger=PRIMARY_VERSION, status_rule="see cbb_common.classify"),
        provenance=dict(repo="chmoses98/cbb-edge-finder", branch_heads={d: head_sha(P(d)) for d in ("cbb_kalshi-panel-archive", "cbb_kalshi-archive", "cbb_projections-archive", "cbb_schedule-archive", "cbb_period-scores-archive", "cbb_market-research", "cbb_espn-lines-archive")},
                        input_sha256_digest={"panel_files": C.hashlib.sha256("\n".join("%s %s" % kv for kv in sorted(pfiles.items())).encode()).hexdigest(), "n_panel_files": len(pfiles),
                                             "schedule_rows": C.hashlib.sha256("\n".join("%s %s" % kv for kv in sorted(sfiles.items())).encode()).hexdigest(), "n_schedule_files": len(sfiles),
                                             "period_scores": C.hashlib.sha256("\n".join("%s %s" % kv for kv in sorted(perfiles.items())).encode()).hexdigest(), "n_period_files": len(perfiles),
                                             "projection_records": C.hashlib.sha256("\n".join("%s %s" % kv for kv in sorted(pshas.items())).encode()).hexdigest(), "n_projection_files": len(pshas)},
                        first_panel_capture=min(r["cap"] for r in rows), last_panel_capture=max(r["cap"] for r in rows)),
        integrity=integ,
        settlement_coverage_by_bucket={k: dict(v) for k, v in sorted(sb.items())},
        capture_window_exclusions=dict(pcnt),
        universe_inventory_all_families={"%s|%s" % k: v for k, v in sorted(inv.items())},
        cells=cells + nomodel,
        status_counts=dict(collections.Counter(c["status"] for c in cells + nomodel)))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(report, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print(json.dumps(report["status_counts"]), json.dumps(integ, default=str)[:1500])
    for c in cells:
        g = c["incremental_gain"]
        if c["is_primary_challenger"]:
            print(c["family"], c["horizon"], c["n_games"], c["n_contracts"], c["status"], g["mean"] and "%.4f [%.4f,%.4f] holm=%.3f" % (g["mean"], g["lo"], g["hi"], g["holm_p"]))


if __name__ == "__main__":
    main()
