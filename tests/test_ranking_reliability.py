"""Public behavior tests for the shadow ranking reliability core."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from research_loop import ranking


class ScriptedJudge:
    """Free deterministic judge returning raw position verdicts in sequence."""
    provider_name = "fake"
    model_name = "scripted"

    def __init__(self, verdicts):
        self.verdicts = iter(verdicts)

    def compare(self, left, right):
        return {"verdict": next(self.verdicts), "reason": "fixture"}


def _candidates():
    return [
        ranking.hypothesis_candidate("H1", "Hypothesis one", "hash-1"),
        ranking.hypothesis_candidate("H2", "Hypothesis two", "hash-2"),
        ranking.hypothesis_candidate("H3", "Hypothesis three", "hash-3"),
    ]


def test_fair_pairwise_conflicting_position_orders_are_uncertain():
    pair = ranking.fair_pairwise_judge(
        _candidates()[0], _candidates()[1], ScriptedJudge(["A", "A"]),
        comparison_id="cmp-1")

    assert pair["raw_verdicts"][0]["order"] == ["H1", "H2"]
    assert pair["raw_verdicts"][1]["order"] == ["H2", "H1"]
    assert pair["final_verdict"] == "UNCERTAIN"
    assert pair["winner_id"] is None
    assert pair["prompt_hash"]


def test_elo_is_reproducible_and_uncertain_match_does_not_update_scores():
    uncertain = ScriptedJudge(["A", "A", "A", "A", "A", "A"])
    a = ranking.run_elo_ranking(_candidates(), uncertain, seed=7, match_budget=3)
    b = ranking.run_elo_ranking(_candidates(),
                                ScriptedJudge(["A", "A", "A", "A", "A", "A"]),
                                seed=7, match_budget=3)

    assert a["ranking_results"] == b["ranking_results"]
    assert [r["score"] for r in a["ranking_results"]] == [1000.0] * 3
    assert all(p["final_verdict"] == "UNCERTAIN"
               for p in a["pairwise_judgments"])


def test_consistent_orders_produce_win_and_elo_update():
    pair = ranking.fair_pairwise_judge(
        _candidates()[0], _candidates()[1], ScriptedJudge(["A", "B"]))
    artifact = ranking.run_elo_ranking(
        _candidates()[:2], ScriptedJudge(["A", "B"]), seed=1, match_budget=1)

    assert pair["final_verdict"] == "WIN"
    assert pair["winner_id"] == "H1"
    scores = {row["candidate_id"]: row["score"] for row in artifact["ranking_results"]}
    assert scores["H1"] > 1000.0 > scores["H2"]


def test_checkpoint_resume_is_equivalent_and_skips_completed_comparisons():
    full = ranking.run_elo_ranking(
        _candidates(), ScriptedJudge(["A", "B"] * 4), seed=3, match_budget=4)
    partial = ranking.run_elo_ranking(
        _candidates(), ScriptedJudge(["A", "B"] * 2), seed=3, match_budget=2)
    resumed = ranking.run_elo_ranking(
        _candidates(), ScriptedJudge(["A", "B"] * 2), seed=3, match_budget=4,
        checkpoint=partial)

    assert resumed["ranking_results"] == full["ranking_results"]
    assert resumed["budget"] == full["budget"] == {"matches": 4, "tokens": None,
                                                       "cost": None}
    assert resumed == full
    ids = [p["comparison_id"] for p in resumed["pairwise_judgments"]]
    assert len(ids) == len(set(ids)) == 4


def test_json_checkpoint_round_trip_resumes_without_reapplying_matches(tmp_path):
    full = ranking.run_elo_ranking(
        _candidates(), ScriptedJudge(["A", "B"] * 2), seed=13, match_budget=2)
    partial = ranking.run_elo_ranking(
        _candidates(), ScriptedJudge(["A", "B"]), seed=13, match_budget=1)
    checkpoint_path = ranking.write_checkpoint(tmp_path, partial, run_id="resume-1")
    with pytest.raises(FileExistsError):
        ranking.write_checkpoint(tmp_path, partial, run_id="resume-1")
    resumed = ranking.run_elo_ranking(
        _candidates(), ScriptedJudge(["A", "B"]), seed=13, match_budget=2,
        checkpoint=ranking.load_checkpoint(checkpoint_path))

    assert len(resumed["pairwise_judgments"]) == 2
    assert resumed == full
    assert resumed["applied_comparison_ids"] == list(dict.fromkeys(
        resumed["applied_comparison_ids"]))


def test_resume_rejects_lower_budget_and_tampered_checkpoint():
    partial = ranking.run_elo_ranking(
        _candidates(), ScriptedJudge(["A", "B"]), seed=13, match_budget=1)
    with pytest.raises(ValueError, match="below completed"):
        ranking.run_elo_ranking(_candidates(), seed=13, match_budget=0, checkpoint=partial)

    tampered = json.loads(json.dumps(partial, default=list))
    tampered["hypothesis_candidates"][0]["source_delta_hash"] = "changed"
    with pytest.raises(ValueError, match="candidate snapshots"):
        ranking.run_elo_ranking(_candidates(), seed=13, match_budget=2, checkpoint=tampered)

    tampered = json.loads(json.dumps(partial, default=list))
    tampered["applied_comparison_ids"].append("forged")
    with pytest.raises(ValueError, match="applied comparison"):
        ranking.run_elo_ranking(_candidates(), seed=13, match_budget=2, checkpoint=tampered)

    tampered = json.loads(json.dumps(partial, default=list))
    tampered["schema_version"] = "99.0"
    with pytest.raises(ValueError, match="schema version"):
        ranking.run_elo_ranking(_candidates(), seed=13, match_budget=2, checkpoint=tampered)

    tampered = json.loads(json.dumps(partial, default=list))
    tampered["pairwise_judgments"][0]["raw_verdicts"][0]["winner_id"] = "NOT_A_WINNER"
    with pytest.raises(ValueError, match="raw winner"):
        ranking.run_elo_ranking(_candidates(), seed=13, match_budget=2, checkpoint=tampered)


@pytest.mark.parametrize("mutate", [
    lambda checkpoint: checkpoint["scheduler"]["scores"].__setitem__("H1", 9999.0),
    lambda checkpoint: checkpoint["scheduler"]["match_counts"].__setitem__("H1", 99),
    lambda checkpoint: checkpoint["scheduler"]["rng_state"][1].__setitem__(0, 0),
])
def test_resume_rejects_tampered_reconstructed_scheduler_state(mutate):
    partial = ranking.run_elo_ranking(
        _candidates(), ScriptedJudge(["A", "B"]), seed=13, match_budget=1)
    tampered = json.loads(json.dumps(partial, default=list))
    mutate(tampered)

    with pytest.raises(ValueError, match="scheduler state"):
        ranking.run_elo_ranking(_candidates(), seed=13, match_budget=2, checkpoint=tampered)


def test_evidence_events_are_validated_and_applied_once_without_elo_change():
    artifact = ranking.new_ranking_artifact(_candidates(), seed=1, match_budget=0)
    event = {"event_id": "ev-1", "hypothesis_id": "H1", "source": "assay.csv",
             "direction": "supports", "strength": "high", "quality": "verified",
             "payload": {"p": 0.01}}
    assert ranking.apply_evidence_event(artifact, event) is True
    assert ranking.apply_evidence_event(artifact, event) is False
    assert artifact["evidence_events"][0]["applied"] is True
    assert artifact["ranking_results"] == []

    changed = dict(event, source="other_assay.csv")
    with pytest.raises(ValueError, match="immutable fields"):
        ranking.apply_evidence_event(artifact, changed)


def test_hypothesis_ids_are_explicit_and_evidence_uses_them_not_candidate_ids():
    candidate = ranking.hypothesis_candidate("C1", "Hypothesis one", hypothesis_id="H-1")
    artifact = ranking.new_ranking_artifact([candidate], seed=1, match_budget=0)
    event = {"event_id": "ev-h", "hypothesis_id": "H-1", "source": "assay.csv",
             "direction": "supports", "strength": "high", "quality": "verified",
             "payload": {"p": 0.01}}

    assert artifact["hypothesis_candidates"][0]["candidate_id"] == "C1"
    assert artifact["hypothesis_candidates"][0]["hypothesis_id"] == "H-1"
    assert ranking.apply_evidence_event(artifact, event) is True


def test_artifact_json_and_markdown_report_are_auditable(tmp_path):
    artifact = ranking.run_elo_ranking(
        _candidates()[:2], ScriptedJudge(["A", "B"]), seed=2, match_budget=1)
    written = ranking.write_ranking_artifact(tmp_path, artifact, run_id="shadow-1")
    report = ranking.render_markdown_report(artifact)

    on_disk = json.loads(Path(written).read_text(encoding="utf-8"))
    assert Path(written).parent == tmp_path / "08_Audit" / "ranking"
    assert on_disk["schema_version"] == ranking.SCHEMA_VERSION
    assert "# Shadow Ranking Report" in report
    assert "H1" in report and "H2" in report
    with pytest.raises(FileExistsError):
        ranking.write_ranking_artifact(tmp_path, artifact, run_id="shadow-1")
    with pytest.raises(ValueError, match="safe"):
        ranking.write_ranking_artifact(tmp_path, artifact, run_id="../escape")


def test_provider_adapter_uses_unique_audit_child_dirs_and_persists_references(tmp_path):
    class Provider:
        type = "command"
        name = "fixture-provider"
        model = "fixture-model"

        def __init__(self):
            self.calls = []

        def run_agent(self, node, persona, context, output_schema=None, run_dir=None, **kwargs):
            self.calls.append((node, persona, context, output_schema, run_dir))
            self.last_prompt_file = str(Path(run_dir) / "prompt.txt")
            self.last_delta_file = str(Path(run_dir) / "delta.json")
            return {"verdict": "A", "reason": "fixture"}

    provider = Provider()
    audit_dir = tmp_path / "08_Audit" / "ranking" / "shadow-1"
    judge = ranking.ProviderJudge(provider, run_dir=audit_dir)
    pair = ranking.fair_pairwise_judge(_candidates()[0], _candidates()[1], judge)

    assert len(provider.calls) == 2
    assert provider.calls[0][0] == "RANKING"
    assert provider.calls[0][3] == {"verdict": str, "reason": str}
    sent_payload = json.loads(provider.calls[0][2])
    raw = pair["raw_verdicts"][0]
    assert raw["prompt_payload"] == sent_payload
    assert raw["prompt_hash"] == ranking.prompt_hash(sent_payload)
    run_dirs = [Path(call[4]) for call in provider.calls]
    assert len(set(run_dirs)) == 2
    assert all(path.parent == audit_dir for path in run_dirs)
    assert pair["raw_verdicts"][0]["provider_prompt_file"].startswith(str(audit_dir))
    assert pair["raw_verdicts"][1]["provider_delta_file"].startswith(str(audit_dir))
    assert pair["provider"] == "fixture-provider"
    assert pair["model"] == "fixture-model"


def test_advisory_comparisons_record_agreement_disagreement_and_uncertainty():
    artifact = ranking.new_ranking_artifact(_candidates(), seed=1, match_budget=0)
    artifact["ranking_results"] = [
        {"candidate_id": "H1", "rank": 1, "score": 1010.0, "matches": 1, "uncertainty": 0},
        {"candidate_id": "H2", "rank": 2, "score": 1000.0, "matches": 1, "uncertainty": 0},
        {"candidate_id": "H3", "rank": 3, "score": 990.0, "matches": 1, "uncertainty": 1},
    ]
    records = ranking.attach_advisory_comparisons(artifact, [
        {"candidate_id": "H1", "hypothesis_id": "H1", "formal_decision": "SELECTED",
         "formal_direction": "HIGHER"},
        {"candidate_id": "H2", "hypothesis_id": "H2", "formal_decision": "SELECTED",
         "formal_direction": "HIGHER"},
        {"candidate_id": "H3", "hypothesis_id": "H3", "formal_decision": "REJECTED",
         "formal_direction": "LOWER"},
    ])

    assert [record["comparison_status"] for record in records] == [
        "AGREES", "DISAGREES", "UNCERTAIN"]
    assert records[0]["shadow_signal"] == "HIGHER"
    assert records[2]["shadow_uncertainty"] == 1
    report = ranking.render_markdown_report(artifact)
    assert "## Formal Decision Comparison" in report
    assert "DISAGREES" in report and "UNCERTAIN" in report
