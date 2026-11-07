"""Roof-aware weather availability + observed-conditions repair (RESEARCH_ONLY).

Weather columns are NOT expected for games indoors (roof dome/closed): NaN there is by design and is never counted as missing.  For outdoor/open games, a missing temp/wind is
a real gap and is filled ONLY from a documented source: the nflverse play-by-play `weather` text (e.g. "Cloudy Temp: 80° F, Humidity: 81%, Wind: NE 8 mph").
Both sources are OBSERVED, game-time records -- they describe the game after it was played and are never presented as a forecast known before kickoff.  A true pre-game forecast
is a separate quantity (`fcst_*` columns, all NaN until a free point-in-time source is secured -- see the repair queue)."""
from __future__ import annotations
import re
from pathlib import Path
import numpy as np
import pandas as pd

INDOOR = {"dome", "closed"}
TEMP = re.compile(r"Temp:\s*(-?\d+)\s*°?\s*F", re.I)
WIND = re.compile(r"Wind:\s*(?:[A-Za-z]+\s+)?(\d+)\s*mph", re.I)


def parse_weather_text(s) -> tuple[float, float]:
    if not isinstance(s, str):
        return np.nan, np.nan
    t, w = TEMP.search(s), WIND.search(s)
    return (float(t.group(1)) if t else np.nan, float(w.group(1)) if w else np.nan)


def pbp_weather(pbp_dir: Path, seasons) -> pd.DataFrame:
    fr = []
    for s in seasons:
        f = Path(pbp_dir) / f"pbp_{s}.parquet"
        if f.exists():
            d = pd.read_parquet(f, columns=["game_id", "weather"]).dropna(subset=["weather"]).drop_duplicates("game_id")
            fr.append(d)
    d = pd.concat(fr, ignore_index=True) if fr else pd.DataFrame(columns=["game_id", "weather"])
    tw = d["weather"].map(parse_weather_text)
    d["temp_pbp"] = [a for a, _ in tw]; d["wind_pbp"] = [b for _, b in tw]
    return d[["game_id", "temp_pbp", "wind_pbp"]]


def repair_observed(games: pd.DataFrame, pbp_dir: Path) -> pd.DataFrame:
    g = games.copy()
    g["roof_indoor"] = g["roof"].isin(INDOOR)
    g["weather_expected"] = ~g["roof_indoor"] & g["roof"].notna()
    pw = pbp_weather(pbp_dir, sorted(g["season"].dropna().unique().astype(int)))
    g = g.merge(pw, on="game_id", how="left")
    g["weather_source"] = np.where(g["temp"].notna(), "games_csv_observed", "none")
    fill = g["temp"].isna() & g["weather_expected"] & g["temp_pbp"].notna()
    g.loc[fill, "temp"] = g.loc[fill, "temp_pbp"]
    fillw = g["wind"].isna() & g["weather_expected"] & g["wind_pbp"].notna()
    g.loc[fillw, "wind"] = g.loc[fillw, "wind_pbp"]
    g.loc[fill, "weather_source"] = "pbp_weather_text_observed"
    g["weather_missing_expected"] = g["weather_expected"] & (g["temp"].isna() | g["wind"].isna())
    for c in ("fcst_temp", "fcst_wind"):
        g[c] = np.nan                                  # no pre-game forecast source yet: never substituted by the observed values
    return g.drop(columns=["temp_pbp", "wind_pbp"])


def availability(g: pd.DataFrame) -> dict:
    """Per-season roof-aware availability (denominator = games where weather is expected)."""
    out = {}
    for s, x in g[g["season"] >= 2010].groupby("season"):
        e = x[x["weather_expected"]]
        out[int(s)] = {"games": int(len(x)), "indoor": int(x["roof_indoor"].sum()), "expected": int(len(e)), "temp_wind_avail": round(float((e["temp"].notna() & e["wind"].notna()).mean()), 4) if len(e) else None,
                       "from_pbp_text": int((e["weather_source"] == "pbp_weather_text_observed").sum()), "still_missing": int(e["weather_missing_expected"].sum())}
    return out
