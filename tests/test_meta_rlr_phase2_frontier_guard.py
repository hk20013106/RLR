from pathlib import Path
from types import SimpleNamespace
from rlr_maintenance.host import MetaRLRHost
from rlr_maintenance.observer import observe_contract_failure

class L:
    def __init__(self): self.calls=[]
    def todo_add_agent(self, **k): self.calls.append(("add",k)); return {"ok":True,"todo_id":"todo_event"}
    def quota_should_run(self, **k): self.calls.append(("quota",k)); return {"ok":True,"should_run":True,"agent_lane_next_action":{"todo_id":"todo_event"}}
    def todo_claim(self, **k): self.calls.append(("claim",k)); return {"ok":True}
    def todo_complete(self, **k): self.calls.append(("complete",k)); return {"ok":True}
    def refresh_state(self, **k): self.calls.append(("refresh",k)); return {"ok":True}
    def quota_spend_slot(self, **k): self.calls.append(("spend",k)); return {"ok":True}
class W:
    def __init__(self,p): self.p=Path(p)
    def find_existing(self, **k): return None
    def create(self, **k): return SimpleNamespace(path=self.p,base_sha="a"*40,repair_key=k["event_token"])
    def inspect(self,w): return SimpleNamespace(head_sha=w.base_sha,changed_paths=("src/x.py",))
    def commit_verified(self,w,**k): return "b"*40
class C:
    def run_repair(self,**k): return SimpleNamespace(status="changed")

def test_unbound_frontier_precedes_bound_settlement_guard(tmp_path):
    e=observe_contract_failure(component="l0_restore",error_code="L0_STATE_HASH_MISMATCH",expected_contract="l0_restore_fail_closed",rlr_revision="a"*40,observed_at="2026-08-13T22:00:00+08:00")
    lx=L(); v=lambda p,r: SimpleNamespace(passed=True)
    result=MetaRLRHost(loopx=lx,codex=C(),workspace=W(tmp_path),verifier=v).run_once(event=e,goal_id="g",agent_id="a")
    assert result.outcome=="verified"
    q=[k for n,k in lx.calls if n=="quota"]
    assert len(q)==2 and q[0].get("turn_instance_id") is None and q[1].get("turn_instance_id")
    assert [n for n,_ in lx.calls][-3:]==["complete","refresh","spend"]
    assert lx.calls[-3][1]["turn_instance_id"]==lx.calls[-2][1]["turn_instance_id"]==lx.calls[-1][1]["turn_instance_id"]
