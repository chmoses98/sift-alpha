"""One autonomous cycle of the frozen nfl_totals_v1 prospective experiment (RESEARCH_ONLY): refresh -> predict -> ingest -> evaluate -> publish.

Safety properties, all enforced in code (and tested):
  * frozen model: the config is `prospective.FROZEN`; before anything is appended the 2014-2025 predictions are rebuilt and compared with FREEZE_DIGEST.json -- any drift aborts the cycle
  * predictions are appended only with the current timestamp and only when mu changed; earlier versions are never edited; a decision uses the latest prediction generated before it
  * quotes come ONLY from the verified collector (capture_ingest); a run that was never captured is a reported gap, not a reconstruction
  * publishing is append-only: every ledger already on the data branch must be a byte-prefix of the new file, else nothing is pushed"""
from __future__ import annotations
import hashlib, json, os, shutil, subprocess, tempfile, time
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


def run_cycle(data_dir: Path, md_repo: Path | None, out: Path, work: Path, now: pd.Timestamp | None = None, download: bool = True, md_src=None, md_ref: str = "origin/market-data", pins: dict | None = None, exchange_results: dict | None = None) -> dict:
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
    frame, audit = PP.audit_and_frame(preds, quotes, obs, games, now, exchange_results=exchange_results)
    first = min((pd.Timestamp(p["generated_utc"]) for p in preds), default=now)
    rep["accounting"] = PP.accounting(games, audit, fz_utc)
    rep.update({"chains": chains, "evaluation": PP.evaluate(frame, audit, chains_ok), "capture_gaps": CI.capture_gaps(obs, first, now) if obs else None,
                "counts": {"predictions": len(preds), "quotes": len(quotes), "observations": len(obs), "complete_observations": sum(1 for o in obs if o["complete"])}})
    ev = frame[(frame["horizon"] == "T-6h") & frame["outcome"].notna()] if not frame.empty else frame
    rep["eligible_decision_games"] = {"T-6h_settled": int(ev["game_id"].nunique()) if len(ev) else 0, "by_status": PP.audit_summary(audit)}
    (out / "REPORT.json").write_text(json.dumps(rep, indent=1, default=float))
    (out / "decision_audit.json").write_text(json.dumps(audit, indent=0))
    return rep


# ------------------------------------------------------------------ commit provenance and the single-writer lease
def code_sha(repo: Path) -> str:
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def commit_message(message: str, meta: dict | None) -> str:
    """Every publishing run is identified in the commit itself (git trailers), so any ledger/shard commit can be traced to its run, role and code version."""
    if not meta:
        return message
    return message + "\n\n" + "\n".join(f"{k}: {v}" for k, v in meta.items())


LEASE = "LEASE.json"


def _read_branch_file(repo: Path, rel: str, remote: str = "origin", branch: str = BRANCH) -> bytes | None:
    r = subprocess.run(["git", "-C", str(repo), "show", f"FETCH_HEAD:{rel}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def _push_one(repo: Path, files: dict[str, bytes], message: str, branch: str, remote: str, meta: dict | None, expect_head: str | None = None) -> dict:
    """Commit `files` on top of the CURRENT branch head and push (non-force).  If `expect_head` is given the push is only attempted when the head has not moved (compare-and-swap)."""
    tmp = Path(tempfile.mkdtemp())
    try:
        have = _run(repo, "fetch", "--depth=1", remote, branch, check=False).returncode == 0
        head = _run(repo, "rev-parse", "FETCH_HEAD").stdout.strip() if have else None
        if expect_head is not None and head != expect_head:
            return {"pushed": False, "raced": True}
        _run(repo, "worktree", "prune", check=False)
        if have:
            _run(repo, "worktree", "add", "-f", "--detach", str(tmp / "wt"), "FETCH_HEAD")
        else:
            _run(repo, "worktree", "add", "-f", "--detach", str(tmp / "wt"), "HEAD"); _run(tmp / "wt", "checkout", "--orphan", branch); _run(tmp / "wt", "rm", "-rf", "--quiet", ".", check=False)
        wt = tmp / "wt"
        for rel, data in files.items():
            (wt / rel).parent.mkdir(parents=True, exist_ok=True); (wt / rel).write_bytes(data)
        _run(wt, "add", "-A")
        if not _run(wt, "status", "--porcelain").stdout.strip():
            return {"pushed": False, "unchanged": True}
        _run(wt, "-c", "user.name=prospective-bot", "-c", "user.email=prospective-bot@users.noreply.github.com", "commit", "-qm", commit_message(message, meta))
        pr = _run(wt, "push", remote, f"HEAD:refs/heads/{branch}", check=False); ok = pr.returncode == 0
        return {"pushed": ok, "commit": _run(wt, "rev-parse", "HEAD").stdout.strip() if ok else None, "raced": not ok, **({} if ok else {"error": ((pr.stderr or "") + (pr.stdout or "")).strip()[-400:]})}
    finally:
        _run(repo, "worktree", "remove", "--force", str(tmp / "wt"), check=False); shutil.rmtree(tmp, ignore_errors=True)


def acquire_lease(repo: Path, holder: str, role: str = "refresh", ttl_min: float = 45.0, now: pd.Timestamp | None = None, branch: str = BRANCH, remote: str = "origin") -> dict:
    """Single-writer lease for ledger refreshes, held in a file on the data branch and taken with a compare-and-swap push (two racing writers cannot both win).  A held, unexpired lease
    blocks other holders; an expired lease may be taken over (the takeover is itself a commit that names the previous holder)."""
    now = now or pd.Timestamp.now(tz="UTC")
    for _ in range(3):
        have = _run(repo, "fetch", "--depth=1", remote, branch, check=False).returncode == 0
        head = _run(repo, "rev-parse", "FETCH_HEAD").stdout.strip() if have else None
        cur = _read_branch_file(repo, LEASE) if have else None
        prev = json.loads(cur) if cur else None
        if prev and not prev.get("released") and prev.get("holder") != holder and pd.Timestamp(prev["expires_utc"]) > now:
            return {"acquired": False, "reason": "lease held", "holder": prev["holder"], "expires_utc": prev["expires_utc"]}
        doc = {"holder": holder, "role": role, "acquired_utc": now.isoformat(), "expires_utc": (now + pd.Timedelta(minutes=ttl_min)).isoformat(), "released": False,
               "took_over_from": prev["holder"] if prev and not prev.get("released") and prev.get("holder") != holder else None}
        r = _push_one(repo, {LEASE: json.dumps(doc, indent=1).encode()}, f"lease: acquire ({role})", branch, remote, {"writer-run": holder, "role": role}, expect_head=head)
        if r.get("pushed"):
            return {"acquired": True, **doc}
    return {"acquired": False, "reason": "lost the race to another writer"}


def release_lease(repo: Path, holder: str, now: pd.Timestamp | None = None, branch: str = BRANCH, remote: str = "origin") -> dict:
    now = now or pd.Timestamp.now(tz="UTC")
    _run(repo, "fetch", "--depth=1", remote, branch, check=False)
    cur = _read_branch_file(repo, LEASE)
    if not cur or json.loads(cur).get("holder") != holder:
        return {"released": False, "reason": "not the holder"}
    doc = json.loads(cur); doc.update({"released": True, "released_utc": now.isoformat()})
    r = _push_one(repo, {LEASE: json.dumps(doc, indent=1).encode()}, "lease: release", branch, remote, {"writer-run": holder, "role": doc.get("role", "refresh")})
    return {"released": bool(r.get("pushed"))}


def lease_ok(repo: Path, holder: str, now: pd.Timestamp | None = None, remote: str = "origin", branch: str = BRANCH) -> bool:
    now = now or pd.Timestamp.now(tz="UTC")
    _run(repo, "fetch", "--depth=1", remote, branch, check=False)
    cur = _read_branch_file(repo, LEASE)
    if not cur:
        return False
    d = json.loads(cur)
    return d.get("holder") == holder and not d.get("released") and pd.Timestamp(d["expires_utc"]) > now


# ------------------------------------------------------------------ append-only publication
def _run(cwd, *a, check=True):
    return subprocess.run(["git", "-C", str(cwd), *a], check=check, capture_output=True, text=True)


import re
_SEG = re.compile(r"^(predictions|quotes|observations)(\.\d{4})?\.jsonl$")


def fetch_branch_files(repo: Path, branch: str, rel: str, dest: Path) -> list[str]:
    """Copy ledgers already published on the data branch into dest (so the cycle continues the SAME chain), INCLUDING every size-bounded segment (quotes.0001.jsonl ...).  Returns the names found."""
    got = []
    if _run(repo, "fetch", "--depth=1", "origin", branch, check=False).returncode != 0:
        return got
    ls = subprocess.run(["git", "-C", str(repo), "ls-tree", "--name-only", "FETCH_HEAD", f"{rel}/"], capture_output=True, text=True)
    names = [Path(x).name for x in ls.stdout.split()] if ls.returncode == 0 else []
    for f in [n for n in names if _SEG.match(n)] + ["FREEZE.json", "FREEZE_DIGEST.json"]:
        r = subprocess.run(["git", "-C", str(repo), "show", f"FETCH_HEAD:{rel}/{f}"], capture_output=True)
        if r.returncode == 0:
            Path(dest).mkdir(parents=True, exist_ok=True); (Path(dest) / f).write_bytes(r.stdout); got.append(f)
    return got


AUX_FILES = ("FREEZE.json", "FREEZE_DIGEST.json", "REPORT.json", "decision_audit.json", "alerts.json")


def ledger_files(out: Path) -> dict[str, Path]:
    """Every file of every logical ledger in `out` (all segments), name -> path."""
    out = Path(out); files = {}
    for base in LEDGERS:
        for sp in PP.segment_paths(out / base):
            files[sp.name] = sp
    return files


def verify_remote(repo: Path, expected: dict[str, Path], rel: str, branch: str = BRANCH, remote: str = "origin") -> dict:
    """Fail-closed proof of publication: fetch the REMOTE branch head and compare the git blob id of every expected file with the local file's.  Equal blob ids = equal bytes.  A failed fetch,
    a missing file or a differing blob is `verified: False` -- a successful `git push` exit code alone is never accepted as evidence."""
    r = _run(repo, "fetch", "--depth=1", remote, branch, check=False)
    if r.returncode != 0:
        return {"verified": False, "error": "remote fetch failed: " + (r.stderr or "")[-200:], "files": len(expected)}
    head = _run(repo, "rev-parse", "FETCH_HEAD").stdout.strip(); bad = []
    for name, path in sorted(expected.items()):
        want = _run(repo, "hash-object", str(path)).stdout.strip()
        got = _run(repo, "rev-parse", f"FETCH_HEAD:{rel}/{name}", check=False)
        if got.returncode != 0:
            bad.append({"file": name, "problem": "missing on remote"})
        elif got.stdout.strip() != want:
            bad.append({"file": name, "problem": "differs from local"})
    return {"verified": not bad, "remote_head": head, "files": len(expected), "mismatches": bad[:10]}


def publish(repo: Path, out: Path, rel: str = "nfl_totals_v1", branch: str = BRANCH, remote: str = "origin", message: str = "prospective cycle", meta: dict | None = None, holder: str | None = None) -> dict:
    """Append-only push of the out/ ledgers (every segment) to `branch`, then PROOF that the remote contains exactly those bytes.
    Guards (all fail closed, none push): lease; every file already on the branch must be a byte-prefix of its local twin; no segment may exist only on the branch; no file may exceed
    MAX_PUBLISH_FILE_BYTES (GitHub rejects >100 MiB).  Result: pushed / unchanged AND verified; a rejected push reports git's own error text.  Non-force; retried on a race."""
    out = Path(out)
    if holder is not None and not lease_ok(repo, holder, remote=remote, branch=branch):
        return {"pushed": False, "verified": False, "error": "ledger publication refused: this run does not hold the single-writer lease"}
    try:
        local = ledger_files(out)
    except PP.LedgerLayoutError as e:
        return {"pushed": False, "verified": False, "error": f"ledger layout violation: {e}"}
    big = {n: p.stat().st_size for n, p in local.items() if p.stat().st_size > PP.MAX_PUBLISH_FILE_BYTES}
    if big:
        return {"pushed": False, "verified": False, "error": f"OVERSIZE_FILE: {big} exceeds {PP.MAX_PUBLISH_FILE_BYTES} bytes; refusing to push (repartition the ledger)"}
    expected = dict(local)
    for f in AUX_FILES:
        if (out / f).exists():
            expected[f] = out / f
    last_err = ""
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
            remote_segs = {q.name for q in dst.iterdir() if q.is_file() and _SEG.match(q.name)}
            missing = sorted(remote_segs - set(local))
            if missing:
                return {"pushed": False, "verified": False, "error": f"append-only violation: segment(s) {missing} are on {branch} but absent from the local ledger"}
            for name, new in local.items():
                old = dst / name
                if old.exists() and not _is_prefix(old, new):
                    return {"pushed": False, "verified": False, "error": f"append-only violation: {name} on {branch} is not a prefix of the local ledger"}
                shutil.copyfile(new, old)
            for f in AUX_FILES:
                if (out / f).exists():
                    shutil.copyfile(out / f, dst / f)
            _run(wt, "add", "-A")
            if not _run(wt, "status", "--porcelain").stdout.strip():
                v = verify_remote(repo, expected, rel, branch, remote)
                return {"pushed": False, "unchanged": True, **v}
            _run(wt, "-c", "user.name=prospective-bot", "-c", "user.email=prospective-bot@users.noreply.github.com", "commit", "-qm", commit_message(message, meta))
            commit = _run(wt, "rev-parse", "HEAD").stdout.strip()
            r = _run(wt, "push", remote, f"HEAD:refs/heads/{branch}", check=False)
            if r.returncode == 0:
                v = verify_remote(repo, expected, rel, branch, remote)
                return {"pushed": True, "commit": commit, "attempt": attempt + 1, **v}
            last_err = ((r.stderr or "") + (r.stdout or "")).strip()[-600:]
            if any(m in last_err for m in ("GH001", "exceeds", "file size limit", "Large files")):
                return {"pushed": False, "verified": False, "error": "push REJECTED by the remote: " + last_err}           # a size-limit rejection is deterministic: retrying cannot heal it
            time.sleep(0.4 * (attempt + 1))                                                                                 # a race (non-fast-forward, ref lock, transient fetch error): back off and retry on a fresh head
        finally:
            _run(repo, "worktree", "remove", "--force", str(tmp / "wt"), check=False); shutil.rmtree(tmp, ignore_errors=True)
    return {"pushed": False, "verified": False, "error": "push failed after retries (non-fast-forward race or network): " + last_err}


def _is_prefix(old: Path, new: Path, chunk: int = 1 << 20) -> bool:
    """True iff the bytes of `old` are a prefix of `new` (streamed; ledgers are large)."""
    if old.stat().st_size > new.stat().st_size:
        return False
    with open(old, "rb") as a, open(new, "rb") as b:
        while True:
            x = a.read(chunk)
            if not x:
                return True
            if b.read(len(x)) != x:
                return False


def publication_status(steps: dict) -> tuple[bool, list[str]]:
    """The ONLY definition of a successful refresh publication: every publication the run attempted is verified on the remote.  Returns (ok, reasons)."""
    reasons = []

    def good(r):
        return isinstance(r, dict) and bool(r.get("verified")) and (bool(r.get("pushed")) or bool(r.get("unchanged")))
    t = steps.get("publish_totals")
    if not good(t):
        reasons.append("publish_totals:" + ("not attempted" if t is None else (str(t.get("error") or ("unverified: " + str(t.get("mismatches") or t.get("pushed"))))[:160])))
    if "publish_player" in steps and not good(steps["publish_player"]):
        pp = steps["publish_player"]; reasons.append("publish_player:" + str(pp.get("error") or ("unverified: " + str(pp.get("mismatches"))))[:160])
    pl = steps.get("player_predict")
    if isinstance(pl, dict) and pl.get("error"):
        reasons.append("player_refresh:" + str(pl["error"])[:120])
    sc = steps.get("settle_capture") or {}
    if sc.get("publish") and not (sc["publish"].get("pushed") or sc["publish"].get("unchanged")):
        reasons.append("settlement_publish:" + str(sc["publish"].get("error") or "not pushed")[:120])
    return (not reasons), reasons


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
def publish_captures(repo: Path, stage: Path, branch: str = BRANCH, remote: str = "origin", message: str = "capture shards", meta: dict | None = None) -> dict:
    """Publish NEW files from `stage` (whose layout mirrors the branch root) to `branch`.  A capture worker may only ever add files under ALLOWED_PREFIXES (captures/, contracts/, heartbeats/,
    settlements/): any other staged path is refused and reported, so a capture run cannot touch ledgers, freeze files, the lease, or anything else.  Never overwrites a different file at an
    existing path; identical re-publication is a no-op.  Concurrent writers cannot fork anything because every path is new."""
    from . import capture_window as CW
    stage = Path(stage)
    files = sorted(p for p in stage.rglob("*") if p.is_file() and not p.name.startswith("_") and p.suffix in (".gz", ".json"))
    bad = [str(p.relative_to(stage)) for p in files if not str(p.relative_to(stage)).startswith(CW.ALLOWED_PREFIXES)]
    if bad:
        return {"pushed": False, "error": f"refused: staged paths outside the capture allowlist: {bad[:5]}"}
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
                dst = wt / f.relative_to(stage)
                if dst.exists():
                    if dst.read_bytes() != f.read_bytes():
                        return {"pushed": False, "error": f"append-only violation: {dst.relative_to(wt)} exists with different content"}
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(f, dst); added += 1
            if not added:
                return {"pushed": False, "unchanged": True}
            _run(wt, "add", "-A")
            _run(wt, "-c", "user.name=prospective-bot", "-c", "user.email=prospective-bot@users.noreply.github.com", "commit", "-qm", commit_message(f"{message} (+{added})", meta))
            pr = _run(wt, "push", remote, f"HEAD:refs/heads/{branch}", check=False)
            if pr.returncode == 0:
                return {"pushed": True, "added": added, "commit": _run(wt, "rev-parse", "HEAD").stdout.strip(), "attempt": attempt + 1}
            last_err = ((pr.stderr or "") + (pr.stdout or "")).strip()[-300:]
        finally:
            _run(repo, "worktree", "remove", "--force", str(tmp / "wt"), check=False); shutil.rmtree(tmp, ignore_errors=True)
    return {"pushed": False, "error": "push failed after retries: " + locals().get("last_err", "")}


def fetch_branch_tree(repo: Path, branch: str, rel: str, dest: Path, remote: str = "origin") -> int:
    """Extract `rel/` from the branch head into dest (read-only retrieval for the single-writer ingester).  Returns the number of files."""
    if _run(repo, "fetch", "--depth=1", remote, branch, check=False).returncode != 0:
        return 0
    Path(dest).mkdir(parents=True, exist_ok=True)
    r = subprocess.run(f"git -C {repo} archive FETCH_HEAD {rel} | tar -x -C {dest}", shell=True, capture_output=True)
    return sum(1 for _ in Path(dest).rglob("*.json.gz")) if r.returncode == 0 else 0


# ------------------------------------------------------------------ the single-writer refresh (expensive, run rarely) -- capture itself lives in capture_window
def run_refresh(repo: Path, work: Path, data_dir: Path, player: bool = True, now: pd.Timestamp | None = None, season: int = 2026, run_id: str | None = None, use_lease: bool = True) -> dict:
    """Single writer.  lease -> fetch published state -> refresh nflverse -> ingest new capture shards -> frozen-model + pin checks -> predictions -> evaluate -> alerts -> (player) -> append-only
    publish (lease re-checked, commit trailers name this run) -> release lease.  A run that cannot take the lease changes NOTHING."""
    from . import capture_window as CW, alerts as AL
    from ..input_research import refresh as RF
    repo, work, data_dir = Path(repo), Path(work), Path(data_dir)
    now = now or pd.Timestamp.now(tz="UTC"); run_id = run_id or f"refresh-{now.strftime('%Y%m%dT%H%M%SZ')}"
    out = {"refresh_utc": now.isoformat(), "run_id": run_id, "mode": "RESEARCH_ONLY", "steps": {}}
    meta = {"writer-run": run_id, "role": "refresh", "code": code_sha(repo)[:12]}
    if use_lease:
        lz = acquire_lease(repo, run_id, now=now); out["steps"]["lease"] = lz
        if not lz.get("acquired"):
            out["lease_busy"] = True; out["alert_summary"] = AL.summarize([{"severity": "WARN", "code": "LEASE_BUSY", "detail": str(lz)}]); return out
    try:
        return _refresh_locked(repo, work, data_dir, player, now, season, run_id, meta, out, use_lease)
    finally:
        if use_lease:
            out["steps"]["lease_release"] = release_lease(repo, run_id)


def _refresh_locked(repo, work, data_dir, player, now, season, run_id, meta, out, use_lease):
    from . import capture_window as CW, alerts as AL
    from ..input_research import refresh as RF
    holder = run_id if use_lease else None
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
    hbs_dir = work / "hb"; fetch_branch_tree(repo, BRANCH, "heartbeats", hbs_dir)
    out["steps"]["shard_ingest"] = CW.ingest_shards(shards, pv, games, now=now)
    sstage = work / "settle_stage"; sh = CW.capture_settled(lambda: pd.Timestamp.now(tz="UTC"))
    CW.write_shard(sstage, sh, kind="settlements")
    out["steps"]["settle_capture"] = {"markets": sum(b["n"] for b in sh["books"].values()), "failures": sh["failures"]}
    sp = publish_captures(repo, sstage, message="settlement evidence", meta=meta); out["steps"]["settle_capture"]["publish"] = sp; out["steps"]["settle_capture"]["published"] = bool(sp.get("pushed"))
    fetch_branch_tree(repo, BRANCH, "settlements", work / "settle_tree")
    xr, xconf = CW.load_exchange_results(work / "settle_tree"); out["steps"]["exchange_results"] = {"tickers": len(xr), "conflicts": len(xconf)}
    rep = run_cycle(data_dir, None, pv, work / "cyc", now=now, download=False, pins=PINS, exchange_results=xr)
    out["cycle"] = {k: rep.get(k) for k in ("steps", "counts", "eligible_decision_games", "aborted", "accounting")}
    out["steps"]["cycle"] = out["cycle"]
    heartbeats = [json.loads(f.read_text()) for f in sorted(hbs_dir.rglob("*.json"))] if hbs_dir.exists() else []
    obs = CI._read(pv / "observations.jsonl")
    first = json.loads((pv / "FREEZE.json").read_text())["frozen_utc"]
    ko = CW.kickoffs(games, season); cov = CW.coverage_matrix(ko[ko > pd.Timestamp(first)], obs) if len(ko) else None
    extra = []
    if rep.get("aborted"):
        extra.append({"severity": "HIGH", "code": "FROZEN_MODEL_ABORT", "detail": str(rep["aborted"])[:200]})
    for k, v in (rep.get("evaluation") or {}).get("audit_by_horizon", {}).items():
        if v.get("SETTLEMENT_MISMATCH"):
            extra.append({"severity": "HIGH", "code": "SETTLEMENT_MISMATCH", "detail": f"{k}: {v['SETTLEMENT_MISMATCH']} game-horizon cell(s) where exchange result != nflverse outcome"})
    if xconf:
        extra.append({"severity": "HIGH", "code": "SETTLEMENT_MISMATCH", "detail": f"{len(xconf)} ticker(s) with conflicting exchange results across shards"})
    wins = [{"start": dt - pd.Timedelta(minutes=CW.PRE_MIN), "end": dt + pd.Timedelta(minutes=CW.POST_MIN)} for _, _, dt in CW.decision_times(ko[ko > pd.Timestamp(first)], now)] if len(ko) else []
    alerts = AL.evaluate(heartbeats, obs, out["steps"]["shard_ingest"], now, coverage=cov, since=first, extra=extra, windows=wins)
    out["alerts"] = alerts; out["alert_summary"] = AL.summarize(alerts)
    (pv / "alerts.json").write_text(json.dumps({"generated_utc": now.isoformat(), "run_id": run_id, "summary": out["alert_summary"], "alerts": alerts}, indent=1))
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
            out["steps"]["publish_player"] = publish(repo, pp, rel="nfl_player_v3", message="prospective player refresh", meta=meta, holder=holder)
        except Exception as e:                                                     # a failed player refresh never blocks the totals experiment
            out["steps"]["player_predict"] = {"error": repr(e)[:300]}
    out["steps"]["publish_totals"] = publish(repo, pv, rel="nfl_totals_v1", message="prospective refresh", meta=meta, holder=holder)
    return out
