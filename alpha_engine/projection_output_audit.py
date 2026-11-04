"""Audit of a PUBLISHED projection file (nba-edge-finder projection-data `projections/nba/latest.json` shape).

Answers, from the real output only: which collected inputs are VISIBLE in the published projection (as fields that exist, are
populated and vary across players), how fresh it is, whether distributions are internally coherent, and the reconciliation status.
It does not re-run the model, so it can never promote a projection to independently reproduced. Aggregates only (no player names)."""
from __future__ import annotations

import hashlib
import json
import re
import statistics as st
from collections import Counter
from datetime import datetime

# output field -> registry input it evidences (an input is "visible" only if its field is populated for >=50% of players AND varies)
FIELD_EVIDENCE = {
    "nba.injuries_pit": ("participation.status", lambda p: (p.get("participation") or {}).get("status")),
    "nba.minutes": ("opportunity.mean", lambda p: (p.get("opportunity") or {}).get("mean")),
    "nba.opp_def_pos": ("opponent_adjustment.factor", lambda p: (p.get("opponent_adjustment") or {}).get("factor")),
    "nba.starters_pit": ("starter flag", lambda p: p.get("starter") if "starter" in p else (p.get("lineup") or {}).get("starter") if isinstance(p.get("lineup"), dict) else None),
    "nba.stat_dist": ("thresholds", lambda p: json.dumps(p.get("thresholds"), sort_keys=True) if p.get("thresholds") else None),
}
ADJ_RX = {"participation": r"^Participation", "opponent": r"^Opponent ", "teammates_out_redistribution": r"Teammates listed out"}


def _ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def audit(raw: bytes, source: dict) -> dict:
    d = json.loads(raw)
    P = d["players"]
    n = len(P)
    vis = {}
    for iid, (field, fn) in FIELD_EVIDENCE.items():
        vals = [fn(p) for p in P]
        pop = [v for v in vals if v is not None]
        vis[iid] = {"field": field, "populated_share": round(len(pop) / n, 4) if n else 0, "distinct_values": len(set(map(str, pop))),
                    "visible_in_output": bool(n and len(pop) / n >= 0.5 and len(set(map(str, pop))) > 1)}
    adj = Counter()
    for p in P:
        for a in p.get("adjustments", []):
            for k, rx in ADJ_RX.items():
                if re.search(rx, a):
                    adj[k] += 1
    coh = Counter()
    for p in P:
        t = p.get("thresholds") or {}
        ks = sorted(t, key=float)
        coh["thresholds_monotone"] += all(t[a] >= t[b] for a, b in zip(ks, ks[1:]))
        coh["p10<=median<=p90"] += (p.get("p10", 0) <= p.get("median", 0) <= p.get("p90", 0))
        coh["mean_within_p10_p90"] += (p.get("p10", 0) <= p.get("mean", 0) <= p.get("p90", 0))
    ages = [(p.get("participation") or {}).get("age_minutes") for p in P if (p.get("participation") or {}).get("age_minutes") is not None]
    fac = [p["opponent_adjustment"]["factor"] for p in P if p.get("opponent_adjustment")]
    gen, asof = _ts(d["generated_utc"]), _ts(d["data_asof_utc"])
    return {"schema_version": "projection-output-audit-1.0", "source": dict(source, sha256=hashlib.sha256(raw).hexdigest(), model=d.get("model"), mode=d.get("mode")),
            "slate_date": d.get("slate_date"), "generated_utc": d["generated_utc"], "data_asof_utc": d["data_asof_utc"],
            "freshness_minutes_generated_minus_asof": round((gen - asof).total_seconds() / 60, 1), "n_players": n,
            "by_family": dict(Counter(p["family"] for p in P)), "readiness": dict(Counter(p.get("readiness") for p in P)),
            "actionable": sum(bool(p.get("actionable")) for p in P), "gate_status": dict(Counter((p.get("gate") or {}).get("status") for p in P)),
            "participation": {"source": dict(Counter((p.get("participation") or {}).get("source") for p in P)), "certainty": dict(Counter((p.get("participation") or {}).get("certainty") for p in P)),
                              "status": dict(Counter((p.get("participation") or {}).get("status") for p in P)), "implicit_not_listed": sum(bool((p.get("participation") or {}).get("implicit")) for p in P),
                              "max_report_age_minutes": max(ages) if ages else None},
            "adjustment_counts": dict(adj), "opponent_adjustment": {"n": len(fac), "n_not_one": sum(abs(f - 1) > 1e-9 for f in fac), "sample_games_median": st.median([p["opponent_adjustment"]["sample_games"] for p in P if p.get("opponent_adjustment")]) if fac else None},
            "distribution_coherence": {k: round(v / n, 4) for k, v in coh.items()}, "game_reconciliation": dict(Counter(r.get("status") for r in d.get("reconciliation", []))),
            "input_visibility": vis, "limits": "Descriptive audit of one published file. It shows which input-derived fields reach the output; it does not prove the model's use is correct, reproducible, or predictive."}


# ------------------------------------------------------------------ generic leaf-visibility adapters (CBB games, NFL forecasts)
def _leaves(o, pre=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _leaves(v, f"{pre}{k}.")
    elif isinstance(o, list):
        yield pre + "[]", (len(o) > 0)
    else:
        yield pre.rstrip("."), o


def leaf_visibility(records, mapping):
    """mapping: input_id -> [leaf path prefixes]. visible_in_output needs >=50% of records populated (non-null/non-empty) and >1 distinct value."""
    n = len(records)
    stats = {}
    for r in records:
        for path, v in _leaves(r):
            s = stats.setdefault(path, [0, set()])
            if v not in (None, "", False) and not (isinstance(v, float) and v != v):
                s[0] += 1
                if not isinstance(v, bool):
                    s[1].add(str(v)[:40])
    out = {}
    for iid, prefixes in mapping.items():
        hit = {p: (round(c / n, 3), len(d)) for p, (c, d) in stats.items() if any(p.startswith(x) for x in prefixes) for _ in [0]}
        vis = [p for p, (sh, dv) in hit.items() if sh >= 0.5 and dv > 1]
        out[iid] = {"leaf_prefixes": prefixes, "visible_in_output": bool(vis), "visible_leaves": sorted(vis)[:6], "matching_leaves": len(hit)}
    return out


CBB_MAP = {"cbb.adj_off": ["ratings.home.adj_off", "ratings.away.adj_off", "projection.home_ppp", "projection.away_ppp"],
           "cbb.adj_def": ["ratings.home.adj_def", "ratings.away.adj_def"], "cbb.tempo": ["ratings.home.adj_tempo", "projection.possessions"],
           "cbb.four_factors": ["ratings.home.four_factors"], "cbb.roster_minutes": ["roster.sides"], "cbb.starters": ["player_context.h.rotation_known_STARTERS"],
           "cbb.player_usage": ["player_context.h.player_off", "player_context.h.player_def"], "cbb.venue": ["game.site"],
           "cbb.score_resid": ["projection.total_sd", "projection.margin_sd"], "cbb.half_split": ["projection.first_half", "projection.h1"],
           "cbb.injuries": ["roster.sides.home.injur", "roster.sides.away.injur"], "m.quote_history": ["market."]}
NFL_MAP = {"nfl.injuries_pit": ["participation"], "nfl.depth_chart_pit": ["position"], "nfl.snaps": ["snaps"], "nfl.targets": ["targets"], "nfl.weather_pit": ["weather"],
           "nfl.qb": ["qb"], "nfl.pace": ["pace"], "nfl.off_epa": ["off_epa"], "nfl.def_epa": ["def_epa"], "nfl.script": ["script"], "nfl.proe": ["proe"]}


def _git(repo, *a, binary=False):
    import subprocess
    r = subprocess.run(["git", "-C", str(repo), *a], capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode()[:200])
    return r.stdout if binary else r.stdout.decode()


def cbb_audit(repo, ref="FETCH_HEAD", model_dir="projections/pure-0.5.0_roster/"):
    """Latest projection file per game in the newest model directory (pinned commit)."""
    import collections
    commit = _git(repo, "rev-parse", ref).strip()
    files = [f for f in _git(repo, "ls-tree", "-r", "--name-only", ref).split("\n") if f.startswith(model_dir) and "/G" in f]
    by = collections.defaultdict(list)
    for f in files:
        by[f.split("/")[-2]].append(f)
    recs = [json.loads(_git(repo, "show", f"{ref}:{sorted(v)[-1]}")) for v in by.values()]
    gen = sorted(r["generated_at"] for r in recs)
    pr = [r["projection"] for r in recs]
    return {"schema_version": "projection-output-audit-1.0", "sport": "CBB", "source": {"repo": "chmoses98/cbb-edge-finder", "branch": "projections-archive", "commit": commit, "model_dir": model_dir},
            "n_games": len(recs), "generated_range": [gen[0], gen[-1]], "model": dict(collections.Counter(r["model"]["version"] for r in recs)),
            "projection_fields": sorted(pr[0]), "market_joined_share": round(sum(r["market"] is not None for r in recs) / len(recs), 4),
            "matchup_factors_populated_share": round(sum(bool(r["matchup_factors"]) for r in recs) / len(recs), 4),
            "input_visibility": leaf_visibility(recs, CBB_MAP),
            "limits": "Published game-level (home/away score, total, margin) projections only; no first-half, team-total-market or player-prop projection exists in this archive. Descriptive; model not re-run."}


def nfl_audit(repo, ref="FETCH_HEAD", last_n=3):
    import collections
    import gzip
    commit = _git(repo, "rev-parse", ref).strip()
    fc = sorted(f for f in _git(repo, "ls-tree", "-r", "--name-only", ref).split("\n") if f.startswith("forecasts/nfl/"))[-last_n:]
    rows = []
    for f in fc:
        rows += [json.loads(line) for line in gzip.decompress(_git(repo, "show", f"{ref}:{f}", binary=True)).decode().splitlines() if line.strip()]
    fam = collections.Counter(r["family"] for r in rows)
    return {"schema_version": "projection-output-audit-1.0", "sport": "NFL", "source": {"repo": "chmoses98/nfl-edge-finder", "branch": "projection-data", "commit": commit, "files": fc},
            "n_forecasts": len(rows), "families": dict(fam), "model": dict(collections.Counter(f"{r['model_id']}:{r['model_version']}" for r in rows)),
            "has_game_total_or_period_family": any(k for k in fam if "total" in k and "team" not in k or "quarter" in k or "half" in k),
            "team_level_families": sorted(k for k in fam if k.startswith("team_")), "authority": dict(collections.Counter(r.get("authority") for r in rows)),
            "participation_certainty": dict(collections.Counter(r.get("participation") for r in rows)), "gate_status": dict(collections.Counter(r.get("gate_status") for r in rows)),
            "input_visibility": leaf_visibility(rows, NFL_MAP),
            "limits": "Latest archived forecast files only (player/team stat distributions). No game total, quarter or half distribution is published here. Descriptive; model not re-run."}
