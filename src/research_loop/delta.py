"""Delta schemas + structural validation + delta file resolution (Phase 2a).

DeltaValidator boundary. Depends only on research_loop.paths (leaf) -> no
engine import, no cycle. Schemas kept byte-for-byte (no delta_version bump;
that is v0.8). research_loop_v04 imports these back via inward shim.
"""
import json
import os
import sqlite3
from pathlib import Path

from research_loop.paths import _sha256


def _v2_candidate_delta_file(project_dir, delta_key, cand_id):
    """Return the non-overwriting v2 delta artifact path."""
    legacy = _delta_file(project_dir, delta_key)
    if legacy is None:
        return None
    return legacy.with_name(f"{cand_id}_{delta_key}_delta.v2.json")


def _v2_commit_valid(project_dir, delta_key, cand_id, path):
    """A v2 artifact is consumable only with a matching immutable receipt."""
    if not path or not path.exists():
        return False
    digest = _sha256(path)
    node = delta_key.split("_", 1)[0]
    binding_file = Path(project_dir) / "00_Preflight" / "hypothesis_store_binding.json"
    store_path = os.environ.get("RLR_HYPOTHESIS_STORE")
    if not binding_file.is_file() or not store_path or not Path(store_path).is_file():
        return False
    try:
        binding = json.loads(binding_file.read_text(encoding="utf-8"))
        relative_path = path.relative_to(project_dir).as_posix()
        con = sqlite3.connect(
            f"{Path(store_path).resolve().as_uri()}?mode=ro", uri=True
        )
        try:
            store = con.execute(
                "SELECT value FROM ledger_meta WHERE key='store_id'"
            ).fetchone()
            activation = con.execute(
                "SELECT 1 FROM project_activations WHERE project_id=?",
                (binding.get("project_id"),),
            ).fetchone()
            emission = con.execute(
                "SELECT c.receipt_sha256 FROM emissions e JOIN committed_emissions c "
                "ON c.delta_hash=e.delta_hash WHERE e.delta_hash=? AND e.project_id=? "
                "AND e.candidate_id=? AND e.node=? AND e.delta_path=? "
                "AND c.artifact_sha256=?",
                (digest, binding.get("project_id"), str(cand_id), node,
                 relative_path, digest),
            ).fetchone()
        finally:
            con.close()
        if (not store or store[0] != binding.get("store_id")
                or not activation or not emission):
            return False
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError):
        return False
    commits = Path(project_dir) / "08_Audit" / "hypothesis_commits"
    if not commits.is_dir():
        return False
    for receipt_path in commits.glob("*.json"):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (receipt.get("candidate_id") == str(cand_id)
                and receipt.get("node") == node
                and receipt.get("delta_hash") == digest
                and _sha256(receipt_path) == emission[0]):
            return True
    return False


DELTA_SCHEMAS = {
    "L0_linnaeus": {
        "skills_found": list, "skills_gaps": list, "input_verified": dict,
        "environment": dict, "skill_use_plan": list, "forbidden_shortcuts": list,
        # v0.6: optional cross-loop memory; required only for from_memory candidates
        # (enforced by _audit_l0_memory, not by structural schema).
    },
    # NOTE: input_verified values should be dicts with keys:
    #   path, files, format, classification, verified, notes
    #   (not bare strings like "valid") — enforced by L0 persona/layer templates
    "L1_einstein": {
        "hypotheses": [{"id": str, "text": str, "testable": bool, "rationale": str}],
        "key_uncertainty": str, "primary_hypothesis": str
    },
    "L2_feynman": {
        "attacks": [{"hypothesis_id": str, "severity": str, "text": str}],
        "confounders": [{"name": str, "severity": str, "text": str}],
        "diagnostic_tests": [{"name": str, "text": str}], "verdict": str
    },
    "L3_oppenheimer": {
        "selected": list, "rejected": list, "reason": str, "route_to": str
    },
    "L4_fisher": {
        "strategies": [{"id": str, "name": str, "steps": list, "samples": int, "status": str}],
        "recommended": str,
        "scripts_needed": [{"name": str, "purpose": str, "status": str}],
        "key_decisions": list
    },
    "L5_tukey": {
        "attacks": [{"target": str, "severity": str, "text": str}],
        "qc_checkpoints": [{"name": str, "text": str}],
        "failure_stop_rules": [{"name": str, "text": str}]
    },
    "L6_oppenheimer": {
        "approved_strategy": str, "modifications": list, "reason": str,
        "analysis_plan": {"scripts": list, "parameters": dict, "outputs": list}
    },
    "L7_turing": {
        "scripts_run": [{"name": str, "exit_code": int, "output_files": list}],
        "key_results": dict, "warnings": list, "failures": list
    },
    "L8_curie": {
        "evidence_verified": [{"file": str, "check": str, "result": str}],
        "evidence_level": str, "caveats": list
    },
    "L8.5_curie": {
        "searched_keywords": list,
        "papers": [{"pmid": str, "title": str, "abstract": str, "comparison": str, "relevance": str}],
        "summary": str
    },
    "L9a_feynman": {
        "falsification_risks": [{"name": str, "severity": str, "resolvable": bool, "text": str}],
        "survives": list, "falsified": list
    },
    "L9b_darwin": {
        "module_interpretations": [{"module": str, "meaning": str, "genes": list, "evidence": str}],
        "convergent_evolution": str, "limitations": list
    },
    "L10a_jobs": {
        "value_assessment": str, "headline": str,
        "publishable_now": list, "needs_more_work": list,
        "manuscript_framing": str
    },
    "L10b_oppenheimer": {
        "decision": str, "evidence_level": str, "reason": str, "next_steps": list,
        "next_round_hypothesis": str
    },
}

DELTA_PERSONA = {
    "L0_linnaeus": "Linnaeus", "L1_einstein": "Einstein",
    "L2_feynman": "Feynman", "L3_oppenheimer": "Oppenheimer",
    "L4_fisher": "Fisher", "L5_tukey": "Tukey",
    "L6_oppenheimer": "Oppenheimer", "L7_turing": "Turing",
    "L8_curie": "Curie", "L8.5_curie": "Curie", "L9a_feynman": "Feynman",
    "L9b_darwin": "Darwin", "L10a_jobs": "Jobs",
    "L10b_oppenheimer": "Oppenheimer",
}

def _delta_file(project_dir, delta_key):
    """Return path to a delta JSON file given its key (e.g. L1_einstein)."""
    persona = DELTA_PERSONA.get(delta_key, "")
    if not persona:
        return None
    return Path(project_dir) / "02_Agent_Notes" / persona / f"{delta_key}_delta.json"

def _candidate_delta_file(project_dir, delta_key, cand_id):
    """Return the non-overwriting path used for new candidate-owned deltas."""
    legacy = _delta_file(project_dir, delta_key)
    if legacy is None:
        return None
    return legacy.with_name(f"{cand_id}_{legacy.name}")

def _delta_for_candidate(project_dir, delta_key, cand_id):
    """Resolve only a committed v2 delta; legacy files are migration input only."""
    v2 = _v2_candidate_delta_file(project_dir, delta_key, cand_id)
    if _v2_commit_valid(project_dir, delta_key, cand_id, v2):
        return v2
    return None

def _delta_belongs_to_candidate(project_dir, delta_key, cand_id):
    """True only when a delta is unambiguously linked to ``cand_id``."""
    return _delta_for_candidate(project_dir, delta_key, cand_id) is not None

def _validate_delta(schema, data, path=""):
    """Recursively validate *data* against a delta *schema*, returning errors.

    A schema node may be:
      - a bare type (list/dict/str/bool/int): isinstance check only;
      - a list literal [elem_schema]: data must be a list and every element is
        validated against elem_schema (e.g. [{"id": str}] => list of objects);
      - a dict literal {k: subschema}: data must be a dict; every declared key
        is required (extra keys allowed) and validated against its subschema.

    This is what lets the validator reject hypotheses=[{"foo": 1}] (element
    missing the required id/text) instead of only checking the top-level type.
    """
    loc = path or "<root>"
    if isinstance(schema, dict):
        if not isinstance(data, dict):
            return [f"{loc}: expected object, got {type(data).__name__}"]
        errors = []
        for k, sub in schema.items():
            kp = f"{path}.{k}" if path else k
            if k not in data:
                errors.append(f"missing required key: {kp}")
            else:
                errors += _validate_delta(sub, data[k], kp)
        return errors
    if isinstance(schema, list):
        if not isinstance(data, list):
            return [f"{loc}: expected list, got {type(data).__name__}"]
        errors = []
        if schema:  # typed element schema -> validate each element
            elem = schema[0]
            for i, item in enumerate(data):
                errors += _validate_delta(elem, item, f"{path}[{i}]")
        return errors
    if schema is list and not isinstance(data, list):
        return [f"{loc}: expected list, got {type(data).__name__}"]
    if schema is dict and not isinstance(data, dict):
        return [f"{loc}: expected dict, got {type(data).__name__}"]
    if schema is bool and not isinstance(data, bool):
        return [f"{loc}: expected bool, got {type(data).__name__}"]
    if schema is int and (not isinstance(data, int) or isinstance(data, bool)):
        return [f"{loc}: expected int, got {type(data).__name__}"]
    if schema is str and not isinstance(data, str):
        return [f"{loc}: expected str, got {type(data).__name__}"]
    return []
