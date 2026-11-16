"""NFL kickoff-hour weather FORECAST vintages -> point-in-time game features (RESEARCH_ONLY).

Source: nfl-edge-finder `context-capture.yml` archive on its `market-data` branch, `data/context/<date>/<run_id>.weather.jsonl`
(one row per scheduled game per capture run: Open-Meteo hourly forecast and NWS hourly periods within +/-6 h of kickoff, each with
its own HTTP retrieval timestamp). Only the forecast that EXISTED before the cut-off is used:

  vintage(game, lead) = the latest capture whose Open-Meteo retrieval time <= kickoff - lead hours

and the value is the forecast for the kickoff hour (nearest hourly step at or after kickoff, else nearest). Columns (per lead):
  wfc_temp_f, wfc_wind_mph, wfc_gust_mph, wfc_precip_prob, wfc_precip_in, wfc_humidity, wfc_lead_h (actual lead of the vintage used)
  wfc_exposed (1 if the venue is open-air per the schedule's roof field, 0 for dome/closed; retractable roofs are unknown -> NaN)
Nothing is imputed: a game with no vintage before its cut-off is NaN (the capture stalled 2026-10-28 -> 2026-11-15; those games
have stale or no vintages and are reported, not filled). NWS periods are kept as a cross-check only (`nws_temp_f`).
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

OM = {"temperature_2m": "wfc_temp_f", "wind_speed_10m": "wfc_wind_mph", "wind_gusts_10m": "wfc_gust_mph",
      "precipitation_probability": "wfc_precip_prob", "precipitation": "wfc_precip_in", "relative_humidity_2m": "wfc_humidity"}
COLS = list(OM.values()) + ["wfc_lead_h", "wfc_exposed"]
MAX_LEAD_H = 240


def _exposed(roof) -> float:
    r = (roof or "").lower()
    if r in ("outdoors", "open"):
        return 1.0
    if r in ("dome", "closed"):
        return 0.0
    return np.nan


def load_vintages(context_dir) -> pd.DataFrame:
    """One row per (capture run, game) with the kickoff-hour forecast and its retrieval time. Rows without an Open-Meteo forecast are dropped."""
    rows = []
    for f in sorted(glob.glob(str(Path(context_dir) / "*" / "*.weather.jsonl"))):
        for ln in open(f):
            if not ln.strip():
                continue
            r = json.loads(ln)
            om = r.get("open_meteo") or {}; h = om.get("hourly") or {}; meta = om.get("meta") or {}
            times = h.get("time") or []
            if not times or meta.get("status") != 200:
                continue
            k = pd.Timestamp(r["kickoff_utc"]).tz_convert("UTC").tz_localize(None)
            ts = pd.to_datetime(times)
            after = [i for i, t in enumerate(ts) if t >= k]
            i = after[0] if after else int(np.argmin(np.abs((ts - k).total_seconds())))
            rec = {"run_id": r["run_id"], "game_id": r["game_id"], "kickoff_utc": pd.Timestamp(r["kickoff_utc"]).tz_convert("UTC"),
                   "retrieved_at": pd.Timestamp(meta["retrieved_at"]).tz_convert("UTC"), "roof": r.get("roof"), "home_team": r.get("home_team"),
                   "wfc_exposed": _exposed(r.get("roof"))}
            for key, col in OM.items():
                v = (h.get(key) or [None] * len(times))[i]
                rec[col] = np.nan if v is None else float(v)
            if rec["wfc_precip_in"] == rec["wfc_precip_in"]:
                rec["wfc_precip_in"] = rec["wfc_precip_in"] / 25.4          # Open-Meteo precipitation is mm
            per = (r.get("nws") or {}).get("periods") or []
            near = [p for p in per if pd.Timestamp(p["startTime"]).tz_convert("UTC").tz_localize(None) <= k]
            rec["nws_temp_f"] = float(near[-1]["temperature"]) if near and near[-1].get("temperature") is not None else np.nan
            rows.append(rec)
    v = pd.DataFrame(rows)
    if v.empty:
        return v
    v["lead_h"] = (v.kickoff_utc - v.retrieved_at).dt.total_seconds() / 3600.0
    return v.sort_values(["game_id", "retrieved_at", "run_id"], kind="mergesort").reset_index(drop=True)


def at_lead(v: pd.DataFrame, lead_h: float, max_lead_h: float = MAX_LEAD_H) -> pd.DataFrame:
    """Per game: the latest vintage retrieved at least `lead_h` hours before kickoff (and at most max_lead_h)."""
    ok = v[(v.lead_h >= lead_h) & (v.lead_h <= max_lead_h)]
    last = ok.groupby("game_id", sort=False).tail(1).copy()
    last["wfc_lead_h"] = last.lead_h.round(2)
    return last[["game_id", "kickoff_utc", "retrieved_at", "run_id"] + COLS + ["nws_temp_f"]].reset_index(drop=True)


def validate_against_observed(fc: pd.DataFrame, games: pd.DataFrame) -> dict:
    """Forecast vs the schedule's observed game temp/wind (open-air games with both). An independent sanity check, not a feature."""
    j = fc.merge(games[["game_id", "temp", "wind", "roof"]], on="game_id", how="inner")
    j = j[(j.wfc_exposed == 1) & j.temp.notna() & j.wind.notna()]
    if j.empty:
        return {"n": 0}
    return {"n": int(len(j)), "temp_corr": round(float(np.corrcoef(j.wfc_temp_f, j.temp)[0, 1]), 3), "temp_mae_f": round(float((j.wfc_temp_f - j.temp).abs().mean()), 2),
            "wind_corr": round(float(np.corrcoef(j.wfc_wind_mph, j.wind)[0, 1]), 3), "wind_mae_mph": round(float((j.wfc_wind_mph - j.wind).abs().mean()), 2)}
