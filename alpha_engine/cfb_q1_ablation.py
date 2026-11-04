"""Input-level ablation for CFB first-quarter total, on ESPN period scores (pinned data branch).

Question answered: which *inputs derivable from this one source* improve out-of-sample prediction of Q1 total points?
Every variant uses only games final (start + RESULT_LAG_HOURS) before the target game's start, so ablations differ ONLY by
which inputs they consume. Variants (nested, each adds exactly one input to the previous):
  V0 league_mean      : prior league mean Q1 total (the baseline used by cfb_q1_intel)
  V1 +team_offense    : each team's shrunk Q1 points scored vs league
  V2 +opp_defense     : V1 + opponent's shrunk Q1 points allowed (== cfb_q1_intel 'model')
  V3 +home_site       : + home/neutral-site shift learned from prior games only
  V4 +recency         : V2 with exponential recency weights (half-life HALF_LIFE games)
  V5 team_only_total  : team's own scored+allowed with NO opponent adjustment (opponent-adjustment ablation)
A variant is VALIDATED_PREDICTIVE only when the Bonferroni-adjusted (over every comparison tried) paired-bootstrap CI of its MAE
improvement over its comparison is strictly > 0, n_eval >= MIN_EVAL, AND the improvement is positive in both chronological halves.
An unadjusted-only pass is SUGGESTIVE_UNCONFIRMED and must not be promoted. Bootstrap is over games; teams recur across games, so intervals are optimistic
(superseded: intervals are now week-clustered with a leave-one-team-out guard). No betting inference: this measures outcome prediction against a no-information baseline,
NOT against a Kalshi price (no quote history is joined here)."""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import timedelta

from .cfb_q1_intel import BOOT, MIN_EVAL, MIN_PRIOR, RESULT_LAG_HOURS, SEED, SHRINK_K, _ts

HALF_LIFE = 4.0
VARIANTS = ["V0_league_mean", "V1_team_offense", "V2_opp_defense", "V3_home_site", "V4_recency", "V5_team_only_total"]
COMPARE = {"V1_team_offense": "V0_league_mean", "V2_opp_defense": "V0_league_mean", "V3_home_site": "V2_opp_defense",
           "V4_recency": "V2_opp_defense", "V5_team_only_total": "V0_league_mean"}
MIN_CLUSTERS = 8
N_COMPARISONS = len(COMPARE)  # Bonferroni family: every comparison tried is counted, none dropped
INPUT_OF = {"V1_team_offense": "cfb.q_scoring (team scored)", "V2_opp_defense": "cfb.q_scoring (opponent allowed)",
            "V3_home_site": "cfb.venue/neutral_site", "V4_recency": "cfb.q_scoring (recency weighting)",
            "V5_team_only_total": "cfb.q_scoring (no opponent adjustment)"}


def _shr(vals, lm, weights=None):
    if not vals:
        return 0.0
    w = weights or [1.0] * len(vals)
    return (sum(wi * (v - lm) for wi, v in zip(w, vals)) ) / (sum(w) + SHRINK_K)


def predict_rows(games):
    lag = timedelta(hours=RESULT_LAG_HOURS)
    hist = defaultdict(list)          # team -> [(avail, scored, allowed)]
    pending, league, site = [], [], []  # site: (avail, home_minus_away_q1, neutral)
    rows = []
    for g in games:
        start = _ts(g["start_time_utc"])
        keep = []
        for p in pending:
            if p["avail"] <= start:
                hist[p["h"]].append((p["avail"], p["hq"], p["aq"])); hist[p["a"]].append((p["avail"], p["aq"], p["hq"]))
                league.append((p["avail"], p["hq"] + p["aq"])); site.append((p["hq"] - p["aq"], p["neutral"]))
            else:
                keep.append(p)
        pending = keep
        h, a = g["home_team_id"], g["away_team_id"]
        hq, aq = g["home_periods"][0], g["away_periods"][0]
        neutral = bool(g.get("neutral_site"))
        hh, aa = hist[h], hist[a]
        if len(league) >= 30 and len(hh) >= MIN_PRIOR and len(aa) >= MIN_PRIOR:
            lt = sum(t for _, t in league) / len(league); lm = lt / 2
            off = lambda hs: _shr([x[1] for x in hs], lm)
            dfn = lambda hs: _shr([x[2] for x in hs], lm)
            def rec(hs, idx):
                n = len(hs); w = [0.5 ** ((n - 1 - i) / HALF_LIFE) for i in range(n)]
                return _shr([x[idx] for x in hs], lm, w)
            v1 = lt + (off(hh) + off(aa))                               # offense only, no opponent defense
            v2 = (lm + off(hh) + dfn(aa)) + (lm + off(aa) + dfn(hh))
            non_neutral = [d for d, nu in site if not nu]
            shift = (sum(non_neutral) / len(non_neutral)) if non_neutral else 0.0
            v3 = v2 + (0.0 if neutral else 0.0)   # total unaffected by a symmetric home shift; see note
            v4 = (lm + rec(hh, 1) + rec(aa, 2)) + (lm + rec(aa, 1) + rec(hh, 2))
            # V5: each team's own scored+allowed, no opponent term (total = team mean of both sides, average of two teams)
            v5 = lt + (off(hh) + dfn(hh) + off(aa) + dfn(aa)) / 2
            rows.append({"event_id": g["event_id"], "start_time_utc": g["start_time_utc"], "home": h, "away": a, "actual": hq + aq, "neutral_site": neutral,
                         "V0_league_mean": lt, "V1_team_offense": v1, "V2_opp_defense": v2, "V3_home_site": v3, "V4_recency": v4, "V5_team_only_total": v5})
        pending.append({"avail": start + lag, "h": h, "a": a, "hq": hq, "aq": aq, "neutral": neutral})
    return rows


def _week(r):
    from datetime import datetime
    y, w, _ = datetime.strptime(r["start_time_utc"], "%Y-%m-%dT%H:%MZ").isocalendar()
    return f"{y}-W{w:02d}"


def _cluster_boot(diffs, keys, rng, alpha=0.05):
    """Cluster bootstrap: resample whole calendar weeks (all games in a week move together) so repeated teams/schedule
    shocks inside a week do not masquerade as independent evidence. Statistic = mean per-game difference over resampled games."""
    groups = defaultdict(list)
    for d, k in zip(diffs, keys):
        groups[k].append(d)
    gl = list(groups.values()); m = len(gl); means = []
    for _ in range(BOOT):
        tot = cnt = 0
        for _ in range(m):
            g = gl[rng.randrange(m)]; tot += sum(g); cnt += len(g)
        means.append(tot / cnt)
    means.sort()
    return means[int(alpha / 2 * BOOT)], means[min(BOOT - 1, int((1 - alpha / 2) * BOOT) - 1)]


def _team_jackknife(diffs, rows):
    """Leave-one-team-out mean improvement: min over teams (every game involving the team dropped). Guards against one team driving a result."""
    teams = {t for r in rows for t in (r.get("home"), r.get("away")) if t}
    if not teams:
        return None
    worst = None
    for t in teams:
        kept = [d for d, r in zip(diffs, rows) if t not in (r.get("home"), r.get("away"))]
        if kept:
            mu = sum(kept) / len(kept)
            worst = mu if worst is None else min(worst, mu)
    return worst


def ablate(rows, first_half_split=True):
    n = len(rows)
    out = {"n_eval": n, "min_eval": MIN_EVAL, "dependence_aware": True, "dependence_method": "calendar-week cluster bootstrap + leave-one-team-out minimum; residual dependence across weeks (team strength persistence) is NOT modelled",
           "variants": {}}
    if n == 0:
        return out
    rng = random.Random(SEED)
    err = {v: [abs(r["actual"] - r[v]) for r in rows] for v in VARIANTS}
    for v in VARIANTS:
        ent = {"mae": round(sum(err[v]) / n, 4), "rmse": round((sum((r["actual"] - r[v]) ** 2 for r in rows) / n) ** 0.5, 4)}
        if v in COMPARE:
            c = COMPARE[v]; d = [err[c][i] - err[v][i] for i in range(n)]
            keys = [_week(r) if "start_time_utc" in r else i for i, r in enumerate(rows)]
            lo, hi = _cluster_boot(d, keys, rng)
            blo, bhi = _cluster_boot(d, keys, rng, 0.05 / N_COMPARISONS)
            jk = _team_jackknife(d, rows)
            h = n // 2
            halves = [sum(d[:h]) / h, sum(d[h:]) / (n - h)] if h else [0.0, 0.0]
            ent.update({"input": INPUT_OF[v], "compared_to": c, "mae_improvement_mean": round(sum(d) / n, 4), "mae_improvement_ci95": [round(lo, 4), round(hi, 4)],
                        "mae_improvement_ci_bonferroni": [round(blo, 4), round(bhi, 4)], "n_comparisons_family": N_COMPARISONS,
                        "chronological_halves_mean": [round(x, 4) for x in halves], "team_jackknife_min_mean": None if jk is None else round(jk, 4),
                        "n_week_clusters": len(set(keys))})
            if n < MIN_EVAL:
                ent["verdict"] = "INSUFFICIENT_DATA"
            elif blo > 0 and min(halves) > 0 and jk is not None and jk > 0 and len(set(keys)) >= MIN_CLUSTERS:
                ent["verdict"] = "VALIDATED_PREDICTIVE"          # survives multiplicity, week-clustering, both halves AND leave-one-team-out
            elif lo > 0:
                ent["verdict"] = "SUGGESTIVE_UNCONFIRMED"         # unadjusted CI > 0 only; must not be promoted
            elif hi < 0:
                ent["verdict"] = "HARMFUL"
            else:
                ent["verdict"] = "NOT_DEMONSTRATED"
        out["variants"][v] = ent
    # chronological holdout stability: improvement of V2 over V0 in each half
    if first_half_split and n >= 2 * 50:
        h = n // 2
        out["stability_V2_vs_V0"] = {"first_half_mean": round(sum(err["V0_league_mean"][i] - err["V2_opp_defense"][i] for i in range(h)) / h, 4),
                                     "second_half_mean": round(sum(err["V0_league_mean"][i] - err["V2_opp_defense"][i] for i in range(h, n)) / (n - h), 4)}
    out["note_V3"] = "NEGATIVE CONTROL (not a signal): V3 is identical to V2 for a TOTAL by construction (a symmetric home shift cancels in home+away); reported to document that site is not a Q1-total input here."
    return out


def build(data_dir, manifest_path, data_commit):
    import json
    from pathlib import Path
    from . import cfb_q1_intel as q
    games = q.load_games(Path(data_dir), json.loads(Path(manifest_path).read_text()))
    res = ablate(predict_rows(games))
    res.update({"schema_version": "ablation-1.0", "family": "CFB/quarter_total", "period": "Q1", "source": "ESPN scoreboard period scores via sift-alpha:period-scoring-data",
                "data_commit": data_commit, "games_total": len(games), "result_lag_hours": RESULT_LAG_HOURS,
                "market_baseline": "NOT_EVALUABLE: no timestamped Kalshi 1Q quote history is joined (m.quote_history is STALE_OR_PARTIAL; only one 1Q shard pinned). Comparison is against a no-information league-mean baseline only, so this is NOT evidence of edge versus the market."})
    return res


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys
    from pathlib import Path
    # usage: python -m alpha_engine.cfb_q1_ablation DATA_DIR(out/data) DATA_COMMIT
    d = Path(sys.argv[1])
    out = build(d, d / "MANIFEST.sha256.json", sys.argv[2])
    p = Path(__file__).resolve().parents[1] / "research/audit/verification/CFB_quarter_total_ablation.json"
    p.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
