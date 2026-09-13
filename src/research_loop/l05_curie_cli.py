"""Thin CLI extension for the L0.5 Europe PMC acquisition runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from research_loop import deep_research, research_seed, structured_execution
from research_loop.l0_language import L0LanguageError, normalize_semantic_fields
from research_loop.l05_curie import CurieContractError
from research_loop.l05_curie.europepmc_runtime import (
    run_europepmc_acquisition,
    run_paperqa2_europepmc_acquisition,
)
from research_loop.l05_curie.paperqa2_runtime import (
    PaperQA2CurieRuntime,
    PaperQA2SubprocessBackend,
)
from research_loop.providers import CommandProvider, ProviderError

_SEMANTIC_ASSESSMENT_SCHEMA = {
    "entailment": "SUPPORTED | CONTRADICTED | AMBIGUOUS | UNRELATED",
    "scope_match": bool,
    "context_preserved": bool,
    "qualification_preserved": bool,
    "reason": str,
}
_ENGLISH_SEED_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scientific_question": {"type": "string", "minLength": 1},
        "hypothesis_seed": {"type": "string", "minLength": 1},
    },
    "required": ["scientific_question", "hypothesis_seed"],
}


def _seed_normalization_prompt(fields: dict[str, str]) -> str:
    return f"""RLR boundary: user-language normalization into canonical internal English.

User semantic fields:
{json.dumps(fields, ensure_ascii=False, sort_keys=True)}

Return JSON only with exactly two fields: scientific_question and
hypothesis_seed.

Rules:
- Chinese input must be translated into precise standard English scientific terminology.
- English input must be copied exactly, byte-for-byte after surrounding whitespace is removed.
- Preserve gene/protein names, abbreviations, numbers, directionality, comparisons,
  tissue/cell types, causal qualifiers, uncertainty, and hypothesis strength.
- Do not summarize, expand, reinterpret, answer, search literature, browse the web,
  add citations, or change the scientific claim.
- Output must contain English natural-language text only, apart from normal
  scientific symbols such as Greek letters.
- Return no prose, Markdown, code fences, commentary, or extra fields.
"""


def _provider_translate_seed(
    project_dir: str | Path,
    cand_id: str,
    fields: dict[str, str],
) -> tuple[dict[str, str], dict]:
    try:
        spec, _skill_version = deep_research.load_runtime_spec(project_dir)
    except deep_research.DeepResearchError as exc:
        raise CurieContractError(
            f"L0 English normalization runtime is not configured: {exc}"
        ) from exc
    consistent, reason = deep_research.validate_spec_consistency(spec)
    if not consistent:
        raise CurieContractError(
            f"L0 English normalization runtime spec is inconsistent: {reason}"
        )
    ready, reason = structured_execution.runtime_ready(spec)
    if not ready:
        raise CurieContractError(
            f"L0 English normalization runtime is not ready: {reason}"
        )

    work = Path(project_dir) / "08_Audit" / "research_seed_bindings" / "english" / str(cand_id)
    work.mkdir(parents=True, exist_ok=True)
    schema_path = work / "english_seed_output.schema.json"
    schema_path.write_text(
        json.dumps(_ENGLISH_SEED_SCHEMA, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        command = structured_execution.build_invocation(spec, schema_path)
    except structured_execution.StructuredExecutionError as exc:
        raise CurieContractError(
            f"L0 English normalization invocation is invalid: {exc}"
        ) from exc
    prompt = _seed_normalization_prompt(fields)
    command[0] = deep_research.resolve_subprocess_executable(command[0])
    execution_command, invocation_kwargs = deep_research.subprocess_invocation(
        command, prompt
    )
    completed = deep_research.execute_provider_invocation(
        execution_command,
        invocation_kwargs,
        timeout=spec.timeout,
        label="L0 Chinese-to-English semantic normalization",
    )
    if completed.returncode != 0:
        raise CurieContractError(
            f"L0 English normalization exited {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    try:
        payload = deep_research._parse_cli_output(completed.stdout)
    except deep_research.DeepResearchError as exc:
        raise CurieContractError(
            f"L0 English normalization returned invalid JSON: {exc}"
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


def _ensure_english_research_seed(project_dir: str | Path, cand_id: str) -> dict:
    # Fast path: English raw input passes through, and Chinese input with an
    # already-frozen valid projection reuses that projection without a model call.
    try:
        return research_seed.load_l1_research_seed(project_dir, cand_id)
    except research_seed.ResearchSeedError as exc:
        projection_path = research_seed._english_seed_path(project_dir, cand_id)
        if projection_path.is_file():
            # Existing but invalid projections are immutable failures; never
            # hide corruption or semantic drift by retranslating over them.
            raise CurieContractError(
                f"canonical English ResearchSeed is invalid: {exc}"
            ) from exc

    try:
        raw_seed = research_seed.load_l0_research_seed(project_dir, cand_id)
    except research_seed.ResearchSeedError as exc:
        raise CurieContractError(f"canonical L0 ResearchSeed is invalid: {exc}") from exc
    source_fields = {
        "scientific_question": str(raw_seed["scientific_question"]),
        "hypothesis_seed": str(raw_seed["hypothesis_seed"]),
    }

    def translator(fields):
        return _provider_translate_seed(project_dir, cand_id, fields)

    try:
        normalized, receipt = normalize_semantic_fields(
            source_fields,
            translator=translator,
        )
    except L0LanguageError as exc:
        raise CurieContractError(str(exc)) from exc
    if receipt["mode"] != "translated":
        # An English raw seed should have succeeded in the fast path. Reaching
        # this state means the internal projection contract is inconsistent.
        raise CurieContractError(
            "English ResearchSeed passthrough failed before normalization"
        )
    try:
        research_seed.write_english_research_seed(
            project_dir,
            raw_seed,
            normalized,
            receipt,
        )
        return research_seed.load_l1_research_seed(project_dir, cand_id)
    except research_seed.ResearchSeedError as exc:
        raise CurieContractError(
            f"canonical English ResearchSeed is invalid: {exc}"
        ) from exc


def _english_explicit_queries(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    from research_loop.l0_language import validate_internal_english

    result = []
    seen = set()
    for index, value in enumerate(values, 1):
        try:
            query = validate_internal_english(
                value, name=f"explicit literature query {index}"
            )
        except L0LanguageError as exc:
            raise CurieContractError(str(exc)) from exc
        key = query.casefold()
        if key in seen:
            raise CurieContractError("explicit literature queries must be distinct")
        seen.add(key)
        result.append(query)
    return result


def cmd_l05_acquire_europepmc(args) -> int:
    try:
        _ensure_english_research_seed(args.project_dir, args.cand_id)
        result = run_europepmc_acquisition(
            args.project_dir,
            args.cand_id,
            explicit_queries=_english_explicit_queries(args.queries),
            max_papers=args.max_papers,
            page_size=args.page_size,
            run_id=args.run_id,
            timeout=args.timeout,
        )
    except CurieContractError as exc:
        print(f"ERROR: L0.5 Europe PMC acquisition -- {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def _load_pdf_paths(path: str) -> dict[str, str]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise CurieContractError(f"PaperQA2 PDF map is unreadable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CurieContractError(f"PaperQA2 PDF map is not JSON: {exc}") from exc
    if not isinstance(value, dict) or not value:
        raise CurieContractError("PaperQA2 PDF map must be a non-empty object")
    paths = {}
    for paper_id, pdf_path in value.items():
        if not str(paper_id).strip() or not isinstance(pdf_path, str) or not pdf_path.strip():
            raise CurieContractError(
                "PaperQA2 PDF map keys and values must be non-empty strings"
            )
        paths[str(paper_id)] = pdf_path
    return paths


def _semantic_assessor_from_command(
    command: str,
    *,
    run_dir: str | Path,
    timeout: int,
):
    """Adapt an explicit headless command to the fixed semantic-assessor contract."""
    command = str(command or "").strip()
    if not command:
        raise CurieContractError("PaperQA2 semantic assessor command must be non-empty")
    try:
        provider = CommandProvider({"command": command, "timeout": timeout})
    except ProviderError as exc:
        raise CurieContractError(f"PaperQA2 semantic assessor is invalid: {exc}") from exc
    root = Path(run_dir)
    counter = 0

    def assessor(*, extract: dict, claim: str) -> dict:
        nonlocal counter
        counter += 1
        context = (
            "Assess whether the independently LOCATED scientific extract supports, "
            "contradicts, is ambiguous for, or is unrelated to the ResearchSeed target. "
            "Judge scope, context, and qualification preservation. Do not rewrite the "
            "extract or claim.\n\n"
            + json.dumps(
                {"claim": claim, "extract": extract},
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        try:
            result = provider.run_agent(
                "L0.5",
                "SemanticVerifier",
                context,
                output_schema=_SEMANTIC_ASSESSMENT_SCHEMA,
                run_dir=root / f"assessment_{counter:04d}",
            )
        except Exception as exc:
            raise CurieContractError(
                f"PaperQA2 semantic assessor command failed: {exc}"
            ) from exc
        if not isinstance(result, dict):
            raise CurieContractError("PaperQA2 semantic assessor command must return JSON object")
        return result

    command_sha = hashlib.sha256(command.encode("utf-8")).hexdigest()
    return assessor, f"l05-semantic-command-sha256/{command_sha}"


def cmd_l05_acquire_paperqa2_europepmc(args) -> int:
    try:
        _ensure_english_research_seed(args.project_dir, args.cand_id)
        backend = PaperQA2SubprocessBackend(
            python_executable=args.paperqa_python,
            bridge_script=args.paperqa_bridge,
            paperqa_repo=args.paperqa_repo,
            pqa_home=args.pqa_home,
            timeout_seconds=args.paperqa_timeout,
        )
        runtime = PaperQA2CurieRuntime(
            backend=backend,
            backend_id=backend.backend_id,
        )
        semantic_assessor, semantic_assessor_id = _semantic_assessor_from_command(
            args.semantic_assessor_command,
            run_dir=Path(args.pqa_home) / "semantic-assessor" / str(args.cand_id),
            timeout=args.semantic_assessor_timeout,
        )
        result = run_paperqa2_europepmc_acquisition(
            args.project_dir,
            args.cand_id,
            paperqa_runtime=runtime,
            pdf_paths=_load_pdf_paths(args.pdf_map),
            semantic_assessor=semantic_assessor,
            semantic_assessor_id=semantic_assessor_id,
            explicit_queries=_english_explicit_queries(args.queries),
            max_papers=args.max_papers,
            page_size=args.page_size,
            run_id=args.run_id,
            timeout=args.timeout,
        )
    except CurieContractError as exc:
        print(f"ERROR: L0.5 PaperQA2 Europe PMC acquisition -- {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def install(cli_module) -> None:
    """Install the Europe PMC command without duplicating canonical parser code."""
    if getattr(cli_module, "_l05_europepmc_cli_installed", False):
        return
    original_build_parser = cli_module.build_parser

    def build_parser():
        parser = original_build_parser()
        subparsers = next(
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        command = subparsers.add_parser(
            "l05-acquire-europepmc",
            help="run one auditable L0.5 Europe PMC acquisition round through FREEZE",
        )
        command.add_argument("project_dir")
        command.add_argument("cand_id")
        command.add_argument(
            "--query", dest="queries", action="append", default=None,
            help="explicit reproducible English Europe PMC query (repeatable)",
        )
        command.add_argument("--max-papers", type=int, default=3)
        command.add_argument("--page-size", type=int, default=25)
        command.add_argument("--timeout", type=int, default=20)
        command.add_argument("--run-id", default=None)
        command.set_defaults(func=cmd_l05_acquire_europepmc)

        paperqa = subparsers.add_parser(
            "l05-acquire-paperqa2-europepmc",
            help="run pinned PaperQA2 retrieval through Europe PMC verification into L1 v1",
        )
        paperqa.add_argument("project_dir")
        paperqa.add_argument("cand_id")
        paperqa.add_argument("--paperqa-python", required=True)
        paperqa.add_argument("--paperqa-bridge", required=True)
        paperqa.add_argument("--paperqa-repo", required=True)
        paperqa.add_argument("--pqa-home", required=True)
        paperqa.add_argument("--pdf-map", required=True)
        paperqa.add_argument(
            "--semantic-assessor-command",
            required=True,
            help=(
                "headless command template for semantic assessment; must write the JSON "
                "assessment to {output_file} and may read {prompt_file}"
            ),
        )
        paperqa.add_argument("--semantic-assessor-timeout", type=int, default=300)
        paperqa.add_argument(
            "--query", dest="queries", action="append", default=None,
            help="explicit reproducible English Europe PMC query (repeatable)",
        )
        paperqa.add_argument("--max-papers", type=int, default=3)
        paperqa.add_argument("--page-size", type=int, default=25)
        paperqa.add_argument("--timeout", type=int, default=20)
        paperqa.add_argument("--paperqa-timeout", type=int, default=300)
        paperqa.add_argument("--run-id", default=None)
        paperqa.set_defaults(func=cmd_l05_acquire_paperqa2_europepmc)
        return parser

    cli_module.build_parser = build_parser
    cli_module._l05_europepmc_cli_installed = True
