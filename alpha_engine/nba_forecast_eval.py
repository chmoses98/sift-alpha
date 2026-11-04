"""Independent out-of-sample evaluation of ARCHIVED, frozen pre-game NBA forecasts against ESPN final box-score outcomes.

Inputs (read-only, from nba-edge-finder `projection-data`): forecasts/nba/*/*.jsonl.gz and outcomes/nba/*/*.jsonl.gz.
For each (player, game, family) the LAST forecast with archived_utc <= game_start_utc is used per model_role (challenger/incumbent);
a forecast archived after tip-off is never used. Stats are evaluated conditional on the player participating (the forecasts are
conditional on playing); participation itself is evaluated on all rostered players with a forecast.
Metrics: discrete CRPS from the archived challenger pmf, MAE of the mean, central-80% coverage (discrete lattices over-cover), participation Brier.
The incumbent (existing model) archives only a mean, so challenger vs incumbent is compared on absolute error of the mean on the SAME player-games, with calendar-date cluster bootstrap,
Bonferroni over every comparison reported, and a leave-one-player-out minimum. Nothing here implies a market edge: no price baseline."""
from __future__ import annotations

import glob
import gzip
import json
import random
from collections import defaultdict
from datetime import datetime

BOOT = 2000
SEED = 20261104
STAT_FAMILIES = ["minutes", "points", "rebounds", "assists", "threes", "pra"]


def _ts(s):
    return datetime.strptime(s[:19].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")


def load(root):
    fc = {}
    for f in sorted(glob.glob(f"{root}/forecasts/nba/*/*.jsonl.gz")):
        for line in gzip.open(f, "rt"):
            r = json.loads(line)
            if r["family"] not in STAT_FAMILIES + ["participation"] or _ts(r["archived_utc"]) > _ts(r["game_start_utc"]):
                continue                       # post-tip archives are never evaluated
            k = (r["entity_id"], r["game_id"], r["family"], r["model_role"])
            if k not in fc or r["archived_utc"] >= fc[k]["archived_utc"]:
                fc[k] = r
    oc = {}
    for f in sorted(glob.glob(f"{root}/outcomes/nba/*/*.jsonl.gz")):
        for line in gzip.open(f, "rt"):
            r = json.loads(line)
            if r.get("final") and r.get("in_box") is not None:
                oc[(r["entity_id"], r["game_id"], r["family"])] = r
    return fc, oc


def crps(probs, lo, y):
    tot, c = 0.0, 0.0
    n = len(probs)
    for i in range(n):
        c += probs[i]
        x = lo + i
        tot += (c - (1.0 if x >= y else 0.0)) ** 2
    if y > lo + n - 1:                          # outcome above support: add mass-free tail
        tot += (y - (lo + n - 1)) * 1.0
    return tot


def interval80(probs, lo, y):
    c, q10, q90 = 0.0, None, None
    for i, p in enumerate(probs):
        c += p
        if q10 is None and c >= 0.1:
            q10 = lo + i
        if q90 is None and c >= 0.9:
            q90 = lo + i
    return q10 is not None and q10 <= y <= (q90 if q90 is not None else lo + len(probs))


def _cboot(d, keys, rng, alpha=0.05):
    g = defaultdict(list)
    for x, k in zip(d, keys):
        g[k].append(x)
    gl = list(g.values()); m = len(gl); means = []
    for _ in range(BOOT):
        t = c = 0
        for _ in range(m):
            q = gl[rng.randrange(m)]; t += sum(q); c += len(q)
        means.append(t / c)
    means.sort()
    return means[int(alpha / 2 * BOOT)], means[min(BOOT - 1, int((1 - alpha / 2) * BOOT) - 1)]


def _loo_player(d, players):
    by = defaultdict(list)
    for x, p in zip(d, players):
        by[p].append(x)
    tot, n = sum(d), len(d)
    return min((tot - sum(v)) / (n - len(v)) for v in by.values() if n - len(v) > 0)


def evaluate(fc, oc):
    rng = random.Random(SEED)
    res = {"families": {}, "participation": {}}
    comps = 0
    rows = {f: [] for f in STAT_FAMILIES}
    for (eid, gid, fam, role), r in fc.items():
        if role != "challenger" or fam not in STAT_FAMILIES:
            continue
        o = oc.get((eid, gid, fam))
        inc = fc.get((eid, gid, fam, "incumbent"))
        if not o or not o.get("participated") or o.get("actual") is None or o["actual"] != o["actual"]:
            continue
        y = float(o["actual"])
        row = {"date": o["game_date"], "player": eid, "y": y, "c_mean": r["mean"], "c_crps": crps(r["probs"], r["lo"], y), "c_in80": interval80(r["probs"], r["lo"], y)}
        if inc and inc.get("mean") is not None:            # the incumbent archives a MEAN only (empty pmf): compare on absolute error of the mean
            row.update(i_mean=inc["mean"])
        rows[fam].append(row)
    for fam, rs in rows.items():
        if not rs:
            continue
        paired = [r for r in rs if "i_mean" in r]
        ent = {"n_player_games": len(rs), "n_dates": len({r["date"] for r in rs}), "n_players": len({r["player"] for r in rs}),
               "challenger_mae": round(sum(abs(r["y"] - r["c_mean"]) for r in rs) / len(rs), 4), "challenger_bias": round(sum(r["c_mean"] - r["y"] for r in rs) / len(rs), 4),
               "challenger_crps": round(sum(r["c_crps"] for r in rs) / len(rs), 4), "challenger_coverage_80": round(sum(r["c_in80"] for r in rs) / len(rs), 4)}
        if paired:
            d = [abs(r["y"] - r["i_mean"]) - abs(r["y"] - r["c_mean"]) for r in paired]            # >0: challenger mean is closer
            keys = [r["date"] for r in paired]
            lo, hi = _cboot(d, keys, rng)
            ent["paired_vs_incumbent"] = {"n": len(paired), "incumbent_mae": round(sum(abs(r["y"] - r["i_mean"]) for r in paired) / len(paired), 4), "challenger_mae": round(sum(abs(r["y"] - r["c_mean"]) for r in paired) / len(paired), 4),
                                          "mae_improvement_mean": round(sum(d) / len(d), 4), "ci95_date_cluster": [round(lo, 4), round(hi, 4)], "min_leave_one_player_out": round(_loo_player(d, [r["player"] for r in paired]), 4), "_d": d, "_k": keys}
            comps += 1
        res["families"][fam] = ent
    for fam, ent in res["families"].items():
        p = ent.get("paired_vs_incumbent")
        if not p:
            continue
        d, keys = p.pop("_d"), p.pop("_k")
        blo, bhi = _cboot(d, keys, rng, 0.05 / max(comps, 1))
        p["ci_bonferroni"] = [round(blo, 4), round(bhi, 4)]; p["n_comparisons"] = comps
        h = len(d) // 2
        p["chronological_halves_mean"] = [round(sum(d[:h]) / h, 4), round(sum(d[h:]) / (len(d) - h), 4)] if h else None
        p["verdict"] = ("CHALLENGER_BETTER" if blo > 0 and min(p["chronological_halves_mean"]) > 0 and p["min_leave_one_player_out"] > 0 else
                        "CHALLENGER_WORSE" if bhi < 0 else "NOT_DEMONSTRATED")
    # participation (injury/availability input): Brier of archived p_play vs prior base-rate baseline, chronological
    prs = []
    for (eid, gid, fam, role), r in fc.items():
        if fam != "participation" or role != "challenger":
            continue
        o = oc.get((eid, gid, "minutes"))
        if not o:
            continue
        prs.append({"date": o["game_date"], "player": eid, "p": r["probs"][1], "y": 1.0 if o.get("participated") else 0.0, "implicit": bool((r.get("participation") or {}).get("implicit"))})
    prs.sort(key=lambda r: r["date"])
    if prs:
        seen_n = seen_y = 0
        d, keys, players = [], [], []
        for date in sorted({r["date"] for r in prs}):
            day = [r for r in prs if r["date"] == date]
            base = (seen_y / seen_n) if seen_n >= 200 else None
            if base is not None:
                for r in day:
                    d.append((base - r["y"]) ** 2 - (r["p"] - r["y"]) ** 2); keys.append(date); players.append(r["player"])
            seen_n += len(day); seen_y += sum(r["y"] for r in day)
        explicit = [r for r in prs if not r["implicit"]]
        res["participation"] = {"n_player_games": len(prs), "participated_rate": round(sum(r["y"] for r in prs) / len(prs), 4), "brier_model": round(sum((r["p"] - r["y"]) ** 2 for r in prs) / len(prs), 4),
                                "explicit_report_share": round(len(explicit) / len(prs), 4), "explicit_brier": round(sum((r["p"] - r["y"]) ** 2 for r in explicit) / len(explicit), 4) if explicit else None,
                                "implicit_brier": round(sum((r["p"] - r["y"]) ** 2 for r in prs if r["implicit"]) / max(1, len(prs) - len(explicit)), 4)}
        if d:
            lo, hi = _cboot(d, keys, rng)
            res["participation"]["brier_improvement_vs_prior_base_rate"] = {"n": len(d), "mean": round(sum(d) / len(d), 5), "ci95_date_cluster": [round(lo, 5), round(hi, 5)], "min_leave_one_player_out": round(_loo_player(d, players), 5)}
    return res
