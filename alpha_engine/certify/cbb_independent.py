"""Independent re-implementation of the CBB game-level feature dataset.

Built solely from docs/certification/CBB_FEATURE_SPEC.md (certification spec v1) for
blind certification. RESEARCH_ONLY.

SPEC AMBIGUITIES (most literal reading chosen in each case):
  A1. Warm start keeps ONLY the previous solved date's final solution. A team that is in
      an older solution but not in the immediately previous one restarts at 0.
      (Implementation note: O/D are held in arrays over all teams; after any solve a team
      with no rows in H(D) has O = D = 0 by the update formulas, which is identical to
      "absent from the previous solution -> start at 0".)
  A2. "Team absent from H(D)" means the team is not in the union of team_id and
      opponent_team_id of H(D). A team present only as an opponent therefore gets
      adj_o/adj_d/adj_net from the solution, n_pre = 0, and tempo / factor features
      = 0/0 = missing.
  A3. The "team absent -> missing" rule is applied to every feature except hca_pre
      (the only stated exception). conf_net_pre: see spec v1.1 amendment (present for absent teams).
  A4. conf_net_pre: conference membership for the mean is taken from H(D) rows of that
      team as `team_id` (not as opponent). The row's own conf_id that is mapped comes from
      its schedule join; missing conf_id or a conference with no member in H(D) -> missing.
  A5. Factor values that are +/-inf (x / 0 with x != 0) are not "missing"; only NaN
      (e.g. 0/0) is treated as missing and contributes 0 to the numerator. In the
      actual data no infinite factor values were observed after the poss > 40 filter.
  A6. `pts_against` is the row's own `opponent_team_score` coerced to numeric (not the
      opponent row's team_score). Missing values here are not filtered.
  A7. `date` is stored as datetime64 at midnight (calendar date, no tz). `cutoff_utc`
      is `start_date` parsed with utc=True (NaT when the game has no schedule row).
  A8. `neutral` and `conference_game` are float 0/1; `y_home_win` is int 0/1.
  A9. When |H(D)| < 200 hca_pre is also missing ("every feature").
  A10. `split` is derived from the team-box `season` column; seasons outside the stated
      ranges (none expected) get missing split.
  A11. Column order of the 30 features: all home_<f> in the spec's list order, then all
      away_<f> in the same order.
  A12. The schedule is deduplicated on game_id across all concatenated seasons (first
      occurrence in ascending-season file order).
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import time

import numpy as np
import pandas as pd

NUM_COLS = [
    "field_goals_attempted", "field_goals_made", "three_point_field_goals_made",
    "free_throws_attempted", "offensive_rebounds", "defensive_rebounds", "turnovers",
    "team_score",
]
SCHED_COLS = [
    "game_id", "start_date", "neutral_site", "conference_competition", "home_id", "away_id",
    "home_conference_id", "away_conference_id",
]
FACTORS = ["efg", "tov", "orb", "ftr", "d_efg", "d_tov", "d_orb", "d_ftr"]
FEATS = [
    "adj_o_pre", "adj_d_pre", "adj_net_pre", "hca_pre", "tempo_pre", "n_pre", "conf_net_pre",
    "efg_pre", "tov_pre", "orb_pre", "ftr_pre", "d_efg_pre", "d_tov_pre", "d_orb_pre",
    "d_ftr_pre",
]
N_ITER = 12
HALF_LIFE = 60.0
WINDOW_DAYS = 400
MIN_HIST = 200
PRIOR = 3.0


def _season_files(d: str, pattern: str) -> list[tuple[int, str]]:
    out = []
    for p in glob.glob(os.path.join(d, pattern)):
        m = re.search(r"_(\d{4})\.parquet$", p)
        if m and int(m.group(1)) >= 2006:
            out.append((int(m.group(1)), p))
    return sorted(out)


def load_raw(cbb_dir: str) -> dict:
    tb = [pd.read_parquet(p) for _, p in _season_files(os.path.join(cbb_dir, "team_box"), "team_box_*.parquet")]
    sc = [pd.read_parquet(p, columns=SCHED_COLS)
          for _, p in _season_files(os.path.join(cbb_dir, "schedules"), "mbb_schedule_*.parquet")]
    return {
        "team_box": pd.concat(tb, ignore_index=True),
        "schedule": pd.concat(sc, ignore_index=True),
    }


# ---------------------------------------------------------------- team-game table
def build_team_games(raw: dict) -> pd.DataFrame:
    tb = raw["team_box"].copy()
    for c in NUM_COLS:
        tb[c] = pd.to_numeric(tb[c], errors="coerce")
    tb["opponent_team_score"] = pd.to_numeric(tb["opponent_team_score"], errors="coerce")
    tb = tb[tb["season_type"].isin([2, 3])]
    tb = tb.dropna(subset=NUM_COLS)
    tb = tb.drop_duplicates(subset=["game_id", "team_id"], keep="first").reset_index(drop=True)
    tb["date"] = pd.to_datetime(tb["game_date"].astype(str).str.slice(0, 10), format="%Y-%m-%d")
    tb["poss_own"] = (tb["field_goals_attempted"] - tb["offensive_rebounds"]
                      + tb["turnovers"] + 0.475 * tb["free_throws_attempted"])

    opp_cols = NUM_COLS + ["poss_own"]
    opp = tb[["game_id", "team_id"] + opp_cols].rename(
        columns={c: "o_" + c for c in opp_cols} | {"team_id": "_opp_tid"})
    g = tb.merge(opp, left_on=["game_id", "opponent_team_id"], right_on=["game_id", "_opp_tid"],
                 how="inner").drop(columns="_opp_tid")

    g["poss"] = (g["poss_own"] + g["o_poss_own"]) / 2.0
    g = g[g["poss"] > 40].reset_index(drop=True)
    g["pts_for"] = g["team_score"]
    g["pts_against"] = g["opponent_team_score"]
    g["eff_o"] = 100.0 * g["pts_for"] / g["poss"]

    fga, fgm, tpm = g["field_goals_attempted"], g["field_goals_made"], g["three_point_field_goals_made"]
    fta, orb, drb, to = (g["free_throws_attempted"], g["offensive_rebounds"],
                         g["defensive_rebounds"], g["turnovers"])
    o_fga, o_fgm, o_tpm = g["o_field_goals_attempted"], g["o_field_goals_made"], g["o_three_point_field_goals_made"]
    o_fta, o_orb, o_drb, o_to = (g["o_free_throws_attempted"], g["o_offensive_rebounds"],
                                 g["o_defensive_rebounds"], g["o_turnovers"])
    g["efg"] = (fgm + 0.5 * tpm) / fga
    g["tov"] = to / g["poss_own"]
    g["orb"] = orb / (orb + o_drb)
    g["ftr"] = fta / fga
    g["d_efg"] = (o_fgm + 0.5 * o_tpm) / o_fga
    g["d_tov"] = o_to / g["o_poss_own"]
    g["d_orb"] = o_orb / (o_orb + drb)
    g["d_ftr"] = o_fta / o_fga

    sched = raw["schedule"][SCHED_COLS].drop_duplicates(subset=["game_id"], keep="first")
    g = g.merge(sched, on="game_id", how="left")
    g["neutral"] = g["neutral_site"].astype("boolean").fillna(False).astype(bool)
    home = (g["team_home_away"] == "home").to_numpy()
    g["site"] = np.where(g["neutral"].to_numpy(), 0, np.where(home, 1, -1)).astype(float)
    g["conf_id"] = np.where(g["team_id"] == g["home_id"], g["home_conference_id"],
                            np.where(g["team_id"] == g["away_id"], g["away_conference_id"], np.nan))
    g["conf_id"] = g["conf_id"].astype(float)

    g = g.sort_values(["date", "game_id", "team_id"], kind="mergesort").reset_index(drop=True)
    return g


# ---------------------------------------------------------------- rating solver
def solve(t, o, y, site, w, n_teams, O0, D0, h0):
    """Weighted alternating updates (spec order). Only H(D) arrays are passed in."""
    sw = w.sum()
    lg = (w * y).sum() / sw
    O = O0.copy()
    D = D0.copy()
    h = float(h0)
    wt = np.bincount(t, weights=w, minlength=n_teams)
    wo = np.bincount(o, weights=w, minlength=n_teams)
    nz = site != 0
    swnz = w[nz].sum()
    for _ in range(N_ITER):
        O = np.bincount(t, weights=w * (y - lg - h * site + D[o]), minlength=n_teams) / (wt + PRIOR)
        D = np.bincount(o, weights=w * (lg + O[t] + h * site - y), minlength=n_teams) / (wo + PRIOR)
        if swnz > 0:
            h = float((w * site * (y - lg - O[t] + D[o]))[nz].sum() / swnz)
        else:
            h = 0.0
        lg = float((w * (y - O[t] + D[o] - h * site)).sum() / sw)
    return O, D, h, lg


def compute_features(g: pd.DataFrame, verbose: bool = False, max_dates: int | None = None) -> pd.DataFrame:
    n = len(g)
    teams = np.unique(np.concatenate([g["team_id"].to_numpy(), g["opponent_team_id"].to_numpy()]))
    n_teams = len(teams)
    T = np.searchsorted(teams, g["team_id"].to_numpy())
    OP = np.searchsorted(teams, g["opponent_team_id"].to_numpy())
    day = (g["date"].to_numpy().astype("datetime64[D]").astype(np.int64))
    y_all = g["eff_o"].to_numpy(float)
    site_all = g["site"].to_numpy(float)
    poss_all = g["poss"].to_numpy(float)
    conf_all = g["conf_id"].to_numpy(float)
    fac_all = {f: g[f].to_numpy(float) for f in FACTORS}

    out = {f: np.full(n, np.nan) for f in FEATS}

    dates = np.unique(day)
    if max_dates is not None:
        dates = dates[:max_dates]
    O_prev = np.zeros(n_teams)
    D_prev = np.zeros(n_teams)
    h_prev = 0.0
    t0 = time.time()
    for k, Dd in enumerate(dates):
        lo = np.searchsorted(day, Dd - WINDOW_DAYS, side="left")
        hi = np.searchsorted(day, Dd, side="left")
        cur_hi = np.searchsorted(day, Dd, side="right")
        cur = slice(hi, cur_hi)
        if hi - lo < MIN_HIST:
            O_prev[:] = 0.0
            D_prev[:] = 0.0
            h_prev = 0.0
            continue
        # history H(D): rows with D-400 <= date < D only
        t = T[lo:hi]
        o = OP[lo:hi]
        y = y_all[lo:hi]
        site = site_all[lo:hi]
        poss = poss_all[lo:hi]
        age = (Dd - day[lo:hi]).astype(float)
        w = 0.5 ** (age / HALF_LIFE)

        O, Dv, h, lg = solve(t, o, y, site, w, n_teams, O_prev, D_prev, h_prev)
        O_prev, D_prev, h_prev = O, Dv, h

        present = (np.bincount(t, minlength=n_teams) + np.bincount(o, minlength=n_teams)) > 0
        n_pre = np.bincount(t, weights=w, minlength=n_teams)
        wp = w * poss
        swp = np.bincount(t, weights=wp, minlength=n_teams)
        with np.errstate(invalid="ignore", divide="ignore"):
            tempo = swp / n_pre
            fac_pre = {}
            for f in FACTORS:
                fv = fac_all[f][lo:hi]
                fv = np.where(np.isnan(fv), 0.0, fv)
                fac_pre[f] = np.bincount(t, weights=fv * wp, minlength=n_teams) / swp

        # conference means: last row per team (sort order) with non-missing conf_id in H(D)
        conf_h = conf_all[lo:hi]
        has = ~np.isnan(conf_h)
        conf_map = {}
        if has.any():
            th = t[has][::-1]
            ch = conf_h[has][::-1]
            _, first_idx = np.unique(th, return_index=True)  # first in reversed = last
            last_t = th[first_idx]
            last_c = ch[first_idx]
            net = O[last_t] + Dv[last_t]
            s = pd.Series(net).groupby(last_c).mean()
            conf_map = s.to_dict()

        tc = T[cur]
        pres = present[tc]
        out["hca_pre"][cur] = h
        out["adj_o_pre"][cur] = np.where(pres, lg + O[tc], np.nan)
        out["adj_d_pre"][cur] = np.where(pres, lg - Dv[tc], np.nan)
        out["adj_net_pre"][cur] = np.where(pres, (lg + O[tc]) - (lg - Dv[tc]), np.nan)
        out["n_pre"][cur] = np.where(pres, n_pre[tc], np.nan)
        out["tempo_pre"][cur] = np.where(pres, tempo[tc], np.nan)
        for f in FACTORS:
            out[f + "_pre"][cur] = np.where(pres, fac_pre[f][tc], np.nan)
        cc = conf_all[cur]
        cn = np.array([conf_map.get(c, np.nan) if not np.isnan(c) else np.nan for c in cc], dtype=float)
        out["conf_net_pre"][cur] = cn  # spec v1.1 amendment: defined for the row's conference even when the team is absent from H(D)

        if verbose and (k % 200 == 0):
            print(f"[{k}/{len(dates)}] {np.datetime64(int(Dd), 'D')} hist={hi - lo} "
                  f"elapsed={time.time() - t0:.1f}s", flush=True)
    feats = pd.DataFrame(out, index=g.index)
    return feats


# ---------------------------------------------------------------- game-level
def _split(season: pd.Series) -> pd.Series:
    s = season.astype(int)
    res = pd.Series(pd.NA, index=season.index, dtype="object")
    res[(s >= 2006) & (s <= 2019)] = "train"
    res[(s >= 2020) & (s <= 2022)] = "validate"
    res[(s >= 2023) & (s <= 2026)] = "test"
    res[s == 2027] = "prospective"
    return res


def build(raw: dict, verbose: bool = False, max_dates: int | None = None) -> pd.DataFrame:
    g = build_team_games(raw)
    feats = compute_features(g, verbose=verbose, max_dates=max_dates)
    g = pd.concat([g, feats], axis=1)

    home = g[g["team_home_away"] == "home"].copy()
    df = pd.DataFrame({
        "game_id": home["game_id"].to_numpy(),
        "season": home["season"].to_numpy(),
        "date": home["date"].to_numpy(),
        "home_team": home["team_id"].to_numpy(),
        "away_team": home["opponent_team_id"].to_numpy(),
        "cutoff_utc": pd.to_datetime(home["start_date"], utc=True, errors="coerce").to_numpy(),
        "neutral": home["neutral"].astype(float).to_numpy(),
        "conference_game": home["conference_competition"].astype("boolean").fillna(False)
                                .astype(float).to_numpy(),
    })
    df["cutoff_utc"] = pd.to_datetime(df["cutoff_utc"], utc=True)
    margin = (home["pts_for"] - home["pts_against"]).to_numpy(float)
    df["y_home_margin"] = margin
    df["y_total"] = (home["pts_for"] + home["pts_against"]).to_numpy(float)
    df["y_home_win"] = (margin > 0).astype(int)
    for f in FEATS:
        df["home_" + f] = home[f].to_numpy()

    away = g[["game_id", "team_id"] + FEATS].rename(
        columns={"team_id": "away_team"} | {f: "away_" + f for f in FEATS})
    df = df.merge(away, on=["game_id", "away_team"], how="left")
    df["split"] = _split(df["season"])
    df = df.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    cols = (["game_id", "season", "date", "home_team", "away_team", "cutoff_utc", "neutral",
             "conference_game", "y_home_margin", "y_total", "y_home_win"]
            + ["home_" + f for f in FEATS] + ["away_" + f for f in FEATS] + ["split"])
    return df[cols]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cbb", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-dates", type=int, default=None, help="debug: only first N rating dates")
    a = ap.parse_args(argv)
    t0 = time.time()
    raw = load_raw(a.cbb)
    df = build(raw, verbose=True, max_dates=a.max_dates)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    df.to_parquet(a.out, index=False)
    print(f"rows={len(df)} cols={df.shape[1]} runtime={time.time() - t0:.1f}s -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
