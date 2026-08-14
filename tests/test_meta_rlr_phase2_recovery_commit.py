from pathlib import Path
from types import SimpleNamespace
from rlr_maintenance.host import MetaRLRHost, _turn_instance_id
from rlr_maintenance.observer import observe_contract_failure

class L:
    def __init__(self): self.calls=[]
    def todo_complete(self,**k): self.calls.append(("complete",k)); return {"ok":True}
    def refresh_state(self,**k): self.calls.append(("refresh",k)); return {"ok":True,"idempotent_replay":True}
    def quota_spend_slot(self,**k): self.calls.append(("spend",k)); return {"ok":True,"idempotent_replay":True}
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
    control=tmp_path/"control"
    result=MetaRLRHost(loopx=lx,codex=C(),workspace=W(tmp_path,e["event_id"]),verifier=v,loopx_cwd=control).run_once(event=e,goal_id="g",agent_id="a")
    expected_turn=_turn_instance_id(e["event_id"],"todo_event")
    assert result.outcome=="recovered"
    assert result.commit_sha=="b"*40
    assert [n for n,_ in lx.calls]==["complete","refresh","spend"]
    assert all(k["turn_instance_id"]==expected_turn for _,k in lx.calls)
    assert lx.calls[1][1]["delivery_outcome"]=="outcome_progress"
    assert lx.calls[1][1]["delivery_workspace_path"]==tmp_path
    assert lx.calls[1][1]["project"]==control
