from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .codex_cli import CodexError
from .contracts import validate_maintenance_event
from .profiles import profile_for_event
from .verification import run_profile
from .workspace import GitWorkspaceError


class MetaRLRHostError(RuntimeError):
    pass


@dataclass(frozen=True)
class MetaRLRTurnResult:
    outcome: str
    event_id: str
    todo_id: str | None
    profile_id: str
    commit_sha: str | None = None
    reason: str | None = None


def _require_ok(packet: Mapping[str, Any], action: str) -> None:
    if packet.get("ok") is not True:
        raise MetaRLRHostError(f"LoopX {action} did not return ok=true")


def _selected_todo(packet: Mapping[str, Any]) -> str | None:
    lane = packet.get("agent_lane_next_action")
    if not isinstance(lane, Mapping):
        return None
    todo_id = lane.get("todo_id")
    return todo_id if isinstance(todo_id, str) and todo_id else None


def _turn_instance_id(event_id: str, todo_id: str) -> str:
    todo_hash = hashlib.sha256(todo_id.encode("utf-8")).hexdigest()[:16]
    return f"meta-rlr:{event_id}:{todo_hash}"


def _todo_text(event: Mapping[str, Any]) -> str:
    return f"Repair RLR failure {event['dedup_fingerprint'][:12]}: {event['component']} violates {event['expected_contract']}"


def _repair_prompt(event: Mapping[str, Any], profile: object, todo_id: str) -> str:
    payload = {
        "objective": "Repair exactly one Meta-RLR software maintenance todo.",
        "todo_id": todo_id,
        "event": {
            "event_id": event["event_id"],
            "component": event["component"],
            "expected_contract": event["expected_contract"],
            "rlr_revision": event["rlr_revision"],
            "observed": event["observed"],
        },
        "verification_profile": getattr(profile, "profile_id"),
        "forbidden_success_shortcuts": list(getattr(profile, "forbidden_success_shortcuts")),
        "worker_boundary": [
            "Edit only the bounded root-cause repair.",
            "Obey AGENTS.md and existing canonical authorities.",
            "Do not commit, push, merge, modify LoopX state, weaken tests, or change scientific policy.",
            "Do not treat your own completion text as verification.",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


class MetaRLRHost:
    def __init__(self, *, loopx: object, codex: object, workspace: object, verifier: Callable[[str, str | Path], object] = run_profile, loopx_cwd: str | Path | None = None, capabilities: Sequence[str] = ("shell",)) -> None:
        self._loopx = loopx
        self._codex = codex
        self._workspace = workspace
        self._verifier = verifier
        self._loopx_cwd = Path(loopx_cwd) if loopx_cwd is not None else None
        self._capabilities = tuple(str(x) for x in capabilities)

    def _block(self, *, event: Mapping[str, Any], profile_id: str, goal_id: str, agent_id: str, todo_id: str, reason: str) -> MetaRLRTurnResult:
        packet = self._loopx.todo_update(
            goal_id=goal_id,
            todo_id=todo_id,
            agent_id=agent_id,
            status="blocked",
            evidence=f"profile={profile_id} passed=false reason={reason}",
            reason=reason.replace("_", " "),
            cwd=self._loopx_cwd,
        )
        _require_ok(packet, "todo update")
        return MetaRLRTurnResult(outcome="blocked", event_id=event["event_id"], todo_id=todo_id, profile_id=profile_id, reason=reason)

    def run_once(self, *, event: Mapping[str, Any], goal_id: str, agent_id: str) -> MetaRLRTurnResult:
        normalized = validate_maintenance_event(event)
        profile = profile_for_event(normalized)
        added = self._loopx.todo_add_agent(
            goal_id=goal_id,
            text=_todo_text(normalized),
            task_class="advancement_task",
            action_kind="repair",
            cwd=self._loopx_cwd,
        )
        _require_ok(added, "todo add")
        todo_id = added.get("todo_id")
        if not isinstance(todo_id, str) or not todo_id:
            raise MetaRLRHostError("LoopX todo add did not return a todo_id")
        turn_id = _turn_instance_id(normalized["event_id"], todo_id)
        quota = self._loopx.quota_should_run(
            goal_id=goal_id,
            agent_id=agent_id,
            capabilities=self._capabilities,
            turn_instance_id=turn_id,
            cwd=self._loopx_cwd,
        )
        _require_ok(quota, "quota should-run")
        if quota.get("should_run") is not True:
            return MetaRLRTurnResult(outcome="noop", event_id=normalized["event_id"], todo_id=todo_id, profile_id=profile.profile_id, reason=str(quota.get("state") or "quota_no_run"))
        if _selected_todo(quota) != todo_id:
            return MetaRLRTurnResult(outcome="deferred", event_id=normalized["event_id"], todo_id=todo_id, profile_id=profile.profile_id, reason="different_frontier_todo")
        claimed = self._loopx.todo_claim(goal_id=goal_id, todo_id=todo_id, agent_id=agent_id, cwd=self._loopx_cwd)
        _require_ok(claimed, "todo claim")
        try:
            work = self._workspace.create(base_revision=normalized["rlr_revision"], event_token=normalized["dedup_fingerprint"][:12], todo_id=todo_id)
        except GitWorkspaceError:
            return self._block(event=normalized, profile_id=profile.profile_id, goal_id=goal_id, agent_id=agent_id, todo_id=todo_id, reason="workspace_failed")
        try:
            worker = self._codex.run_repair(worktree=work.path, prompt=_repair_prompt(normalized, profile, todo_id))
        except CodexError:
            return self._block(event=normalized, profile_id=profile.profile_id, goal_id=goal_id, agent_id=agent_id, todo_id=todo_id, reason="codex_failed")
        if getattr(worker, "status", None) != "changed":
            return self._block(event=normalized, profile_id=profile.profile_id, goal_id=goal_id, agent_id=agent_id, todo_id=todo_id, reason="no_verified_change")
        before = self._workspace.inspect(work)
        if before.head_sha != work.base_sha:
            return self._block(event=normalized, profile_id=profile.profile_id, goal_id=goal_id, agent_id=agent_id, todo_id=todo_id, reason="worker_changed_head")
        if not before.changed_paths:
            return self._block(event=normalized, profile_id=profile.profile_id, goal_id=goal_id, agent_id=agent_id, todo_id=todo_id, reason="empty_diff")
        receipt = self._verifier(profile.profile_id, work.path)
        if getattr(receipt, "passed", False) is not True:
            return self._block(event=normalized, profile_id=profile.profile_id, goal_id=goal_id, agent_id=agent_id, todo_id=todo_id, reason="verification_failed")
        after = self._workspace.inspect(work)
        if after.head_sha != work.base_sha or after.changed_paths != before.changed_paths:
            return self._block(event=normalized, profile_id=profile.profile_id, goal_id=goal_id, agent_id=agent_id, todo_id=todo_id, reason="post_verification_diff_changed")
        try:
            commit_sha = self._workspace.commit_verified(
                work,
                changed_paths=after.changed_paths,
                message=f"fix: repair {normalized['component']} contract",
            )
        except GitWorkspaceError:
            return self._block(event=normalized, profile_id=profile.profile_id, goal_id=goal_id, agent_id=agent_id, todo_id=todo_id, reason="verified_commit_failed")
        evidence = f"profile={profile.profile_id} passed=true commit={commit_sha} event={normalized['event_id']}"
        completed = self._loopx.todo_complete(
            goal_id=goal_id,
            todo_id=todo_id,
            agent_id=agent_id,
            evidence=evidence,
            note="bounded repair independently verified and committed",
            no_follow_up=True,
            cwd=self._loopx_cwd,
        )
        _require_ok(completed, "todo complete")
        refreshed = self._loopx.refresh_state(goal_id=goal_id, agent_id=agent_id, cwd=self._loopx_cwd)
        _require_ok(refreshed, "refresh-state")
        spent = self._loopx.quota_spend_slot(
            goal_id=goal_id,
            todo_id=todo_id,
            agent_id=agent_id,
            capabilities=self._capabilities,
            turn_instance_id=turn_id,
            cwd=self._loopx_cwd,
        )
        _require_ok(spent, "quota spend-slot")
        return MetaRLRTurnResult(outcome="verified", event_id=normalized["event_id"], todo_id=todo_id, profile_id=profile.profile_id, commit_sha=commit_sha)
