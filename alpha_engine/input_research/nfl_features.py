"""Point-in-time NFL game feature table from free nflverse data (play-by-play, games/lines, injuries, snap counts, players).

Every feature for game G is computed from information available BEFORE G kicked off: team ratings are opponent-adjusted exponentially weighted
means over games strictly before G (with season-boundary regression and a shrinkage prior); injuries are the final Friday-style report rows
combined with each player's PRIOR snap share. Features that are only partially knowable pregame are tagged in FEATURE_META["pit"].
Nothing is fitted here and no outcome of G enters any feature of G.

Raw inputs (all free, github.com/nflverse/nflverse-data release assets): play_by_play_YYYY.parquet, games.csv (spread/total/moneyline/odds,
weather, rest, QB ids), injuries_YYYY.csv, snap_counts_YYYY.csv, players.csv.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HALF_LIFE = 8.0           # games
LAM = 0.5 ** (1.0 / HALF_LIFE)
PRIOR_K = 3.0             # pseudo-games shrinking an unproven rating to league average
SEASON_CARRY = 0.65       # fraction of accumulated evidence carried across the offseason
QB_PRIOR_DROPBACKS = 150.0

# metric -> (what it measures)
OFF_METRICS = ["epa_pass", "epa_rush", "sr", "sack_rate", "qbhit_rate", "expl_pass", "expl_rush", "neutral_pass", "pass_oe", "sec_play",
               "plays", "to_rate", "pen_rate", "score_drive", "third_conv"]

FEATURE_META: dict[str, dict] = {}


def _meta(name, label, group, pit="yes", catalog_ids=(), note=""):
    FEATURE_META[name] = {"label": label, "group": group, "pit": pit, "catalog_ids": list(catalog_ids), "note": note}


# ---------------------------------------------------------------------------------------------------------------- play-by-play aggregation
def team_games_from_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
    d = pbp[(pbp["season_type"].isin(["REG", "POST"])) & pbp["posteam"].notna()].copy()
    scrim = d[(d["pass"] == 1) | (d["rush"] == 1)]
    scrim = scrim[(scrim["qb_kneel"] != 1) & (scrim["qb_spike"] != 1) & scrim["epa"].notna()].copy()
    scrim["dropback"] = (scrim["qb_dropback"] == 1)
    scrim["rush_play"] = (scrim["rush"] == 1) & ~scrim["dropback"]
    scrim = scrim.sort_values(["game_id", "posteam", "play_id"])
    gsr = scrim["game_seconds_remaining"]
    nxt_t = scrim.groupby(["game_id", "posteam", "drive"])["game_seconds_remaining"].shift(-1)
    gap = (gsr - nxt_t)
    neutral = (scrim["wp"].between(0.2, 0.8)) & (scrim["qtr"] <= 3) & (scrim["half_seconds_remaining"] > 120) & (scrim["down"].isin([1, 2]))
    scrim["neutral_gap"] = np.where(neutral & gap.between(3, 60), gap, np.nan)
    scrim["neutral_pass_flag"] = np.where(neutral, scrim["dropback"].astype(float), np.nan)
    scrim["turnover"] = ((scrim["interception"] == 1) | (scrim["fumble_lost"] == 1)).astype(float)
    scrim["expl_p"] = ((scrim["pass"] == 1) & (scrim["yards_gained"] >= 20)).astype(float)
    scrim["expl_r"] = ((scrim["rush"] == 1) & (scrim["yards_gained"] >= 10)).astype(float)
    scrim["sack_f"] = (scrim["sack"] == 1).astype(float)
    scrim["hit_f"] = ((scrim["qb_hit"] == 1) | (scrim["sack"] == 1)).astype(float)
    scrim["pen_f"] = ((scrim["penalty"] == 1) & (scrim["penalty_team"] == scrim["posteam"])).astype(float)
    scrim["third_att"] = (scrim["down"] == 3).astype(float)
    scrim["third_conv"] = ((scrim["down"] == 3) & (scrim["first_down"] == 1)).astype(float)
    db = scrim[scrim["dropback"]]
    ru = scrim[scrim["rush_play"]]
    g = scrim.groupby(["game_id", "posteam"])
    out = pd.DataFrame({
        "plays": g.size(),
        "sr": g["success"].mean(),
        "neutral_pass": g["neutral_pass_flag"].mean(),
        "pass_oe": g["pass_oe"].mean(),
        "sec_play": g["neutral_gap"].mean(),
        "to_rate": g["turnover"].mean(),
        "pen_rate": g["pen_f"].mean(),
        "expl_rush": ru.groupby(["game_id", "posteam"])["expl_r"].mean(),
        "epa_rush": ru.groupby(["game_id", "posteam"])["epa"].mean(),
        "epa_pass": db.groupby(["game_id", "posteam"])["epa"].mean(),
        "expl_pass": db.groupby(["game_id", "posteam"])["expl_p"].mean(),
        "sack_rate": db.groupby(["game_id", "posteam"])["sack_f"].mean(),
        "qbhit_rate": db.groupby(["game_id", "posteam"])["hit_f"].mean(),
        "dropbacks": db.groupby(["game_id", "posteam"]).size(),
        "third_att": g["third_att"].sum(), "third_conv_n": g["third_conv"].sum(),
    }).reset_index()
    out["third_conv"] = out["third_conv_n"] / out["third_att"].replace(0, np.nan)
    # drives
    dr = d[d["fixed_drive"].notna()].groupby(["game_id", "posteam"])["fixed_drive"].nunique().rename("drives").reset_index()
    out = out.merge(dr, on=["game_id", "posteam"], how="left")
    ds = d[d["fixed_drive"].notna()].groupby(["game_id", "posteam", "fixed_drive"])["drive_ended_with_score"].max().groupby(["game_id", "posteam"]).mean().rename("score_drive").reset_index()
    out = out.merge(ds, on=["game_id", "posteam"], how="left")
    # primary passer per team-game
    ps = db.dropna(subset=["passer_player_id"]).groupby(["game_id", "posteam", "passer_player_id"]).agg(n=("epa", "size"), epa=("epa", "sum")).reset_index()
    ps = ps.sort_values(["game_id", "posteam", "n"], ascending=[True, True, False]).drop_duplicates(["game_id", "posteam"])
    out = out.merge(ps.rename(columns={"passer_player_id": "qb_id", "n": "qb_db", "epa": "qb_epa_sum"}), on=["game_id", "posteam"], how="left")
    return out


# ---------------------------------------------------------------------------------------------------------------- loading
def load_pbp(pbp_dir: Path, seasons) -> pd.DataFrame:
    cols = ["game_id", "season", "season_type", "week", "posteam", "defteam", "play_id", "drive", "fixed_drive", "qtr", "down", "wp", "half_seconds_remaining",
            "game_seconds_remaining", "drive_ended_with_score", "pass", "rush", "qb_dropback", "qb_kneel", "qb_spike", "epa", "success", "yards_gained", "interception", "fumble_lost", "sack",
            "qb_hit", "penalty", "penalty_team", "first_down", "pass_oe", "passer_player_id", "home_team", "away_team",
            "passing_yards", "pass_attempt", "air_yards", "cpoe"]
    parts = []
    for s in seasons:
        f = Path(pbp_dir) / f"pbp_{s}.parquet"
        if f.exists():
            p = pd.read_parquet(f)
            parts.append(p[[c for c in cols if c in p.columns]])
    return pd.concat(parts, ignore_index=True)


def american_to_prob(o):
    o = pd.to_numeric(o, errors="coerce")
    return np.where(o < 0, -o / (-o + 100.0), 100.0 / (o + 100.0))


def devig(a, b):
    pa, pb = american_to_prob(a), american_to_prob(b)
    return pa / (pa + pb)


# ---------------------------------------------------------------------------------------------------------------- rolling opponent-adjusted ratings
def rolling_ratings(games: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
    """Sequential (chronological) opponent-adjusted EWMA ratings. Returns one row per game with pregame ratings for home & away.

    Per metric m: rating_off[T] = EWMA of (obs_off - rating_def_pre[opp]) ; rating_def[T] = EWMA of (obs_allowed - rating_off_pre[opp]);
    all in deviations from the running league mean (expanding mean of games BEFORE the current one), so a positive off rating = better than average.
    """
    games = games.sort_values(["gameday", "game_id"]).reset_index(drop=True)
    tgi = tg.set_index(["game_id", "posteam"])
    state = {}  # (team, side, metric) -> [num, den]
    league = {m: [0.0, 0.0] for m in OFF_METRICS}  # running sum/count over team-games before now
    qb_state = {}  # qb id -> [num, den] (epa per dropback deviation, dropback weighted)
    last_season = {}
    last_qb = {}
    rows = []

    def val(team, side, m):
        n, dn = state.get((team, side, m), (0.0, 0.0))
        return n / (dn + PRIOR_K)

    def lg(m):
        s, c = league[m]
        return s / c if c > 0 else np.nan

    for g in games.itertuples(index=False):
        h, a = g.home_team, g.away_team
        for t in (h, a):
            if last_season.get(t) is not None and last_season[t] != g.season:
                for (tt, side, m), v in list(state.items()):
                    if tt == t:
                        state[(tt, side, m)] = [v[0] * SEASON_CARRY, v[1] * SEASON_CARRY]
            last_season[t] = g.season
        rec = {"game_id": g.game_id}
        for tag, t, o in (("h", h, a), ("a", a, h)):
            for m in OFF_METRICS:
                rec[f"{tag}_off_{m}"] = val(t, "off", m)
                rec[f"{tag}_def_{m}"] = val(t, "def", m)
            rec[f"{tag}_games_played"] = state.get((t, "off", "plays"), [0, 0])[1]
        qbs = {}
        for tag, t, qid in (("h", h, g.home_qb_id), ("a", a, g.away_qb_id)):
            n, dn = qb_state.get(qid, (0.0, 0.0)) if isinstance(qid, str) else (0.0, 0.0)
            rec[f"{tag}_qb_epa"] = n / (dn + QB_PRIOR_DROPBACKS)
            rec[f"{tag}_qb_dropbacks_prior"] = dn
            rec[f"{tag}_qb_change"] = float(isinstance(qid, str) and last_qb.get(t) is not None and last_qb[t] != qid)
            qbs[t] = qid
        rows.append(rec)
        # ---- update with this game's result (AFTER features were written)
        have = ((g.game_id, h) in tgi.index) and ((g.game_id, a) in tgi.index)
        if not have:
            continue
        for t, o in ((h, a), (a, h)):
            obs_o, obs_d = tgi.loc[(g.game_id, t)], tgi.loc[(g.game_id, o)]
            for m in OFF_METRICS:
                x_off, x_def = obs_o[m], obs_d[m]
                L = lg(m)
                if np.isnan(L):
                    continue
                if not np.isnan(x_off):
                    adj = (x_off - L) - val(o, "def", m)          # what T did vs what the opponent defence usually allows
                    s = state.setdefault((t, "off", m), [0.0, 0.0]); s[0] = s[0] * LAM + adj; s[1] = s[1] * LAM + 1.0
                if not np.isnan(x_def):
                    adj = (x_def - L) - val(o, "off", m)          # what T allowed vs what the opponent offence usually does
                    s = state.setdefault((t, "def", m), [0.0, 0.0]); s[0] = s[0] * LAM + adj; s[1] = s[1] * LAM + 1.0
        for t in (h, a):
            r = tgi.loc[(g.game_id, t)]
            for m in OFF_METRICS:
                if not np.isnan(r[m]):
                    league[m][0] += float(r[m]); league[m][1] += 1.0
            qid = r["qb_id"]
            if isinstance(qid, str) and r["qb_db"] > 0:
                base = lg("epa_pass")
                s = qb_state.setdefault(qid, [0.0, 0.0])
                s[0] = s[0] * 0.995 ** r["qb_db"] + (r["qb_epa_sum"] - base * r["qb_db"]); s[1] = s[1] * 0.995 ** r["qb_db"] + r["qb_db"]
            last_qb[t] = qid if isinstance(qid, str) else last_qb.get(t)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------------------------- injuries
POS_GROUPS = {"QB": "qb", "T": "ol", "G": "ol", "C": "ol", "OL": "ol", "OT": "ol", "OG": "ol", "WR": "skill", "TE": "skill", "RB": "skill", "FB": "skill", "HB": "skill",
              "DE": "dl", "DT": "dl", "NT": "dl", "DL": "dl", "OLB": "lb", "ILB": "lb", "LB": "lb", "MLB": "lb", "CB": "db", "S": "db", "DB": "db", "FS": "db", "SS": "db", "SAF": "db"}
STATUS_W = {"Out": 1.0, "Doubtful": 0.85, "Questionable": 0.25}


DIAGNOSTICS: dict = {}


def kickoff_table(games: pd.DataFrame) -> pd.DataFrame:
    """(season, week, team) -> kickoff as naive UTC. nflverse gametime is US Eastern."""
    g = games.copy()
    t = g["gametime"].fillna("13:00")
    ko = pd.to_datetime(g["gameday"] + " " + t, errors="coerce").dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC").dt.tz_localize(None)
    g["ko"] = ko
    a = g[["season", "week", "home_team", "ko"]].rename(columns={"home_team": "team"})
    b = g[["season", "week", "away_team", "ko"]].rename(columns={"away_team": "team"})
    return pd.concat([a, b]).dropna(subset=["ko"]).drop_duplicates(["season", "week", "team"])


def injury_features(inj_dir: Path, snap_dir: Path, players: pd.DataFrame, kickoffs: pd.DataFrame | None = None) -> pd.DataFrame:
    """Snap-share-weighted starters unavailable per team-week: sum over Out/Doubtful(/Questionable*0.25) players of their prior-4-game snap share."""
    idmap = players.dropna(subset=["gsis_id", "pfr_id"]).drop_duplicates("pfr_id").set_index("pfr_id")["gsis_id"]
    snaps = []
    for f in sorted(Path(snap_dir).glob("snap_*.csv")):
        s = pd.read_csv(f)
        if len(s.columns) > 3:
            snaps.append(s)
    snap = pd.concat(snaps, ignore_index=True)
    snap = snap[snap["game_type"].isin(["REG", "POST"])]
    snap["gsis_id"] = snap["pfr_player_id"].map(idmap)
    snap = snap.dropna(subset=["gsis_id"]).sort_values(["gsis_id", "season", "week"])
    # rolling mean of the player's own last 4 played games INCLUDING that game; looked up strictly BEFORE the report week via an as-of join, because a
    # player listed Out has no snap row in the report week (a same-week join would silently give every Out starter zero impact).
    snap["off_roll"] = snap.groupby("gsis_id")["offense_pct"].transform(lambda x: x.rolling(4, min_periods=1).mean())
    snap["def_roll"] = snap.groupby("gsis_id")["defense_pct"].transform(lambda x: x.rolling(4, min_periods=1).mean())
    snap["tkey"] = (snap["season"] * 100 + snap["week"]).astype("int64")
    prior = snap[["tkey", "gsis_id", "off_roll", "def_roll"]].sort_values("tkey")
    rows = []
    for f in sorted(Path(inj_dir).glob("inj_*.csv")):
        i = pd.read_csv(f)
        if len(i.columns) > 3:
            rows.append(i)
    inj = pd.concat(rows, ignore_index=True)
    inj = inj[inj["game_type"].isin(["REG", "POST"])].copy()
    # point-in-time filter: a report row stamped AFTER the game's kickoff cannot be a pregame input. Rows with no timestamp cannot be verified and are counted, not dropped.
    inj["dm"] = pd.to_datetime(inj["date_modified"], utc=True, errors="coerce").dt.tz_localize(None) if "date_modified" in inj else pd.NaT
    diag = {"report_rows": int(len(inj)), "rows_without_timestamp": int(inj["dm"].isna().sum())}
    if kickoffs is not None:
        inj["season"] = pd.to_numeric(inj["season"], errors="coerce"); inj["week"] = pd.to_numeric(inj["week"], errors="coerce")
        inj = inj.merge(kickoffs, on=["season", "week", "team"], how="left")
        late = inj["dm"].notna() & inj["ko"].notna() & (inj["dm"] > inj["ko"])
        diag["rows_modified_after_kickoff_dropped"] = int(late.sum())
        inj = inj[~late]
    DIAGNOSTICS["injury_report"] = diag
    inj = inj[inj["report_status"].isin(STATUS_W)].copy()
    inj["w"] = inj["report_status"].map(STATUS_W)
    inj["grp"] = inj["position"].map(POS_GROUPS)
    inj = inj.dropna(subset=["grp"]).copy()
    inj["season"] = pd.to_numeric(inj["season"], errors="coerce")
    inj["week"] = pd.to_numeric(inj["week"], errors="coerce")
    inj = inj.dropna(subset=["season", "week"])
    inj["tkey"] = (inj["season"] * 100 + inj["week"]).astype("int64")
    inj = pd.merge_asof(inj.sort_values("tkey"), prior, on="tkey", by="gsis_id", direction="backward", allow_exact_matches=False)
    inj = inj.rename(columns={"off_roll": "off_prior", "def_roll": "def_prior"})
    # a listed player with no prior snaps (rookie/backup) contributes ~0 starter impact: that is the point of weighting by prior snap share
    inj["share"] = np.where(inj["grp"].isin(["qb", "ol", "skill"]), inj["off_prior"], inj["def_prior"]).astype(float)
    inj["share"] = inj["share"].fillna(0.0)
    inj["impact"] = inj["w"] * inj["share"]
    piv = inj.pivot_table(index=["season", "week", "team"], columns="grp", values="impact", aggfunc="sum", fill_value=0.0)
    piv.columns = [f"inj_{c}" for c in piv.columns]
    piv["inj_total"] = piv.sum(axis=1)
    return piv.reset_index()


# ---------------------------------------------------------------------------------------------------------------- assemble
_meta("off_epa_pass_diff", "Opponent-adjusted passing EPA/dropback (offence) vs opposing defence", "team_efficiency", "yes", ["nfl.off_epa", "nfl.def_epa"])
_meta("pace", "Neutral-situation seconds per play (both teams)", "pace_script", "yes", ["nfl.pace"])


def build_game_table(data_dir: Path, first_season: int = 2010, last_season: int | None = None) -> pd.DataFrame:
    data_dir = Path(data_dir)
    games = pd.read_csv(data_dir / "games.csv")
    games = games[(games["season"] >= first_season) & games["game_type"].isin(["REG", "POST"])].copy()
    if last_season:
        games = games[games["season"] <= last_season]
    seasons = sorted(games["season"].unique())
    pbp = load_pbp(data_dir / "pbp", seasons)
    tg = team_games_from_pbp(pbp)
    rat = rolling_ratings(games, tg)
    gm = games.merge(rat, on="game_id", how="left")
    players = pd.read_csv(data_dir / "players.csv", low_memory=False)
    inj = injury_features(data_dir / "inj", data_dir / "snaps", players, kickoff_table(games))
    for tag, team in (("h", "home_team"), ("a", "away_team")):
        x = inj.rename(columns={c: f"{tag}_{c}" for c in inj.columns if c.startswith("inj_")})
        x = x.rename(columns={"team": team})
        gm = gm.merge(x, on=["season", "week", team], how="left")
    inj_cols = [c for c in gm.columns if c.startswith(("h_inj_", "a_inj_"))]
    has_snaps = gm["season"] >= 2013
    gm.loc[~has_snaps, inj_cols] = np.nan
    gm[inj_cols] = gm[inj_cols].where(~has_snaps, gm[inj_cols].fillna(0.0))   # reports exist but no Out/Doubtful listed => 0 impact (2013+ only)
    return gm


def add_matchup_features(g: pd.DataFrame) -> pd.DataFrame:
    """Derived, leakage-free features. Names are stable: the dashboard keys on them."""
    d = g.copy()
    F = {}
    # --- team efficiency (opponent-adjusted; matchup = my offence vs their defence, both directions)
    for tag, opp in (("h", "a"), ("a", "h")):
        F[f"{tag}_exp_epa_pass"] = d[f"{tag}_off_epa_pass"] + d[f"{opp}_def_epa_pass"]
        F[f"{tag}_exp_epa_rush"] = d[f"{tag}_off_epa_rush"] + d[f"{opp}_def_epa_rush"]
        F[f"{tag}_exp_sack_vs_prot"] = d[f"{opp}_def_sack_rate"] + d[f"{tag}_off_sack_rate"]
        F[f"{tag}_exp_pressure"] = d[f"{opp}_def_qbhit_rate"] + d[f"{tag}_off_qbhit_rate"]
        F[f"{tag}_exp_expl_pass"] = d[f"{tag}_off_expl_pass"] + d[f"{opp}_def_expl_pass"]
        F[f"{tag}_exp_sr"] = d[f"{tag}_off_sr"] + d[f"{opp}_def_sr"]
    X = pd.DataFrame(F, index=d.index)
    d = pd.concat([d, X], axis=1)
    out = pd.DataFrame(index=d.index)
    # totals-style (sums) and margin-style (differences) forms
    for k in ["exp_epa_pass", "exp_epa_rush", "exp_sack_vs_prot", "exp_pressure", "exp_expl_pass", "exp_sr"]:
        out[f"sum_{k}"] = d[f"h_{k}"] + d[f"a_{k}"]
        out[f"diff_{k}"] = d[f"h_{k}"] - d[f"a_{k}"]
    out["sum_pace_sec"] = d["h_off_sec_play"] + d["a_off_sec_play"]                  # slower = fewer possessions
    out["sum_plays_rating"] = d["h_off_plays"] + d["a_off_plays"] + d["h_def_plays"] + d["a_def_plays"]
    out["sum_neutral_pass"] = d["h_off_neutral_pass"] + d["a_off_neutral_pass"]
    out["sum_pass_oe"] = d["h_off_pass_oe"] + d["a_off_pass_oe"]
    out["diff_neutral_pass"] = d["h_off_neutral_pass"] - d["a_off_neutral_pass"]
    out["sum_to_luck"] = d["h_off_to_rate"] + d["a_off_to_rate"] + d["h_def_to_rate"] + d["a_def_to_rate"]       # turnover-rate regression component
    out["diff_to_luck"] = (d["h_off_to_rate"] - d["a_off_to_rate"]) - (d["h_def_to_rate"] - d["a_def_to_rate"])
    out["sum_pen_rate"] = d["h_off_pen_rate"] + d["a_off_pen_rate"] + d["h_def_pen_rate"] + d["a_def_pen_rate"]
    out["sum_third_conv"] = d["h_off_third_conv"] + d["a_off_third_conv"]
    out["sum_score_drive"] = d["h_off_score_drive"] + d["a_off_score_drive"]
    out["diff_score_drive"] = d["h_off_score_drive"] - d["a_off_score_drive"]
    out["qb_epa_h"] = d["h_qb_epa"]; out["qb_epa_a"] = d["a_qb_epa"]
    out["sum_qb_epa"] = d["h_qb_epa"] + d["a_qb_epa"]; out["diff_qb_epa"] = d["h_qb_epa"] - d["a_qb_epa"]
    out["qb_change_any"] = d["h_qb_change"] + d["a_qb_change"]
    out["diff_qb_change"] = d["h_qb_change"] - d["a_qb_change"]
    for grp in ("qb", "ol", "skill", "dl", "lb", "db", "total"):
        hc, ac = f"h_inj_{grp}", f"a_inj_{grp}"
        if hc in d:
            out[f"inj_sum_{grp}"] = d[hc] + d[ac]
            out[f"inj_diff_{grp}"] = d[hc] - d[ac]            # positive = home more depleted
    # --- environment / schedule
    out["dome"] = d["roof"].isin(["dome", "closed"]).astype(float)
    out["wind_eff"] = d["wind"].where(~out["dome"].astype(bool), 0.0)
    out["cold"] = (65.0 - d["temp"]).clip(lower=0).where(~out["dome"].astype(bool), 0.0)
    out["wind_x_pass"] = out["wind_eff"] * out["sum_neutral_pass"]
    out["rest_diff"] = d["home_rest"] - d["away_rest"]
    out["short_week_any"] = ((d["home_rest"] < 6) | (d["away_rest"] < 6)).astype(float)
    out["div_flag"] = d["div_game"].astype(float)
    out["neutral_site"] = (d["location"] == "Neutral").astype(float)
    out["games_played_min"] = d[["h_games_played", "a_games_played"]].min(axis=1)
    out["late_season"] = (d["week"] >= 14).astype(float)
    # --- market-structure controls (the line is also an input for the residual: do extreme lines carry bias?)
    out["mkt_total_level"] = d["total_line"]
    out["mkt_abs_spread"] = d["spread_line"].abs()
    out["mkt_spread"] = d["spread_line"]
    # --- interactions pre-specified from the catalog hypotheses
    out["ix_spread_x_passrate"] = out["mkt_abs_spread"] * out["sum_neutral_pass"]
    out["ix_pressure_x_qb"] = out["diff_exp_pressure"] * out["diff_qb_epa"]
    out["ix_pace_x_total"] = out["sum_pace_sec"] * d["total_line"]
    out["ix_wind_x_expl"] = out["wind_eff"] * out["sum_exp_expl_pass"]
    out["ix_qbinj_x_epa"] = (out["inj_sum_qb"] if "inj_sum_qb" in out else 0.0) * out["sum_qb_epa"]
    out["ix_olinj_x_pressure"] = (out["inj_diff_ol"] if "inj_diff_ol" in out else 0.0) * out["diff_exp_pressure"]
    return pd.concat([d, out], axis=1)


def market_columns(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["margin"] = d["home_score"] - d["away_score"]
    d["p_home_mkt"] = devig(d["home_moneyline"], d["away_moneyline"])
    d["p_over_mkt"] = devig(d["over_odds"], d["under_odds"])
    d["p_homecover_mkt"] = devig(d["home_spread_odds"], d["away_spread_odds"])
    d["resid_total"] = d["total"] - d["total_line"]
    d["resid_margin"] = d["margin"] - d["spread_line"]
    d["home_win"] = np.where(d["margin"] > 0, 1.0, np.where(d["margin"] < 0, 0.0, np.nan))
    d["over"] = np.where(d["resid_total"] > 0, 1.0, np.where(d["resid_total"] < 0, 0.0, np.nan))
    d["home_cover"] = np.where(d["resid_margin"] > 0, 1.0, np.where(d["resid_margin"] < 0, 0.0, np.nan))
    return d
