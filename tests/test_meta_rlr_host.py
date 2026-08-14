from pathlib import Path
from types import SimpleNamespace

from rlr_maintenance.host import MetaRLRHost, MetaRLRHostError
from rlr_maintenance.observer import observe_contract_failure


def event():
    return observe_contract_failure(component="l0_restore", error_code="L0_STATE_HASH_MISMATCH", expected_contract="l0_restore_fail_closed", rlr_revision="a" * 40, observed_at="2026-08-13T22:00:00+08:00")


class LoopXFake:
    def __init__(self, should_run=True, selected="todo_event", refresh_ok=True):
        self.should_run = should_run
        self.selected = selected
        self.refresh_ok = refresh_ok
        self.calls = []
    def todo_add_agent(self, **kwargs):
        self.calls.append(("add", kwargs)); return {"ok": True, "todo_id": "todo_event"}
    def quota_should_run(self, **kwargs):
        self.calls.append(("quota", kwargs)); return {"ok": True, "should_run": self.should_run, "agent_lane_next_action": {"todo_id": self.selected}}
    def todo_claim(self, **kwargs):
        self.calls.append(("claim", kwargs)); return {"ok": True}
    def todo_update(self, **kwargs):
        self.calls.append(("update", kwargs)); return {"ok": True}
    def todo_complete(self, **kwargs):
        self.calls.append(("complete", kwargs)); return {"ok": True}
    def refresh_state(self, **kwargs):
        self.calls.append(("refresh", kwargs)); return {"ok": self.refresh_ok}
    def quota_spend_slot(self, **kwargs):
        self.calls.append(("spend", kwargs)); return {"ok": True}


class WorkspaceFake:
    def __init__(self, root): self.root, self.calls = Path(root), []
    def find_existing(self, **kwargs):
        self.calls.append(("find", kwargs)); return None
    def create(self, **kwargs):
        self.calls.append(("create", kwargs)); return SimpleNamespace(path=self.root, base_sha=kwargs["base_revision"], branch="meta-rlr/test", repair_key=kwargs["event_token"])
    def inspect(self, work):
        self.calls.append(("inspect", {})); return SimpleNamespace(base_sha=work.base_sha, head_sha=work.base_sha, changed_paths=("src/x.py",))
    def commit_verified(self, work, *, changed_paths, message, event_id, todo_id, turn_instance_id, profile_id):
        self.calls.append(("commit", {"changed_paths": tuple(changed_paths), "message": message, "event_id": event_id, "todo_id": todo_id, "turn_instance_id": turn_instance_id, "profile_id": profile_id}))
        return "b" * 40


class CodexFake:
    def __init__(self): self.calls = []
    def run_repair(self, **kwargs):
        self.calls.append(kwargs); return SimpleNamespace(status="changed", summary="bounded repair", tests_requested=(), blocker=None)


def verifier(passed=True):
    calls = []
    def run(profile_id, repo_root):
        calls.append((profile_id, Path(repo_root))); return SimpleNamespace(profile_id=profile_id, passed=passed, steps=())
    run.calls = calls
    return run


def test_no_run_stops_before_claim_and_model(tmp_path):
    loopx, codex = LoopXFake(should_run=False), CodexFake()
    check = verifier()
    workspace = WorkspaceFake(tmp_path)
    result = MetaRLRHost(loopx=loopx, codex=codex, workspace=workspace, verifier=check).run_once(event=event(), goal_id="g", agent_id="a")
    assert result.outcome == "noop"
    assert [name for name, _ in loopx.calls] == ["add", "quota"]
    assert [name for name, _ in workspace.calls] == ["find"]
    assert codex.calls == [] and check.calls == []


def test_success_commits_verified_diff_before_loopx_completion(tmp_path):
    loopx, workspace, codex, check = LoopXFake(), WorkspaceFake(tmp_path), CodexFake(), verifier(True)
    result = MetaRLRHost(loopx=loopx, codex=codex, workspace=workspace, verifier=check, loopx_cwd=tmp_path / "control").run_once(event=event(), goal_id="g", agent_id="a")
    assert result.outcome == "verified"
    assert result.commit_sha == "b" * 40
    assert [name for name, _ in loopx.calls] == ["add", "quota", "quota", "claim", "complete", "refresh", "spend"]
    assert [name for name, _ in workspace.calls] == ["find", "create", "inspect", "inspect", "commit"]
    assert workspace.calls[1][1]["base_revision"] == "a" * 40
    assert workspace.calls[-1][1]["changed_paths"] == ("src/x.py",)
    assert workspace.calls[-1][1]["event_id"] == event()["event_id"]
    assert workspace.calls[-1][1]["todo_id"] == "todo_event"
    assert workspace.calls[-1][1]["profile_id"] == "l0_state_integrity"
    assert check.calls == [("l0_state_integrity", tmp_path)]
    assert ("commit=" + "b" * 40) in loopx.calls[4][1]["evidence"]
    turn_id = loopx.calls[2][1]["turn_instance_id"]
    assert loopx.calls[4][1]["turn_instance_id"] == turn_id
    assert loopx.calls[5][1]["turn_instance_id"] == turn_id
    assert loopx.calls[6][1]["turn_instance_id"] == turn_id
    assert loopx.calls[5][1]["delivery_outcome"] == "outcome_progress"
    assert loopx.calls[5][1]["delivery_workspace_path"] == tmp_path
    assert "project" not in loopx.calls[5][1]
    assert workspace.calls[-1][1]["turn_instance_id"] == turn_id
    assert loopx.calls[1][1].get("turn_instance_id") is None


def test_failed_verification_blocks_without_commit_complete_refresh_or_spend(tmp_path):
    loopx, workspace = LoopXFake(), WorkspaceFake(tmp_path)
    result = MetaRLRHost(loopx=loopx, codex=CodexFake(), workspace=workspace, verifier=verifier(False)).run_once(event=event(), goal_id="g", agent_id="a")
    assert result.outcome == "blocked"
    assert [name for name, _ in loopx.calls] == ["add", "quota", "quota", "claim", "update"]
    assert [name for name, _ in workspace.calls] == ["find", "create", "inspect"]
    assert loopx.calls[-1][1]["status"] == "blocked"


def test_refresh_failure_prevents_quota_spend(tmp_path):
    loopx, workspace = LoopXFake(refresh_ok=False), WorkspaceFake(tmp_path)
    try:
        MetaRLRHost(loopx=loopx, codex=CodexFake(), workspace=workspace, verifier=verifier(True), loopx_cwd=tmp_path / "control").run_once(event=event(), goal_id="g", agent_id="a")
    except MetaRLRHostError:
        pass
    else:
        raise AssertionError("refresh failure must fail closed")
    assert [name for name, _ in loopx.calls][-2:] == ["complete", "refresh"]
    assert all(name != "spend" for name, _ in loopx.calls)


def test_different_frontier_todo_defers(tmp_path):
    loopx, codex = LoopXFake(selected="todo_other"), CodexFake()
    workspace = WorkspaceFake(tmp_path)
    result = MetaRLRHost(loopx=loopx, codex=codex, workspace=workspace, verifier=verifier()).run_once(event=event(), goal_id="g", agent_id="a")
    assert result.outcome == "deferred"
    assert [name for name, _ in loopx.calls] == ["add", "quota"]
    assert [name for name, _ in workspace.calls] == ["find"]
    assert codex.calls == []
