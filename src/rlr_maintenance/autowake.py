"""Thin Phase 3 bridge from observed RLR runtime failure to Phase 2 Meta-RLR.

This module owns no scheduler and no repair logic. It converts an already
classified provider-runtime failure into the canonical maintenance event,
invokes the existing ``meta_rlr.py run-once`` entry point, and resolves the
verified repair through the existing GitWorkspace provenance authority.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, MutableMapping

from .bounded_process import DEFAULT_MAX_OUTPUT_BYTES, run_bounded_process
from .codex_cli import DEFAULT_REPAIR_JOB_TIMEOUT
from .contracts import validate_maintenance_event
from .observer import observe_provider_runtime_failure
from .verification import VERIFICATION_COMMAND_TIMEOUT
from .workspace import GIT_COMMAND_TIMEOUT, GitWorkspace, GitWorkspaceError


AUTOWAKE_CONFIG_ENV = "RLR_META_RLR_AUTOWAKE_CONFIG"
AUTOWAKE_RETRY_GUARD_ENV = "RLR_META_RLR_AUTOWAKE_RETRY"
AUTOWAKE_CONFIG_SCHEMA = "RLRMetaAutoWakeConfig/v1"
PROVIDER_RUNTIME_CONTRACT = "provider_runtime_execution_integrity"
PROVIDER_RUNTIME_PROFILE = "provider_runtime_integrity"
OUTER_SAFETY_MARGIN = 300.0
# OUTER_SAFETY_MARGIN is outer slack, not a separately consumable inner
# settlement/orchestration budget. The two known hard inner budgets are the
# Codex repair maximum and the profile-wide verification maximum. The 300s
# margin covers all short bounded LoopX/Git/bootstrap operations and
# orchestration overhead between/after those budgets. The outer boundary only
# prevents infinite orchestration; Codex activity/inactivity semantics remain
# owned by the inner observer.
AUTOWAKE_OUTER_TIMEOUT = (
    DEFAULT_REPAIR_JOB_TIMEOUT
    + VERIFICATION_COMMAND_TIMEOUT
    + OUTER_SAFETY_MARGIN
)
REPAIRABLE_PROVIDER_STATES = frozenset(
    {
        "provider_failed",
        "provider_dead",
        "transport_lost",
        "job_timed_out",
        "inactivity_timed_out",
    }
)
_REPAIRABLE_TERMINATION_REASONS = frozenset(
    {
        "provider_exit_nonzero",
        "provider_exited_without_final_output",
        "job_timeout",
        "inactivity_timeout",
    }
)


class AutoWakeConfigError(ValueError):
    """Raised when explicit Phase 3 runtime configuration is malformed."""


@dataclass(frozen=True)
class RepairHandoff:
    outcome: str
    event_id: str
    event_path: Path
    commit_sha: str
    worktree_path: Path


@dataclass(frozen=True)
class _AutoWakeConfig:
    loopx_project: Path
    goal_id: str
    agent_id: str
    workspace_parent: Path
    registry: Path | None
    loopx_executable: str
    quota_runtime_profile: str
    quota_scan_root: Path
    codex_executable: str
    capabilities: tuple[str, ...]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_config(path: Path) -> _AutoWakeConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutoWakeConfigError(f"cannot read auto-wakeup config: {exc}") from exc
    if not isinstance(raw, Mapping) or raw.get("schema_version") != AUTOWAKE_CONFIG_SCHEMA:
        raise AutoWakeConfigError("invalid auto-wakeup config schema")

    required_text = (
        "loopx_project",
        "goal_id",
        "agent_id",
        "workspace_parent",
        "loopx_executable",
        "quota_runtime_profile",
        "quota_scan_root",
        "codex_executable",
    )
    values: dict[str, str] = {}
    for key in required_text:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise AutoWakeConfigError(f"auto-wakeup config requires non-empty {key}")
        values[key] = value

    registry_value = raw.get("registry")
    if registry_value is not None and (
        not isinstance(registry_value, str) or not registry_value.strip()
    ):
        raise AutoWakeConfigError("auto-wakeup registry must be a non-empty path when set")
    raw_capabilities = raw.get("capabilities", ["shell"])
    if (
        not isinstance(raw_capabilities, list)
        or not raw_capabilities
        or any(not isinstance(item, str) or not item for item in raw_capabilities)
    ):
        raise AutoWakeConfigError("auto-wakeup capabilities must be a non-empty string list")

    return _AutoWakeConfig(
        loopx_project=Path(values["loopx_project"]),
        goal_id=values["goal_id"],
        agent_id=values["agent_id"],
        workspace_parent=Path(values["workspace_parent"]),
        registry=Path(registry_value) if registry_value else None,
        loopx_executable=values["loopx_executable"],
        quota_runtime_profile=values["quota_runtime_profile"],
        quota_scan_root=Path(values["quota_scan_root"]),
        codex_executable=values["codex_executable"],
        capabilities=tuple(raw_capabilities),
    )


def _run_git(repo_root: Path, runner, *args: str):
    if runner is None:
        return run_bounded_process(
            ["git", *args],
            timeout=GIT_COMMAND_TIMEOUT,
            cwd=repo_root,
            max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES,
        )
    return runner(
        ["git", *args],
        cwd=repo_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        shell=False,
    )


def _current_revision(repo_root: Path, runner) -> str:
    status = _run_git(repo_root, runner, "status", "--porcelain")
    if int(getattr(status, "returncode", 1)) != 0:
        raise RuntimeError("cannot inspect failing RLR checkout")
    if str(getattr(status, "stdout", "") or "").strip():
        raise RuntimeError("automatic repair requires a clean RLR code checkout")

    completed = _run_git(repo_root, runner, "rev-parse", "HEAD")
    if int(getattr(completed, "returncode", 1)) != 0:
        raise RuntimeError("cannot resolve failing RLR revision")
    revision = str(getattr(completed, "stdout", "")).strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise RuntimeError("failing RLR revision is not a full commit SHA")
    return revision


def _write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _existing_event(event_dir: Path, dedup_fingerprint: str) -> tuple[dict, Path] | None:
    if not event_dir.is_dir():
        return None
    for path in sorted(event_dir.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            event = validate_maintenance_event(value)
        except Exception:
            continue
        if event.get("dedup_fingerprint") == dedup_fingerprint:
            return event, path
    return None


def _provider_failure_is_repairable(status: Mapping[str, object]) -> bool:
    state = str(status.get("state") or "")
    if state not in REPAIRABLE_PROVIDER_STATES:
        return False
    if state != "provider_failed":
        return True
    reason = str(status.get("termination_reason") or "")
    return reason in _REPAIRABLE_TERMINATION_REASONS or reason.startswith("launch_failed:")


def _event_for_failure(
    *,
    project_dir: Path,
    task_id: str,
    handler_args: Mapping[str, object],
    returncode: int,
    status: Mapping[str, object],
    revision: str,
) -> dict:
    node = str(handler_args.get("node") or "unknown")
    candidate = handler_args.get("cand_id")
    event = observe_provider_runtime_failure(
        component=f"deep_research_provider:{node}",
        task_id=task_id,
        provider_state=str(status.get("state") or "unknown"),
        termination_reason=str(status.get("termination_reason") or "unknown"),
        worker_exit_code=int(returncode),
        expected_contract=PROVIDER_RUNTIME_CONTRACT,
        rlr_revision=revision,
        observed_at=str(status.get("updated_at") or ""),
        candidate_ref=str(candidate) if isinstance(candidate, str) and candidate else None,
        evidence_refs=(
            {
                "kind": "rlr_artifact",
                "ref": (
                    Path("08_Audit")
                    / "deep_research_runtime"
                    / "tasks"
                    / task_id
                    / "status.json"
                ).as_posix(),
            },
        ),
    )
    existing = _existing_event(
        project_dir / "08_Audit" / "meta_rlr" / "events",
        event["dedup_fingerprint"],
    )
    return existing[0] if existing is not None else event


def _meta_command(
    *,
    repo_root: Path,
    event_path: Path,
    config: _AutoWakeConfig,
) -> list[str]:
    command = [
        sys.executable,
        str(repo_root / "meta_rlr.py"),
        "run-once",
        "--event",
        str(event_path),
        "--repo",
        str(repo_root),
        "--loopx-project",
        str(config.loopx_project),
        "--goal-id",
        config.goal_id,
        "--agent-id",
        config.agent_id,
        "--workspace-parent",
        str(config.workspace_parent),
        "--loopx-executable",
        config.loopx_executable,
        "--quota-runtime-profile",
        config.quota_runtime_profile,
        "--quota-scan-root",
        str(config.quota_scan_root),
        "--codex-executable",
        config.codex_executable,
    ]
    if config.registry is not None:
        command.extend(["--registry", str(config.registry)])
    for capability in config.capabilities:
        command.extend(["--capability", capability])
    return command


def _resolve_verified_worktree(
    *,
    repo_root: Path,
    workspace_parent: Path,
    revision: str,
    event: Mapping[str, object],
    commit_sha: str,
) -> Path | None:
    workspace = GitWorkspace(repo_root=repo_root, workspace_parent=workspace_parent)
    work = workspace.find_existing(
        base_revision=revision,
        repair_key=str(event["dedup_fingerprint"])[:12],
    )
    if work is None:
        return None
    binding = workspace.read_verified_commit(work)
    if (
        binding.commit_sha != commit_sha
        or binding.event_id != event["event_id"]
        or binding.profile_id != PROVIDER_RUNTIME_PROFILE
    ):
        return None
    return work.path


def maybe_wake_meta_rlr(
    *,
    project_dir: str | Path,
    task_id: str,
    handler_args: Mapping[str, object],
    returncode: int,
    status: Mapping[str, object],
    command_runner: Callable[..., object] | None = None,
    environ: MutableMapping[str, str] | None = None,
    timeout: float = AUTOWAKE_OUTER_TIMEOUT,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> RepairHandoff | None:
    """Run one existing Meta-RLR turn for an already-classified runtime failure.

    Any unavailable/invalid maintenance infrastructure leaves the original RLR
    failure unchanged. Only independently verified/recovered Phase 2 outcomes
    are returned as a code-activation handoff.
    """
    environment = os.environ if environ is None else environ
    if environment.get(AUTOWAKE_RETRY_GUARD_ENV):
        return None
    config_token = environment.get(AUTOWAKE_CONFIG_ENV)
    if not config_token or not _provider_failure_is_repairable(status):
        return None

    try:
        config = _load_config(Path(config_token))
        repo_root = _repo_root()
        revision = _current_revision(repo_root, command_runner)
        project_root = Path(project_dir).resolve()
        event = _event_for_failure(
            project_dir=project_root,
            task_id=task_id,
            handler_args=handler_args,
            returncode=returncode,
            status=status,
            revision=revision,
        )
        event_dir = project_root / "08_Audit" / "meta_rlr" / "events"
        existing = _existing_event(event_dir, str(event["dedup_fingerprint"]))
        if existing is not None:
            event, event_path = existing
        else:
            event_path = event_dir / f"{event['event_id']}.json"
            _write_json_atomic(event_path, event)

        # The maintenance process and every verifier/Codex child it launches
        # inherit the guard. That keeps Phase 3 single-shot: verification of a
        # repair may observe failures, but it must never recursively wake a
        # second Meta-RLR turn from inside the first maintenance tree.
        meta_environment = dict(environment)
        meta_environment[AUTOWAKE_RETRY_GUARD_ENV] = "1"
        command = _meta_command(repo_root=repo_root, event_path=event_path, config=config)
        if command_runner is None:
            completed = run_bounded_process(
                command,
                timeout=timeout,
                cwd=repo_root,
                env=meta_environment,
                max_output_bytes=max_output_bytes,
            )
        else:
            completed = command_runner(
                command,
                cwd=repo_root,
                env=meta_environment,
                text=True,
                encoding="utf-8",
                capture_output=True,
                shell=False,
            )
        if getattr(completed, "terminal_state", "completed") == "timed_out":
            return None
        if getattr(completed, "stdout_truncated", False):
            return None
        if int(getattr(completed, "returncode", 1)) != 0:
            return None
        payload = json.loads(str(getattr(completed, "stdout", "") or ""))
        if not isinstance(payload, Mapping) or payload.get("outcome") not in {
            "verified",
            "recovered",
        }:
            return None
        commit_sha = payload.get("commit_sha")
        if not isinstance(commit_sha, str) or len(commit_sha) != 40:
            return None
        worktree = _resolve_verified_worktree(
            repo_root=repo_root,
            workspace_parent=config.workspace_parent,
            revision=revision,
            event=event,
            commit_sha=commit_sha,
        )
        if worktree is None:
            return None
        return RepairHandoff(
            outcome=str(payload["outcome"]),
            event_id=str(event["event_id"]),
            event_path=event_path,
            commit_sha=commit_sha,
            worktree_path=worktree,
        )
    except (
        AutoWakeConfigError,
        GitWorkspaceError,
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None
