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
    cfg = {k: PP.FROZEN[k] for k in ("model", "dist", "rating", "groups")}
    lab = GL.GameLab(gt, tg, work / "ledger_tmp.jsonl", work / "cache")
    P = lab.final_predictions("total", cfg, last=season)
    games = pd.read_csv(data_dir / "games.csv")
    sha = hashlib.sha256(((view / "games.csv").read_bytes() + (data_dir / "pbp" / f"pbp_{season}.parquet").read_bytes())).hexdigest()[:16]
    return P, games, sha


def run_cycle(data_dir: Path, md_repo: Path | None, out: Path, work: Path, now: pd.Timestamp | None = None, download: bool = True, md_src=None, md_ref: str = "origin/market-data") -> dict:
    now = now or pd.Timestamp.now(tz="UTC")
    out = Path(out); work = Path(work); work.mkdir(parents=True, exist_ok=True)
    rep: dict = {"cycle_utc": now.isoformat(), "config_id": PP.config_id(), "mode": "RESEARCH_ONLY", "steps": {}}
    P, games, dsha = build_predictions(Path(data_dir), work, download)
    fz = json.loads((out / "FREEZE_DIGEST.json").read_text())
    got = digest_mu(P)
    rep["steps"]["frozen_reproduction"] = {"ok": got == fz["mu_digest_2014_2025"], "expected": fz["mu_digest_2014_2025"], "got": got}
    if got != fz["mu_digest_2014_2025"]:
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
