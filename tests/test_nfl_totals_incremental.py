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
        assert g["verdict"] in ("VALIDATED_INCREMENTAL", "SUGGESTIVE_UNCONFIRMED", "WORSE_THAN_MARKET", "NOT_DEMONSTRATED")
