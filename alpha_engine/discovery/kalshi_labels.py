"""Official Kalshi results as LABELS for game-line contracts, joined to dataset games (RESEARCH_ONLY).

Reads the vault snapshot of official settlements (one JSON line per market; `<SERIES>.historical.jsonl` / `<SERIES>.live.jsonl`; a market
served by both tiers is kept once). The official result is the label; the score-derived outcome is computed beside it only to report
agreement, never to replace it. Markets whose result is not yes/no (void, fair-price, still open) are counted and excluded.
No price field is read: `last_price_dollars` is a post-event value, not a contemporaneous quote.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
EVT = re.compile(r"^(?P<series>[A-Z0-9]+)-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})(?P<pair>[A-Z0-9]+)$")


def read_official(root: Path, series: dict[str, str]) -> pd.DataFrame:
    """series: {SERIES_TICKER: family}. One row per market ticker."""
    rows = {}
    for s, fam in series.items():
        for tier in ("historical", "live"):
            f = root / f"{s}.{tier}.jsonl"
            if not f.exists():
                continue
            with open(f) as fh:
                for line in fh:
                    m = json.loads(line); e = EVT.match(m.get("event_ticker") or "")
                    if not e:
                        continue
                    suffix = m["ticker"][len(m["event_ticker"]) + 1:]
                    rows[m["ticker"]] = {"ticker": m["ticker"], "event": m["event_ticker"], "family": fam, "pair": e["pair"],
                                         "date": f"20{e['yy']}-{MONTHS[e['mon']]:02d}-{e['dd']}", "suffix": suffix, "strike": m.get("floor_strike"),
                                         "result": m.get("result") or "", "status": m.get("status") or "", "strike_type": m.get("strike_type") or ""}
    return pd.DataFrame(list(rows.values()))


def join_games(off: pd.DataFrame, games: pd.DataFrame, alias: dict[str, list[str]]) -> pd.DataFrame:
    """games: game_id, date (YYYY-MM-DD), home, away. alias: dataset team code -> Kalshi codes (the dataset code itself is always tried).
    An event joins when exactly one game within one day of the ticker date has away+home (or home+away) equal to the ticker pair."""
    codes = lambda t: [t] + alias.get(t, [])
    by_pair = {}
    for g in games.itertuples():
        for a in codes(g.away):
            for h in codes(g.home):
                by_pair.setdefault(a + h, []).append((g.date, g.game_id, a, h)); by_pair.setdefault(h + a, []).append((g.date, g.game_id, a, h))
    ev = off.drop_duplicates("event")[["event", "pair", "date"]]
    m = {}
    for e in ev.itertuples():
        d0 = pd.Timestamp(e.date)
        c = {(gid, a, h) for (gd, gid, a, h) in by_pair.get(e.pair, []) if abs((pd.Timestamp(gd) - d0).days) <= 1}
        if len({x[0] for x in c}) == 1:
            m[e.event] = next(iter(c))
    o = off.copy()
    o["game_id"] = o.event.map(lambda x: m.get(x, (None,))[0]); o["k_away"] = o.event.map(lambda x: m.get(x, (None, None, None))[1]); o["k_home"] = o.event.map(lambda x: m.get(x, (None,) * 3)[2])
    team = o.suffix.str.replace(r"[\d.]+$", "", regex=True)
    o["side"] = np.where(o.game_id.isna(), None, np.where(team == o.k_home, "home", np.where(team == o.k_away, "away", np.where(o.family.str.endswith("total"), "total", None))))
    return o


def yes_probability(o: pd.DataFrame, pred: pd.DataFrame, fam_target: dict[str, tuple[str, str]]) -> pd.DataFrame:
    """Model probability of YES under a normal predictive distribution. fam_target: family -> (kind, target) with kind in winner/spread/total.
    winner: P(side wins) ; spread: P(side wins by more than strike) ; total: P(total > strike). Also the score-derived label where the outcome is known."""
    from scipy.stats import norm
    o = o.merge(pred, on="game_id", how="left"); p = np.full(len(o), np.nan); yd = np.full(len(o), np.nan)
    for fam, (kind, tn) in fam_target.items():
        k = (o.family == fam).to_numpy(); mu = o[f"{tn}_mu"].to_numpy(float); sg = o[f"{tn}_sigma"].to_numpy(float); y = o[f"{tn}_actual"].to_numpy(float)
        x = o.strike.to_numpy(float) if kind != "winner" else np.zeros(len(o))
        sgn = np.where(o.side == "away", -1.0, 1.0)
        if kind == "total":
            pv = 1 - norm.cdf((x - mu) / sg); yv = np.where(np.isnan(y), np.nan, (y > x).astype(float))
        else:
            pv = 1 - norm.cdf((x - sgn * mu) / sg); yv = np.where(np.isnan(y), np.nan, (sgn * y > x).astype(float))
            pv = np.where(o.side.isin(["home", "away"]), pv, np.nan)
        p[k] = pv[k]; yd[k] = yv[k]
    o["p_model"] = p; o["y_derived"] = yd
    o["y_official"] = np.where(o.result == "yes", 1.0, np.where(o.result == "no", 0.0, np.nan))
    return o
