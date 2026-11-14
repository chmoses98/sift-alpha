"""Scaled, ledger-logged, market-free systematic search across all eight sports (RESEARCH_ONLY).

Consumes ONLY inputs that passed the computable-inputs audit (status COMPUTED_*; leak-tested), grouped by catalog input. One market = one decision-unit table (game or player-game), one target and a
no-information baseline (league mean of strictly earlier dates for games; the player's own prior EWMA for players). The search is search.nested_search (chronological outer seasons/blocks, inner folds,
1-SE rule, structured leave-one-group-out core) and logs every configuration x outer season to a #59-compatible Ledger. Multiple testing: a permutation null (>=2 reps through the identical procedure),
a cluster-bootstrap p per market, Holm across ALL markets tested, plus block-positivity/halves consistency. Kalshi prices and sportsbook lines never enter (marketfree guard).
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.features import college, mlb, nba, nfl, nhl, soccer, tennis
from alpha_engine.features.core import prior_date_mean, prior_ewm

from . import ledger as L
from . import search as SR
from . import stats as ST

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
CACHE = Path("/tmp/featcache")
OUTDIR = ROOT / "research/audit/input_research/scaled_search"
COMPUTABLE = ROOT / "research/input_research/computable_inputs.json"
SR.GBM_MAX_ROWS = 40000
MAX_ROWS = 60000     # most recent decision units kept per market (keeps a 4-core sweep tractable; recorded in the market meta)

SPEC_FN = {"NBA": nba.specs, "NHL": nhl.specs, "MLB": mlb.specs, "TENNIS": tennis.specs, "SOCCER": soccer.specs, "CBB": college.specs_cbb, "CFB": college.specs_cfb, "NFL": nfl.specs}
# sport -> (home pts col, away pts col) on the team table (for the team-level game tables)
PTS = {"NBA": ("pts", "opp_pts"), "NHL": ("gf", "ga"), "MLB": ("rs", "ra"), "SOCCER": ("gf", "ga"), "CBB": ("pts", "pts_a"), "CFB": ("pts", "pts_a"), "NFL": ("pts", "pts_a")}

GAME_MARKETS = [  # (sport, name, target kind, extra (home col, away col) for sum targets)
    ("NBA", "game_total", "total", None), ("NBA", "game_margin", "margin", None),
    ("NHL", "game_total", "total", None), ("NHL", "game_margin", "margin", None),
    ("MLB", "game_total", "total", None), ("MLB", "game_margin", "margin", None), ("MLB", "f5_total", "sum", ("r5", "ra5")), ("MLB", "first_inning_total", "sum", ("r1", "ra1")),
    ("SOCCER", "game_total", "total", None), ("SOCCER", "game_margin", "margin", None), ("SOCCER", "corners_total", "sum", ("corners", "corners_a")), ("SOCCER", "cards_total", "sum", ("cards", "cards_a")),
    ("CBB", "game_total", "total", None), ("CBB", "game_margin", "margin", None),
    ("CFB", "game_total", "total", None), ("CFB", "game_margin", "margin", None),
    ("NFL", "game_total", "total", None), ("NFL", "game_margin", "margin", None),
]
PLAYER_MARKETS = [  # (sport, name, table, target col, row filter)
    ("NBA", "player_points", "player", "pts", "played"), ("NBA", "player_rebounds", "player", "reb", "played"), ("NBA", "player_assists", "player", "ast", "played"), ("NBA", "player_threes", "player", "fg3m", "played"),
    ("NHL", "skater_shots", "skater", "sog", None), ("NHL", "skater_points", "skater", "points", None), ("NHL", "goalie_saves", "goalie", "saves", "starter"),
    ("MLB", "pitcher_strikeouts", "pitcher", "k", "gs"), ("MLB", "pitcher_outs", "pitcher", "outs", "gs"), ("MLB", "hitter_total_bases", "hitter", "tb", None), ("MLB", "hitter_hits", "hitter", "h", None),
]
TENNIS_MARKETS = [("TENNIS", "match_winner", "won"), ("TENNIS", "total_games", "games"), ("TENNIS", "total_aces", "aces")]


def verified_groups(sport: str, table: str, df: pd.DataFrame, comp: dict) -> dict[str, list[str]]:
    groups = {}
    for s in SPEC_FN[sport]():
        rec = comp["inputs"].get(f"{sport}:{s.catalog_id}", {})
        if s.table != table or not rec.get("status", "").startswith("COMPUTED") or s.pit != "pregame_rolling":
            continue
        cols = [c for c in rec.get("columns", s.columns) if c in df and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.5 and df[c].dtype != object]
        if cols:
            groups[s.catalog_id] = cols
    return groups


def _season_index(df):
    """Chronological integer ids; fall back to month blocks when the history has too few seasons for nested validation."""
    d = pd.to_datetime(df["date"])
    seas = pd.factorize(df["season"].astype(str), sort=True)[0] if "season" in df else d.dt.year.to_numpy()
    s = pd.Series(seas, index=df.index)
    ordered = s.groupby(s).apply(lambda x: d[x.index].min()).sort_values()
    rank = {k: i for i, k in enumerate(ordered.index)}
    s = s.map(rank)
    if s.nunique() < 8:
        s = (((d - d.min()).dt.days) // 30).astype(int)
        return s.to_numpy(), "block30d"
    return s.to_numpy(), "season"


def _team_game_table(sport, comp):
    t = pd.read_parquet(CACHE / f"{sport}_team.parquet")
    groups = verified_groups(sport, "team", t, comp)
    cols = sorted({c for g in groups.values() for c in g})
    h = t[t.home == 1].drop_duplicates("game_id"); a = t[t.home == 0].drop_duplicates("game_id")
    pc, pa = PTS[sport]
    ex = [c for c in {"r5", "ra5", "r1", "ra1", "corners", "corners_a", "cards", "cards_a"} if c in t]
    g = h[["game_id", "date", "season", pc, pa, *[c for c in ex if c in h]] + cols].rename(columns={c: f"h_{c}" for c in cols})
    g = g.merge(a[["game_id", *cols]].rename(columns={c: f"a_{c}" for c in cols}), on="game_id")
    return g, {k: [f"{p}_{c}" for c in v for p in ("h", "a")] for k, v in groups.items()}, (pc, pa)


def build_game(sport, name, kind, extra, comp):
    g, groups, (pc, pa) = _team_game_table(sport, comp)
    g = g.dropna(subset=[pc, pa]).sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    if kind == "total":
        y = g[pc] + g[pa]
    elif kind == "margin":
        y = g[pc] - g[pa]
    else:
        y = g[extra[0]] + g[extra[1]] if extra[0] in g else pd.Series(np.nan, index=g.index)
    g["y"] = y
    g = g.dropna(subset=["y"]).reset_index(drop=True)
    base = prior_date_mean(g, "date", "y")
    ok = base.notna().to_numpy()
    g = g[ok].reset_index(drop=True); g["season_id"], mode = _season_index(g)
    r = (g["y"] - base[ok].reset_index(drop=True)).to_numpy(float)
    d = g.rename(columns={"season": "season_label"}).assign(season=g["season_id"])
    return d, r, groups, d["game_id"].to_numpy(), dict(unit="game", target=name, mode=mode, n=len(d), baseline="league mean of strictly earlier dates")


def build_player(sport, name, table, target, flt, comp):
    p = pd.read_parquet(CACHE / f"{sport}_{table}.parquet")
    groups = verified_groups(sport, table, p, comp)
    if flt:
        p = p[p[flt].astype(float) > 0] if p[flt].dtype != bool else p[p[flt]]
    p = p.dropna(subset=[target]).sort_values(["date", "game_id" if "game_id" in p else "game_pk"], kind="mergesort").reset_index(drop=True)
    p["y"] = p[target].astype(float)
    p["base"] = prior_ewm(p, "pid", "y", hl=10, min_periods=5)
    p = p[p.base.notna()].tail(MAX_ROWS).reset_index(drop=True)
    p["season_id"], mode = _season_index(p)
    r = (p.y - p.base).to_numpy(float)
    d = p.assign(season=p["season_id"])
    gid = d["game_id"] if "game_id" in d else d["game_pk"]
    return d, r, groups, gid.to_numpy(), dict(unit="player-game", target=name, mode=mode, n=len(d), baseline="player's own prior EWMA of the stat (hl 10)")


def build_tennis(name, target, comp):
    t = pd.read_parquet(CACHE / "TENNIS_player.parquet")
    groups = verified_groups("TENNIS", "player", t, comp)
    cols = sorted({c for g in groups.values() for c in g})
    t["aces"] = t.ace + t.o_ace
    a = t[t.pid < t.opp].drop_duplicates("match_id"); b = t[t.pid > t.opp].drop_duplicates("match_id")
    g = a[["match_id", "date", "season", "tour_wta" if "tour_wta" in a else "tour", target, "best_of", *cols]].rename(columns={c: f"a_{c}" for c in cols})
    g = g.merge(b[["match_id", *cols]].rename(columns={c: f"b_{c}" for c in cols}), on="match_id")
    gr = {k: [f"{p}_{c}" for c in v for p in ("a", "b")] for k, v in groups.items()}
    g = g.dropna(subset=[target]).sort_values(["date", "match_id"], kind="mergesort").reset_index(drop=True)
    g["y"] = g[target].astype(float)
    if target == "won":
        base = pd.Series(0.5, index=g.index)
    else:
        base = prior_date_mean(g.assign(_k=g.best_of), "date", "y")
        g["_bo"] = g.best_of
        base = g.groupby("best_of")["y"].transform(lambda s: s.shift(1).expanding(min_periods=100).mean())
    ok = base.notna().to_numpy(); g = g[ok].reset_index(drop=True)
    cap = 25000 if target in ("won", "games", "aces") else MAX_ROWS      # tennis: 25k most recent matches (the 60k run took >45 min per search on 4 cores)
    base = base[ok].reset_index(drop=True); g, base = g.tail(cap).reset_index(drop=True), base.tail(cap).reset_index(drop=True); ok = np.ones(len(g), bool)
    g["season_id"], mode = _season_index(g)
    r = (g.y - base[ok].reset_index(drop=True)).to_numpy(float)
    d = g.assign(season=g["season_id"])
    return d, r, gr, d["match_id"].to_numpy(), dict(unit="match", target=name, mode=mode, n=len(d), baseline="0.5 for winner; best-of-specific expanding mean of earlier matches otherwise")


def all_markets():
    ms = [(f"{s}:{n}", ("game", s, n, k, e)) for s, n, k, e in GAME_MARKETS]
    ms += [(f"{s}:{n}", ("player", s, n, tb, tg, fl)) for s, n, tb, tg, fl in PLAYER_MARKETS]
    ms += [(f"{s}:{n}", ("tennis", n, tg)) for s, n, tg in TENNIS_MARKETS]
    return ms


def build(spec, comp):
    return build_game(*spec[1:], comp) if spec[0] == "game" else build_player(*spec[1:], comp) if spec[0] == "player" else build_tennis(*spec[1:], comp)


def run_market(key, spec, comp, n_extra=50, null_reps=2, max_seasons=7, force=False):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    f = OUTDIR / f"{key.replace(':', '__')}.json"
    if f.exists() and not force:
        return json.load(open(f))
    t0 = time.time()
    d, r, groups, cluster, meta = build(spec, comp)
    if len(groups) < 3 or len(d) < 400:
        res = dict(market=key, status="SKIPPED", reason=f"{len(groups)} verified groups, {len(d)} rows", meta=meta)
        f.write_text(json.dumps(res, indent=1)); return res
    sid = np.unique(d["season"].to_numpy()); test = [int(x) for x in sid[-max_seasons:] if x >= sid[0] + 6]
    fp = L.data_fingerprint(key, len(d), float(np.nansum(r)), sorted(groups))
    led = L.Ledger(OUTDIR / "ledger" / f"{key.replace(':', '__')}.jsonl")
    ctx = dict(lab="alpha-input-research", market=key, mode=meta["mode"], fp=fp, null=False)
    n_cfg = 1 + len(groups) + n_extra
    res = SR.nested_search(d, r, groups, test, n_configs=n_cfg, seed=1, ledger=led, ctx=ctx)
    g = SR.summarize_gain(d, r, res["pred"], cluster)
    ok = ~np.isnan(res["pred"]); diff = (r[ok] ** 2 - (r[ok] - res["pred"][ok]) ** 2); h = len(diff) // 2
    g["halves_pct"] = [float(100 * diff[:h].mean() / (r[ok][:h] ** 2).mean()), float(100 * diff[h:].mean() / (r[ok][h:] ** 2).mean())] if len(diff) > 20 else None
    nulls = SR.permutation_null(d, r, groups, test, cluster, reps=null_reps, n_configs=n_cfg, ledger=led, ctx=ctx)
    # core leave-one-group-out importance, averaged over the outer folds
    imp = {}
    for ch in res["chosen"]:
        c = ch["core_inner_rel_mse"]
        for k2, v in c.items():
            if k2.startswith("drop:"):
                imp.setdefault(k2[5:], []).append(v - c["full"])
    imp = {k2: round(float(np.mean(v)), 4) for k2, v in imp.items()}
    out = dict(market=key, status="TESTED", meta=meta, n_groups=len(groups), groups={k2: v for k2, v in groups.items()}, test_blocks=test, n_configs_per_fold=res["n_configs"], gain=g,
               nulls=nulls, null_max_pct=max(n["pct_gain"] for n in nulls), importance_drop_group=dict(sorted(imp.items(), key=lambda kv: -kv[1])[:10]),
               chosen=res["chosen"][-3:], ledger_rows=len(led), seconds=round(time.time() - t0))
    f.write_text(json.dumps(out, indent=1, default=float))
    print(key, out["seconds"], round(g["pct_gain"], 3), nulls, file=sys.stderr, flush=True)
    return out


def finalize(results: list[dict]) -> dict:
    tested = [r for r in results if r["status"] == "TESTED"]
    p = {r["market"]: r["gain"]["p"] for r in tested}
    adj = ST.holm(p)
    for r in tested:
        gn = r["gain"]; lo, hi = gn["ci_0.05"]
        sp = gn["seasons_positive"] / max(1, len(gn["seasons"]))
        halves = gn.get("halves_pct") or [0, 0]
        r["holm_p"] = adj[r["market"]]
        r["blocks_positive_share"] = round(sp, 3)
        beats_null = gn["pct_gain"] > 2 * max(0.0, r["null_max_pct"]) + 0.05
        if gn["pct_gain"] <= 0 or hi < 0:
            v = "NO_GAIN"
        elif r["holm_p"] < 0.05 and lo > 0 and min(halves) > 0 and sp >= 0.7 and beats_null:
            v = "VALIDATED"
        elif lo > 0 and beats_null:
            v = "SUGGESTIVE"
        else:
            v = "NOT_VALIDATED"
        r["verdict"] = v
    return dict(n_markets=len(results), n_tested=len(tested), n_skipped=len(results) - len(tested), verdicts={v: sum(1 for r in tested if r["verdict"] == v) for v in ("VALIDATED", "SUGGESTIVE", "NOT_VALIDATED", "NO_GAIN")})


def _worker(args):
    key, spec = args
    comp = json.load(open(COMPUTABLE))
    try:
        return run_market(key, spec, comp, **({"n_extra": 30, "null_reps": 1} if spec[0] == "tennis" else {}))
    except Exception as e:  # keep the sweep alive; the failure itself is recorded
        import traceback
        res = dict(market=key, status="ERROR", reason=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-600:])
        (OUTDIR / f"{key.replace(':', '__')}.json").write_text(json.dumps(res, indent=1)); return res


if __name__ == "__main__":
    from .phase import assert_predictive_allowed; assert_predictive_allowed('scaled_search')
    import multiprocessing as mp
    only = set(sys.argv[1:])
    ms = [m for m in all_markets() if not only or m[0].split(":")[0] in only or m[0] in only]
    with mp.get_context("fork").Pool(4) as pool:
        res = list(pool.imap_unordered(_worker, ms))
    summ = finalize(res)
    for r in res:
        (OUTDIR / f"{r['market'].replace(':', '__')}.json").write_text(json.dumps(r, indent=1, default=float))
    print(json.dumps(summ, indent=1))
