"""Normalize user-language semantics once before a new L0 contract is frozen.

This is an intake adapter, not a second L0 authority. The existing l0_contract
module still owns the canonical contract bytes, validation, and hash. This
adapter only transforms user-facing Chinese semantic fields to English before
those canonical bytes are created. English passes through unchanged; other
natural languages fail closed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

from research_loop import deep_research, structured_execution
from research_loop.l0_language import (
    L0LanguageError,
    normalize_semantic_fields,
    validate_internal_english,
)


class L0LanguageBoundaryError(ValueError):
    """Raised when a new canonical L0 contract cannot be normalized safely."""


def _canonical_sha(value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _user_fields(contract: dict) -> dict[str, str]:
    current = contract.get("current_round")
    current = current if isinstance(current, dict) else {}
    source = contract.get("source_input")
    source = source if isinstance(source, dict) else {}
    result = {
        "scientific_question": str(contract.get("scientific_question") or "").strip(),
        "hypothesis": str(current.get("hypothesis") or "").strip(),
    }
    description = str(source.get("description") or "").strip()
    if description:
        result["source_description"] = description
    return result


def _validate_inherited_internal_semantics(contract: dict) -> None:
    previous = contract.get("previous_round")
    if not isinstance(previous, dict):
        return
    for field in ("hypothesis", "conclusion"):
        value = str(previous.get(field) or "").strip()
        if not value:
            continue
        try:
            validate_internal_english(value, name=f"previous_round.{field}")
        except L0LanguageError as exc:
            raise L0LanguageBoundaryError(
                "continuation inherited internal semantics must already be English: "
                f"{exc}"
            ) from exc


def _schema(fields: dict[str, str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            key: {"type": "string", "minLength": 1}
            for key in fields
        },
        "required": list(fields),
    }


def _prompt(fields: dict[str, str]) -> str:
    return f"""RLR intake boundary: normalize user scientific semantics to canonical English.

Input fields:
{json.dumps(fields, ensure_ascii=False, sort_keys=True)}

Return JSON with exactly the same field names.

Rules:
- Translate Chinese fields into precise standard English scientific terminology.
- Copy fields already written in English exactly; do not paraphrase them.
- Preserve genes/proteins, abbreviations, numbers, directionality, comparisons,
  organism/tissue/cell names, uncertainty, negation, and hypothesis strength.
- Do not answer the question, summarize, expand, reinterpret, search literature,
  browse the web, add evidence/citations, or change the scientific claim.
- Output English natural-language text only, apart from standard scientific
  notation such as isolated Greek symbols.
- Return JSON only: no prose, Markdown, code fences, or extra fields.
"""


def _translate(project_dir: str | Path, candidate_id: str, fields: dict[str, str]):
    try:
        spec, _skill_version = deep_research.load_runtime_spec(project_dir)
    except deep_research.DeepResearchError as exc:
        raise L0LanguageBoundaryError(
            f"L0 language normalization runtime is not configured: {exc}"
        ) from exc
    consistent, reason = deep_research.validate_spec_consistency(spec)
    if not consistent:
        raise L0LanguageBoundaryError(
            f"L0 language normalization runtime spec is inconsistent: {reason}"
        )
    ready, reason = structured_execution.runtime_ready(spec)
    if not ready:
        raise L0LanguageBoundaryError(
            f"L0 language normalization runtime is not ready: {reason}"
        )

    work = (
        Path(project_dir)
        / "08_Audit"
        / "l0_language_normalization"
        / str(candidate_id)
    )
    work.mkdir(parents=True, exist_ok=True)
    schema_path = work / "output.schema.json"
    schema_path.write_text(
        json.dumps(_schema(fields), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        command = structured_execution.build_invocation(spec, schema_path)
    except structured_execution.StructuredExecutionError as exc:
        raise L0LanguageBoundaryError(
            f"L0 language normalization invocation is invalid: {exc}"
        ) from exc
    prompt = _prompt(fields)
    command[0] = deep_research.resolve_subprocess_executable(command[0])
    execution_command, invocation_kwargs = deep_research.subprocess_invocation(
        command, prompt
    )
    completed = deep_research.execute_provider_invocation(
        execution_command,
        invocation_kwargs,
        timeout=spec.timeout,
        label="L0 user-language normalization",
    )
    if completed.returncode != 0:
        raise L0LanguageBoundaryError(
            f"L0 language normalization exited {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    try:
        payload = deep_research._parse_cli_output(completed.stdout)
    except deep_research.DeepResearchError as exc:
        raise L0LanguageBoundaryError(
            f"L0 language normalization returned invalid JSON: {exc}"
        ) from exc
    receipt = structured_execution.execution_receipt(
        spec.backend,
        command,
        prompt,
        exit_code=completed.returncode,
        stdout_hash=hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        model=spec.model,
        purpose="l0_user_language_to_internal_english",
    )
    return payload, receipt


def normalize_contract(project_dir: str | Path, candidate_id: str, contract: dict) -> dict:
    """Return one canonical-English copy of a not-yet-frozen L0 contract."""
    if not isinstance(contract, dict):
        raise L0LanguageBoundaryError("L0 contract must be a mapping")
    _validate_inherited_internal_semantics(contract)
    raw_fields = _user_fields(contract)
    raw_sha = _canonical_sha(raw_fields)

    from research_loop import l0_contract

    existing, _path, _raw = l0_contract.load_contract(project_dir, candidate_id)
    if isinstance(existing, dict):
        metadata = existing.get("language_normalization")
        if isinstance(metadata, dict) and metadata.get("input_sha256") == raw_sha:
            result = copy.deepcopy(contract)
            result["scientific_question"] = existing.get("scientific_question")
            result.setdefault("current_round", {})["hypothesis"] = (
                (existing.get("current_round") or {}).get("hypothesis")
            )
            if isinstance(result.get("source_input"), dict) and isinstance(
                existing.get("source_input"), dict
            ):
                result["source_input"]["description"] = (
                    existing["source_input"].get("description")
                )
            result["language_normalization"] = copy.deepcopy(metadata)
            return result
        if isinstance(metadata, dict):
            raise L0LanguageBoundaryError(
                "existing candidate language normalization was derived from different raw user semantics"
            )

    def translator(fields):
        return _translate(project_dir, candidate_id, fields)

    try:
        normalized, receipt = normalize_semantic_fields(
            raw_fields, translator=translator
        )
    except L0LanguageError as exc:
        raise L0LanguageBoundaryError(str(exc)) from exc

    result = copy.deepcopy(contract)
    result["scientific_question"] = normalized["scientific_question"]
    result.setdefault("current_round", {})["hypothesis"] = normalized["hypothesis"]
    if "source_description" in normalized and isinstance(result.get("source_input"), dict):
        result["source_input"]["description"] = normalized["source_description"]
    result["language_normalization"] = {
        "schema_version": "L0LanguageNormalization/v1",
        "mode": receipt["mode"],
        "source_languages": receipt["source_languages"],
        "target_language": "en",
        "input_sha256": raw_sha,
        "output_sha256": _canonical_sha(normalized),
        "provider_receipt": receipt.get("provider_receipt"),
    }
    return result


def _validate_normalized_contract(contract: dict) -> list[str]:
    metadata = contract.get("language_normalization")
    if metadata is None:
        return []  # historical artifacts remain readable
    errors = []
    if (
        not isinstance(metadata, dict)
        or metadata.get("schema_version") != "L0LanguageNormalization/v1"
    ):
        errors.append("language_normalization must be L0LanguageNormalization/v1")
        return errors
    for key, value in _user_fields(contract).items():
        try:
            validate_internal_english(value, name=key)
        except L0LanguageError as exc:
            errors.append(str(exc))
    if metadata.get("target_language") != "en":
        errors.append("language_normalization.target_language must be 'en'")
    if metadata.get("mode") not in {"passthrough", "translated"}:
        errors.append("language_normalization.mode must be passthrough or translated")
    if not isinstance(metadata.get("input_sha256"), str) or len(metadata["input_sha256"]) != 64:
        errors.append("language_normalization.input_sha256 must be a SHA256 digest")
    return errors


def install(lifecycle_module) -> None:
    """Install normalization only on the two formal new-candidate intake paths."""
    if getattr(lifecycle_module, "_l0_language_boundary_installed", False):
        return

    original_validator = lifecycle_module.l0_contract.validate_l0_input_contract

    def validate_l0_input_contract(*args, **kwargs):
        errors = list(original_validator(*args, **kwargs))
        contract = args[0] if args else kwargs.get("contract")
        if isinstance(contract, dict):
            errors.extend(
                f"[L0 internal language] {item}"
                for item in _validate_normalized_contract(contract)
            )
        return errors

    lifecycle_module.l0_contract.validate_l0_input_contract = validate_l0_input_contract

    original_new_candidate = lifecycle_module.cmd_new_candidate

    def cmd_new_candidate(args):
        original_initial = lifecycle_module.l0_contract.build_initial_contract
        original_continuation = lifecycle_module.l0_contract.build_continuation_contract
        project_dir = Path(args.project_dir)

        def initial(cand_id, round_id, question, source_input, new_hypothesis):
            raw = original_initial(
                cand_id, round_id, question, source_input, new_hypothesis
            )
            return normalize_contract(project_dir, cand_id, raw)

        def continuation(
            cand_id, round_id, parent_round_id, previous_candidate_id,
            question, source_input, previous_round, new_hypothesis,
        ):
            raw = original_continuation(
                cand_id, round_id, parent_round_id, previous_candidate_id,
                question, source_input, previous_round, new_hypothesis,
            )
            return normalize_contract(project_dir, cand_id, raw)

        lifecycle_module.l0_contract.build_initial_contract = initial
        lifecycle_module.l0_contract.build_continuation_contract = continuation
        try:
            return original_new_candidate(args)
        except L0LanguageBoundaryError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        finally:
            lifecycle_module.l0_contract.build_initial_contract = original_initial
            lifecycle_module.l0_contract.build_continuation_contract = original_continuation

    lifecycle_module.cmd_new_candidate = cmd_new_candidate

    original_normalize_command = lifecycle_module.cmd_normalize_l0_input

    def cmd_normalize_l0_input(args):
        original_normalize = lifecycle_module.l0_intake.normalize_request
        project_dir = Path(args.project)

        def normalize_request(*nargs, **nkwargs):
            result = original_normalize(*nargs, **nkwargs)
            contract = result.get("contract") if isinstance(result, dict) else None
            if not isinstance(contract, dict):
                return result
            candidate_id = str(contract.get("candidate_id") or "").strip()
            updated = dict(result)
            updated["contract"] = normalize_contract(
                project_dir, candidate_id, contract
            )
            return updated

        lifecycle_module.l0_intake.normalize_request = normalize_request
        try:
            return original_normalize_command(args)
        except L0LanguageBoundaryError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        finally:
            lifecycle_module.l0_intake.normalize_request = original_normalize

    lifecycle_module.cmd_normalize_l0_input = cmd_normalize_l0_input
    lifecycle_module._l0_language_boundary_installed = True
