"""Read-only sources for production artifacts. Every adapter talks to this interface only:

    read_bytes(path) / read_json(path)   one file at the source's pinned commit
    list_files(prefix)                   file paths (recursive) under prefix
    meta()                               {"repo", "ref", "commit", "committed_at"}

GitSource   a local git repository + ref (a normal clone, or a blobless shallow cache made by
            `remote_git`, which lazily fetches only the blobs that are read).
HttpSource  raw.githubusercontent.com for files + the GitHub REST API for the commit and tree
            listing; pinned to the commit sha resolved once at construction.
DirSource   a plain directory (recorded test fixtures).
"""
import gzip
import json
import os
import subprocess
import urllib.request
from pathlib import Path

OWNER = "chmoses98"


def _decode(path, data):
    if path.endswith(".gz"):
        data = gzip.decompress(data)
    return json.loads(data)


class Source:
    def read_bytes(self, path):
        raise NotImplementedError

    def read_json(self, path):
        return _decode(path, self.read_bytes(path))

    def list_files(self, prefix):
        raise NotImplementedError

    def meta(self):
        raise NotImplementedError


class GitSource(Source):
    def __init__(self, repo_dir, ref, repo=None):
        self.dir, self.ref = str(repo_dir), ref
        self.repo = repo or f"{OWNER}/{Path(repo_dir).name.removesuffix('.git')}"
        out = self._git("log", "-1", "--format=%H %cI", ref).split()
        self.commit, self.committed_at = out[0], out[1]

    def _git(self, *args, binary=False):
        r = subprocess.run(["git", "-C", self.dir, *args], capture_output=True, check=True)
        return r.stdout if binary else r.stdout.decode()

    def read_bytes(self, path):
        return self._git("cat-file", "blob", f"{self.commit}:{path}", binary=True)

    def list_files(self, prefix):
        out = self._git("ls-tree", "-r", "--name-only", self.commit, "--", prefix.rstrip("/"))
        return [line for line in out.splitlines() if line]

    def prefetch(self, paths):
        """Blobless caches: fetch the named blobs in one round trip instead of one per read."""
        promisor = subprocess.run(["git", "-C", self.dir, "config", "--get", "remote.origin.promisor"],
                                  capture_output=True, text=True).stdout.strip()
        if not paths or promisor != "true":
            return
        oids = []
        for i in range(0, len(paths), 200):
            out = self._git("ls-tree", self.commit, "--", *paths[i:i + 200])
            oids += [line.split()[2] for line in out.splitlines() if line]
        subprocess.run(["git", "-C", self.dir, "fetch", "-q", "--no-tags", "--no-write-fetch-head",
                        "--filter=blob:none", "origin", *oids], capture_output=True)

    def meta(self):
        return {"repo": self.repo, "ref": self.ref.rsplit("/", 1)[-1] if self.ref.startswith("refs/") else self.ref,
                "commit": self.commit, "committed_at": _utc(self.committed_at)}


class HttpSource(Source):
    API = "https://api.github.com/repos"
    RAW = "https://raw.githubusercontent.com"

    def __init__(self, repo, ref, opener=None):
        self.repo, self.ref = (repo if "/" in repo else f"{OWNER}/{repo}"), ref
        self._open = opener or _http_get
        c = json.loads(self._open(f"{self.API}/{self.repo}/commits/{ref}"))
        self.commit, self.committed_at = c["sha"], c["commit"]["committer"]["date"]

    def read_bytes(self, path):
        return self._open(f"{self.RAW}/{self.repo}/{self.commit}/{path}")

    def list_files(self, prefix):
        prefix = prefix.rstrip("/")
        t = json.loads(self._open(f"{self.API}/{self.repo}/git/trees/{self.commit}:{prefix}?recursive=1"))
        if t.get("truncated"):
            raise RuntimeError(f"tree listing truncated for {self.repo}:{prefix}")
        return [f"{prefix}/{e['path']}" for e in t.get("tree", []) if e["type"] == "blob"]

    def meta(self):
        return {"repo": self.repo, "ref": self.ref, "commit": self.commit, "committed_at": _utc(self.committed_at)}


class DirSource(Source):
    def __init__(self, root, repo="fixture/repo", ref="fixture", commit="0" * 40, committed_at="2026-11-18T00:00:00Z"):
        self.root, self._meta = Path(root), {"repo": repo, "ref": ref, "commit": commit, "committed_at": committed_at}

    def read_bytes(self, path):
        return (self.root / path).read_bytes()

    def list_files(self, prefix):
        base = self.root / prefix
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())

    def meta(self):
        return dict(self._meta)


def _http_get(url, timeout=60):
    headers = {"User-Agent": "sift-feed", "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN") and url.startswith(HttpSource.API):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return r.read()


def remote_git(cache_dir, repo, branch):
    """Blobless, depth-1 bare cache of one public branch (trees only; blobs arrive lazily on read)."""
    d = Path(cache_dir) / repo.replace("/", "__")
    url = f"https://github.com/{repo if '/' in repo else OWNER + '/' + repo}.git"
    if not d.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(d)], check=True)
        for k, v in (("remote.origin.url", url), ("remote.origin.promisor", "true"),
                     ("remote.origin.partialclonefilter", "blob:none")):
            subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(d), "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin",
                    f"+refs/heads/{branch}:refs/remotes/origin/{branch}"], check=True)
    return GitSource(d, f"refs/remotes/origin/{branch}", repo=repo if "/" in repo else f"{OWNER}/{repo}")


def _utc(ts):
    """Normalise an ISO timestamp to UTC 'YYYY-MM-DDTHH:MM:SSZ'."""
    from .schema import iso, parse_ts
    return iso(parse_ts(ts))
