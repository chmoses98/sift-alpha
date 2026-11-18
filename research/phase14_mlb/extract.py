"""Phase 14 MLB: compact play-by-play extraction from vault `postgame_feed_compact` (MLB Stats API).

Writes (to a scratch dir, never committed):
  games.parquet   one row per final MLB game (R + postseason): date, start, teams, venue, score, starters, batting orders
  pa.parquet      one row per plate appearance: batter/pitcher/hands/outcome class + base-out transition (innings 1-9)
  bat.parquet     starting-lineup batter lines (H, TB, HR, PA) per game
  sp.parquet      starting pitcher lines (K, BF, outs) per game
Outcome classes: 0 K, 1 BB(+IBB), 2 HBP, 3 1B, 4 2B, 5 3B, 6 HR, 7 OUT (all other PA-ending events incl. ROE/CI).
Non-PA plays (caught stealing, pickoffs) are folded into the preceding PA's base-out transition.
"""
from __future__ import annotations

import json
import os
import sys
from multiprocessing import Pool

import pandas as pd

OUTCOMES = ["K", "BB", "HBP", "1B", "2B", "3B", "HR", "OUT"]
NON_PA = ("caught_stealing", "pickoff", "stolen_base", "wild_pitch", "passed_ball", "balk", "other_advance",
          "runner_double_play", "defensive_indiff", "error")  # 'error' alone = runner event; field_error is a PA
EV = {"strikeout": 0, "strikeout_double_play": 0, "strikeout_triple_play": 0, "walk": 1, "intent_walk": 1,
      "hit_by_pitch": 2, "single": 3, "double": 4, "triple": 5, "home_run": 6}
GAME_TYPES = {"R", "F", "D", "L", "W"}
BASE_BIT = {"1B": 1, "2B": 2, "3B": 4}


def is_pa(event: str) -> bool:
    if event in EV:
        return True
    return not any(event.startswith(p) for p in NON_PA)


def parse_game(path: str):
    d = json.load(open(path))
    if d["game"]["type"] not in GAME_TYPES or d["status"]["codedGameState"] != "F":
        return None
    pk = d["pk"]
    date = d["datetime"]["officialDate"]
    lt = d["linescore"]["teams"]
    box = d["box"]
    g = dict(game_pk=pk, season=int(d["game"]["season"]), gtype=d["game"]["type"], date=date,
             start_utc=d["datetime"]["dateTime"], home_id=d["teams"]["home"]["id"], away_id=d["teams"]["away"]["id"],
             venue_id=d["venue"]["id"], home_runs=lt["home"]["runs"], away_runs=lt["away"]["runs"],
             n_inn=len(d["linescore"]["innings"]),
             prob_home=(d.get("probables") or {}).get("home"), prob_away=(d.get("probables") or {}).get("away"))
    hands = {int(k): v for k, v in d["players"].items()}  # id -> [name, pos, bats, throws]
    bats, sps = [], []
    for side in ("home", "away"):
        b = box[side]
        # STARTING lineup by slot (order "X00"); box `batting_order` holds the end-of-game occupant of each slot
        # (pinch hitters / defensive subs), i.e. post-game information, so it must not be used.
        starters = sorted((int(p["order"]), p["id"]) for p in b["players"] if p.get("order") and p["order"].endswith("00"))
        g[f"{side}_order"] = [pid for _, pid in starters]
        g[f"{side}_sp"] = b["pitchers"][0] if b["pitchers"] else None
        team = d["teams"][side]["id"]
        for p in b["players"]:
            o = p.get("order")
            if o and o.endswith("00") and p.get("bat"):
                s = p["bat"]
                h, d2, t3, hr = s["hits"], s["doubles"], s["triples"], s["homeRuns"]
                bats.append(dict(game_pk=pk, date=date, team_id=team, side=side, player=p["id"], slot=int(o[0]),
                                 H=h, TB=h + d2 + 2 * t3 + 3 * hr, HR=hr, PA=s["plateAppearances"]))
            if p["id"] == g[f"{side}_sp"] and p.get("pit"):
                s = p["pit"]
                sps.append(dict(game_pk=pk, date=date, team_id=team, side=side, player=p["id"], K=s["strikeOuts"],
                                BF=s["battersFaced"], outs=s["outs"]))
    g["bats_home"] = [hands.get(x, ["", "", "R", "R"])[2] for x in g["home_order"]]
    g["bats_away"] = [hands.get(x, ["", "", "R", "R"])[2] for x in g["away_order"]]
    g["thr_home_sp"] = hands.get(g["home_sp"], ["", "", "R", "R"])[3]
    g["thr_away_sp"] = hands.get(g["away_sp"], ["", "", "R", "R"])[3]
    pas = []
    plays = d["plays"]
    sp = {"top": g["home_sp"], "bottom": g["away_sp"]}  # pitcher of record for defense
    i = 0
    cur_half = None
    bases, outs, score = {}, 0, (0, 0)
    for p in plays:
        half = (p["inn"], p["half"])
        if half != cur_half:
            cur_half, bases, outs = half, {}, 0
        pre_state = sum(BASE_BIT[b] for b in set(bases.values()))
        pre_outs, pre_score = outs, score
        for r in p.get("runners") or []:
            rid = r["id"]
            end = r.get("end")
            if r.get("out") or end == "score":
                bases.pop(rid, None)
            elif end in BASE_BIT:
                bases[rid] = end
        outs = p["outs"]
        score = (p["away"], p["home"])
        if outs >= 3:
            bases = {}
        ev = p["event"]
        runs = (score[0] - pre_score[0]) if p["half"] == "top" else (score[1] - pre_score[1])
        post_state = sum(BASE_BIT[b] for b in set(bases.values()))
        if is_pa(ev):
            pas.append(dict(game_pk=pk, date=date, inn=p["inn"], top=p["half"] == "top", bat=p["bat"], pit=p["pit"],
                            stand=p["stand"], throws=p["throws"], ev=EV.get(ev, 7), pre_base=pre_state,
                            pre_outs=min(pre_outs, 2), post_base=post_state, outs_add=min(outs, 3) - pre_outs,
                            runs=runs, is_sp=p["pit"] == sp[p["half"]]))
        elif pas and pas[-1]["game_pk"] == pk and pas[-1]["inn"] == p["inn"] and pas[-1]["top"] == (p["half"] == "top"):
            last = pas[-1]  # fold base-running play into preceding PA transition
            last["post_base"] = post_state
            last["outs_add"] = min(outs, 3) - last["pre_outs"]
            last["runs"] += runs
    for a in pas:
        a["bat_team"] = g["away_id"] if a["top"] else g["home_id"]
        a["pit_team"] = g["home_id"] if a["top"] else g["away_id"]
    return g, pas, bats, sps


def extract(src_root: str, out_dir: str, seasons=(2022, 2023, 2024, 2025, 2026), procs: int = 4):
    os.makedirs(out_dir, exist_ok=True)
    files = [os.path.join(src_root, str(y), f) for y in seasons for f in sorted(os.listdir(os.path.join(src_root, str(y))))
             if f[0].isdigit() and f.endswith(".json")]
    with Pool(procs) as pool:
        res = [r for r in pool.imap(parse_game, files, chunksize=32) if r]
    G = pd.DataFrame([r[0] for r in res]).sort_values(["start_utc", "game_pk"]).reset_index(drop=True)
    PA = pd.DataFrame([a for r in res for a in r[1]])
    PA = PA[PA.inn <= 30].reset_index(drop=True)
    B = pd.DataFrame([a for r in res for a in r[2]])
    S = pd.DataFrame([a for r in res for a in r[3]])
    G.to_parquet(os.path.join(out_dir, "games.parquet"))
    PA.to_parquet(os.path.join(out_dir, "pa.parquet"))
    B.to_parquet(os.path.join(out_dir, "bat.parquet"))
    S.to_parquet(os.path.join(out_dir, "sp.parquet"))
    return len(G), len(PA)


if __name__ == "__main__":
    print(extract(sys.argv[1], sys.argv[2]))
