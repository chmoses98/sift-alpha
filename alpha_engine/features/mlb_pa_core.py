"""MLB plate-appearance tables from the archived post-game feeds, shared by the batch-7 builders (mlb_pitcher_ext7, mlb_team_ext7). RESEARCH_ONLY.

Raw: sift-data-vault archives/MLB/postgame_feed_compact/<season> (MLB Stats API game feed, compacted by tools/collectors/mlb_statsapi.py; one JSON per final game).
Rights: MLBAM terms (individual non-commercial non-bulk); tier UNRESOLVED_INTERNAL_ONLY. Internal research only. No market price enters.

CHRONOLOGY (same rule as mlb_line amendment 1): a game is dated by its FIRST PITCH (`datetime.officialDate`); its plays become usable history only for rows dated
STRICTLY AFTER `avail_date` = `datetime.resumeDate` when present (suspended, completed later), else officialDate. A row's own game is never history.
The starting pitcher of a game (box `pitchers[0]`) is an AS-PLAYED fact: it is used only for EARLIER games (whose starts define rotations and times-through-order samples),
never for the game being featured. Pregame probable-pitcher snapshots do not exist in the archive (the feed's `probables` field is a post-game value and is never read).

Tables
  games: game_id, season, game_date, avail_date, gtype, home, away, h_r, a_r (linescore run totals), home_sp, away_sp
  pa:    one row per plate appearance (plays whose event does not start with an excluded prefix), in feed order: game_id, ab, inn, top (bool), bat, pit, stand, throws, event,
         n_pitch, n_called (pitch code C), n_whiff (S W T M Q), n_swing (S W T M Q F L O X D E)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

TYPES = ("R", "F", "D", "L", "W")
NON_PA_PREFIX = ("caught_stealing", "pickoff", "stolen_base", "wild_pitch", "passed_ball", "balk", "other_advance", "other_out", "runner", "defensive_indiff", "game_advisory", "ejection")
WHIFF = {"S", "W", "T", "M", "Q"}
SWING = WHIFF | {"F", "L", "O", "X", "D", "E"}
STRIKEOUT = {"strikeout", "strikeout_double_play"}
WALK = {"walk", "intent_walk"}
# fixed linear weights (a typical recent-season wOBA scale; the catalog's wRC+ needs season constants and park factors, see specs)
WOBA_W = {"walk": 0.69, "hit_by_pitch": 0.72, "single": 0.88, "double": 1.25, "triple": 1.58, "home_run": 2.03}
WOBA_EXCLUDE = {"intent_walk", "sac_bunt", "catcher_interf"}
GAME_CONTENT = ["h_r", "a_r", "home_sp", "away_sp"]
PA_CONTENT = ["bat", "pit", "stand", "throws", "event", "n_pitch", "n_called", "n_whiff", "n_swing"]


def _parse(j: dict):
    try:
        if j["game"]["type"] not in TYPES or j["status"]["codedGameState"] != "F":
            return None, []
        inn = j["linescore"]["innings"]; dt = j["datetime"]
        g = {"game_id": int(j["pk"]), "season": int(j["game"]["season"]), "game_date": dt["officialDate"], "avail_date": dt.get("resumeDate") or dt["officialDate"], "gtype": j["game"]["type"],
             "home": int(j["teams"]["home"]["id"]), "away": int(j["teams"]["away"]["id"]),
             "h_r": float(sum(float((x.get("home") or {}).get("runs") or 0) for x in inn)), "a_r": float(sum(float((x.get("away") or {}).get("runs") or 0) for x in inn))}
    except (KeyError, ValueError, TypeError):
        return None, []
    for s, side in (("home_sp", "home"), ("away_sp", "away")):
        try:
            g[s] = float(j["box"][side]["pitchers"][0])
        except (KeyError, IndexError, TypeError, ValueError):
            g[s] = np.nan
    rows = []
    for p in j.get("plays") or []:
        ev = p.get("event")
        if not isinstance(ev, str) or ev.startswith(NON_PA_PREFIX) or p.get("bat") is None or p.get("pit") is None:
            continue
        codes = [q.get("code") for q in (p.get("pitches") or [])]
        rows.append({"game_id": g["game_id"], "ab": int(p["ab"]), "inn": int(p.get("inn") or 0), "top": p.get("half") == "top", "bat": int(p["bat"]), "pit": int(p["pit"]),
                     "stand": p.get("stand"), "throws": p.get("throws"), "event": ev, "n_pitch": float(len(codes)), "n_called": float(sum(c == "C" for c in codes)),
                     "n_whiff": float(sum(c in WHIFF for c in codes)), "n_swing": float(sum(c in SWING for c in codes))})
    return g, rows


def load_raw(dirs) -> dict:
    """dirs: comma-separated restored season directories (or a directory holding cached games.parquet + pa.parquet written by cache())."""
    d0 = Path(str(dirs).split(",")[0])
    if (d0 / "games.parquet").exists() and (d0 / "pa.parquet").exists():
        return _split({"games": pd.read_parquet(d0 / "games.parquet"), "pa": pd.read_parquet(d0 / "pa.parquet")})
    gs, ps = [], []
    for d in str(dirs).split(","):
        for f in sorted(Path(d).glob("*.json")):
            if f.name.startswith("_"):
                continue
            g, rows = _parse(json.loads(f.read_text()))
            if g:
                gs.append(g); ps.extend(rows)
    games = pd.DataFrame(gs).drop_duplicates("game_id").sort_values(["game_date", "game_id"], kind="mergesort").reset_index(drop=True)
    pa = pd.DataFrame(ps)
    pa = pa[pa.game_id.isin(set(games.game_id))].sort_values(["game_id", "ab"], kind="mergesort").reset_index(drop=True)
    return _split({"games": games, "pa": pa})


WARM_BEFORE = 2023      # first output season of the batch-7 builders


def _split(r: dict) -> dict:
    """Harness wiring (same precedent as nfl_player_ext5): seasons before the first output season are history only and go to games_warm / pa_warm, which precede
    every replay cut and are never truncated or permuted."""
    w = r["games"].season < WARM_BEFORE; wid = set(r["games"].game_id[w])
    pw = r["pa"].game_id.isin(wid)
    return {"games": r["games"][~w].reset_index(drop=True), "pa": r["pa"][~pw].reset_index(drop=True),
            "games_warm": r["games"][w].reset_index(drop=True), "pa_warm": r["pa"][pw].reset_index(drop=True)}


def _all(raw: dict, key: str) -> pd.DataFrame:
    parts = [raw[k] for k in (key + "_warm", key) if raw.get(k) is not None and len(raw[k])]
    return pd.concat(parts, ignore_index=True) if parts else raw[key]


def cache(dirs, out) -> None:
    r = load_raw(dirs); Path(out).mkdir(parents=True, exist_ok=True)
    _all(r, "games").to_parquet(Path(out) / "games.parquet", index=False); _all(r, "pa").to_parquet(Path(out) / "pa.parquet", index=False)


def prepared(raw: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """games with date / avail as Timestamps; pa joined to its game with batting / fielding team, pitcher-start flag, batters-faced index and outcome flags."""
    g = _all(raw, "games").copy(); g["date"] = pd.to_datetime(g.game_date); g["avail"] = pd.to_datetime(g.avail_date)
    p = _all(raw, "pa").merge(g[["game_id", "season", "date", "avail", "home", "away", "home_sp", "away_sp"]], on="game_id", how="inner")
    top = p["top"].astype(bool).to_numpy()
    p["bat_team"] = np.where(top, p.away, p.home); p["fld_team"] = np.where(top, p.home, p.away)
    sp = np.where(top, p.home_sp, p.away_sp)
    p["is_start"] = (p.pit.astype(float).to_numpy() == sp)
    p = p.sort_values(["game_id", "ab"], kind="mergesort").reset_index(drop=True)
    p["bf_i"] = p.groupby(["game_id", "pit"], sort=False).cumcount() + 1
    ev = p.event.astype(str)
    p["k"] = ev.isin(STRIKEOUT).astype(float); p["bb"] = ev.isin(WALK).astype(float)
    p["woba_num"] = ev.map(WOBA_W).fillna(0.0).astype(float); p["woba_den"] = (~ev.isin(WOBA_EXCLUDE)).astype(float)
    p["csw"] = p.n_called + p.n_whiff
    return g, p


def league(p: pd.DataFrame, season: int) -> dict:
    """League constants of season `season` (computed from that season's PAs; used for rows of season + 1)."""
    q = p[p.season == season]
    out = {"k": q.k.sum() / len(q), "csw": q.csw.sum() / q.n_pitch.sum(), "whiff": q.n_whiff.sum() / q.n_swing.sum(), "woba": q.woba_num.sum() / q.woba_den.sum()}
    for h in ("R", "L"):
        qh = q[q.throws == h]
        out[f"k_{h}"] = qh.k.sum() / len(qh); out[f"woba_{h}"] = qh.woba_num.sum() / qh.woba_den.sum()
    s = q[q.is_start]
    for t in (1, 2, 3):
        st = s[np.minimum((s.bf_i + 8) // 9, 3) == t]
        out[f"tto_k_{t}"] = st.k.sum() / len(st); out[f"tto_bb_{t}"] = st.bb.sum() / len(st); out[f"tto_woba_{t}"] = st.woba_num.sum() / st.woba_den.sum()
    bf = s.groupby(["game_id", "pit"]).size().to_numpy(float)     # starters' BF per start
    for t in (1, 2, 3):
        out[f"tto_bf_{t}"] = float(np.minimum(np.maximum(bf - 9 * (t - 1), 0), 9).mean())
    return out


def team_games(g: pd.DataFrame) -> pd.DataFrame:
    rows = [g.assign(team=g[a].astype(int), opp=g[b].astype(int), runs=g[ra], runs_allowed=g[rb]) for a, b, ra, rb in (("home", "away", "h_r", "a_r"), ("away", "home", "a_r", "h_r"))]
    t = pd.concat(rows, ignore_index=True)[["game_id", "season", "date", "avail", "team", "opp", "runs", "runs_allowed"]]
    return t.sort_values(["team", "date", "game_id"], kind="mergesort").reset_index(drop=True)


def last_n_games(tg: pd.DataFrame, rows: pd.DataFrame, n: int) -> pd.DataFrame:
    """For each row (game_id, team, date): the team's last n games with avail < date (ordered by (date, game_id)). Returns (game_id, team, prev_gid)."""
    out = []
    for team, r in rows.groupby("team", sort=True):
        h = tg[tg.team == team]
        hd = h.date.to_numpy(); ha = h.avail.to_numpy(); hg = h.game_id.to_numpy()
        for gid, d in zip(r.game_id.to_numpy(), r.date.to_numpy()):
            ok = np.flatnonzero(ha < d)
            if len(ok) == 0:
                continue
            ok = ok[np.lexsort((hg[ok], hd[ok]))][-n:]
            out.append(pd.DataFrame({"game_id": gid, "team": team, "prev_gid": hg[ok]}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["game_id", "team", "prev_gid"])


def window_sums(p: pd.DataFrame, key: str, rows: pd.DataFrame, cols: list[str], by_extra: str | None = None) -> pd.DataFrame:
    """For each row (row_id, key value, date, season): sums of `cols` over PAs of that key with avail < date and season >= row season - 1 (optionally split by `by_extra`).
    Cumulative-sum lookup by avail date: PAs sorted by (key, avail); for each row take the cumulative sums up to the last PA with avail < date, minus those before season S-1."""
    grp = [key] + ([by_extra] if by_extra else [])
    q = p[grp + ["avail", "season"] + cols].copy()
    agg = q.groupby(grp + ["avail", "season"], sort=True)[cols].sum().reset_index().sort_values(grp + ["avail"], kind="mergesort")
    cs = agg.groupby(grp, sort=False)[cols].cumsum(); agg[[c + "_cs" for c in cols]] = cs.to_numpy()
    # cumulative sum as of the end of each season (to subtract everything before season S-1)
    res = rows.copy()
    lk = pd.merge_asof(res.sort_values("date").rename(columns={"date": "avail"}), agg.sort_values("avail")[grp + ["avail"] + [c + "_cs" for c in cols]],
                       on="avail", by=grp, allow_exact_matches=False, direction="backward").rename(columns={"avail": "date"})
    first = pd.to_datetime((res.season - 1).astype(str) + "-01-01")
    lk0 = pd.merge_asof(res.assign(avail=first.to_numpy()).sort_values("avail"), agg.sort_values("avail")[grp + ["avail"] + [c + "_cs" for c in cols]],
                        on="avail", by=grp, allow_exact_matches=False, direction="backward")
    a = lk.set_index("row_id").sort_index(); b = lk0.set_index("row_id").sort_index()
    out = pd.DataFrame(index=a.index)
    for c in cols:
        out[c] = a[c + "_cs"].fillna(0.0) - b[c + "_cs"].fillna(0.0)
    return out
