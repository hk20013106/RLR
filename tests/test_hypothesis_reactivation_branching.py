from tests.native_v2_helpers import commit_v2
from tests.test_hypothesis_pool import _seed_rejected_hypothesis
from tests.test_hypothesis_reactivation_lifecycle import _source


def test_one_recalled_parent_can_seed_distinct_derivatives(tmp_path):
    project, _ledger, hypothesis_id = _seed_rejected_hypothesis(tmp_path)
    record, _artifact, _recalled = _source(project, _ledger, hypothesis_id)

    result = commit_v2(
        project,
        "C2",
        "L1",
        "Einstein",
        {
            "schema_version": "2.1",
            "hypotheses": [
                {
                    "proposal_key": "d1",
                    "origin": "DERIVE",
                    "parent_hypothesis_ids": [hypothesis_id],
                    "statement": record["statement"] + " in atrial tissue",
                    "operationalization": record["operationalization"],
                    "falsification_criteria": record["falsification_criteria"],
                    "rationale": "fixture",
                    "change_summary": "Restrict the statement to atrial tissue.",
                },
                {
                    "proposal_key": "d2",
                    "origin": "DERIVE",
                    "parent_hypothesis_ids": [hypothesis_id],
                    "statement": record["statement"] + " in ventricular tissue",
                    "operationalization": record["operationalization"],
                    "falsification_criteria": record["falsification_criteria"],
                    "rationale": "fixture",
                    "change_summary": "Restrict the statement to ventricular tissue.",
                },
            ],
            "primary_proposal_key": "d1",
            "key_uncertainty": "tissue specificity",
        },
        round_id="2",
    )

    ids = [item["hypothesis_id"] for item in result.normalized_delta["hypotheses"]]
    assert len(ids) == 2
    assert len(set(ids)) == 2
