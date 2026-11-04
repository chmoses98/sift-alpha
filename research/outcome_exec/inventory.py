#!/usr/bin/env python3
"""Cross-repo data inventory (tree listings only; no blobs are downloaded). Writes aggregates: per repo/branch file counts by
top-level path group and by dated-range. usage: inventory.py OUT.json owner/repo[:branch,branch]..."""
import json, os, re, subprocess, sys, tempfile, collections

DATA_RE = re.compile(r"(data|evidence|ledger|settle|scores|archive|outcome|market|research|projection|sweep|history)", re.I)


def sh(*a, cwd=None, timeout=280):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def group(path):
    parts = path.split("/")
    g = "/".join(parts[:3]) if len(parts) > 3 else "/".join(parts[:-1]) or "."
    return re.sub(r"\d{4}-\d{2}-\d{2}|\d{8}T\d{6}Z|\d{4}_\d{2}_\w+|[A-Z]{2,}\d*-\d{2}[A-Z]{3}\d+\w*", "*", g)


def main(out, specs):
    res = {}
    for spec in specs:
        repo, _, brs = spec.partition(":")
        d = tempfile.mkdtemp(prefix="inv_")
        sh("git", "init", "-q", d)
        sh("git", "remote", "add", "origin", f"https://github.com/{repo}", cwd=d)
        heads = sh("git", "ls-remote", "--heads", "origin", cwd=d).stdout.split("\n")
        names = [h.split("refs/heads/")[1] for h in heads if "refs/heads/" in h]
        want = brs.split(",") if brs else [n for n in names if not n.startswith(("claude/", "fix/", "ops/", "research/", "audit/", "amend/", "recovery/", "maint/", "feat/", "chore/", "dependabot/")) and n != "main"]
        entry = dict(branches_total=len(names), data_branches={})
        for b in ["main"] + want:
            if b not in names:
                continue
            r = sh("git", "fetch", "-q", "--depth=1", "--filter=blob:none", "origin", f"{b}:refs/b/{b}", cwd=d)
            if r.returncode:
                entry["data_branches"][b] = dict(error=r.stderr[-200:]); continue
            files = sh("git", "ls-tree", "-r", "--name-only", f"refs/b/{b}", cwd=d).stdout.split("\n")
            files = [f for f in files if f]
            c = collections.Counter(group(f) for f in files)
            dates = sorted({m for f in files for m in re.findall(r"20\d{2}-\d{2}-\d{2}", f)})
            entry["data_branches"][b] = dict(files=len(files), groups=dict(c.most_common(25)), first_date=dates[0] if dates else None, last_date=dates[-1] if dates else None)
        res[repo] = entry
        print(repo, {k: v.get("files") for k, v in entry["data_branches"].items()}, flush=True)
    json.dump(res, open(out, "w"), indent=1, sort_keys=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
