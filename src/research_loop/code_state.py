"""Deterministic provenance for the exact code and config that produced a run."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def _working_tree_material(repo: Path) -> tuple[bytes, list[dict[str, str]]]:
    """Return tracked binary diff plus identity-bearing untracked entries.

    Git's binary diff does not include untracked files.  Their relative paths
    and exact-byte hashes are included in the material so two dirty trees at
    one HEAD cannot share a code-state identity merely because one change is
    untracked.
    """
    tracked = _git(repo, "diff", "--binary", "--no-ext-diff", "HEAD")
    names = _git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    untracked = []
    for name in names.decode("utf-8", errors="strict").split("\0"):
        if not name:
            continue
        relative = Path(name)
        path = repo / relative
        if not path.is_file():
            continue
        untracked.append({
            "path": relative.as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    payload = {
        "tracked_binary_diff_sha256": hashlib.sha256(tracked).hexdigest(),
        "untracked_files": sorted(untracked, key=lambda item: item["path"]),
    }
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8"),
        payload["untracked_files"],
    )


def capture_code_state(repo_root: str | Path, config_path: str | Path) -> dict:
    """Capture a deterministic identity for a Git checkout and exact config bytes."""
    repo = Path(repo_root).resolve()
    config = Path(config_path).resolve()
    if not config.is_file():
        raise ValueError(f"run config is missing: {config}")
    git_head = _git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    material, untracked = _working_tree_material(repo)
    working_tree_diff_sha256 = hashlib.sha256(material).hexdigest()
    git_dirty = bool(_git(repo, "status", "--porcelain=v1"))
    config_sha256 = hashlib.sha256(config.read_bytes()).hexdigest()
    identity = {
        "git_head": git_head,
        "git_dirty": git_dirty,
        "working_tree_diff_sha256": working_tree_diff_sha256,
        "config_sha256": config_sha256,
    }
    return {
        **identity,
        "code_state_id": hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "untracked_files": untracked,
    }
