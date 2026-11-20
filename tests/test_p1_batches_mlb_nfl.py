"""Batches 7 (MLB plate appearances) and 8 (NFL drive model, quarterbacks, skill availability): point-in-time behaviour on synthetic data. RESEARCH_ONLY."""
import numpy as np
import pandas as pd

from alpha_engine.features import mlb_pitcher_ext7 as MP
from alpha_engine.features import mlb_team_ext7 as MT
from alpha_engine.features import nfl_qb_ext8 as NQ
from alpha_engine.features import nfl_skill_ext8 as NS
from alpha_engine.features import nfl_team_ext8 as NT

EVENTS = ["field_out", "strikeout", "single", "walk", "double", "home_run", "hit_by_pitch", "intent_walk", "sac_bunt"]


def _mlb(seed=0, suspend=None):
    """4 teams, seasons 2022-2023, 24 game days each; 6 starters per team; ~30 PAs per half."""
    rng = np.random.default_rng(seed); gs, ps = [], []; pk = 1000
    for season in (2022, 2023):
        for day in range(24):
            d = pd.Timestamp(f"{season}-04-01") + pd.Timedelta(days=day); o = rng.permutation([1, 2, 3, 4])
            for k in range(2):
                pk += 1; h, a = int(o[2 * k]), int(o[2 * k + 1]); avail = d
                if suspend is not None and pk == suspend:
                    avail = d + pd.Timedelta(days=5)
                hs, as_ = 100 * h + int(rng.integers(0, 6)), 100 * a + int(rng.integers(0, 6))
                gs.append(dict(game_id=pk, season=season, game_date=str(d.date()), avail_date=str(avail.date()), gtype="R", home=h, away=a, h_r=float(rng.integers(0, 9)),
                               a_r=float(rng.integers(0, 9)), home_sp=float(hs), away_sp=float(as_)))
                ab = 0
                for top in (True, False):
                    sp = hs if top else as_; bat_t = a if top else h
                    for i in range(30):
                        pit = sp if i < int(rng.integers(15, 27)) else 100 * (h if top else a) + 50
                        n = int(rng.integers(1, 7))
                        ps.append(dict(game_id=pk, ab=ab, inn=1 + i // 4, top=top, bat=1000 * bat_t + int(rng.integers(0, 12)), pit=int(pit), stand="R", throws="L" if pit % 2 else "R",
                                       event=str(rng.choice(EVENTS)), n_pitch=float(n), n_called=float(rng.integers(0, n + 1)), n_whiff=float(rng.integers(0, 2)), n_swing=float(rng.integers(1, 3))))
                        ab += 1
    return MT.C._split({"games": pd.DataFrame(gs), "pa": pd.DataFrame(ps)})


def _cut(raw, cut, gkey="games", date_col="game_date"):
    g = raw[gkey]; keep = g[pd.to_datetime(g[date_col]) < cut]
    out = dict(raw); out[gkey] = keep
    for k in ("pa", "pbp", "injuries"):
        if k in raw:
            out[k] = raw[k][raw[k].game_id.isin(set(keep.game_id))]
    return out


def _same_early(mod, raw, cut, cols, **kw):
    full = mod.compute(raw)["team"]; part = mod.compute(_cut(raw, cut, **kw))["team"]
    a = full[full.date < cut].set_index(["game_id", "team"]); b = part[part.date < cut].set_index(["game_id", "team"])
    assert set(a.index) == set(b.index) and len(a) > 0
    np.testing.assert_allclose(b.loc[a.index, cols].to_numpy(float), a[cols].to_numpy(float), rtol=1e-12, atol=1e-12, equal_nan=True)
    return full


def test_mlb_team_and_pitcher_truncation():
    raw = _mlb()
    f = _same_early(MT, raw, pd.Timestamp("2023-04-15"), MT.ALL)
    assert f[MT.ALL].notna().all().all() and (f.season >= 2023).all()
    p = _same_early(MP, raw, pd.Timestamp("2023-04-15"), MP.ALL)
    assert p[MP.ALL].notna().any().all()


def test_mlb_suspended_game_withheld_until_complete():
    """A game suspended on day d and completed 5 days later must not affect rows dated before its completion (first-pitch dating, result withheld)."""
    sus = 1000 + 2 * 24 + 2 * 3 + 1                      # a 2023 game on day 3
    raw = _mlb(1, suspend=sus)
    g = MT.C._all(raw, "games"); row = g[g.game_id == sus].iloc[0]
    avail = pd.Timestamp(row.avail_date)
    base_t = MT.compute(raw)["team"]; base_p = MP.compute(raw)["team"]
    pa = raw["pa"].copy(); m = pa.game_id == sus
    pa.loc[m, "event"] = "home_run"; pa.loc[m, "n_whiff"] = 9.0
    gg = raw["games"].copy(); gg.loc[gg.game_id == sus, ["h_r", "a_r"]] = 30.0
    alt = {**raw, "pa": pa, "games": gg}
    for mod, base, cols in ((MT, base_t, MT.ALL), (MP, base_p, MP.ALL)):
        new = mod.compute(alt)["team"]; sel = base.date <= avail
        a = base[sel].set_index(["game_id", "team"]); b = new[new.date <= avail].set_index(["game_id", "team"])
        np.testing.assert_allclose(b.loc[a.index, cols].to_numpy(float), a[cols].to_numpy(float), rtol=1e-12, atol=1e-12, equal_nan=True)
        later = new[new.date > avail].set_index(["game_id", "team"]); bl = base[base.date > avail].set_index(["game_id", "team"])
        assert not np.allclose(later.loc[bl.index, cols].to_numpy(float), bl[cols].to_numpy(float), equal_nan=True)


def _nfl(seed=0):
    rng = np.random.default_rng(seed); g, p, inj = [], [], []
    teams = ["KC", "LV", "DEN", "LAC"]
    for season in range(2010, 2016):
        for wk in range(1, 9):
            d = pd.Timestamp(f"{season}-09-05") + pd.Timedelta(days=7 * wk); o = rng.permutation(teams)
            for k in range(2):
                h, a = o[2 * k], o[2 * k + 1]; gid = f"{season}_{wk:02d}_{a}_{h}"
                code = lambda t: "OAK" if (t == "LV" and season < 2012) else t  # noqa: E731
                hs, as_ = float(rng.integers(3, 40)), float(rng.integers(3, 40))
                g.append(dict(game_id=gid, season=season, week=wk, game_type="REG", gameday=str(d.date()), gametime="13:00", home_team=code(h), away_team=code(a),
                              home_score=hs, away_score=as_, location="Home"))
                hsc = asc = 0.0; pid = 0
                for qtr in (1, 2, 3, 4):
                    for t in (h, a):
                        for drv in range(3):
                            res = str(rng.choice(["Touchdown", "Field goal", "Punt", "Turnover"]))
                            for _ in range(6):
                                pid += 1; tg = rng.random() < 0.55; pl = f"{t}_{rng.integers(0, 5)}"; qb = f"{t}_QB{int(rng.random() < 0.1)}"
                                comp = tg and rng.random() < 0.6; intc = tg and not comp and rng.random() < 0.05; td = comp and rng.random() < 0.05
                                if td:
                                    hsc += 7 * (t == h); asc += 7 * (t == a)
                                p.append(dict(game_id=gid, play_id=float(pid), posteam=code(t), defteam=code(a if t == h else h), fixed_drive=float(qtr * 10 + drv + (0 if t == h else 5)),
                                              fixed_drive_result=res, play_type="pass" if tg else "run", qtr=float(qtr), total_home_score=hsc, total_away_score=asc,
                                              two_point_attempt=0.0, qb_scramble=0.0, receiver_player_id=pl if tg else None, rusher_player_id=None if tg else pl,
                                              passer_player_id=qb if tg else None, complete_pass=float(comp), incomplete_pass=float(tg and not comp and not intc),
                                              interception=float(intc), pass_touchdown=float(td), yardline_100=float(rng.integers(1, 99)),
                                              air_yards=float(rng.integers(-3, 30)) if tg else np.nan, cp=float(rng.uniform(0.4, 0.9)) if tg else np.nan))
                for t in (h, a):
                    inj.append(dict(season=season, game_type="REG", team=code(t), week=wk, gsis_id=f"{t}_{rng.integers(0, 5)}", position="WR",
                                    report_status=str(rng.choice(["Out", "Questionable"])), date_modified=str(d.date()) + "T10:00:00Z", game_id=gid))
    games = pd.DataFrame(g); pbp = pd.DataFrame(p); injuries = pd.DataFrame(inj); injuries["team"] = injuries.team.replace({"OAK": "LV"})
    return games, pbp, injuries


def _nfl_raw(games, pbp, warm_before, injuries=None):
    w = games.season < warm_before; wid = set(games.game_id[w])
    r = {"games": games[~w], "games_warm": games[w], "pbp": pbp[~pbp.game_id.isin(wid)], "pbp_warm": pbp[pbp.game_id.isin(wid)]}
    if injuries is not None:
        r["injuries"] = injuries[~injuries.game_id.isin(wid)]
    return r


def test_nfl_team_qb_skill_truncation_and_relocation():
    games, pbp, injuries = _nfl()
    cut = pd.Timestamp("2015-10-10")
    t = _same_early(NT, _nfl_raw(games, pbp, NT.OUT_FIRST), cut, NT.ALL, date_col="gameday")
    assert t[NT.ALL].notna().any().all() and "OAK" not in set(t.team)          # relocated code mapped before every join
    q = _same_early(NQ, _nfl_raw(games, pbp, NQ.OUT_ROWS), cut, NQ.ALL, date_col="gameday")
    assert q[NQ.ALL].notna().any().all()
    s = _same_early(NS, _nfl_raw(games, pbp, NS.OUT_FIRST, injuries), cut, NS.COLS, date_col="gameday")
    assert s[NS.COLS].notna().all().all()


def test_nfl_skill_ignores_reports_modified_after_kickoff():
    games, pbp, injuries = _nfl(3)
    raw = _nfl_raw(games, pbp, NS.OUT_FIRST, injuries); base = NS.compute(raw)["team"]
    late = raw["injuries"].copy(); late["date_modified"] = late.date_modified.str.slice(0, 10) + "T23:59:00Z"     # after a 13:00 ET kickoff
    late["report_status"] = "Out"
    new = NS.compute({**raw, "injuries": pd.concat([raw["injuries"].assign(report_status="Questionable"), late.assign(gsis_id=late.gsis_id + "_x")], ignore_index=True)})["team"]
    q_only = NS.compute({**raw, "injuries": raw["injuries"].assign(report_status="Questionable")})["team"]
    np.testing.assert_allclose(new[NS.COLS].to_numpy(float), q_only[NS.COLS].to_numpy(float), equal_nan=True)
    assert (q_only.ska_n_listed_pre.dropna() == 0).all() and (base.ska_n_listed_pre.dropna() > 0).any()


def test_specs_levels_are_honest():
    for mod in (MT, MP, NT, NQ, NS):
        for s in mod.specs():
            assert s.level in ("PARTIAL", "PROXY") and s.missing, s.catalog_id


def _nba(seed=0):
    from alpha_engine.features import nba_stint_ext10 as NB
    rng = np.random.default_rng(seed); G, E, S_ = [], [], []
    teams = [1, 2, 3, 4]; roster = {t: [-(t * 100 + j) for j in range(8)] for t in teams}
    for i in range(40):
        season = "2024-25" if i < 20 else "2025-26"; d = pd.Timestamp("2024-11-01") + pd.Timedelta(days=2 * i + (300 if i >= 20 else 0)); o = rng.permutation(teams)
        for k in range(2):
            gid = f"espn:{1000 + 2 * i + k}"; h, a = int(o[2 * k]), int(o[2 * k + 1])
            G.append(dict(game_id=gid, season=season, start_time_utc=(d + pd.Timedelta(hours=23)).strftime("%Y-%m-%dT%H:%M:%SZ"), home_team_id=h, away_team_id=a, home_pts=100, away_pts=99,
                          status_completed=True))
            order = 0
            for st in range(4):
                hp = list(rng.choice(roster[h], 5, replace=False)); ap = list(rng.choice(roster[a], 5, replace=False)); start = order
                for _ in range(30):
                    team = h if rng.random() < 0.5 else a; on = hp if team == h else ap; made = rng.random() < 0.45; three = rng.random() < 0.35
                    p1 = int(rng.choice(on)); p2 = int(rng.choice([x for x in on if x != p1])) if made and rng.random() < 0.6 else None
                    E.append(dict(game_id=gid, order=order, type_text="Jump Shot", text="three point" if three else "jumper", team_id=team, p1=p1, p2=p2, scoring_play=made,
                                  score_value=(3 if three else 2) if made else 0, shooting_play=True)); order += 1
                    if not made:
                        rt = h if rng.random() < 0.3 else a; ron = hp if rt == h else ap
                        E.append(dict(game_id=gid, order=order, type_text="Offensive Rebound" if rt == team else "Defensive Rebound", text="", team_id=rt,
                                      p1=int(rng.choice(ron)) if rng.random() < 0.9 else None, p2=None, scoring_play=False, score_value=0, shooting_play=False)); order += 1
                S_.append(dict(game_id=gid, period=1 + st, start_order=start, end_order=order, seconds=720.0, **{f"home_p{j + 1}": hp[j] for j in range(5)},
                               **{f"away_p{j + 1}": ap[j] for j in range(5)}, home_poss=25, away_poss=25, home_pts=25, away_pts=25, certified=bool(rng.random() < 0.9), home_n=5, away_n=5))
    g = pd.DataFrame(G); g["game_date"] = pd.to_datetime(g.start_time_utc, utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    e = pd.DataFrame(E); e["p1"] = e.p1.astype("Int64"); e["p2"] = e.p2.astype("Int64")
    return NB, {"games": g, "events": e, "stints": pd.DataFrame(S_)}


def test_nba_stint_truncation_and_event_assignment():
    NB, raw = _nba()
    full = NB.compute(raw)["team"]; cut = pd.Timestamp("2025-09-15")
    keep = set(raw["games"].game_id[raw["games"].game_date < cut])
    part = NB.compute({k: v[v.game_id.isin(keep)] for k, v in raw.items()})["team"]
    a = full[full.date < cut].set_index(["game_id", "team"]); b = part[part.date < cut].set_index(["game_id", "team"])
    assert set(a.index) == set(b.index) and len(a)
    np.testing.assert_allclose(b.loc[a.index, NB.ALL].to_numpy(float), a[NB.ALL].to_numpy(float), rtol=1e-12, atol=1e-12, equal_nan=True)
    ev = pd.DataFrame({"game_id": ["g"] * 4, "order": [0, 5, 6, 9]}); st = pd.DataFrame({"game_id": ["g", "g"], "start_order": [0, 6], "end_order": [6, 9], "certified": [True, True]})
    assert list(NB._assign(ev, st)) == [0, 0, 1, -1]                                 # start <= order < end; an event past the last stint has none


def test_mlb_first_inning_chain_exact_cases_and_truncation():
    from alpha_engine.features import mlb_fi_ext11 as FI
    q = np.array([[0, 0, 0, 0, 0.5, 0.5], [0, 0, 0, 1.0, 0, 0], [0.5, 0, 0, 0, 0.5, 0]])
    p = FI.p_no_run(q)
    assert p[0] == 1.0 and p[1] == 0.0
    # walks or outs, 50/50: no run unless 4 walks come before the 3rd out: P(no run) = P(at most 3 walks before 3 outs) = sum_{w=0..3} C(w+2, w) 0.5^(w+3)
    from math import comb
    assert abs(p[2] - sum(comb(w + 2, w) * 0.5 ** (w + 3) for w in range(4))) < 1e-12
    raw = _mlb(5)
    _same_early(FI, raw, pd.Timestamp("2023-04-15"), ["fim_p_score_pre", "fim_p_nrfi_pre"])


def _cfb(seed=0):
    from alpha_engine.features import cfb_drive_ext12 as CD
    rng = np.random.default_rng(seed); G, D, SC = [], [], []; gid = 100
    for season in range(2014, 2018):
        for wk in range(10):
            d = pd.Timestamp(f"{season}-09-01") + pd.Timedelta(days=7 * wk); o = rng.permutation([1, 2, 3, 4, 5, 6])
            for k in range(3):
                gid += 1; h, a = int(o[2 * k]), int(o[2 * k + 1]); G.append(dict(game_id=gid, season=season, game_date=d, home=h, away=a))
                idx = 0; hs = as_ = 0.0; si = 0
                for per in (1, 2, 3, 4):
                    for j in range(6):
                        tm = h if (j + per) % 2 == 0 else a
                        D.append(dict(game_id=gid, idx=idx, team=tm, period=float(per), secs=float(rng.integers(30, 300)), result=str(rng.choice(["punt", "touchdown", "end of half"])),
                                      start_margin=abs(hs - as_))); idx += 1
                        if rng.random() < 0.3:
                            if tm == h: hs += 7
                            else: as_ += 7
                            SC.append(dict(game_id=gid, idx=si, period=float(per), clock=float(900 - 150 * j - 10), home_score=hs, away_score=as_)); si += 1
    g = pd.DataFrame(G); dr = pd.DataFrame(D); sc = pd.DataFrame(SC); w = set(g.game_id[g.season < CD.OUT_FIRST])
    return CD, {"games": g[~g.game_id.isin(w)], "games_warm": g[g.game_id.isin(w)], "drives": dr[~dr.game_id.isin(w)], "drives_warm": dr[dr.game_id.isin(w)],
                "scores": sc[~sc.game_id.isin(w)], "scores_warm": sc[sc.game_id.isin(w)]}


def test_cfb_drive_truncation():
    CD, raw = _cfb()
    full = CD.compute(raw)["team"]; cut = pd.Timestamp("2017-10-01")
    keep = set(raw["games"].game_id[raw["games"].game_date < cut])
    part = CD.compute({k: (v[v.game_id.isin(keep)] if not k.endswith("_warm") else v) for k, v in raw.items()})["team"]
    a = full[full.date < cut].set_index(["game_id", "team"]); b = part[part.date < cut].set_index(["game_id", "team"])
    assert set(a.index) == set(b.index) and len(a)
    np.testing.assert_allclose(b.loc[a.index, CD.ALL].to_numpy(float), a[CD.ALL].to_numpy(float), rtol=1e-12, atol=1e-12, equal_nan=True)
    assert full[CD.ALL].notna().any().all()
