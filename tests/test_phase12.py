"""Phase 12: discovery engine protocol, MLB v1.1 and NBA team-box point-in-time rules, vault evidence, market coverage (synthetic data only)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alpha_engine.certify import mlb_game_v11 as M
from alpha_engine.discovery import engine as E, kalshi_labels as K
from alpha_engine.features import nba_team_box as N
from alpha_engine.foundation import acquisition as A, market_coverage as MC
from alpha_engine.input_research.data_foundation import datasets as DS, evidence as EV

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------------------------------------ discovery engine
def _toy(seed=0, n_seasons=8, per=120):
    rng = np.random.default_rng(seed); rows = []
    for s in range(2010, 2010 + n_seasons):
        for i in range(per):
            a, b = rng.normal(size=2)
            rows.append({"game_id": f"{s}_{i}", "season": s, "week": i // 10, "gameday": f"{s}-09-{1 + i % 28:02d}", "home_x_pre": a, "away_x_pre": b, "home_noise_pre": rng.normal(),
                         "away_noise_pre": rng.normal(), "y_home_margin": 3 * (a - b) + rng.normal(scale=5), "y_total": 40 + rng.normal(scale=8)})
    return pd.DataFrame(rows)


def _prereg(d):
    return {"study": "toy", "sport": "NFL", "dataset_sha256": E.canonical_hash(d), "order_column": "gameday", "cluster_column": "week", "min_train": 200,
            "walk_forward_seasons": list(range(2013, 2018)), "splits": {"dev": [2013, 2014], "test": [2015, 2016], "holdout": [2017]},
            "groups": {"x": ["x_pre"], "noise": ["noise_pre"]}, "models": {"climatology": [], "ref": ["noise"], "full": ["x", "noise"]}, "reference_model": "ref", "full_model": "full",
            "targets": {"margin": {"column": "y_home_margin", "binary_from_sign": True, "market_line": "spread_line"}, "total": {"column": "y_total"}},
            "hypotheses": [{"group": "x", "target": "margin"}, {"group": "x", "target": "total"}]}


def test_engine_finds_real_signal_and_rejects_noise_target():
    d = _toy(); p = _prereg(d)
    r = E.run(p, d, None)
    h = {x["target"]: x for x in r["hypotheses_test"]}
    assert h["margin"]["verdict"] == "DEMONSTRATED_INCREMENTAL" and h["margin"]["gain_sq_err"] > 0
    assert h["total"]["verdict"] != "DEMONSTRATED_INCREMENTAL"
    assert "holdout" not in r and r["test"]["targets"]["margin"]["models"]["full"]["rmse"] < r["test"]["targets"]["margin"]["models"]["ref"]["rmse"]


def test_holdout_outcomes_cannot_reach_dev_or_test_results():
    d = _toy(); p = _prereg(d)
    a = E.run(p, d, None); d2 = d.copy()
    d2.loc[d2.season == 2017, ["y_home_margin", "y_total"]] = 999.0          # change only holdout outcomes
    b = E.run(p, d2, None)
    a.pop("_predictions"); b.pop("_predictions")
    assert json.dumps(a["test"], sort_keys=True) == json.dumps(b["test"], sort_keys=True) and a["hypotheses_test"] == b["hypotheses_test"]
    assert set(E.run(p, d, None, holdout=True)) >= {"holdout"}


def test_walk_forward_never_uses_the_predicted_or_later_seasons():
    d = _toy(); p = _prereg(d)
    feats = E.group_columns(p, ["x"], set(d.columns))
    mu, _ = E.walk_forward(d, feats, "y_home_margin", [2014], 200)
    d2 = d.copy(); d2.loc[d2.season >= 2014, "y_home_margin"] += 50
    mu2, _ = E.walk_forward(d2, feats, "y_home_margin", [2014], 200)
    k = (d.season == 2014).to_numpy()
    assert np.allclose(mu[k], mu2[k]) and np.isnan(mu[~k]).all()


def test_market_and_postgame_columns_are_refused_as_features():
    d = _toy(); d["home_spread_line"] = 1.0; d["away_spread_line"] = 1.0
    p = _prereg(d); p["groups"]["bad"] = ["spread_line"]
    with pytest.raises(ValueError):
        E.group_columns(p, ["bad"], set(d.columns))


def test_dataset_must_match_prereg_hash_and_be_registered(tmp_path):
    d = _toy(); p = _prereg(d); f = tmp_path / "d.parquet"; d.to_parquet(f)
    v = tmp_path / "versions.json"
    v.write_text(json.dumps({"versions": [{"sport": "NFL", "canonical_sha256": p["dataset_sha256"], "superseded_by": None}]}))
    assert len(E.load_dataset(f, p, v)) == len(d)
    with pytest.raises(ValueError):
        E.load_dataset(f, {**p, "dataset_sha256": "0" * 64}, v)
    v.write_text(json.dumps({"versions": [{"sport": "NFL", "canonical_sha256": p["dataset_sha256"], "superseded_by": "x"}]}))
    with pytest.raises(ValueError):
        E.load_dataset(f, p, v)


def test_prereg_hash_changes_with_any_edit():
    p = _prereg(_toy()); q = json.loads(json.dumps(p)); q["hypotheses"].append({"group": "noise", "target": "total"})
    assert E.prereg_hash(p) != E.prereg_hash(q) and E.prereg_hash(p) == E.prereg_hash(json.loads(json.dumps(p)))


def test_committed_studies_are_consistent():
    reg = {(e["sport"], e["canonical_sha256"]) for e in json.loads((ROOT / "research/certification/dataset_versions.json").read_text())["versions"] if not e.get("superseded_by")}
    studies = [p for p in (ROOT / "research/discovery").iterdir() if p.is_dir()]
    assert len(studies) >= 6
    for p in studies:
        pr = json.loads((p / "prereg.json").read_text()); r = json.loads((p / "results.json").read_text()); h = json.loads((p / "holdout.json").read_text())
        assert r["prereg_sha256"] == h["prereg_sha256"] == E.prereg_hash(pr), p.name
        assert (pr["sport"], pr["dataset_sha256"]) in reg, p.name
        assert not set(pr["splits"]["holdout"]) & (set(pr["splits"]["dev"]) | set(pr["splits"]["test"]))
        assert "holdout" not in r and set(h) >= {"holdout"}
        assert len(r["hypotheses_test"]) == len(pr["hypotheses"])


def test_official_join_and_yes_probability_use_betting_convention():
    off = pd.DataFrame([{"ticker": "KXNFLSPREAD-26NOV15PITCIN-CIN7", "event": "KXNFLSPREAD-26NOV15PITCIN", "family": "spread", "pair": "PITCIN", "date": "2026-11-15", "suffix": "CIN7", "strike": 6.5, "result": "yes", "status": "finalized", "strike_type": "greater"},
                        {"ticker": "KXNFLSPREAD-26NOV15PITCIN-PIT7", "event": "KXNFLSPREAD-26NOV15PITCIN", "family": "spread", "pair": "PITCIN", "date": "2026-11-15", "suffix": "PIT7", "strike": 6.5, "result": "no", "status": "finalized", "strike_type": "greater"}])
    g = pd.DataFrame([{"game_id": "g1", "date": "2026-11-15", "home": "CIN", "away": "PIT"}])
    o = K.join_games(off, g, {})
    assert o.side.tolist() == ["home", "away"]
    pred = pd.DataFrame([{"game_id": "g1", "margin_mu": 7.0, "margin_sigma": 13.0, "margin_actual": 7.0}])
    o = K.yes_probability(o, pred, {"spread": ("spread", "margin")})
    assert o.y_derived.tolist() == [1.0, 0.0]            # home at -6.5 must win by at least 7: a 7-point win covers
    assert o.p_model[0] > 0.5 > o.p_model[1] and o.y_official.tolist() == [1.0, 0.0]


# ------------------------------------------------------------------------------------------------ MLB v1.1
def _g(i, team_h, team_a, start, hours=3.0, hr=5, ar=3):
    t0 = datetime(2024, 4, 1, tzinfo=timezone.utc) + timedelta(hours=start)
    return {"game_id": i, "season": 2024, "official_date": t0.strftime("%Y-%m-%d"), "start": t0, "end": t0 + timedelta(hours=hours), "game_number": 1, "home_id": team_h, "away_id": team_a,
            "home_runs": hr, "away_runs": ar, "home_bat": (9, 3, 1, 14, 34), "away_bat": (7, 2, 0, 9, 33), "home_r6": hr - 1, "away_r6": ar, "home_rel": (1, 9), "away_rel": (2, 6)}


def test_mlb_v11_prior_rule_lead_and_unresolved():
    games = [_g(1, 10, 20, 0), _g(2, 10, 30, 24), _g(3, 10, 20, 26, hours=30), _g(4, 10, 30, 48)]      # game 3 is suspended and ends after game 4 starts
    d = M.build(games).set_index("game_id")
    assert d.loc[1, "home_n_pre"] == 0 and np.isnan(d.loc[1, "home_win_pct_pre"]) and d.loc[1, "home_games_remaining_pre"] == 162
    assert d.loc[4, "home_n_pre"] == 2 and d.loc[4, "home_unresolved_pre"] == 1 and d.loc[4, "home_wins_pre"] == 2 and d.loc[4, "home_run_diff_pre"] == 4
    assert d.loc[4, "home_pyth_pct_pre"] == pytest.approx(10 ** 1.83 / (10 ** 1.83 + 6 ** 1.83))
    d24 = M.build(games, 24.0).set_index("game_id")
    assert d24.loc[4, "home_n_pre"] == 1 and d24.loc[2, "home_n_pre"] == 0      # a 24 h lead hides games that ended inside the last day
    odd = [_g(1, 10, 20, 0), {**_g(2, 10, 30, 24), "end": datetime(2024, 4, 1, 12, tzinfo=timezone.utc)}]   # feed whose last play is stamped before first pitch
    assert M.build(odd).set_index("game_id").loc[2, "home_n_pre"] == 1          # the game is never its own prior
    chk = M.leakage_checks(games, M.build(games), 0.0, n_cutoffs=4)
    assert chk["truncation_identical"] and chk["future_scramble_identical"] and chk["own_outcome_scramble_identical"]


# ------------------------------------------------------------------------------------------------ NBA team box
def _nba_raw():
    rows = []; rng = np.random.default_rng(1); gid = 0
    for day in range(12):
        for h, a in ((1, 2), (3, 4)) if day % 2 == 0 else ((2, 3), (4, 1)):
            gid += 1
            for side, tid, opp in (("home", h, a), ("away", a, h)):
                r = {"game_id": gid, "season": 2024, "season_type": 2, "game_date": pd.Timestamp("2023-11-01") + pd.Timedelta(days=day), "team_id": tid, "team_home_away": side}
                r.update({c: int(v) for c, v in zip(N.NUM, [100 + rng.integers(0, 20), 0, 38, 85, 11, 32, 18, 24, 10, 33, 14])})
                rows.append(r)
    t = pd.DataFrame(rows)
    sc = t.groupby("game_id").team_score.apply(list)
    t["opponent_team_score"] = [sc[g][1] if s == "home" else sc[g][0] for g, s in zip(t.game_id, t.team_home_away)]
    return {"team_box": t, "schedule": pd.DataFrame({"game_id": sorted(t.game_id.unique()), "date": "2023-11-01T00:00Z", "neutral_site": False})}


def test_nba_team_box_uses_strictly_earlier_dates_only():
    raw = _nba_raw(); d = N.build(raw)
    assert len(d) == 24 and d.home_n_pre.iloc[0] == 0 and np.isnan(d.home_off_rtg_pre.iloc[0])
    last = d.iloc[-1]
    t = raw["team_box"]; tid = last.home_team_id; prior = t[(t.team_id == tid) & (t.game_date < pd.Timestamp(last.date))]
    assert last.home_n_pre == len(prior) and last.home_efg_pre == pytest.approx((prior.field_goals_made.sum() + 0.5 * prior.three_point_field_goals_made.sum()) / prior.field_goals_attempted.sum())
    chk = N.leakage_checks(raw, d, ["2023-11-06"])["2023-11-06"]
    assert chk["truncation_identical"] and chk["future_scramble_identical"] and chk["own_game_identical"] and chk["perturbation_reaches_later_games"]


# ------------------------------------------------------------------------------------------------ vault evidence, readiness, coverage
def test_vault_evidence_points_at_measured_ledger_entries_and_resolves_held():
    led = json.loads((ROOT / "research/input_research/data_collection/vault_ledger.json").read_text())["datasets"]
    reg = json.loads((ROOT / "research/input_research/data_foundation/datasets.json").read_text())["datasets"]
    for did, keys in DS.VAULT_EVIDENCE.items():
        for k in keys:
            assert k in led and (led[k].get("rows") or led[k].get("games")), (did, k)
        assert reg[did]["access_status"] == "COLLECTED_ARCHIVE", did
    assert all("scope_note" in v for v in led.values())


def test_dataset_without_ledger_entry_is_not_held(monkeypatch):
    monkeypatch.setattr(EV, "ledgers", lambda: {})
    out = EV.resolve_all()
    assert out["mlb.pitch_pa_events"]["access_status"] != "COLLECTED_ARCHIVE" and out["cbb.box_player"]["access_status"] != "COLLECTED_ARCHIVE"


def test_history_must_hold_for_every_need():
    ds = {"long": {"history": {"first": "2010", "last": "2026"}}, "short": {"history": {"first": "2025", "last": "2026"}}}
    inp = {"chain": ["OK"] * 5 + ["MISSING"] * 3, "pit": "PIT_SAFE"}
    r = A.readiness(inp, {"A": {"long"}, "B": {"short"}}, {"long", "short"}, ds)
    assert r["c"]["history"] == "PARTIAL" and r["state"] != "TRAINING_READY"
    assert A.readiness(inp, {"A": {"long"}}, {"long"}, ds)["state"] == "TRAINING_READY"


def test_certification_promotes_only_listed_inputs_of_live_versions():
    cert = A.load_certification()
    for k in ("MLB:mlb.pythag_luck", "MLB:mlb.wins_to_date_and_games_remaining", "NBA:nba.four_factors_matchup", "NBA:nba.pythag_residual", "NBA:nba.rebound_pool"):
        assert k in cert and cert[k]["builder_columns"] and cert[k]["seasons"] >= 3, k
    for k in ("MLB:mlb.sp_quality", "NBA:nba.pace", "NBA:nba.rest_travel", "MLB:mlb.opp_strength"):
        assert k not in cert                       # held back: definition not fully implemented or not point-in-time
    inputs = json.loads((ROOT / "research/data_foundation_ops/acquisition_inputs.json").read_text())["inputs"]
    assert sum(1 for v in inputs.values() if v["tr"]["state"] == "TRAINING_READY") == 58   # Phase 12 continued: +4 NBA player-box inputs (blind-certified v1.1)


def test_market_coverage_is_exhaustive_and_reconciles():
    c = json.loads((ROOT / "research/data_foundation_ops/market_coverage.json").read_text())
    assert set(c["sports"]) == set(MC.CORE) and sum(c["now"]["cls"].values()) == c["now"]["inputs"] == len(c["inputs"])
    assert all(v["cls"] in MC.CLASSES for v in c["inputs"].values())
    assert sum(c["before"]["totals"]["cls"].values()) == c["before"]["totals"]["inputs"] == c["now"]["inputs"]
    assert c["before"]["totals"]["missing_primary_slots"] == 715 and c["before"]["totals"]["missing_primary_inputs"] == 565
    for s, x in c["sports"].items():
        assert sum(x["cls"].values()) == x["inputs"]
        for m in x["markets"]:
            assert all(i in c["inputs"] for i, _ in m["inputs"]) and m["next"]
    certified = {k for k, v in c["inputs"].items() if v["cls"] == "CERTIFIED"}
    assert all(c["inputs"][k]["st"] == "TRAINING_READY" for k in certified)
