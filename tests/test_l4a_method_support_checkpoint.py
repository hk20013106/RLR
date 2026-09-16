from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop import deep_research as dr
from research_loop import l4_contextual_literature as contextual
from research_loop import l4_inventory
from research_loop import l4_pipeline as l4p
from research_loop import provider_runtime_observability as runtime_observability


ORIGINAL_SKILL_RECEIPT = dr.skill_receipt


def _method(method_id: str, name: str | None = None) -> dict:
    return {
        "method_id": method_id,
        "name": name or f"Method {method_id}",
        "purpose": f"Purpose {method_id}",
        "inventory_reason": f"Reason {method_id}",
    }


def _record(paper_id: str, *, title: str | None = None) -> dict:
    return {
        "paper_id": paper_id,
        "title": title or f"Paper {paper_id}",
        "metadata": {
            "abstract": f"Abstract {paper_id}",
            "journal": "Fixture Journal",
            "year": "2026",
        },
    }


def _selection(*pairs: tuple[str, str]) -> dict:
    return {
        "pairs": [
            {
                "paper_id": paper_id,
                "method_id": method_id,
                "semantic_score": 0.9,
                "semantic_rank": index,
                "selector_decision": "INCLUDE",
            }
            for index, (paper_id, method_id) in enumerate(pairs, 1)
        ]
    }


def _wire(*classifications: str) -> dict:
    return {
        "schema_version": contextual.METHOD_SUPPORT_SCHEMA_VERSION,
        "decisions": [
            {
                "classification": classification,
                "rationale": f"Fixture rationale {index}",
            }
            for index, classification in enumerate(classifications, 1)
        ],
    }


def _sha(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: dict) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _checkpoint_content_sha256(checkpoint: dict) -> str:
    payload = {key: value for key, value in checkpoint.items() if key != "content_sha256"}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _sha(canonical)


def _dict_sha256(value: dict) -> str:
    return _sha(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _write_runtime_snapshot(
    project_dir: Path,
    method_work: Path,
    *,
    backend: str,
    command: list[str],
    prompt: str,
    stdout: str,
) -> dict:
    artifact_bytes = {
        "events.jsonl": b'{"type":"turn.completed"}\n',
        "stderr.log": b"",
        "final_output.json": stdout.encode("utf-8"),
    }
    receipt = {
        "schema_version": runtime_observability.RECEIPT_SCHEMA,
        "task_id": f"fixture-{method_work.name}",
        "attempt_id": "",
        "candidate_id": "C1",
        "node": "L4",
        "backend": backend,
        "provider_version": "fixture-provider-v1",
        "command_hash": _sha(json.dumps(command, ensure_ascii=False)),
        "executed_command_hash": _sha(json.dumps(command, ensure_ascii=False)),
        "command_metadata": {
            "argv0": command[0],
            "argument_count": len(command),
            "backend": backend,
        },
        "cwd": str(method_work.resolve()),
        "timeout_config": {
            "job_timeout_seconds": 3,
            "inactivity_timeout_seconds": None,
            "observer_interval_seconds": 0.01,
        },
        "prompt_hash": _sha(prompt),
        "started_at": "2026-09-15T00:00:00+00:00",
        "ended_at": "2026-09-15T00:00:01+00:00",
        "provider_pid": None,
        "thread_id": "",
        "final_status": "succeeded",
        "exit_code": 0,
        "last_successful_event": {"type": "turn.completed"},
        "last_provider_event": {"type": "turn.completed"},
        "last_provider_event_at": "2026-09-15T00:00:01+00:00",
        "current_item_at_termination": {},
        "termination_reason": "completed",
        "timed_out": False,
        "process_activity": {
            "cpu_seconds": None,
            "io_bytes": None,
            "last_process_activity_at": "",
            "last_activity_at": "2026-09-15T00:00:01+00:00",
            "process_tree_pids": [],
        },
        "process_tree_cleanup": {
            "attempted": False,
            "targeted_pids": [],
            "terminated_pids": [],
            "killed_pids": [],
            "errors": [],
            "provider_alive_after_cleanup": False,
        },
        "artifacts": {
            "events": {
                "path": "events.jsonl",
                "sha256": _sha(artifact_bytes["events.jsonl"]),
                "bytes": len(artifact_bytes["events.jsonl"]),
            },
            "stderr": {
                "path": "stderr.log",
                "sha256": _sha(artifact_bytes["stderr.log"]),
                "bytes": len(artifact_bytes["stderr.log"]),
            },
            "final_output": {
                "path": "final_output.json",
                "sha256": _sha(artifact_bytes["final_output.json"]),
                "bytes": len(artifact_bytes["final_output.json"]),
            },
        },
    }
    receipt_bytes = _json_bytes(receipt)
    receipt_sha256 = _sha(receipt_bytes)
    snapshot = method_work / "provider_runtime" / receipt_sha256
    snapshot.mkdir(parents=True, exist_ok=True)
    (snapshot / "runtime_receipt.json").write_bytes(receipt_bytes)
    for name, content in artifact_bytes.items():
        (snapshot / name).write_bytes(content)
    return {
        "schema": runtime_observability.RECEIPT_SCHEMA,
        "path": (snapshot / "runtime_receipt.json").relative_to(project_dir).as_posix(),
        "sha256": receipt_sha256,
    }


def _invoke(
    monkeypatch,
    project_dir: Path,
    *,
    methods: list[dict],
    records: list[dict],
    selection: dict,
    outcomes: dict[str, dict | Exception],
    backend: str = "codex",
    model: str = "fixture-model",
    skill_version: str = "fixture-skill-v1",
    command_marker: str = "command-v1",
    call_log: list[str] | None = None,
    include_runtime_receipt: bool = True,
) -> tuple[dict, list[str]]:
    calls = call_log if call_log is not None else []
    execution: dict[str, str] = {}
    work_dir = project_dir / "work"
    spec = dr.RuntimeSpec(backend, backend, model=model, timeout=3)

    def build_invocation(_spec, _node, _question, _claim, invocation_work):
        return [
            backend,
            "exec",
            "--output-schema",
            str(Path(invocation_work) / "deep_research_output.schema.json"),
            "--model",
            model,
            command_marker,
        ], "unused"

    def subprocess_invocation(command, prompt):
        execution["prompt"] = prompt
        execution["method_work"] = str(
            Path(command[command.index("--output-schema") + 1]).parent
        )
        return command, {"input": prompt}

    def execute_provider_invocation(_command, _kwargs, **kwargs):
        match = re.search(r"\(([^()]+)\)$", kwargs["label"])
        assert match is not None
        method_id = match.group(1)
        calls.append(method_id)
        outcome = outcomes[method_id]
        if isinstance(outcome, Exception):
            raise outcome
        stdout = json.dumps(outcome, ensure_ascii=False)
        execution["stdout"] = stdout
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    def skill_receipt(receipt_backend, command, prompt, receipt_skill_version, **kwargs):
        receipt = ORIGINAL_SKILL_RECEIPT(
            receipt_backend,
            command,
            prompt,
            receipt_skill_version,
            **kwargs,
        )
        if include_runtime_receipt:
            receipt["runtime_receipt"] = _write_runtime_snapshot(
                project_dir,
                Path(execution["method_work"]),
                backend=receipt_backend,
                command=command,
                prompt=prompt,
                stdout=execution["stdout"],
            )
        return receipt

    monkeypatch.setattr(dr, "build_invocation", build_invocation)
    monkeypatch.setattr(dr, "resolve_subprocess_executable", lambda value: value)
    monkeypatch.setattr(dr, "subprocess_invocation", subprocess_invocation)
    monkeypatch.setattr(dr, "execute_provider_invocation", execute_provider_invocation)
    monkeypatch.setattr(dr, "skill_receipt", skill_receipt)

    result = contextual._run_method_support_adjudication(
        l4p,
        dr,
        project_dir,
        "C1",
        "question outside method prompt",
        "claim outside method prompt",
        spec,
        work_dir,
        skill_version,
        methods,
        records,
        selection,
        inventory_module=l4_inventory,
    )
    return result, calls


def _checkpoint(project_dir: Path, index: int, method_id: str) -> Path:
    return (
        project_dir
        / "work"
        / f"method_support_{index:03d}_{method_id}"
        / "l4a_method_support_checkpoint.json"
    )


def test_m01_checkpoint_is_reused_after_m02_provider_failure(tmp_path, monkeypatch):
    methods = [_method("M01"), _method("M02")]
    records = [_record("P01"), _record("P02")]
    selection = _selection(("P01", "M01"), ("P02", "M02"))

    with pytest.raises(dr.DeepResearchError, match="quota exhausted"):
        _invoke(
            monkeypatch,
            tmp_path,
            methods=methods,
            records=records,
            selection=selection,
            outcomes={
                "M01": _wire("DIRECT_METHOD_SUPPORT"),
                "M02": dr.DeepResearchError("quota exhausted"),
            },
        )

    assert _checkpoint(tmp_path, 1, "M01").is_file()
    assert not _checkpoint(tmp_path, 2, "M02").exists()

    resumed, calls = _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={
            "M01": AssertionError("M01 provider must not run"),
            "M02": _wire("RELATED_BUT_NOT_METHOD_SUPPORT"),
        },
    )

    assert calls == ["M02"]
    assert [batch["method_id"] for batch in resumed["method_batches"]] == ["M01", "M02"]
    assert resumed["adjudication_call_count"] == 2


def test_identical_checkpoint_reuses_all_methods_with_zero_provider_calls(
    tmp_path, monkeypatch
):
    methods = [_method("M01"), _method("M02")]
    records = [_record("P01"), _record("P02")]
    selection = _selection(("P01", "M01"), ("P02", "M02"))
    outcomes = {
        "M01": _wire("DIRECT_METHOD_SUPPORT"),
        "M02": _wire("INSUFFICIENT_METADATA"),
    }
    clean, first_calls = _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes=outcomes,
    )
    resumed, second_calls = _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={
            "M01": AssertionError("provider must not run"),
            "M02": AssertionError("provider must not run"),
        },
    )

    assert first_calls == ["M01", "M02"]
    assert second_calls == []
    assert resumed == clean


def test_checkpoint_persists_exact_execution_binding(tmp_path, monkeypatch):
    _invoke(
        monkeypatch,
        tmp_path,
        methods=[_method("M01")],
        records=[_record("P01")],
        selection=_selection(("P01", "M01")),
        outcomes={"M01": _wire("DIRECT_METHOD_SUPPORT")},
    )

    checkpoint = json.loads(_checkpoint(tmp_path, 1, "M01").read_text(encoding="utf-8"))
    assert checkpoint["schema_version"] == "L4AMethodSupportCheckpoint/v1"
    assert set(checkpoint["input_binding"]) == {
        "candidate_id",
        "method_id",
        "ordered_candidate_paper_ids",
        "method_support_input",
        "backend",
        "model",
        "skill_version",
        "method_support_schema_version",
        "output_schema_sha256",
        "command_hash",
        "runtime_command_hash",
        "prompt_hash",
    }
    assert checkpoint["input_binding"]["candidate_id"] == "C1"
    assert checkpoint["input_binding"]["method_id"] == "M01"
    assert checkpoint["input_binding"]["ordered_candidate_paper_ids"] == ["P01"]
    assert checkpoint["provider_stdout"] == json.dumps(
        _wire("DIRECT_METHOD_SUPPORT"), ensure_ascii=False
    )
    assert "decisions" not in checkpoint
    assert checkpoint["content_sha256"] == _checkpoint_content_sha256(checkpoint)


def test_active_runtime_success_without_frozen_receipt_fails_closed(
    tmp_path, monkeypatch
):
    calls: list[str] = []
    token = runtime_observability._CONTEXT.set({"backend": "codex"})
    try:
        with pytest.raises(
            dr.DeepResearchError,
            match="durable checkpoint.*frozen runtime receipt",
        ):
            _invoke(
                monkeypatch,
                tmp_path,
                methods=[_method("M01")],
                records=[_record("P01")],
                selection=_selection(("P01", "M01")),
                outcomes={"M01": _wire("DIRECT_METHOD_SUPPORT")},
                call_log=calls,
                include_runtime_receipt=False,
            )
    finally:
        runtime_observability._CONTEXT.reset(token)

    assert calls == ["M01"]
    assert not _checkpoint(tmp_path, 1, "M01").exists()


@pytest.mark.parametrize("change", ["paper_ids", "paper_order", "method_input"])
def test_scientific_input_change_marks_only_method_stale(
    tmp_path, monkeypatch, change
):
    methods = [_method("M01")]
    records = [_record("P01"), _record("P02")]
    selection = _selection(("P01", "M01"), ("P02", "M01"))
    _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={"M01": _wire("DIRECT_METHOD_SUPPORT", "IRRELEVANT")},
    )
    assert _checkpoint(tmp_path, 1, "M01").is_file()

    if change == "paper_ids":
        records = [_record("P01"), _record("P03")]
        selection = _selection(("P01", "M01"), ("P03", "M01"))
    elif change == "paper_order":
        selection = _selection(("P02", "M01"), ("P01", "M01"))
    else:
        methods = [_method("M01", "Changed method name")]

    _, calls = _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={"M01": _wire("IRRELEVANT", "DIRECT_METHOD_SUPPORT")},
    )
    assert calls == ["M01"]


@pytest.mark.parametrize(
    "change",
    ["model", "backend", "skill", "schema_version", "output_schema", "prompt", "command"],
)
def test_execution_contract_change_marks_method_stale(
    tmp_path, monkeypatch, change
):
    methods = [_method("M01")]
    records = [_record("P01")]
    selection = _selection(("P01", "M01"))
    _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={"M01": _wire("DIRECT_METHOD_SUPPORT")},
    )
    assert _checkpoint(tmp_path, 1, "M01").is_file()

    kwargs = {}
    if change == "model":
        kwargs["model"] = "fixture-model-v2"
    elif change == "backend":
        kwargs["backend"] = "claude"
    elif change == "skill":
        kwargs["skill_version"] = "fixture-skill-v2"
    elif change == "schema_version":
        monkeypatch.setattr(
            contextual,
            "METHOD_SUPPORT_SCHEMA_VERSION",
            "L4AMethodSupportAdjudication/v3",
        )
    elif change == "output_schema":
        original_schema = contextual._method_support_schema

        def changed_schema():
            value = original_schema()
            value["title"] = "changed exact output schema bytes"
            return value

        monkeypatch.setattr(contextual, "_method_support_schema", changed_schema)
    elif change == "prompt":
        original_prompt = contextual._method_support_prompt
        monkeypatch.setattr(
            contextual,
            "_method_support_prompt",
            lambda payload, backend: original_prompt(payload, backend) + "\nchanged prompt",
        )
    else:
        kwargs["command_marker"] = "command-v2"

    _, calls = _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={"M01": _wire("IRRELEVANT")},
        **kwargs,
    )
    assert calls == ["M01"]


@pytest.mark.parametrize("damage", ["malformed_json", "content_hash"])
def test_corrupt_checkpoint_fails_closed_without_provider_call(
    tmp_path, monkeypatch, damage
):
    methods = [_method("M01")]
    records = [_record("P01")]
    selection = _selection(("P01", "M01"))
    _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={"M01": _wire("DIRECT_METHOD_SUPPORT")},
    )
    path = _checkpoint(tmp_path, 1, "M01")
    if damage == "malformed_json":
        path.write_text("{", encoding="utf-8")
    else:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        checkpoint["input_binding"]["candidate_id"] = "tampered"
        path.write_text(json.dumps(checkpoint), encoding="utf-8")

    calls: list[str] = []
    with pytest.raises(
        dr.DeepResearchError,
        match=rf"checkpoint.*corrupt.*{re.escape(str(path))}",
    ):
        _invoke(
            monkeypatch,
            tmp_path,
            methods=methods,
            records=records,
            selection=selection,
            outcomes={"M01": AssertionError("provider must not run")},
            call_log=calls,
        )
    assert calls == []


def test_corrupt_runtime_snapshot_fails_closed_without_provider_call(
    tmp_path, monkeypatch
):
    methods = [_method("M01")]
    records = [_record("P01")]
    selection = _selection(("P01", "M01"))
    _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={"M01": _wire("DIRECT_METHOD_SUPPORT")},
    )
    checkpoint = json.loads(
        _checkpoint(tmp_path, 1, "M01").read_text(encoding="utf-8")
    )
    receipt_path = tmp_path / checkpoint["skill_receipt"]["runtime_receipt"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    events_path = receipt_path.parent / receipt["artifacts"]["events"]["path"]
    events_path.write_bytes(b"tampered")

    calls: list[str] = []
    with pytest.raises(dr.DeepResearchError, match="checkpoint.*corrupt.*runtime receipt"):
        _invoke(
            monkeypatch,
            tmp_path,
            methods=methods,
            records=records,
            selection=selection,
            outcomes={"M01": AssertionError("provider must not run")},
            call_log=calls,
        )
    assert calls == []


def test_foreign_valid_runtime_snapshot_fails_closed_without_provider_call(
    tmp_path, monkeypatch
):
    methods = [_method("M01")]
    records = [_record("P01")]
    selection = _selection(("P01", "M01"))
    _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={"M01": _wire("DIRECT_METHOD_SUPPORT")},
    )
    path = _checkpoint(tmp_path, 1, "M01")
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint["skill_receipt"]["runtime_receipt"] = _write_runtime_snapshot(
        tmp_path,
        tmp_path / "foreign_invocation",
        backend="codex",
        command=["foreign-provider", "exec"],
        prompt="foreign prompt",
        stdout=json.dumps(_wire("IRRELEVANT"), ensure_ascii=False),
    )
    checkpoint["content_sha256"] = _checkpoint_content_sha256(checkpoint)
    path.write_bytes(_json_bytes(checkpoint))

    calls: list[str] = []
    with pytest.raises(
        dr.DeepResearchError,
        match="checkpoint.*corrupt.*runtime receipt.*mismatch",
    ):
        _invoke(
            monkeypatch,
            tmp_path,
            methods=methods,
            records=records,
            selection=selection,
            outcomes={"M01": AssertionError("provider must not run")},
            call_log=calls,
        )
    assert calls == []


def test_malformed_self_hashed_input_binding_fails_closed_without_provider_call(
    tmp_path, monkeypatch
):
    methods = [_method("M01")]
    records = [_record("P01")]
    selection = _selection(("P01", "M01"))
    _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={"M01": _wire("DIRECT_METHOD_SUPPORT")},
    )
    path = _checkpoint(tmp_path, 1, "M01")
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint["input_binding"]["method_support_input"] = []
    checkpoint["input_binding_sha256"] = _dict_sha256(checkpoint["input_binding"])
    checkpoint["content_sha256"] = _checkpoint_content_sha256(checkpoint)
    path.write_bytes(_json_bytes(checkpoint))

    calls: list[str] = []
    with pytest.raises(
        dr.DeepResearchError,
        match="checkpoint.*corrupt.*input binding",
    ):
        _invoke(
            monkeypatch,
            tmp_path,
            methods=methods,
            records=records,
            selection=selection,
            outcomes={"M01": AssertionError("provider must not run")},
            call_log=calls,
        )
    assert calls == []


@pytest.mark.parametrize(
    ("field", "bogus_value"),
    [
        ("schema_version", "BogusSkillReceipt/v999"),
        ("skill", "bogus-skill"),
        ("upstream", "https://example.invalid/bogus-skill"),
    ],
)
def test_self_hashed_invalid_skill_receipt_fails_closed_without_provider_call(
    tmp_path, monkeypatch, field, bogus_value
):
    methods = [_method("M01")]
    records = [_record("P01")]
    selection = _selection(("P01", "M01"))
    _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={"M01": _wire("DIRECT_METHOD_SUPPORT")},
    )
    path = _checkpoint(tmp_path, 1, "M01")
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint["skill_receipt"][field] = bogus_value
    checkpoint["content_sha256"] = _checkpoint_content_sha256(checkpoint)
    path.write_bytes(_json_bytes(checkpoint))

    calls: list[str] = []
    with pytest.raises(
        dr.DeepResearchError,
        match=rf"checkpoint.*corrupt.*skill receipt {field} mismatch",
    ):
        _invoke(
            monkeypatch,
            tmp_path,
            methods=methods,
            records=records,
            selection=selection,
            outcomes={"M01": AssertionError("provider must not run")},
            call_log=calls,
        )
    assert calls == []


def test_checkpoint_decision_count_corruption_fails_closed(tmp_path, monkeypatch):
    methods = [_method("M01")]
    records = [_record("P01"), _record("P02")]
    selection = _selection(("P01", "M01"), ("P02", "M01"))
    _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={"M01": _wire("DIRECT_METHOD_SUPPORT", "IRRELEVANT")},
    )
    path = _checkpoint(tmp_path, 1, "M01")
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint["provider_stdout"] = json.dumps(_wire("DIRECT_METHOD_SUPPORT"))
    checkpoint["skill_receipt"]["stdout_hash"] = _sha(checkpoint["provider_stdout"])
    checkpoint["content_sha256"] = _checkpoint_content_sha256(checkpoint)
    path.write_bytes(_json_bytes(checkpoint))

    calls: list[str] = []
    with pytest.raises(
        dr.DeepResearchError,
        match="checkpoint.*corrupt.*runtime receipt.*final_output mismatch",
    ):
        _invoke(
            monkeypatch,
            tmp_path,
            methods=methods,
            records=records,
            selection=selection,
            outcomes={"M01": AssertionError("provider must not run")},
            call_log=calls,
        )
    assert calls == []


def test_mixed_resume_preserves_clean_method_and_decision_order(
    tmp_path, monkeypatch
):
    methods = [_method("M01"), _method("M02")]
    records = [_record("P01"), _record("P02"), _record("P03")]
    selection = _selection(
        ("P01", "M01"),
        ("P02", "M01"),
        ("P03", "M02"),
    )
    with pytest.raises(dr.DeepResearchError, match="capacity"):
        _invoke(
            monkeypatch,
            tmp_path,
            methods=methods,
            records=records,
            selection=selection,
            outcomes={
                "M01": _wire("DIRECT_METHOD_SUPPORT", "IRRELEVANT"),
                "M02": dr.DeepResearchError("capacity"),
            },
        )
    resumed, calls = _invoke(
        monkeypatch,
        tmp_path,
        methods=methods,
        records=records,
        selection=selection,
        outcomes={
            "M01": AssertionError("provider must not run"),
            "M02": _wire("RELATED_BUT_NOT_METHOD_SUPPORT"),
        },
    )

    assert calls == ["M02"]
    assert [batch["method_id"] for batch in resumed["method_batches"]] == ["M01", "M02"]
    assert [
        (decision["paper_id"], decision["method_id"])
        for decision in resumed["decisions"]
    ] == [("P01", "M01"), ("P02", "M01"), ("P03", "M02")]
    assert resumed["direct_count"] == 1
    assert resumed["shortlisted_pair_count"] == 3
    assert resumed["adjudication_call_count"] == 2
