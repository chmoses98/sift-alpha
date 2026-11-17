"""NBA long-history team-box dataset: efficiency, four factors, rebound pool, Pythagorean residual, rest (RESEARCH_ONLY).

    python -m alpha_engine.features.nba_team_box --root <restored vault NBA archive> --out nba_team_box.parquet [--evidence OUT.json]

Specification: docs/certification/NBA_TEAM_BOX_SPEC.md v1. PRIMARY builder; `certify/nba_team_box_independent.py` was written from
the spec alone. Source: sift-data-vault archives/NBA/espn_pbp_boxes_schedules (ESPN team boxes and schedules 2002-2027).
Every feature of a game uses only same-season games on strictly earlier calendar dates (plus the previous season's final net rating).
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

SPEC = "docs/certification/NBA_TEAM_BOX_SPEC.md v1"
NUM = ["team_score", "opponent_team_score", "field_goals_made", "field_goals_attempted", "three_point_field_goals_made", "three_point_field_goals_attempted",
       "free_throws_made", "free_throws_attempted", "offensive_rebounds", "defensive_rebounds", "turnovers"]
SHORT = dict(zip(NUM, ["PTS", "oPTS_row", "FGM", "FGA", "TPM", "TPA", "FTM", "FTA", "ORB", "DRB", "TOV"]))
TEAM_F = ["n_pre", "off_rtg_pre", "def_rtg_pre", "net_rtg_pre", "pace_pre", "efg_pre", "tov_pre", "orb_pre", "ftr_pre", "d_efg_pre", "d_tov_pre", "d_orb_pre", "d_ftr_pre",
          "three_rate_pre", "miss2_pg_pre", "miss3_pg_pre", "missft_pg_pre", "win_pct_pre", "pyth_pct_pre", "pyth_resid_pre", "close_n_pre", "close_win_pct_pre", "net_l10_pre",
          "rest_days", "b2b", "prev_net_prior"]
MATCH_F = [f"{s}_exp_{f}" for s in ("home", "away") for f in ("efg", "tov", "orb", "ftr")] + ["exp_miss2", "exp_miss3", "exp_missft", "exp_reb_pool", "exp_poss"]
FEATURES = [f"{s}_{f}" for s in ("home", "away") for f in TEAM_F] + MATCH_F
LABELS = ["y_home_margin", "y_total", "y_home_win"]
COLUMNS = ["game_id", "season", "date", "cutoff_utc", "neutral", "home_team_id", "away_team_id"] + [f"{s}_{f}" for s in ("home", "away") for f in TEAM_F] + MATCH_F + LABELS
CATALOG = {
    "nba.four_factors_matchup": ["efg_pre", "tov_pre", "orb_pre", "ftr_pre", "d_efg_pre", "d_tov_pre", "d_orb_pre", "d_ftr_pre", "@home_exp_efg", "@home_exp_tov", "@home_exp_orb", "@home_exp_ftr",
                                 "@away_exp_efg", "@away_exp_tov", "@away_exp_orb", "@away_exp_ftr"],
    "nba.pythag_residual": ["win_pct_pre", "pyth_pct_pre", "pyth_resid_pre", "close_n_pre", "close_win_pct_pre"],
    "nba.rebound_pool": ["miss2_pg_pre", "miss3_pg_pre", "missft_pg_pre", "@exp_miss2", "@exp_miss3", "@exp_missft", "@exp_reb_pool"],
}


def load_raw(root) -> dict:
    tb = pd.concat([pd.read_parquet(f, columns=["game_id", "season", "season_type", "game_date", "team_id", "team_home_away"] + NUM)
                    for f in sorted(glob.glob(str(Path(root) / "**" / "team_box_*.parquet"), recursive=True))], ignore_index=True)
    sc = pd.concat([pd.read_parquet(f, columns=["game_id", "date", "neutral_site"]) for f in sorted(glob.glob(str(Path(root) / "**" / "nba_schedule_*.parquet"), recursive=True))], ignore_index=True)
    return {"team_box": tb, "schedule": sc}


def team_rows(raw: dict) -> tuple[pd.DataFrame, dict]:
    t = raw["team_box"]; drop = {}
    t = t[t.season_type == 2].copy()
    usable = t[NUM].notna().all(axis=1) & (t.field_goals_attempted > 0)
    drop["rows_not_usable"] = int((~usable).sum()); t = t[usable]
    cnt = t.groupby(["season", "team_id"]).game_id.transform("size")
    t["league"] = cnt >= 5
    g = t.groupby("game_id").agg(n=("team_id", "size"), home=("team_home_away", lambda s: int((s == "home").sum())), away=("team_home_away", lambda s: int((s == "away").sum())), lg=("league", "all"))
    ok = g[(g.n == 2) & (g.home == 1) & (g.away == 1)]
    drop["games_not_two_rows_home_away"] = int(len(g) - len(ok)); drop["games_with_non_league_team"] = int((~ok.lg).sum())
    t = t[t.game_id.isin(ok.index[ok.lg])].rename(columns=SHORT).drop(columns=["oPTS_row", "league", "season_type"])
    for c in ("PTS", "FGM", "FGA", "TPM", "TPA", "FTM", "FTA", "ORB", "DRB", "TOV"):
        t[c] = t[c].astype(float)
    o = t[["game_id", "team_id", "PTS", "FGM", "FGA", "TPM", "TPA", "FTM", "FTA", "ORB", "DRB", "TOV"]].rename(columns=lambda c: c if c == "game_id" else "o" + c)
    t = t.merge(o, on="game_id"); t = t[t.team_id != t.oteam_id].copy()
    home = t[t.team_home_away == "home"].set_index("game_id")
    t["season"] = t.game_id.map(home.season).astype(int); t["date"] = pd.to_datetime(t.game_id.map(home.game_date))
    t["poss_T"] = t.FGA - t.ORB + t.TOV + 0.44 * t.FTA; t["poss_U"] = t.oFGA - t.oORB + t.oTOV + 0.44 * t.oFTA; t["POSS"] = (t.poss_T + t.poss_U) / 2
    t["MISS2"] = (t.FGA - t.TPA) - (t.FGM - t.TPM); t["MISS3"] = t.TPA - t.TPM; t["MISSFT"] = t.FTA - t.FTM
    t["W"] = (t.PTS > t.oPTS).astype(float); t["CL"] = ((t.PTS - t.oPTS).abs() <= 5).astype(float); t["CLW"] = t.CL * t.W; t["G"] = 1.0
    return t.sort_values(["season", "team_id", "date", "game_id"], kind="mergesort").reset_index(drop=True), drop


SUMS = ["G", "PTS", "oPTS", "POSS", "FGM", "TPM", "FGA", "TOV", "poss_T", "ORB", "oDRB", "FTA", "oFGM", "oTPM", "oFGA", "oTOV", "poss_U", "oORB", "DRB", "oFTA", "TPA", "MISS2", "MISS3", "MISSFT",
        "W", "CL", "CLW"]


def _div(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b == 0, np.nan, a / np.where(b == 0, 1, b))


def build(raw: dict) -> pd.DataFrame:
    t, _ = team_rows(raw)
    grp = t.groupby(["season", "team_id"], sort=False)
    # prior = strictly earlier DATE: two games of a team on one date (one ESPN date error in 2020) are not prior to each other
    day = t.groupby(["season", "team_id", "date"], sort=False)[SUMS].transform("sum")
    last_of_day = ~t.duplicated(["season", "team_id", "date"], keep="last")
    cum_day = day.where(last_of_day, 0.0).groupby([t.season, t.team_id], sort=False).cumsum()
    cum_day = cum_day.groupby([t.season, t.team_id, t.date], sort=False).transform("max")       # every row of the date sees the cumulative total through that date
    S = cum_day - day                                      # sums over the team's same-season games on strictly earlier dates
    n = S.G.to_numpy(); has = n > 0; nan = np.nan
    f = pd.DataFrame(index=t.index)
    f["n_pre"] = n.astype(int)
    f["off_rtg_pre"] = 100 * _div(S.PTS, S.POSS); f["def_rtg_pre"] = 100 * _div(S.oPTS, S.POSS); f["net_rtg_pre"] = f.off_rtg_pre - f.def_rtg_pre
    f["pace_pre"] = _div(S.POSS, S.G)
    f["efg_pre"] = _div(S.FGM + 0.5 * S.TPM, S.FGA); f["tov_pre"] = _div(S.TOV, S.poss_T); f["orb_pre"] = _div(S.ORB, S.ORB + S.oDRB); f["ftr_pre"] = _div(S.FTA, S.FGA)
    f["d_efg_pre"] = _div(S.oFGM + 0.5 * S.oTPM, S.oFGA); f["d_tov_pre"] = _div(S.oTOV, S.poss_U); f["d_orb_pre"] = _div(S.oORB, S.oORB + S.DRB); f["d_ftr_pre"] = _div(S.oFTA, S.oFGA)
    f["three_rate_pre"] = _div(S.TPA, S.FGA)
    for a, b in (("miss2_pg_pre", "MISS2"), ("miss3_pg_pre", "MISS3"), ("missft_pg_pre", "MISSFT")):
        f[a] = _div(S[b], S.G)
    f["win_pct_pre"] = _div(S.W, S.G)
    P, A = S.PTS.to_numpy(), S.oPTS.to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        f["pyth_pct_pre"] = np.where(has, 1.0 / (1.0 + (A / np.where(P == 0, np.nan, P)) ** 14), nan)
    f["pyth_resid_pre"] = f.win_pct_pre - f.pyth_pct_pre
    f["close_n_pre"] = S.CL.to_numpy().astype(int); f["close_win_pct_pre"] = _div(S.CLW, S.CL)
    start = grp.cumcount().to_numpy(); start = np.arange(len(t)) - start                 # first row of each team-season block (t is sorted by date, game_id)
    hi = start + n.astype(int); lo = start + np.maximum(n.astype(int) - 10, 0)
    r = {}
    for c in ("PTS", "oPTS", "POSS"):
        cs = np.concatenate([[0.0], np.cumsum(t[c].to_numpy())]); r[c] = cs[hi] - cs[lo]
    f["net_l10_pre"] = 100 * _div(r["PTS"] - r["oPTS"], r["POSS"])
    dates = t.date.to_numpy()
    f["rest_days"] = np.where(has, (dates - dates[np.maximum(hi - 1, 0)]) / np.timedelta64(1, "D"), nan).astype(float)
    f["b2b"] = np.where(f.rest_days.isna(), nan, (f.rest_days == 1).astype(float))
    tot = t.groupby(["season", "team_id"])[["PTS", "oPTS", "POSS"]].sum()
    net = (100 * (tot.PTS - tot.oPTS) / tot.POSS).rename("prev_net_prior").reset_index(); net["season"] += 1
    f["prev_net_prior"] = t[["season", "team_id"]].merge(net, on=["season", "team_id"], how="left").prev_net_prior.to_numpy()
    for c in f.columns:
        if c not in ("n_pre", "close_n_pre", "close_win_pct_pre", "prev_net_prior"):
            f.loc[~has, c] = nan
    # league prior sums: all team-game rows of the season on strictly earlier dates
    LS = ["G", "FGM", "TPM", "FGA", "TOV", "poss_T", "ORB", "oDRB", "FTA", "POSS"]
    d = t.groupby(["season", "date"])[LS].sum().sort_index()
    L = (d.groupby(level=0).cumsum() - d).reset_index()
    lg = pd.DataFrame({"season": L.season, "date": L.date, "lg_efg": _div(L.FGM + 0.5 * L.TPM, L.FGA), "lg_tov": _div(L.TOV, L.poss_T), "lg_orb": _div(L.ORB, L.ORB + L.oDRB),
                       "lg_ftr": _div(L.FTA, L.FGA), "lg_pace": _div(L.POSS, L.G)})
    x = pd.concat([t[["game_id", "season", "date", "team_id", "team_home_away", "PTS"]], f], axis=1)
    h = x[x.team_home_away == "home"].set_index("game_id"); a = x[x.team_home_away == "away"].set_index("game_id").reindex(h.index)
    out = pd.DataFrame({"game_id": h.index.astype("int64"), "season": h.season.to_numpy().astype("int64"), "date": h.date.dt.strftime("%Y-%m-%d").to_numpy()})
    sc = raw["schedule"].drop_duplicates("game_id").set_index("game_id").reindex(h.index)
    cu = pd.to_datetime(sc["date"], utc=True, errors="coerce")
    out["cutoff_utc"] = cu.dt.strftime("%Y-%m-%dT%H:%M:%SZ").fillna("").to_numpy()
    out["neutral"] = sc.neutral_site.fillna(False).astype(bool).astype(float).to_numpy()
    out["home_team_id"] = h.team_id.to_numpy().astype("int64"); out["away_team_id"] = a.team_id.to_numpy().astype("int64")
    for s, fr in (("home", h), ("away", a)):
        for c in TEAM_F:
            out[f"{s}_{c}"] = fr[c].to_numpy()
    g = out[["season", "date"]].assign(date=pd.to_datetime(out.date)).merge(lg, on=["season", "date"], how="left")
    for s, o in (("home", "away"), ("away", "home")):
        for k in ("efg", "tov", "orb", "ftr"):
            out[f"{s}_exp_{k}"] = out[f"{s}_{k}_pre"].to_numpy() + out[f"{o}_d_{k}_pre"].to_numpy() - g[f"lg_{k}"].to_numpy()
    out["exp_miss2"] = out.home_miss2_pg_pre + out.away_miss2_pg_pre; out["exp_miss3"] = out.home_miss3_pg_pre + out.away_miss3_pg_pre
    out["exp_missft"] = out.home_missft_pg_pre + out.away_missft_pg_pre; out["exp_reb_pool"] = out.exp_miss2 + out.exp_miss3
    out["exp_poss"] = out.home_pace_pre.to_numpy() * out.away_pace_pre.to_numpy() / g.lg_pace.to_numpy()
    out["y_home_margin"] = (h.PTS.to_numpy() - a.PTS.to_numpy()).astype(float); out["y_total"] = (h.PTS.to_numpy() + a.PTS.to_numpy()).astype(float)
    out["y_home_win"] = (out.y_home_margin > 0).astype("int64")
    return out.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)[COLUMNS]


def _same(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    x, y = a[FEATURES].to_numpy(float), b[FEATURES].to_numpy(float)
    return bool(x.shape == y.shape and ((np.isnan(x) & np.isnan(y)) | np.isclose(x, y, rtol=1e-12, atol=1e-12)).all())


def leakage_checks(raw: dict, d: pd.DataFrame, dates: list[str], seed: int = 7) -> dict:
    """Per cut date D: (truncation) rebuild from games dated <= D only; rows dated <= D must be identical. (future scramble) add noise to every
    box number of games dated >= D ... rows dated <= D identical; (own game) scramble only games dated == D: rows dated == D identical."""
    rng = np.random.default_rng(seed); tb = raw["team_box"]; gd = pd.to_datetime(tb.game_date); out = {}
    by = d.set_index("game_id")
    for D in dates:
        cut = pd.Timestamp(D); season = int(d[pd.to_datetime(d.date) <= cut].season.max())
        ids = d[(pd.to_datetime(d.date) <= cut) & (d.season == season)].game_id.tolist()        # same season: the previous-season prior legitimately uses the whole earlier season
        own = d[pd.to_datetime(d.date) == cut].game_id.tolist()
        tr = build({"team_box": tb[gd <= cut], "schedule": raw["schedule"]}).set_index("game_id")
        def scr(mask):
            x = tb.copy(); k = mask.to_numpy()
            for c in NUM:
                x[c] = x[c].to_numpy() + np.where(k, rng.integers(1, 9, size=len(x)), 0).astype(x[c].dtype)
            return build({"team_box": x, "schedule": raw["schedule"]}).set_index("game_id")
        fu = scr(gd >= cut); og = scr(gd == cut)
        out[D] = {"season": season, "rows_checked": len(ids), "truncation_identical": _same(tr.reindex(ids), by.reindex(ids)), "future_scramble_identical": _same(fu.reindex(ids), by.reindex(ids)),
                  "future_games_checked": len(ids), "own_game_identical": _same(og.reindex(own), by.reindex(own)) if own else True, "own_games": len(own),
                  "perturbation_reaches_later_games": bool(not _same(fu.reindex(d[(d.season == season) & (pd.to_datetime(d.date) > cut)].game_id.tolist()),
                                                                      by.reindex(d[(d.season == season) & (pd.to_datetime(d.date) > cut)].game_id.tolist())))}
    return out


def evidence(raw: dict, d: pd.DataFrame, checks: dict) -> dict:
    from ..foundation.training_sets import canonical_hash
    _, drop = team_rows(raw)
    return {"schema": "nba-team-box-dataset-1.0", "status": "RESEARCH_ONLY", "spec": SPEC, "builder": "alpha_engine.features.nba_team_box", "rows": int(len(d)), "columns": len(d.columns),
            "features": len(FEATURES), "dropped": drop, "seasons": {str(k): int(v) for k, v in d.season.value_counts().sort_index().items()}, "date_range": [d.date.min(), d.date.max()],
            "keys_unique": bool(not d.game_id.duplicated().any()), "canonical_sha256": canonical_hash(d), "deterministic_regeneration": canonical_hash(build(raw)) == canonical_hash(d),
            "rows_without_cutoff": int((d.cutoff_utc == "").sum()), "missing_share_max": round(float(d[FEATURES].isna().mean().max()), 6),
            "both_sides_have_history_share": round(float(((d.home_n_pre > 0) & (d.away_n_pre > 0)).mean()), 6), "leakage": checks, "catalog_columns": CATALOG,
            "caveat": "ESPN `turnovers` is the team total before 2014 and excludes team (dead-ball) turnovers from 2014 (about 0.6 per game): possessions shift by that amount between eras"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--root", required=True); ap.add_argument("--out", required=True); ap.add_argument("--evidence")
    ap.add_argument("--dates", default="2008-01-12,2016-03-05,2024-12-14,2026-11-10")
    a = ap.parse_args(argv)
    raw = load_raw(a.root); d = build(raw)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); d.to_parquet(a.out, index=False)
    ev = evidence(raw, d, leakage_checks(raw, d, a.dates.split(",")))
    if a.evidence:
        Path(a.evidence).write_text(json.dumps(ev, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: ev[k] for k in ("rows", "canonical_sha256", "deterministic_regeneration", "dropped", "rows_without_cutoff", "both_sides_have_history_share", "leakage")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
