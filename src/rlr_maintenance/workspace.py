from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence


class GitWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepairWorkspace:
    path: Path
    branch: str
    base_sha: str


@dataclass(frozen=True)
class WorkspaceInspection:
    base_sha: str
    head_sha: str
    changed_paths: tuple[str, ...]


class GitWorkspace:
    def __init__(self, *, repo_root: str | Path, workspace_parent: str | Path, runner: Callable[..., object] = subprocess.run) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.workspace_parent = Path(workspace_parent).resolve()
        self._runner = runner

    def _run(self, cwd: Path, args: Sequence[str], *, allow_failure: bool = False) -> object:
        completed = self._runner(["git", *args], cwd=cwd, text=True, encoding="utf-8", capture_output=True, shell=False)
        code = int(getattr(completed, "returncode"))
        if code != 0 and not allow_failure:
            raise GitWorkspaceError(f"Git command failed with exit code {code}")
        return completed

    @staticmethod
    def _stdout(completed: object) -> str:
        return str(getattr(completed, "stdout", "") or "").strip()

    @staticmethod
    def _safe_paths(text: str) -> tuple[str, ...]:
        values: set[str] = set()
        for raw in text.splitlines():
            value = raw.strip().replace("\\", "/")
            if not value:
                continue
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts:
                raise GitWorkspaceError("unsafe repository path")
            values.add(value)
        return tuple(sorted(values))

    @staticmethod
    def _identity(event_token: str, todo_id: str) -> tuple[str, str]:
        event_part = re.sub(r"[^A-Za-z0-9]", "", str(event_token))[:12] or "event"
        todo_hash = hashlib.sha256(str(todo_id).encode("utf-8")).hexdigest()[:12]
        token = f"{event_part}-{todo_hash}"
        return f"meta-rlr/{token}", f"meta-rlr-{token}"

    def create(self, *, base_revision: str, event_token: str, todo_id: str) -> RepairWorkspace:
        if not self.repo_root.is_dir():
            raise GitWorkspaceError("RLR repository does not exist")
        resolved = self._run(self.repo_root, ["rev-parse", "--verify", f"{base_revision}^{{commit}}"], allow_failure=True)
        if int(getattr(resolved, "returncode")) != 0:
            raise GitWorkspaceError("event revision does not resolve")
        base_sha = self._stdout(resolved)
        if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
            raise GitWorkspaceError("resolved revision is not a full SHA")
        branch, dirname = self._identity(event_token, todo_id)
        path = self.workspace_parent / dirname
        if path.exists():
            raise GitWorkspaceError("repair worktree already exists")
        branch_check = self._run(self.repo_root, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], allow_failure=True)
        if int(getattr(branch_check, "returncode")) == 0:
            raise GitWorkspaceError("repair branch already exists")
        self.workspace_parent.mkdir(parents=True, exist_ok=True)
        self._run(self.repo_root, ["worktree", "add", "-b", branch, str(path), base_sha])
        if self._stdout(self._run(path, ["rev-parse", "HEAD"])) != base_sha:
            raise GitWorkspaceError("worktree base mismatch")
        return RepairWorkspace(path=path, branch=branch, base_sha=base_sha)

    def inspect(self, work: RepairWorkspace) -> WorkspaceInspection:
        head_sha = self._stdout(self._run(work.path, ["rev-parse", "HEAD"]))
        tracked = self._stdout(self._run(work.path, ["diff", "--name-only", work.base_sha]))
        untracked = self._stdout(self._run(work.path, ["ls-files", "--others", "--exclude-standard"]))
        changed = self._safe_paths("\n".join(x for x in (tracked, untracked) if x))
        return WorkspaceInspection(base_sha=work.base_sha, head_sha=head_sha, changed_paths=changed)

    def commit_verified(self, work: RepairWorkspace, *, changed_paths: Sequence[str], message: str) -> str:
        expected = tuple(sorted(set(str(x) for x in changed_paths)))
        if not expected:
            raise GitWorkspaceError("no verified changed paths")
        if not message.strip() or "\n" in message or len(message) > 200:
            raise ValueError("invalid commit message")
        current = self.inspect(work)
        if current.head_sha != work.base_sha:
            raise GitWorkspaceError("worker changed HEAD")
        if current.changed_paths != expected:
            raise GitWorkspaceError("working tree changed after verification")
        self._run(work.path, ["add", "-A", "--", *expected])
        staged = self._safe_paths(self._stdout(self._run(work.path, ["diff", "--cached", "--name-only"])))
        if staged != expected:
            raise GitWorkspaceError("staged paths differ from verified paths")
        self._run(work.path, ["commit", "-m", message])
        commit_sha = self._stdout(self._run(work.path, ["rev-parse", "HEAD"]))
        if not re.fullmatch(r"[0-9a-f]{40}", commit_sha) or commit_sha == work.base_sha:
            raise GitWorkspaceError("verified commit missing")
        return commit_sha
