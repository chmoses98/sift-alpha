"""CFB Q1-total input ablation with ESPN team-game pace/efficiency features (cfb-edge-finder `data/football/2026/team_games.jsonl`).

Every feature is an as-of running mean (shrunk to the league mean) over the team's earlier games that were FINAL before the target
game's kickoff (kickoff_of_earlier_game + RESULT_LAG_HOURS <= target kickoff). The rows were backfilled on one date (observed_at is
NOT the true availability time), so availability is a conservative proxy, and results stay research-only.
Model per variant: Q1_total = league_mean + sum(beta_k * feature_k), ridge, refit by EXPANDING WINDOW on earlier evaluated games only
(a game never trains its own prediction). Variants are compared to the no-information league-mean baseline with the same
week-cluster bootstrap, Bonferroni (every variant counted), chronological-halves and leave-one-team-out gates as cfb_q1_ablation."""
from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .cfb_q1_ablation import MIN_CLUSTERS, _cluster_boot, _team_jackknife, _week
from .cfb_q1_intel import BOOT, MIN_EVAL, RESULT_LAG_HOURS, SEED, SHRINK_K

MIN_TRAIN = 60
RIDGE = 5.0
GROUPS = {"V6_pace_plays": ["pace"], "V7_drives": ["drives"], "V8_success_rate": ["succ"], "V9_explosiveness": ["expl"], "V10_pass_rate": ["pass"],
          "V11_all_pace_efficiency": ["pace", "drives", "succ", "expl", "pass"]}
INPUT_OF = {"V6_pace_plays": "cfb.pace", "V7_drives": "cfb.drives", "V8_success_rate": "cfb.off_ppa/def_ppa (success-rate proxy)", "V9_explosiveness": "cfb.drives (explosiveness)",
            "V10_pass_rate": "cfb.pass_rate", "V11_all_pace_efficiency": "cfb.pace+drives+success+explosive+pass_rate"}


def _ts(s):
    return datetime.strptime(s.replace("Z", ""), "%Y-%m-%dT%H:%M") if len(s) <= 17 else datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def team_game_metrics(r):
    b, p = r["box"], r["pbp"]
    plays = max(p.get("scrim_plays") or b.get("plays") or 0, 1)
    pa, ru = p.get("pass_plays", 0), p.get("rush_plays", 0)
    return {"plays": b.get("plays") or plays, "drives": p.get("drives") or 0, "succ": (p.get("success_plays") or 0) / plays,
            "expl": ((p.get("explosive_pass") or 0) + (p.get("explosive_rush") or 0)) / plays, "pass": pa / max(pa + ru, 1)}


def build_rows(team_games, period_games):
    """period_games: cfb_q1_intel.load_games output. Returns evaluation rows with as-of features and the Q1 total."""
    lag = timedelta(hours=RESULT_LAG_HOURS)
    by_game = defaultdict(dict)
    for r in team_games:
        if r.get("pbp") and r.get("box"):
            by_game[r["game_id"]][r["team_id"]] = r
    hist = defaultdict(list)            # team -> [(avail, own metrics, opponent-vs-team metrics)]
    league = []                         # (avail, metrics of one team-game)
    pending = []
    rows = []
    for g in sorted(period_games, key=lambda x: (x["start_time_utc"], x["event_id"])):
        start = _ts(g["start_time_utc"])
        keep = []
        for p in pending:
            if p["avail"] <= start:
                for t, own, opp in p["sides"]:
                    hist[t].append((own, opp)); league.append(own)
            else:
                keep.append(p)
        pending = keep
        h, a = g["home_team_id"], g["away_team_id"]
        tg = by_game.get(g["event_id"], {})
        if h in tg and a in tg:
            mh, ma = team_game_metrics(tg[h]), team_game_metrics(tg[a])
            pending.append({"avail": start + lag, "sides": [(h, mh, ma), (a, ma, mh)]})
        else:
            tg = None
        hh, aa = hist[h], hist[a]
        if tg is not None and len(league) >= 60 and len(hh) >= 3 and len(aa) >= 3:
            lm = {k: sum(x[k] for x in league) / len(league) for k in ("plays", "drives", "succ", "expl", "pass")}

            def mean(hs, which, k):
                v = [x[which][k] for x in hs]
                return (sum(v) + SHRINK_K * lm[k]) / (len(v) + SHRINK_K)
            f = {"pace": (mean(hh, 0, "plays") + mean(aa, 0, "plays")) / 2 - lm["plays"],
                 "drives": (mean(hh, 0, "drives") + mean(aa, 0, "drives")) / 2 - lm["drives"],
                 "succ": (mean(hh, 0, "succ") + mean(aa, 1, "succ") + mean(aa, 0, "succ") + mean(hh, 1, "succ")) / 4 - lm["succ"],
                 "expl": (mean(hh, 0, "expl") + mean(aa, 1, "expl") + mean(aa, 0, "expl") + mean(hh, 1, "expl")) / 4 - lm["expl"],
                 "pass": (mean(hh, 0, "pass") + mean(aa, 0, "pass")) / 2 - lm["pass"]}
            rows.append({"event_id": g["event_id"], "start_time_utc": g["start_time_utc"], "home": h, "away": a, "f": f, "actual": g["home_periods"][0] + g["away_periods"][0]})
    return rows


def _solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(M[r][i]))
        M[i], M[piv] = M[piv], M[i]
        d = M[i][i] or 1e-12
        for j in range(i, n + 1):
            M[i][j] /= d
        for r in range(n):
            if r != i:
                fct = M[r][i]
                for j in range(i, n + 1):
                    M[r][j] -= fct * M[i][j]
    return [M[i][n] for i in range(n)]


def ridge_fit(X, y, lam=RIDGE):
    """Ridge on features standardised by TRAIN std (returns coefficients on the raw scale)."""
    k = len(X[0])
    xbar = [sum(x[i] for x in X) / len(X) for i in range(k)]
    sd = [max((sum((x[i] - xbar[i]) ** 2 for x in X) / len(X)) ** 0.5, 1e-9) for i in range(k)]
    Z = [[(x[i] - xbar[i]) / sd[i] for i in range(k)] for x in X]
    beta, mu = _ridge_std(Z, y, lam)
    return [beta[i] / sd[i] for i in range(k)], mu, xbar


def _ridge_std(X, y, lam):
    k = len(X[0])
    mu_y = sum(y) / len(y)
    A = [[sum(x[i] * x[j] for x in X) + (lam * len(X) / 100 if i == j else 0) for j in range(k)] for i in range(k)]
    b = [sum(x[i] * (yy - mu_y) for x, yy in zip(X, y)) for i in range(k)]
    return _solve(A, b), mu_y


def predict_variants(rows):
    """Expanding window: row i is predicted from a model fit on rows[:i] ONLY (their actuals are final before row i starts only if
    their own start + lag <= row i start; rows are skipped from training otherwise)."""
    lag = timedelta(hours=RESULT_LAG_HOURS)
    out = []
    for i, r in enumerate(rows):
        start = _ts(r["start_time_utc"])
        train = [t for t in rows[:i] if _ts(t["start_time_utc"]) + lag <= start]
        if len(train) < MIN_TRAIN:
            continue
        base = sum(t["actual"] for t in train) / len(train)
        rec = {"event_id": r["event_id"], "start_time_utc": r["start_time_utc"], "home": r["home"], "away": r["away"], "actual": r["actual"], "V0_league_mean": base}
        for v, feats in GROUPS.items():
            beta, mu, xbar = ridge_fit([[t["f"][k] for k in feats] for t in train], [t["actual"] for t in train])
            rec[v] = mu + sum(b * (r["f"][k] - xb) for b, k, xb in zip(beta, feats, xbar))
        out.append(rec)
    return out


def ablate(rows):
    n = len(rows)
    res = {"n_eval": n, "min_eval": MIN_EVAL, "dependence_aware": True, "dependence_method": "calendar-week cluster bootstrap + leave-one-team-out minimum", "variants": {}}
    if not n:
        return res
    rng = random.Random(SEED)
    err = {v: [abs(r["actual"] - r[v]) for r in rows] for v in ["V0_league_mean", *GROUPS]}
    res["variants"]["V0_league_mean"] = {"mae": round(sum(err["V0_league_mean"]) / n, 4)}
    keys = [_week(r) for r in rows]
    h = n // 2
    for v in GROUPS:
        d = [err["V0_league_mean"][i] - err[v][i] for i in range(n)]
        lo, hi = _cluster_boot(d, keys, rng)
        blo, bhi = _cluster_boot(d, keys, rng, 0.05 / len(GROUPS))
        jk = _team_jackknife(d, rows)
        halves = [sum(d[:h]) / h, sum(d[h:]) / (n - h)]
        verdict = ("INSUFFICIENT_DATA" if n < MIN_EVAL else "VALIDATED_PREDICTIVE" if (blo > 0 and min(halves) > 0 and jk is not None and jk > 0 and len(set(keys)) >= MIN_CLUSTERS)
                   else "SUGGESTIVE_UNCONFIRMED" if lo > 0 else "HARMFUL" if hi < 0 else "NOT_DEMONSTRATED")
        res["variants"][v] = {"mae": round(sum(err[v]) / n, 4), "input": INPUT_OF[v], "compared_to": "V0_league_mean", "mae_improvement_mean": round(sum(d) / n, 4),
                              "mae_improvement_ci95": [round(lo, 4), round(hi, 4)], "mae_improvement_ci_bonferroni": [round(blo, 4), round(bhi, 4)], "n_comparisons_family": len(GROUPS),
                              "chronological_halves_mean": [round(x, 4) for x in halves], "team_jackknife_min_mean": None if jk is None else round(jk, 4), "n_week_clusters": len(set(keys)), "verdict": verdict}
    return res


def build(team_games_path, period_data_dir, manifest_path, meta):
    from . import cfb_q1_intel as q
    games = q.load_games(Path(period_data_dir), json.loads(Path(manifest_path).read_text()))
    tg = [json.loads(line) for line in Path(team_games_path).read_text().splitlines() if line.strip()]
    rows = build_rows(tg, games)
    res = ablate(predict_variants(rows))
    res.update({"schema_version": "ablation-1.0", "family": "CFB/quarter_total", "period": "Q1", "feature_rows_with_history": len(rows), "team_game_rows": len(tg), "result_lag_hours": RESULT_LAG_HOURS, **meta,
                "market_baseline": "NOT_EVALUABLE: no timestamped Kalshi 1Q quote history exists for these completed games (see blockers); baseline is the no-information league mean.",
                "availability_caveat": "team_games rows were backfilled on a single date; availability = kickoff + lag is a proxy, not verified point-in-time publication."})
    return res
