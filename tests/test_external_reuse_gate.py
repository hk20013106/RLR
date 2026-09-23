import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "external_reuse_gate.py"


def _module():
    spec = spec_from_file_location("external_reuse_gate", MODULE_PATH)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_artifact(**overrides):
    artifact = {
        "schema_version": "ExternalReuseAudit/v1",
        "change_id": "test-change",
        "EXISTING_IMPLEMENTATIONS_REVIEWED": [
            {"scope": "internal", "reference": "src/research_loop/gates.py",
             "finding": "existing gate owner"},
            {"scope": "external", "reference": "https://example.invalid/prior-art",
             "finding": "mature external pattern"},
        ],
        "REUSABLE_COMPONENTS": [
            {"reference": "src/research_loop/gates.py",
             "disposition": "EXTEND", "reason": "extend the existing owner"},
        ],
        "ADOPTED_PATTERN": "EXTEND",
        "WHY_NEW_CODE_IS_NECESSARY": (
            "The existing owner does not cover this boundary, so it is extended "
            "rather than replaced."
        ),
    }
    artifact.update(overrides)
    return artifact


# ---------------------------------------------------------------------------
# Architecture surface classification
# ---------------------------------------------------------------------------

def test_architecture_surface_classification():
    gate = _module()
    assert gate.is_architecture_path("src/research_loop/gates.py")
    assert gate.is_architecture_path("src/research_loop/providers/base.py")
    assert gate.is_architecture_path("src/rlr_maintenance/contracts.py")
    assert gate.is_architecture_path(".github/workflows/ci.yml")
    assert gate.is_architecture_path("templates/L4_fisher.md")
    assert gate.is_architecture_path("src/run_loop.py")
    assert gate.is_architecture_path("requirements-dev.txt")
    # Self-watch: the gate's own owners are on the architecture surface.
    assert gate.is_architecture_path("AGENTS.md")
    assert gate.is_architecture_path("docs/architecture/EXTERNAL_REUSE_GATE.md")
    assert gate.is_architecture_path("tools/external_reuse_gate.py")
    assert gate.architecture_area("AGENTS.md") == "governance"
    assert gate.architecture_area("tools/external_reuse_gate.py") == "governance"
    # Tests and other docs never trigger the gate on their own.
    assert not gate.is_architecture_path("tests/test_external_reuse_gate.py")
    assert not gate.is_architecture_path("README.md")
    assert not gate.is_architecture_path("docs/AGENT_CONTEXT.md")
    assert not gate.is_architecture_path(
        "docs/architecture/external-reuse/2026-09-23-external-reuse-gate.json"
    )
    assert not gate.is_architecture_path("")


def test_architecture_paths_filters_and_dedupes():
    gate = _module()
    paths = [
        "docs/readme.md",
        "src/research_loop/gates.py",
        "src\\research_loop\\gates.py",
        "tests/test_x.py",
        ".github/workflows/ci.yml",
    ]
    assert gate.architecture_paths(paths) == [
        "src/research_loop/gates.py",
        ".github/workflows/ci.yml",
    ]


# ---------------------------------------------------------------------------
# Artifact validation
# ---------------------------------------------------------------------------

def test_valid_artifact_has_no_violations():
    gate = _module()
    assert gate.validate_audit_artifact(_valid_artifact()) == []


def test_artifact_requires_internal_and_external_review():
    gate = _module()
    only_internal = _valid_artifact(
        EXISTING_IMPLEMENTATIONS_REVIEWED=[
            {"scope": "internal", "reference": "a", "finding": "b"},
        ]
    )
    codes = {v["code"] for v in gate.validate_audit_artifact(only_internal)}
    assert "reviewed_missing_external" in codes

    only_external = _valid_artifact(
        EXISTING_IMPLEMENTATIONS_REVIEWED=[
            {"scope": "external", "reference": "a", "finding": "b"},
        ]
    )
    codes = {v["code"] for v in gate.validate_audit_artifact(only_external)}
    assert "reviewed_missing_internal" in codes


def test_artifact_rejects_bad_decision_and_placeholders():
    gate = _module()
    bad = _valid_artifact(ADOPTED_PATTERN="BUILD")
    assert {v["code"] for v in gate.validate_audit_artifact(bad)} >= {"bad_adopted_pattern"}

    placeholder = _valid_artifact(WHY_NEW_CODE_IS_NECESSARY="n/a")
    codes = {v["code"] for v in gate.validate_audit_artifact(placeholder)}
    assert "why_placeholder" in codes


def test_artifact_create_requires_prior_evaluation():
    gate = _module()
    create_without = _valid_artifact(
        ADOPTED_PATTERN="CREATE",
        WHY_NEW_CODE_IS_NECESSARY=(
            "A genuinely new mechanism is required because no existing owner or "
            "external system provides this exact contract boundary."
        ),
        REUSABLE_COMPONENTS=[
            {"reference": "src/research_loop/gates.py",
             "disposition": "REJECT", "reason": "does not cover this boundary"},
        ],
    )
    codes = {v["code"] for v in gate.validate_audit_artifact(create_without)}
    assert "create_without_prior_evaluation" in codes

    create_with = _valid_artifact(
        ADOPTED_PATTERN="CREATE",
        WHY_NEW_CODE_IS_NECESSARY=(
            "A genuinely new mechanism is required because no existing owner or "
            "external system provides this exact contract boundary."
        ),
        REUSABLE_COMPONENTS=[
            {"reference": "src/research_loop/gates.py",
             "disposition": "EXTEND", "reason": "considered but insufficient"},
        ],
    )
    assert gate.validate_audit_artifact(create_with) == []


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------

def test_evaluate_not_applicable_without_architecture_paths(tmp_path):
    gate = _module()
    report = gate.evaluate(tmp_path, ["docs/readme.md", "tests/test_x.py"])
    assert report["status"] == "NOT_APPLICABLE"
    assert report["allowed_to_proceed"] is True
    assert report["architecture_paths"] == []


def test_evaluate_fails_closed_without_artifact(tmp_path):
    gate = _module()
    report = gate.evaluate(tmp_path, ["src/research_loop/gates.py"])
    assert report["status"] == "FAIL"
    assert report["allowed_to_proceed"] is False
    codes = {v["code"] for v in report["violations"]}
    assert "missing_audit_artifact" in codes


def test_evaluate_stale_artifact_on_disk_does_not_satisfy_gate(tmp_path):
    gate = _module()
    stale = tmp_path / "docs/architecture/external-reuse/stale.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps(_valid_artifact()), encoding="utf-8")
    # The artifact exists on disk but is not part of this change set.
    report = gate.evaluate(tmp_path, ["src/research_loop/gates.py"])
    assert report["status"] == "FAIL"
    assert "missing_audit_artifact" in {v["code"] for v in report["violations"]}


def test_evaluate_passes_with_valid_artifact_in_change(tmp_path):
    gate = _module()
    rel = "docs/architecture/external-reuse/change.json"
    artifact_path = tmp_path / rel
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(_valid_artifact()), encoding="utf-8")
    report = gate.evaluate(
        tmp_path, ["src/research_loop/gates.py", rel],
    )
    assert report["status"] == "PASS"
    assert report["allowed_to_proceed"] is True
    assert report["valid_audit_artifacts"] == [rel]
    assert report["architecture_areas"] == ["validation/recovery"]


def test_evaluate_fails_with_invalid_artifact_in_change(tmp_path):
    gate = _module()
    rel = "docs/architecture/external-reuse/bad.json"
    artifact_path = tmp_path / rel
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(
        json.dumps(_valid_artifact(ADOPTED_PATTERN="BUILD")), encoding="utf-8"
    )
    report = gate.evaluate(tmp_path, ["src/research_loop/gates.py", rel])
    assert report["status"] == "FAIL"
    assert "bad_adopted_pattern" in {v["code"] for v in report["violations"]}


# ---------------------------------------------------------------------------
# Unknown diff (fail closed)
# ---------------------------------------------------------------------------

def test_evaluate_unknown_diff_fails_closed(tmp_path):
    gate = _module()
    report = gate.evaluate(tmp_path, [], diff_known=False)
    assert report["status"] == "FAIL"
    assert report["allowed_to_proceed"] is False
    assert report["diff_known"] is False
    assert {v["code"] for v in report["violations"]} == {"unknown_diff"}
    # A known, empty change set is genuinely NOT_APPLICABLE; unknown is not.
    known_empty = gate.evaluate(tmp_path, [], diff_known=True)
    assert known_empty["status"] == "NOT_APPLICABLE"
    assert known_empty["allowed_to_proceed"] is True


def test_evaluate_unknown_diff_fails_closed_even_with_artifact(tmp_path):
    gate = _module()
    rel = "docs/architecture/external-reuse/change.json"
    artifact_path = tmp_path / rel
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(_valid_artifact()), encoding="utf-8")
    report = gate.evaluate(tmp_path, ["src/research_loop/gates.py", rel],
                           diff_known=False)
    assert report["status"] == "FAIL"
    assert report["violations"][0]["code"] == "unknown_diff"


# ---------------------------------------------------------------------------
# Self-watch
# ---------------------------------------------------------------------------

def test_evaluate_self_watch_tool_requires_artifact(tmp_path):
    gate = _module()
    report = gate.evaluate(tmp_path, ["tools/external_reuse_gate.py"])
    assert report["status"] == "FAIL"
    assert "missing_audit_artifact" in {v["code"] for v in report["violations"]}


def test_evaluate_self_watch_tool_with_valid_artifact_passes(tmp_path):
    gate = _module()
    rel = "docs/architecture/external-reuse/change.json"
    artifact_path = tmp_path / rel
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(_valid_artifact()), encoding="utf-8")
    report = gate.evaluate(
        tmp_path, ["tools/external_reuse_gate.py", "AGENTS.md", rel],
    )
    assert report["status"] == "PASS"
    assert report["allowed_to_proceed"] is True
    assert report["architecture_areas"] == ["governance"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_check_reads_name_status_and_exit_codes(tmp_path, capsys):
    gate = _module()
    rel = "docs/architecture/external-reuse/change.json"
    artifact_path = tmp_path / rel
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(_valid_artifact()), encoding="utf-8")
    changed = tmp_path / "changed.txt"
    changed.write_text(
        "M\tsrc/research_loop/gates.py\n" f"A\t{rel}\n", encoding="utf-8"
    )
    assert gate.main([
        "check", "--repo-root", str(tmp_path), "--changed", str(changed),
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"


def test_cli_check_unknown_diff_fails_closed(tmp_path, capsys):
    gate = _module()
    changed = tmp_path / "changed.txt"
    changed.write_text("src/research_loop/gates.py\n", encoding="utf-8")
    assert gate.main([
        "check", "--repo-root", str(tmp_path),
        "--changed", str(changed), "--diff-known", "false",
    ]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "FAIL"
    assert report["allowed_to_proceed"] is False
    assert report["violations"][0]["code"] == "unknown_diff"


def test_cli_check_missing_changed_file_fails_closed(tmp_path, capsys):
    gate = _module()
    assert gate.main([
        "check", "--repo-root", str(tmp_path),
        "--changed", str(tmp_path / "absent.txt"),
    ]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["allowed_to_proceed"] is False
    assert report["violations"][0]["code"] == "changed_list_missing"


def test_cli_validate(tmp_path, capsys):
    gate = _module()
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_valid_artifact()), encoding="utf-8")
    assert gate.main(["validate", str(good)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_valid_artifact(ADOPTED_PATTERN="BUILD")),
                   encoding="utf-8")
    assert gate.main(["validate", str(bad)]) == 1
    assert json.loads(capsys.readouterr().out)["valid"] is False
