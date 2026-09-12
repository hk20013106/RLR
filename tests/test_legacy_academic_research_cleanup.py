import hashlib
from types import SimpleNamespace

import pytest

from research_loop import structured_execution
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE, PROFILE_V20
from research_loop.topology import topology_for_profile


def test_native_literature_nodes_do_not_declare_legacy_pre_research():
    _, native_nodes, _ = topology_for_profile(DEFAULT_NATIVE_PROFILE)

    for node in ("L0.5", "L1", "L4", "L8.5"):
        assert "pre_research" not in native_nodes[node]

    _, legacy_nodes, _ = topology_for_profile(PROFILE_V20)
    assert legacy_nodes["L1"]["pre_research"] == "deep_research"


def test_native_structured_execution_has_no_academic_skill_authority(tmp_path):
    spec = type("Spec", (), {"backend": "codex", "executable": "codex"})()

    command = structured_execution.build_invocation(
        spec, tmp_path / "output.schema.json"
    )

    assert command[:2] == ["codex", "exec"]
    assert "--plugin-dir" not in command
    assert not any("academic-research" in str(item).casefold() for item in command)


def test_native_l4_uses_structured_model_execution_boundary(tmp_path):
    from research_loop import l4_inventory

    calls = {}

    class FakeDeepResearch:
        DeepResearchError = ValueError

        @staticmethod
        def build_invocation(*_args, **kwargs):
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


def test_l85_verdicts_are_exactly_once_and_doi_is_not_verification():
    from research_loop.l85_literature_verification import validate_finding_verdicts

    findings = [
        {"finding_id": "H1", "text": "the observed result"},
        {"finding_id": "H2", "text": "the second observed result"},
    ]
    verdicts = [
        {"finding_id": "H1", "verdict": "supports", "evidence_ids": ["E1"]},
        {"finding_id": "H2", "verdict": "unresolved", "evidence_ids": []},
    ]
    assert [item["verdict"] for item in validate_finding_verdicts(
        findings, verdicts, known_evidence_ids={"E1"}
    )] == ["supports", "unresolved"]
    with pytest.raises(ValueError, match="exactly one"):
        validate_finding_verdicts(
            findings,
            verdicts + [{"finding_id": "H1", "verdict": "contradicts", "evidence_ids": ["E1"]}],
            known_evidence_ids={"E1"},
        )


def test_native_l85_audit_revalidates_located_source_bytes(tmp_path):
    from research_loop import l85_literature_verification as l85
    from research_loop.commands import ledger as ledger_commands

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
                "evidence_id": "E1", "verification_status": "LOCATED",
                "retrieval": {"snapshot_path": "08_Audit/l85_source.xml", "source_sha256": source_sha256},
            }],
            "verdicts": [{"finding_id": "H1", "verdict": "unresolved", "evidence_ids": []}],
        },
    )
    ok, reason, audited = l85.audit_run_manifest(tmp_path, "C1", run_id=run["run_id"])
    assert (ok, reason, audited["run_id"]) == (True, "", "L85_fixture")
    reference = {
        "run_id": run["run_id"], "run_sha256": run["run_sha256"],
        "finding_count": 1, "located_evidence_ids": ["E1"],
    }
    assert ledger_commands._native_l85_evidence_manifest(
        SimpleNamespace(project_dir=str(tmp_path), cand_id="C1"), reference
    ) == reference

    source.write_bytes(b"tampered\n")
    ok, reason, audited = l85.audit_run_manifest(tmp_path, "C1", run_id=run["run_id"])
    assert not ok
    assert "hash mismatch" in reason
    assert audited is None


def test_native_run_loop_literature_hook_does_not_forward_legacy_options(
    tmp_path, monkeypatch
):
    import run_loop

    calls = []
    monkeypatch.setattr(run_loop, "_bound_profile_id", lambda _project: DEFAULT_NATIVE_PROFILE)
    monkeypatch.setattr(
        run_loop,
        "_deep_research_config",
        lambda _cfg: {
            "backend": "codex", "executable": "codex",
            "plugin_dir": "C:/legacy/plugin", "skill_path": "C:/legacy/skill",
            "skill_version": "legacy", "model": "configured-model", "timeout": 30,
        },
    )

    def fake_ctl(*argv):
        calls.append(argv)
        if argv[0] == "audit-literature-evidence":
            return SimpleNamespace(returncode=1, stdout="", stderr="missing")
        return SimpleNamespace(returncode=0, stdout='{"run_id": "native-L4-run"}', stderr="")

    monkeypatch.setattr(run_loop, "_ctl", fake_ctl)
    assert run_loop.ensure_pre_research(
        str(tmp_path), "C1", "L4", SimpleNamespace(data={}), SimpleNamespace(), tmp_path / "run"
    ) is True
    dispatch = calls[1]
    assert "--plugin-dir" not in dispatch
    assert "--skill-path" not in dispatch
    assert "--skill-version" not in dispatch
    assert "C:/legacy/plugin" not in dispatch
    assert "C:/legacy/skill" not in dispatch
