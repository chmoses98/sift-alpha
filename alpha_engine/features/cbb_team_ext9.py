"""CBB batch 9, team rows from the ESPN schedule table only (RESEARCH_ONLY, PROXY): first-half share of scoring and a binned competitive / blowout margin-regime mixture.
No line, spread or price anywhere. Source: sift-data-vault archives/CBB/espn_team_box_schedules (schedules/mbb_schedule_<season>.parquet); ESPN-derived, UNRESOLVED_INTERNAL_ONLY.

DEFINITIONS (every value for a row dated d uses only games dated strictly before d; binned tables for season S use seasons before S only)
  Games: schedule rows with season_type in {2, 3}, status_type_completed true, home_score and away_score present, season >= 2006 (first row per game_id). date = game_date.
  Team-games: home (s = +1) and away (s = -1); s = 0 for both when neutral_site is true. margin = own - opponent final score; total = sum. ot = status_period > 2.
  Linescores (2023+ only): home_linescores / away_linescores are stringified lists of {'period': p, 'value': v, ...} (2023-2024 entries have no 'period': the list position 1, 2, ...
  is the period); h1 = value of period 1, reg = values of periods 1 + 2 (missing
  if a side lacks either period). Game ratio r = (h1_home + h1_away) / (reg_home + reg_away) when both sides have them and the denominator > 0.
  Team state: EWM sums W(x) = sum r^(i-j) x_j over the team's team-games (half-life 15), read at its last team-game dated before d.
nfl-style naming is not used; columns:
cbb.first_half_pace_ratio   fhp_team_ratio_pre = n/(n+12) R + 12/(n+12) lg_r with R = W(r 1[r defined]) / W(1[r defined]), n = W(1[r defined]) (R = lg_r when n = 0),
                            lg_r = mean r over games of season S-1 (missing if none: rows before 2024); fhp_pair_ratio_pre = mean of the two teams' values;
                            fhp_exp_h1_total_pre = pair ratio x 0.5 (W(total)/W(1) of T + of O).
cbb.margin_regime_mixture   m_hat = 0.5 (W(margin)/W(1) of T - of O) + 0.5 H s, H = mean (home - away) final margin over non-neutral games of S-1; mrm_m_hat_pre = m_hat.
                            Reference: team-game rows of seasons S-10 .. S-1 (>= 2007) with their m_hat; bin b = floor(clip(m_hat, -29.999, 29.999) / 2). Per bin (needs >= 20 rows, else missing):
                            mrm_p_blowout_pre = share |margin| >= 15; mrm_comp_mu_pre / mrm_comp_sd_pre = mean / sample SD of margin over rows with |margin| < 15; mrm_blow_mu_pre /
                            mrm_blow_sd_pre the same over |margin| >= 15 (missing if < 2 such rows); mrm_p_ot_pre = share ot; mrm_p_win_pre = share margin > 0.
"""
from __future__ import annotations

import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec

S = "CBB"
HIST_FIRST, OUT_FIRST = 2006, 2013
HL, K_R = 15.0, 12.0
REF_SEASONS, MIN_BIN = 10, 20
BLOW = 15
COLS = ["game_id", "season", "season_type", "game_date", "home_id", "away_id", "home_score", "away_score", "neutral_site", "status_type_completed", "status_period", "home_linescores", "away_linescores"]
CONTENT = ["home_score", "away_score", "status_period", "home_linescores", "away_linescores"]
_LS = re.compile(r"\{[^}]*\}")


def load_raw(root) -> dict:
    import pyarrow.parquet as pq
    fs = sorted(glob.glob(str(Path(root) / "schedules" / "mbb_schedule_*.parquet")))
    s = pd.concat([pd.read_parquet(f, columns=[c for c in COLS if c in pq.read_schema(f).names]).reindex(columns=COLS) for f in fs], ignore_index=True)
    s = s[s.season >= HIST_FIRST].copy()
    s["game_date"] = pd.to_datetime(s.game_date.astype(str)).dt.normalize()
    for c in ("home_linescores", "away_linescores"):
        s[c] = s[c].where(s[c].notna(), None).map(lambda v: None if v is None else str(v))
    w = s.season < OUT_FIRST
    return {"sched": s[~w].reset_index(drop=True), "sched_warm": s[w].reset_index(drop=True)}


def _periods(v) -> dict:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return {}
    out = {}
    for i, m in enumerate(_LS.findall(str(v))):
        p = re.search(r"'period':\s*([\d.]+)", m); x = re.search(r"'value':\s*([\d.]+)", m)
        if x:                                      # 2023-2024 entries carry no 'period' key: the list position (1, 2, ...) is the period
            out.setdefault(int(float(p.group(1))) if p else i + 1, float(x.group(1)))
    return out


def _team_games(raw: dict) -> pd.DataFrame:
    s = pd.concat([x for x in (raw.get("sched_warm"), raw["sched"]) if x is not None and len(x)], ignore_index=True)
    s = s[s.season_type.isin([2, 3]) & (s.status_type_completed == True) & s.home_score.notna() & s.away_score.notna()].drop_duplicates("game_id").copy()  # noqa: E712
    hp = s.home_linescores.map(_periods); ap = s.away_linescores.map(_periods)
    g = lambda P, k: P.map(lambda d: d.get(k, np.nan)).astype(float)  # noqa: E731
    hh1, hh2, ah1, ah2 = g(hp, 1), g(hp, 2), g(ap, 1), g(ap, 2)
    den = hh1 + hh2 + ah1 + ah2
    s["r"] = np.where(den > 0, (hh1 + ah1) / den.where(den > 0), np.nan)
    neu = s.neutral_site.fillna(False).astype(bool).to_numpy()
    rows = []
    for a, b, pa, pb, sg in (("home_id", "away_id", "home_score", "away_score", 1), ("away_id", "home_id", "away_score", "home_score", -1)):
        rows.append(pd.DataFrame({"game_id": s.game_id.astype("int64").to_numpy(), "season": s.season.astype(int).to_numpy(), "date": s.game_date.to_numpy(),
                                  "team": s[a].astype("int64").to_numpy(), "opp": s[b].astype("int64").to_numpy(), "s": np.where(neu, 0, sg), "is_home": sg == 1,
                                  "margin": (s[pa].astype(float) - s[pb].astype(float)).to_numpy(), "total": (s[pa].astype(float) + s[pb].astype(float)).to_numpy(),
                                  "ot": (pd.to_numeric(s.status_period, errors="coerce") > 2).astype(float).to_numpy(), "r": s.r.to_numpy()}))
    return pd.concat(rows, ignore_index=True).sort_values(["team", "date", "game_id"], kind="mergesort").reset_index(drop=True)


def _wsum(keys, x, hl):
    r = 0.5 ** (1.0 / hl); out = np.empty(len(x)); acc = 0.0; prev = None
    for i, (k, v) in enumerate(zip(keys.tolist(), np.asarray(x, float).tolist())):
        if k != prev:
            acc = 0.0; prev = k
        acc = acc * r + v; out[i] = acc
    return out


FHP = ["fhp_team_ratio_pre", "fhp_pair_ratio_pre", "fhp_exp_h1_total_pre"]
MRM = ["mrm_m_hat_pre", "mrm_p_blowout_pre", "mrm_comp_mu_pre", "mrm_comp_sd_pre", "mrm_blow_mu_pre", "mrm_blow_sd_pre", "mrm_p_ot_pre", "mrm_p_win_pre"]
ALL = FHP + MRM


def compute(raw: dict) -> dict:
    t = _team_games(raw); k = t.team.to_numpy(); dr = t.r.notna().to_numpy(float)
    st = t[["team", "date"]].copy()
    st["W1"] = _wsum(k, np.ones(len(t)), HL); st["Wm"] = _wsum(k, t.margin, HL); st["Wt"] = _wsum(k, t.total, HL)
    st["Wr"] = _wsum(k, np.where(dr > 0, t.r.fillna(0.0), 0.0), HL); st["Wn"] = _wsum(k, dr, HL)
    stl = st.sort_values(["date", "team"], kind="mergesort")
    rows = t[t.season >= HIST_FIRST + 1].sort_values(["date", "team"], kind="mergesort")
    a = pd.merge_asof(rows, stl.add_prefix("T_").rename(columns={"T_team": "team", "T_date": "date"}), on="date", by="team", allow_exact_matches=False, direction="backward")
    a = pd.merge_asof(a.sort_values(["date", "opp"], kind="mergesort"), stl.add_prefix("O_").rename(columns={"O_team": "opp", "O_date": "date"}), on="date", by="opp",
                      allow_exact_matches=False, direction="backward").sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    sea = {s_: t[t.season == s_] for s_ in sorted(t.season.unique())}
    lg_r = a.season.map({s_ + 1: (q.r.mean() if q.r.notna().any() else np.nan) for s_, q in sea.items()}).to_numpy(float)
    H = a.season.map({s_ + 1: float((q[(q.is_home) & (q.s != 0)].margin).mean()) for s_, q in sea.items()}).to_numpy(float)
    def team_r(p):
        n = a[p + "Wn"].fillna(0.0).to_numpy(); R = np.where(n > 0, a[p + "Wr"].to_numpy() / np.where(n > 0, n, 1.0), lg_r)
        return n / (n + K_R) * R + K_R / (n + K_R) * lg_r
    rT, rO = team_r("T_"), team_r("O_")
    a["fhp_team_ratio_pre"] = rT; a["fhp_pair_ratio_pre"] = 0.5 * (rT + rO)
    a["fhp_exp_h1_total_pre"] = a.fhp_pair_ratio_pre * 0.5 * (a.T_Wt / a.T_W1 + a.O_Wt / a.O_W1)
    a["mrm_m_hat_pre"] = 0.5 * (a.T_Wm / a.T_W1 - a.O_Wm / a.O_W1) + 0.5 * H * a.s.to_numpy()
    a["bin"] = np.floor(np.clip(a.mrm_m_hat_pre.to_numpy(float), -29.999, 29.999) / 2.0)
    for c in MRM[1:]:
        a[c] = np.nan
    for s_ in sorted(a.season.unique()):
        if s_ < OUT_FIRST:
            continue
        ref = a[(a.season >= max(HIST_FIRST + 1, s_ - REF_SEASONS)) & (a.season <= s_ - 1) & a.mrm_m_hat_pre.notna()]
        bl = (ref.margin.abs() >= BLOW)
        g = ref.assign(blow=bl.astype(float), win=(ref.margin > 0).astype(float), mc=ref.margin.where(~bl), mb=ref.margin.where(bl)).groupby("bin")
        tab = pd.DataFrame({"n": g.size(), "mrm_p_blowout_pre": g.blow.mean(), "mrm_comp_mu_pre": g.mc.mean(), "mrm_comp_sd_pre": g.mc.std(ddof=1),
                            "mrm_blow_mu_pre": g.mb.mean(), "mrm_blow_sd_pre": g.mb.std(ddof=1), "mrm_p_ot_pre": g.ot.mean(), "mrm_p_win_pre": g.win.mean()})
        tab.loc[tab.n < MIN_BIN, MRM[1:]] = np.nan
        cur = (a.season == s_).to_numpy()
        for c in MRM[1:]:
            a.loc[cur, c] = a.loc[cur, "bin"].map(tab[c]).to_numpy(float)
    out = a[a.season >= OUT_FIRST][["game_id", "team", "opp", "season", "date"] + ALL].copy()
    for c in ALL:
        out[c] = out[c].astype("float64")
    return {"team": out.reset_index(drop=True)}


def specs() -> list[FeatureSpec]:
    raw = ["ESPN men's college basketball schedules 2006-2027 (final scores, neutral site, status period; period line scores from 2023)"]
    return [
        FeatureSpec(S, "cbb.first_half_pace_ratio", "team", FHP, "PROXY",
                    "First-half share of regulation scoring per game (both teams), EWM over the team's games (half-life 15) shrunk to the previous season's league share with n/(n+12); pair = mean of "
                    "the two teams; expected first-half total = pair share x the teams' EWM game totals", ["team first-half ratio with half-life 15 and n/(n+12) shrinkage", "team-pair average",
                    "expected first-half quantity from the pair ratio"],
                    ["POSSESSION ratio (no half-level box scores: the POINTS share is used, so it mixes pace and efficiency)", "expected regulation possessions from the certified tempo inputs",
                     "line scores exist only from 2023: rows before 2024 are missing"], raw),
        FeatureSpec(S, "cbb.margin_regime_mixture", "team", MRM, "PROXY",
                    "Competitive (|margin| < 15) vs blowout regime mixture of the final margin by 2-point bins of a market-free expected margin (half the EWM net-margin gap + half the previous "
                    "season's home edge), estimated on the previous 10 seasons: P(blowout), each regime's mean and SD, P(overtime) and P(win)",
                    ["P(blowout) as a function of the model expected margin", "normal-in-regime mean and SD per regime", "overtime mass", "refit each season on earlier seasons only"],
                    ["logistic regression with coach decay (binned empirical frequencies used; no coach data)", "integer-margin pmf with the OT spike at 1-6",
                     "certified adjusted-efficiency expected margin (a simple EWM net-margin gap is used)"], raw),
    ]


def perturb_nv(raw: dict, block_ids, seed: int) -> dict:
    """Non-vacuity perturbation: the standard content scramble of the block's games PLUS a permutation of the line scores of the 2024 season's games. The default block (the median
    output season, about 2020) has no line scores, so without the second step the first-half ratio could not move however it was built; 2024 precedes the 2025-2027 rows that use it."""
    from ..input_research.data_foundation import replay_generic as G
    rng = np.random.default_rng(seed); o = dict(raw); s = raw["sched"]
    s = G._perm(s, s.game_id.isin(block_ids).to_numpy(), CONTENT, rng)
    m = (s.season == 2024).to_numpy()
    s = G._perm(s, m, ["home_linescores", "away_linescores"], rng)
    o["sched"] = s
    return o
