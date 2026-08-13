from pathlib import Path
from types import SimpleNamespace

from rlr_maintenance.host import MetaRLRHost
from rlr_maintenance.observer import observe_contract_failure


def event():
    return observe_contract_failure(component="l0_restore", error_code="L0_STATE_HASH_MISMATCH", expected_contract="l0_restore_fail_closed", rlr_revision="a" * 40, observed_at="2026-08-13T22:00:00+08:00")


class LoopXFake:
    def __init__(self, should_run=True, selected="todo_event"):
        self.should_run = should_run
        self.selected = selected
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
        self.calls.append(("refresh", kwargs)); return {"ok": True}
    def quota_spend_slot(self, **kwargs):
        self.calls.append(("spend", kwargs)); return {"ok": True}


class WorkspaceFake:
    def __init__(self, root): self.root, self.calls = Path(root), []
    def create(self, **kwargs):
        self.calls.append(("create", kwargs)); return SimpleNamespace(path=self.root, base_sha=kwargs["base_revision"], branch="meta-rlr/test")
    def inspect(self, work):
        self.calls.append(("inspect", {})); return SimpleNamespace(base_sha=work.base_sha, head_sha=work.base_sha, changed_paths=("src/x.py",))


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
    result = MetaRLRHost(loopx=loopx, codex=codex, workspace=WorkspaceFake(tmp_path), verifier=check).run_once(event=event(), goal_id="g", agent_id="a")
    assert result.outcome == "noop"
    assert [name for name, _ in loopx.calls] == ["add", "quota"]
    assert codex.calls == [] and check.calls == []


def test_success_order_and_exact_revision(tmp_path):
    loopx, workspace, codex, check = LoopXFake(), WorkspaceFake(tmp_path), CodexFake(), verifier(True)
    result = MetaRLRHost(loopx=loopx, codex=codex, workspace=workspace, verifier=check).run_once(event=event(), goal_id="g", agent_id="a")
    assert result.outcome == "verified"
    assert [name for name, _ in loopx.calls] == ["add", "quota", "claim", "complete", "refresh", "spend"]
    assert workspace.calls[0][1]["base_revision"] == "a" * 40
    assert check.calls == [("l0_state_integrity", tmp_path)]


def test_failed_verification_blocks_without_complete_or_spend(tmp_path):
    loopx = LoopXFake()
    result = MetaRLRHost(loopx=loopx, codex=CodexFake(), workspace=WorkspaceFake(tmp_path), verifier=verifier(False)).run_once(event=event(), goal_id="g", agent_id="a")
    assert result.outcome == "blocked"
    assert [name for name, _ in loopx.calls] == ["add", "quota", "claim", "update"]
    assert loopx.calls[-1][1]["status"] == "blocked"


def test_different_frontier_todo_defers(tmp_path):
    loopx, codex = LoopXFake(selected="todo_other"), CodexFake()
    result = MetaRLRHost(loopx=loopx, codex=codex, workspace=WorkspaceFake(tmp_path), verifier=verifier()).run_once(event=event(), goal_id="g", agent_id="a")
    assert result.outcome == "deferred"
    assert [name for name, _ in loopx.calls] == ["add", "quota"]
    assert codex.calls == []
