from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop import l0_preflight, structured_execution
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE, PROFILE_V20
from research_loop.l05_native_context_gate import install as install_native_gate
from research_loop.topology import topology_for_profile


def test_native_literature_nodes_do_not_declare_legacy_pre_research():
    _, native_nodes, _ = topology_for_profile(DEFAULT_NATIVE_PROFILE)

    for node in ("L0.5", "L1", "L4", "L8.5"):
        assert "pre_research" not in native_nodes[node]

    _, legacy_nodes, _ = topology_for_profile(PROFILE_V20)
    assert legacy_nodes["L1"]["pre_research"] == "deep_research"


def test_structured_execution_command_has_no_academic_skill_authority(tmp_path):
    spec = type("Spec", (), {
        "backend": "codex",
        "executable": "codex",
        "model": "configured-model",
    })()

    command = structured_execution.build_invocation(
        spec, tmp_path / "structured-output.schema.json"
    )

    assert command[:2] == ["codex", "exec"]
    assert "--output-schema" in command
    assert "--plugin-dir" not in command
    assert not any("academic-research" in str(value).casefold() for value in command)


def test_structured_runtime_readiness_does_not_require_skill_manifest(
    tmp_path, monkeypatch
):
    executable = tmp_path / "provider.exe"
    executable.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(structured_execution.shutil, "which", lambda value: str(executable))
    spec = type("Spec", (), {
        "backend": "codex",
        "executable": "codex",
    })()

    assert structured_execution.runtime_ready(spec) == (True, "")


def test_native_l4_uses_structured_model_execution_boundary(tmp_path):
    from research_loop import l4_inventory

    calls = {}

    class FakeDeepResearch:
        DeepResearchError = ValueError

        @staticmethod
        def build_invocation(*args, **kwargs):
            calls.update(kwargs)
            return ["codex", "exec", "--output-schema", str(kwargs["schema_path"])], ""

    command, _ = l4_inventory._structured_model_invocation(
        FakeDeepResearch,
        type("Spec", (), {"backend": "codex", "executable": "codex"})(),
        "L4",
        "question",
        "claim",
        tmp_path,
        tmp_path / "l4a.schema.json",
    )

    assert calls == {
        "execution_kind": "structured_model",
        "schema_path": tmp_path / "l4a.schema.json",
    }
    assert "academic-research" not in " ".join(command).casefold()
    assert "--plugin-dir" not in command


def test_native_l1_context_gate_does_not_mutate_legacy_pre_research_map(
    tmp_path, monkeypatch
):
    # Importing the fixture keeps this regression at the actual context boundary.
    from test_l05_native_l1_handoff import _args, _native_project
    from research_loop import context
    import research_loop.l05_native_context_gate as gate

    project, store, _seed, _manifest = _native_project(tmp_path)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))

    class ForbiddenLegacyMap(dict):
        def pop(self, *args, **kwargs):  # pragma: no cover - the failure is the assertion
            raise AssertionError("native L1 must not pop the legacy pre-research map")

    monkeypatch.setattr(gate, "PRE_RESEARCH_MAP", ForbiddenLegacyMap(), raising=False)
    assert context.cmd_assemble_context(_args(project, store)) == 0


def test_l85_verdicts_are_exactly_once_and_doi_is_not_verification():
    from research_loop.l85_literature_verification import validate_finding_verdicts

    findings = [
        {"finding_id": "H1", "text": "the observed result"},
        {"finding_id": "H2", "text": "the second observed result"},
    ]
    verdicts = [
        {"finding_id": "H1", "verdict": "supports", "evidence_ids": ["E1"]},
        {"finding_id": "H2", "verdict": "unresolved", "evidence_ids": [],
         "reason": "a DOI-only metadata record is not located evidence"},
    ]

    validated = validate_finding_verdicts(findings, verdicts, known_evidence_ids={"E1"})

    assert [item["verdict"] for item in validated] == ["supports", "unresolved"]
    with pytest.raises(ValueError, match="exactly one"):
        validate_finding_verdicts(
            findings,
            verdicts + [{"finding_id": "H1", "verdict": "contradicts", "evidence_ids": ["E1"]}],
            known_evidence_ids={"E1"},
        )


def test_native_l85_audit_revalidates_located_source_bytes(tmp_path):
    from research_loop import l85_literature_verification as l85

    source = tmp_path / "08_Audit" / "l85_source.xml"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"<article><body>located evidence</body></article>\n")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

    run = l85.persist_run_manifest(
        tmp_path,
        "C1",
        run_id="L85_fixture",
        payload={
            "findings": [{"finding_id": "H1", "text": "observed result"}],
            "located_evidence": [{
                "evidence_id": "E1",
                "verification_status": "LOCATED",
                "retrieval": {
                    "snapshot_path": "08_Audit/l85_source.xml",
                    "source_sha256": source_sha256,
                },
                "text": "located evidence",
            }],
            "semantic_verifications": [],
            "verdicts": [{
                "finding_id": "H1",
                "verdict": "unresolved",
                "evidence_ids": [],
                "reason": "no semantic assessor",
            }],
        },
    )

    ok, reason, audited = l85.audit_run_manifest(
        tmp_path, "C1", run_id=run["run_id"]
    )
    assert (ok, reason) == (True, "")
    assert audited["run_id"] == "L85_fixture"

    source.write_bytes(b"tampered\n")
    ok, reason, audited = l85.audit_run_manifest(
        tmp_path, "C1", run_id=run["run_id"]
    )
    assert not ok
    assert "hash mismatch" in reason
    assert audited is None


def test_native_l85_receipt_binds_canonical_context_reference(tmp_path):
    from research_loop import l85_literature_verification as l85
    from research_loop.commands import ledger as ledger_commands

    source = tmp_path / "08_Audit" / "l85_receipt_source.xml"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"<article><body>receipt evidence</body></article>\n")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    run = l85.persist_run_manifest(
        tmp_path,
        "C1",
        run_id="L85_receipt_fixture",
        payload={
            "findings": [{"finding_id": "H1", "text": "observed result"}],
            "located_evidence": [{
                "evidence_id": "E1",
                "verification_status": "LOCATED",
                "retrieval": {
                    "snapshot_path": "08_Audit/l85_receipt_source.xml",
                    "source_sha256": source_sha256,
                },
                "text": "receipt evidence",
            }],
            "semantic_verifications": [],
            "verdicts": [{
                "finding_id": "H1",
                "verdict": "unresolved",
                "evidence_ids": [],
                "reason": "no independent semantic assessor",
            }],
        },
    )
    reference = {
        "run_id": run["run_id"],
        "run_sha256": run["run_sha256"],
        "finding_count": 1,
        "located_evidence_ids": ["E1"],
    }

    resolved = ledger_commands._native_l85_evidence_manifest(
        SimpleNamespace(project_dir=str(tmp_path), cand_id="C1"),
        reference,
    )

    assert resolved == reference


def test_native_run_loop_literature_hook_does_not_forward_legacy_options(
    tmp_path, monkeypatch
):
    import run_loop

    calls = []
    monkeypatch.setattr(
        run_loop, "_bound_profile_id", lambda _project: DEFAULT_NATIVE_PROFILE
    )
    monkeypatch.setattr(
        run_loop,
        "_deep_research_config",
        lambda _cfg: {
            "backend": "codex",
            "executable": "codex",
            "plugin_dir": "C:/legacy/plugin",
            "skill_path": "C:/legacy/skill",
            "skill_version": "legacy",
            "model": "configured-model",
            "timeout": 30,
        },
    )

    def fake_ctl(*argv):
        calls.append(argv)
        if argv[0] == "audit-literature-evidence":
            return SimpleNamespace(returncode=1, stdout="", stderr="missing")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"run_id": "native-L4-run"}),
            stderr="",
        )

    monkeypatch.setattr(run_loop, "_ctl", fake_ctl)

    assert run_loop.ensure_pre_research(
        str(tmp_path),
        "C1",
        "L4",
        SimpleNamespace(data={}),
        SimpleNamespace(),
        tmp_path / "run",
    ) is True

    dispatch = calls[1]
    assert "--plugin-dir" not in dispatch
    assert "--skill-path" not in dispatch
    assert "--skill-version" not in dispatch
    assert "C:/legacy/plugin" not in dispatch
    assert "C:/legacy/skill" not in dispatch
