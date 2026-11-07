"""One autonomous cycle of the frozen nfl_totals_v1 prospective experiment (RESEARCH_ONLY): refresh -> predict -> ingest -> evaluate -> publish.

Safety properties, all enforced in code (and tested):
  * frozen model: the config is `prospective.FROZEN`; before anything is appended the 2014-2025 predictions are rebuilt and compared with FREEZE_DIGEST.json -- any drift aborts the cycle
  * predictions are appended only with the current timestamp and only when mu changed; earlier versions are never edited; a decision uses the latest prediction generated before it
  * quotes come ONLY from the verified collector (capture_ingest); a run that was never captured is a reported gap, not a reconstruction
  * publishing is append-only: every ledger already on the data branch must be a byte-prefix of the new file, else nothing is pushed"""
from __future__ import annotations
import hashlib, json, os, shutil, subprocess, tempfile
from pathlib import Path
import numpy as np
import pandas as pd
from . import prospective as PP, capture_ingest as CI

LEDGERS = ("predictions.jsonl", "quotes.jsonl", "observations.jsonl")
BRANCH = "prospective-data"


# sha256 of the frozen declarations, pinned IN CODE: changing a freeze file therefore needs a visible code change, and a cycle that finds a different file aborts without appending.
PINS = {"FREEZE.json": "4de7dba4ae0bf4af21b771cf642a161fdfed1d565f83a310adb31c36f84a2e78",
        "FREEZE_DIGEST.json": "f979647e42701fb2278db9f4997c84856a667cee3ce1ef91401185454ade47ee"}
PLAYER_PINS = {"FREEZE.json": "8a32f4c827be7500a3b72b991023cdf459c6ab5c4b91e0517e63700bc6293b82"}


def verify_pins(d: Path, pins: dict = None) -> dict:
    pins = PINS if pins is None else pins
    bad = {}
    for f, want in pins.items():
        p = Path(d) / f
        got = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        if got != want:
            bad[f] = {"expected": want, "got": got}
    return bad


def digest_sigma(P: pd.DataFrame) -> str:
    x = P[P["season"].between(2014, 2025)].sort_values("game_id")
    return hashlib.sha256(",".join(f"{g}:{s:.6f}" for g, s in zip(x["game_id"], x["sigma"])).encode()).hexdigest()


def digest_mu(P: pd.DataFrame) -> str:
    x = P[P["season"].between(2014, 2025)].sort_values("game_id")
    return hashlib.sha256(",".join(f"{g}:{m:.6f}" for g, m in zip(x["game_id"], x["mu"])).encode()).hexdigest()


def build_predictions(data_dir: Path, work: Path, download: bool, season: int = 2026) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    from . import repair, game_lab as GL
    from ..input_research import nfl_features as nf, refresh as RF
    if download:
        RF.download(data_dir, season)
    view = repair.normalized_data_dir(data_dir, work / "view", fill_weather=True)
    gt = nf.add_matchup_features(nf.build_game_table(view, 2010, season))
    tg = nf.team_games_from_pbp(nf.load_pbp(view / "pbp", sorted(gt["season"].unique())))
    (work / "lab").mkdir(parents=True, exist_ok=True); gt.to_parquet(work / "lab" / "game_table.parquet"); tg.to_parquet(work / "lab" / "tg.parquet")
    cfg = {k: PP.FROZEN[k] for k in ("model", "dist", "rating", "groups")}
    lab = GL.GameLab(gt, tg, work / "ledger_tmp.jsonl", work / "cache")
    P = lab.final_predictions("total", cfg, last=season)
    games = pd.read_csv(data_dir / "games.csv")
    sha = hashlib.sha256(((view / "games.csv").read_bytes() + (data_dir / "pbp" / f"pbp_{season}.parquet").read_bytes())).hexdigest()[:16]
    return P, games, sha


def run_cycle(data_dir: Path, md_repo: Path | None, out: Path, work: Path, now: pd.Timestamp | None = None, download: bool = True, md_src=None, md_ref: str = "origin/market-data", pins: dict | None = None) -> dict:
    now = now or pd.Timestamp.now(tz="UTC")
    out = Path(out); work = Path(work); work.mkdir(parents=True, exist_ok=True)
    rep: dict = {"cycle_utc": now.isoformat(), "config_id": PP.config_id(), "mode": "RESEARCH_ONLY", "steps": {}}
    if pins is not None:
        bad = verify_pins(out, pins)
        if bad:
            rep["aborted"] = f"frozen declaration changed or missing: {sorted(bad)}; nothing appended"; rep["pin_mismatch"] = bad
            (out / "REPORT.json").write_text(json.dumps(rep, indent=1)); return rep
    P, games, dsha = build_predictions(Path(data_dir), work, download)
    fz = json.loads((out / "FREEZE_DIGEST.json").read_text())
    got, gots = digest_mu(P), digest_sigma(P)
    ok_mu = got == fz["mu_digest_2014_2025"]; ok_sig = fz.get("sigma_digest_2014_2025") in (None, gots)
    rep["steps"]["frozen_reproduction"] = {"ok": ok_mu and ok_sig, "mu_ok": ok_mu, "sigma_ok": ok_sig, "expected": fz["mu_digest_2014_2025"], "got": got}
    if not (ok_mu and ok_sig):
        rep["aborted"] = "frozen model no longer reproduces its 2014-2025 predictions (data revision or code drift); nothing appended"
        (out / "REPORT.json").write_text(json.dumps(rep, indent=1)); return rep
    rep["steps"]["predictions_appended"] = PP.predict(P, games, now, out / "predictions.jsonl", dsha)
    src = md_src or (CI.GitSource(md_repo, ref=md_ref) if md_repo else None)
    fz_utc = json.loads((out / "FREEZE.json").read_text())["frozen_utc"]
    since = (pd.Timestamp(fz_utc) - pd.Timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")        # nothing before the freeze can be a decision input
    rep["steps"]["ingest"] = CI.ingest(src, out, since_run=since) if src is not None else {"skipped": "no market-data source"}
    preds, quotes, obs = (CI._read(out / f) for f in ("predictions.jsonl", "quotes.jsonl", "observations.jsonl"))
    chains = {f: PP.verify_chain(out / f) for f in LEDGERS if (out / f).exists()}
    chains_ok = all(c["ok"] for c in chains.values())
    frame, audit = PP.audit_and_frame(preds, quotes, obs, games, now)
    first = min((pd.Timestamp(p["generated_utc"]) for p in preds), default=now)
    rep["accounting"] = PP.accounting(games, audit, fz_utc)
    rep.update({"chains": chains, "evaluation": PP.evaluate(frame, audit, chains_ok), "capture_gaps": CI.capture_gaps(obs, first, now) if obs else None,
                "counts": {"predictions": len(preds), "quotes": len(quotes), "observations": len(obs), "complete_observations": sum(1 for o in obs if o["complete"])}})
    ev = frame[(frame["horizon"] == "T-6h") & frame["outcome"].notna()] if not frame.empty else frame
    rep["eligible_decision_games"] = {"T-6h_settled": int(ev["game_id"].nunique()) if len(ev) else 0, "by_status": PP.audit_summary(audit)}
    (out / "REPORT.json").write_text(json.dumps(rep, indent=1, default=float))
    (out / "decision_audit.json").write_text(json.dumps(audit, indent=0))
    return rep


# ------------------------------------------------------------------ append-only publication
def _run(cwd, *a, check=True):
    return subprocess.run(["git", "-C", str(cwd), *a], check=check, capture_output=True, text=True)


def fetch_branch_files(repo: Path, branch: str, rel: str, dest: Path) -> list[str]:
    """Copy ledgers already published on the data branch into dest (so the cycle continues the SAME chain).  Returns the file names found."""
    got = []
    if _run(repo, "fetch", "--depth=1", "origin", branch, check=False).returncode != 0:
        return got
    for f in LEDGERS + ("FREEZE.json", "FREEZE_DIGEST.json"):
        r = subprocess.run(["git", "-C", str(repo), "show", f"FETCH_HEAD:{rel}/{f}"], capture_output=True)
        if r.returncode == 0:
            Path(dest).mkdir(parents=True, exist_ok=True); (Path(dest) / f).write_bytes(r.stdout); got.append(f)
    return got


def publish(repo: Path, out: Path, rel: str = "nfl_totals_v1", branch: str = BRANCH, remote: str = "origin", message: str = "prospective cycle") -> dict:
    """Append-only push of the out/ ledgers to `branch`.  Guard: every file already on the branch must be a byte-prefix of the local file.  Non-force; retried on a race."""
    out = Path(out)
    for attempt in range(4):
        tmp = Path(tempfile.mkdtemp())
        try:
            have_branch = _run(repo, "fetch", "--depth=1", remote, branch, check=False).returncode == 0
            _run(repo, "worktree", "prune", check=False)
            if have_branch:
                _run(repo, "worktree", "add", "-f", "--detach", str(tmp / "wt"), "FETCH_HEAD")
            else:
                _run(repo, "worktree", "add", "-f", "--detach", str(tmp / "wt"), "HEAD"); wt = tmp / "wt"
                _run(wt, "checkout", "--orphan", branch); _run(wt, "rm", "-rf", "--quiet", ".", check=False)
            wt = tmp / "wt"; dst = wt / rel; dst.mkdir(parents=True, exist_ok=True)
            for f in LEDGERS:
                new = out / f
                if not new.exists():
                    continue
                old = dst / f
                if old.exists():
                    b = old.read_bytes()
                    if not new.read_bytes().startswith(b):
                        return {"pushed": False, "error": f"append-only violation: {f} on {branch} is not a prefix of the local ledger"}
                shutil.copyfile(new, old)
            for f in ("FREEZE.json", "FREEZE_DIGEST.json", "REPORT.json", "decision_audit.json"):
                if (out / f).exists():
                    shutil.copyfile(out / f, dst / f)
            _run(wt, "add", "-A")
            if not _run(wt, "status", "--porcelain").stdout.strip():
                return {"pushed": False, "unchanged": True}
            _run(wt, "-c", "user.name=prospective-bot", "-c", "user.email=prospective-bot@users.noreply.github.com", "commit", "-qm", message)
            r = _run(wt, "push", remote, f"HEAD:refs/heads/{branch}", check=False)
            if r.returncode == 0:
                return {"pushed": True, "commit": _run(wt, "rev-parse", "HEAD").stdout.strip(), "attempt": attempt + 1}
        finally:
            _run(repo, "worktree", "remove", "--force", str(tmp / "wt"), check=False); shutil.rmtree(tmp, ignore_errors=True)
    return {"pushed": False, "error": "push failed after retries (non-fast-forward race or network)"}


def run_player_report(player_dir: Path, quotes_dir: Path, data_dir: Path, now: pd.Timestamp | None = None, season: int = 2026) -> dict:
    """Evaluate the separately labelled player experiment: its own predictions ledger, the shared quote/observation ledgers, outcomes from post-game play-by-play, its OWN gate (never pooled with totals)."""
    from . import player_prospective as PPR, player_lab as PL
    now = now or pd.Timestamp.now(tz="UTC"); player_dir, quotes_dir, data_dir = Path(player_dir), Path(quotes_dir), Path(data_dir)
    preds = CI._read(player_dir / "predictions.jsonl"); quotes = CI._read(quotes_dir / "quotes.jsonl"); obs = CI._read(quotes_dir / "observations.jsonl")
    games = pd.read_csv(data_dir / "games.csv")
    floors = {}
    for q in quotes:
        if q.get("floor") is not None:
            floors[q["ticker"]] = q["floor"]
    contracts = pd.DataFrame([{"ticker": p["ticker"], "game_id": p["game_id"], "pid": p.get("pid"), "family": p["family"], "floor": floors.get(p["ticker"], np.nan)} for p in preds]).drop_duplicates("ticker")
    contracts = contracts.dropna(subset=["floor"]) if len(contracts) else contracts
    pg = PL.player_games(PL.load_pbp_players(data_dir / "pbp", [season])) if len(contracts) else pd.DataFrame()
    outcomes = PPR.settle(contracts, pg, games) if len(contracts) else {}
    frame, audit = PPR.audit_and_frame(preds, quotes, obs, outcomes, now)
    chains_ok = all(PP.verify_chain(f)["ok"] for f in (player_dir / "predictions.jsonl", quotes_dir / "quotes.jsonl", quotes_dir / "observations.jsonl") if f.exists())
    gate = PP.claim_gate(frame, chains_ok)
    gate["scope"] = "applies to the MARKET_SELECTED_POPULATION (exchange-listed players) only"
    by: dict = {}
    for a in audit:
        by.setdefault(a["horizon"], {}).setdefault(a["status"], 0); by[a["horizon"]][a["status"]] += 1
    rep = {"cycle_utc": now.isoformat(), "label": PPR.LABEL, "experiment": "nfl_player_v3_listed_emp", "predictions": len(preds), "contracts": int(len(contracts)), "audit_by_horizon": by, "gate": gate}
    (player_dir / "REPORT.json").write_text(json.dumps(rep, indent=1, default=float))
    return rep


# ------------------------------------------------------------------ capture shards: new-files-only publication and retrieval
def publish_captures(repo: Path, stage: Path, branch: str = BRANCH, remote: str = "origin", rel: str = "captures", message: str = "capture shards") -> dict:
    """Publish immutable capture shards as NEW files on `branch` (never overwrites a different file at an existing path; identical re-publication is a no-op).  Safe for concurrent capture
    sessions: shards have unique names, so a lost push race is simply retried against the fresh branch head."""
    stage = Path(stage)
    files = sorted(p for p in stage.rglob("*.json.gz"))
    if not files:
        return {"pushed": False, "unchanged": True}
    for attempt in range(5):
        tmp = Path(tempfile.mkdtemp())
        try:
            have = _run(repo, "fetch", "--depth=1", remote, branch, check=False).returncode == 0
            _run(repo, "worktree", "prune", check=False)
            if have:
                _run(repo, "worktree", "add", "-f", "--detach", str(tmp / "wt"), "FETCH_HEAD")
            else:
                _run(repo, "worktree", "add", "-f", "--detach", str(tmp / "wt"), "HEAD"); _run(tmp / "wt", "checkout", "--orphan", branch); _run(tmp / "wt", "rm", "-rf", "--quiet", ".", check=False)
            wt = tmp / "wt"; added = 0
            for f in files:
                dst = wt / rel / f.relative_to(stage)
                if dst.exists():
                    if dst.read_bytes() != f.read_bytes():
                        return {"pushed": False, "error": f"append-only violation: {dst.relative_to(wt)} exists with different content"}
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(f, dst); added += 1
            if not added:
                return {"pushed": False, "unchanged": True}
            _run(wt, "add", "-A")
            _run(wt, "-c", "user.name=prospective-bot", "-c", "user.email=prospective-bot@users.noreply.github.com", "commit", "-qm", f"{message} (+{added})")
            if _run(wt, "push", remote, f"HEAD:refs/heads/{branch}", check=False).returncode == 0:
                return {"pushed": True, "added": added, "commit": _run(wt, "rev-parse", "HEAD").stdout.strip(), "attempt": attempt + 1}
        finally:
            _run(repo, "worktree", "remove", "--force", str(tmp / "wt"), check=False); shutil.rmtree(tmp, ignore_errors=True)
    return {"pushed": False, "error": "push failed after retries"}


def fetch_branch_tree(repo: Path, branch: str, rel: str, dest: Path, remote: str = "origin") -> int:
    """Extract `rel/` from the branch head into dest (read-only retrieval for the single-writer ingester).  Returns the number of files."""
    if _run(repo, "fetch", "--depth=1", remote, branch, check=False).returncode != 0:
        return 0
    Path(dest).mkdir(parents=True, exist_ok=True)
    r = subprocess.run(f"git -C {repo} archive FETCH_HEAD {rel} | tar -x -C {dest}", shell=True, capture_output=True)
    return sum(1 for _ in Path(dest).rglob("*.json.gz")) if r.returncode == 0 else 0


# ------------------------------------------------------------------ the single-writer refresh (expensive, run rarely) -- capture itself lives in capture_window
def run_refresh(repo: Path, work: Path, data_dir: Path, player: bool = True, now: pd.Timestamp | None = None, season: int = 2026) -> dict:
    """fetch published state -> refresh nflverse -> ingest new capture shards -> frozen-model check + new predictions -> evaluate -> (player predictions + report) -> append-only publish."""
    from . import capture_window as CW
    from ..input_research import refresh as RF
    repo, work, data_dir = Path(repo), Path(work), Path(data_dir)
    now = now or pd.Timestamp.now(tz="UTC"); out = {"refresh_utc": now.isoformat(), "mode": "RESEARCH_ONLY", "steps": {}}
    seed = repo / "research" / "prospective"
    pv, pp = work / "pv", work / "pv_player"
    for rel, d, seeddir in (("nfl_totals_v1", pv, seed / "nfl_totals_v1"), ("nfl_player_v3", pp, seed / "nfl_player_v3")):
        d.mkdir(parents=True, exist_ok=True)
        got = fetch_branch_files(repo, BRANCH, rel, d) if _run(repo, "ls-remote", "--exit-code", "origin", BRANCH, check=False).returncode == 0 else []
        if "predictions.jsonl" not in got:                                      # first run seeds the branch from the frozen ledgers committed with the PR
            for f in seeddir.glob("*"):
                if f.is_file():
                    shutil.copyfile(f, d / f.name)
        for f in ("FREEZE.json", "FREEZE_DIGEST.json"):                         # the frozen declarations always come from the committed PR, never from a mutable place
            if (seeddir / f).exists():
                shutil.copyfile(seeddir / f, d / f)
        out["steps"][f"state_{rel}"] = {"from_branch": got}
    RF.download(data_dir, season)
    games = pd.read_csv(data_dir / "games.csv")
    shards = work / "shards"; out["steps"]["shards_fetched"] = fetch_branch_tree(repo, BRANCH, "captures", shards)
    out["steps"]["shard_ingest"] = CW.ingest_shards(shards, pv, games, now=now)
    rep = run_cycle(data_dir, None, pv, work / "cyc", now=now, download=False, pins=PINS)
    out["steps"]["cycle"] = {k: rep.get(k) for k in ("steps", "counts", "eligible_decision_games", "aborted")}
    if rep.get("aborted"):
        out["aborted"] = rep["aborted"]; return out
    if player and verify_pins(pp, PLAYER_PINS):
        out["steps"]["player_predict"] = {"error": "player freeze declaration changed or missing", "pin_mismatch": verify_pins(pp, PLAYER_PINS)}
        player = False
    if player:
        from . import player_prospective as PPR
        try:
            out["steps"]["player_predict"] = PPR.run_predict(data_dir, work / "player", repo / "research" / "audit" / "lab", pp, work / "cyc" / "lab" / "game_table.parquet", now)
            out["steps"]["player_gate"] = run_player_report(pp, pv, data_dir, now)["gate"]
            out["steps"]["publish_player"] = publish(repo, pp, rel="nfl_player_v3", message="prospective player refresh")
        except Exception as e:                                                     # a failed player refresh never blocks the totals experiment
            out["steps"]["player_predict"] = {"error": repr(e)[:300]}
    out["steps"]["publish_totals"] = publish(repo, pv, rel="nfl_totals_v1", message="prospective refresh")
    return out
