import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
from alpha_engine import nfl_totals_incremental as nt  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "research" / "audit" / "verification" / "NFL_totals_incremental.json"


def synth(signal=0.0, n_per=260, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(2015, 2026):
        for i in range(n_per):
            x = rng.normal()
            rows.append({"season": s, "week": 1 + i // 16, "game_id": f"{s}_{i}", "resid": signal * x + rng.normal(scale=13), "x": x})
    return pd.DataFrame(rows)


def run(df, feats=("x",)):
    df = df.copy()
    g = {"g1": list(feats)}
    orig = nt.groups
    nt.groups = lambda d: g
    try:
        return nt.evaluate(df)
    finally:
        nt.groups = orig


def test_noise_feature_is_not_validated():
    assert run(synth(0.0))["groups"]["g1"]["verdict"] != "VALIDATED_INCREMENTAL"


def test_planted_signal_is_validated():
    assert run(synth(6.0))["groups"]["g1"]["verdict"] == "VALIDATED_INCREMENTAL"


def test_training_never_uses_the_test_season():
    df = synth(0.0)
    df2 = df.copy()
    df2.loc[df2.season == 2025, "resid"] += 1000                    # a huge shock in the LAST season
    a, b = nt.predict(df.sort_values(["season", "week", "game_id"]).reset_index(drop=True), ["x"]), nt.predict(df2.sort_values(["season", "week", "game_id"]).reset_index(drop=True), ["x"])
    d = df.sort_values(["season", "week", "game_id"]).reset_index(drop=True)
    early = d["season"].to_numpy() < 2025
    assert np.allclose(a[early], b[early], equal_nan=True)         # earlier seasons' predictions cannot see the 2025 outcome


def test_committed_result_makes_no_promotion_or_betting_claim():
    d = json.loads(OUT.read_text())
    assert d["decision"].startswith("No input is wired")
    assert "after-fee" in " ".join(d["caveats"]) and "NOT tested" in " ".join(d["caveats"])
    assert d["n_groups_tried"] == len(d["groups"])
    for g in d["groups"].values():
        assert "mse_gain_vs_B1" in g and "bonferroni_ci_halfwidth_pct_of_base_mse" in g
        assert g["verdict"] in ("VALIDATED_INCREMENTAL", "SUGGESTIVE_UNCONFIRMED", "WORSE_THAN_MARKET", "NOT_DEMONSTRATED")


def test_intercept_bias_shift_alone_cannot_validate_a_useless_feature():
    """The market residual has a constant bias; a pure-noise feature must not 'win' just because ridge carries the past-mean intercept."""
    df = synth(0.0)
    df["resid"] = df["resid"] + 3.0                       # a persistent +3 point market bias
    r = run(df)["groups"]["g1"]
    assert r["mse_gain_vs_market_line_B0"] > r["mse_gain_vs_B1"] and r["verdict"] != "VALIDATED_INCREMENTAL"


def test_a_moderate_real_effect_is_detectable_in_a_realistic_sample():
    """Sensitivity near realistic size (3 points of signal on 13 points of noise) so that 'not demonstrated' is not an artefact of a too-strict gate."""
    assert run(synth(3.0))["groups"]["g1"]["verdict"] == "VALIDATED_INCREMENTAL"


def test_nested_cluster_intervals_always_nest():
    r = run(synth(1.0, seed=4))["groups"]["g1"]
    assert r["ci_bonferroni"][0] <= r["ci95_week_cluster"][0] and r["ci_bonferroni"][1] >= r["ci95_week_cluster"][1]


def test_engine_hook_applies_only_to_nfl_total_and_never_claims_absence():
    from alpha_engine import verification_engine as ve
    ctx, *_ = ve.run(write=False)
    ie = ctx["fams"]["NFL/TOTAL"]["projection"]["independent_evaluation"]
    assert ie["verdict"] == "NOT_DEMONSTRATED_VS_MARKET_UNDERPOWERED" and ie["group_verdicts"] == {"NOT_DEMONSTRATED": 7}
    assert "game totals only" in ie["baseline"]
    for k in ("NFL/TEAM_TOTAL", "NFL/PLAYER_STAT"):
        assert "independent_evaluation" not in ctx["fams"][k]["projection"]
    assert ctx["fams"]["NFL/TOTAL"]["stages"]["historical_eval"]["state"] == "PARTIAL"
