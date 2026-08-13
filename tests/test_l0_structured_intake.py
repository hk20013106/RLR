"""End-to-end and unit tests for structured frontmatter intake (Task 2.1 - 2.8)."""
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from research_loop import l0_contract, l0_intake, l0_plan_intake
from research_loop.commands import lifecycle

ROOT = Path(__file__).resolve().parents[1]
RL = str(ROOT / "research_loop_v04.py")


def _run(*args):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run([sys.executable, RL, *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)


def _new_project(tmp_path):
    project = tmp_path / "P"
    result = _run("new-project", str(project), "Structured intake test")
    assert result.returncode == 0, result.stderr
    return project


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_no_circular_import():
    """Verify l0_plan_intake.py does not import l0_intake.py."""
    assert hasattr(l0_plan_intake, "detect_intake_schema")
    assert not hasattr(l0_plan_intake, "l0_intake")
    if "research_loop.l0_intake" in sys.modules:
        del sys.modules["research_loop.l0_intake"]
    import importlib
    importlib.reload(l0_plan_intake)
    assert "research_loop.l0_intake" not in sys.modules


def test_valid_structured_preplan_produces_schema_11_contract(tmp_path):
    """Valid structured preplan produces a valid schema-1.1 contract passing canonical validation."""
    project = _new_project(tmp_path)
    data_dir = project / "data"
    data_dir.mkdir()
    f1 = data_dir / "samples.csv"
    f2 = data_dir / "report.MD"
    f1.write_bytes(b"col1,col2\n1,2\n")
    f2.write_bytes(b"# Report\n")

    request_text = (
        f"---\n"
        f"intake_schema: 'research-loop-plan/1.0'\n"
        f"round_id: '1'\n"
        f"scientific_question: 'Does Mogera sp. carry introgression?'\n"
        f"current_round:\n"
        f"  hypothesis: 'Introgression signal exists in ancestral population.'\n"
        f"source_input:\n"
        f"  file_manifest:\n"
        f"    - path: '{f1.as_posix()}'\n"
        f"      role: 'genotypes'\n"
        f"      bytes: {f1.stat().st_size}\n"
        f"      sha256: '{_sha256_bytes(f1.read_bytes())}'\n"
        f"    - path: '{f2.as_posix()}'\n"
        f"      role: 'documentation'\n"
        f"      bytes: {f2.stat().st_size}\n"
        f"      sha256: '{_sha256_bytes(f2.read_bytes())}'\n"
        f"research_plan:\n"
        f"  goal: 'Detect introgression'\n"
        f"---\n"
    )
    request_path = tmp_path / "preplan.md"
    request_path.write_bytes(request_text.encode("utf-8"))

    result = l0_intake.normalize_request(request_path, request_text, "C_TEST0001", data=str(data_dir))
    assert result["missing_fields"] == []
    assert result["errors"] == []
    contract = result["contract"]
    assert contract is not None

    # Contract assertions
    assert contract["schema_version"] == "1.1"
    assert contract["round_type"] == "initial"
    assert contract["candidate_id"] == "C_TEST0001"
    assert contract["round_id"] == "1"

    # Provenance snapshot assertions
    prov = contract["provenance"]
    assert prov["parser_mode"] == "plan-v1"
    assert prov["manifest_verified"] is True
    assert prov["research_plan_snapshot_path"] == "01_Candidates/_research_plans/C_TEST0001.md"
    assert prov["research_plan_snapshot_sha256"] == _sha256_bytes(request_text.encode("utf-8"))

    # Validate against canonical validator
    val_errors = l0_contract.validate_l0_input_contract(contract, {}, project, "C_TEST0001")
    assert val_errors == [], val_errors


def test_cli_non_dry_run_writes_all_three_files(tmp_path):
    """CLI normalize-l0-input non-dry-run writes candidate .md, sidecar .l0_input.yaml, and snapshot."""
    project = _new_project(tmp_path)
    sample = project / "data.csv"
    sample.write_bytes(b"col1\n1\n")

    request_bytes = (
        f"---\n"
        f"intake_schema: 'research-loop-plan/1.0'\n"
        f"round_id: '1'\n"
        f"scientific_question: 'Real run question?'\n"
        f"current_round:\n"
        f"  hypothesis: 'Real run hypothesis.'\n"
        f"source_input:\n"
        f"  file_manifest:\n"
        f"    - path: '{sample.as_posix()}'\n"
        f"      role: 'input'\n"
        f"      bytes: {sample.stat().st_size}\n"
        f"      sha256: '{_sha256_bytes(sample.read_bytes())}'\n"
        f"research_plan: {{'goal': 'g'}}\n"
        f"---\n"
    ).encode("utf-8")

    request = tmp_path / "preplan.md"
    request.write_bytes(request_bytes)

    result = _run("normalize-l0-input", "--project", str(project),
                  "--input", str(request), "--data", str(project))

    assert result.returncode == 0, result.stderr
    assert "Contract valid: yes" in result.stdout

    cand_files = list((project / "01_Candidates").glob("C*.md"))
    assert len(cand_files) == 1
    cand_id = cand_files[0].stem

    sidecar = project / "01_Candidates" / f"{cand_id}.l0_input.yaml"
    assert sidecar.exists()

    snapshot_path = project / "01_Candidates" / "_research_plans" / f"{cand_id}.md"
    assert snapshot_path.exists()
    assert snapshot_path.read_bytes() == request_bytes


def test_rollback_on_write_contract_failure(tmp_path, monkeypatch, capsys):
    """Simulated failure during write_contract rolls back the candidate file."""
    project = _new_project(tmp_path)
    sample = project / "data.csv"
    sample.write_bytes(b"col1\n1\n")

    request = tmp_path / "preplan.md"
    request.write_text(
        f"---\n"
        f"intake_schema: 'research-loop-plan/1.0'\n"
        f"round_id: '1'\n"
        f"scientific_question: 'Question?'\n"
        f"current_round:\n"
        f"  hypothesis: 'Hypothesis.'\n"
        f"source_input:\n"
        f"  file_manifest:\n"
        f"    - path: '{sample.as_posix()}'\n"
        f"      role: 'input'\n"
        f"      bytes: {sample.stat().st_size}\n"
        f"      sha256: '{_sha256_bytes(sample.read_bytes())}'\n"
        f"research_plan: {{'goal': 'g'}}\n"
        f"---\n",
        encoding="utf-8")

    def mock_write_contract(*args, **kwargs):
        raise IOError("Disk full simulation during write_contract")

    monkeypatch.setattr(l0_contract, "write_contract", mock_write_contract)

    args = SimpleNamespace(
        project=str(project),
        input=str(request),
        data=str(project),
        dataset=None,
        from_memory=None,
        loop_type=None,
        dry_run=False,
        run_l0=False,
        knowledge_store=None,
    )
    rc = lifecycle.cmd_normalize_l0_input(args)
    stderr = capsys.readouterr().err

    assert rc == 2
    assert "structured intake write failed: Disk full simulation" in stderr
    assert "rolled back" in stderr

    # Candidate md and sidecar and snapshot must not exist
    assert not list((project / "01_Candidates").glob("C*.md"))
    assert not list((project / "01_Candidates").glob("C*.l0_input.yaml"))
    assert not (project / "01_Candidates" / "_research_plans").exists()


def test_rollback_on_snapshot_write_failure_removes_candidate_and_sidecar_and_empty_plans_dir(tmp_path, monkeypatch, capsys):
    """Simulated failure writing snapshot removes candidate, sidecar, and empty _research_plans directory."""
    project = _new_project(tmp_path)
    sample = project / "data.csv"
    sample.write_bytes(b"col1\n1\n")

    request = tmp_path / "preplan.md"
    request.write_text(
        f"---\n"
        f"intake_schema: 'research-loop-plan/1.0'\n"
        f"round_id: '1'\n"
        f"scientific_question: 'Question?'\n"
        f"current_round:\n"
        f"  hypothesis: 'Hypothesis.'\n"
        f"source_input:\n"
        f"  file_manifest:\n"
        f"    - path: '{sample.as_posix()}'\n"
        f"      role: 'input'\n"
        f"      bytes: {sample.stat().st_size}\n"
        f"      sha256: '{_sha256_bytes(sample.read_bytes())}'\n"
        f"research_plan: {{'goal': 'g'}}\n"
        f"---\n",
        encoding="utf-8")

    orig_write_bytes = Path.write_bytes

    def mock_write_bytes(self, data):
        if "_research_plans" in str(self):
            raise PermissionError("Permission denied simulation on snapshot write")
        return orig_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", mock_write_bytes)

    args = SimpleNamespace(
        project=str(project),
        input=str(request),
        data=str(project),
        dataset=None,
        from_memory=None,
        loop_type=None,
        dry_run=False,
        run_l0=False,
        knowledge_store=None,
    )
    rc = lifecycle.cmd_normalize_l0_input(args)
    stderr = capsys.readouterr().err

    assert rc == 2
    assert "structured intake write failed: Permission denied" in stderr
    assert "rolled back" in stderr

    # Candidate, sidecar, and snapshot directory must be cleaned up
    assert not list((project / "01_Candidates").glob("C*.md"))
    assert not list((project / "01_Candidates").glob("C*.l0_input.yaml"))
    assert not (project / "01_Candidates" / "_research_plans").exists()


def test_rollback_preserves_preexisting_research_plans_dir(tmp_path, monkeypatch, capsys):
    """Rollback does not delete a pre-existing _research_plans directory."""
    project = _new_project(tmp_path)
    plans_dir = project / "01_Candidates" / "_research_plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    preexisting_file = plans_dir / "old_plan.txt"
    preexisting_file.write_text("old", encoding="utf-8")

    sample = project / "data.csv"
    sample.write_bytes(b"col1\n1\n")

    request = tmp_path / "preplan.md"
    request.write_text(
        f"---\n"
        f"intake_schema: 'research-loop-plan/1.0'\n"
        f"round_id: '1'\n"
        f"scientific_question: 'Question?'\n"
        f"current_round:\n"
        f"  hypothesis: 'Hypothesis.'\n"
        f"source_input:\n"
        f"  file_manifest:\n"
        f"    - path: '{sample.as_posix()}'\n"
        f"      role: 'input'\n"
        f"      bytes: {sample.stat().st_size}\n"
        f"      sha256: '{_sha256_bytes(sample.read_bytes())}'\n"
        f"research_plan: {{'goal': 'g'}}\n"
        f"---\n",
        encoding="utf-8")

    orig_write_bytes = Path.write_bytes

    def mock_write_bytes(self, data):
        if "_research_plans" in str(self) and "old_plan" not in str(self):
            raise IOError("Simulated snapshot write error")
        return orig_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", mock_write_bytes)

    args = SimpleNamespace(
        project=str(project),
        input=str(request),
        data=str(project),
        dataset=None,
        from_memory=None,
        loop_type=None,
        dry_run=False,
        run_l0=False,
        knowledge_store=None,
    )
    rc = lifecycle.cmd_normalize_l0_input(args)
    stderr = capsys.readouterr().err

    assert rc == 2
    assert "structured intake write failed" in stderr

    # Pre-existing directory and file must be preserved
    assert plans_dir.exists()
    assert preexisting_file.exists()


def test_preexisting_target_collision_rejected(tmp_path, monkeypatch, capsys):
    """Pre-existing target artifact causes fail-closed result without deleting existing file."""
    project = _new_project(tmp_path)
    sample = project / "data.csv"
    sample.write_bytes(b"col1\n1\n")

    cand_file = project / "01_Candidates" / "C_COLLISION.md"
    cand_file.parent.mkdir(parents=True, exist_ok=True)
    cand_file.write_text("existing content", encoding="utf-8")

    request = tmp_path / "preplan.md"
    request.write_text(
        f"---\n"
        f"intake_schema: 'research-loop-plan/1.0'\n"
        f"round_id: '1'\n"
        f"scientific_question: 'Question?'\n"
        f"current_round:\n"
        f"  hypothesis: 'Hypothesis.'\n"
        f"source_input:\n"
        f"  file_manifest:\n"
        f"    - path: '{sample.as_posix()}'\n"
        f"      role: 'input'\n"
        f"      bytes: {sample.stat().st_size}\n"
        f"      sha256: '{_sha256_bytes(sample.read_bytes())}'\n"
        f"research_plan: {{'goal': 'g'}}\n"
        f"---\n",
        encoding="utf-8")

    args = SimpleNamespace(
        project=str(project),
        input=str(request),
        data=str(project),
        dataset=None,
        from_memory=None,
        loop_type=None,
        dry_run=False,
        run_l0=False,
        knowledge_store=None,
    )
    monkeypatch.setattr(lifecycle, "_stamp", lambda: "_COLLISION")
    rc = lifecycle.cmd_normalize_l0_input(args)
    stderr = capsys.readouterr().err

    assert rc == 2
    assert ("candidate id collision" in stderr or "target file already exists" in stderr)
    assert cand_file.read_text(encoding="utf-8") == "existing content"


def test_cli_dry_run_writes_no_files_or_snapshot_dir(tmp_path):
    """CLI normalize-l0-input --dry-run writes no candidate, sidecar, or snapshot files/dirs."""
    project = _new_project(tmp_path)
    sample = project / "data.csv"
    sample.write_bytes(b"col1\n1\n")

    request = tmp_path / "preplan.md"
    request.write_text(
        f"---\n"
        f"intake_schema: 'research-loop-plan/1.0'\n"
        f"round_id: '1'\n"
        f"scientific_question: 'Dry run question?'\n"
        f"current_round:\n"
        f"  hypothesis: 'Dry run hypothesis.'\n"
        f"source_input:\n"
        f"  file_manifest:\n"
        f"    - path: '{sample.as_posix()}'\n"
        f"      role: 'input'\n"
        f"      bytes: {sample.stat().st_size}\n"
        f"      sha256: '{_sha256_bytes(sample.read_bytes())}'\n"
        f"research_plan: {{'goal': 'g'}}\n"
        f"---\n",
        encoding="utf-8")

    result = _run("normalize-l0-input", "--project", str(project),
                  "--input", str(request), "--data", str(project), "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "Contract valid: yes" in result.stdout
    assert not list((project / "01_Candidates").glob("*"))


def test_rules_v1_intake_does_not_create_snapshot_dir(tmp_path):
    """Rules-v1 intake does not create _research_plans directory or snapshot files."""
    project = _new_project(tmp_path)
    data_file = project / "data.tsv"
    data_file.write_text("x\n", encoding="utf-8")

    request = tmp_path / "rules_req.md"
    request.write_text(
        "科学问题：规则一提取问题？\n"
        "本轮新假说：规则一提取假说。\n",
        encoding="utf-8")

    result = _run("normalize-l0-input", "--project", str(project),
                  "--input", str(request), "--data", str(data_file))

    assert result.returncode == 0, result.stderr
    assert not (project / "01_Candidates" / "_research_plans").exists()


def test_unclosed_leading_delimiter_uses_rules_v1(tmp_path):
    """Unclosed leading delimiter falls back to rules-v1 parsing (Bug 1 behavior preserved)."""
    request_text = (
        "---\n"
        "intake_schema: 'research-loop-plan/1.0'\n"
        "科学问题：未闭合 delimiter 的问题？\n"
        "本轮新假说：未闭合 delimiter 的假说。\n"
    )
    frontmatter_text, body_text = l0_intake._split_frontmatter(request_text)
    assert frontmatter_text is None
    result = l0_intake.normalize_request(tmp_path / "req.md", request_text, "C_TEST", data=str(tmp_path))
    assert result["contract"] is not None
    assert result["contract"]["provenance"]["parser_mode"] == "rules-v1"


def test_body_frontmatter_matching_accepted(tmp_path):
    """Matching body and frontmatter scientific_question and hypothesis are accepted."""
    sample = tmp_path / "d.txt"
    sample.write_bytes(b"x")
    request_text = (
        f"---\n"
        f"intake_schema: 'research-loop-plan/1.0'\n"
        f"round_id: '1'\n"
        f"scientific_question: 'Frontmatter question?'\n"
        f"current_round:\n"
        f"  hypothesis: 'Frontmatter hypothesis.'\n"
        f"source_input:\n"
        f"  file_manifest:\n"
        f"    - path: '{sample.as_posix()}'\n"
        f"      role: 'input'\n"
        f"      bytes: 1\n"
        f"      sha256: '{_sha256_bytes(b'x')}'\n"
        f"research_plan: {{'goal': 'g'}}\n"
        f"---\n"
        f"科学问题：Frontmatter question?\n"
        f"本轮新假说：Frontmatter hypothesis.\n"
    )
    result = l0_intake.normalize_request(tmp_path / "req.md", request_text, "C_TEST", data=str(tmp_path))
    assert result["missing_fields"] == []
    assert result["errors"] == []


def test_body_frontmatter_conflicting_rejected(tmp_path):
    """Conflicting body vs frontmatter question or hypothesis is rejected."""
    sample = tmp_path / "d.txt"
    sample.write_bytes(b"x")
    request_text = (
        f"---\n"
        f"intake_schema: 'research-loop-plan/1.0'\n"
        f"round_id: '1'\n"
        f"scientific_question: 'Frontmatter question?'\n"
        f"current_round:\n"
        f"  hypothesis: 'Frontmatter hypothesis.'\n"
        f"source_input:\n"
        f"  file_manifest:\n"
        f"    - path: '{sample.as_posix()}'\n"
        f"      role: 'input'\n"
        f"      bytes: 1\n"
        f"      sha256: '{_sha256_bytes(b'x')}'\n"
        f"research_plan: {{'goal': 'g'}}\n"
        f"---\n"
        f"科学问题：Conflicting body question？\n"
        f"本轮新假说：Conflicting body hypothesis。\n"
    )
    result = l0_intake.normalize_request(tmp_path / "req.md", request_text, "C_TEST", data=str(tmp_path))
    assert result["contract"] is None
    assert any("conflicts with frontmatter" in err for err in result["errors"])


def test_missing_or_empty_research_plan_rejected(tmp_path):
    """Missing or empty research_plan mapping is rejected."""
    request_text = (
        "---\n"
        "intake_schema: 'research-loop-plan/1.0'\n"
        "round_id: '1'\n"
        "scientific_question: 'Q?'\n"
        "current_round:\n"
        "  hypothesis: 'H.'\n"
        "source_input:\n"
        "  file_manifest: [{'path': 'a'}]\n"
        "research_plan: {}\n"
        "---\n"
    )
    result = l0_intake.normalize_request(tmp_path / "req.md", request_text, "C_TEST")
    assert "research_plan" in result["missing_fields"]


def test_duplicate_nested_key_rejected():
    """Duplicate nested YAML key is rejected with line number."""
    yaml_text = (
        "---\n"
        "intake_schema: 'research-loop-plan/1.0'\n"
        "source_input:\n"
        "  location: 'a'\n"
        "  location: 'b'\n"
        "---\n"
    )
    parsed, errors = l0_plan_intake.parse_frontmatter_strict(yaml_text)
    assert parsed is None
    assert any("duplicate YAML key 'location'" in err for err in errors)


def test_manifest_entry_not_a_mapping_fails(tmp_path):
    """Manifest entry that is a string instead of a mapping fails."""
    project = _new_project(tmp_path)
    request = tmp_path / "req.md"
    request.write_text(
        "---\n"
        "intake_schema: 'research-loop-plan/1.0'\n"
        "round_id: '1'\n"
        "scientific_question: 'Q?'\n"
        "current_round:\n"
        "  hypothesis: 'H.'\n"
        "source_input:\n"
        "  file_manifest:\n"
        "    - 'just a string'\n"
        "research_plan: {'goal': 'g'}\n"
        "---\n",
        encoding="utf-8")

    result = _run("normalize-l0-input", "--project", str(project), "--input", str(request), "--data", str(project))
    assert result.returncode == 2
    assert "source_input.file_manifest[0] must be a mapping" in result.stderr
    assert not list((project / "01_Candidates").glob("*"))


def test_duplicate_top_level_key_rejected():
    """Duplicate top-level key is rejected with key name and line number."""
    yaml_text = (
        "---\n"
        "intake_schema: 'research-loop-plan/1.0'\n"
        "scientific_question: 'Question 1'\n"
        "scientific_question: 'Question 2'\n"
        "---\n"
    )
    parsed, errors = l0_plan_intake.parse_frontmatter_strict(yaml_text)
    assert parsed is None
    assert len(errors) == 1
    assert "duplicate YAML key 'scientific_question'" in errors[0]
    assert "line 4" in errors[0]


def test_unsupported_intake_schema_rejected(tmp_path):
    """Unsupported intake_schema returns RC=2 listing supported value and writes no artifacts."""
    project = _new_project(tmp_path)
    data_file = project / "data.tsv"
    data_file.write_text("x\n", encoding="utf-8")
    request = tmp_path / "bad_schema.md"
    request.write_text(
        "---\n"
        "intake_schema: 'research-loop-plan/99.0'\n"
        "---\n",
        encoding="utf-8")

    result = _run("normalize-l0-input", "--project", str(project),
                  "--input", str(request), "--data", str(data_file))

    assert result.returncode == 2
    assert "unsupported intake_schema 'research-loop-plan/99.0'" in result.stderr
    assert "supported value is 'research-loop-plan/1.0'" in result.stderr
    assert not list((project / "01_Candidates").glob("*"))


def test_structured_continuation_round_type_rejected(tmp_path):
    """round_type: continuation returns RC=2 with v0.9 unsupported message."""
    project = _new_project(tmp_path)
    data_file = project / "data.tsv"
    data_file.write_text("x\n", encoding="utf-8")
    request = tmp_path / "continuation_plan.md"
    request.write_text(
        "---\n"
        "intake_schema: 'research-loop-plan/1.0'\n"
        "round_type: continuation\n"
        "---\n",
        encoding="utf-8")

    result = _run("normalize-l0-input", "--project", str(project),
                  "--input", str(request), "--data", str(data_file))

    assert result.returncode == 2
    assert "structured continuation rounds are not supported in v0.9" in result.stderr
    assert not list((project / "01_Candidates").glob("*"))


def test_normal_rules_v1_request_uses_rules_v1_path(tmp_path):
    """Normal request without frontmatter uses rules-v1 path."""
    request_text = (
        "科学问题：测试问题？\n"
        "本轮新假说：测试假说。\n"
    )
    result = l0_intake.normalize_request(
        tmp_path / "req.md", request_text, "C_TEST", data=str(tmp_path)
    )
    assert result["contract"] is not None
    assert result["contract"]["provenance"]["parser_mode"] == "rules-v1"


def test_closed_frontmatter_without_intake_schema_falls_back_to_rules_v1(tmp_path):
    """Closed frontmatter lacking intake_schema falls back to rules-v1 extraction."""
    request_text = (
        "---\n"
        "title: custom header\n"
        "---\n"
        "科学问题：带普通frontmatter的问题？\n"
        "本轮新假说：带普通frontmatter的假说。\n"
    )
    frontmatter_text, body_text = l0_intake._split_frontmatter(request_text)
    assert frontmatter_text is not None
    assert not l0_plan_intake.detect_intake_schema(frontmatter_text)

    result = l0_intake.normalize_request(
        tmp_path / "req.md", request_text, "C_TEST", data=str(tmp_path)
    )
    assert result["contract"] is not None
    assert result["contract"]["scientific_question"] == "带普通frontmatter的问题？"
    assert result["contract"]["current_round"]["hypothesis"] == "带普通frontmatter的假说。"


def test_conflict_comparison_normalization_cjk_block_scalar_folding(tmp_path):
    """YAML block scalar line folding adding space around Chinese characters/punctuation is accepted as non-conflicting."""
    sample = tmp_path / "d.txt"
    sample.write_bytes(b"x")
    # Frontmatter has block scalar hypo with line fold space: "模块， 并且"
    # Body has un-folded Chinese text: "模块，并且"
    request_text = (
        f"---\n"
        f"intake_schema: 'research-loop-plan/1.0'\n"
        f"round_id: '1'\n"
        f"scientific_question: '构建物种特异性分析模块？'\n"
        f"current_round:\n"
        f"  hypothesis: >-\n"
        f"    构建物种特异性分析模块，\n"
        f"    并且评估群体推断。\n"
        f"source_input:\n"
        f"  file_manifest:\n"
        f"    - path: '{sample.as_posix()}'\n"
        f"      role: 'input'\n"
        f"      bytes: 1\n"
        f"      sha256: '{_sha256_bytes(b'x')}'\n"
        f"research_plan: {{'goal': 'g'}}\n"
        f"---\n"
        f"科学问题：构建物种特异性分析模块？\n"
        f"本轮新假说：构建物种特异性分析模块，并且评估群体推断。\n"
    )
    result = l0_intake.normalize_request(tmp_path / "req.md", request_text, "C_TEST", data=str(tmp_path))
    assert result["missing_fields"] == []
    assert result["errors"] == []
    contract = result["contract"]
    assert contract is not None
    # Verify original YAML value stored in contract is preserved (not stripped of spaces)
    assert contract["current_round"]["hypothesis"] == "构建物种特异性分析模块， 并且评估群体推断。"


def test_conflict_comparison_normalization_preserves_english_word_spaces():
    """Conflict normalization removes CJK line fold spaces but preserves English word spaces."""
    norm = l0_plan_intake._normalize_conflict_text
    assert norm("模块， 并且") == "模块，并且"
    assert norm("Does Mogera sp. carry introgression?") == "Does Mogera sp. carry introgression?"
    assert norm("carry introgression") != norm("carryintrogression")

