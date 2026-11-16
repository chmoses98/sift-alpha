"""kalshi_official snapshot / restore: pack only verified folders, detect any change, restore into empty only."""
import json
from pathlib import Path

import pytest

from alpha_engine.game_completeness import kalshi_official as ko


def make(root, series=("KXA", "KXB")):
    def fake(s, out, max_pages=0, pause=0, **kw):
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / f"{s}.jsonl").write_text(
            json.dumps({"ticker": s + "-1", "result": "yes", "close_time": "2026-10-01T00:00:00Z"}) + "\n")
        (Path(out) / f"{s}.rules.json").write_text("{}")
        return {"series": s, "contracts": 1, "pages": 1, "truncated": False}
    ko.fetch_scope({"sports": {"NBA": list(series)}}, root, fetch=fake)
    return root


def test_snapshot_round_trip_is_deterministic(tmp_path):
    live, hist = make(tmp_path / "live"), make(tmp_path / "hist", ("KXA",))
    a = ko.snapshot({"live": live, "historical": hist}, tmp_path / "s1.tar.gz")
    b = ko.snapshot({"live": live, "historical": hist}, tmp_path / "s2.tar.gz")
    assert a["sha256"] == b["sha256"] and a["roots"]["live"]["rows"] == 2 and a["roots"]["historical"]["series"] == 1
    r = ko.restore(tmp_path / "s1.tar.gz", tmp_path / "back")
    assert r["ok"] and r["roots"]["live"] == {"series": 2, "rows": 2, "problems": [], "matches_sidecar": True}
    assert (tmp_path / "back" / "live" / "NBA" / "KXA.rules.json").exists()      # rules text and markers travel too
    assert (tmp_path / "back" / "live" / "NBA" / "KXA.done").exists()


def test_snapshot_refuses_unverified_folder(tmp_path):
    live = make(tmp_path / "live")
    (live / "NBA" / "KXB.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="read-back failed"):
        ko.snapshot({"live": live}, tmp_path / "s.tar.gz")


def test_restore_detects_corruption_and_refuses_non_empty_target(tmp_path):
    ko.snapshot({"live": make(tmp_path / "live")}, tmp_path / "s.tar.gz")
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "x").write_text("1")
    with pytest.raises(ValueError, match="empty"):
        ko.restore(tmp_path / "s.tar.gz", tmp_path / "busy")
    data = bytearray((tmp_path / "s.tar.gz").read_bytes())
    data[len(data) // 2] ^= 0xFF
    (tmp_path / "s.tar.gz").write_bytes(bytes(data))
    with pytest.raises(ValueError, match="sha256"):
        ko.restore(tmp_path / "s.tar.gz", tmp_path / "back")
