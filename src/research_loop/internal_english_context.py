"""Inject the internal-English contract into cognitive contexts.

The canonical L0 contract is the scientific semantic authority. For candidates
created through the intake language boundary, legacy candidate frontmatter
question/claim/title values are display metadata only and are excluded from
agent context so original user-language text cannot compete with the canonical
English semantics.
"""
from __future__ import annotations

from pathlib import Path

from research_loop import l0_contract


_LANGUAGE_LINES = [
    "INTERNAL LANGUAGE CONTRACT:",
    "- MUST write all generated scientific prose and semantic fields in English.",
    "- This includes hypotheses, rationales, findings, method names/purposes, interpretations, reasons, gaps, and next actions.",
    "- MUST NOT translate or rewrite exact IDs, file paths, code, gene/protein symbols, database identifiers, or verbatim evidence/source locators.",
    "- Chinese is permitted only at the external user-intake boundary; do not emit Chinese internal scientific prose.",
]


def _has_normalized_contract(candidate_path: str | Path, candidate_id: str) -> bool:
    path = Path(candidate_path)
    try:
        project = path.parent.parent
        contract, _artifact, _raw = l0_contract.load_contract(project, candidate_id)
    except (OSError, ValueError, TypeError):
        return False
    return isinstance(contract, dict) and isinstance(
        contract.get("language_normalization"), dict
    )


def install(context_module) -> None:
    if getattr(context_module, "_internal_english_context_installed", False):
        return

    original_frontmatter = context_module.candidate_frontmatter_for_node

    def candidate_frontmatter_for_node(
        candidate_path, node_id, include_source_path=False
    ):
        visible = original_frontmatter(
            candidate_path,
            node_id,
            include_source_path=include_source_path,
        )
        candidate_id = str(visible.get("candidate_id") or "").strip()
        if candidate_id and _has_normalized_contract(candidate_path, candidate_id):
            visible.pop("title", None)
            visible.pop("question", None)
            visible.pop("claim", None)
        return visible

    original_generate_contract = context_module._generate_contract

    def generate_contract(node_info, project_dir, schema_version, profile_id=""):
        lines = list(
            original_generate_contract(
                node_info, project_dir, schema_version, profile_id
            )
        )
        lines.extend(["", *_LANGUAGE_LINES])
        return lines

    context_module.candidate_frontmatter_for_node = candidate_frontmatter_for_node
    context_module._generate_contract = generate_contract
    context_module._internal_english_context_installed = True
