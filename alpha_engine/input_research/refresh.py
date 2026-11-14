"""One command that refreshes the whole input-research system from free sources and republishes the dashboard artifacts.

    python -m alpha_engine.input_research.refresh --data-dir DIR [--quick] [--no-download]

Downloads nflverse release files (current-season files are always re-fetched; closed seasons are cached), rebuilds the point-in-time feature tables, re-runs every
research path, rebuilds the catalog/availability/evidence/queue artifacts, and writes a run record that states how many NEW completed games arrived since the last run.
Free sources only; no credentials; no orders; no network access beyond github.com release assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import catalog as C, nfl_features as nf, nfl_game as ng, qb_passing as qp, publish as P, queue as Q

REL = "https://github.com/nflverse/nflverse-data/releases/download"
FIRST = 2010


def _get(url: str, dest: Path, force: bool) -> bool:
    if dest.exists() and not force:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    ctx = None
    try:
        import os
        ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
        ctx = ssl.create_default_context(cafile=ca) if ca else None
    except Exception:
        ctx = None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "sift-alpha-research"}), timeout=180, context=ctx) as r:
            data = r.read()
        dest.write_bytes(data)
        return True
    except Exception as e:  # a missing season file is normal (e.g. 2012 snap counts)
        print(f"  skip {url}: {e}", file=sys.stderr)
        return False


def download(data_dir: Path, current: int) -> None:
    for y in range(FIRST, current + 1):
        f = y >= current - 0
        _get(f"{REL}/pbp/play_by_play_{y}.parquet", data_dir / "pbp" / f"pbp_{y}.parquet", f)
        _get(f"{REL}/injuries/injuries_{y}.csv", data_dir / "inj" / f"inj_{y}.csv", f)
        if y >= 2012:
            _get(f"{REL}/snap_counts/snap_counts_{y}.csv", data_dir / "snaps" / f"snap_{y}.csv", f)
    _get(f"{REL}/players/players.csv", data_dir / "players.csv", True)
    _get(f"{REL}/schedules/games.csv", data_dir / "games.csv", True)


def sha(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def provenance(data_dir: Path) -> dict:
    files = {}
    for p in sorted(list(data_dir.glob("pbp/*.parquet")) + list(data_dir.glob("inj/*.csv")) + list(data_dir.glob("snaps/*.csv")) + [data_dir / "games.csv", data_dir / "players.csv"]):
        if p.exists() and p.stat().st_size > 1000:
            files[str(p.relative_to(data_dir))] = {"bytes": p.stat().st_size, "sha256": sha(p)}
    return {"source": "github.com/nflverse/nflverse-data release assets (free; licence terms are those published by nflverse and have not been independently verified here)", "files": files,
            "files_are_unpinned_latest_release_assets": True, "note": "nflverse can revise released files (stat corrections), so a later refresh may differ; the per-file sha256 values identify exactly which bytes produced these results.",
            "diagnostics": dict(nf.DIAGNOSTICS)}


def previous_n_completed() -> int | None:
    f = P.OUT / "run_log.json"
    if f.exists():
        try:
            return json.loads(f.read_text())["runs"][-1]["completed_games_in_table"]
        except Exception:
            return None
    return None


def run(data_dir: Path, quick: bool = False, no_download: bool = False, n_boot: int | None = None) -> dict:
    now = datetime.now(timezone.utc)
    current = now.year if now.month >= 8 else now.year - 1
    if not no_download:
        download(data_dir, current)
    gm = nf.build_game_table(data_dir)
    gm = nf.market_columns(nf.add_matchup_features(gm))
    done = gm[gm["result"].notna()]
    n_boot = n_boot or (400 if quick else 2000)
    res = ng.run_all(gm, n_boot=n_boot, quick=quick)
    pbp = nf.load_pbp(data_dir / "pbp", range(FIRST, int(gm["season"].max()) + 1))
    qb = qp.build_qb_table(gm, pbp)
    qres = qp.run(qb, n_boot=n_boot, quick=quick)
    prov = provenance(data_dir)
    latest = done.sort_values("gameday").iloc[-1]
    vintage = {"generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "retrieved_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "latest_completed_game": f"{latest['gameday']} {latest['game_id']}",
               "completed_games_in_table": int(len(done)), "seasons": [int(gm["season"].min()), int(gm["season"].max())], "provenance_files": len(prov["files"]),
               "provenance_sha256_of_manifest": hashlib.sha256(json.dumps(prov, sort_keys=True).encode()).hexdigest()}
    nfl_labels = {**ng.LABELS}
    src = "nflverse play_by_play + games(lines, weather, rest, QB ids) + injuries + snap_counts + players (free; github.com/nflverse/nflverse-data release assets)"
    mkt = ("nflverse schedule-file consensus line / de-vigged price. Documented only as a near-close sportsbook line (exact timestamp undocumented, so not a point-in-time price at any horizon). "
           "It is not a Kalshi price; no spread, fees or depth")
    boundary_mkt = ("This tests whether pregame inputs add information beyond a near-close sportsbook line. It does NOT show, and nothing here implies, an edge over Kalshi prices: "
                    "no Kalshi price, spread, fee, depth or fill is involved, and the line's exact timing is unknown.")
    boundary_qb = ("The benchmark is the QB's own historical rate, NOT a market. A demonstrated gain means these inputs predict yardage better than a naive history average; "
                   "it says nothing about whether any passing-yards price (Kalshi or otherwise) is wrong. Game-script inputs come from near-close game lines.")
    paths = {
        "nfl_total_vs_close": {"sport": "NFL", "archetype": "game_total", "evidenced_families": ["NFL/TOTAL"], "level": "L2_TESTED_VS_MARKET", "title": "NFL game total vs the near-close sportsbook total",
                               "benchmark": mkt, "claim_boundary": boundary_mkt, "data_source": src, "scope_note": "Game total only. Team totals, halves, quarters, BTTS-style markets inherit the inputs but were NOT tested.",
                               "result": P.compact_continuous(res["total"], {}, nfl_labels, ng.links_for, {"B0": "near-close total line", "B1": "near-close total + past mean residual"}, ng.PARTIAL_PIT)},
        "nfl_spread_vs_close": {"sport": "NFL", "archetype": "game_moneyline_spread", "evidenced_families": ["NFL/SPREAD"], "level": "L2_TESTED_VS_MARKET", "title": "NFL point spread vs the near-close sportsbook spread",
                                "benchmark": mkt, "claim_boundary": boundary_mkt, "data_source": src, "scope_note": "Spread (home margin) only. Win-margin buckets were NOT tested.",
                                "result": P.compact_continuous(res["spread"], {}, nfl_labels, ng.links_for, {"B0": "near-close spread", "B1": "near-close spread + past mean residual"}, ng.PARTIAL_PIT)},
        "nfl_moneyline_vs_close": {"sport": "NFL", "archetype": "game_moneyline_spread", "evidenced_families": ["NFL/GAME_WINNER"], "level": "L2_TESTED_VS_MARKET", "title": "NFL game winner vs the de-vigged near-close moneyline",
                                   "benchmark": mkt, "claim_boundary": boundary_mkt, "data_source": src,
                                   "scope_note": "Home-win probability; scored by log loss/Brier against the de-vigged line (and a recalibrated line, the fairer competitor).",
                                   "result": P.compact_moneyline(res["moneyline"], nfl_labels, ng.links_for, ng.PARTIAL_PIT)},
        "nfl_qb_passing_yards_vs_history": {"sport": "NFL", "archetype": "qb_passing_yards", "evidenced_families": ["NFL/PLAYER_STAT"], "level": "L1_TESTED_VS_BASELINE", "title": "NFL QB passing yards vs the QB's own historical rate",
                                            "benchmark": "NO MARKET: the benchmark is the QB's own shrunk recency-weighted passing yards per game. Historical prop lines are unavailable free, so this is a research lead only.",
                                            "claim_boundary": boundary_qb, "data_source": src, "sample_note": qres.get("sample_note"),
                                            "scope_note": "QB1 passing yards only (>=12 dropbacks). Rushing/receiving/TD props inherit inputs but were NOT tested. Coverage-shell, time-to-throw and route data were NOT available free and are untested.",
                                            "result": P.compact_continuous(qres, {}, qp.QB_LABELS, lambda c: qp.FEATURE_CATALOG.get(c, []), {"B0": "QB historical rate (N1)", "B1": "N1 + past mean residual"}, qp.PARTIAL_PIT)},
    }
    built = P.build_all(paths, vintage)
    docs = built["docs"]
    cats = {s: C.load(s) for s in docs}
    q = Q.build(docs, cats)
    q["generated_utc"] = vintage["generated_utc"]
    P.write(q, "queue.json")
    log_f = P.OUT / "run_log.json"
    prev = json.loads(log_f.read_text()) if log_f.exists() else {"runs": []}
    new_games = (vintage["completed_games_in_table"] - prev["runs"][-1]["completed_games_in_table"]) if prev["runs"] else None   # None = first run
    prev["runs"].append({**{k: vintage[k] for k in ("generated_utc", "latest_completed_game", "completed_games_in_table", "provenance_sha256_of_manifest")}, "new_completed_games_since_previous_run": new_games,
                         "paths": {k: {"n_test_rows": v["result"]["n_test_rows"], "headline": (v["result"]["headline_models"].get("ridge_all") or v["result"]["headline_models"].get("logit_all"))["verdict"]} for k, v in paths.items()}})
    prev["runs"] = prev["runs"][-50:]
    P.write(prev, "run_log.json")
    P.write({"provenance": prov}, "provenance.json")
    return {"vintage": vintage, "paths": {k: v["result"]["headline_models"] for k, v in paths.items()}}


if __name__ == "__main__":
    from .phase import assert_predictive_allowed; assert_predictive_allowed('refresh')
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--n-boot", type=int)
    a = ap.parse_args()
    out = run(Path(a.data_dir), a.quick, a.no_download, a.n_boot)
    print(json.dumps(out["vintage"], indent=1))
