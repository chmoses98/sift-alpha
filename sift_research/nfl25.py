"""Loaders for the 2025 NFL Kalshi backfill (market-data branch ``data/kalshi/backfill``) joined to nflverse schedule/results.

Roots are arguments/env (``SIFT_NFL_BACKFILL``, ``SIFT_NFLVERSE_GAMES``); nothing is hard-coded to a scratch directory.
Everything returned is point-in-time safe ONLY for the fields documented: ``result``/``scores`` are outcomes (never features).
"""
from __future__ import annotations
import csv, glob, json, os, re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BACKFILL = os.environ.get("SIFT_NFL_BACKFILL", "/home/user/data_nfl_md/data/kalshi/backfill")
GAMES_CSV = os.environ.get("SIFT_NFLVERSE_GAMES", "/home/user/ext/games.csv")
ET = ZoneInfo("America/New_York")
MON = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
K2N = {"JAC": "JAX"}          # Kalshi -> nflverse
FAMILY = {  # series -> family label used in all reports
    "KXNFLGAME": "moneyline", "KXNFLSPREAD": "spread", "KXNFLTOTAL": "total", "KXNFLTEAMTOTAL": "team_total",
    "KXNFL1HWINNER": "1h_winner", "KXNFL1HSPREAD": "1h_spread", "KXNFL1HTOTAL": "1h_total", "KXNFL1HTEAMTOTAL": "1h_team_total",
    "KXNFL2HWINNER": "2h_winner", "KXNFL2HSPREAD": "2h_spread", "KXNFL2HTOTAL": "2h_total",
    "KXNFL1QWINNER": "1q_winner", "KXNFL1QSPREAD": "1q_spread", "KXNFL1QTOTAL": "1q_total",
    "KXNFLWINMARGIN": "win_margin", "KXNFL1HFT": "1h_first_td", "KXNFLBOTH": "both_teams_score", "KXNFLTD": "player_td",
    "KXNFLPASSYDS": "player_pass_yds", "KXNFLRSHYDS": "player_rush_yds", "KXNFLRECYDS": "player_rec_yds",
}


def event_parts(event_ticker: str):
    """'KXNFLGAME-25SEP08MINCHI' -> (series, date, 'MINCHI')."""
    series, rest = event_ticker.split("-", 1)
    yy, mon, dd = int(rest[:2]), MON[rest[2:5]], int(rest[5:7])
    return series, datetime(2000 + yy, mon, dd).date(), rest[7:]


def load_games(path=GAMES_CSV, season=2025):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            if int(r["season"]) != season:
                continue
            day = datetime.strptime(r["gameday"], "%Y-%m-%d")
            hh, mm = r["gametime"].split(":") if r["gametime"] else ("13", "0")
            ko = day.replace(hour=int(hh), minute=int(mm), tzinfo=ET).astimezone(timezone.utc)
            rows.append(dict(game_id=r["game_id"], week=int(r["week"]), game_type=r["game_type"], gameday=r["gameday"], kickoff=ko,
                             away=r["away_team"], home=r["home_team"],
                             away_score=None if r["away_score"] == "" else int(float(r["away_score"])),
                             home_score=None if r["home_score"] == "" else int(float(r["home_score"])),
                             spread_line=r["spread_line"], total_line=r["total_line"]))
    return rows


def game_index(games):
    """(date_str, away, home) -> game, tolerant to Kalshi/nflverse code differences and a UTC date rollover."""
    idx = {}
    for g in games:
        idx[(g["gameday"], g["away"], g["home"])] = g
    return idx


def resolve_event(event_ticker, idx):
    series, d, codes = event_parts(event_ticker)
    for cut in (2, 3):
        a, h = codes[:cut], codes[cut:]
        a, h = K2N.get(a, a), K2N.get(h, h)
        for dd in (d, d - timedelta(days=1), d + timedelta(days=1)):
            g = idx.get((dd.isoformat(), a, h))
            if g:
                return g
    return None


def load_markets(series, root=BACKFILL):
    out = []
    p = os.path.join(root, "markets", series + ".jsonl")
    if not os.path.exists(p):
        return out
    for l in open(p):
        out.append(json.loads(l))
    return out


def outcome_yes(m):
    """1/0 for a finalized yes/no market, else None (scalar, unsettled). Never inferred from prices."""
    return {"yes": 1, "no": 0}.get(m.get("result"))


def load_candles(series, ticker, root=BACKFILL):
    p = os.path.join(root, "candles", series, ticker + ".json")
    return json.load(open(p)) if os.path.exists(p) else None


def load_trades(series, ticker, root=BACKFILL):
    p = os.path.join(root, "trades", series, ticker + ".jsonl")
    if not os.path.exists(p):
        return None
    seen, out = set(), []
    for l in open(p):
        r = json.loads(l)
        if r["trade_id"] in seen:
            continue
        seen.add(r["trade_id"])
        out.append(dict(ts=datetime.fromisoformat(r["created_time"].replace("Z", "+00:00")), yes=float(r["yes_price_dollars"]),
                        no=float(r["no_price_dollars"]), n=float(r["count_fp"]), taker=r["taker_side"], block=bool(r.get("is_block_trade"))))
    out.sort(key=lambda x: x["ts"])
    return out
