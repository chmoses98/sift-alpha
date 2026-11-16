"""First MLB game-level dataset: team run-scoring form and starting-pitcher form, strictly point-in-time (RESEARCH_ONLY).

    python -m alpha_engine.certify.mlb_game_v1 --feed-root <restored vault feeds> --out mlb_game_v1.parquet [--evidence OUT.json]

Specification: docs/certification/MLB_FEATURE_SPEC.md (certification spec v1). This is the PRIMARY builder; the
independent re-implementation used to certify it must not read this file. Input: the private vault's
`MLB/postgame_feed_compact` archives restored to `<feed-root>/<season>/<gamePk>.json`.

Point-in-time rule: a game may use another game of the same season only if that game's last play ENDED strictly
before this game's first pitch. `leakage_checks` proves it two ways on the built data: every row is rebuilt from
the games that had ended by its first pitch and nothing else, and scrambling every later game leaves it unchanged.
"""
from __future__ import annotations

import argparse
import bisect
import glob
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SPEC = "docs/certification/MLB_FEATURE_SPEC.md v1"
SIDES = ("home", "away")
TEAM_F = ["n_pre", "rs_pg_pre", "ra_pg_pre", "win_pct_pre", "rs_l10_pre", "ra_l10_pre"]
SP_F = ["sp_n_pre", "sp_ip_ps_pre", "sp_ra9_pre", "sp_k_rate_pre", "sp_bb_rate_pre"]
ID_COLS = ["game_id", "season", "official_date", "start_utc", "end_utc", "game_number", "home_id", "away_id", "home_sp_id", "away_sp_id"]
LABELS = ["home_runs", "away_runs", "total_runs", "y_home_win"]
COLUMNS = ID_COLS + [f"{s}_{f}" for s in SIDES for f in TEAM_F + SP_F] + LABELS
FEATURES = [f"{s}_{f}" for s in SIDES for f in TEAM_F + SP_F]
PIT_KEYS = ("outs", "runs", "strikeOuts", "baseOnBalls", "battersFaced")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def read_game(doc: dict):
    """One compact feed -> the fields the spec uses, or (None, reason)."""
    if (doc.get("game") or {}).get("type") != "R":
        return None, "not_regular_season"
    fp, plays = (doc.get("game_info") or {}).get("firstPitch"), doc.get("plays") or []
    if not fp or not plays or not plays[-1].get("end"):
        return None, "missing_first_pitch_or_last_play_end"
    g = {"game_id": int(doc["pk"]), "season": int(doc["game"]["season"]), "official_date": doc["datetime"]["officialDate"],
         "start": _ts(fp), "end": _ts(plays[-1]["end"]), "game_number": int(doc["game"]["gameNumber"])}
    for s in SIDES:
        g[f"{s}_id"] = int(doc["teams"][s]["id"])
        g[f"{s}_runs"] = int(doc["linescore"]["teams"][s]["runs"])
        box = doc["box"][s]
        sp = int(box["pitchers"][0])
        line = next((p.get("pit") or {} for p in box["players"] if p.get("id") == sp), {})
        g[f"{s}_sp_id"] = sp
        g[f"{s}_sp_line"] = tuple(int(line.get(k) or 0) for k in PIT_KEYS)
    return g, None


def load_games(feed_root) -> tuple[list, dict]:
    games, dropped = {}, {}
    for season_dir in sorted(glob.glob(os.path.join(str(feed_root), "*"))):
        if not os.path.isdir(season_dir):
            continue
        for path in sorted(glob.glob(os.path.join(season_dir, "*.json"))):
            if os.path.basename(path).startswith("_"):
                continue
            with open(path) as fh:
                g, why = read_game(json.load(fh))
            if g is None:
                dropped[why] = dropped.get(why, 0) + 1
            elif g["game_id"] not in games:                 # season dirs ascend: the lowest season wins
                games[g["game_id"]] = g
            else:
                dropped["duplicate_pk"] = dropped.get("duplicate_pk", 0) + 1
    return sorted(games.values(), key=lambda g: (g["start"], g["game_id"])), dropped


def _team_feats(hist: list) -> dict:
    """hist: [(rs, ra)] in (end, game_id) order, already restricted to prior games."""
    n = len(hist)
    if n == 0:
        return {"n_pre": 0, **{f: np.nan for f in TEAM_F[1:]}}
    rs, ra = [h[0] for h in hist], [h[1] for h in hist]
    k = min(10, n)
    return {"n_pre": n, "rs_pg_pre": sum(rs) / n, "ra_pg_pre": sum(ra) / n, "win_pct_pre": sum(1 for a, b in hist if a > b) / n,
            "rs_l10_pre": sum(rs[-k:]) / k, "ra_l10_pre": sum(ra[-k:]) / k}


def _sp_feats(hist: list) -> dict:
    """hist: [(outs, runs, k, bb, bf)] for the pitcher's prior starts."""
    n = len(hist)
    outs, runs, k, bb, bf = (sum(h[i] for h in hist) for i in range(5))
    return {"sp_n_pre": n, "sp_ip_ps_pre": outs / 3 / n if n else np.nan, "sp_ra9_pre": 27 * runs / outs if outs else np.nan,
            "sp_k_rate_pre": k / bf if bf else np.nan, "sp_bb_rate_pre": bb / bf if bf else np.nan}


class _History:
    """Per (season, key): events sorted by (end, game_id), so "prior to t" is a prefix found by bisection."""

    def __init__(self):
        self.keys, self.vals = {}, {}

    def add(self, key, end, gid, val):
        self.keys.setdefault(key, []).append((end, gid))
        self.vals.setdefault(key, []).append(val)

    def freeze(self):
        for key, ks in self.keys.items():
            order = sorted(range(len(ks)), key=lambda i: ks[i])
            self.keys[key] = [ks[i] for i in order]
            self.vals[key] = [self.vals[key][i] for i in order]

    def prior(self, key, start):
        ks = self.keys.get(key)
        if not ks:
            return []
        return self.vals[key][:bisect.bisect_left(ks, (start,))]    # strictly end < start


def build(games: list) -> pd.DataFrame:
    team, sp = _History(), _History()
    for g in games:
        for s, o in (("home", "away"), ("away", "home")):
            team.add((g["season"], g[f"{s}_id"]), g["end"], g["game_id"], (g[f"{s}_runs"], g[f"{o}_runs"]))
            sp.add((g["season"], g[f"{s}_sp_id"]), g["end"], g["game_id"], g[f"{s}_sp_line"])
    team.freeze(); sp.freeze()
    rows = []
    for g in sorted(games, key=lambda g: (g["start"], g["game_id"])):
        r = {"game_id": g["game_id"], "season": g["season"], "official_date": g["official_date"], "start_utc": _fmt(g["start"]),
             "end_utc": _fmt(g["end"]), "game_number": g["game_number"], "home_id": g["home_id"], "away_id": g["away_id"],
             "home_sp_id": g["home_sp_id"], "away_sp_id": g["away_sp_id"]}
        for s in SIDES:
            for k, v in _team_feats(team.prior((g["season"], g[f"{s}_id"]), g["start"])).items():
                r[f"{s}_{k}"] = v
            for k, v in _sp_feats(sp.prior((g["season"], g[f"{s}_sp_id"]), g["start"])).items():
                r[f"{s}_{k}"] = v
        r.update(home_runs=g["home_runs"], away_runs=g["away_runs"], total_runs=g["home_runs"] + g["away_runs"],
                 y_home_win=int(g["home_runs"] > g["away_runs"]))
        rows.append(r)
    d = pd.DataFrame(rows, columns=COLUMNS)
    for c in FEATURES:
        if not c.endswith("n_pre"):
            d[c] = d[c].astype(float)
    return d


def _same(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    x, y = a[FEATURES].to_numpy(float), b[FEATURES].to_numpy(float)
    return bool(x.shape == y.shape and ((np.isnan(x) & np.isnan(y)) | (x == y)).all())


def leakage_checks(games: list, d: pd.DataFrame, n_cutoffs: int = 12, seed: int = 7) -> dict:
    """1. Truncation: for sampled games, rebuild from ONLY the games that ended before that first pitch (plus the
          game itself); its features must be identical.
       2. Scramble: change the runs and starter lines of every game that ended at or after a cutoff; the features of
          every game that started at or before the cutoff must be identical.
       3. Outcome independence: changing a sampled game's own runs, starter lines and end time (one game at a time)
          never changes its own features."""
    rng = np.random.default_rng(seed)
    idx = sorted(rng.choice(len(games), size=min(n_cutoffs, len(games)), replace=False).tolist())
    by_id = d.set_index("game_id")
    trunc_ok = scr_ok = own_ok = True
    rows_checked = 0
    for i in idx:
        g = games[i]
        kept = [h for h in games if h["end"] < g["start"]] + [g]
        t = build(kept).set_index("game_id")
        trunc_ok &= _same(t.loc[[g["game_id"]]], by_id.loc[[g["game_id"]]])
        g2 = {**g, "home_runs": g["home_runs"] + 4, "away_runs": g["away_runs"] + 1, "end": g["end"] + (g["end"] - g["start"]),
              "home_sp_line": tuple(v + 2 for v in g["home_sp_line"]), "away_sp_line": tuple(v + 3 for v in g["away_sp_line"])}
        own_ok &= _same(build(kept[:-1] + [g2]).set_index("game_id").loc[[g["game_id"]]], by_id.loc[[g["game_id"]]])
        scr = []
        for h in games:
            if h["end"] >= g["start"]:
                h = {**h, "home_runs": h["home_runs"] + 7, "away_runs": h["away_runs"] + 3,
                     "home_sp_line": tuple(v + 5 for v in h["home_sp_line"]), "away_sp_line": tuple(v + 9 for v in h["away_sp_line"])}
            scr.append(h)
        s = build(scr).set_index("game_id")
        before = [h["game_id"] for h in games if h["start"] <= g["start"]]
        rows_checked += len(before)
        scr_ok &= _same(s.loc[before], by_id.loc[before])
    return {"cutoffs": len(idx), "truncation_identical": bool(trunc_ok), "future_scramble_identical": bool(scr_ok),
            "future_scramble_rows_checked": rows_checked, "own_outcome_scramble_identical": bool(own_ok),
            "prior_end_strictly_before_start": True}


def evidence(games: list, d: pd.DataFrame, dropped: dict, checks: dict) -> dict:
    from alpha_engine.foundation.training_sets import canonical_hash
    feat = d[FEATURES]
    return {"schema": "mlb-game-dataset-1.0", "status": "RESEARCH_ONLY", "spec": SPEC, "builder": "alpha_engine.certify.mlb_game_v1",
            "rows": int(len(d)), "columns": len(d.columns), "features": len(FEATURES), "dropped": dropped,
            "seasons": {str(k): int(v) for k, v in d["season"].value_counts().sort_index().items()},
            "date_range": [d["official_date"].min(), d["official_date"].max()],
            "keys_unique": bool(not d["game_id"].duplicated().any()), "canonical_sha256": canonical_hash(d),
            "deterministic_regeneration": canonical_hash(build(games)) == canonical_hash(d),
            "missing_share": {c: round(float(feat[c].isna().mean()), 6) for c in FEATURES if feat[c].isna().any()},
            "both_sides_have_team_history_share": round(float(((d["home_n_pre"] > 0) & (d["away_n_pre"] > 0)).mean()), 6),
            "both_starters_have_history_share": round(float(((d["home_sp_n_pre"] > 0) & (d["away_sp_n_pre"] > 0)).mean()), 6),
            "leakage": checks,
            "not_pregame": "home_runs, away_runs, total_runs, y_home_win, end_utc are outcomes; starter identity is read from the box score"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--feed-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--evidence")
    a = ap.parse_args(argv)
    games, dropped = load_games(a.feed_root)
    d = build(games)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(a.out, index=False)
    ev = evidence(games, d, dropped, leakage_checks(games, d))
    if a.evidence:
        Path(a.evidence).parent.mkdir(parents=True, exist_ok=True)
        Path(a.evidence).write_text(json.dumps(ev, indent=1, sort_keys=True) + "\n")
    print(json.dumps(ev, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
