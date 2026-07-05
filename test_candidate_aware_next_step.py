# -*- coding: utf-8 -*-
"""Focused regression tests for candidate-aware delta completion."""
import hashlib
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import research_loop_v04 as rl


def _candidate(project, cand_id="CNEW", status="IDEA_PROPOSED"):
    d = project / "01_Candidates"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cand_id}.md").write_text(
        f"---\ncandidate_id: {cand_id}\ncurrent_status: {status}\n---\n",
        encoding="utf-8")


def _delta(project, persona, name, data=None):
    p = project / "02_Agent_Notes" / persona / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data or {}), encoding="utf-8")
    return p


def _next_step(project, cand_id="CNEW"):
    out = io.StringIO()
    with redirect_stdout(out):
        rc = rl.main(["next-step", str(project), cand_id])
    assert rc == 0
    return json.loads(out.getvalue())


def test_anonymous_legacy_deltas_do_not_complete_new_candidate_nodes():
    with tempfile.TemporaryDirectory() as d:
        project = Path(d)
        _candidate(project)
        _delta(project, "Einstein", "L1_einstein_delta.json")
        _delta(project, "Feynman", "L2_feynman_delta.json")
        assert _next_step(project)["node"] == "L1"


def test_matching_receipt_counts_current_delta_for_candidate():
    with tempfile.TemporaryDirectory() as d:
        project = Path(d)
        _candidate(project)
        l1 = _delta(project, "Einstein", "L1_einstein_delta.json")
        _delta(project, "Feynman", "L2_feynman_delta.json")
        audit = project / "08_Audit"
        audit.mkdir()
        receipt = {
            "candidate_id": "CNEW",
            "node": "L1",
            "delta_key": "L1_einstein",
            "output_delta_sha256": hashlib.sha256(l1.read_bytes()).hexdigest(),
        }
        (audit / "run_receipt_L1_1.json").write_text(
            json.dumps(receipt), encoding="utf-8")
        assert _next_step(project)["node"] == "L2"


def test_emit_delta_embeds_candidate_id():
    with tempfile.TemporaryDirectory() as d:
        project = Path(d)
        _candidate(project)
        src = project / "l3.json"
        src.write_text(json.dumps({
            "selected": ["H1"], "rejected": [],
            "reason": "test", "route_to": "Fisher",
        }), encoding="utf-8")
        rc = rl.main([
            "emit-delta", str(project), "CNEW", "--node", "L3",
            "--persona", "Oppenheimer", "--file", str(src),
        ])
        assert rc == 0
        emitted = json.loads((project / "02_Agent_Notes" / "Oppenheimer" /
                              "L3_oppenheimer_delta.json").read_text(encoding="utf-8"))
        assert emitted["candidate_id"] == "CNEW"


def _run_as_script():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_as_script())
