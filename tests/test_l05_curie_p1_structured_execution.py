import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop import deep_research, structured_execution


SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"value": {"type": "string"}}, "required": ["value"],
}


def test_structured_model_runs_existing_executor_and_validates_schema(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(deep_research, "resolve_subprocess_executable", lambda value: value)

    def fake_execute(command, **kwargs):
        seen.update(command=command, kwargs=kwargs)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"value": "ok"}), stderr="")

    monkeypatch.setattr(structured_execution.DEFAULT_EXECUTOR, "run", fake_execute)
    spec = SimpleNamespace(backend="codex", executable="codex", model="fixture", timeout=9)
    result = structured_execution.run_structured_model(
        spec, prompt="AUTHORIZED_SENTINEL", schema=SCHEMA, work_dir=tmp_path,
    )
    assert result["payload"] == {"value": "ok"}
    assert result["receipt"]["schema_sha256"]
    assert result["receipt"]["stdout_hash"]
    assert result["receipt"]["validation_status"] == "PASS"
    assert result["receipt"]["prompt_path"]
    assert (tmp_path / "structured_model_prompt.txt").read_text(encoding="utf-8") == "AUTHORIZED_SENTINEL"
    assert seen["kwargs"]["cwd"] == tmp_path
    assert "AUTHORIZED_SENTINEL" in " ".join(seen["command"]) + str(seen["kwargs"])
    assert "--sandbox" in seen["command"]
    assert "read-only" in seen["command"]
    assert "--cd" in seen["command"]


def test_claude_invocation_disables_tools_and_session_persistence(tmp_path):
    spec = SimpleNamespace(backend="claude", executable="claude", model="fixture")
    command = structured_execution.build_invocation(spec, tmp_path / "schema.json")
    assert command[command.index("--tools") + 1] == ""
    assert "--no-session-persistence" in command


def test_structured_model_rejects_schema_invalid_output(tmp_path, monkeypatch):
    monkeypatch.setattr(deep_research, "resolve_subprocess_executable", lambda value: value)
    monkeypatch.setattr(
        structured_execution.DEFAULT_EXECUTOR, "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout='{"value": 1}', stderr=""),
    )
    spec = SimpleNamespace(backend="codex", executable="codex", model="fixture", timeout=9)
    with pytest.raises(structured_execution.StructuredExecutionError, match="schema"):
        structured_execution.run_structured_model(
            spec, prompt="AUTHORIZED_SENTINEL", schema=SCHEMA, work_dir=tmp_path,
        )


def test_structured_model_persistence_error_is_typed_before_model_dispatch(tmp_path, monkeypatch):
    original_write = Path.write_bytes

    def failed_prompt_write(path, data):
        if path.name == "structured_model_prompt.txt":
            raise OSError("fixture disk unavailable")
        return original_write(path, data)

    monkeypatch.setattr(Path, "write_bytes", failed_prompt_write)
    monkeypatch.setattr(structured_execution.DEFAULT_EXECUTOR, "run",
                        lambda *_args, **_kwargs: pytest.fail("persistence error reached model"))
    spec = SimpleNamespace(backend="codex", executable="codex", model="fixture", timeout=9)
    with pytest.raises(structured_execution.StructuredExecutionError) as caught:
        structured_execution.run_structured_model(
            spec, prompt="AUTHORIZED_SENTINEL", schema=SCHEMA, work_dir=tmp_path,
        )
    assert caught.value.category == "PERSISTENCE_ERROR"
