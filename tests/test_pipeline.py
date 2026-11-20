"""Research-to-operating pipeline: shared selection evaluation and the evidence-backed adoption ladder. RESEARCH_ONLY."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alpha_engine.pipeline import ladder as L, selection as S

ROOT = Path(__file__).resolve().parents[1]


def _contracts(n=400, seed=1, model_noise=0.0):
    rng = np.random.default_rng(seed); p = rng.uniform(0.1, 0.9, n); y = (rng.uniform(size=n) < p).astype(int)
    mid = np.clip(p + rng.normal(0, 0.05, n), 0.03, 0.97)
    return pd.DataFrame({"game_id": np.arange(n) // 2, "contract_id": [f"c{i}" for i in range(n)], "family": np.where(np.arange(n) % 2, "TOTAL", "SPREAD"),
                         "yes_bid": mid - 0.01, "yes_ask": mid + 0.01, "model_p": np.clip(p + rng.normal(0, model_noise, n), 0.01, 0.99), "y": y})


def test_fee_matches_canonical_and_rounds_up():
    assert S.fee_order(0.5, 1) == 0.02 and S.fee_order(0.5, 10) == 0.18
    assert abs(float(S.fee_unrounded(0.5)) - 0.0175) < 1e-12


def test_sides_axes_and_net_edge():
    c = _contracts(4); s = S.sides(c)
    yes, no = s[s.side == "YES"].reset_index(drop=True), s[s.side == "NO"].reset_index(drop=True)
    np.testing.assert_allclose(yes.entry, c.yes_ask); np.testing.assert_allclose(no.entry, 1 - c.yes_bid)
    np.testing.assert_allclose(yes.prob + no.prob, 1.0); assert (yes.won != no.won).all()
    np.testing.assert_allclose(s.net_edge, s.prob - s.entry - 0.07 * s.entry * (1 - s.entry))


def test_oracle_model_wins_and_market_copy_does_not_bet():
    c = _contracts(2000, model_noise=0.0); c["model_p"] = c.y.astype(float) * 0.98 + 0.01      # perfect foresight
    r = S.evaluate(c, [{"name": "R1", "min_net_edge": 0.05, "one_per": ["game_id", "family"]}], boot=200)
    assert r["rules"]["R1"]["all"]["net_roi"] > 0.5 and r["rules"]["R1"]["all"]["net_roi_95ci_game_bootstrap"][0] > 0
    c2 = c.assign(model_p=(c.yes_bid + c.yes_ask) / 2)                                             # model = market mid -> never clears fees
    assert S.select(c2, {"name": "x", "min_net_edge": 0.05}).empty


def test_one_per_keeps_largest_edge_and_rules_are_hashable():
    c = _contracts(40, model_noise=0.3); rule = {"name": "R", "min_net_edge": 0.0, "one_per": ["game_id"]}
    b = S.select(c, rule); assert b.game_id.is_unique
    s = S.sides(c); best = s[s.net_edge >= 0].groupby("game_id").net_edge.max()
    np.testing.assert_allclose(b.set_index("game_id").net_edge.sort_index(), best.sort_index())
    h = S.freeze(rule); S.verify_frozen(rule, h)
    with pytest.raises(ValueError):
        S.verify_frozen({**rule, "min_net_edge": 0.01}, h)


def test_summary_breakeven_clv_and_pvalue():
    c = _contracts(600, model_noise=0.15); c["close_yes_bid"] = c.yes_bid + 0.02; c["close_yes_ask"] = c.yes_ask + 0.02
    b = S.select(c, {"name": "R", "min_net_edge": 0.05}); s = S.summarize(b, boot=0)
    assert abs(s["breakeven_win_prob"] - (b.entry + b.fee).mean()) < 1e-4
    yes = b.side == "YES"; mv = np.where(yes, 0.02, -0.02).mean()
    assert abs(s["clv"]["selection_clv_mean"] - round(mv, 4)) < 1e-4                           # pure market movement, no fee
    assert abs(s["clv"]["entry_spread_component_mean"] - 0.01) < 1e-6 and s["clv"]["entry_fee_mean_not_clv"] > 0
    assert S.poisson_binomial_p_at_least(0, np.array([0.5, 0.5])) == 1.0 and abs(S.poisson_binomial_p_at_least(2, np.array([0.5, 0.5])) - 0.25) < 1e-12


def test_ladder_counts_reconcile_with_ledger_and_registry_is_clean():
    d = L.build()
    assert d["registry_problems"] == {}
    led = json.loads((ROOT / "research/input_research/data_foundation/verified_coverage.json").read_text())["rows"]
    cert = {(r["sport"], r["id"]) for r in led if (r.get("status") or r.get("verified_status")) in L.CERT}
    assert d["counts_at_least"]["CERTIFIED"] == len(cert) == sum(1 for r in d["inputs"] if r["verified_status"] in L.CERT)
    assert d["counts_at_level"]["PRODUCTION_CONSUMED"] == 0                                        # nothing is consumed in production today
    assert (ROOT / "research/pipeline/input_ladder.json").read_text() == json.dumps(d, indent=1) + "\n"


def test_ladder_rejects_unbacked_claims(tmp_path, monkeypatch):
    bad = [{"level": "EXPERIMENTAL_ADOPTION", "inputs": ["CFB:cfb.period_margin_lattice"], "columns": ["pml_lead_half_pre_typo"], "evidence": {"file": "research/cfb_bet_selection/evaluate.py"}},
           {"level": "PRICE_AWARE_VERIFIED", "inputs": ["CFB:cfb.period_margin_lattice"], "evidence": {"file": "research/cfb_forward_validation/forward_report.json", "pointer": "/nope"}},
           {"level": "PRODUCTION_CONSUMED", "inputs": ["CFB:cfb.period_margin_lattice"], "evidence": {"file": "README.md"}}]
    for c in bad:
        assert L.check_claim(c), c
    ok = {"level": "EXPERIMENTAL_ADOPTION", "inputs": ["CFB:cfb.period_margin_lattice"], "columns": ["pml_lead_half_pre"], "evidence": {"file": "research/cfb_bet_selection/evaluate.py"}}
    assert L.check_claim(ok) == []


def test_readiness_ledger_reconciles_and_is_current():
    from alpha_engine.input_research.data_foundation import readiness_ledger as RL
    d = RL.build(); t = d["totals"]
    assert t["reconciles"] and t["slots"] == t["inventory_primary_missing_critical"] == sum(d["by_class"].values())
    assert set(d["by_class"]) <= set(RL.CLASSES) and sum(d["by_tier"].values()) == t["slots"]
    assert all(s["datasets_held"] == s["datasets"] for s in d["slots"] if s["class"] == "B_DATA_IN_HAND_NO_BUILDER" and s["inventory_category"] != "DATA_IN_HAND")
    assert RL.main(["--check"]) == 0                                                                                    # committed files are current


def test_nfl_legacy_builder_one_home_row_per_game_for_relocated_franchises():
    """Amendment 1: schedule codes STL/SD/OAK must map to the pbp's LA/LAC/LV, else both rows of a relocated team's home game get home = 0."""
    from alpha_engine.features import nfl as N, nfl_ext as E
    assert N.TEAM_FIX == E.TEAM_FIX
    pbp = pd.DataFrame({c: [] for c in N.PBP if c != "x"})
    rows = []
    for gid, home, away, hs, as_ in (("2010_01_ARI_STL", "STL", "ARI", 13, 17), ("2021_01_ARI_LA", "LA", "ARI", 20, 10)):
        for team, opp in ((home if home not in N.TEAM_FIX else N.TEAM_FIX[home], away), (away, N.TEAM_FIX.get(home, home))):
            rows.append({"game_id": gid, "posteam": team, "defteam": opp, "epa": 0.1, "season_type": "REG", "drive": 1, "qb_dropback": 0, "pass": 0, "rush": 1, "yards_gained": 3, "yardline_100": 50, "down": 1, "wp": 0.5})
    pb = pd.DataFrame(rows).reindex(columns=[c for c in N.PBP if c != "x"]); pb[["success", "sack", "interception", "fumble_lost", "touchdown", "penalty", "qb_hit", "xpass", "pass_oe", "no_huddle", "shotgun", "air_yards", "cpoe"]] = 0.0
    pb["epa"] = 0.1; pb["season_type"] = "REG"; pb["drive"] = 1.0; pb["qb_dropback"] = 0.0; pb["pass"] = 0.0; pb["rush"] = 1.0; pb["yards_gained"] = 3.0; pb["yardline_100"] = 50.0; pb["down"] = 1.0; pb["wp"] = 0.5
    games = pd.DataFrame([{"game_id": "2010_01_ARI_STL", "season": 2010, "game_type": "REG", "week": 1, "gameday": "2010-09-12", "away_team": "ARI", "home_team": "STL", "away_rest": 7, "home_rest": 7, "div_game": 1, "roof": "dome", "surface": "", "temp": None, "wind": None, "referee": "x", "away_coach": "a", "home_coach": "h", "overtime": 0, "away_score": 17, "home_score": 13, "location": "Home"},
                          {"game_id": "2021_01_ARI_LA", "season": 2021, "game_type": "REG", "week": 1, "gameday": "2021-09-12", "away_team": "ARI", "home_team": "LA", "away_rest": 7, "home_rest": 7, "div_game": 1, "roof": "dome", "surface": "", "temp": None, "wind": None, "referee": "x", "away_coach": "a", "home_coach": "h", "overtime": 0, "away_score": 10, "home_score": 20, "location": "Home"}])
    t = N._team_stats({"pbp": pb, "games": games})
    assert (t.groupby("game_id").home.sum() == 1).all()
    la10 = t[(t.game_id == "2010_01_ARI_STL") & (t.team == "LA")].iloc[0]
    assert la10.home == 1 and la10.pts == 13 and la10.pts_a == 17 and la10.coach == "h"
