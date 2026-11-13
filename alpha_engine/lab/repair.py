"""Data repairs applied before modelling (RESEARCH_ONLY).

R1  nflverse labels postseason games WC/DIV/CON/SB, never "POST".  #53's build_game_table filters game_type in {REG, POST}, so postseason games were
    silently dropped in EVERY season (not only 2025).  `normalized_data_dir` builds a view of the raw data (symlinks) whose games.csv maps those labels to POST,
    leaving the raw files untouched and the #53 code unchanged.
"""
from __future__ import annotations
import os
from pathlib import Path
import pandas as pd

POST_LABELS = {"WC": "POST", "DIV": "POST", "CON": "POST", "SB": "POST"}


def normalize_games(games: pd.DataFrame) -> pd.DataFrame:
    g = games.copy()
    g["game_type_raw"] = g["game_type"]
    g["game_type"] = g["game_type"].replace(POST_LABELS)
    return g


def normalized_data_dir(raw: Path, view: Path, fill_weather: bool = False) -> Path:
    raw, view = Path(raw), Path(view)
    view.mkdir(parents=True, exist_ok=True)
    for p in raw.iterdir():
        if p.name == "games.csv":
            continue
        t = view / p.name
        if not t.exists():
            os.symlink(p.resolve(), t)
    g = normalize_games(pd.read_csv(raw / "games.csv"))
    if fill_weather:
        from . import weather as W
        g = W.repair_observed(g, raw / "pbp")
    g.to_csv(view / "games.csv", index=False)
    return view
