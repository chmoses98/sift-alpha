"""Collect MLB pitch-level events from the public Stats API game feed (RESEARCH_ONLY, read-only GET, $0; scratch output, nothing committed).

    python -m alpha_engine.input_research.data_foundation.mlb_pitch_collect SCHEDULE.csv.gz OUT_DIR 2021 2022 ... [--workers 4]

Source: statsapi.mlb.com /api/v1.1/game/{gamePk}/feed/live, the endpoint the owner's own workflows already use; terms of the unofficial API are NOT verified (recorded as TERMS_UNVERIFIED in the evidence), so
the output is research scratch only. Polite: few workers, retry with backoff, resumable per game. Game list comes from the owner's committed schedule archive (final regular-season games only). One row per pitch.
"""
from __future__ import annotations

import concurrent.futures as cf
import sys
import time
from pathlib import Path

import pandas as pd
import requests

URL = "https://statsapi.mlb.com/api/v1.1/game/{}/feed/live"


def _pitches(pk: int, d: dict) -> list[dict]:
    rows = []
    for ab in (d.get("liveData") or {}).get("plays", {}).get("allPlays", []):
        a = ab.get("about", {}); m = ab.get("matchup", {}); r = ab.get("result", {})
        for i, ev in enumerate(ab.get("playEvents", [])):
            if not ev.get("isPitch"): continue
            det = ev.get("details", {}); pd_ = ev.get("pitchData", {}) or {}; co = pd_.get("coordinates", {}) or {}; br = pd_.get("breaks", {}) or {}; hd = ev.get("hitData", {}) or {}; c = ev.get("count", {})
            rows.append({"game_pk": pk, "ab": a.get("atBatIndex"), "n": ev.get("pitchNumber"), "inning": a.get("inning"), "top": a.get("isTopInning"), "pitcher": (m.get("pitcher") or {}).get("id"), "batter": (m.get("batter") or {}).get("id"),
                         "p_hand": (m.get("pitchHand") or {}).get("code"), "b_side": (m.get("batSide") or {}).get("code"), "type": (det.get("type") or {}).get("code"), "call": (det.get("call") or {}).get("code"),
                         "is_strike": det.get("isStrike"), "is_ball": det.get("isBall"), "in_play": det.get("isInPlay"), "balls": c.get("balls"), "strikes": c.get("strikes"), "speed": pd_.get("startSpeed"), "spin": br.get("spinRate"),
                         "zone": pd_.get("zone"), "px": co.get("pX"), "pz": co.get("pZ"), "ev": hd.get("launchSpeed"), "la": hd.get("launchAngle"), "dist": hd.get("totalDistance"), "result": r.get("eventType") if i == len(ab["playEvents"]) - 1 or True else None,
                         "last_pitch_of_pa": i == max(j for j, e in enumerate(ab["playEvents"]) if e.get("isPitch"))})
    return rows


def fetch(pk: int, tries: int = 4):
    for k in range(tries):
        try:
            r = requests.get(URL.format(pk), timeout=90)
            if r.status_code == 200: return pk, _pitches(pk, r.json())
            if r.status_code in (404, 400): return pk, []
        except requests.RequestException:
            pass
        time.sleep(2 ** k)
    return pk, None


def main(a=None) -> int:
    a = a or sys.argv[1:]; w = int(a[a.index("--workers") + 1]) if "--workers" in a else 4
    pos = [x for x in a if not x.startswith("--") and (a.index(x) == 0 or a[a.index(x) - 1] != "--workers")]
    sched, out, years = pos[0], Path(pos[1]), [int(y) for y in pos[2:]]; out.mkdir(parents=True, exist_ok=True)
    g = pd.read_csv(sched)
    for y in years:
        f = out / f"pitches_{y}.parquet"
        if f.exists(): continue
        ids = g[(g.season == y) & g.home_score.notna()].game_pk.astype(int).tolist(); rows = []; fail = []
        with cf.ThreadPoolExecutor(w) as ex:
            for pk, r in ex.map(fetch, ids):
                (fail.append(pk) if r is None else rows.extend(r))
        pd.DataFrame(rows).to_parquet(f); print(y, len(ids), "games", len(rows), "pitches", len(fail), "failed", flush=True)
        if fail: (out / f"failed_{y}.txt").write_text("\n".join(map(str, fail)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
