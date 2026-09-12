from research_loop import structured_execution


def test_native_structured_execution_has_no_academic_skill_authority(tmp_path):
    spec = type("Spec", (), {"backend": "codex", "executable": "codex"})()

    command = structured_execution.build_invocation(
        spec, tmp_path / "output.schema.json"
    )

    assert command[:2] == ["codex", "exec"]
    assert "--plugin-dir" not in command
    assert not any("academic-research" in str(item).casefold() for item in command)
