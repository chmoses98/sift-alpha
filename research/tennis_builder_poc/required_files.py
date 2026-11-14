"""Authorization manifest for a real-data replay of tennis_ext6 (RESEARCH_ONLY, offline).

Reads ONLY research/input_research/data_collection/repo_archives_ledger.json and lists the exact pinned Sackmann files (with SHA-256) that a real-data replay would need.
Nothing is fetched. Writes required_files.json next to this file."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
L = json.loads((ROOT / "research/input_research/data_collection/repo_archives_ledger.json").read_text())
files, meta = [], {}
for k in ("tennis_atp_matches", "tennis_wta_matches"):
    d = L["datasets"][k]
    meta[k] = {x: d[x] for x in ("source_repo", "branch", "rows", "date_min", "date_max", "files", "note")}
    tour = k.split("_")[1]
    for name, sha in sorted(d["sha256_by_file"].items()):
        files.append({"path_in_repo": f"tennis_{tour}/{name}", "file": name, "sha256": sha})
out = {
    "status": "RESEARCH_ONLY - authorization request, nothing downloaded",
    "licence": "Jeff Sackmann tennis_atp / tennis_wta, CC BY-NC-SA 4.0 (registry sackmann_tennis: CLEARED_NONCOMMERCIAL_RESEARCH; commercial use NOT cleared)",
    "source": "github.com/chmoses98/Tennis-Edge-Finder, branch tennis-data (the owner's own repository; anonymous git read of a public repo per the 2026-11-10 access record)",
    "snapshot_discrepancy": "ledger note says snapshot 2026-11-06; rights_and_access_20261110b.json says snapshot 20261109T145505Z. The SHA-256 list below is authoritative: a replay must refuse any file whose hash differs.",
    "ledger": "research/input_research/data_collection/repo_archives_ledger.json",
    "datasets": meta,
    "n_files": len(files),
    "files": files,
    "access_needed": "attach chmoses98/Tennis-Edge-Finder to a session (read-only) or place the 54 files in a local directory; no other host, account or key",
    "replay_command_not_run": "python -m alpha_engine.input_research.data_foundation.replay_ext_run tennis6 <DIR_WITH_FILES> research/input_research/data_foundation/verification/replay_ext/TENNIS_tennis6.json",
    "then": "independent blind re-implementation from a written brief (as for tennis_ext4) and compare_independent; only both passing may change any status",
}
(pathlib.Path(__file__).parent / "required_files.json").write_text(json.dumps(out, indent=1) + "\n")
print(out["n_files"], "files")
