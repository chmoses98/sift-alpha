#!/usr/bin/env python3
"""Assemble the dashboard-ready outcome-intelligence export and the coverage ledger from per-sport audit reports (no recomputation).
Tree: sport -> family -> cells[horizon/challenger]; each cell carries inputs -> evidence -> model prob -> market prob -> incremental gain -> confidence -> status.
Anything not supported is UNKNOWN with a reason. usage: build_dashboard.py [--dir reports/outcome_intel]"""
from __future__ import annotations
import argparse, collections, glob, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import status as S

UNK = lambda why: dict(value="UNKNOWN", reason=why)


def holdout_games_of(c):
    g = c.get("incremental_gain") or {}
    d = c.get("challenger_detail") or {}
    m_ = c.get("model_metrics") or {}
    for v in (c.get("holdout_games"), g.get("n_holdout_games"), d.get("holdout_games"), m_.get("holdout_games") if isinstance(m_, dict) else None):
        if isinstance(v, (int, float)):
            return int(v)
    m = re.search(r"(\d+) (?:holdout|HOLDOUT)[ -]?(?:games|matches)|holdout (?:only )?(\d+) (?:games|matches)|over (\d+) holdout", c.get("reason") or "")
    return int(next(x for x in m.groups() if x)) if m else None


def nc_of(c):
    g = c.get("incremental_gain") or {}
    d = c.get("challenger_detail") or {}
    for v in (c.get("negative_control"), g.get("negative_control"), d.get("negative_control_gain"), c.get("negative_control_gain_vs_calibrated")):
        if isinstance(v, dict) and v.get("lo") is not None:
            return v
    return None


def central_status(c, agent_status, hg):
    """The ONLY authority for cells that carry a gain estimate; sport-level statuses are kept as `agent_status` for traceability."""
    g = c.get("incremental_gain") or {}
    if agent_status in ("MISSING_DATA", "INVALID_EVIDENCE", "INCONCLUSIVE_UNDERPOWERED") and g.get("mean") is None:
        return agent_status, None
    if g.get("mean") is None:      # a positive/null verdict without any gain estimate is unsupported
        return "INCONCLUSIVE_UNDERPOWERED", f"no gain estimate behind sport-level status {agent_status}"
    if agent_status in ("MISSING_DATA", "INVALID_EVIDENCE"):
        return agent_status, None
    st = S.classify_gain(g, hg, g.get("holm_p"), nc_of(c), c.get("validation_gates"))
    note = None
    if hg is None:
        note = "holdout game count not recorded -> cannot verify power"
    elif st == "PROMISING_INSUFFICIENT" and g["mean"] < S.MEANINGFUL:
        note = f"CI lower bound > 0 but mean gain {g['mean']:.4f} < {S.MEANINGFUL} logloss (economically negligible); sport-level status was {agent_status}"
    elif st != agent_status:
        note = f"recomputed centrally: sport-level status was {agent_status}"
    return st, note


def norm(c, sport=None):
    g = c.get("incremental_gain") or c.get("gain") or {}
    gain = UNK(c.get("reason") or "no incremental test run") if not g or g.get("mean") is None else dict(
        metric="logloss_gain_vs_calibrated_market (positive = challenger better)", mean=g["mean"], lo=g.get("lo"), hi=g.get("hi"), holm_p=g.get("holm_p"))
    st0 = c.get("status") or c.get("evidence_status") or "MISSING_DATA"
    hg = holdout_games_of(c)
    st, note = central_status(c, st0, hg)
    c = dict(c, holdout_games=hg)
    return dict(agent_status=st0, status_note=note, sport=sport or c.get("sport"), family=c.get("family", "UNKNOWN"), horizon=c.get("horizon", "all"), challenger=c.get("challenger") or "UNKNOWN",
                inputs_available=c.get("inputs_available") or UNK("not recorded"),
                evidence=dict(n_games=c.get("n_games"), n_contracts=c.get("n_contracts"), holdout_games=c.get("holdout_games"), price_coverage=c.get("price_coverage") or UNK("not recorded"),
                              settlement_source=c.get("settlement_source") or UNK("not recorded")),
                market_probability=c.get("market_metrics") or UNK("no pregame market price"),
                model_probability=c.get("model_metrics") or UNK("no archived pregame model probability"),
                incremental_gain=gain, validation_gates={k: (c.get("validation_gates") or {}).get(k) for k in S.GATES}, validation_status=st if st in S.ALL else "INVALID_EVIDENCE", reason=c.get("reason"))


def cfb_cells(d):
    inc = json.load(open(os.path.join(d, "cfb_incremental.json")))
    out = []
    for k, c in inc["cells"].items():
        fam, lab = k.split("|")
        g = c.get("gain_vs_calibrated_market_logloss")
        out.append(dict(sport="CFB", family=fam, horizon=lab, challenger="SIFT CFB model (0.4.0 margin-corrected)", n_games=(c.get("train_games", 0) or 0) + (c.get("holdout_games", 0) or 0),
                        holdout_games=c.get("holdout_games"), n_contracts=c.get("n_holdout"), price_coverage="executable bid/ask snapshots, spread<=10c", settlement_source="DERIVED from ESPN final (exchange result confirmed on 14 wagered tickers only)",
                        market_metrics=c.get("logloss"), incremental_gain=dict(g, holm_p=c.get("holm_p_gain_vs_calibrated")) if g else None, status=c["evidence_status"],
                        reason="3 weeks of prospective capture; ~30 holdout games per cell"))
    for f_, why in (("team_total", "no team-total prices captured"), ("1h/quarter", "no period-market prices captured (ESPN period scores exist for 573 games)"), ("player_props", "no prop prices captured")):
        out.append(dict(sport="CFB", family=f_, horizon="all", status="MISSING_DATA", reason=why + "; repair: add series discovery to the CFB research capture"))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dir", default="reports/outcome_intel"); a = ap.parse_args()
    cells = []
    cells += [norm(c) for c in cfb_cells(a.dir)]
    for f in sorted(glob.glob(os.path.join(a.dir, "*_audit.json"))):
        sp = os.path.basename(f).split("_")[0].upper()
        if sp == "CFB":
            continue
        d = json.load(open(f))
        for c in d.get("cells", []):
            cells.append(norm(c, sp if not c.get("sport") else c["sport"]))
    tree = collections.defaultdict(lambda: collections.defaultdict(list))
    for c in cells:
        tree[c["sport"]][c["family"]].append(c)
    counts = collections.Counter(c["validation_status"] for c in cells)
    tested = [c for c in cells if isinstance(c["incremental_gain"], dict) and c["incremental_gain"].get("mean") is not None]
    ranked = sorted(tested, key=lambda c: (-(c["incremental_gain"]["lo"] if c["incremental_gain"].get("lo") is not None else -9), -c["incremental_gain"]["mean"]))
    rank_row = lambda c: dict(sport=c["sport"], family=c["family"], horizon=c["horizon"], challenger=c["challenger"], holdout_games=c["evidence"]["holdout_games"],
                              gain_mean=c["incremental_gain"]["mean"], gain_lo=c["incremental_gain"].get("lo"), gain_hi=c["incremental_gain"].get("hi"),
                              holm_p=c["incremental_gain"].get("holm_p"), status=c["validation_status"], status_note=c["status_note"])
    ledger = []
    for sp, fams in sorted(tree.items()):
        for fam, cs in sorted(fams.items()):
            ledger.append(dict(sport=sp, family=fam, cells=len(cs), statuses=dict(collections.Counter(c["validation_status"] for c in cs)),
                               max_holdout_games=max([c["evidence"]["holdout_games"] or 0 for c in cs] + [0]),
                               reasons=sorted({c["reason"] for c in cs if c["reason"]})[:3]))
    out = dict(status="RESEARCH_ONLY", schema="sift-outcome-intel-dashboard/1", status_counts=dict(counts), validated=[(c["sport"], c["family"], c["horizon"], c["challenger"]) for c in cells if c["validation_status"] == "VALIDATED_IMPROVEMENT"],
               tested_cells=len(tested), ranked_signals_top25_by_ci_lower_bound=[rank_row(c) for c in ranked[:25]],
               worst5_by_mean_gain=[rank_row(c) for c in sorted(tested, key=lambda c: c["incremental_gain"]["mean"])[:5]],
               sport_status_counts={sp: dict(collections.Counter(c["validation_status"] for c in cells if c["sport"] == sp)) for sp in sorted({c["sport"] for c in cells})},
               ledger=ledger, tree={s: {f: v for f, v in fs.items()} for s, fs in tree.items()})
    json.dump(out, open(os.path.join(a.dir, "dashboard.json"), "w"), indent=1, sort_keys=True, default=str)
    json.dump(dict(status="RESEARCH_ONLY", schema="sift-outcome-intel-coverage/2", ledger=ledger, status_counts=dict(counts)), open(os.path.join(a.dir, "coverage_ledger.json"), "w"), indent=1, sort_keys=True)
    print(dict(counts), len(cells), "cells")


if __name__ == "__main__":
    main()
