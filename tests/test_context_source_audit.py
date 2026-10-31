"""Adversarial point-in-time and exact ticker settlement QA."""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import unittest
from alpha_engine.context_source_audit import (
    audit, capture_at, check_manifest, read_source, select_schedule_asof,
    settlement_candidate, source_profile,
)

class ContextSourceAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=json.loads(Path("research/context_join_pins.json").read_text())

    def test_all_sources_pinned_and_budgeted(self):
        rows=check_manifest(self.manifest)
        self.assertEqual(len(rows),6)
        self.assertEqual({x["sport"] for x in rows},{"NBA","NHL"})
        self.assertEqual(sum(x["bytes"] for x in rows),59032)

    def test_tampered_commit_or_unbounded_download_rejected(self):
        bad=copy.deepcopy(self.manifest)
        bad["sources"][0]["commit"]="main"
        with self.assertRaises(ValueError):check_manifest(bad)
        bad=copy.deepcopy(self.manifest)
        bad["sources"][0]["bytes"]=99999999
        with self.assertRaises(ValueError):check_manifest(bad)

    def test_future_schedule_cannot_leak_into_tape_base(self):
        rows=[{"kind":"schedule","captured_at":"2026-10-24T23:15:57Z","path":"old"},
              {"kind":"schedule","captured_at":"2026-10-25T00:18:44Z","path":"future"}]
        self.assertEqual(select_schedule_asof(rows,"2026-10-25T00:02:24Z")["path"],"old")
        self.assertIsNone(select_schedule_asof(rows,"2026-10-24T22:00:00Z"))
        self.assertEqual(select_schedule_asof(rows,"2026-10-25T00:20:00Z")["path"],"future")

    def test_no_inferred_settlement_or_ambiguous_ticker(self):
        self.assertEqual(settlement_candidate({"ticker":"KXGAME-A","won":True})[0],None)
        self.assertEqual(settlement_candidate({"ticker":"KXGAME-A","result":"VOID"})[0],None)
        self.assertEqual(settlement_candidate({"ticker":"KXGAME-A","result":"YES"})[0],("KXGAME-A","YES"))
        self.assertEqual(settlement_candidate({"ticker":"KXGAME-A","settlement":{"result":"NO"}})[0],("KXGAME-A","NO"))

    def test_source_gzip_budget_and_blob_hash(self):
        sample=self.manifest["sources"][0]
        with self.assertRaises(ValueError):
            read_source(sample,1000,downloader=lambda _:b"corrupt")
        raw=gzip.compress(b'{"game_id":"123"}\n',mtime=0)
        fake={**sample,"bytes":len(raw),"sha":hashlib.sha1(
            b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()}
        rows,_=read_source(fake,1000,downloader=lambda _:raw)
        self.assertEqual(rows,[{"game_id":"123"}])
        with self.assertRaises(ValueError):
            read_source(fake,2,downloader=lambda _:raw)

    def test_source_profiles_do_not_emit_private_values(self):
        profile=source_profile([{"event_id":"SENSITIVE", "game":{"start":"SENSITIVE"}}])
        self.assertEqual(profile["top_level_fields"],["event_id","game"])
        self.assertEqual(profile["nested_fields"],["game.start"])
        self.assertNotIn("SENSITIVE",str(profile))

if __name__=="__main__": unittest.main()
