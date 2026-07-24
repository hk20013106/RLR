"""Public CLI seam tests for shadow ranking commands."""
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

from research_loop import engine
from research_loop.hypothesis_ledger import HypothesisLedger
from native_v2_helpers import commit_finalized


def _project_with_hypotheses(tmp_path, *, final=False):
    project = tmp_path / "ranking-project"
    project.mkdir()
    (project / "00_Project_Index.md").write_text("# Test project\n", encoding="utf-8")
    oppenheimer = project / "02_Agent_Notes" / "Oppenheimer"
    oppenheimer.mkdir(parents=True)
    ledger = HypothesisLedger(os.environ["RLR_HYPOTHESIS_STORE"])
    binding = ledger.bind_project(project)

    def commit(candidate_id, node, persona, delta):
        return commit_finalized(
            project, candidate_id, node, persona, delta, round_id="1"
        )

    for candidate_id, text in (("C1", "Hypothesis one"),
                               ("C2", "Hypothesis two")):
        (project / "01_Candidates").mkdir(exist_ok=True)
        (project / "01_Candidates" / f"{candidate_id}.md").write_text(
            "---\n"
            f"candidate_id: {candidate_id}\n"
            "---\n",
            encoding="utf-8")
        l1 = commit(candidate_id, "L1", "Einstein", {
            "schema_version": "2.0", "hypotheses": [{
                "proposal_key": "primary", "statement": text,
                "operationalization": "measure", "falsification_criteria": ["absent"],
                "rationale": "fixture"}], "primary_proposal_key": "primary",
            "key_uncertainty": "none",
        })
        hid = l1.normalized_delta["primary_hypothesis_id"]
        disposition = "SELECTED" if final or candidate_id == "C2" else "REJECTED"
        commit(candidate_id, "L3", "Oppenheimer", {
            "schema_version": "2.0", "triage": [{"hypothesis_id": hid,
                "disposition": disposition, "reason_code": "fixture", "reason": "fixture"}],
            "route_to": "Fisher",
        })
        if final:
            commit(candidate_id, "L4", "Fisher", {"schema_version": "2.0",
                "strategies": [{"strategy_id": "S1", "hypothesis_ids": [hid],
                                "name": "method", "steps": ["measure"]}]})
            commit(candidate_id, "L6", "Oppenheimer", {"schema_version": "2.0",
                "analysis_plan": [{"strategy_id": "S1", "hypothesis_ids": [hid],
                                   "scripts": [], "parameters": {}, "outputs": []}],
                "method_decision": "APPROVE", "reason": "fixture"})
            l7 = commit(candidate_id, "L7", "Turing", {"schema_version": "2.0",
                "results": [{"result_key": "R", "hypothesis_ids": [hid],
                    "summary": "result", "artifact_refs": [{"path": "result.json",
                    "sha256": "a" * 64}]}], "scripts_run": [], "warnings": [], "failures": []})
            evidence_id = l7.normalized_delta["results"][0]["evidence_id"]
            commit(candidate_id, "L8", "Curie", {"schema_version": "2.0",
                "evidence_assessments": [{"evidence_id": evidence_id,
                    "verification": "VERIFIED", "relations": [{"hypothesis_id": hid,
                    "outcome": "SUPPORTS", "reason": "fixture"}]}]})
            commit(candidate_id, "L9a", "Feynman", {"schema_version": "2.0",
                "assessments": [{"hypothesis_id": hid,
                    "epistemic_status": "PROVISIONALLY_SUPPORTED", "reason": "fixture",
                    "evidence_ids": [evidence_id]}]})
            keep = candidate_id == "C2"
            commit(candidate_id, "L10b", "Oppenheimer", {"schema_version": "2.0",
                "decision": "KEEP" if keep else "DROP", "reason": "fixture",
                "next_steps": [], "hypothesis_decisions": [{"hypothesis_id": hid,
                    "disposition": "RETAIN" if keep else "ARCHIVE", "reason": "fixture"}]})
    l3 = oppenheimer / "C1_L3_oppenheimer_delta.json"
    l3.write_text(json.dumps({"candidate_id": "C1", "selected": [],
                              "rejected": ["H1"], "reason": "fixture", "route_to": "ARCHIVED"}),
                  encoding="utf-8")
    assert binding["project_id"]
    return project, l3


def test_ranking_shadow_writes_only_isolated_audit_artifacts(tmp_path, capsys):
    project, formal_l3 = _project_with_hypotheses(tmp_path)
    before = hashlib.sha256(formal_l3.read_bytes()).hexdigest()

    assert engine.main([
        "ranking-shadow", str(project), "--stage", "L3",
        "--candidate", "C1", "--candidate", "C2", "--seed", "17",
        "--match-budget", "3", "--token-budget", "11", "--cost-budget", "2.5",
        "--run-id", "fixture-run",
    ]) == 0

    response = json.loads(capsys.readouterr().out)
    assert response["budget"]["token_budget_policy"] == "declared-only/not-enforced"
    assert response["budget"]["cost_budget_policy"] == "declared-only/not-enforced"
    artifact = Path(response["artifact"])
    checkpoint = Path(response["checkpoint"])
    report = Path(response["report"])
    complete = Path(response["complete_marker"])
    assert artifact.is_file()
    assert checkpoint.is_file()
    assert report.is_file()
    assert complete.is_file()
    marker = json.loads(complete.read_text(encoding="utf-8"))
    assert marker == {
        "schema_version": "1.0", "run_id": "fixture-run", "stage": "L3",
        "judge_mode": "fake", "sha256": {
            "artifact": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "checkpoint": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "report": hashlib.sha256(report.read_bytes()).hexdigest(),
        },
    }
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["provenance"]["stage"] == "L3"
    assert len(payload["hypothesis_candidates"]) == 2
    assert payload["budget"]["logical_matches"] == 3
    assert payload["budget"]["raw_judge_calls"] == 6
    assert payload["budget"]["tokens"] == 11
    assert payload["budget"]["cost"] == 2.5
    assert payload["budget"]["token_budget_policy"] == "declared-only/not-enforced"
    assert payload["budget"]["cost_budget_policy"] == "declared-only/not-enforced"
    assert all(record["comparison_status"] == "DISAGREES"
               for record in payload["advisory_comparisons"])
    assert {record["formal_direction"] for record in payload["advisory_comparisons"]} == {
        "HIGHER", "LOWER"}
    assert hashlib.sha256(formal_l3.read_bytes()).hexdigest() == before


def test_ranking_shadow_records_l10b_disagreement_and_report(tmp_path, capsys):
    project, _ = _project_with_hypotheses(tmp_path, final=True)

    assert engine.main([
        "ranking-shadow", str(project), "--stage", "L10b",
        "--candidate", "C1", "--candidate", "C2", "--seed", "17",
        "--match-budget", "3", "--run-id", "l10b-disagreement",
    ]) == 0
    response = json.loads(capsys.readouterr().out)
    artifact = json.loads(Path(response["artifact"]).read_text(encoding="utf-8"))
    assert {record["formal_decision"] for record in artifact["advisory_comparisons"]} == {
        "DROP", "KEEP"}
    assert all(record["comparison_status"] == "DISAGREES"
               for record in artifact["advisory_comparisons"])

    report = Path(response["report"]).read_text(encoding="utf-8")
    assert "## Formal Decision Comparison" in report
    assert "DISAGREES=2" in report


def test_ranking_shadow_rejects_resume_stage_or_judge_mismatch_before_running(tmp_path, capsys):
    project, _ = _project_with_hypotheses(tmp_path)
    assert engine.main([
        "ranking-shadow", str(project), "--stage", "L3",
        "--candidate", "C1", "--candidate", "C2", "--seed", "1",
        "--match-budget", "1", "--run-id", "resume-source",
    ]) == 0
    checkpoint = json.loads(capsys.readouterr().out)["checkpoint"]

    assert engine.main([
        "ranking-shadow", str(project), "--stage", "L10b",
        "--candidate", "C1", "--candidate", "C2", "--seed", "1",
        "--match-budget", "1", "--resume", checkpoint, "--run-id", "resume-stage",
    ]) == 2
    assert "stage" in capsys.readouterr().err

    assert engine.main([
        "ranking-shadow", str(project), "--stage", "L3",
        "--candidate", "C1", "--candidate", "C2", "--seed", "1",
        "--match-budget", "1", "--judge", "provider", "--resume", checkpoint,
        "--run-id", "resume-judge",
    ]) == 2
    assert "judge mode" in capsys.readouterr().err


def test_provider_shadow_ranking_uses_run_owned_audit_directory(tmp_path, capsys):
    project, _ = _project_with_hypotheses(tmp_path)
    observed = []

    def fake_provider_judge(args, audit_run_dir):
        observed.append(Path(audit_run_dir))
        return engine.ranking.DeterministicFakeJudge()

    with patch("research_loop.engine._ranking_judge", side_effect=fake_provider_judge):
        assert engine.main([
            "ranking-shadow", str(project), "--stage", "L3",
            "--candidate", "C1", "--candidate", "C2", "--seed", "3",
            "--match-budget", "1", "--judge", "provider", "--run-id", "provider-run",
        ]) == 0
    capsys.readouterr()
    assert observed == [project / "08_Audit" / "ranking" / "provider-run.provider"]


def test_ranking_benchmark_and_json_report_are_machine_readable(tmp_path, capsys):
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({
        "schema_version": "1.0",
        "candidates": [
            {"candidate_id": "C1", "hypothesis_id": "H1", "hypothesis": "one", "gold_rank": 1},
            {"candidate_id": "C2", "hypothesis_id": "H2", "hypothesis": "two", "gold_rank": 2},
            {"candidate_id": "C3", "hypothesis_id": "H3", "hypothesis": "three", "gold_rank": 3},
        ],
    }), encoding="utf-8")
    output = tmp_path / "benchmark.json"

    assert engine.main([
        "ranking-benchmark", "--gold", str(gold), "--seeds", "3,7",
        "--match-budget", "4", "--output", str(output),
    ]) == 0
    benchmark = json.loads(capsys.readouterr().out)
    assert output.is_file()
    assert "synthetic" in benchmark["disclaimer"].lower()
    for metric in ("pairwise_accuracy", "position_bias", "self_consistency",
                   "top_k_stability", "ranking_churn", "uncertain_rate", "budget"):
        assert metric in benchmark["metrics"]
    bias = benchmark["metrics"]["position_bias"]
    assert bias["naive_false_first_win_rate"] > bias["fair_false_first_win_rate"]
    budget = benchmark["metrics"]["budget"]
    assert budget["fair_raw_judge_calls"] == 16
    assert budget["naive_raw_judge_calls"] == 8

    project, _ = _project_with_hypotheses(tmp_path)
    assert engine.main([
        "ranking-shadow", str(project), "--stage", "L3",
        "--candidate", "C1", "--candidate", "C2", "--seed", "3",
        "--match-budget", "1", "--run-id", "report-fixture",
    ]) == 0
    capsys.readouterr()
    assert engine.main([
        "ranking-report", str(project), "--run", "report-fixture", "--format", "json",
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["run_id"] == "report-fixture"

    assert engine.main([
        "ranking-report", str(project), "--run", "report-fixture", "--format", "markdown",
    ]) == 0
    assert capsys.readouterr().out.startswith("# Shadow Ranking Report\n")


def test_ranking_shadow_prevalidates_run_id_and_output_collisions(tmp_path, capsys):
    project, _ = _project_with_hypotheses(tmp_path)
    ranking_dir = project / "08_Audit" / "ranking"
    ranking_dir.mkdir(parents=True)
    (ranking_dir / "occupied.json").write_text("{}", encoding="utf-8")

    with patch("research_loop.engine._ranking_judge") as judge:
        assert engine.main([
            "ranking-shadow", str(project), "--stage", "L3",
            "--candidate", "C1", "--candidate", "C2", "--seed", "1",
            "--match-budget", "1", "--judge", "provider", "--run-id", "occupied",
        ]) == 2
        judge.assert_not_called()
        assert engine.main([
            "ranking-shadow", str(project), "--stage", "L3",
            "--candidate", "C1", "--candidate", "C2", "--seed", "1",
            "--match-budget", "1", "--judge", "provider", "--run-id", "../unsafe",
        ]) == 2
        judge.assert_not_called()
    assert "collision" in capsys.readouterr().err


def test_ranking_shadow_prevalidates_complete_marker_collision_before_provider(tmp_path, capsys):
    project, _ = _project_with_hypotheses(tmp_path)
    ranking_dir = project / "08_Audit" / "ranking"
    ranking_dir.mkdir(parents=True)
    (ranking_dir / "complete-collides.complete.json").write_text("{}", encoding="utf-8")

    with patch("research_loop.engine._ranking_judge") as judge:
        assert engine.main([
            "ranking-shadow", str(project), "--stage", "L3",
            "--candidate", "C1", "--candidate", "C2", "--seed", "1",
            "--match-budget", "1", "--judge", "provider", "--run-id", "complete-collides",
        ]) == 2
        judge.assert_not_called()
    assert "collision" in capsys.readouterr().err


def test_ranking_cli_rejects_malformed_gold_evidence_and_artifact(tmp_path, capsys):
    malformed_gold = tmp_path / "malformed-gold.json"
    malformed_gold.write_text("[]", encoding="utf-8")
    assert engine.main([
        "ranking-benchmark", "--gold", str(malformed_gold), "--seeds", "1",
        "--match-budget", "1",
    ]) == 2

    project, _ = _project_with_hypotheses(tmp_path)
    malformed_evidence = tmp_path / "bad-evidence.json"
    malformed_evidence.write_text("[1]", encoding="utf-8")
    assert engine.main([
        "ranking-shadow", str(project), "--stage", "L3",
        "--candidate", "C1", "--candidate", "C2", "--seed", "1",
        "--match-budget", "1", "--run-id", "bad-evidence",
        "--evidence", str(malformed_evidence),
    ]) == 2

    artifact_dir = project / "08_Audit" / "ranking"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "malformed.json").write_text("{}", encoding="utf-8")
    assert engine.main([
        "ranking-report", str(project), "--run", "malformed", "--format", "markdown",
    ]) == 2
    assert "ERROR:" in capsys.readouterr().err
