"""CFB first-quarter total: leakage-safe features, base rates and walk-forward validation.

Source: ESPN scoreboard period scores collected by the period-scoring backfill (data branch pinned by
commit; every file is sha256-verified against its manifest). Every row is POST-GAME information. A game's
result is treated as available only RESULT_LAG_HOURS after its scheduled start (assumption: the true
final time was not recorded), so a team's history for a game excludes anything not yet final.

Nothing here is a betting authorization. The validation rule is fixed in code *before* looking at the
outcome: the team-history model is SUPPORTED only if the paired bootstrap 95% interval of the absolute-error
improvement over the prior-league-mean baseline is strictly positive on at least MIN_EVAL held-out games.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

RESULT_LAG_HOURS = 4.0
SHRINK_K = 4.0
MIN_PRIOR = 3  # prior completed games required for BOTH teams to be evaluated
MIN_EVAL = 200
LINES = (6.5, 7.5, 9.5, 10.5, 13.5)
BOOT = 2000
SEED = 20261103


def _ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%MZ")


def load_games(data_dir: Path, manifest: dict[str, str]) -> list[dict]:
    """Load RECONCILED 4-period games after verifying every file against the manifest."""
    games = []
    for rel, digest in sorted(manifest.items()):
        if not rel.startswith("cfb/"):
            continue
        raw = (data_dir / rel).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"hash mismatch: {rel}")
        for line in raw.decode().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("reconciliation") != "RECONCILED" or r.get("regulation_periods") != 4:
                continue
            if len(r["home_periods"]) < 1 or len(r["away_periods"]) < 1:
                continue
            games.append(r)
    games.sort(key=lambda r: (r["start_time_utc"], r["event_id"]))
    seen = set()
    out = []
    for g in games:
        if g["event_id"] in seen:
            raise ValueError(f"duplicate event {g['event_id']}")
        seen.add(g["event_id"])
        out.append(g)
    return out


def walk_forward(games: list[dict]) -> dict:
    """Evaluate each game using only games final before its start. Returns per-game rows + summary."""
    lag = timedelta(hours=RESULT_LAG_HOURS)
    # team -> list of (available_at, scored_q1, allowed_q1)
    hist: dict[str, list[tuple[datetime, int, int]]] = defaultdict(list)
    pending = []  # games not yet final, kept to be released into history in time order
    rows = []
    league: list[tuple[datetime, int]] = []
    for g in games:
        start = _ts(g["start_time_utc"])
        # release finished games into history
        still = []
        for p in pending:
            if p["avail"] <= start:
                hist[p["h"]].append((p["avail"], p["hq"], p["aq"]))
                hist[p["a"]].append((p["avail"], p["aq"], p["hq"]))
                league.append((p["avail"], p["hq"] + p["aq"]))
            else:
                still.append(p)
        pending = still
        hq, aq = g["home_periods"][0], g["away_periods"][0]
        h, a = g["home_team_id"], g["away_team_id"]
        n_league = len(league)
        if n_league >= 30:
            lm_total = sum(t for _, t in league) / n_league
            lm_team = lm_total / 2
            hh, aa = hist[h], hist[a]
            if len(hh) >= MIN_PRIOR and len(aa) >= MIN_PRIOR:

                def rating(hs, which):
                    n = len(hs)
                    s = sum(x[which] for x in hs)
                    return (s - n * lm_team) / (n + SHRINK_K)

                off_h, def_h = rating(hh, 1), rating(hh, 2)  # allowed: higher = worse defense
                off_a, def_a = rating(aa, 1), rating(aa, 2)
                pred = (lm_team + off_h + def_a) + (lm_team + off_a + def_h)
                rows.append(
                    {
                        "event_id": g["event_id"],
                        "start_time_utc": g["start_time_utc"],
                        "home": g["home"],
                        "away": g["away"],
                        "n_prior_home": len(hh),
                        "n_prior_away": len(aa),
                        "league_team_mean": round(lm_team, 3),
                        "ratings": {
                            "home_off": round(off_h, 3),
                            "home_def_allowed": round(def_h, 3),
                            "away_off": round(off_a, 3),
                            "away_def_allowed": round(def_a, 3),
                        },
                        "baseline": round(lm_total, 3),
                        "model": round(pred, 3),
                        "actual": hq + aq,
                    }
                )
        pending.append({"avail": start + lag, "h": h, "a": a, "hq": hq, "aq": aq})
    return {"rows": rows, "n_games": len(games)}


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n_eval": 0, "verdict": "INSUFFICIENT_DATA"}
    be = [abs(r["actual"] - r["baseline"]) for r in rows]
    me = [abs(r["actual"] - r["model"]) for r in rows]
    diff = [b - m for b, m in zip(be, me, strict=True)]  # >0: model better
    rng = random.Random(SEED)
    means = []
    for _ in range(BOOT):
        s = sum(diff[rng.randrange(n)] for _ in range(n)) / n
        means.append(s)
    means.sort()
    lo, hi = means[int(0.025 * BOOT)], means[int(0.975 * BOOT) - 1]
    rmse = lambda xs: (sum(x * x for x in xs) / len(xs)) ** 0.5  # noqa: E731
    be2 = [r["actual"] - r["baseline"] for r in rows]
    me2 = [r["actual"] - r["model"] for r in rows]
    if n < MIN_EVAL:
        verdict = "INSUFFICIENT_DATA"
    elif lo > 0:
        verdict = "SUPPORTED"
    else:
        verdict = "NOT_SUPPORTED"
    return {
        "n_eval": n,
        "baseline_mae": round(sum(be) / n, 4),
        "model_mae": round(sum(me) / n, 4),
        "baseline_rmse": round(rmse(be2), 4),
        "model_rmse": round(rmse(me2), 4),
        "mae_improvement_mean": round(sum(diff) / n, 4),
        "mae_improvement_ci95": [round(lo, 4), round(hi, 4)],
        "verdict": verdict,
        "rule": f"SUPPORTED iff paired-bootstrap 95% CI of MAE improvement > 0 and n_eval >= {MIN_EVAL}",
    }


def base_rates(games: list[dict]) -> dict:
    q1 = [g["home_periods"][0] + g["away_periods"][0] for g in games]
    n = len(q1)
    dist: dict[int, int] = defaultdict(int)
    for x in q1:
        dist[x] += 1
    mean = sum(q1) / n
    var = sum((x - mean) ** 2 for x in q1) / n
    return {
        "n_games": n,
        "mean": round(mean, 3),
        "sd": round(var**0.5, 3),
        "distribution": {str(k): v for k, v in sorted(dist.items())},
        "p_over": {str(line): round(sum(x > line for x in q1) / n, 4) for line in LINES},
        "caveat": "Whole-sample descriptive frequencies (not as-of). Current 2026 season only; "
        "a quote line must be matched before any over/under comparison is meaningful.",
    }


def build(data_dir: Path, manifest_path: Path, data_commit: str) -> dict:
    manifest = json.loads(manifest_path.read_text())
    games = load_games(data_dir, manifest)
    wf = walk_forward(games)
    return {
        "schema_version": "intel-1.0",
        "sport": "CFB",
        "market_family": "quarter_total",
        "period": "Q1",
        "provenance": {
            "data_branch": "chmoses98/sift-alpha:period-scoring-data",
            "data_commit": data_commit,
            "files_verified": len([k for k in manifest if k.startswith("cfb/")]),
            "result_lag_hours_assumption": RESULT_LAG_HOURS,
            "every_row_is_postgame": True,
        },
        "base_rates": base_rates(games),
        "validation": summarize(wf["rows"]),
        "walk_forward_rows": wf["rows"],
    }


if __name__ == "__main__":  # pragma: no cover
    import sys

    out = build(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
    Path(sys.argv[4]).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: out[k] for k in ("base_rates", "validation")}, indent=1)[:1800])
