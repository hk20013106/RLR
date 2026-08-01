import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop.hypothesis_contracts import validate_submission


def test_v21_l4_method_extension_is_atomic():
    delta = {
        "schema_version": "2.1",
        "deep_research_run_id": "C1_L4_abc",
        "strategies": [{
            "strategy_id": "S1", "hypothesis_ids": ["H1"],
            "name": "Cross-species expression analysis", "steps": ["map orthologs"],
        }],
        "method_components": [{
            "component_id": "orthology", "name": "Orthology mapping",
            "required": True, "rationale": "Build a comparable gene space.",
        }],
        "method_candidates": [{
            "method_id": "ensembl_1to1", "component_id": "orthology",
            "hypothesis_ids": ["H1"], "name": "Ensembl one-to-one orthologs",
            "status": "eligible", "purpose": "Restrict analysis to comparable genes.",
            "applicable_to": ["multi-species expression"],
            "implementation_steps": ["retrieve ortholog table", "filter one-to-one genes"],
            "assumptions": ["orthology annotations are current"],
            "expected_outputs": ["one-to-one gene matrix"],
            "strengths": ["simple and auditable"],
            "limitations": ["drops lineage-specific genes"],
            "alternatives": ["gene-family aggregation"],
            "method_anchor_ids": ["A1"],
            "rejection_reasons": [], "missing_source": "",
        }],
    }
    assert validate_submission("L4", delta, schema_version="2.1") == []

    missing = dict(delta)
    missing.pop("method_candidates")
    errors = validate_submission("L4", missing, schema_version="2.1")
    assert any("method_candidates" in error for error in errors)


def test_v21_l5_validates_candidate_level_critiques_when_present():
    delta = {
        "schema_version": "2.1",
        "attacks": [{
            "attack_id": "AT1", "hypothesis_ids": ["H1"], "strategy_id": "S1",
            "severity": "major", "text": "Ortholog filtering may bias conserved pathways.",
            "resolution": "Report retained-gene coverage.",
        }],
        "qc_checkpoints": [{
            "hypothesis_ids": ["H1"], "strategy_id": "S1",
            "name": "ortholog coverage", "criterion": ">=70% expressed genes retained",
        }],
        "failure_stop_rules": [{
            "hypothesis_ids": ["H1"], "strategy_id": "S1",
            "name": "coverage failure", "condition": "coverage <50%",
            "reason": "Cross-species comparison becomes unrepresentative.",
        }],
        "method_critiques": [{
            "method_id": "ensembl_1to1", "component_id": "orthology",
            "verdict": "MODIFY", "assumption_risks": ["annotation completeness differs"],
            "required_diagnostics": ["coverage by species"],
            "failure_modes": ["systematic gene loss"],
            "recommended_modifications": ["sensitivity analysis with gene families"],
        }],
    }
    assert validate_submission("L5", delta, schema_version="2.1") == []
    delta["method_critiques"][0].pop("method_id")
    assert any("method_id" in error
               for error in validate_submission("L5", delta, schema_version="2.1"))


def test_v21_l6_validates_selected_methods_when_present():
    delta = {
        "schema_version": "2.1",
        "analysis_plan": [{
            "hypothesis_ids": ["H1"], "strategy_id": "S1",
            "scripts": ["01_orthology.R"], "parameters": {"orthology": "one_to_one"},
            "outputs": ["ortholog_matrix.tsv"],
        }],
        "method_decision": "APPROVE",
        "reason": "The selected method matches the input and passed QC review.",
        "selected_methods": [{
            "component_id": "orthology", "selected_method_ids": ["ensembl_1to1"],
            "decision_rationale": "Auditable one-to-one mapping for the primary analysis.",
            "rejected_alternatives": [{
                "method_id": "gene_family", "reason": "Reserved for sensitivity analysis."
            }],
            "parameters": {"orthology_type": "one2one"},
            "software_requirements": ["biomaRt"],
            "scripts": ["01_orthology.R"],
            "method_anchor_ids": ["A1"],
            "l5_qc_requirements": ["report retained-gene coverage by species"],
        }],
    }
    assert validate_submission("L6", delta, schema_version="2.1") == []
    delta["selected_methods"][0]["selected_method_ids"] = []
    assert any("selected_method_ids" in error
               for error in validate_submission("L6", delta, schema_version="2.1"))


def test_legacy_v21_and_v20_deltas_remain_readable():
    v21 = {
        "schema_version": "2.1",
        "strategies": [{
            "strategy_id": "S1", "hypothesis_ids": ["H1"],
            "name": "Legacy v2.1 strategy", "steps": ["step"],
        }],
    }
    assert validate_submission("L4", v21, schema_version="2.1") == []

    v20 = {
        "schema_version": "2.0",
        "strategies": [{
            "strategy_id": "S1", "hypothesis_ids": ["H1"],
            "name": "Legacy strategy", "steps": ["step"],
        }],
    }
    assert validate_submission("L4", v20, schema_version="2.0") == []
