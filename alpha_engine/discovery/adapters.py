"""Sport adapters for the discovery engine: market side-table (scoring only), schedule frame and Kalshi series map (RESEARCH_ONLY).

A market frame is indexed by game_id and NEVER merged into the feature dataset. Its timing is stated per sport in `MARKET_NOTE`; a
"closing" line may contain information that arrived after any realistic decision time, which flatters the market side of a comparison.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _american_to_p(o):
    o = np.asarray(o, float)
    return np.where(o < 0, -o / (-o + 100.0), 100.0 / (o + 100.0))


def devig(home_odds, away_odds):
    ph, pa = _american_to_p(home_odds), _american_to_p(away_odds)
    return ph / (ph + pa)


MARKET_NOTE = {
    "NFL": "nflverse games.csv spread_line / total_line / moneylines: documented only as near-close sportsbook consensus, no quote timestamp. spread_line > 0 = home favoured by that many points (home covers when margin > spread_line, i.e. home at -spread_line).",
    "CFB": "CFBD /lines: per-provider closing spread and over/under without quote timestamps; the median across providers is used. CFBD spread is home-relative with NEGATIVE = home favoured; it is sign-flipped here so that line > 0 = home favoured.",
}


def nfl_market(games_csv) -> pd.DataFrame:
    g = pd.read_csv(games_csv)
    m = pd.DataFrame({"game_id": g.game_id, "spread_line": g.spread_line, "total_line": g.total_line})
    ok = g.home_moneyline.notna() & g.away_moneyline.notna()
    m["p_home_devig"] = np.where(ok, devig(g.home_moneyline.fillna(-110), g.away_moneyline.fillna(-110)), np.nan)
    return m.set_index("game_id")


def nfl_schedule(d: pd.DataFrame, aux=None) -> pd.DataFrame:
    return pd.DataFrame({"game_id": d.game_id, "date": d.gameday.astype(str), "home": d.home_team, "away": d.away_team})


def cfb_market(lines_dir) -> pd.DataFrame:
    """Median closing spread / total across providers from the vault CFBD cache (<season>/lines_{regular,postseason}.json.gz)."""
    import glob, gzip, json
    rows = []
    for f in sorted(glob.glob(str(lines_dir) + "/*/lines_*.json.gz")):
        for g in json.load(gzip.open(f, "rt")):
            sp = [x.get("spread") for x in g.get("lines") or [] if x.get("spread") is not None]
            ou = [x.get("overUnder") for x in g.get("lines") or [] if x.get("overUnder") is not None]
            if sp or ou:
                rows.append({"game_id": str(g["id"]), "spread_line": -float(np.median(sp)) if sp else np.nan, "total_line": float(np.median(ou)) if ou else np.nan, "n_providers": len(g.get("lines") or [])})
    return pd.DataFrame(rows).drop_duplicates("game_id").set_index("game_id")


def nba_schedule(d: pd.DataFrame, aux=None) -> pd.DataFrame:
    """Team abbreviations come from the archived team boxes (aux = archive root); the dataset itself carries ESPN team ids only."""
    import glob
    ab = pd.concat([pd.read_parquet(f, columns=["team_id", "team_abbreviation", "season"]) for f in sorted(glob.glob(str(aux) + "/**/team_box_*.parquet", recursive=True))]).drop_duplicates(["season", "team_id"])
    m = {(int(r.season), int(r.team_id)): r.team_abbreviation for r in ab.itertuples()}
    return pd.DataFrame({"game_id": d.game_id, "date": d.date.astype(str), "home": [m.get((int(s), int(t))) for s, t in zip(d.season, d.home_team_id)],
                         "away": [m.get((int(s), int(t))) for s, t in zip(d.season, d.away_team_id)]})


ADAPTERS = {
    "NFL": {"market": nfl_market, "schedule": nfl_schedule,
            "series": {"KXNFLGAME": "winner", "KXNFLSPREAD": "spread", "KXNFLTOTAL": "total"},
            "family_target": {"winner": ("winner", "margin"), "spread": ("spread", "margin"), "total": ("total", "total")},
            "alias": {"JAX": ["JAC"], "LA": ["LAR"], "WAS": ["WSH"], "LV": ["LVR"], "NE": ["NEP"], "NO": ["NOS"], "SF": ["SFO"], "TB": ["TBB"], "GB": ["GNB"], "KC": ["KAN"]}},
    "NBA": {"market": lambda path: None, "schedule": nba_schedule,
            "series": {"KXNBAGAME": "winner", "KXNBASPREAD": "spread", "KXNBATOTAL": "total"},
            "family_target": {"winner": ("winner", "margin"), "spread": ("spread", "margin"), "total": ("total", "total")},
            "alias": {"GS": ["GSW"], "NO": ["NOP"], "NY": ["NYK"], "SA": ["SAS"], "UTAH": ["UTA"], "WSH": ["WAS"], "PHX": ["PHO"], "BKN": ["BRK"], "CHA": ["CHO"]}},
    "CFB": {"market": cfb_market, "schedule": None, "series": {}, "family_target": {}, "alias": {}},
}
