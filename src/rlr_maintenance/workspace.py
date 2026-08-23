from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence

from .bounded_process import DEFAULT_MAX_OUTPUT_BYTES, run_bounded_process
from .verification import VERIFICATION_RECEIPT_FILENAME


GIT_COMMAND_TIMEOUT = 60.0


class GitWorkspaceError(RuntimeError):
    pass


_LOOPX_TODO_ID_PATTERN = re.compile(r"^todo_[a-z0-9_-]{3,64}$")


@dataclass(frozen=True)
class RepairWorkspace:
    path: Path
    branch: str
    base_sha: str
    repair_key: str | None = None


@dataclass(frozen=True)
class WorkspaceInspection:
    base_sha: str
    head_sha: str
    changed_paths: tuple[str, ...]
    dirty_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerifiedRepairCommit:
    commit_sha: str
    base_sha: str
    changed_paths: tuple[str, ...]
    repair_key: str
    event_id: str
    todo_id: str
    turn_instance_id: str
    profile_id: str


class GitWorkspace:
    def __init__(
        self,
        *,
        repo_root: str | Path,
        workspace_parent: str | Path,
        runner: Callable[..., object] | None = None,
        timeout: float = GIT_COMMAND_TIMEOUT,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.workspace_parent = Path(workspace_parent).resolve()
        self._runner = runner
        self._timeout = float(timeout)
        self._max_output_bytes = int(max_output_bytes)

    def _run(self, cwd: Path, args: Sequence[str], *, allow_failure: bool = False) -> object:
        if self._runner is None:
            try:
                completed = run_bounded_process(
                    ["git", *args],
                    timeout=self._timeout,
                    cwd=cwd,
                    max_output_bytes=self._max_output_bytes,
                )
            except OSError as exc:
                raise GitWorkspaceError(f"Git command could not be launched: {exc}") from exc
            if completed.terminal_state == "timed_out":
                raise GitWorkspaceError(f"Git command timed out after {self._timeout}s")
            if completed.stdout_truncated:
                raise GitWorkspaceError("Git stdout exceeded the bounded output cap")
        else:
            completed = self._runner(
                ["git", *args],
                cwd=cwd,
                text=True,
                encoding="utf-8",
                capture_output=True,
                shell=False,
            )
        if getattr(completed, "terminal_state", "completed") == "timed_out":
            raise GitWorkspaceError(f"Git command timed out after {self._timeout}s")
        if getattr(completed, "stdout_truncated", False):
            raise GitWorkspaceError("Git stdout exceeded the bounded output cap")
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
    def _without_durable_evidence(paths: Sequence[str]) -> tuple[str, ...]:
        """Keep the verifier receipt durable without treating it as repair code."""
        return tuple(path for path in paths if path != VERIFICATION_RECEIPT_FILENAME)

    @staticmethod
    def _event_part(event_token: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", str(event_token))[:12] or "event"

    @classmethod
    def _identity(cls, event_token: str, todo_id: str) -> tuple[str, str]:
        event_part = cls._event_part(event_token)
        todo_hash = hashlib.sha256(str(todo_id).encode("utf-8")).hexdigest()[:12]
        token = f"{event_part}-{todo_hash}"
        return f"meta-rlr/{token}", f"meta-rlr-{token}"

    def _resolve_base(self, base_revision: str) -> str:
        if not self.repo_root.is_dir():
            raise GitWorkspaceError("RLR repository does not exist")
        resolved = self._run(self.repo_root, ["rev-parse", "--verify", f"{base_revision}^{{commit}}"], allow_failure=True)
        if int(getattr(resolved, "returncode")) != 0:
            raise GitWorkspaceError("event revision does not resolve")
        base_sha = self._stdout(resolved)
        if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
            raise GitWorkspaceError("resolved revision is not a full SHA")
        return base_sha

    def create(self, *, base_revision: str, event_token: str, todo_id: str) -> RepairWorkspace:
        base_sha = self._resolve_base(base_revision)
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
        return RepairWorkspace(path=path, branch=branch, base_sha=base_sha, repair_key=self._event_part(event_token))

    def find_existing(self, *, base_revision: str, repair_key: str) -> RepairWorkspace | None:
        base_sha = self._resolve_base(base_revision)
        key = self._event_part(repair_key)
        if not self.workspace_parent.is_dir():
            return None
        candidates = sorted(
            path.resolve()
            for path in self.workspace_parent.glob(f"meta-rlr-{key}-*")
            if path.is_dir()
        )
        if not candidates:
            return None
        if len(candidates) != 1:
            raise GitWorkspaceError("ambiguous repair worktree recovery")
        path = candidates[0]
        branch = self._stdout(self._run(path, ["rev-parse", "--abbrev-ref", "HEAD"]))
        if not branch.startswith(f"meta-rlr/{key}-"):
            raise GitWorkspaceError("repair worktree branch identity mismatch")
        return RepairWorkspace(path=path, branch=branch, base_sha=base_sha, repair_key=key)

    def inspect(self, work: RepairWorkspace) -> WorkspaceInspection:
        head_sha = self._stdout(self._run(work.path, ["rev-parse", "HEAD"]))
        tracked = self._stdout(self._run(work.path, ["diff", "--name-only", work.base_sha]))
        dirty_tracked = self._stdout(self._run(work.path, ["diff", "--name-only", "HEAD"]))
        untracked = self._stdout(self._run(work.path, ["ls-files", "--others", "--exclude-standard"]))
        changed = self._without_durable_evidence(
            self._safe_paths("\n".join(x for x in (tracked, untracked) if x))
        )
        dirty = self._without_durable_evidence(
            self._safe_paths("\n".join(x for x in (dirty_tracked, untracked) if x))
        )
        return WorkspaceInspection(base_sha=work.base_sha, head_sha=head_sha, changed_paths=changed, dirty_paths=dirty)

    @staticmethod
    def _repair_trailers(message: str) -> dict[str, str]:
        keys = {
            "Meta-RLR-Repair-Key": "repair_key",
            "Meta-RLR-Event-ID": "event_id",
            "Meta-RLR-Todo-ID": "todo_id",
            "Meta-RLR-Turn-ID": "turn_instance_id",
            "Meta-RLR-Profile-ID": "profile_id",
        }
        values: dict[str, str] = {}
        for raw in message.splitlines():
            if ":" not in raw:
                continue
            name, value = raw.split(":", 1)
            field = keys.get(name.strip())
            if field is None:
                continue
            if field in values:
                raise GitWorkspaceError("duplicate Meta-RLR repair trailer")
            text = value.strip()
            if not text:
                raise GitWorkspaceError("empty Meta-RLR repair trailer")
            values[field] = text
        missing = sorted(set(keys.values()) - set(values))
        if missing:
            raise GitWorkspaceError("verified repair commit is missing required Meta-RLR trailers")
        return values

    def read_verified_commit(self, work: RepairWorkspace) -> VerifiedRepairCommit:
        if not work.repair_key:
            raise GitWorkspaceError("repair worktree has no recovery key")
        inspection = self.inspect(work)
        if not re.fullmatch(r"[0-9a-f]{40}", inspection.head_sha) or inspection.head_sha == work.base_sha:
            raise GitWorkspaceError("recoverable verified commit is missing")
        if inspection.dirty_paths:
            raise GitWorkspaceError("repair worktree is dirty after verified commit")
        count = self._stdout(self._run(work.path, ["rev-list", "--count", f"{work.base_sha}..{inspection.head_sha}"]))
        if count != "1":
            raise GitWorkspaceError("recovery requires exactly one repair commit")
        parent = self._stdout(self._run(work.path, ["rev-parse", "HEAD^"]))
        if parent != work.base_sha:
            raise GitWorkspaceError("repair commit parent does not match event revision")
        message = self._stdout(self._run(work.path, ["show", "-s", "--format=%B", inspection.head_sha]))
        trailers = self._repair_trailers(message)
        if trailers["repair_key"] != work.repair_key:
            raise GitWorkspaceError("repair commit recovery key mismatch")
        if not re.fullmatch(r"rme-[0-9a-f]{20}", trailers["event_id"]):
            raise GitWorkspaceError("invalid Meta-RLR event id trailer")
        if not _LOOPX_TODO_ID_PATTERN.fullmatch(trailers["todo_id"]):
            raise GitWorkspaceError("invalid LoopX todo id trailer")
        if not re.fullmatch(r"meta-rlr:[!-~]+", trailers["turn_instance_id"]):
            raise GitWorkspaceError("invalid Meta-RLR turn id trailer")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", trailers["profile_id"]):
            raise GitWorkspaceError("invalid verification profile trailer")
        return VerifiedRepairCommit(
            commit_sha=inspection.head_sha,
            base_sha=work.base_sha,
            changed_paths=inspection.changed_paths,
            repair_key=trailers["repair_key"],
            event_id=trailers["event_id"],
            todo_id=trailers["todo_id"],
            turn_instance_id=trailers["turn_instance_id"],
            profile_id=trailers["profile_id"],
        )

    def commit_verified(
        self,
        work: RepairWorkspace,
        *,
        changed_paths: Sequence[str],
        message: str,
        event_id: str,
        todo_id: str,
        turn_instance_id: str,
        profile_id: str,
    ) -> str:
        expected = tuple(sorted(set(str(x) for x in changed_paths)))
        if not expected:
            raise GitWorkspaceError("no verified changed paths")
        if not message.strip() or "\n" in message or len(message) > 200:
            raise ValueError("invalid commit message")
        if not work.repair_key:
            raise GitWorkspaceError("repair worktree has no recovery key")
        binding_text = "\n".join(
            (
                f"Meta-RLR-Repair-Key: {work.repair_key}",
                f"Meta-RLR-Event-ID: {event_id}",
                f"Meta-RLR-Todo-ID: {todo_id}",
                f"Meta-RLR-Turn-ID: {turn_instance_id}",
                f"Meta-RLR-Profile-ID: {profile_id}",
            )
        )
        trailers = self._repair_trailers(binding_text)
        if trailers["event_id"] != event_id or not re.fullmatch(r"rme-[0-9a-f]{20}", event_id):
            raise GitWorkspaceError("invalid Meta-RLR event id")
        if trailers["todo_id"] != todo_id or not _LOOPX_TODO_ID_PATTERN.fullmatch(todo_id):
            raise GitWorkspaceError("invalid LoopX todo id")
        if trailers["turn_instance_id"] != turn_instance_id or not re.fullmatch(r"meta-rlr:[!-~]+", turn_instance_id):
            raise GitWorkspaceError("invalid Meta-RLR turn id")
        if trailers["profile_id"] != profile_id or not re.fullmatch(r"[A-Za-z0-9_.-]+", profile_id):
            raise GitWorkspaceError("invalid verification profile id")
        current = self.inspect(work)
        if current.head_sha != work.base_sha:
            raise GitWorkspaceError("worker changed HEAD")
        if current.changed_paths != expected:
            raise GitWorkspaceError("working tree changed after verification")
        self._run(work.path, ["add", "-A", "--", *expected])
        staged = self._safe_paths(self._stdout(self._run(work.path, ["diff", "--cached", "--name-only"])))
        if staged != expected:
            raise GitWorkspaceError("staged paths differ from verified paths")
        self._run(work.path, ["commit", "-m", message, "-m", binding_text])
        commit_sha = self._stdout(self._run(work.path, ["rev-parse", "HEAD"]))
        if not re.fullmatch(r"[0-9a-f]{40}", commit_sha) or commit_sha == work.base_sha:
            raise GitWorkspaceError("verified commit missing")
        binding = self.read_verified_commit(work)
        if (
            binding.commit_sha != commit_sha
            or binding.changed_paths != expected
            or binding.event_id != event_id
            or binding.todo_id != todo_id
            or binding.turn_instance_id != turn_instance_id
            or binding.profile_id != profile_id
        ):
            raise GitWorkspaceError("verified commit provenance readback mismatch")
        return commit_sha
