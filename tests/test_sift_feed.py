"""SIFT projection feed (schema v1): adapters against recorded production fixtures, spread notation,
staleness, production-vs-research labelling, size budget and the consumer sentence. Offline."""
import json
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from sift_feed import adapters, build, say
from sift_feed.schema import (OPERATING, PRODUCTION, RESEARCH, SCHEMA_VERSION, SOURCE_CLASSES, SPORT_STATUSES, classify,
                              make_game, parse_ts, spread_fields, validate_game)
from sift_feed.sources import DirSource

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "sift_feed"
NOW = parse_ts("2026-11-18T19:00:00Z")
NHL_NOW = parse_ts("2026-11-18T02:50:00Z")  # the recorded NHL slate's games start 03:00Z


def sources(sport, root=FIX):
    mod = adapters.load(sport)
    return {k: DirSource(root / sport.lower() / k, repo=f"chmoses98/{repo}", ref=branch, commit="a" * 40,
                         committed_at="2026-11-18T18:00:00Z")
            for k, (repo, branch) in mod.SOURCES.items()}


def run(sport, now=NOW, root=FIX):
    mod = adapters.load(sport)
    return build.finalize(sport, mod, mod.build(sources(sport, root), now), now)


def game(gs, gid):
    return next(g for g in gs if g["game_id"] == gid)


# ---- spread notation -------------------------------------------------------------------------
def test_spread_home_favourite():
    assert spread_fields(8.36, "BOS", "NYK") == (-8.4, "BOS -8.4")


def test_spread_away_favourite():
    assert spread_fields(-3.44, "DEN", "BOS") == (3.4, "BOS -3.4")


@pytest.mark.parametrize("m", [0.0, 0.04, -0.04])
def test_spread_pickem(m):
    assert spread_fields(m, "A", "B") == (0.0, "PK")


def test_spread_missing_margin_is_null():
    assert spread_fields(None, "A", "B") == (None, None)


def test_validate_catches_wrong_spread_sign():
    g = make_game(sport="NBA", game_id="x", start_time="2026-11-19T00:00:00Z", home={"name": None, "abbr": "A"},
                  away={"name": None, "abbr": "B"}, model_version="m", projected_at="2026-11-18T18:00:00Z", source="s",
                  declaration={"authority": "RESEARCH"}, p_home=0.7, margin_home=5.0)
    assert validate_game(g) == []
    g["home_spread"] = 5.0
    assert "home_spread sign does not oppose margin" in validate_game(g)


# ---- adapters on recorded fixtures --------------------------------------------------------
def test_nba_adapter_values_and_signs():
    summary, gs, rs = run("NBA")
    assert summary["status"] == "ok" and rs == []
    cle = game(gs, "espn:401910007")  # MEM @ CLE, home favourite
    assert (cle["home"]["abbr"], cle["away"]["abbr"]) == ("CLE", "MEM")
    assert cle["spread"] == "CLE -13.4" and cle["home_spread"] == -13.4 and cle["projected_winner"] == "CLE"
    assert cle["win_probability"] == {"home": 0.795, "away": 0.205}
    assert cle["projected_total"] == 235.9 and cle["team_totals"] == {"home": 124.6, "away": 111.3}
    assert cle["spread"] == cle["detail"]["model_spread_label"]  # agrees with the slate's own label
    ind = game(gs, "espn:401910008")  # HOU @ IND, away favourite
    assert ind["spread"].startswith("HOU -") and ind["home_spread"] > 0 and ind["projected_winner"] == "HOU"
    assert ind["spread"] == ind["detail"]["model_spread_label"]
    fams = {c["family"] for c in cle["contracts"]}
    assert "player_points" not in fams and fams <= set(adapters.load("NBA").FAMILIES)
    assert cle["period_projections"]["1H"]["home_win_prob"] > cle["period_projections"]["1H"]["away_win_prob"]


def test_nhl_adapter_uses_primary_model_not_shadow():
    summary, gs, _ = run("NHL", NHL_NOW)
    assert summary["status"] == "ok" and len(gs) == 2
    for g in gs:
        assert g["model_version"] == "DATA_ONLY_V1" and g["source_class"] == OPERATING
        assert "projected_margin_home: exp_home_goals - exp_away_goals" in g["derived"]
        assert g["period_projections"] is None
    vgk = game(gs, "2026020342")
    assert vgk["win_probability"] == {"home": 0.528, "away": 0.472} and vgk["projected_total"] == 5.94


def test_nfl_adapter_model_view_and_bucket_a_only():
    summary, gs, _ = run("NFL")
    hou = game(gs, "2026_11_IND_HOU")
    assert hou["spread"] == "HOU -12.0" and hou["home_spread"] == -12.0 and hou["projected_total"] == 44.5
    assert hou["win_probability"] == {"home": 0.864, "away": 0.136} and hou["team_totals"] == {"home": 28.2, "away": 16.2}
    assert hou["model_version"] == "shadow-0.4.0" and all(c["period"] == "FULL" for c in hou["contracts"])
    assert hou["period_projections"] is None


def test_cbb_adapter_incumbent_only_newest_run(tmp_path):
    root = tmp_path / "fx"
    shutil.copytree(FIX, root)
    base = root / "cbb/prod/projections/2027/2026-11-19/G401918959"
    newest = next(base.iterdir())
    older = json.loads(newest.read_text())
    older["projection"]["margin"] = 99.0
    (base / "2026-11-17T000000.000000Z.json").write_text(json.dumps(older))
    summary, gs, _ = run("CBB", root=root)
    assert len(gs) == 1
    g = gs[0]
    assert g["model_version"] == "pure-0.2.0" and g["projected_margin_home"] == -2.7  # newest run, not 99
    assert g["home"] == {"name": "Murray State Racers", "abbr": None} and g["spread"] == "NC State Wolfpack -2.7"
    assert g["win_probability"] == {"home": 0.4, "away": 0.6} and g["contract_count"] == 0


def test_cbb_record_not_marked_incumbent_is_skipped(tmp_path):
    root = tmp_path / "fx"
    shutil.copytree(FIX, root)
    f = next((root / "cbb/prod/projections/2027/2026-11-19/G401918959").iterdir())
    r = json.loads(f.read_text())
    r["prospective"]["role"] = "challenger"
    f.write_text(json.dumps(r))
    _, gs, _ = run("CBB", root=root)
    assert gs == []


def test_cfb_is_unavailable_and_research_is_labelled():
    summary, gs, rs = run("CFB")
    assert summary["status"] == "unavailable" and gs == [] and rs
    for r in rs:
        assert r["source_class"] == RESEARCH and r["source_declaration"]["model.authority"] == "research_only"
        assert "spread" not in r and "win_probability" not in r
        assert parse_ts(r["start_time"]) > NOW


def test_mlb_offseason():
    summary, gs, _ = run("MLB")
    assert summary["status"] == "offseason" and gs == []


def test_production_adapters_never_read_research_branches():
    research_branches = {"projection-data", "shadow-data"}
    for sport in adapters.SPORTS:
        for key, (_, branch) in adapters.load(sport).SOURCES.items():
            if key != "research":
                assert branch not in research_branches, (sport, key, branch)


# ---- staleness -------------------------------------------------------------------------------
def test_staleness_flags_and_status():
    # NFL packet built 2026-11-17T06:22Z, limit 48h; its games are 2026-11-20 .. 2026-11-24
    summary, gs, _ = run("NFL", parse_ts("2026-11-19T12:00:00Z"))
    assert summary["status"] == "stale" and gs and all(g["stale"] for g in gs)
    assert all(g["age_hours_at_build"] > 48 for g in gs) and summary["stale_after_hours"] == 48
    summary, gs, _ = run("NFL", NOW)
    assert summary["status"] == "ok" and gs and not any(g["stale"] for g in gs)
    summary, gs, _ = run("NBA", NOW + timedelta(hours=20))  # every NBA game has started
    assert gs == [] and "no upcoming game" in summary["reason"]


def test_started_games_are_dropped():
    _, gs, _ = run("NHL", NOW)
    assert gs == []


# ---- assembled index: schema, labelling, size -----------------------------------------------
@pytest.fixture(scope="module")
def built():
    results = {s: run(s, NHL_NOW if s == "NHL" else NOW) for s in adapters.SPORTS}
    return build.assemble(results, NOW)


def test_index_schema(built):
    index, per_sport = built
    assert index["schema_version"] == SCHEMA_VERSION and index["generated_at"] == "2026-11-18T19:00:00Z"
    assert set(index["sports"]) == set(adapters.SPORTS)
    for s in index["sports"].values():
        assert s["status"] in SPORT_STATUSES
    for g in index["games"]:
        assert g["source_class"] in (PRODUCTION, OPERATING) and "source_declaration" in g
        assert "contracts" not in g and "detail" not in g and "source" not in g
        assert {"projected_at", "age_hours_at_build", "stale", "source_updated_at"} <= set(g)
    for doc in per_sport.values():
        for g in doc["games"]:
            assert validate_game(g) == []


def test_research_never_in_production_games(built):
    index, _ = built
    assert all(g["sport"] != "CFB" for g in index["games"])
    assert index["research"] and all(r["source_class"] == RESEARCH for r in index["research"])


def test_size_budget(built, monkeypatch):
    index, _ = built
    assert build.size(index) < build.INDEX_BUDGET
    results = {"NBA": run("NBA"), "NFL": run("NFL"), "CFB": run("CFB")}
    monkeypatch.setattr(build, "INDEX_BUDGET", build.size(build.assemble(results, NOW)[0]) - 1)
    small, _ = build.assemble(results, NOW)
    assert small["research"] == [] and small["games"]
    full = build.assemble(results, NOW)[0]
    monkeypatch.setattr(build, "INDEX_BUDGET", build.size(full) - build.size(full["research"]) - 1)
    trimmed, _ = build.assemble(results, NOW)
    assert trimmed["games"] and "games_note" in trimmed
    assert all(g["start_time"] <= "2026-11-20T07:00:00Z" for g in trimmed["games"])
    monkeypatch.setattr(build, "INDEX_BUDGET", 1000)
    with pytest.raises(ValueError):
        build.assemble(results, NOW)


def test_committed_feed_is_valid_and_under_budget():
    p = ROOT / "feed" / "v1" / "index.json"
    if not p.exists():
        pytest.skip("feed not built")
    assert p.stat().st_size < build.INDEX_BUDGET
    index = json.loads(p.read_text())
    assert index["schema_version"] == SCHEMA_VERSION
    assert all(g["source_class"] in (PRODUCTION, OPERATING) for g in index["games"])
    assert all(g["source_class"] == classify(g["source_declaration"]) for g in index["games"])
    assert index["max_age_note"] and index["stale_after_hours"]


# ---- consumer ----------------------------------------------------------------------------
def test_say_sentence_and_research_refusal(built, tmp_path, capsys, monkeypatch):
    index, _ = built
    p = tmp_path / "index.json"
    p.write_text(json.dumps(index))
    monkeypatch.setattr(say, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    assert say.main(["Cavaliers", "--index", str(p)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("SIFT's operating (not production-approved) NBA model projects Cleveland Cavaliers -13.4 vs "
                          "Memphis Grizzlies, total 235.9, with an 80% win probability.")
    assert "2026-11-18T18:14:13Z" in out and "nba-sim-0.1.0" in out and "All families are RESEARCH" in out
    assert "STALE" not in out and "already started" not in out
    assert say.main(["Grizzlies", "--index", str(p)]) == 0
    assert "Memphis Grizzlies +13.4 at Cleveland Cavaliers" in capsys.readouterr().out
    cfb_team = index["research"][0]["home"]["name"]
    assert say.main([cfb_team, "--index", str(p), "--sport", "CFB"]) == 2
    out = capsys.readouterr().out
    assert "NOT a SIFT forecast" in out and "pf-" not in out.split("(")[0]
    assert say.main([cfb_team, "--index", str(p), "--sport", "CFB", "--research"]) == 3
    out = capsys.readouterr().out
    assert out.startswith("RESEARCH ONLY - not a SIFT production or operating forecast") and "SIFT projects" not in out



# ---- strict source labelling -----------------------------------------------------------------
@pytest.mark.parametrize("decl,cls", [
    (None, OPERATING), ({}, OPERATING), ({"authority": None}, OPERATING),
    ({"authority": "PRODUCTION"}, PRODUCTION), ({"status": "approved_production"}, PRODUCTION),
    ({"authority": "PRODUCTION", "model": "shadow-1"}, OPERATING),
    ({"authority": "NOT PRODUCTION"}, OPERATING), ({"authority": "RESEARCH_ONLY"}, OPERATING),
    ({"real_money_status": "NOT VALIDATED -- this packet recommends nothing and authorises nothing"}, OPERATING),
    ({"authority": "incumbent"}, OPERATING),
])
def test_classify_defaults_to_weaker_class(decl, cls):
    assert classify(decl) == cls


def test_every_sport_labelled_from_its_own_declaration():
    expect = {"NBA": "authority_note", "NHL": "authority", "CBB": "model.research_state", "NFL": "real_money_status"}
    for sport, key in expect.items():
        summary, gs, _ = run(sport, NHL_NOW if sport == "NHL" else NOW)
        assert summary["source_class"] == OPERATING and key in summary["source_declaration"]
        for g in gs:
            assert g["source_class"] == OPERATING and g["source_declaration"][key] is not None
    _, gs, _ = run("NFL")
    assert gs[0]["source_declaration"]["model_view.model_version"] == "shadow-0.4.0"
    assert "behind it on game outcomes" in gs[0]["source_declaration"]["model_view.caveat"]
    summary, gs, rs = run("CFB")
    assert summary["source_class"] == RESEARCH and summary["source_declaration"] == {"contains_model_projections": False}
    assert gs == [] and all(r["source_class"] == RESEARCH for r in rs)


def test_production_declaration_is_phrased_as_sift_projects(built, tmp_path, capsys, monkeypatch):
    index, _ = built
    index = json.loads(json.dumps(index))
    g = next(g for g in index["games"] if g["sport"] == "NBA")
    g["source_declaration"], g["source_class"] = {"authority": "PRODUCTION"}, PRODUCTION
    p = tmp_path / "index.json"
    p.write_text(json.dumps(index))
    monkeypatch.setattr(say, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    assert say.main([g["home"]["abbr"], "--index", str(p), "--sport", "NBA"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("SIFT projects ") and "The source declares" not in out


def test_validate_rejects_optimistic_label():
    _, gs, _ = run("NFL")
    g = dict(gs[0], source_class=PRODUCTION)
    assert "source_class does not follow from source_declaration" in validate_game(g)
    assert "not allowed" in validate_game(dict(gs[0], source_class=RESEARCH))[0]
    assert set(SOURCE_CLASSES) == {PRODUCTION, OPERATING, RESEARCH}


# ---- freshness against the current time -----------------------------------------------------
def test_say_warns_stale_and_started_against_now(built, tmp_path, capsys, monkeypatch):
    index, _ = built
    p = tmp_path / "index.json"
    p.write_text(json.dumps(index))
    later = NOW + timedelta(hours=13)  # NBA limit 12h; built 19:00Z, forecast 18:14Z
    monkeypatch.setattr(say, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: later)}))
    assert say.main(["Cavaliers", "--index", str(p)]) == 0
    out = capsys.readouterr().out
    assert "STALE: forecast is 13.8h old now (limit 12h)" in out
    assert "already started" in out and "the feed itself was generated 13.0h ago" in out
    nba = next(g for g in index["games"] if g["sport"] == "NBA")
    assert nba["age_hours_at_build"] == 0.8 and nba["stale"] is False and nba["source_updated_at"]
