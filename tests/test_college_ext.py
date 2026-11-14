"""Phase 8 guards: college/soccer extension builders (RESEARCH_ONLY)."""
import json
import re

import pandas as pd

from alpha_engine.features import cbb_ext, cfb_ext, college_collect as CC, soccer_of_ext as SO
from alpha_engine.input_research.data_foundation import verified_coverage as VC


def test_collector_never_loads_market_columns():
    for cols in list(CC.CBB_KEEP.values()) + [CC.CFB_PLAY_KEEP, CC.CFB_SCHED_KEEP, cfb_ext.PL_COLS]:
        assert not set(cols) & set(CC.FORBIDDEN), set(cols) & set(CC.FORBIDDEN)
    for bad in CC.FORBIDDEN:
        try: CC.assert_no_market([bad])
        except ValueError: continue
        raise AssertionError(bad)
    assert not any(re.search(r"spread|over_under|wp_|wpa|elo", c, re.I) for c in cfb_ext.PL_COLS)


def test_new_builders_declare_what_is_missing_so_none_can_be_full():
    for mod in (cbb_ext, cfb_ext, SO):
        for s in mod.specs():
            assert s.level == "PARTIAL" and s.missing, s.catalog_id


def test_openfootball_parser_handles_both_line_formats(tmp_path):
    d = tmp_path / "england" / "2023-24"; d.mkdir(parents=True)
    (d / "1-premierleague.txt").write_text("= EPL 2023/24\n\n▪ Matchday 1\nFri Aug 11\n  20:00  Burnley FC               0-3 (0-2)  Manchester City FC\n"
                                           "Sat Jan 13 2024\n    15:00  Arsenal FC    v Fulham FC      2-1 (1-0)\n  (Some Scorer 12')\n")
    old = SO.REPOS; SO.REPOS = {"england": ["1-premierleague.txt"]}
    try: m = SO.load_raw(tmp_path)["matches"]
    finally: SO.REPOS = old
    assert len(m) == 2 and list(m.hg) == [0, 2] and list(m.ag) == [3, 1]
    assert [str(x.date()) for x in m.game_date] == ["2023-08-11", "2024-01-13"]


def test_soccer_rho_uses_only_earlier_matches():
    rng = __import__("numpy").random.default_rng(0)
    rows = [(i, "L/1", "2000-01", pd.Timestamp("2000-08-01") + pd.Timedelta(days=i // 5), f"T{i % 10}", f"T{(i * 3 + 1) % 10}", int(rng.poisson(1.4)), int(rng.poisson(1.1))) for i in range(1200)]
    m = pd.DataFrame(rows, columns=["game_id", "league", "season", "game_date", "home", "away", "hg", "ag"])
    base = SO.compute({"matches": m})["team"]
    m2 = m.copy(); late = m2.game_date >= m2.game_date.quantile(0.8); m2.loc[late, ["hg", "ag"]] = m2.loc[late, ["ag", "hg"]].to_numpy()
    new = SO.compute({"matches": m2})["team"]; early = base.date < m.game_date.quantile(0.8)
    cols = [c for c in base if c.endswith("_pre")]
    pd.testing.assert_frame_equal(base.loc[early, cols].reset_index(drop=True), new.loc[early, cols].reset_index(drop=True))
    assert base.dc_rho_pre.notna().any()


def test_matrix_records_14_college_partials_and_soccer_partial_never_full():
    V = {r["id"]: r for r in json.loads((VC.DF / "verified_coverage.json").read_text())["rows"]}
    ids = [s.catalog_id for mod in (cbb_ext, cfb_ext, SO) for s in mod.specs()]
    assert len(ids) == 15
    for i in ids: assert V[i]["verified_status"] == "VERIFIED_PARTIAL", i
