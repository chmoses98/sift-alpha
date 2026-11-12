"""Read-only adapters from existing producer exports into ``sift-alpha-eval/1`` rows. They do not import or modify any
producer engine. Implemented: sift-sports-intelligence ``pure-contract`` ``pure_forecast.v1`` ladders + means."""
from __future__ import annotations

from .schema import SCHEMA_VERSION, SPORTS_ONLY, MARKET_INFORMED


def from_pure_forecast_v1(row: dict, *, sport: str = "", evidence_class: str, model_id: str = "pure_forecast") -> list:
    """One pure_forecast.v1 row -> 1 CONTINUOUS row (mean, quantiles) + one BINARY row per ladder rung P(X >= at_least).
    Rungs share ``group_id`` = game_id so they are clustered, and are tagged LADDER_RUNG so they are never independent.
    Lineage classes other than sports_only mark the model market_informed (conservative)."""
    lineage = row.get("feature_lineage") or []
    mkt = [x.get("name") for x in lineage if x.get("class") != "sports_only"]
    base = dict(schema=SCHEMA_VERSION, sport=(sport or str(row.get("sport", ""))).upper(), event_id=row["game_id"], group_id=row["game_id"], model_id=model_id,
                model_version=row.get("model_version"), model_independence=MARKET_INFORMED if mkt else SPORTS_ONLY,
                market_inputs_used=mkt, frozen_at=row["as_of"], event_start=row["kickoff"], evidence_class=evidence_class,
                native_family=f"player_{row['statistic']}", meta=dict(player_id=row.get("player_id"),
                conditional_on_playing=row.get("conditional_on_playing")))
    mid = f"{row['game_id']}|{row['player_id']}|{row['statistic']}"
    proj = row.get("projection") or {}
    out = []
    qs = {q["q"]: q["value"] for q in proj.get("quantiles", []) if "q" in q and "value" in q}
    for lvl, key in ((0.1, "p10"), (0.5, "median"), (0.9, "p90")):
        if proj.get(key) is not None:
            qs[lvl] = proj[key]
    if "mean" in proj:
        out.append(dict(base, forecast_id=f"{mid}|{row['as_of']}|mean", market_id=mid, scoring_type="CONTINUOUS",
                        payload=dict(mean=proj["mean"], quantiles=qs)))
    for rung in proj.get("thresholds", proj.get("ladder", [])) or []:
        t = rung.get("at_least")
        out.append(dict(base, forecast_id=f"{mid}|{row['as_of']}|ge{t}", market_id=f"{mid}|ge{t}", scoring_type="BINARY",
                        line=t, line_role="LADDER_RUNG", payload=dict(p_yes=rung.get("p_yes", rung.get("probability")))))
    return out
