"""Adversarial source, scalar and time-leakage checks for Tennis settlements."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import unittest
from alpha_engine.tennis_settlement import audit,join_prior_quotes,validate_pins

def blob(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()

def fixture():
    spec=json.loads(Path("research/tennis_settlement_pins.json").read_text())
    raw={}
    for i,cap in enumerate(spec["captures"]):
        start=["2026-10-25T00:45:43Z","2026-10-25T01:45:43Z","2026-10-25T03:57:05Z"][i]
        end=["2026-10-25T00:48:00Z","2026-10-25T01:48:08Z","2026-10-25T03:59:41Z"][i]
        payout=["1.0000","0.0000","0.5000"][i]
        result=["yes","no","scalar"][i]
        manifest={"run_id":cap["run_id"],"started_at":start,"finished_at":end,
                  "incomplete":[],"client_stats":{"failures":0},"counts":{"settlements":1}}
        row={"run_id":cap["run_id"],"ticker":f"TEST-{i}","event_ticker":f"EVENT-{i}",
             "status":"finalized","result":result,"settlement_value_dollars":payout,
             "captured_at":start,"settlement_ts":"2026-10-25T00:15:00Z",
             "open_time":"2026-10-24T23:00:00Z","close_time":"2026-10-25T00:10:00Z",
             "occurrence_datetime":"2026-10-25T05:00:00Z"}
        for name,content in (("manifest",json.dumps(manifest).encode()),
                             ("settlements",gzip.compress((json.dumps(row)+"\n").encode()))):
            entry=cap[name]
            entry["bytes"]=len(content)
            entry["sha"]=blob(content)
            raw[entry["path"]]=content
    return spec,raw

def mutate(spec,raw,idx,kind,edit):
    entry=spec["captures"][idx][kind]
    data=raw[entry["path"]]
    if kind=="manifest":
        obj=json.loads(data);edit(obj);data=json.dumps(obj).encode()
    else:
        obj=json.loads(gzip.decompress(data));edit(obj)
        data=gzip.compress((json.dumps(obj)+"\n").encode())
    raw[entry["path"]]=data
    entry["bytes"]=len(data)
    entry["sha"]=blob(data)

class TennisSettlementTests(unittest.TestCase):
    def test_exact_source_scope(self):
        spec,raw=fixture()
        report,rows=audit(spec,lambda e:raw[e["path"]])
        self.assertEqual(report["n_settlement_rows"],3)
        self.assertEqual(report["exchange_result_counts"],{"no":1,"scalar":1,"yes":1})
        self.assertEqual(report["n_occurrence_timestamps_after_reported_settlement"],3)
        self.assertTrue(all(not r["actual_match_start_verified"] for r in rows))
        self.assertTrue(all(not r["independently_authenticated_exchange_result"] for r in rows))
        self.assertEqual(report["profitability_authority"],"NONE")

    def test_source_tamper_fails_closed(self):
        spec,raw=fixture()
        path=spec["captures"][0]["settlements"]["path"]
        raw[path]+=b"x"
        with self.assertRaises(ValueError):audit(spec,lambda e:raw[e["path"]])

    def test_unknown_or_wrong_scalar_payout_rejected(self):
        for change in (lambda x:x.update(result="yes"),
                       lambda x:x.update(settlement_value_dollars="0.0"),
                       lambda x:x.update(settlement_value_dollars="NaN")):
            spec,raw=fixture()
            mutate(spec,raw,2,"settlements",change)
            with self.assertRaises(ValueError):audit(spec,lambda e:raw[e["path"]])

    def test_future_settlement_rejected(self):
        spec,raw=fixture()
        mutate(spec,raw,1,"settlements",lambda x:x.update(settlement_ts="2026-10-25T07:00:00Z"))
        with self.assertRaises(ValueError):audit(spec,lambda e:raw[e["path"]])

    def test_duplicate_across_captures_rejected(self):
        spec,raw=fixture()
        mutate(spec,raw,1,"settlements",lambda x:x.update(ticker="TEST-0"))
        with self.assertRaises(ValueError):audit(spec,lambda e:raw[e["path"]])

    def test_manifest_count_or_failure_rejected(self):
        for change in (lambda x:x["counts"].update(settlements=2),
                       lambda x:x["client_stats"].update(failures=1)):
            spec,raw=fixture()
            mutate(spec,raw,0,"manifest",change)
            with self.assertRaises(ValueError):audit(spec,lambda e:raw[e["path"]])

    def test_source_budget_and_path_guard(self):
        spec,_=fixture()
        spec["captures"][0]["settlements"]["path"]="../bad.gz"
        with self.assertRaises(ValueError):validate_pins(spec)
        spec,_=fixture()
        spec["captures"][0]["settlements"]["bytes"]=1000000
        with self.assertRaises(ValueError):validate_pins(spec)

    def test_quote_after_settlement_not_treated_as_prior(self):
        spec,raw=fixture()
        _,settlements=audit(spec,lambda e:raw[e["path"]])
        quotes=[{"sport":"TENNIS","ticker":"TEST-0","observed_at_utc":"2026-10-25T00:14:00Z"},
                {"sport":"TENNIS","ticker":"TEST-0","observed_at_utc":"2026-10-25T00:16:00Z"},
                {"sport":"TENNIS","ticker":"TEST-1","observed_at_utc":"2026-10-25T00:16:00Z"}]
        j=join_prior_quotes(settlements,quotes)
        self.assertEqual(j["n_settled_tickers_with_quote_observed_before_settlement"],1)
        self.assertEqual(j["n_quote_observations_after_settlement_excluded"],2)
        self.assertEqual(j["pregame_eligibility"],"NOT_VERIFIED_ACTUAL_MATCH_START")

if __name__=="__main__":unittest.main()
