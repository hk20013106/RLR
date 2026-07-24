# -*- coding: utf-8 -*-
"""Legacy deltas are migration input only after the ledger cutover."""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import research_loop_v04 as rl


def _candidate(project, cand_id="CNEW"):
    directory = project / "01_Candidates"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{cand_id}.md").write_text(
        f"---\ncandidate_id: {cand_id}\ncurrent_status: IDEA_PROPOSED\n---\n",
        encoding="utf-8",
    )


def _delta(project, persona, name, data=None):
    path = project / "02_Agent_Notes" / persona / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data or {}), encoding="utf-8")
    return path


def test_unactivated_legacy_project_is_rejected_even_with_candidate_receipt():
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        _candidate(project)
        source = _delta(project, "Einstein", "L1_einstein_delta.json")
        audit = project / "08_Audit"
        audit.mkdir()
        (audit / "run_receipt_L1_1.json").write_text(json.dumps({
            "candidate_id": "CNEW", "node": "L1", "delta_key": "L1_einstein",
            "output_delta_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }), encoding="utf-8")
        assert rl.main(["next-step", str(project), "CNEW"]) == 2


def test_unactivated_project_cannot_emit_or_overwrite_a_legacy_delta():
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        _candidate(project)
        legacy = _delta(project, "Einstein", "L1_einstein_delta.json",
                        {"historical": "anonymous"})
        before = legacy.read_bytes()
        source = project / "l1.json"
        source.write_text(json.dumps({
            "hypotheses": [{"id": "H1", "text": "legacy", "testable": True,
                             "rationale": "legacy"}],
            "key_uncertainty": "u", "primary_hypothesis": "H1",
        }), encoding="utf-8")
        assert rl.main(["emit-delta", str(project), "CNEW", "--node", "L1",
                        "--persona", "Einstein", "--file", str(source)]) == 2
        assert legacy.read_bytes() == before
        assert not (legacy.parent / "CNEW_L1_einstein_delta.json").exists()
