"""Phase 16 NBA: per-game/team possession + lineup-stint table from ESPN play-by-play, and point-in-time pregame features.

    python build_pbp_lineup_features.py --pbp-old $V/pbp1624 --raw $V/raw --out <dir>

--pbp-old : sift-data-vault archives/NBA/espn_pbp/2016-2024/sportsdataverse/snapshot-20261118 (restored; play_by_play_2016..2024)
--raw     : sift-data-vault archives/NBA/espn_pbp_boxes_schedules/2002-2027/sportsdataverse/snapshot-20261116 (restored;
            espn_nba_pbp 2025..2027 + player/team boxes)
Writes  <out>/pbp_game_team.csv.gz   (one row per game x team: possessions, ratings, starters, stint aggregates, validation flags)
        <out>/pbp_player_game.csv.gz (one row per game x player on-court totals; input to the starter-strength features)
        <out>/pbp_pregame_features.csv.gz (point-in-time features: each row uses only strictly earlier games of that team/player)
        <out>/build_manifest.json
Season label = end year (2016 = 2015-16), as in the nba-edge-finder research code. Regular season (2) and playoffs (3) only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from multiprocessing import Pool

import numpy as np
import pandas as pd

SEASONS = range(2016, 2028)
HL_TEAM, HL_PLAYER = 20.0, 25.0          # EWM half-lives in games (fixed in advance, not tuned)


def clock_secs(s: str) -> float:
    s = str(s)
    if ":" in s:
        m, x = s.split(":")
        return int(m) * 60 + float(x)
    try:
        return float(s)
    except ValueError:
        return np.nan


def period_start(p: int) -> float:
    return 720.0 * min(p - 1, 4) + 300.0 * max(p - 5, 0)


def period_len(p: int) -> float:
    return 720.0 if p <= 4 else 300.0


def pbp_path(a, s):
    return f"{a.pbp_old}/play_by_play_{s}.parquet" if s <= 2024 else f"{a.raw}/espn_nba_pbp/play_by_play_{s}.parquet"


COLS = ["game_id", "sequence_number", "type_text", "text", "team_id", "athlete_id_1", "athlete_id_2", "athlete_id_3",
        "home_score", "away_score", "period_number", "clock_display_value", "shooting_play", "home_team_id", "away_team_id",
        "season_type", "game_date"]
TECH = re.compile(r"technical|ejection|delay|no turnover|no timeout|too many players|taunting|hanging|double", re.I)


def game_rows(g: pd.DataFrame, roster: dict, box_starters: dict):
    """Return (team_rows, player_rows, diag) for one game. roster: athlete_id -> team_id (from the player box)."""
    g = g.drop_duplicates(["sequence_number"]).sort_values("sequence_number", kind="stable")
    hid, aid = int(g.home_team_id.iloc[0]), int(g.away_team_id.iloc[0])
    teams = (hid, aid)
    tt = g.type_text.astype(str).to_numpy()
    tid = g.team_id.to_numpy()
    a1, a2, a3 = (g[c].to_numpy() for c in ("athlete_id_1", "athlete_id_2", "athlete_id_3"))
    per = g.period_number.to_numpy().astype(int)
    clk = np.array([clock_secs(c) for c in g.clock_display_value.to_numpy()])
    el = np.array([period_start(p) + period_len(p) - min(max(c, 0.0), period_len(p)) for p, c in zip(per, clk)])
    hs, as_ = g.home_score.to_numpy().astype(float), g.away_score.to_numpy().astype(float)
    hs, as_ = np.maximum.accumulate(np.nan_to_num(hs)), np.maximum.accumulate(np.nan_to_num(as_))
    shoot = g.shooting_play.fillna(False).to_numpy().astype(bool)
    n = len(g)
    is_sub = tt == "Substitution"
    is_ft = np.char.startswith(tt.astype(str), "Free Throw")
    is_tech = np.array([bool(TECH.search(x)) for x in tt])
    is_to = np.array(["Turnover" in x and not x.startswith("No ") for x in tt])
    is_dreb = tt == "Defensive Rebound"
    is_oreb = tt == "Offensive Rebound"
    is_fga = shoot & ~is_ft
    # --- possession team per event (None when event does not define it)
    pos_team = [None] * n
    for i in range(n):
        t = tid[i]
        if t != t or t is None:
            continue
        t = int(t)
        if is_ft[i] and is_tech[i]:
            continue
        if is_fga[i] or is_ft[i] or is_to[i] or is_dreb[i] or is_oreb[i]:
            pos_team[i] = t
    # --- lineups: period starters inferred from first appearance; period 1 compared with box starter flags
    pdiag = {}
    on = {t: set() for t in teams}
    prev_end = {t: set() for t in teams}
    starters_box = {t: set(box_starters.get(t, [])) for t in teams}
    starters_pbp = {}
    lineup_at = [None] * n
    periods = sorted(set(per))
    pidx = {p: np.where(per == p)[0] for p in periods}
    for p in periods:
        idx = pidx[p]
        seen_in, start = {t: set() for t in teams}, {t: [] for t in teams}
        for i in idx:
            if is_tech[i] and not is_ft[i]:
                continue
            if is_sub[i]:
                pin, pout = a1[i], a2[i]
                if pin == pin:
                    seen_in.setdefault(roster.get(int(pin), -1), set()).add(int(pin))
                if pout == pout:
                    t = roster.get(int(pout))
                    if t in teams and int(pout) not in seen_in[t] and int(pout) not in start[t]:
                        start[t].append(int(pout))
                continue
            for x in (a1[i], a2[i], a3[i]):
                if x != x:
                    continue
                t = roster.get(int(x))
                if t in teams and int(x) not in seen_in[t] and int(x) not in start[t]:
                    start[t].append(int(x))
        for t in teams:
            s = start[t][:5]
            if p == 1:
                starters_pbp[t] = set(s)          # inferred from pbp alone (before any fill), for validation
            if len(s) < 5:   # silent players: carry over from previous period end, never someone who subbed in first
                for x in (prev_end[t] if p > 1 else starters_box[t]):
                    if len(s) >= 5:
                        break
                    if x not in s and x not in seen_in[t]:
                        s.append(x)
            if p == 1:
                if len(starters_box[t]) == 5:      # box starter flags are authoritative for the period-1 lineup
                    s = list(starters_box[t])
            on[t] = set(s)
            pdiag[(t, p)] = len(s)
        for i in idx:
            if is_sub[i]:
                pin, pout = a1[i], a2[i]
                t = roster.get(int(pout)) if pout == pout else roster.get(int(pin)) if pin == pin else None
                if t in teams:
                    if pout == pout:
                        on[t].discard(int(pout))
                    if pin == pin:
                        on[t].add(int(pin))
            lineup_at[i] = (frozenset(on[hid]), frozenset(on[aid]))
        for t in teams:
            prev_end[t] = set(on[t])
    # --- stints: walk events, attribute elapsed time / points / possessions to the lineup in force
    st = {t: (box_starters.get(t) and set(box_starters[t])) or starters_pbp.get(t, set()) for t in teams}
    agg = {t: dict(poss=0, pts_pbp=0.0, su_sec=0.0, su_pf=0.0, su_pa=0.0, su_pos_f=0, su_pos_a=0,
                   bn_sec=0.0, bn_pf=0.0, bn_pa=0.0, bn_pos_f=0, bn_pos_a=0, bad5_sec=0.0,
                   st_sec_q1=0.0, st_sec_q2=0.0, st_sec_q3=0.0, st_sec_q4=0.0, lineups=set()) for t in teams}
    pl = {}
    cur_pos, last_el, last_h, last_a, last_p = None, 0.0, 0.0, 0.0, 1
    for i in range(n):
        lu = lineup_at[i]
        if lu is None:
            continue
        p = per[i]
        if p != last_p:
            cur_pos = None
            last_el = max(last_el, period_start(p))   # never re-count time if period numbers go back
            last_p = p
        dt = max(el[i] - last_el, 0.0) if el[i] == el[i] else 0.0
        dh, da = hs[i] - last_h, as_[i] - last_a
        newpos = pos_team[i] is not None and pos_team[i] != cur_pos
        if newpos:
            cur_pos = pos_team[i]
        for t, mine, opp_lu in ((hid, lu[0], lu[1]), (aid, lu[1], lu[0])):
            pf, pa = (dh, da) if t == hid else (da, dh)
            A = agg[t]
            A["lineups"].add(mine)
            ns = len(mine & st[t])
            pf_pos = 1 if newpos and cur_pos == t else 0
            pa_pos = 1 if newpos and cur_pos != t else 0
            A["poss"] += pf_pos
            A["pts_pbp"] += pf
            if len(mine) != 5:
                A["bad5_sec"] += dt
            if ns == 5:
                A["su_sec"] += dt; A["su_pf"] += pf; A["su_pa"] += pa; A["su_pos_f"] += pf_pos; A["su_pos_a"] += pa_pos
            elif ns <= 2:
                A["bn_sec"] += dt; A["bn_pf"] += pf; A["bn_pa"] += pa; A["bn_pos_f"] += pf_pos; A["bn_pos_a"] += pa_pos
            if p <= 4:
                A[f"st_sec_q{p}"] += dt * ns
            for x in mine:
                r = pl.setdefault((t, x), [0.0, 0.0, 0.0, 0, 0])
                r[0] += dt; r[1] += pf; r[2] += pa; r[3] += pf_pos; r[4] += pa_pos
        last_el, last_h, last_a = (max(last_el, el[i]) if el[i] == el[i] else last_el), hs[i], as_[i]   # monotone clock
    rows = []
    for t in teams:
        A = agg[t]
        A["n_lineups"] = len(A.pop("lineups"))
        o = aid if t == hid else hid
        rows.append(dict(team_id=t, opp_id=o, home=int(t == hid), **A,
                         pbp_final=float(hs[-1] if t == hid else as_[-1]), n_periods=int(max(periods)),
                         starters=" ".join(str(x) for x in sorted(st[t])), n_starters=len(st[t]),
                         starters_pbp_match=int(starters_pbp.get(t, set()) == starters_box[t]) if len(starters_box[t]) == 5 else -1,
                         period_lineup_short=int(sum(1 for (tt_, _), v in pdiag.items() if tt_ == t and v < 5))))
    prow = [dict(team_id=t, athlete_id=x, on_sec=v[0], on_pf=v[1], on_pa=v[2], on_pos_f=v[3], on_pos_a=v[4],
                 started=int(x in st[t])) for (t, x), v in pl.items()]
    return rows, prow


def build_season(args):
    a, s = args
    pbp = pd.read_parquet(pbp_path(a, s), columns=COLS)
    pbp = pbp[pbp.season_type.isin([2, 3])]
    box = pd.read_parquet(f"{a.raw}/espn_nba_player_boxscores/player_box_{s}.parquet",
                          columns=["game_id", "athlete_id", "team_id", "starter", "minutes"])
    box = box.dropna(subset=["athlete_id"])
    rost = {gid: dict(zip(z.athlete_id.astype(int), z.team_id.astype(int))) for gid, z in box.groupby("game_id")}
    stb = {gid: {int(t): list(zz[zz.starter.fillna(False).astype(bool)].athlete_id.astype(int)) for t, zz in z.groupby("team_id")}
           for gid, z in box.groupby("game_id")}
    T, P, fail = [], [], []
    for gid, g in pbp.groupby("game_id", sort=False):
        gid = int(gid)
        if gid not in rost:
            fail.append((gid, "no_player_box"))
            continue
        try:
            rows, prow = game_rows(g, rost[gid], stb.get(gid, {}))
        except Exception as e:  # noqa: BLE001 - counted and reported
            fail.append((gid, f"error:{type(e).__name__}"))
            continue
        for r in rows:
            r.update(game_id=gid, season=s, season_type=int(g.season_type.iloc[0]), date=str(g.game_date.iloc[0])[:10])
        for r in prow:
            r.update(game_id=gid, season=s)
        T += rows
        P += prow
    return pd.DataFrame(T), pd.DataFrame(P), fail


def box_validation(T: pd.DataFrame, raw: str) -> pd.DataFrame:
    tb = pd.concat([pd.read_parquet(f"{raw}/espn_nba_team_boxscores/team_box_{s}.parquet") for s in SEASONS])
    tb = tb[["game_id", "team_id", "team_score", "field_goals_attempted", "offensive_rebounds", "turnovers", "total_turnovers",
             "free_throws_attempted"]].copy()
    tb["poss_box"] = tb.field_goals_attempted - tb.offensive_rebounds + tb.total_turnovers.fillna(tb.turnovers) + 0.44 * tb.free_throws_attempted
    tb = tb.drop_duplicates(["game_id", "team_id"])
    T = T.merge(tb[["game_id", "team_id", "team_score", "poss_box"]], on=["game_id", "team_id"], how="left")
    T["score_ok"] = (T.pbp_final == T.team_score).astype(int)
    return T


def derive(T: pd.DataFrame) -> pd.DataFrame:
    T = T.copy()
    o = T[["game_id", "team_id", "poss", "pbp_final"]].rename(columns={"team_id": "opp_id", "poss": "opp_poss", "pbp_final": "opp_pts"})
    T = T.merge(o, on=["game_id", "opp_id"], how="left")
    mins = 48 + 5 * (T.n_periods - 4).clip(lower=0)
    T["poss_game"] = (T.poss + T.opp_poss) / 2
    T["pace48"] = T.poss_game * 48 / mins
    T["ortg"] = 100 * T.pbp_final / T.poss_game
    T["drtg"] = 100 * T.opp_pts / T.poss_game
    T["su_share"] = T.su_sec / (60 * mins)
    T["su_net"] = 100 * (T.su_pf - T.su_pa) / ((T.su_pos_f + T.su_pos_a) / 2).clip(lower=1)
    T["bn_share"] = T.bn_sec / (60 * mins)
    T["bn_net"] = 100 * (T.bn_pf - T.bn_pa) / ((T.bn_pos_f + T.bn_pos_a) / 2).clip(lower=1)
    for q in (1, 2, 3, 4):
        T[f"st_min_q{q}"] = T[f"st_sec_q{q}"] / 60          # summed over the 5 starters (max 60)
    return T


def _ewm_prior(df, key, cols, hl, order):
    """EWM of earlier rows only (shift before ewm) within `key`, rows ordered by `order`. Returns aligned frame."""
    df = df.sort_values(order, kind="stable")
    g = df.groupby(key, sort=False)[cols]
    out = g.transform(lambda s: s.shift(1).ewm(halflife=hl, ignore_na=True).mean())
    out["n_prior"] = df.groupby(key, sort=False).cumcount()
    return out.loc[df.index]


def pregame_features(T: pd.DataFrame, PL: pd.DataFrame) -> pd.DataFrame:
    T = T.copy()
    T["date"] = pd.to_datetime(T["date"])
    base = ["pace48", "ortg", "drtg", "su_share", "su_net", "bn_share", "bn_net", "st_min_q1", "st_min_q2"]
    # team rolling (prior games; same-date games cannot exist for one team)
    r = _ewm_prior(T, "team_id", base, HL_TEAM, ["date", "game_id"])
    F = T[["game_id", "team_id", "opp_id", "home", "season", "season_type", "date", "starters"]].copy()
    for c in base:
        F[f"pre_{c}"] = r[c]
    F["pre_n_games"] = r["n_prior"]
    # player rolling on-court ratings (prior games only), then actual starting five vs the team's recent starters
    PL = PL.merge(T[["game_id", "team_id", "date"]], on=["game_id", "team_id"], how="left")
    PL["date"] = pd.to_datetime(PL["date"])
    PL = PL.sort_values(["athlete_id", "date", "game_id"], kind="stable")
    for c in ("on_sec", "on_pf", "on_pa", "on_pos_f", "on_pos_a"):
        PL[f"c_{c}"] = PL.groupby("athlete_id")[c].transform(lambda s: s.shift(1).ewm(halflife=HL_PLAYER, ignore_na=True).mean())
    # shrink to league average (0 net) with a 250 on-court-minute prior, as in PAG's player prior
    n_prior = PL.groupby("athlete_id").cumcount()
    w = PL.c_on_sec.fillna(0) / 60 * np.minimum(n_prior, 2 * HL_PLAYER)
    raw = 100 * (PL.c_on_pf - PL.c_on_pa) / ((PL.c_on_pos_f + PL.c_on_pos_a) / 2).clip(lower=0.5)
    PL["p_net"] = raw.fillna(0) * (w / (w + 250.0))
    PL["p_min"] = PL.c_on_sec.fillna(0) / 60
    s5 = PL[PL.started == 1].groupby(["game_id", "team_id"]).agg(st5_net=("p_net", "mean"), st5_min=("p_min", "mean"))
    F = F.merge(s5.reset_index(), on=["game_id", "team_id"], how="left")
    # "expected" starters: the team's 5 most frequent starters over its previous 10 games -> how many of tonight's are new
    T2 = T.sort_values(["date", "game_id"])
    exp_new = {}
    for t, z in T2.groupby("team_id", sort=False):
        hist = []
        for gid, s in zip(z.game_id, z.starters):
            cur = set(s.split())
            if hist:
                cnt = pd.Series([x for h in hist[-10:] for x in h]).value_counts()
                exp = set(cnt.index[:5])
                exp_new[(gid, t)] = len(cur - exp)
            hist.append(cur)
    F["st5_n_unexpected"] = [exp_new.get((g, t), np.nan) for g, t in zip(F.game_id, F.team_id)]
    return F


def leak_check(T: pd.DataFrame, PL: pd.DataFrame, F: pd.DataFrame, n_dates: int = 6, seed: int = 0) -> dict:
    """Truncation test: rebuild features from games strictly before date d plus the games of d itself (whose own
    outcomes must not matter) and compare with the full-history features for date d."""
    rng = np.random.default_rng(seed)
    T = T.copy()
    T["date"] = pd.to_datetime(T["date"])
    dates = rng.choice(T["date"].drop_duplicates().sort_values().iloc[200:].to_numpy(), n_dates, replace=False)
    cols = [c for c in F.columns if c.startswith(("pre_", "st5_"))]
    maxdiff = 0.0
    for d in dates:
        keep = T[T["date"] <= d].copy()
        today = keep["date"] == d
        for c in ("pace48", "ortg", "drtg", "su_share", "su_net", "bn_share", "bn_net", "st_min_q1", "st_min_q2"):
            keep.loc[today, c] = np.nan if c != "pace48" else 1e6     # scramble same-day outcomes
        pk = PL[PL.game_id.isin(keep.game_id)].copy()
        tg = set(keep[today].game_id)
        pk.loc[pk.game_id.isin(tg), ["on_sec", "on_pf", "on_pa", "on_pos_f", "on_pos_a"]] = 9e5
        Fk = pregame_features(keep, pk)
        a = Fk[Fk.game_id.isin(tg)].set_index(["game_id", "team_id"])[cols].sort_index()
        b = F[F.game_id.isin(tg)].set_index(["game_id", "team_id"])[cols].sort_index()
        dd = (a - b).abs().to_numpy()
        dd = dd[~(np.isnan(a.to_numpy()) & np.isnan(b.to_numpy()))]
        maxdiff = max(maxdiff, float(np.nanmax(dd)) if dd.size else 0.0)
    assert maxdiff < 1e-9, f"point-in-time violation: max diff {maxdiff}"
    return {"dates_checked": [str(pd.Timestamp(x).date()) for x in dates], "max_abs_diff": maxdiff}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbp-old", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    with Pool(a.procs) as pool:
        res = pool.map(build_season, [(a, s) for s in SEASONS])
    T = pd.concat([r[0] for r in res], ignore_index=True)
    PL = pd.concat([r[1] for r in res], ignore_index=True)
    fails = [f for r in res for f in r[2]]
    T = derive(box_validation(T, a.raw))
    F = pregame_features(T, PL)
    lc = leak_check(T, PL, F)
    os.makedirs(a.out, exist_ok=True)
    paths = {k: f"{a.out}/{k}.csv.gz" for k in ("pbp_game_team", "pbp_player_game", "pbp_pregame_features")}
    T.to_csv(paths["pbp_game_team"], index=False, float_format="%.4f")
    PL.to_csv(paths["pbp_player_game"], index=False, float_format="%.3f")
    F.to_csv(paths["pbp_pregame_features"], index=False, float_format="%.5f")
    v = {}
    for s, z in T.groupby("season"):
        sb = z[z.starters_pbp_match >= 0]
        v[int(s)] = {"games": int(z.game_id.nunique()), "team_rows": len(z),
                     "score_reconciled": round(float(z.score_ok.mean()), 4),
                     "poss_event_vs_box_mean_abs": round(float((z.poss - z.poss_box).abs().mean()), 2),
                     "poss_event_vs_box_corr": round(float(np.corrcoef(z.poss.fillna(0), z.poss_box.fillna(0))[0, 1]), 3),
                     "poss_event_minus_box_mean": round(float((z.poss - z.poss_box).mean()), 2),
                     "starters_box_5_rate": round(float((z.n_starters == 5).mean()), 4),
                     "pbp_inferred_starters_eq_box_rate": round(float(sb.starters_pbp_match.mean()), 4) if len(sb) else None,
                     "lineup_not5_seconds_share": round(float(z.bad5_sec.sum() / (z.n_periods.clip(upper=4) * 720 + (z.n_periods - 4).clip(lower=0) * 300).sum()), 5),
                     "failures": sum(1 for f in fails if f[0] in set(z.game_id))}
    man = {"seasons": [int(s) for s in SEASONS], "validation_by_season": v,
           "failures_total": len(fails), "failure_reasons": pd.Series([f[1] for f in fails]).value_counts().to_dict(),
           "leak_check": lc, "rows": {"pbp_game_team": len(T), "pbp_player_game": len(PL), "pbp_pregame_features": len(F)},
           "files": {k: {"path": os.path.basename(p), "sha256": sha(p), "bytes": os.path.getsize(p)} for k, p in paths.items()},
           "half_lives": {"team": HL_TEAM, "player": HL_PLAYER}}
    json.dump(man, open(f"{a.out}/build_manifest.json", "w"), indent=1, default=str)
    print(json.dumps(man, indent=1, default=str))


if __name__ == "__main__":
    main()
