"""Strict, immutable, no-credential source intake for historical research.

No trading, no paid APIs, no source endpoints other than specifically
allowlisted public raw GitHub files pinned to a full commit and Git blob SHA.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

VALID_REPO = re.compile(r"^chmoses98/[A-Za-z0-9-]+$")
VALID_COMMIT = re.compile(r"^[0-9a-f]{40}$")
VALID_SHA = re.compile(r"^[0-9a-f]{40}$")
SAFE_PATH = re.compile(r"^[A-Za-z0-9_./=-]+$")


def load_manifest(path: Path) -> list[dict[str, Any]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("schema_version") != 1 or not isinstance(obj.get("sources"), list):
        raise ValueError("Invalid versioned source manifest")
    entries = obj["sources"]
    if not entries or len({entry.get("id") for entry in entries}) != len(entries):
        raise ValueError("No sources or duplicate source IDs")
    for entry in entries:
        if entry.get("repo") not in ("chmoses98/cfb-edge-finder", "chmoses98/edge-finder-api"):
            raise ValueError("Repository is not on explicit read-only allowlist")
        if not VALID_REPO.fullmatch(entry["repo"]) or not VALID_COMMIT.fullmatch(entry["commit"]):
            raise ValueError("Source must have pinned owner/repo and full commit")
        if not VALID_SHA.fullmatch(entry["git_blob_sha1"]):
            raise ValueError("Missing pinned Git blob digest")
        p = entry["path"]
        if not SAFE_PATH.fullmatch(p) or ".." in p.split("/") or p.startswith("/"):
            raise ValueError("Unsafe source path")
        if entry["format"] not in ("jsonl", "json") or entry.get("max_bytes") not in range(1, 1_000_001):
            raise ValueError("Unsupported source format / unbounded read")
        if entry.get("data_class") != "public_derived_research":
            raise ValueError("No approved public research data class")
        if entry.get("rights") != "upstream_data_rights_not_independently_verified":
            raise ValueError("Unexpected source rights declaration: requires new review")
    return entries


def source_url(entry: dict[str, Any]) -> str:
    return "https://raw.githubusercontent.com/" + entry["repo"] + "/" + entry["commit"] + "/" + entry["path"]


def verify_blob(data: bytes, entry: dict[str, Any]) -> dict[str, str | int]:
    if len(data) > entry["max_bytes"] or not data:
        raise ValueError("Source size outside explicitly bounded range")
    git_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\\0" + data).hexdigest()
    if git_blob != entry["git_blob_sha1"]:
        raise ValueError("Source hash mismatch: refuse modified data")
    return {"blob_sha1": git_blob, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def read_source(entry: dict[str, Any], *, offline_path: Path | None = None) -> bytes:
    if offline_path is not None:
        data = offline_path.read_bytes()
    else:
        request = urllib.request.Request(source_url(entry), headers={"User-Agent": "SIFT-Alpha-research-audit/0.1"})
        with urllib.request.urlopen(request, timeout=18) as response:
            if response.geturl() != source_url(entry):
                raise ValueError("Unexpected source redirect")
            data = response.read(entry["max_bytes"] + 1)
    verify_blob(data, entry)
    return data


def parsed_source(data: bytes, entry: dict[str, Any]) -> Any:
    decoded = data.decode("utf-8")
    if entry["format"] == "jsonl":
        rows = [json.loads(line) for line in decoded.splitlines() if line.strip()]
        if not rows or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Expected nonempty JSONL record objects")
        return rows
    obj = json.loads(decoded)
    if not isinstance(obj, dict) or not obj:
        raise ValueError("Expected nonempty JSON dictionary")
    return obj
