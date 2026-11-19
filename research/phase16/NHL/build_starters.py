"""Historical starting-goalie table (one row per regular-season team-game), with provenance.

Sources, in priority order (no new bulk collection; see RESULTS.md on NHL api-web terms):
  1. boxscore_refresh_2026  api-web boxscore starter flag, fetched once 2026-11-18 for 2026-27 games through 2026-11-17 (data/raw/starters_2026.jsonl)
  2. boxscore_repo          repo data/history/players/goalies_{2021..2026}.parquet (api-web boxscore `starter` flag, official)
  3. moneypuck_first_shot   repo MoneyPuck shot rows 2008-2025: the goalie who faced his team's first shot (proxy; agreement measured on 2021-25)
Output: data/starters_history.csv.gz
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

REPO = Path("/home/user/NHL-edge-finder"); H = REPO / "data/history"; OUT = Path(__file__).parent

def nhl_games():
    g = pd.concat([pd.read_parquet(p) for p in sorted((H / "nhl").glob("games_*.parquet"))])
    g = g[g.game_type == 2]
    return g[["game_id", "season", "game_date", "home_team_id", "away_team_id", "home_abbrev", "away_abbrev"]].drop_duplicates("game_id")

def moneypuck_rows(games):
    paths = sorted((H / "shots_extension").glob("shots_*.parquet")) + sorted((H / "moneypuck").glob("shots_*.parquet"))
    s = pd.concat([pd.read_parquet(p, columns=["season", "nhl_game_id", "isPlayoffGame", "isHomeTeam", "period", "time", "goalieIdForShot", "goalieNameForShot", "shotOnEmptyNet"]) for p in paths])
    s = s[(s.isPlayoffGame == 0) & (s.goalieIdForShot > 0) & (s.period.between(1, 4))]
    s["is_home"] = s.isHomeTeam == 0          # defending side
    first = s.sort_values("time").groupby(["nhl_game_id", "is_home"]).head(1)
    n_g = s.groupby(["nhl_game_id", "is_home"]).goalieIdForShot.nunique().rename("n_goalies_played")
    r = first.merge(n_g, left_on=["nhl_game_id", "is_home"], right_index=True)
    r = r.rename(columns={"nhl_game_id": "game_id", "goalieIdForShot": "starter_id", "goalieNameForShot": "starter_name"})
    r["source"] = "moneypuck_first_shot"; r["source_ref"] = "data/history/{shots_extension,moneypuck}/shots_<season>.parquet"
    return r[["game_id", "is_home", "starter_id", "starter_name", "n_goalies_played", "source", "source_ref"]]

def boxscore_repo_rows():
    rows = []
    for p in sorted((H / "players").glob("goalies_*.parquet")):
        g = pd.read_parquet(p); g = g[(g.game_type == 2)]
        played = g[g.toi_s > 0].groupby(["game_id", "is_home"]).player_id.nunique().rename("n_goalies_played")
        st = g[g.starter.astype(bool)].merge(played, left_on=["game_id", "is_home"], right_index=True, how="left")
        st = st.rename(columns={"player_id": "starter_id", "name": "starter_name"})
        st["source"] = "boxscore_repo"; st["source_ref"] = f"data/history/players/{p.name} (api-web boxscore starter flag)"
        rows.append(st[["game_id", "is_home", "starter_id", "starter_name", "n_goalies_played", "source", "source_ref", "game_date", "home_team_id", "away_team_id"]])
    r = pd.concat(rows); r["is_home"] = r.is_home.astype(bool)
    return r

def refresh_rows():
    p = OUT / "data/raw/starters_2026.jsonl"
    if not p.exists(): return None
    d = pd.read_json(p, lines=True)
    d = d[d.starter_id.notna()]
    d["source"] = "boxscore_refresh_2026"
    d["source_ref"] = d.source_url + " @ " + d.fetched_at_utc + " sha256=" + d.response_sha256.str[:16]
    return d.rename(columns={"is_home": "is_home"})[["game_id", "is_home", "starter_id", "starter_name", "n_goalies_played", "source", "source_ref",
                                                     "season", "game_date", "team_id", "opp_team_id", "team"]]

def main():
    games = nhl_games()
    mp, bx, rf = moneypuck_rows(games), boxscore_repo_rows(), refresh_rows()
    # agreement of the MoneyPuck proxy with the official flag where both exist
    j = mp.merge(bx, on=["game_id", "is_home"], suffixes=("_mp", "_bx"))
    agree = {"n_team_games": int(len(j)), "agree": float((j.starter_id_mp == j.starter_id_bx).mean())}
    comb = pd.concat([x for x in (rf, bx, mp) if x is not None])
    pri = {"boxscore_refresh_2026": 0, "boxscore_repo": 1, "moneypuck_first_shot": 2}
    comb["_p"] = comb.source.map(pri)
    comb = comb.sort_values("_p").drop_duplicates(["game_id", "is_home"]).drop(columns="_p")
    # attach game metadata (schedule from repo history; 2026-27 refresh rows carry their own)
    gm = games.set_index("game_id")
    def side(r, k):
        return r[f"home_{k}"] if r["is_home"] else r[f"away_{k}"]
    m = comb.merge(games, on="game_id", how="left", suffixes=("", "_g"))
    S = lambda a: pd.Series(a, index=m.index)
    m["game_date"] = m["game_date"].fillna(m["game_date_g"]).astype(str).str[:10]
    for c in ("home_team_id", "away_team_id"): m[c] = m[c].fillna(m[f"{c}_g"])
    m["team_id"] = m["team_id"].fillna(S(np.where(m.is_home, m.home_team_id, m.away_team_id)))
    m["opp_team_id"] = m["opp_team_id"].fillna(S(np.where(m.is_home, m.away_team_id, m.home_team_id)))
    ab = pd.concat([games[["home_team_id", "home_abbrev"]].set_axis(["tid", "ab"], axis=1), games[["away_team_id", "away_abbrev"]].set_axis(["tid", "ab"], axis=1)]).drop_duplicates("tid", keep="last").set_index("tid").ab
    m["team"] = m["team"].fillna(m.team_id.map(ab))
    m["season"] = (m.game_id // 1_000_000).astype(int)
    m = m.dropna(subset=["game_date"])
    cols = ["game_id", "season", "game_date", "team_id", "team", "opp_team_id", "is_home", "starter_id", "starter_name", "n_goalies_played", "source", "source_ref"]
    m = m[cols].sort_values(["game_date", "game_id", "is_home"]).reset_index(drop=True)
    for c in ("team_id", "opp_team_id", "starter_id"): m[c] = m[c].astype("int64")
    out = OUT / "data/starters_history.csv.gz"; m.to_csv(out, index=False, compression="gzip")
    summ = {"rows": int(len(m)), "games": int(m.game_id.nunique()), "seasons": sorted(int(s) for s in m.season.unique()),
            "by_source": m.source.value_counts().to_dict(), "rows_by_season": m.groupby("season").size().astype(int).to_dict(),
            "moneypuck_vs_boxscore_agreement_2021_25": agree, "file": str(out), "bytes": out.stat().st_size,
            "last_game_date": str(m.game_date.max())}
    (OUT / "results/starters_history_summary.json").write_text(json.dumps(summ, indent=1, default=str))
    print(json.dumps(summ, default=str)[:1500])

if __name__ == "__main__":
    main()
