"""Regression tests for the execution gate's input_manifest.md validation
(Bug 3): the gate must reject a manifest that is still the unfilled template
or lists no verifiable input rows, not merely check that the file exists."""
from pathlib import Path
from types import SimpleNamespace

import research_loop.engine  # noqa: F401 -- wires common._decision_log_template
from research_loop.commands.execution import cmd_execution_gate
from research_loop.common import _mkdirs
from research_loop.paths import _candidate_file
from research_loop.templates import _candidate_template
from research_loop.yamlio import _replace_field

TEMPLATE_MANIFEST = """---
project_name: "P"
preflight_file: input_manifest.md
owner: Linnaeus
created_at: "2026-01-01T00:00:00"
---

# Input Manifest - P

## Input classification

| alias | full path | key files | format | classification | verified | notes |
|-------|-----------|-----------|--------|----------------|----------|-------|
_READ EACH input alias from candidate frontmatter. One row per input. Fill ALL columns. Do NOT leave template rows._

## Required inputs for execution
"""


def _make_candidate(project_dir, cand_id, alias):
    project_dir = Path(project_dir)
    _mkdirs(project_dir)
    body = _candidate_template(cand_id, "T", "src", "Q?", "H", input_alias=alias)
    cf = _candidate_file(project_dir, cand_id)
    cf.write_text(body, encoding="utf-8")
    _replace_field(cf, "current_status", "METHOD_APPROVED")
    return cf


def _write_preflight(project_dir, manifest_text):
    pf = Path(project_dir) / "00_Preflight"
    pf.mkdir(parents=True, exist_ok=True)
    (pf / "skill_use_plan.md").write_text("plan\n", encoding="utf-8")
    (pf / "input_manifest.md").write_text(manifest_text, encoding="utf-8")


def test_unfilled_template_manifest_rejects(tmp_path, capsys):
    _make_candidate(tmp_path, "C1", "ds1")
    _write_preflight(tmp_path, TEMPLATE_MANIFEST)

    rc = cmd_execution_gate(SimpleNamespace(project_dir=str(tmp_path), cand_id="C1"))

    out = capsys.readouterr().out
    assert rc == 1
    assert "EXECUTION GATE: REJECT" in out
    assert "unfilled" in out
    assert "input_manifest.md ........ OK" not in out


def test_manifest_with_zero_data_rows_and_no_marker_still_rejects(tmp_path, capsys):
    manifest = (
        "| alias | full path | key files | format | classification | verified | notes |\n"
        "|-------|-----------|-----------|--------|----------------|----------|-------|\n"
    )
    _make_candidate(tmp_path, "C1", "ds1")
    _write_preflight(tmp_path, manifest)

    rc = cmd_execution_gate(SimpleNamespace(project_dir=str(tmp_path), cand_id="C1"))

    out = capsys.readouterr().out
    assert rc == 1
    assert "EXECUTION GATE: REJECT" in out
    assert "unfilled" in out


def test_filled_manifest_with_matching_alias_passes(tmp_path, capsys):
    data_dir = Path(tmp_path) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "a.tsv").write_text("x\n", encoding="utf-8")
    manifest = (
        "| alias | full path | key files | format | classification | verified | notes |\n"
        "|-------|-----------|-----------|--------|----------------|----------|-------|\n"
        f"| ds1 | {data_dir} | `a.tsv` | tsv | primary | yes | ok |\n"
    )
    _make_candidate(tmp_path, "C1", "ds1")
    _write_preflight(tmp_path, manifest)

    rc = cmd_execution_gate(SimpleNamespace(project_dir=str(tmp_path), cand_id="C1"))

    out = capsys.readouterr().out
    assert rc == 0, out
    assert "EXECUTION GATE: PASS" in out
    assert "input_manifest.md ........ OK (1 input(s) registered)" in out


def test_filled_manifest_with_missing_key_file_rejects(tmp_path, capsys):
    data_dir = Path(tmp_path) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest = (
        "| alias | full path | key files | format | classification | verified | notes |\n"
        "|-------|-----------|-----------|--------|----------------|----------|-------|\n"
        f"| ds1 | {data_dir} | `missing.tsv` | tsv | primary | yes | ok |\n"
    )
    _make_candidate(tmp_path, "C1", "ds1")
    _write_preflight(tmp_path, manifest)

    rc = cmd_execution_gate(SimpleNamespace(project_dir=str(tmp_path), cand_id="C1"))

    out = capsys.readouterr().out
    assert rc == 1
    assert "EXECUTION GATE: REJECT" in out
    assert "missing required input: ds1/missing.tsv" in out
