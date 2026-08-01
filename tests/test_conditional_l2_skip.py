import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import research_loop_v04 as rl
from native_v2_helpers import activate_native_project, commit_v2
from research_loop.node_skips import l2_skip_decision, validate_l2_skip_receipt


def _project(tmp_path: Path, monkeypatch, hypothesis_count: int):
    store = tmp_path / "ledger.sqlite"
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    project = tmp_path / "P"
    project.mkdir()
    (project / "00_Project_Index.md").write_text(
        "---\nproject_name: P\nkind: project_index\ncreated_at: 2026-08-01T00:00:00Z\n---\n",
        encoding="utf-8",
    )
    candidates = project / "01_Candidates"
    candidates.mkdir()
    (candidates / "C1.md").write_text(
        "---\ncandidate_id: C1\ntitle: T\nquestion: Q\nclaim: C\n"
        "current_status: IDEA_PROPOSED\ncurrent_owner: Einstein\nround_id: 1\n---\n",
        encoding="utf-8",
    )
    activate_native_project(project)
    hypotheses = [
        {
            "proposal_key": f"p{i}",
            "statement": f"Hypothesis {i}",
            "operationalization": f"Measure outcome {i}",
            "falsification_criteria": [f"Outcome {i} absent"],
            "rationale": "Testable alternative.",
        }
        for i in range(1, hypothesis_count + 1)
    ]
    commit_v2(project, "C1", "L1", "Einstein", {
        "schema_version": "2.1",
        "hypotheses": hypotheses,
        "primary_proposal_key": "p1",
        "key_uncertainty": "effect size",
    })
    l1_path = project / "02_Agent_Notes" / "Einstein" / "C1_L1_einstein_delta.v2.json"
    return project, l1_path


def test_l2_skip_decision_has_inclusive_four_hypothesis_threshold():
    assert l2_skip_decision(0) == "invalid"
    for count in (1, 2, 3, 4):
        assert l2_skip_decision(count) == "skip"
    assert l2_skip_decision(5) == "run"


@pytest.mark.parametrize("hypothesis_count", [3, 4])
def test_next_step_routes_small_valid_hypothesis_sets_directly_to_l3(
    tmp_path, monkeypatch, capsys, hypothesis_count
):
    project, l1_path = _project(tmp_path, monkeypatch, hypothesis_count)

    assert rl.main(["next-step", str(project), "C1"]) == 0
    packet = json.loads(capsys.readouterr().out)

    assert packet["node"] == "L3"
    assert packet["skipped_nodes"] == [{
        "node": "L2",
        "reason": "hypothesis_count_lte_4",
        "hypothesis_count": hypothesis_count,
    }]
    receipt = project / "08_Audit" / "node_skips" / "C1_L2.json"
    saved = json.loads(receipt.read_text(encoding="utf-8"))
    assert saved["l1_delta_sha256"] == hashlib.sha256(l1_path.read_bytes()).hexdigest()
    assert saved["threshold"] == 4


def test_next_step_runs_l2_for_five_hypotheses(tmp_path, monkeypatch, capsys):
    project, _ = _project(tmp_path, monkeypatch, 5)

    assert rl.main(["next-step", str(project), "C1"]) == 0
    packet = json.loads(capsys.readouterr().out)

    assert packet["node"] == "L2"
    assert not (project / "08_Audit" / "node_skips" / "C1_L2.json").exists()


def test_l3_context_injects_verified_skip_instead_of_fake_l2_delta(
    tmp_path, monkeypatch, capsys
):
    project, l1_path = _project(tmp_path, monkeypatch, 4)
    assert rl.main(["next-step", str(project), "C1"]) == 0
    capsys.readouterr()

    assert rl.main(["assemble-context", str(project), "C1", "--node", "L3"]) == 0
    output = capsys.readouterr().out

    assert "=== NODE SKIP: L2 ===" in output
    assert "hypothesis_count_lte_4" in output
    assert "L2 (not yet emitted)" not in output
    assert "No Feynman attack occurred" in output
    ok, detail = validate_l2_skip_receipt(project, "C1", l1_path)
    assert ok is True, detail


def test_l3_context_rejects_tampered_skip_receipt(tmp_path, monkeypatch, capsys):
    project, _ = _project(tmp_path, monkeypatch, 4)
    assert rl.main(["next-step", str(project), "C1"]) == 0
    capsys.readouterr()
    receipt = project / "08_Audit" / "node_skips" / "C1_L2.json"
    data = json.loads(receipt.read_text(encoding="utf-8"))
    data["hypothesis_count"] = 3
    receipt.write_text(json.dumps(data), encoding="utf-8")

    rc = rl.main(["assemble-context", str(project), "C1", "--node", "L3"])
    captured = capsys.readouterr()
    assert rc != 0
    assert "skip receipt" in captured.err.lower()
