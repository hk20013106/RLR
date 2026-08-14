from pathlib import Path
from types import SimpleNamespace
import pytest
from rlr_maintenance.host import MetaRLRHost, _turn_instance_id
from rlr_maintenance.observer import observe_contract_failure

class L:
    def __init__(self): self.calls=[]
    def quota_should_run(self,**k): self.calls.append(("scoped",k)); return {"ok":True,"should_run":True,"agent_lane_next_action":{"todo_id":"todo_event"}}
    def todo_complete(self,**k): self.calls.append(("complete",k)); return {"ok":True}
    def refresh_state(self,**k): self.calls.append(("refresh",k)); return {"ok":True}
    def quota_spend_slot(self,**k): self.calls.append(("spend",k)); return {"ok":True}
class W:
    def __init__(self,p,event_id): self.p=Path(p); self.key=None; self.event_id=event_id
    def find_existing(self,**k): self.key=k["repair_key"]; return SimpleNamespace(path=self.p,base_sha="a"*40,repair_key=self.key)
    def inspect(self,w): return SimpleNamespace(base_sha=w.base_sha,head_sha="b"*40,changed_paths=("src/x.py",),dirty_paths=())
    def read_verified_commit(self,w):
        todo_id="todo_event"
        return SimpleNamespace(commit_sha="b"*40,base_sha=w.base_sha,changed_paths=("src/x.py",),repair_key=self.key,event_id=self.event_id,todo_id=todo_id,turn_instance_id=_turn_instance_id(self.event_id,todo_id),profile_id="l0_state_integrity")
class C:
    def run_repair(self,**k): raise AssertionError("unexpected Codex")

def test_verified_commit_is_reverified_and_settled_without_codex(tmp_path):
    e=observe_contract_failure(component="l0_restore",error_code="L0_STATE_HASH_MISMATCH",expected_contract="l0_restore_fail_closed",rlr_revision="a"*40,observed_at="2026-08-13T22:00:00+08:00")
    lx=L(); v=lambda p,r: SimpleNamespace(passed=True)
    result=MetaRLRHost(loopx=lx,codex=C(),workspace=W(tmp_path,e["event_id"]),verifier=v).run_once(event=e,goal_id="g",agent_id="a")
    expected_turn=_turn_instance_id(e["event_id"],"todo_event")
    assert result.outcome=="recovered"
    assert result.commit_sha=="b"*40
    assert [n for n,_ in lx.calls]==["scoped","complete","refresh","spend"]
    assert lx.calls[0][1]["turn_instance_id"]==lx.calls[1][1]["turn_instance_id"]==lx.calls[2][1]["turn_instance_id"]==lx.calls[3][1]["turn_instance_id"]==expected_turn
    assert lx.calls[1][1]["no_follow_up"] is False
    assert lx.calls[2][1]["delivery_workspace_path"] == tmp_path
    assert lx.calls[3][1]["cwd"] == tmp_path


class CrashWindowLoopX(L):
    def __init__(self, crash_step=None):
        super().__init__()
        self.crash_step = crash_step
        self.crashed = False

    def _record(self, name, kwargs):
        self.calls.append((name, kwargs))
        if self.crash_step == name and not self.crashed:
            self.crashed = True
            raise RuntimeError(f"simulated process crash after {name}")
        return {"ok": True}

    def todo_complete(self, **kwargs): return self._record("complete", kwargs)
    def refresh_state(self, **kwargs): return self._record("refresh", kwargs)
    def quota_spend_slot(self, **kwargs): return self._record("spend", kwargs)


class SettledReplayLoopX(L):
    def __init__(self):
        super().__init__()
        self.guard_calls = 0

    def quota_should_run(self, **kwargs):
        self.guard_calls += 1
        self.calls.append(("scoped", kwargs))
        if self.guard_calls == 1:
            return {"ok": True, "should_run": True, "agent_lane_next_action": {"todo_id": "todo_event"}}
        return {"ok": True, "should_run": True, "decision": "autonomous_replan_required"}


def test_recovery_replay_allows_loopx_owned_settled_frontier(tmp_path):
    e=observe_contract_failure(component="l0_restore",error_code="L0_STATE_HASH_MISMATCH",expected_contract="l0_restore_fail_closed",rlr_revision="a"*40,observed_at="2026-08-13T22:00:00+08:00")
    lx=SettledReplayLoopX()
    host=MetaRLRHost(loopx=lx,codex=C(),workspace=W(tmp_path,e["event_id"]),verifier=lambda p,r: SimpleNamespace(passed=True))
    assert host.run_once(event=e,goal_id="g",agent_id="a").outcome == "recovered"
    assert host.run_once(event=e,goal_id="g",agent_id="a").outcome == "recovered"


@pytest.mark.parametrize(
    "crash_step,attempt_count",
    [
        (None, 1),
        ("refresh", 2),
        ("spend", 2),
        (None, 2),
    ],
    ids=["before_complete", "after_complete", "after_refresh", "after_spend"],
)
def test_recovery_reuses_same_turn_across_all_settlement_crash_windows(tmp_path, crash_step, attempt_count):
    e=observe_contract_failure(component="l0_restore",error_code="L0_STATE_HASH_MISMATCH",expected_contract="l0_restore_fail_closed",rlr_revision="a"*40,observed_at="2026-08-13T22:00:00+08:00")
    lx=CrashWindowLoopX(crash_step=crash_step)
    workspace=W(tmp_path,e["event_id"])
    host=MetaRLRHost(loopx=lx,codex=C(),workspace=workspace,verifier=lambda p,r: SimpleNamespace(passed=True))

    if crash_step is not None:
        with pytest.raises(RuntimeError, match="simulated process crash"):
            host.run_once(event=e,goal_id="g",agent_id="a")
    for _ in range(attempt_count - 1 if crash_step is not None else attempt_count):
        result=host.run_once(event=e,goal_id="g",agent_id="a")
        assert result.outcome=="recovered"

    expected_turn=_turn_instance_id(e["event_id"],"todo_event")
    assert all(kwargs["turn_instance_id"] == expected_turn for _, kwargs in lx.calls)
    assert all(kwargs.get("delivery_workspace_path", tmp_path) == tmp_path for name, kwargs in lx.calls if name == "refresh")
    assert all(kwargs["cwd"] == tmp_path for name, kwargs in lx.calls if name == "spend")
