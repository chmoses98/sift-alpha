"""Phase 11 guards (RESEARCH_ONLY): rights evidence for CFBD/MoneyPuck, metadata/predictive component split, hold-DP tennis builder."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.features import tennis_ext4 as T
from alpha_engine.input_research.data_foundation import market_completeness as M, rights as RT

DF = Path(__file__).resolve().parents[1] / "research/input_research/data_foundation"
PHASE8 = json.loads((DF / "rights_registry.json").read_text())["retained_phase8_inputs_unresolved"]


def test_cfbd_direct_api_is_scoped_and_does_not_clear_sportsdataverse_path():
    reg = RT.registry(); src = {s["id"]: s for s in reg["sources"]}
    d = src["cfbd_cbbd_direct_api"]
    assert d["tier"] == "CLEARED_PROVIDER_TERMS_DIRECT_API" and d["evidence_status"] == "OWNER_REPORTED_NOT_AGENT_VERIFIED" and d["collection_allowed"] is False
    assert RT.is_cleared(d["tier"]) and RT.is_commercial_cleared(d["tier"])
    # the redistributed SportsDataverse / ESPN acquisition path stays unresolved, alone or mixed with the direct API
    for raw in ("espn_cfb", "cfbfastr_pbp", "sportsdataverse espn_mbb", "espn_cfb + cfbd_direct_api"):
        assert RT.tier_of_source(raw) == "UNRESOLVED_INTERNAL_ONLY", raw
    assert RT.tier_of_source("cfbd_direct_api") == "CLEARED_PROVIDER_TERMS_DIRECT_API"
    assert reg["phase11_rights_update"]["exact_text_verified"] is False


def test_phase8_college_inputs_remain_unresolved():
    keys = [k for k in RT.raw_sources_by_key() if k.split(":")[0] in ("CBB", "CFB")]
    for k in keys:
        assert RT.input_tier(k) == "UNRESOLVED_INTERNAL_ONLY", k


def test_moneypuck_listed_downloads_research_only_and_unlisted_unresolved():
    assert RT.tier_of_source("moneypuck_listed_shots_2023") == "CLEARED_NONCOMMERCIAL_RESEARCH"
    assert RT.is_cleared("CLEARED_NONCOMMERCIAL_RESEARCH") and not RT.is_commercial_cleared("CLEARED_NONCOMMERCIAL_RESEARCH")
    assert RT.tier_of_source("moneypuck_scraped_page") == "UNRESOLVED_INTERNAL_ONLY"
    assert RT.tier_of_source("nhl_api") == "UNRESOLVED_INTERNAL_ONLY"
    assert RT.tier_of_sources(["moneypuck_listed_x", "nhl_api"]) == "UNRESOLVED_INTERNAL_ONLY"           # an input that also needs NHL API data is only as cleared as that source
    assert RT.tier_of_sources(["moneypuck_listed_x", "openfootball"]) == "CLEARED_NONCOMMERCIAL_RESEARCH"


def test_tier_order_keeps_open_licence_strongest_and_existing_tiers():
    order = RT.registry()["tier_order"]
    assert order[0] == "UNRESOLVED_INTERNAL_ONLY" and order[-1] == "CLEARED_OPEN_LICENCE"
    assert RT.tier_of_source("openfootball") == "CLEARED_OPEN_LICENCE" and RT.tier_of_source("sackmann") == "CLEARED_NONCOMMERCIAL_RESEARCH"
    assert RT.tier_of_source("nflverse") == "WRAPPER_LICENCE_UPSTREAM_CAVEAT"


def test_metadata_split_keeps_genuine_predictive_components():
    assert "soc.competition_scope_and_win_definition" in M.NON_PREDICTIVE_IDS
    for i in ("ten.retirement_settlement_rules", "ten.ace_settlement_source", "ten.short_format_rules"):
        assert i not in M.NON_PREDICTIVE_IDS and M.COMPONENT_SPLIT[i]["denominator"] == "PREDICTIVE (retained)" and M.COMPONENT_SPLIT[i]["predictive_component"]
    assert M.COMPONENT_SPLIT["soc.competition_scope_and_win_definition"]["predictive_component"] == "none"


def test_hold_dp_basic_properties():
    p = np.array([0.5, 0.6, 0.65, 0.7]); assert np.allclose(T.hold(np.array([0.5])), 0.5) and (np.diff(T.hold(p)) > 0).all()
    sym = T.set_dp(T.hold(p), T.hold(p), p, p)
    assert np.allclose(sym["win"], 0.5) and np.allclose(sym["m1"], 0, atol=1e-12)
    for r in (sym, T.set_dp(T.hold(p), T.hold(p[::-1]), p, p[::-1])):
        assert np.allclose(sum(r[f"g{g}"] for g in T.GAMES), 1.0) and np.allclose(r["tb"], r["g13"])
    assert np.allclose(T.tiebreak_win(p, p), 0.5)
    a = T.set_dp(T.hold(np.array([0.7])), T.hold(np.array([0.6])), np.array([0.7]), np.array([0.6])); b = T.set_dp(T.hold(np.array([0.6])), T.hold(np.array([0.7])), np.array([0.6]), np.array([0.7]))
    assert np.allclose(a["win"] + b["win"], 1.0) and np.allclose(a["m1"], -b["m1"]) and a["win"] > 0.5      # the better server wins more sets, margins mirror


def _toy(n=400, seed=0):
    rng = np.random.default_rng(seed); ids = np.arange(1, 21); rows = []
    for i in range(n):
        w, l = rng.choice(ids, 2, replace=False); sv1, sv2 = int(rng.integers(40, 90)), int(rng.integers(40, 90))
        rows.append(dict(game_id=f"atp|T{i // 20}|{i}|0", tour="atp", date=pd.Timestamp("2018-01-01") + pd.Timedelta(days=7 * (i // 20)), season=2018, tourney_id=f"T{i // 20}", match_num=i, winner_id=w, loser_id=l, score="6-4 6-4", best_of=3,
                         w_svpt=sv1, w_1stWon=int(sv1 * 0.45), w_2ndWon=int(sv1 * 0.15), l_svpt=sv2, l_1stWon=int(sv2 * 0.4), l_2ndWon=int(sv2 * 0.12)))
    return {"matches": pd.DataFrame(rows)}


def test_hold_dp_builder_point_in_time_and_symmetry():
    raw = _toy(); out = T.compute(raw)["team"]
    assert not out.duplicated(["game_id", "team"]).any() and len(out) == 2 * len(raw["matches"])
    first = out[out.date == out.date.min()]; assert first[[c for c in out if c.startswith(("gps_", "hgm_"))]].isna().all().all()       # nothing before the first tournament
    late = raw["matches"].date.max(); pert = {"matches": raw["matches"].copy()}
    ix = pert["matches"].date == late
    pert["matches"].loc[ix, ["w_svpt", "w_1stWon", "w_2ndWon", "score"]] = [10, 9, 1, "7-6 7-6"]
    out2 = T.compute(pert)["team"]; cols = [c for c in out if c.startswith(("gps_", "hgm_"))]
    pd.testing.assert_frame_equal(out[out.date == late][cols].reset_index(drop=True), out2[out2.date == late][cols].reset_index(drop=True))     # a match's own outcome and same-date data never enter its features
    a = out.dropna(subset=["gps_hold_pre"]).sort_values(["game_id", "team"]).groupby("game_id"); one = a.first(); two = a.last()
    assert np.allclose(one.gps_p_tiebreak_pre, two.gps_p_tiebreak_pre, atol=1e-9) and np.allclose(one.gps_mean_games_pre, two.gps_mean_games_pre, atol=1e-9)      # total-games law is shared by both rows
    assert np.allclose(one.hgm_mean_margin_pre + two.hgm_mean_margin_pre, 0, atol=1e-9)           # margins are antisymmetric between the two rows of a match
    assert np.allclose(one.hgm_set_win_pre + two.hgm_set_win_pre, 1, atol=1e-9)


def test_hold_dp_specs_are_honest_partials():
    ids = [s.catalog_id for s in T.specs()]
    assert ids == ["ten.games_per_set_distribution", "ten.hold_gap_expected_margin"]
    for s in T.specs(): assert s.level == "PARTIAL" and s.missing and s.pit == "pregame_rolling" and all(c.endswith("_pre") for c in s.columns)


def test_hold_dp_replay_evidence_committed_and_clean():
    d = json.loads((DF / "verification/replay_ext/TENNIS_tennis4.json").read_text()); assert not d["quick"] and set(d["inputs"]) == {s.catalog_id for s in T.specs()}
    for iid, r in d["inputs"].items():
        t = r["tests"]; assert t["determinism"]["ok"] and t["own_game"]["ok"] and len(t["truncation"]) == 3 and all(x["ok"] for x in t["truncation"]) and all(x["ok"] for x in t["perturbation"]) and t["pit_check_perturbation_not_vacuous"]["ok"], iid
