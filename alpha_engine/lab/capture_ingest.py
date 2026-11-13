"""Durable, append-only ingestion of the EXISTING verified point-in-time NFL Kalshi collector (nfl-edge-finder `data/kalshi/capture/<date>/<run>.{manifest,quotes}.jsonl` on `market-data`).
RESEARCH_ONLY.  Nothing here fetches from an exchange, places orders, or reconstructs a quote that was not captured live.

For every collector run that observed a watched series we append
  * one `series_observation`: run id, observed_at, completeness, tier, n, whether the run was partial / had errors, source path + git blob ids of the manifest and quotes file
  * one `quote` per row the collector wrote for that series (it writes only rows whose fingerprint changed; an unchanged contract is covered by the next complete observation)
Ingestion is idempotent (a run id already present is skipped), strictly additive (hash chain; see prospective.append/verify_chain) and read-only against the source.
A run that is missing from the source is simply absent: `capture_gaps` reports it and the decision audit gives the affected games NO_COMPLETE_OBSERVATION_IN_WINDOW."""
from __future__ import annotations
import json, re, subprocess
from pathlib import Path
import pandas as pd
from . import prospective as PP

RUN = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})/(?P<run>\d{8}T\d{6}Z)\.manifest\.json$")
TOTAL_SERIES = ("KXNFLTOTAL",)


class GitSource:
    """Read-only view of a branch of a (partial) clone: listing via ls-tree, content via cat-file; blob ids from rev-parse."""
    def __init__(self, repo: Path, ref: str = "origin/market-data", base: str = "data/kalshi/capture"):
        self.repo, self.ref, self.base = str(repo), ref, base

    def _git(self, *a: str) -> bytes:
        return subprocess.run(["git", "-C", self.repo, *a], check=True, capture_output=True).stdout

    def runs(self) -> list[str]:
        out = self._git("ls-tree", "-r", "--name-only", self.ref, self.base + "/").decode().splitlines()
        return sorted(o[len(self.base) + 1:] for o in out if RUN.match(o[len(self.base) + 1:]))

    def read(self, rel: str) -> bytes:
        return self._git("cat-file", "blob", f"{self.ref}:{self.base}/{rel}")

    def blob(self, rel: str) -> str:
        return self._git("rev-parse", f"{self.ref}:{self.base}/{rel}").decode().strip()

    def exists(self, rel: str) -> bool:
        return subprocess.run(["git", "-C", self.repo, "cat-file", "-e", f"{self.ref}:{self.base}/{rel}"], capture_output=True).returncode == 0


class DirSource:
    """Same interface over a plain directory (tests)."""
    def __init__(self, root: Path):
        self.root = Path(root)

    def runs(self) -> list[str]:
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*.manifest.json") if RUN.match(str(p.relative_to(self.root))))

    def read(self, rel: str) -> bytes:
        return (self.root / rel).read_bytes()

    def blob(self, rel: str) -> str:
        import hashlib
        return hashlib.sha1(b"blob %d\0" % len((self.root / rel).read_bytes()) + (self.root / rel).read_bytes()).hexdigest()

    def exists(self, rel: str) -> bool:
        return (self.root / rel).exists()


def _read(path: Path) -> list[dict]:
    """Records of a (possibly segmented) ledger: quotes.jsonl + quotes.0001.jsonl ... in chain order; a plain file is just that file."""
    return PP.read_ledger(path)


def ingest(src, out_dir: Path, series=TOTAL_SERIES, since_run: str | None = None) -> dict:
    """Append new runs.  Returns counts, including runs seen but unusable (and why)."""
    out_dir = Path(out_dir); obs_p, q_p = out_dir / "observations.jsonl", out_dir / "quotes.jsonl"
    done = {(o["run_id"], o["series"]) for o in _read(obs_p)}
    stats = {"runs_seen": 0, "runs_new": 0, "observations": 0, "quotes": 0, "skipped": {}}
    for rel in src.runs():
        m = RUN.match(rel); run_id = m["run"]
        if since_run and run_id < since_run:
            continue
        stats["runs_seen"] += 1
        try:
            man = json.loads(src.read(rel))
        except Exception as e:
            stats["skipped"][run_id] = f"manifest unreadable: {e!r}"[:120]; continue
        qrel = rel.replace(".manifest.json", ".quotes.jsonl")
        new = False
        rows = None
        for s in series:
            info = (man.get("series") or {}).get(s)
            if info is None or (run_id, s) in done:
                continue
            if rows is None:
                if not src.exists(qrel):
                    stats["skipped"][run_id] = "quotes file missing"; break
                rows = [json.loads(l) for l in src.read(qrel).decode().splitlines() if l.strip()]
            complete = bool(info.get("complete")) and not man.get("partial") and not info.get("provisional")
            PP.append(obs_p, {"kind": "series_observation", "source": PP.SOURCE_CAPTURE, "run_id": run_id, "series": s, "observed_at": info["observed_at"], "complete": complete,
                              "n": info.get("n"), "tier": info.get("tier"), "run_partial": bool(man.get("partial")), "run_errors": len(man.get("errors") or []),
                              "trigger_source": man.get("trigger_source"), "manifest_path": rel, "manifest_blob": src.blob(rel), "quotes_path": qrel, "quotes_blob": src.blob(qrel)})
            stats["observations"] += 1; new = True
            for r in rows:
                if r.get("series_ticker") != s or r.get("yes_bid_dollars") is None or r.get("yes_ask_dollars") is None:
                    continue
                PP.append(q_p, {"kind": "quote", "source": PP.SOURCE_CAPTURE, "run_id": run_id, "series": s, "observed_at": r["observed_at"], "ticker": r["ticker"], "game_id": r.get("game_id"),
                                "floor": r.get("floor_strike"), "bid": float(r["yes_bid_dollars"]), "ask": float(r["yes_ask_dollars"]), "bid_size": r.get("yes_bid_size_fp"), "ask_size": r.get("yes_ask_size_fp"),
                                "kickoff_utc": r.get("kickoff_utc"), "status": r.get("status"), "result": r.get("result"), "changed": r.get("changed")})
                stats["quotes"] += 1
        stats["runs_new"] += int(new)
    return stats


def capture_gaps(obs: list[dict], start, end, series="KXNFLTOTAL", max_gap_min: float = PP.PRIMARY_AGE_MIN) -> dict:
    """Missing-capture report from the observation ledger: gaps longer than max_gap_min between consecutive COMPLETE observations inside [start, end]."""
    t = sorted(pd.Timestamp(o["observed_at"]) for o in obs if o["series"] == series and o["complete"])
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    t = [x for x in t if start <= x <= end]
    pts = [start] + t + [end]
    gaps = [{"from": a.isoformat(), "to": b.isoformat(), "minutes": round((b - a).total_seconds() / 60, 1)} for a, b in zip(pts, pts[1:]) if (b - a).total_seconds() / 60 > max_gap_min]
    return {"complete_observations": len(t), "window_minutes": round((end - start).total_seconds() / 60, 1), "gaps_over_limit": len(gaps), "longest_gap_min": max([g["minutes"] for g in gaps], default=0.0),
            "covered_minutes": round((end - start).total_seconds() / 60 - sum(g["minutes"] for g in gaps), 1), "gaps": gaps[:50]}
