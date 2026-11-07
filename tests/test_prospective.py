"""Tests for the autonomous prospective pipeline: capture -> ingestion -> prediction -> settlement -> evaluation, claim gate and append-only publishing."""
import http.server, json, subprocess, sys, threading
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alpha_engine.lab import prospective as PP, capture_ingest as CI, prospective_cycle as PC

KO = pd.Timestamp("2026-11-08 13:00", tz="America/New_York").tz_convert("UTC")
GAMES = pd.DataFrame({"game_id": ["g1"], "home_score": [30.0], "away_score": [20.0], "gameday": ["2026-11-08"], "gametime": ["13:00"], "away_team": ["AAA"], "home_team": ["HHH"], "season": [2026], "week": [10]})


def iso(minutes_before):
    return (KO - pd.Timedelta(minutes=minutes_before)).isoformat()


def pred(gen_hours_before, mu=45.0):
    return {"kind": "prediction", "game_id": "g1", "week": 10, "kickoff_utc": KO.isoformat(), "generated_utc": (KO - pd.Timedelta(hours=gen_hours_before)).isoformat(), "dist": "normal", "mu": mu, "sigma": 13.0}


def obs(minutes_before, complete=True):
    return {"kind": "series_observation", "series": "KXNFLTOTAL", "observed_at": iso(minutes_before), "complete": complete, "run_id": f"r{minutes_before}"}


def quote(minutes_before, bid=0.40, ask=0.44, ticker="KXNFLTOTAL-26NOV08AAAHHH-48", floor=47.5, source=PP.SOURCE_CAPTURE):
    return {"kind": "quote", "source": source, "series": "KXNFLTOTAL", "observed_at": iso(minutes_before), "ticker": ticker, "game_id": "g1", "floor": floor, "bid": bid, "ask": ask, "status": "active", "result": ""}


def status(audit, h):
    return [a["status"] for a in audit if a["horizon"] == h]


# ---------------------------------------------------------------- decision engine
def test_eligible_with_carry_forward_and_latest_prediction():
    # the quote row was written 400 min before kickoff (changed then); the T-6h (=360) decision is covered by a complete observation 358 min before kickoff
    frame, audit = PP.audit_and_frame([pred(200, 40.0), pred(24, 50.0), pred(2, 99.0)], [quote(400)], [obs(380), obs(365)], GAMES, KO)
    assert status(audit, "T-6h") == ["ELIGIBLE"]
    r = frame[frame.horizon == "T-6h"].iloc[0]
    assert abs(r["age"] - 5) < 1e-9                                                    # freshness = age of the OBSERVATION (365 -> 360)
    assert abs(r["model_p"] - float(PP.dists.prob_gt("normal", 50.0, 13.0, 47.5))) < 1e-12   # the 2h-before prediction is after the decision and ignored
    assert r["outcome"] == 1.0                                                          # 50 > 47.5


def test_reason_codes():
    q, o = [quote(400)], [obs(365)]
    assert status(PP.audit_and_frame([pred(200)], q, o, GAMES, KO - pd.Timedelta(hours=30))[1], "T-6h") == ["NOT_YET_DUE"]
    assert status(PP.audit_and_frame([pred(5)], q, o, GAMES, KO)[1], "T-6h") == ["NO_PREDICTION_BEFORE_DECISION"]
    assert status(PP.audit_and_frame([pred(30)], q, [obs(420)], GAMES, KO)[1], "T-6h") == ["NO_COMPLETE_OBSERVATION_IN_WINDOW"]     # last complete observation 60 min old
    assert status(PP.audit_and_frame([pred(30)], q, [obs(365, complete=False)], GAMES, KO)[1], "T-6h") == ["NO_COMPLETE_OBSERVATION_IN_WINDOW"]  # partial run never counts
    assert status(PP.audit_and_frame([pred(30)], [], o, GAMES, KO)[1], "T-6h") == ["NO_QUOTE_ROW"]
    unsettled = GAMES.assign(home_score=np.nan, away_score=np.nan)
    assert status(PP.audit_and_frame([pred(30)], q, o, unsettled, KO)[1], "T-6h") == ["UNSETTLED"]


def test_self_capture_quotes_are_never_decision_inputs_and_closed_markets_excluded():
    assert status(PP.audit_and_frame([pred(30)], [quote(400, source=PP.SOURCE_SELF)], [obs(365)], GAMES, KO)[1], "T-6h") == ["NO_QUOTE_ROW"]
    closed = dict(quote(400), status="finalized", result="yes")
    assert status(PP.audit_and_frame([pred(30)], [closed], [obs(365)], GAMES, KO)[1], "T-6h") == ["NO_QUOTE_ROW"]


# ---------------------------------------------------------------- claim gate
def _frame(n_games, edge, rng, bias=0.0):
    rows = []
    for i in range(n_games):
        true_p = rng.uniform(0.3, 0.7)
        y = float(rng.uniform() < true_p)
        mid = float(np.clip(true_p + bias, 0.05, 0.95))
        model_p = float(np.clip(true_p + edge * rng.standard_normal() * 0 + edge, 0.02, 0.98))
        rows.append({"game_id": f"g{i}", "week": 10, "family": "total", "ticker": f"t{i}", "horizon": "T-6h", "floor": 45.5, "bid": mid - 0.02, "ask": mid + 0.02, "age": 3.0, "outcome": y, "model_p": model_p})
    return pd.DataFrame(rows)


def test_gate_insufficient_n_and_fail_closed_flags():
    rng = np.random.default_rng(1)
    assert PP.claim_gate(_frame(30, 0.1, rng), True)["status"] == "INSUFFICIENT_N"
    assert PP.claim_gate(pd.DataFrame(), True)["status"] == "INSUFFICIENT_N"
    big = _frame(130, 0.0, rng)
    assert PP.claim_gate(big, chains_ok=False)["status"] in ("FAIL", "INSUFFICIENT_N")
    assert PP.claim_gate(big, True, flags=["x"])["status"] in ("FAIL", "INSUFFICIENT_N")


def test_gate_never_says_profitable_and_controls_false_positives():
    """Null world: the model has no information (its P is the market mid plus noise).  Over many simulated seasons the PASS rate must stay well under alpha."""
    rng = np.random.default_rng(7); passes = 0; sims = 120
    for _ in range(sims):
        rows = []
        for i in range(130):
            p = rng.uniform(0.3, 0.7); y = float(rng.uniform() < p); mid = p
            rows.append({"game_id": f"g{i}", "week": 10, "family": "total", "ticker": f"t{i}", "horizon": "T-6h", "floor": 45.5, "bid": mid - 0.02, "ask": mid + 0.02, "age": 3.0, "outcome": y,
                         "model_p": float(np.clip(mid + rng.normal(0, 0.05), 0.02, 0.98))})
        g = PP.claim_gate(pd.DataFrame(rows), True)
        assert "profit" not in json.dumps(g).lower().replace("not a profitability claim", "")
        passes += g["status"] == "PASS_PROVISIONAL"
    assert passes / sims <= 0.05


def test_gate_power_when_the_model_truly_knows_more():
    """A model that knows the true probability while the market is noisy should pass at the larger looks (the gate is not vacuous)."""
    rng = np.random.default_rng(3); rows = []
    for i in range(300):
        p = rng.uniform(0.2, 0.8); y = float(rng.uniform() < p); mid = float(np.clip(p + rng.normal(0, 0.12), 0.05, 0.95))
        rows.append({"game_id": f"g{i}", "week": 10, "family": "total", "ticker": f"t{i}", "horizon": "T-6h", "floor": 45.5, "bid": mid - 0.01, "ask": mid + 0.01, "age": 3.0, "outcome": y, "model_p": p})
    g = PP.claim_gate(pd.DataFrame(rows), True)
    assert g["status"] == "PASS_PROVISIONAL" and g["look"] in (60, 120, 272) and g["games_with_bets"] >= g["look"] and g["primary_after_fee_ev"]["p_holm"] < g["alpha_per_look"]


def test_gate_unit_is_the_game_not_the_contract():
    """Many correlated ladder contracts on few games must not manufacture independent samples."""
    rng = np.random.default_rng(5); rows = []
    for i in range(20):                                           # 20 games x 12 contracts = 240 rows, but only 20 independent games
        for k in range(12):
            rows.append({"game_id": f"g{i}", "week": 10, "family": "total", "ticker": f"t{i}_{k}", "horizon": "T-6h", "floor": 40.5 + k, "bid": 0.4, "ask": 0.44, "age": 3.0, "outcome": float(i % 2), "model_p": 0.6})
    g = PP.claim_gate(pd.DataFrame(rows), True)
    assert g["status"] == "INSUFFICIENT_N" and g["games_scored"] == 20


# ---------------------------------------------------------------- fail-closed fallback capture against a mock API
class _Handler(http.server.BaseHTTPRequestHandler):
    script: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        code, body = self.script.pop(0) if self.script else (500, {})
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(json.dumps(body).encode())


def _serve(script):
    h = type("H", (_Handler,), {"script": list(script)})
    srv = http.server.HTTPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/markets"


def _mk(t, bid="0.40", ask="0.44"):
    return {"ticker": t, "floor_strike": 47.5, "yes_bid_dollars": bid, "yes_ask_dollars": ask, "status": "active"}


def test_fetch_paginates_and_stamps_each_page(monkeypatch):
    srv, url = _serve([(200, {"markets": [_mk("KXNFLTOTAL-26NOV08AAAHHH-48")], "cursor": "c1"}), (200, {"markets": [_mk("KXNFLTOTAL-26NOV08AAAHHH-50")], "cursor": ""})])
    ticks = iter(pd.date_range("2026-11-08", periods=10, freq="3s", tz="UTC"))
    book = PP.fetch_totals(base=url, pause=0, clock=lambda: next(ticks)); srv.shutdown()
    assert book["n"] == 2 and len(book["pages"]) == 2 and book["pages"][0]["fetched_utc"] < book["pages"][1]["fetched_utc"]


def test_fetch_retries_429_then_succeeds_and_fails_closed():
    srv, url = _serve([(429, {"error": "too_many_requests"}), (200, {"markets": [_mk("KXNFLTOTAL-26NOV08AAAHHH-48")], "cursor": ""})])
    assert PP.fetch_totals(base=url, pause=0)["n"] == 1; srv.shutdown()
    srv, url = _serve([(200, {"markets": [_mk("a")], "cursor": "c1"}), (500, {}), (500, {}), (500, {}), (500, {})])
    with pytest.raises(PP.FetchError):                            # second page never succeeds: the first page must NOT be returned as if it were the book
        PP.fetch_totals(base=url, pause=0, tries=3)
    srv.shutdown()
    srv, url = _serve([(200, {"markets": [], "cursor": ""})])
    with pytest.raises(PP.FetchError):
        PP.fetch_totals(base=url, pause=0)
    srv.shutdown()
    srv, url = _serve([(200, {"markets": [_mk("a")], "cursor": "same"}), (200, {"markets": [_mk("b")], "cursor": "same"}), (200, {"markets": [_mk("c")], "cursor": "same"})])
    with pytest.raises(PP.FetchError):
        PP.fetch_totals(base=url, pause=0)
    srv.shutdown()


def test_capture_cli_exit_code_and_no_file_on_failure(tmp_path):
    srv, url = _serve([(500, {})] * 20)
    g = tmp_path / "games.csv"; GAMES.to_csv(g, index=False)
    code = (f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r}); import alpha_engine.lab.prospective as P; P.time.sleep = lambda s: None; "
            f"P.main(['capture','--games',{str(g)!r},'--dir',{str(tmp_path / 'o')!r},'--api',{url!r}])")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True); srv.shutdown()
    assert r.returncode != 0
    assert not (tmp_path / "o" / "quotes.jsonl").exists() and not (tmp_path / "o" / "observations.jsonl").exists()      # no partial book is ever written
    assert json.loads((tmp_path / "o" / "capture_failures.jsonl").read_text().splitlines()[0])["kind"] == "capture_failure"


def test_self_capture_records_use_their_page_timestamps(tmp_path):
    g = pd.DataFrame({"game_id": ["2026_10_AAA_HHH"], "gameday": ["2026-11-08"], "away_team": ["AAA"], "home_team": ["HHH"], "season": [2026], "week": [10]})
    book = {"series": "KXNFLTOTAL", "pages": [{"fetched_utc": "2026-11-08T10:00:00+00:00", "markets": [_mk("KXNFLTOTAL-26NOV08AAAHHH-48")]},
                                               {"fetched_utc": "2026-11-08T10:00:05+00:00", "markets": [_mk("KXNFLTOTAL-26NOV08AAAHHH-50"), {"ticker": "KXNFLTOTAL-26NOV08AAAHHH-52", "yes_bid_dollars": None, "yes_ask_dollars": "0.1"}]}]}
    book["n"] = 3; assert PP.record_quotes(book, g, tmp_path) == 2
    rows = [json.loads(l) for l in (tmp_path / "quotes.jsonl").read_text().splitlines()]
    assert [r["observed_at"] for r in rows] == ["2026-11-08T10:00:00+00:00", "2026-11-08T10:00:05+00:00"] and all(r["source"] == PP.SOURCE_FALLBACK for r in rows)
    ob = json.loads((tmp_path / "observations.jsonl").read_text().splitlines()[0])
    assert ob["observed_at"] == "2026-11-08T10:00:05+00:00" and ob["complete"] and ob["skipped_markets"] == 1 and ob["pages"] == 2    # observed at the LAST page time
    PP._LAST.clear()                                                                                              # a new process: state is rebuilt from the ledger
    assert PP.record_quotes(book, g, tmp_path) == 0                                                              # unchanged rows are not rewritten; the observation still is
    obs2 = [json.loads(l) for l in (tmp_path / "observations.jsonl").read_text().splitlines()]
    assert len(obs2) == 2 and obs2[1]["unchanged_rows_not_rewritten"] == 2


# ---------------------------------------------------------------- ingestion of the verified collector
def _write_run(root: Path, run_id: str, observed_at: str, rows: list[dict], partial=False, complete=True, n=3):
    d = root / f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}"; d.mkdir(parents=True, exist_ok=True)
    man = {"run_id": run_id, "partial": partial, "errors": [], "trigger_source": "CONDUCTOR", "series": {"KXNFLTOTAL": {"n": n, "complete": complete, "tier": "FULL_MICROSTRUCTURE", "observed_at": observed_at, "provisional": False}}}
    (d / f"{run_id}.manifest.json").write_text(json.dumps(man))
    (d / f"{run_id}.quotes.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _row(run_id, observed_at, ticker, bid, ask, series="KXNFLTOTAL"):
    return {"run_id": run_id, "observed_at": observed_at, "ticker": ticker, "series_ticker": series, "game_id": "g1", "floor_strike": 47.5, "yes_bid_dollars": str(bid), "yes_ask_dollars": str(ask),
            "status": "active", "result": "", "changed": True, "kickoff_utc": KO.isoformat()}


def test_ingest_is_idempotent_additive_and_records_provenance(tmp_path):
    src, out = tmp_path / "md", tmp_path / "out"
    _write_run(src, "20261108T070000Z", "2026-11-08T07:00:05+00:00", [_row("20261108T070000Z", "2026-11-08T07:00:05+00:00", "T1", .4, .44), _row("x", "x", "OTHER", .1, .2, series="KXNFLGAME")])
    s1 = CI.ingest(CI.DirSource(src), out)
    assert s1["observations"] == 1 and s1["quotes"] == 1                          # only the watched series, nothing else
    s2 = CI.ingest(CI.DirSource(src), out)
    assert s2["observations"] == 0 and s2["quotes"] == 0                          # idempotent
    _write_run(src, "20261108T073000Z", "2026-11-08T07:30:05+00:00", [], partial=True)
    s3 = CI.ingest(CI.DirSource(src), out)
    assert s3["observations"] == 1
    o = CI._read(out / "observations.jsonl")
    assert o[0]["complete"] and not o[1]["complete"] and o[1]["run_partial"] and o[0]["manifest_blob"] and o[0]["quotes_blob"] and o[0]["run_id"] == "20261108T070000Z"
    assert PP.verify_chain(out / "observations.jsonl")["ok"] and PP.verify_chain(out / "quotes.jsonl")["ok"]


def test_ingest_skips_broken_runs_without_inventing_data(tmp_path):
    src, out = tmp_path / "md", tmp_path / "out"
    d = src / "2026-11-08"; d.mkdir(parents=True)
    (d / "20261108T070000Z.manifest.json").write_text("{not json")
    (d / "20261108T071000Z.manifest.json").write_text(json.dumps({"series": {"KXNFLTOTAL": {"n": 1, "complete": True, "observed_at": "2026-11-08T07:10:00+00:00"}}}))   # quotes file missing
    s = CI.ingest(CI.DirSource(src), out)
    assert s["observations"] == 0 and len(s["skipped"]) == 2


def test_capture_gaps_reports_missing_windows():
    ob = [{"series": "KXNFLTOTAL", "complete": True, "observed_at": t} for t in ("2026-11-08T07:00:00+00:00", "2026-11-08T07:15:00+00:00", "2026-11-08T09:00:00+00:00")]
    g = CI.capture_gaps(ob, "2026-11-08T07:00:00+00:00", "2026-11-08T09:10:00+00:00")
    assert g["gaps_over_limit"] == 1 and g["longest_gap_min"] == 105.0


def test_end_to_end_capture_ingest_predict_settle_evaluate(tmp_path):
    """The complete chain on a synthetic slate: collector files -> ingestion -> predictions -> decision audit -> settlement -> gate."""
    src, out = tmp_path / "md", tmp_path / "out"
    for m in (400, 380, 365):
        rid = (KO - pd.Timedelta(minutes=m)).strftime("%Y%m%dT%H%M%SZ"); at = iso(m)
        _write_run(src, rid, at, [_row(rid, at, "KXNFLTOTAL-26NOV08AAAHHH-48", .40, .44)] if m == 400 else [])
    CI.ingest(CI.DirSource(src), out)
    PP.append(out / "predictions.jsonl", pred(30, 50.0))
    preds, quotes, ob = (CI._read(out / f) for f in ("predictions.jsonl", "quotes.jsonl", "observations.jsonl"))
    frame, audit = PP.audit_and_frame(preds, quotes, ob, GAMES, KO)
    assert status(audit, "T-6h") == ["ELIGIBLE"] and len(frame[frame.horizon == "T-6h"]) == 1
    ev = PP.evaluate(frame, audit, True)
    assert ev["status"] == "OK" and ev["gate"]["status"] == "INSUFFICIENT_N" and ev["gate"]["games_scored"] == 1


# ---------------------------------------------------------------- cycle safety + append-only publishing
def test_cycle_aborts_when_frozen_model_no_longer_reproduces(tmp_path, monkeypatch):
    P = pd.DataFrame({"game_id": ["g0"], "season": [2025], "week": [1], "mu": [41.0], "sigma": [13.0], "mu0": [44.0]})
    monkeypatch.setattr(PC, "build_predictions", lambda *a, **k: (P, GAMES, "sha"))
    out = tmp_path / "out"; out.mkdir()
    (out / "FREEZE_DIGEST.json").write_text(json.dumps({"mu_digest_2014_2025": "0" * 64})); (out / "FREEZE.json").write_text(json.dumps({"frozen_utc": "2026-11-01T00:00:00+00:00"}))
    r = PC.run_cycle(tmp_path, None, out, tmp_path / "w", now=KO, download=False)
    assert r.get("aborted") and not (out / "predictions.jsonl").exists()


def test_cycle_appends_predictions_and_evaluates(tmp_path, monkeypatch):
    P = pd.DataFrame({"game_id": ["g0", "g1"], "season": [2025, 2026], "week": [1, 10], "mu": [41.0, 50.0], "sigma": [13.0, 13.0], "mu0": [44.0, 44.0]})
    monkeypatch.setattr(PC, "build_predictions", lambda *a, **k: (P, GAMES, "sha"))
    out = tmp_path / "out"; out.mkdir(); (out / "FREEZE_DIGEST.json").write_text(json.dumps({"mu_digest_2014_2025": PC.digest_mu(P)}))
    (out / "FREEZE.json").write_text(json.dumps({"frozen_utc": "2026-11-01T00:00:00+00:00"}))
    src = tmp_path / "md"; rid = (KO - pd.Timedelta(minutes=400)).strftime("%Y%m%dT%H%M%SZ"); _write_run(src, rid, iso(400), [_row(rid, iso(400), "KXNFLTOTAL-26NOV08AAAHHH-48", .4, .44)])
    r = PC.run_cycle(tmp_path, None, out, tmp_path / "w", now=KO - pd.Timedelta(hours=40), download=False, md_src=CI.DirSource(src))
    assert r["steps"]["frozen_reproduction"]["ok"] and r["steps"]["predictions_appended"] == 1 and r["counts"]["observations"] == 1
    r2 = PC.run_cycle(tmp_path, None, out, tmp_path / "w", now=KO - pd.Timedelta(hours=39), download=False, md_src=CI.DirSource(src))
    assert r2["steps"]["predictions_appended"] == 0 and r2["counts"]["quotes"] == 1                       # nothing duplicated
    assert all(c["ok"] for c in r2["chains"].values())


def _git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout


def test_publish_is_append_only(tmp_path):
    bare = tmp_path / "remote.git"; subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    work = tmp_path / "clone"; subprocess.run(["git", "init", "-q", str(work)], check=True)
    _git(work, "remote", "add", "origin", str(bare)); (work / "f").write_text("x"); _git(work, "add", "f")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    out = tmp_path / "out"; PP.append(out / "predictions.jsonl", {"kind": "prediction", "i": 1}); PP.append(out / "predictions.jsonl", {"kind": "prediction", "i": 2})
    r1 = PC.publish(work, out); assert r1["pushed"], r1
    assert PC.publish(work, out).get("unchanged")                                                      # idempotent
    PP.append(out / "predictions.jsonl", {"kind": "prediction", "i": 3})
    assert PC.publish(work, out)["pushed"]
    shown = _git(bare, "show", f"{PC.BRANCH}:nfl_totals_v1/predictions.jsonl").splitlines(); assert len(shown) == 3 and json.loads(shown[2])["i"] == 3
    lines = (out / "predictions.jsonl").read_text().splitlines(); rec = json.loads(lines[0]); rec["i"] = 99; lines[0] = json.dumps(rec, sort_keys=True)
    (out / "predictions.jsonl").write_text("\n".join(lines) + "\n")                                    # rewrite history locally
    r = PC.publish(work, out); assert not r["pushed"] and "append-only violation" in r["error"]


def test_fallback_book_is_a_valid_decision_source_but_legacy_quotes_are_not(tmp_path):
    g = pd.DataFrame({"game_id": ["g1"], "gameday": ["2026-11-08"], "away_team": ["AAA"], "home_team": ["HHH"], "season": [2026], "week": [10]})
    at = iso(362)
    book = {"series": "KXNFLTOTAL", "n": 1, "pages": [{"fetched_utc": at, "markets": [_mk("KXNFLTOTAL-26NOV08AAAHHH-48")]}]}
    PP.record_quotes(book, g, tmp_path)
    preds, quotes, ob = ([pred(30)], CI._read(tmp_path / "quotes.jsonl"), CI._read(tmp_path / "observations.jsonl"))
    frame, audit = PP.audit_and_frame(preds, quotes, ob, GAMES, KO)
    assert status(audit, "T-6h") == ["ELIGIBLE"] and abs(frame[frame.horizon == "T-6h"].iloc[0]["age"] - 2) < 1e-9
    legacy = [{k: v for k, v in q.items() if k != "source"} for q in quotes]                    # old-format record without a source tag
    assert status(PP.audit_and_frame(preds, legacy, ob, GAMES, KO)[1], "T-6h") == ["NO_QUOTE_ROW"]


def test_capture_loop_records_failures_and_continues(tmp_path):
    srv, url = _serve([(200, {"markets": [_mk("KXNFLTOTAL-26NOV08AAAHHH-48")], "cursor": ""}), (500, {}), (500, {}), (500, {}), (500, {}), (200, {"markets": [_mk("KXNFLTOTAL-26NOV08AAAHHH-50")], "cursor": ""})])
    g = tmp_path / "games.csv"; pd.DataFrame({"game_id": ["2026_10_AAA_HHH"], "gameday": ["2026-11-08"], "away_team": ["AAA"], "home_team": ["HHH"], "season": [2026], "week": [10]}).to_csv(g, index=False)
    code = (f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r}); import alpha_engine.lab.prospective as P; P.time.sleep = lambda s: None; "
            f"P.main(['capture','--games',{str(g)!r},'--dir',{str(tmp_path / 'o')!r},'--api',{url!r},'--loop-minutes','0.005','--interval','0'])")
    import time as _t
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60); srv.shutdown()
    assert (tmp_path / "o" / "observations.jsonl").exists() and (tmp_path / "o" / "capture_failures.jsonl").exists()


# ---------------------------------------------------------------- player v3 prospective experiment (separately labelled)
from alpha_engine.lab import player_prospective as PPR


def test_player_contract_parsing_and_label():
    games = pd.DataFrame({"game_id": ["2026_10_NYG_PHI"], "gameday": ["2026-11-08"], "away_team": ["NYG"], "home_team": ["PHI"], "season": [2026], "week": [10]})
    mk = {"ticker": "KXNFLRECYDS-26NOV08NYGPHI-NYGTJOHNSON84-60", "title": "Theo Johnson: 60+ receiving yards", "floor_strike": 59.5}
    u = PPR.contracts_from_book({"KXNFLRECYDS": {"pages": [{"markets": [mk, {"ticker": "x", "title": "junk", "floor_strike": 1.0}]}]}}, games)
    r = u.iloc[0]
    assert len(u) == 1 and r["player"] == "Theo Johnson" and r["team"] == "NYG" and r["family"] == "rec_yds" and r["floor"] == 59.5 and PPR.LABEL == "MARKET_SELECTED_POPULATION"


def test_player_settlement_semantics():
    pg = pd.DataFrame({"game_id": ["g", "g"], "pid": ["a", "b"], "rec_yds": [60.0, 59.0], "rec": [4, 3], "rush_yds": [0.0, 0.0], "pass_yds": [0.0, 0.0], "td_any": [1, 0]})
    c = pd.DataFrame({"ticker": ["t60", "t60b", "tabsent", "tun"], "game_id": ["g", "g", "g", "h"], "pid": ["a", "b", "z", "a"], "family": ["rec_yds"] * 4, "floor": [59.5, 59.5, 0.5, 59.5]})
    out = PPR.settle(c, pg, pd.DataFrame({"game_id": ["g", "h"], "home_score": [20.0, np.nan]}))
    assert out == {"t60": 1.0, "t60b": 0.0, "tabsent": 0.0, "tun": None}          # 60 >= 60 yes; 59 no; no recorded involvement = 0; unfinished game = None


def test_player_decisions_use_series_observation_and_latest_prediction():
    def p(gen_h, mp):
        return {"kind": "contract_prediction", "ticker": "T", "game_id": "g1", "family": "rec_yds", "series": "KXNFLRECYDS", "kickoff_utc": KO.isoformat(), "generated_utc": (KO - pd.Timedelta(hours=gen_h)).isoformat(), "model_p": mp, "week": 10}
    q = [dict(quote(400, ticker="T"), source=PP.SOURCE_FALLBACK, floor=59.5)]
    ob = [{"series": "KXNFLRECYDS", "observed_at": iso(362), "complete": True}, {"series": "KXNFLTOTAL", "observed_at": iso(361), "complete": True}]
    frame, audit = PPR.audit_and_frame([p(40, 0.2), p(10, 0.7), p(1, 0.99)], q, ob, {"T": 1.0}, KO)
    r = frame[frame.horizon == "T-6h"].iloc[0]
    assert r["model_p"] == 0.7 and r["outcome"] == 1.0 and abs(r["age"] - 2) < 1e-9
    f2, a2 = PPR.audit_and_frame([p(10, 0.7)], q, [{"series": "KXNFLTOTAL", "observed_at": iso(362), "complete": True}], {"T": 1.0}, KO)    # another series' observation is not a quote observation for this contract
    assert [a["status"] for a in a2 if a["horizon"] == "T-6h"] == ["NO_COMPLETE_OBSERVATION_IN_WINDOW"]
    gate = PP.claim_gate(frame, True)
    assert gate["status"] == "INSUFFICIENT_N"


def test_empty_book_is_an_error_unless_explicitly_allowed():
    srv, url = _serve([(200, {"markets": [], "cursor": ""})])
    with pytest.raises(PP.FetchError):
        PP.fetch_totals(base=url, pause=0)
    srv.shutdown()
    srv, url = _serve([(200, {"markets": [], "cursor": ""})])
    b = PP.fetch_totals(base=url, pause=0, allow_empty=True); srv.shutdown()
    assert b["n"] == 0 and b["complete"] and len(b["pages"]) == 1


def test_player_series_rows_in_the_shared_ledger_are_not_totals_contracts():
    player_row = dict(quote(400, ticker="KXNFLRECYDS-26NOV08AAAHHH-AAATX1-60", floor=59.5), series="KXNFLRECYDS")
    assert status(PP.audit_and_frame([pred(30)], [player_row], [obs(365)], GAMES, KO)[1], "T-6h") == ["NO_QUOTE_ROW"]


def test_player_report_runs_end_to_end_on_synthetic_ledgers(tmp_path, monkeypatch):
    from alpha_engine.lab import player_lab as PLm
    pdir, qdir, ddir = tmp_path / "p", tmp_path / "q", tmp_path / "d"; ddir.mkdir()
    PP.append(pdir / "predictions.jsonl", {"kind": "contract_prediction", "ticker": "T", "game_id": "g1", "family": "rec_yds", "series": "KXNFLRECYDS", "pid": "a", "kickoff_utc": KO.isoformat(),
                                           "generated_utc": (KO - pd.Timedelta(hours=30)).isoformat(), "model_p": 0.6, "week": 10})
    PP.append(qdir / "quotes.jsonl", dict(quote(400, ticker="T", floor=59.5), series="KXNFLRECYDS", source=PP.SOURCE_FALLBACK))
    PP.append(qdir / "observations.jsonl", {"kind": "series_observation", "series": "KXNFLRECYDS", "observed_at": iso(362), "complete": True, "run_id": "r"})
    GAMES.to_csv(ddir / "games.csv", index=False)
    monkeypatch.setattr(PLm, "load_pbp_players", lambda *a, **k: None)
    monkeypatch.setattr(PLm, "player_games", lambda *a, **k: pd.DataFrame({"game_id": ["g1"], "pid": ["a"], "rec_yds": [75.0], "rec": [5], "rush_yds": [0.0], "pass_yds": [0.0], "td_any": [0]}))
    r = PC.run_player_report(pdir, qdir, ddir, now=KO)
    assert r["label"] == "MARKET_SELECTED_POPULATION" and r["audit_by_horizon"]["T-6h"] == {"ELIGIBLE": 1} and r["gate"]["status"] == "INSUFFICIENT_N"


def test_freeze_pins_match_the_committed_declarations_and_detect_edits(tmp_path):
    root = Path(__file__).resolve().parents[1] / "research" / "prospective"
    assert PC.verify_pins(root / "nfl_totals_v1") == {} and PC.verify_pins(root / "nfl_player_v3", PC.PLAYER_PINS) == {}
    import shutil
    shutil.copytree(root / "nfl_totals_v1", tmp_path / "t")
    f = tmp_path / "t" / "FREEZE.json"; f.write_text(f.read_text().replace("nfl_totals_v1", "nfl_totals_v2", 1))
    assert "FREEZE.json" in PC.verify_pins(tmp_path / "t")


def test_cycle_aborts_on_changed_freeze_declaration_and_on_sigma_drift(tmp_path, monkeypatch):
    P = pd.DataFrame({"game_id": ["g0"], "season": [2025], "week": [1], "mu": [41.0], "sigma": [13.0], "mu0": [44.0]})
    monkeypatch.setattr(PC, "build_predictions", lambda *a, **k: (P, GAMES, "sha"))
    out = tmp_path / "out"; out.mkdir()
    (out / "FREEZE.json").write_text(json.dumps({"frozen_utc": "2026-11-01T00:00:00+00:00"}))
    (out / "FREEZE_DIGEST.json").write_text(json.dumps({"mu_digest_2014_2025": PC.digest_mu(P), "sigma_digest_2014_2025": "0" * 64}))
    r = PC.run_cycle(tmp_path, None, out, tmp_path / "w", now=KO, download=False)
    assert r.get("aborted") and r["steps"]["frozen_reproduction"]["sigma_ok"] is False and not (out / "predictions.jsonl").exists()      # sigma changed, mu did not
    r2 = PC.run_cycle(tmp_path, None, out, tmp_path / "w", now=KO, download=False, pins=PC.PINS)
    assert "frozen declaration changed" in r2["aborted"]


def test_accounting_covers_every_game_horizon_and_flags_gaps():
    g = pd.DataFrame({"game_id": ["a", "b", "c"], "season": [2026] * 3, "gameday": ["2026-11-01", "2026-11-08", "2026-11-15"], "gametime": ["13:00", "13:00", "13:00"]})
    frozen = "2026-11-06T00:00:00+00:00"
    audit = [{"game_id": gid, "horizon": h} for gid in ("b", "c") for h in PP.HORIZONS_MIN]
    r = PP.accounting(g, audit, frozen)
    assert r["game_horizons"] == 9 and r["ineligible_decision_before_freeze"] == 3 and r["unaccounted"] == []          # game a kicked off before the freeze
    r2 = PP.accounting(g, audit[:-1], frozen)
    assert r2["unaccounted"] == ["c:T-90m"]                                                                            # a missing audit row is reported, not hidden
