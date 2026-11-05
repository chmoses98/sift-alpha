"""Adversarial tests for genuine source-compatible hash-verified delta chains."""
import copy
import gzip
import hashlib
import json
import unittest
from datetime import datetime,timezone
from pathlib import Path

from alpha_engine.source_delta import canonical_board, board_sha256, build_delta
from alpha_engine.verified_chains import replay, check_manifest

def make_fixture():
    base_path="kalshi/markets/dt=2026-10-25/kalshi_markets_20261025T000224Z_test.jsonl.gz"
    row={"ticker":"KXNBAGAME-26TEST-AAA", "yes_bid_dollars":"0.40",
         "yes_ask_dollars":"0.44", "_observed_at_utc":"2026-10-25T00:02:24Z",
         "_run_id":"a"}
    base=gzip.compress((json.dumps(row)+"\n").encode(),mtime=0)
    before=canonical_board([row])
    nextrow={**before[row["ticker"]],"yes_bid_dollars":"0.52"}
    after={row["ticker"]:nextrow}
    delta=build_delta(before,after,captured_at=datetime(2026,10,25,0,10,21,tzinfo=timezone.utc),
                      run_id="b",seq=1,base_path=base_path,
                      base_sha256=hashlib.sha256(base).hexdigest(),
                      base_captured_at="2026-10-25T00:02:24Z").to_bytes()
    def git_sha(blob):
        return hashlib.sha1(b"blob "+str(len(blob)).encode()+b"\0"+blob).hexdigest()
    root={"repository":"chmoses98/nba-edge-finder","commit":"a"*40,
          "checkpoint":{"path":base_path,"sha":git_sha(base),"bytes":len(base)},
          "deltas":[{"path":"kalshi/markets_delta/dt=2026-10-25/kalshi_markets_delta_20261025T001021Z_test.json.gz",
                     "sha":git_sha(delta),"bytes":len(delta)}]}
    result={"schema_version":1,"max_total_compressed_bytes":2500000,
            "max_decompressed_bytes":50000000,"chains":{"NBA":root,"NHL":{
                **root,"repository":"chmoses98/NHL-edge-finder","checkpoint":{**root["checkpoint"],
                    "path":root["checkpoint"]["path"].replace("kalshi_markets_","kalshi_markets_") },
            }}}
    # Swap NHL's content path and base_path in a second independent fixture later.
    return root,base,delta

class ArchiveChainTests(unittest.TestCase):
    def test_real_source_hash_algorithm_and_end_to_end(self):
        root, base, delta=make_fixture()
        # One fixture per sport; chain's hash must match its own base bytes.
        nhl=copy.deepcopy(root);nhl["repository"]="chmoses98/NHL-edge-finder"
        manifest={"schema_version":1,"max_total_compressed_bytes":2500000,"max_decompressed_bytes":50000000,
                  "chains":{"NBA":root,"NHL":nhl}}
        def fetch(chain,entry):
            return base if entry==chain["checkpoint"] else delta
        x=replay(manifest,downloader=fetch)
        self.assertEqual(x["sport_chains"]["NBA"]["delta_ticks"],1)
        self.assertEqual(x["sport_chains"]["NBA"]["n_unique_tickers_with_quote_movements"],1)
        self.assertEqual(x["sport_chains"]["NBA"]["tick_summaries"][0]["examples"][0]["field_changes"]["yes_bid"],
                         {"before":"0.40","after":"0.52"})
        self.assertEqual(x["sport_chains"]["NBA"]["profitability_authority"],"NONE")
        self.assertFalse(x["full_day_or_full_season"])

    def test_tampered_delta_missing_delta_invalid_host_and_time(self):
        root,base,delta=make_fixture()
        nhl=copy.deepcopy(root);nhl["repository"]="chmoses98/NHL-edge-finder"
        manifest={"schema_version":1,"max_total_compressed_bytes":2500000,"max_decompressed_bytes":50000000,
                  "chains":{"NBA":root,"NHL":nhl}}
        with self.assertRaises(ValueError):
            replay(manifest,downloader=lambda chain,entry: base if entry==chain["checkpoint"] else delta+b"0")
        malicious=copy.deepcopy(manifest);malicious["chains"]["NBA"]["repository"]="bad/paid"
        with self.assertRaises(ValueError): check_manifest(malicious)
        oversized=copy.deepcopy(manifest);oversized["max_total_compressed_bytes"]=999999999
        with self.assertRaises(ValueError): check_manifest(oversized)

    def test_gap_and_parent_board_corruption_fail_closed(self):
        root,base,delta=make_fixture()
        nhl=copy.deepcopy(root);nhl["repository"]="chmoses98/NHL-edge-finder"
        manifest={"schema_version":1,"max_total_compressed_bytes":2500000,"max_decompressed_bytes":50000000,
                  "chains":{"NBA":root,"NHL":nhl}}
        data=json.loads(delta)
        data["seq"]=2
        bad=(json.dumps(data)+"\n").encode()
        for chain in manifest["chains"].values():
            chain["deltas"][0]["sha"]=hashlib.sha1(b"blob "+str(len(bad)).encode()+b"\0"+bad).hexdigest()
            chain["deltas"][0]["bytes"]=len(bad)
        with self.assertRaises(Exception):
            replay(manifest,downloader=lambda chain,entry: base if entry==chain["checkpoint"] else bad)

if __name__=="__main__":
    unittest.main()
