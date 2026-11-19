"""Two-key model promotion in the SIFT feed (sift_feed/promotion.py, operating_models.json).

A challenger is served as a sport's operating forecast only when BOTH the producer's block declares itself activated
(NBA_PAG_OPERATING=1 / CFB_OAE_OPERATING=1) AND the reviewed manifest names that exact model_version. Every other case
serves the incumbent (NBA) or nothing (CFB), flagged, and never relabels a shadow block. Offline, synthetic artifacts.
"""
import copy
import gzip
import json
import shutil
from pathlib import Path

import pytest

from sift_feed import adapters, build, promotion
from sift_feed.schema import OPERATING, PRODUCTION, parse_ts, validate_game
from sift_feed.sources import DirSource

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "sift_feed"
NOW = parse_ts("2026-11-18T19:00:00Z")
PAG_VERSION = "pag-1.0.0+periods-1.0.0"
OAE_VERSION = "cfb-oae-1.0.0"
APPROVAL = {"approved_by": "owner", "approved_at": "2026-11-20", "approval_ref": "https://example.invalid/pr/1"}

PAG_SHADOW = {"activation": "not_activated", "authority": "research_only", "betting_authority": "NONE", "role": "shadow",
              "operating_forecast": False}
PAG_OPERATING = {"activation": "activated", "authority": "operating_forecast", "betting_authority": "NONE",
                 "role": "operating", "operating_forecast": True}
OAE_SHADOW = {"status": "not_activated", "activated": False, "authority": "research_only", "role": "shadow",
              "bet_authority": False, "operating_forecast": False}
OAE_OPERATING = {"status": "activated", "activated": True, "authority": "operating_forecast", "role": "operating",
                 "bet_authority": False, "operating_forecast": True}


def manifest(tmp_path, monkeypatch, **promoted):
    doc = json.loads(promotion.MANIFEST.read_text())
    for sport, version in promoted.items():
        doc["sports"][sport]["promoted"] = None if version is None else {"model_version": version, **APPROVAL}
    path = tmp_path / "operating_models.json"
    path.write_text(json.dumps(doc))
    monkeypatch.setattr(promotion, "MANIFEST", path)
    return path


def srcs(sport, extra=None):
    mod = adapters.load(sport)
    spec = mod.sources() if hasattr(mod, "sources") else mod.SOURCES
    out = {}
    for k, (repo, branch) in spec.items():
        root = (extra or {}).get(k) or FIX / sport.lower() / k
        out[k] = DirSource(root, repo=f"chmoses98/{repo}", ref=branch, commit="b" * 40,
                           committed_at="2026-11-18T18:00:00Z")
    return out


def run(sport, extra=None, now=NOW):
    mod = adapters.load(sport)
    return build.finalize(sport, mod, mod.build(srcs(sport, extra), now), now)


def pag_archive(tmp_path, decl, version=PAG_VERSION, games=("espn:401910007",), newest_without_block=False, mutate=None):
    """projection-data game_forecasts/nba/<day>/*.jsonl.gz with a pf record (+ pag_v1) for the given games."""
    root = tmp_path / "projection-data"
    rows = []
    for gid in games:
        rec = {"game_id": gid, "game_start_utc": "2026-11-19T00:00:00Z", "home": "CLE", "away": "MEM",
               "generated_utc": "2026-11-18T16:20:00Z", "model_version": "pf-1.3.0+x",
               "pag_v1": {"model_id": "pf-nba-pag", "model_version": version, **decl,
                          "generated_utc": "2026-11-18T16:20:00Z", "frozen_sha256": "f" * 64,
                          "full_game": {"p_home_win": 0.71, "margin_mean": 8.4, "margin_sd": 13.1},
                          "periods": {"segments": {
                              "H1": {"total_mean": 113.2, "home_mean": 58.1, "away_mean": 55.1, "published": ["total", "team_total"],
                                     "settlement_basis": "regulation_only: Q1+Q2"},
                              "Q4": {"total_mean": 55.0, "home_mean": 28.0, "away_mean": 27.0, "published": ["total"],
                                     "settlement_basis": "regulation_only: Q4"}}}}}
        if mutate is not None:
            mutate(rec["pag_v1"])
        rows.append(rec)
        if newest_without_block:
            later = {k: v for k, v in rec.items() if k != "pag_v1"}
            rows.append(dict(later, generated_utc="2026-11-18T18:20:00Z"))
    d = root / "game_forecasts" / "nba" / "2026-11-19"
    d.mkdir(parents=True)
    (d / "162000Z_test.jsonl.gz").write_bytes(gzip.compress("\n".join(json.dumps(r) for r in rows).encode()))
    return root


# ------------------------------------------------------------------------------------------------ manifest
def test_committed_manifest_promotes_exactly_the_approved_versions():
    """ACTIVATION change (NBA): the consumer key names the approved NBA model; the producer key must ALSO be set for any game
    to be served from them (tests below)."""
    doc = promotion.load()
    promoted = {s: (e["promoted"] or {}).get("model_version") for s, e in doc["sports"].items()}
    assert promoted == {"NBA": PAG_VERSION, "CFB": None}     # NBA only: CFB is promoted (or rolled back) by its own change


def test_a_promotion_without_its_approval_record_is_rejected(tmp_path, monkeypatch):
    path = manifest(tmp_path, monkeypatch, NBA=PAG_VERSION)
    doc = json.loads(path.read_text())
    doc["sports"]["NBA"]["promoted"].pop("approved_by")
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="approved_by"):
        promotion.load()


# ------------------------------------------------------------------------------------------------ NBA
def test_nba_both_keys_serve_the_promoted_model_and_fall_back_per_game(tmp_path, monkeypatch):
    manifest(tmp_path, monkeypatch, NBA=PAG_VERSION)
    summary, gs, _ = run("NBA", {"promoted": pag_archive(tmp_path, PAG_OPERATING)})
    cle, ind = (next(g for g in gs if g["game_id"] == gid) for gid in ("espn:401910007", "espn:401910008"))
    assert cle["model_version"] == PAG_VERSION and cle["source_class"] == PRODUCTION
    assert cle["spread"] == "CLE -8.4" and cle["home_spread"] == -8.4 and cle["win_probability"]["home"] == 0.71
    assert cle["projected_total"] is None and cle["team_totals"] is None          # PAG publishes no full-game total
    assert cle["period_projections"]["H1"]["total"] == 113.2 and cle["period_projections"]["Q4"]["home"] is None
    assert cle["source"].startswith("chmoses98/nba-edge-finder@") and "game_forecasts/nba" in cle["source"]
    assert ind["model_version"] == "nba-sim-0.1.0" and ind["source_class"] == OPERATING
    assert any(f.startswith("fallback_incumbent: no promoted-model record") for f in ind["flags"])
    assert summary["promotion"]["state"] == "partial" and summary["promotion"]["games_served"] == 1
    assert summary["source_class"] == OPERATING                                   # mixed sport = the weaker class
    assert all(validate_game(g) == [] for g in gs)


def test_nba_all_games_promoted_labels_the_sport_from_the_promoted_declaration(tmp_path, monkeypatch):
    manifest(tmp_path, monkeypatch, NBA=PAG_VERSION)
    archive = pag_archive(tmp_path, PAG_OPERATING, games=("espn:401910007", "espn:401910008"))
    summary, gs, _ = run("NBA", {"promoted": archive})
    assert {g["model_version"] for g in gs} == {PAG_VERSION}
    assert summary["promotion"]["state"] == "active" and summary["source_class"] == PRODUCTION
    assert summary["model_version"] == PAG_VERSION


@pytest.mark.parametrize("decl,version,expect", [
    (PAG_SHADOW, PAG_VERSION, "producer has not activated"),          # manifest key without the producer key
    (PAG_OPERATING, "pag-9.9.9", "is not the promoted"),                # producer activated a different version
])
def test_nba_one_key_alone_serves_the_incumbent(tmp_path, monkeypatch, decl, version, expect):
    manifest(tmp_path, monkeypatch, NBA=PAG_VERSION)
    summary, gs, _ = run("NBA", {"promoted": pag_archive(tmp_path, decl, version=version)})
    assert {g["model_version"] for g in gs} == {"nba-sim-0.1.0"} and {g["source_class"] for g in gs} == {OPERATING}
    cle = next(g for g in gs if g["game_id"] == "espn:401910007")
    assert any(expect in f for f in cle["flags"])
    assert summary["promotion"]["state"] == "awaiting_producer_activation"


def test_nba_newest_run_without_a_block_is_not_replaced_by_an_older_block(tmp_path, monkeypatch):
    manifest(tmp_path, monkeypatch, NBA=PAG_VERSION)
    _, gs, _ = run("NBA", {"promoted": pag_archive(tmp_path, PAG_OPERATING, newest_without_block=True)})
    cle = next(g for g in gs if g["game_id"] == "espn:401910007")
    assert cle["model_version"] == "nba-sim-0.1.0"
    assert any("newest projection run published no pag_v1" in f for f in cle["flags"])


def test_nba_producer_key_alone_changes_nothing_and_rollback_is_byte_identical(tmp_path, monkeypatch):
    manifest(tmp_path, monkeypatch, NBA=None)  # consumer key off; the producer may be activated, it is never read
    baseline = run("NBA")
    assert run("NBA", {"promoted": pag_archive(tmp_path, PAG_OPERATING)}) == baseline
    assert baseline[0]["promotion"] is None


# ------------------------------------------------------------------------------------------------ CFB
def oae_projection(tmp_path, decl, version=OAE_VERSION, available=True):
    root = tmp_path / "cfb-research"
    shutil.copytree(FIX / "cfb" / "research", root)
    path = root / "projections" / "cfb" / "latest.json"
    doc = json.loads(path.read_text())
    g0 = doc["games"][0]
    doc["oae_challenger"] = {"model_version": version, **decl, "available": available, "unavailable_reason": None,
                             "note": "x", "forecast_utc": "2026-11-18T18:00:00Z", "excluded": {"fg_total": "PARTIAL"},
                             "games": [{"game_id": g0["game_id"], "start_utc": g0["start_utc"],
                                        "fg": {"expected_margin": -6.5, "spread_home": 6.5, "sigma_margin": 15.9,
                                               "p_home_win": 0.34, "p_away_win": 0.66, "spread_ladder": []},
                                        "periods": {"q2": {"expected_total": 13.9, "total_ladder": []}}}]}
    path.write_text(json.dumps(doc))
    return root, g0


def test_cfb_both_keys_serve_the_promoted_model(tmp_path, monkeypatch):
    manifest(tmp_path, monkeypatch, CFB=OAE_VERSION)
    root, g0 = oae_projection(tmp_path, OAE_OPERATING)
    summary, gs, rs = run("CFB", {"research": root})
    assert summary["status"] == "ok" and summary["source_class"] == PRODUCTION and len(gs) == 1
    g = gs[0]
    assert g["home"]["name"] == g0["home"] and g["spread"] == f"{g0['away']} -6.5" and g["home_spread"] == 6.5
    assert g["projected_winner"] == g0["away"] and g["period_projections"]["q2"] == {"expected_total": 13.9}
    assert g["projected_total"] is None and validate_game(g) == []
    assert rs and all(r["source_class"] == "research" for r in rs)      # the pf-cfb shadow stays research


@pytest.mark.parametrize("decl,version,available,expect", [
    (OAE_SHADOW, OAE_VERSION, True, "producer has not activated"),
    (OAE_OPERATING, "cfb-oae-9", True, "is not the promoted"),
    (OAE_OPERATING, OAE_VERSION, False, "block unavailable"),
])
def test_cfb_one_key_alone_stays_unavailable(tmp_path, monkeypatch, decl, version, available, expect):
    manifest(tmp_path, monkeypatch, CFB=OAE_VERSION)
    root, _ = oae_projection(tmp_path, decl, version, available)
    summary, gs, _ = run("CFB", {"research": root})
    assert summary["status"] == "unavailable" and gs == [] and expect in summary["reason"]
    assert summary["promotion"]["state"] == "awaiting_producer_activation"


def test_cfb_rollback_is_identical_to_the_incumbent(tmp_path, monkeypatch):
    manifest(tmp_path, monkeypatch, CFB=None)
    baseline = run("CFB")
    root, _ = oae_projection(tmp_path, OAE_OPERATING)
    summary, gs, rs = run("CFB", {"research": root})
    assert (summary, gs) == (baseline[0], baseline[1])


def test_promotion_never_changes_the_research_rule(tmp_path, monkeypatch):
    """The production adapters' own sources still never point at research branches; a promoted source exists only
    while the manifest names a promotion, and only under the explicit `promoted` key."""
    manifest(tmp_path, monkeypatch, NBA=PAG_VERSION)
    spec = adapters.load("NBA").sources()
    assert spec["prod"] == ("nba-edge-finder", "data-archive") and spec["promoted"][1] == "projection-data"
    assert copy.deepcopy(adapters.load("NBA").SOURCES) == {"prod": ("nba-edge-finder", "data-archive")}


# ------------------------------------------------------------------------------------------------ invalid / unavailable forecasts
def _set(path, value):
    def f(b):
        d = b
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = value
    return f


INVALID_PAG = {
    "p_nan": (("full_game", "p_home_win"), float("nan")), "p_inf": (("full_game", "p_home_win"), float("inf")),
    "p_above_1": (("full_game", "p_home_win"), 1.3), "p_zero": (("full_game", "p_home_win"), 0.0),
    "p_missing": (("full_game", "p_home_win"), None), "p_string": (("full_game", "p_home_win"), "0.7"),
    "margin_nan": (("full_game", "margin_mean"), float("nan")), "margin_neg_inf": (("full_game", "margin_mean"), float("-inf")),
    "margin_absurd": (("full_game", "margin_mean"), 400.0), "sd_zero": (("full_game", "margin_sd"), 0.0),
    "sign_incoherent": (("full_game", "margin_mean"), -8.4),          # p_home 0.71 but the home side is the underdog
    "period_nan": (("periods", "segments", "H1", "total_mean"), float("nan")),
    "period_negative": (("periods", "segments", "Q4", "home_mean"), -3.0),
}


@pytest.mark.parametrize("case", sorted(INVALID_PAG))
def test_nba_invalid_promoted_block_falls_back_to_the_incumbent(tmp_path, monkeypatch, case):
    manifest(tmp_path, monkeypatch, NBA=PAG_VERSION)
    path, value = INVALID_PAG[case]
    summary, gs, _ = run("NBA", {"promoted": pag_archive(tmp_path, PAG_OPERATING, mutate=_set(path, value))})
    cle = next(g for g in gs if g["game_id"] == "espn:401910007")
    assert cle["model_version"] == "nba-sim-0.1.0" and cle["source_class"] == OPERATING
    assert any(f.startswith("fallback_incumbent: promoted block failed validation") for f in cle["flags"]), cle["flags"]
    assert summary["promotion"]["games_served"] == 0 and summary["promotion"]["state"] == "awaiting_producer_activation"
    assert summary["model_version"] == "nba-sim-0.1.0" and all(validate_game(g) == [] for g in gs)
    index, per = build.assemble({"NBA": (summary, gs, [])}, NOW)
    build.dumps(index), build.dumps(per["NBA"])                     # strict JSON: would raise on NaN / Infinity


def test_nba_producer_withheld_stub_falls_back_to_the_incumbent(tmp_path, monkeypatch):
    """The producer guard's `unavailable` stub (nba-edge-finder pag.unavailable_block) is never served, even with both keys."""
    manifest(tmp_path, monkeypatch, NBA=PAG_VERSION)
    stub = {"activation": "unavailable", "authority": "none", "betting_authority": "NONE", "role": "unavailable",
            "operating_forecast": False}

    def to_stub(b):
        for k in ("full_game", "periods"):
            b.pop(k)
        b.update(stub, available=False, unavailable_reason=["non-finite values at ['$.full_game.p_home_win']"])
    summary, gs, _ = run("NBA", {"promoted": pag_archive(tmp_path, PAG_OPERATING, mutate=to_stub)})
    cle = next(g for g in gs if g["game_id"] == "espn:401910007")
    assert cle["model_version"] == "nba-sim-0.1.0"
    assert any(f.startswith("fallback_incumbent: producer withheld the forecast: non-finite") for f in cle["flags"])
    assert summary["promotion"]["games_served"] == 0


def test_nba_valid_promoted_block_is_still_served_beside_an_invalid_one(tmp_path, monkeypatch):
    manifest(tmp_path, monkeypatch, NBA=PAG_VERSION)
    root = pag_archive(tmp_path, PAG_OPERATING, games=("espn:401910007", "espn:401910008"))
    f = next(root.rglob("*.jsonl.gz"))
    rows = [json.loads(x) for x in gzip.decompress(f.read_bytes()).decode().splitlines()]
    rows[1]["pag_v1"]["full_game"]["p_home_win"] = float("nan")
    f.write_bytes(gzip.compress("\n".join(json.dumps(r) for r in rows).encode()))
    summary, gs, _ = run("NBA", {"promoted": root})
    by = {g["game_id"]: g for g in gs}
    assert by["espn:401910007"]["model_version"] == PAG_VERSION
    assert by["espn:401910008"]["model_version"] == "nba-sim-0.1.0"
    assert summary["promotion"]["state"] == "partial" and summary["promotion"]["games_served"] == 1


@pytest.mark.parametrize("field,value", [("p_home_win", float("nan")), ("expected_margin", float("inf")), ("p_home_win", 1.4),
                                         ("p_away_win", 0.9), ("spread_home", -6.5), ("sigma_margin", -1.0)])
def test_cfb_invalid_promoted_game_is_withheld_not_served(tmp_path, monkeypatch, field, value):
    manifest(tmp_path, monkeypatch, CFB=OAE_VERSION)
    root, _ = oae_projection(tmp_path, OAE_OPERATING)
    path = root / "projections" / "cfb" / "latest.json"
    doc = json.loads(path.read_text())
    doc["oae_challenger"]["games"][0]["fg"][field] = value
    path.write_text(json.dumps(doc))
    summary, gs, _ = run("CFB", {"research": root})
    assert gs == [] and summary["status"] == "unavailable" and "failed validation" in summary["reason"]
    assert summary["withheld_games"] and summary["promotion"]["games_served"] == 0


def test_finalize_withholds_an_invalid_game_instead_of_failing_the_feed():
    mod = adapters.load("NBA")
    res = mod.build(srcs("NBA"), NOW)
    bad = copy.deepcopy(res["games"][0])
    bad["game_id"] = "espn:bad"
    bad["projected_margin_home"], bad["home_spread"], bad["spread"] = float("nan"), float("nan"), "X -nan"
    res["games"].append(bad)
    summary, gs, _ = build.finalize("NBA", mod, res, NOW)
    assert "espn:bad" not in {g["game_id"] for g in gs} and len(gs) == len(res["games"]) - 1
    assert any("espn:bad" in w and "not a finite number" in w for w in summary["withheld_games"])
    with pytest.raises(ValueError):
        build.dumps({"x": float("nan")})
