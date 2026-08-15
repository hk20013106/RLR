"""Thin Phase 3 bridge from observed RLR runtime failure to Phase 2 Meta-RLR.

This module owns no scheduler and no repair logic. It only converts an already
classified provider-runtime failure into the canonical maintenance event,
invokes the existing ``meta_rlr.py run-once`` entry point, and returns a
verified worktree handoff when Phase 2 accepts the repair.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping, Sequence

from .contracts import build_maintenance_event, validate_maintenance_event


AUTOWAKE_CONFIG_ENV = "RLR_META_RLR_AUTOWAKE_CONFIG"
AUTOWAKE_RETRY_GUARD_ENV = "RLR_META_RLR_AUTOWAKE_RETRY"
AUTOWAKE_CONFIG_SCHEMA = "RLRMetaAutoWakeConfig/v1"
PROVIDER_RUNTIME_CONTRACT = "provider_runtime_execution_integrity"
REPAIRABLE_PROVIDER_STATES = frozenset(
    {
        "provider_failed",
        "provider_dead",
        "transport_lost",
        "job_timed_out",
        "inactivity_timed_out",
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


def _current_revision(repo_root: Path, runner) -> str:
    completed = runner(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        shell=False,
    )
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
    observed_at = str(status.get("updated_at") or "")
    event = build_maintenance_event(
        event_type="runtime_failure",
        component=f"deep_research_provider:{node}",
        severity="blocking",
        observed_at=observed_at,
        rlr_revision=revision,
        observed={
            "task_id": task_id,
            "provider_state": str(status.get("state") or "unknown"),
            "worker_exit_code": int(returncode),
        },
        expected_contract=PROVIDER_RUNTIME_CONTRACT,
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
        suggested_route="repair",
        candidate_ref=str(candidate) if isinstance(candidate, str) and candidate else None,
    )
    event_dir = project_dir / "08_Audit" / "meta_rlr" / "events"
    existing = _existing_event(event_dir, event["dedup_fingerprint"])
    if existing is not None:
        return existing[0]
    return event


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


def maybe_wake_meta_rlr(
    *,
    project_dir: str | Path,
    task_id: str,
    handler_args: Mapping[str, object],
    returncode: int,
    status: Mapping[str, object],
    command_runner=subprocess.run,
    environ: MutableMapping[str, str] | None = None,
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
    if not config_token:
        return None
    state = str(status.get("state") or "")
    if state not in REPAIRABLE_PROVIDER_STATES:
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
        existing = _existing_event(event_dir, event["dedup_fingerprint"])
        if existing is not None:
            event, event_path = existing
        else:
            event_path = event_dir / f"{event['event_id']}.json"
            _write_json_atomic(event_path, event)

        completed = command_runner(
            _meta_command(repo_root=repo_root, event_path=event_path, config=config),
            cwd=repo_root,
            text=True,
            encoding="utf-8",
            capture_output=True,
            shell=False,
        )
        if int(getattr(completed, "returncode", 1)) != 0:
            return None
        payload = json.loads(str(getattr(completed, "stdout", "") or ""))
        if not isinstance(payload, Mapping) or payload.get("outcome") not in {
            "verified",
            "recovered",
        }:
            return None
        commit_sha = payload.get("commit_sha")
        worktree_token = payload.get("worktree_path")
        if (
            not isinstance(commit_sha, str)
            or len(commit_sha) != 40
            or not isinstance(worktree_token, str)
            or not worktree_token
        ):
            return None
        worktree = Path(worktree_token)
        if not worktree.is_dir():
            return None
        return RepairHandoff(
            outcome=str(payload["outcome"]),
            event_id=str(event["event_id"]),
            event_path=event_path,
            commit_sha=commit_sha,
            worktree_path=worktree,
        )
    except (AutoWakeConfigError, OSError, RuntimeError, ValueError, json.JSONDecodeError):
        return None
