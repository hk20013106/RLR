import json
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop import deep_research as dr
from research_loop import gates
from research_loop import engine
from research_loop.preresearch import PRE_RESEARCH_MAP
import run_loop


def _payload():
    return {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": ["cardiac adaptation"],
        "papers": [{
            "doi": "10.1000/example", "pmid": "123456", "url": "https://example.org/paper",
            "title": "Example study", "source_database": "Europe PMC",
            "metadata": {"year": 2026, "journal": "Example Journal"},
            "source_metadata_response": {"id": "123456", "title": "Example study"},
            "open_access": True, "content_type": "text/html",
            "source_payload": "<article>open-access source text</article>",
            "extracts": [
                {"section": "Results", "text": "Observed cardiac adaptation.", "locator": "Results paragraph 2"},
                {"section": "Discussion", "text": "The result supports the mechanism.", "locator": "Discussion paragraph 1"},
                {"section": "Conclusion", "text": "Adaptation is plausible.", "locator": "Conclusion"},
                {"section": "Methods", "text": "RNA-seq was analysed with a signed network.", "locator": "Methods paragraph 3"},
            ],
        }],
    }


def test_codex_command_explicitly_invokes_academic_research_suite(tmp_path):
    spec = dr.RuntimeSpec(backend="codex", executable="codex")
    command, prompt = dr.build_invocation(spec, "L1", "Q", "H", tmp_path)
    assert command[:2] == ["codex", "exec"]
    assert "$academic-research-suite" in prompt
    assert "Results" in prompt and "Conclusion" in prompt


def test_claude_command_requires_plugin_dir_and_ars_alias(tmp_path):
    spec = dr.RuntimeSpec(backend="claude", executable="claude", plugin_dir="C:/ars")
    command, prompt = dr.build_invocation(spec, "L4", "Q", "H", tmp_path)
    assert command[:4] == ["claude", "-p", "--plugin-dir", "C:/ars"]
    assert "/ars-lit-review" in prompt
    with pytest.raises(dr.DeepResearchError, match="plugin_dir"):
        dr.build_invocation(dr.RuntimeSpec(backend="claude", executable="claude"), "L4", "Q", "H", tmp_path)


def test_l85_invocation_includes_actual_l7_l8_results(tmp_path):
    _, prompt = dr.build_invocation(dr.RuntimeSpec(backend="codex", executable="codex"),
                                    "L8.5", "Q", "H", tmp_path,
                                    result_context='{"L7_key_results": {"gene": "ACTC1"}}')
    assert "Actual L7/L8 findings to verify" in prompt
    assert "ACTC1" in prompt


def test_persisted_open_access_paper_keeps_source_and_extracts(tmp_path):
    artifact = dr.persist_run(
        tmp_path, "C1", "L1", _payload(),
        dr.skill_receipt("codex", ["codex", "exec"], "prompt", "0.1.9", model="gpt-test"),
    )
    assert artifact["status"] == "completed"
    assert artifact["skill_receipt"]["provider"] == "codex"
    assert artifact["skill_receipt"]["model"] == "gpt-test"
    assert artifact["skill_receipt"]["upstream"].endswith("academic-research-skills-codex")
    record = next((tmp_path / "09_Literature_Database" / "evidence_packs" / "papers").glob("*.json"))
    saved = json.loads(record.read_text(encoding="utf-8"))
    assert saved["open_access"] is True
    assert saved["source_payload_path"].endswith(".html")
    assert saved["metadata_response_hash"]
    assert saved["source_metadata_response"]["id"] == "123456"
    assert {x["section"] for x in saved["evidence_extracts"]} >= {"Results", "Discussion", "Conclusion"}
    assert (tmp_path / saved["source_payload_path"]).exists()


def test_changed_paper_payload_creates_a_new_immutable_record(tmp_path):
    first = dr.persist_run(tmp_path, "C1", "L1", _payload(),
                           dr.skill_receipt("codex", ["codex", "exec"], "one", "0.1.9"))
    changed = _payload()
    changed["papers"][0]["extracts"][0]["text"] = "A corrected result."
    second = dr.persist_run(tmp_path, "C1", "L1", changed,
                            dr.skill_receipt("codex", ["codex", "exec"], "two", "0.1.9"))
    assert first["papers"][0]["paper_id"] != second["papers"][0]["paper_id"]
    records = list((tmp_path / "09_Literature_Database" / "evidence_packs" / "papers").glob("*.json"))
    assert len(records) == 2


def test_l1_contract_rejects_missing_results_discussion_or_conclusion(tmp_path):
    payload = _payload()
    payload["papers"][0]["extracts"] = payload["papers"][0]["extracts"][:2]
    artifact = dr.persist_run(
        tmp_path, "C1", "L1", payload,
        dr.skill_receipt("codex", ["codex", "exec"], "prompt", "0.1.9"),
    )
    ok, reason = dr.audit_evidence_pack(tmp_path, "C1", "L1")
    assert artifact["status"] == "completed"
    assert ok is False and "Conclusion" in reason


def test_l4_contract_accepts_primary_methods_and_review_search_miss(tmp_path):
    payload = _payload()
    payload["review_search"] = {"query": "systematic review network analysis", "status": "none_found", "receipt": "Europe PMC 0"}
    dr.persist_run(tmp_path, "C1", "L4", payload,
                   dr.skill_receipt("codex", ["codex", "exec"], "prompt", "0.1.9"))
    ok, reason = dr.audit_evidence_pack(tmp_path, "C1", "L4")
    assert ok is True, reason


def test_l4_contract_requires_results_and_conclusion_when_review_was_found(tmp_path):
    payload = _payload()
    payload["review_search"] = {"query": "review network analysis", "status": "completed", "receipt": "Europe PMC 1"}
    dr.persist_run(tmp_path, "C1", "L4", payload,
                   dr.skill_receipt("codex", ["codex", "exec"], "prompt", "0.1.9"))
    ok, reason = dr.audit_evidence_pack(tmp_path, "C1", "L4")
    assert ok is False and "review" in reason.lower()


def test_l10_digest_renders_only_located_evidence(tmp_path):
    dr.persist_run(tmp_path, "C1", "L1", _payload(),
                   dr.skill_receipt("codex", ["codex", "exec"], "prompt", "0.1.9"))
    digest = dr.render_evidence_digest(tmp_path, "C1", ["L1"])
    assert "Evidence IDs" in digest
    assert "Results paragraph 2" in digest
    assert "open-access source text" not in digest


def test_l85_contract_requires_a_cited_verification_verdict(tmp_path):
    payload = _payload()
    dr.persist_run(tmp_path, "C1", "L8.5", payload,
                   dr.skill_receipt("codex", ["codex", "exec"], "prompt", "0.1.9"),
                   result_context='{"L7_key_results": {"gene": "ACTC1"}}')
    ok, reason = dr.audit_evidence_pack(tmp_path, "C1", "L8.5")
    assert ok is False and "verification" in reason.lower()
    artifact = dr._latest_artifact(tmp_path, "C1", "L8.5")
    evidence_id = artifact["papers"][0]["evidence_ids"][0]
    artifact["verification"] = [{"finding": "ACTC1", "verdict": "supports", "evidence_ids": [evidence_id]}]
    run_path = tmp_path / "09_Literature_Database" / "evidence_packs" / "runs" / f"{artifact['run_id']}.json"
    run_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert dr.audit_evidence_pack(tmp_path, "C1", "L8.5") == (True, "")


def test_gate_rejects_a_handwritten_legacy_research_note(tmp_path):
    notes = tmp_path / "02_Agent_Notes" / "_pre_research"
    notes.mkdir(parents=True)
    (notes / "L1_research.md").write_text(
        "## Runtime digest\nPMID: 123456\n\n## Query log\n- q\n\n"
        "## Tool receipt\n- pubmed\n\n## Source count\n1\n", encoding="utf-8")
    ok, reason = gates._audit_pre_research(tmp_path, "L1", PRE_RESEARCH_MAP["L1"], "C1")
    assert ok is False and "evidence pack" in reason


def test_engine_exposes_deep_research_audit_and_report_commands():
    parser = engine.build_parser()
    assert parser.parse_args(["deep-research-run", "P", "C1", "--node", "L1", "--backend", "codex"]).cmd == "deep-research-run"
    assert parser.parse_args(["audit-literature-evidence", "P", "C1", "--node", "L8.5"]).cmd == "audit-literature-evidence"
    assert parser.parse_args(["literature-report", "P", "C1"]).cmd == "literature-report"


def test_runner_refuses_literature_stage_without_explicit_research_runtime(tmp_path):
    cfg = SimpleNamespace(data={"deep_research": {}})
    args = SimpleNamespace()
    assert run_loop.ensure_pre_research(str(tmp_path), "C1", "L1", cfg, args, tmp_path) is False


def test_l10_context_includes_source_located_l1_evidence(tmp_path):
    project = tmp_path / "P"
    cli = ROOT / "research_loop_v04.py"
    created = subprocess.run([sys.executable, str(cli), "new-project", str(project), "Topic"],
                             capture_output=True, text=True)
    assert created.returncode == 0, created.stderr
    candidate = subprocess.run([sys.executable, str(cli), "new-candidate", str(project),
                                "--title", "T", "--question", "Q", "--claim", "C", "--input", "data"],
                               capture_output=True, text=True)
    assert candidate.returncode == 0, candidate.stderr
    cand_id = candidate.stdout.splitlines()[0]
    dr.persist_run(project, cand_id, "L1", _payload(),
                   dr.skill_receipt("codex", ["codex", "exec"], "prompt", "0.1.9"))
    context = subprocess.run([sys.executable, str(cli), "assemble-context", str(project), cand_id,
                              "--node", "L10a"], capture_output=True, text=True)
    assert context.returncode == 0, context.stderr
    assert "=== DEEP RESEARCH EVIDENCE ===" in context.stdout
    assert "Results paragraph 2" in context.stdout


def test_l10_gate_requires_an_existing_evidence_id_when_pack_exists(tmp_path):
    dr.persist_run(tmp_path, "C1", "L1", _payload(),
                   dr.skill_receipt("codex", ["codex", "exec"], "prompt", "0.1.9"))
    bad = {"decision": "KEEP", "reason": "literature supports it", "literature_evidence_ids": ["missing"]}
    ok, reason = gates._audit_l10_evidence(tmp_path, "C1", bad)
    assert ok is False and "unknown" in reason
    evidence_id = dr.evidence_ids(tmp_path, "C1", ["L1"])[0]
    good = {"decision": "KEEP", "reason": "literature supports it", "literature_evidence_ids": [evidence_id]}
    assert gates._audit_l10_evidence(tmp_path, "C1", good) == (True, "")


def test_codex_runtime_preflight_requires_a_skill_manifest(tmp_path):
    spec = dr.RuntimeSpec(backend="codex", executable=sys.executable,
                          skill_path=str(tmp_path / "missing-skill"))
    ok, reason = dr.runtime_ready(spec)
    assert ok is False and "manifest" in reason
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "manifest.json").write_text("{}", encoding="utf-8")
    ok, reason = dr.runtime_ready(dr.RuntimeSpec(backend="codex", executable=sys.executable,
                                                 skill_path=str(skill)))
    assert ok is True, reason


def test_emit_l10b_rejects_missing_literature_evidence_ids(tmp_path):
    project = tmp_path / "P"
    cli = ROOT / "research_loop_v04.py"
    assert subprocess.run([sys.executable, str(cli), "new-project", str(project), "Topic"],
                          capture_output=True, text=True).returncode == 0
    new = subprocess.run([sys.executable, str(cli), "new-candidate", str(project), "--title", "T",
                          "--question", "Q", "--claim", "C", "--input", "data"],
                         capture_output=True, text=True)
    cand_id = new.stdout.splitlines()[0]
    dr.persist_run(project, cand_id, "L1", _payload(),
                   dr.skill_receipt("codex", ["codex", "exec"], "prompt", "0.1.9"))
    delta = {"candidate_id": cand_id, "decision": "KEEP", "evidence_level": "moderate",
             "reason": "literature supports it", "next_steps": [], "next_round_hypothesis": ""}
    src = tmp_path / "l10.json"
    src.write_text(json.dumps(delta), encoding="utf-8")
    rejected = subprocess.run([sys.executable, str(cli), "emit-delta", str(project), cand_id,
                               "--node", "L10b", "--persona", "Oppenheimer", "--file", str(src)],
                              capture_output=True, text=True)
    assert rejected.returncode != 0 and "literature_evidence_ids" in (rejected.stderr + rejected.stdout)
    delta["literature_evidence_ids"] = [dr.evidence_ids(project, cand_id, ["L1"])[0]]
    src.write_text(json.dumps(delta), encoding="utf-8")
    accepted = subprocess.run([sys.executable, str(cli), "emit-delta", str(project), cand_id,
                               "--node", "L10b", "--persona", "Oppenheimer", "--file", str(src)],
                              capture_output=True, text=True)
    assert accepted.returncode == 0, accepted.stderr


def test_deep_research_cli_executes_a_local_fake_codex(tmp_path):
    project = tmp_path / "P"
    cli = ROOT / "research_loop_v04.py"
    assert subprocess.run([sys.executable, str(cli), "new-project", str(project), "Topic"],
                          capture_output=True, text=True).returncode == 0
    new = subprocess.run([sys.executable, str(cli), "new-candidate", str(project), "--title", "T",
                          "--question", "Q", "--claim", "C", "--input", "data"],
                         capture_output=True, text=True)
    cand_id = new.stdout.splitlines()[0]
    skill = tmp_path / "academic-research-suite"
    skill.mkdir()
    (skill / "manifest.json").write_text("{}", encoding="utf-8")
    fake = tmp_path / "fake_codex.py"
    fake.write_text("import json\nprint(json.dumps(" + repr(_payload()) + "))\n", encoding="utf-8")
    command = tmp_path / "fake_codex.cmd"
    command.write_text(f'@echo off\n"{sys.executable}" "{fake}" %*\n', encoding="utf-8")
    runtime = project / "00_Preflight" / "deep_research_runtime.json"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(json.dumps({"backend": "codex", "executable": str(command),
                                   "skill_path": str(skill), "skill_version": "fixture"}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(cli), "deep-research-run", str(project), cand_id,
                             "--node", "L1"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "deep_research_run" in result.stdout
    context = subprocess.run([sys.executable, str(cli), "assemble-context", str(project), cand_id,
                              "--node", "L1"], capture_output=True, text=True)
    assert context.returncode == 0, context.stderr


def test_deep_research_cli_executes_a_local_fake_claude_plugin(tmp_path):
    project = tmp_path / "P"
    cli = ROOT / "research_loop_v04.py"
    assert subprocess.run([sys.executable, str(cli), "new-project", str(project), "Topic"],
                          capture_output=True, text=True).returncode == 0
    new = subprocess.run([sys.executable, str(cli), "new-candidate", str(project), "--title", "T",
                          "--question", "Q", "--claim", "C", "--input", "data"],
                         capture_output=True, text=True)
    cand_id = new.stdout.splitlines()[0]
    plugin = tmp_path / "academic-research-skills" / ".claude-plugin"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text("{}", encoding="utf-8")
    fake_payload = _payload()
    fake_payload["review_search"] = {"query": "review q", "status": "none_found", "receipt": "fixture 0"}
    fake = tmp_path / "fake_claude.py"
    fake.write_text("import json\nprint(json.dumps(" + repr(fake_payload) + "))\n", encoding="utf-8")
    command = tmp_path / "fake_claude.cmd"
    command.write_text(f'@echo off\n"{sys.executable}" "{fake}" %*\n', encoding="utf-8")
    runtime = project / "00_Preflight" / "deep_research_runtime.json"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(json.dumps({"backend": "claude", "executable": str(command),
                                   "plugin_dir": str(plugin.parent), "skill_version": "fixture"}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(cli), "deep-research-run", str(project), cand_id,
                             "--node", "L4"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "deep_research_run" in result.stdout
