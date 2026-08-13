"""Intake-level RED tests for the canonical L0InputContract 1.1 path."""
import hashlib
from pathlib import Path

from research_loop import l0_intake


def _memory():
    return {
        "source_candidate_id": "C_PARENT",
        "previous_hypothesis": "H0",
        "previous_final_decision": "REVISE",
        "previous_conclusion": "additional data are required",
        "round_id": "2",
        "parent_round_id": "1",
    }


def _selector():
    return {
        "path": "04_Analysis_Outputs/result.json",
        "sha256": "b" * 64,
        "role": "prior_result",
        "reuse_reason": "reuse the verified prior result in the revised analysis",
    }


def test_rules_initial_emits_current_schema_11(tmp_path):
    data = tmp_path / "new.csv"
    data.write_text("x\n1\n", encoding="utf-8")
    request = tmp_path / "request.md"
    text = "Scientific question: Q?\nCurrent hypothesis: H.\n"
    request.write_text(text, encoding="utf-8")

    result = l0_intake.normalize_request(
        request, text, "C1", data=str(data)
    )

    assert result["errors"] == []
    assert result["missing_fields"] == []
    assert result["contract"]["schema_version"] == "1.1"
    assert result["contract"]["inherited_inputs"] == []


def test_rules_continuation_new_only_emits_schema_11(tmp_path):
    data = tmp_path / "new.csv"
    data.write_text("x\n1\n", encoding="utf-8")
    request = tmp_path / "request.md"
    text = "Scientific question: Q2?\nCurrent hypothesis: H2.\n"
    request.write_text(text, encoding="utf-8")

    result = l0_intake.normalize_request(
        request,
        text,
        "C2",
        data=str(data),
        memory=_memory(),
        memory_hash="memory-sha",
    )

    assert result["errors"] == []
    assert result["missing_fields"] == []
    contract = result["contract"]
    assert contract["schema_version"] == "1.1"
    assert contract["round_type"] == "continuation"
    assert contract["inherited_inputs"] == []


def test_structured_continuation_allows_inherited_only(tmp_path):
    request = tmp_path / "plan.md"
    selector = _selector()
    text = (
        "---\n"
        "intake_schema: 'research-loop-plan/1.0'\n"
        "round_type: continuation\n"
        "round_id: '2'\n"
        "scientific_question: 'Does the prior result survive the revised test?'\n"
        "current_round:\n"
        "  hypothesis: 'The prior result remains supported.'\n"
        "inherited_inputs:\n"
        f"  - path: '{selector['path']}'\n"
        f"    sha256: '{selector['sha256']}'\n"
        f"    role: '{selector['role']}'\n"
        f"    reuse_reason: '{selector['reuse_reason']}'\n"
        "research_plan:\n"
        "  goal: 'Reanalyze prior result'\n"
        "---\n"
    )
    request.write_text(text, encoding="utf-8")

    result = l0_intake.normalize_request(
        request,
        text,
        "C2",
        memory=_memory(),
        memory_hash="memory-sha",
    )

    assert result["errors"] == []
    assert result["missing_fields"] == []
    contract = result["contract"]
    assert contract["schema_version"] == "1.1"
    assert contract["source_input"] is None
    assert contract["inherited_inputs"] == [selector]


def test_structured_continuation_combines_verified_new_manifest_and_inherited(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    new_file = data_dir / "new.csv"
    new_file.write_bytes(b"x\n1\n")
    digest = hashlib.sha256(new_file.read_bytes()).hexdigest()
    selector = _selector()
    request = tmp_path / "plan.md"
    text = (
        "---\n"
        "intake_schema: 'research-loop-plan/1.0'\n"
        "round_type: continuation\n"
        "round_id: '2'\n"
        "scientific_question: 'Does new data change the prior result?'\n"
        "current_round:\n"
        "  hypothesis: 'The combined data support the revised hypothesis.'\n"
        "source_input:\n"
        "  file_manifest:\n"
        f"    - path: '{new_file.as_posix()}'\n"
        "      role: 'new_measurements'\n"
        f"      bytes: {new_file.stat().st_size}\n"
        f"      sha256: '{digest}'\n"
        "inherited_inputs:\n"
        f"  - path: '{selector['path']}'\n"
        f"    sha256: '{selector['sha256']}'\n"
        f"    role: '{selector['role']}'\n"
        f"    reuse_reason: '{selector['reuse_reason']}'\n"
        "research_plan:\n"
        "  goal: 'Combine old and new data'\n"
        "---\n"
    )
    request.write_text(text, encoding="utf-8")

    result = l0_intake.normalize_request(
        request,
        text,
        "C2",
        data=str(data_dir),
        memory=_memory(),
        memory_hash="memory-sha",
    )

    assert result["errors"] == []
    assert result["missing_fields"] == []
    contract = result["contract"]
    assert contract["schema_version"] == "1.1"
    assert contract["source_input"]["file_manifest"][0]["sha256"] == digest
    assert contract["inherited_inputs"] == [selector]
