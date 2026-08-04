import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop import deep_research as dr
from research_loop import method_evidence_compat as compat


def _source_text(*extracts: str) -> str:
    paragraphs = "".join(f"<p>{extract}</p>" for extract in extracts)
    return (
        "<article><section><h2>Methods</h2>"
        + paragraphs
        + "<p>Detailed reproducible procedure and parameter rationale. " * 20
        + "</p></section></article>"
    )


def _candidate(method_id: str, component_id: str, anchor_ids: list[str]) -> dict:
    return {
        "method_id": method_id,
        "component_id": component_id,
        "name": method_id,
        "status": "eligible",
        "purpose": f"Implement {component_id}.",
        "applicable_to": ["validated input data"],
        "implementation_steps": ["run the documented procedure"],
        "assumptions": [],
        "expected_outputs": ["validated result"],
        "strengths": [],
        "limitations": [],
        "alternatives": [],
        "rejection_reasons": [],
        "method_anchor_ids": list(anchor_ids),
        "missing_source": "",
    }


def _extract(
    anchor_id: str,
    text: str,
    method_ids: list[str],
    component_ids: list[str],
) -> dict:
    return {
        "anchor_id": anchor_id,
        "section": "Workflow",
        "text": text,
        "locator": f"{anchor_id} paragraph 1",
        "extraction_method": "source-located",
        "verification_status": "located",
        "method_component_ids": list(component_ids),
        "method_ids": list(method_ids),
        "source_kind": "official_documentation",
    }


def _payload() -> dict:
    first = "Apply the documented two-stage workflow and retain diagnostic outputs."
    second = "Inspect the final diagnostic report before accepting the estimate."
    return {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": ["two-stage method workflow"],
        "method_components": [
            {
                "component_id": "component_a",
                "name": "Stage A",
                "required": True,
                "rationale": "Prepares the input.",
            },
            {
                "component_id": "component_b",
                "name": "Stage B",
                "required": True,
                "rationale": "Produces the final estimate.",
            },
        ],
        "method_candidates": [
            _candidate("method_a", "component_a", ["anchor_1"]),
            _candidate("method_b", "component_b", ["anchor_1", "anchor_2"]),
        ],
        "papers": [
            {
                "doi": "10.1000/two-stage",
                "pmid": "",
                "url": "https://example.org/two-stage",
                "title": "Two-stage workflow",
                "source_database": "official",
                "metadata": {"year": 2026},
                "source_metadata_response": {"id": "two-stage"},
                "open_access": True,
                "content_type": "text/html",
                "source_payload": _source_text(first, second),
                "paper_type": "method",
                "user_source_id": "",
                "user_source_sha256": "",
                "extracts": [
                    _extract(
                        "anchor_1",
                        first,
                        ["method_a", "method_b"],
                        # Synthetic regression fixture derived from the exact
                        # real-pilot validator path: both method IDs are explicit,
                        # but this redundant list omits method_b's component.
                        ["component_a"],
                    ),
                    _extract(
                        "anchor_2",
                        second,
                        ["method_b"],
                        ["component_b"],
                    ),
                ],
            }
        ],
        "review_search": {
            "query": "two-stage workflow review",
            "status": "none_found",
            "receipt": "Europe PMC 0",
        },
        "verification": [],
    }


def _receipt() -> dict:
    return dr.skill_receipt("codex", ["codex", "exec"], "prompt", "test")


def test_l4_canonicalizes_redundant_component_refs_from_explicit_method_refs(tmp_path):
    artifact = dr.persist_run(
        tmp_path / "project", "C1", "L4", _payload(), _receipt()
    )

    assert artifact["method_anchors"][0]["method_ids"] == ["method_a", "method_b"]
    assert artifact["method_anchors"][0]["method_component_ids"] == [
        "component_a",
        "component_b",
    ]


def test_l4_reference_canonicalization_handles_multiple_anchors_and_methods(tmp_path):
    artifact = dr.persist_run(
        tmp_path / "project", "C1", "L4", _payload(), _receipt()
    )

    anchors = {item["anchor_id"]: item for item in artifact["method_anchors"]}
    assert anchors["anchor_1"]["method_component_ids"] == [
        "component_a",
        "component_b",
    ]
    assert anchors["anchor_2"]["method_component_ids"] == ["component_b"]


def test_l4_reference_canonicalization_strips_ids_consistently(tmp_path):
    payload = _payload()
    payload["method_components"][0]["component_id"] = " component_a "
    payload["method_candidates"][0]["method_id"] = " method_a "
    payload["method_candidates"][0]["component_id"] = " component_a "
    payload["method_candidates"][0]["method_anchor_ids"] = [" anchor_1 "]
    anchor = payload["papers"][0]["extracts"][0]
    anchor["anchor_id"] = " anchor_1 "
    anchor["method_ids"][0] = " method_a "
    anchor["method_component_ids"][0] = " component_a "

    artifact = dr.persist_run(
        tmp_path / "project", "C1", "L4", payload, _receipt()
    )

    assert artifact["method_components"][0]["component_id"] == "component_a"
    assert artifact["method_candidates"][0]["method_id"] == "method_a"
    assert artifact["method_anchors"][0]["anchor_id"] == "anchor_1"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload["method_candidates"][0].update(
                component_id="missing_component"
            ),
            "unknown component",
        ),
        (
            lambda payload: payload["papers"][0]["extracts"][0].update(
                method_ids=["asset-001"]
            ),
            "unknown method candidate",
        ),
    ],
)
def test_l4_reference_canonicalization_does_not_infer_unknown_ids(
    tmp_path, mutation, message
):
    payload = _payload()
    mutation(payload)

    with pytest.raises(dr.DeepResearchError, match=message):
        dr.persist_run(tmp_path / "project", "C1", "L4", payload, _receipt())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload["method_components"].append(
                copy.deepcopy(payload["method_components"][0])
            ),
            "component IDs must be unique",
        ),
        (
            lambda payload: payload["method_candidates"].append(
                copy.deepcopy(payload["method_candidates"][0])
            ),
            "method IDs must be unique",
        ),
        (
            lambda payload: payload["papers"][0]["extracts"].append(
                copy.deepcopy(payload["papers"][0]["extracts"][0])
            ),
            "anchor IDs must be non-empty and unique",
        ),
    ],
)
def test_l4_reference_canonicalization_keeps_duplicate_declarations_fail_closed(
    tmp_path, mutation, message
):
    payload = _payload()
    mutation(payload)

    with pytest.raises(dr.DeepResearchError, match=message):
        dr.persist_run(tmp_path / "project", "C1", "L4", payload, _receipt())


def test_l4_persistence_uses_same_canonical_reference_structure(tmp_path):
    raw = _payload()
    canonical = compat._normalized_payload(raw, "L4")

    raw_artifact = dr.persist_run(
        tmp_path / "raw", "C1", "L4", raw, _receipt()
    )
    canonical_artifact = dr.persist_run(
        tmp_path / "canonical", "C1", "L4", canonical, _receipt()
    )

    assert raw_artifact["run_id"] == canonical_artifact["run_id"]
    assert raw_artifact["method_components"] == canonical_artifact["method_components"]
    assert raw_artifact["method_candidates"] == canonical_artifact["method_candidates"]
    assert raw_artifact["method_anchors"] == canonical_artifact["method_anchors"]


def test_l4b_prompt_states_reference_closure_contract():
    captured = {}

    def original_run(
        project_dir,
        candidate_id,
        node,
        question,
        claim,
        spec,
        work_dir,
        *args,
        **kwargs,
    ):
        captured["claim"] = claim
        return {"node": node}

    fake = SimpleNamespace(
        _MAX_SOURCE_BYTES=5 * 1024 * 1024,
        _parse_cli_output=lambda value: value,
        validate_payload=lambda payload, **kwargs: payload,
        persist_run=lambda *args, **kwargs: {"node": args[2]},
        run_and_persist=original_run,
    )
    compat.install(fake)

    fake.run_and_persist(
        "project", "C1", "L4", "Q", "H", object(), "work"
    )

    assert "method_component_ids" in captured["claim"]
    assert "`component_id` of every" in captured["claim"]
    assert "referenced `method_id`" in captured["claim"]
    assert "Do not use L4A asset IDs" in captured["claim"]
