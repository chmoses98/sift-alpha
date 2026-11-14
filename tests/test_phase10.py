"""Phase 10 guards (RESEARCH_ONLY): new deterministic builders, evidence-backed promotion, collector-audit artefacts (proposals only)."""
import json
from pathlib import Path

import pandas as pd

from alpha_engine.features import soccer_of_ext2 as SO2, tennis_ext2 as T2

ROOT = Path(__file__).resolve().parents[1]
DF = ROOT / "research/input_research/data_foundation"


def _vc():
    return {r["key"]: r for r in json.loads((DF / "verified_coverage.json").read_text())["rows"]}


def test_phase10_statuses_and_counts():
    vc = _vc()
    assert vc["TENNIS:ten.tiebreak_base_rate_by_event"]["verified_status"] == "VERIFIED_FULL"
    assert vc["SOCCER:soc.points_gap_state"]["verified_status"] == "VERIFIED_PARTIAL" and vc["SOCCER:soc.current_win_run_state"]["verified_status"] == "VERIFIED_PARTIAL"
    c = pd.Series([r["verified_status"] for r in vc.values()]).value_counts()
    assert (c["VERIFIED_FULL"], c["VERIFIED_PARTIAL"], c["VERIFIED_PROXY"]) == (58, 209, 20)      # Phase 15 adds 29 NBA/NHL PARTIAL and 1 PROXY (nba.lineup_adj_rating); Phase 11 adds ten.games_per_set_distribution and ten.hold_gap_expected_margin (PARTIAL); Phase 12 adds ten.tiebreak_sweep_joint_table


def test_tennis_tiebreak_has_round_best_of_split_and_no_declared_gap():
    s = next(x for x in T2.specs() if x.catalog_id == "ten.tiebreak_base_rate_by_event")
    assert s.level == "FULL" and not s.missing and {"tbe_tb_rate_rb_pre", "tbe_ss_rate_rb_pre", "tbe_n_eff_rb_pre"} <= set(s.columns)


def _toy():
    rows = []
    d = pd.Timestamp("2020-01-01")
    teams = ["A", "B"]
    for i in range(6):
        h, a = (teams[i % 2], teams[(i + 1) % 2]); rows.append(("e/1", "2019-20", d + pd.Timedelta(days=7 * i), h, a, 2 if i % 3 else 0, 1))
    m = pd.DataFrame(rows, columns=["league", "season", "game_date", "home", "away", "hg", "ag"]); m["game_id"] = range(len(m))
    return {"matches": m}


def test_soccer_table_state_uses_only_strictly_earlier_dates_and_win_run_resets():
    t = SO2.compute(_toy())["team"]
    first = t[t.game_id == 0]
    assert (first[SO2.PGS].fillna(0) == 0).all().all()                       # nothing before the first date
    g1 = t[(t.game_id == 1)]; assert set(g1.pgs_pts_pre) == {0.0, 3.0} and g1.pgs_pts_gap_pre.abs().eq(3).all()
    assert set(SO2.PGS).isdisjoint({"pgs_left_pre", "pgs_played_pre"})      # fixture-count columns are not published (replay gates)


def test_collector_audits_record_verdicts_and_apply_nothing():
    a = json.loads((DF / "collector_audit/nba_nhl.json").read_text()); b = json.loads((DF / "collector_audit/nfl_college.json").read_text())
    ok = {"READY_FOR_PROSPECTIVE_CAPTURE", "READY_WITH_GAPS", "NOT_READY"}
    for k in ("nba_starters", "nba_injuries", "nhl_goalies", "nhl_injuries"): assert a[k]["verdict"] in ok
    for k in ("nfl_injuries", "cfb_qb_status", "cbb_availability"): assert b[k]["verdict"] in ok
    assert b["cbb_availability"]["verdict"] == "NOT_READY"
    wf = (ROOT / ".github/workflows")
    assert not any("collector_audit" in f.read_text() for f in wf.glob("*.yml"))
