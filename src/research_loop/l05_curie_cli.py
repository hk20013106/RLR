"""Thin CLI extension for the L0.5 Europe PMC acquisition runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from research_loop import deep_research, research_seed, structured_execution
from research_loop.l05_curie import CurieContractError
from research_loop.l05_curie.europepmc_runtime import (
    run_europepmc_acquisition,
    run_paperqa2_europepmc_acquisition,
)
from research_loop.l05_curie.paperqa2_runtime import (
    PaperQA2CurieRuntime,
    PaperQA2SubprocessBackend,
)
from research_loop.l05_curie.query_language import (
    validate_english_retrieval_queries,
)
from research_loop.l05_curie.query_planner import (
    MAX_QUERY_CANDIDATES,
    MIN_QUERY_CANDIDATES,
    requires_provider_planning,
)
from research_loop.providers import CommandProvider, ProviderError

_SEMANTIC_ASSESSMENT_SCHEMA = {
    "entailment": "SUPPORTED | CONTRADICTED | AMBIGUOUS | UNRELATED",
    "scope_match": bool,
    "context_preserved": bool,
    "qualification_preserved": bool,
    "reason": str,
}
_QUERY_PLANNING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "queries": {
            "type": "array",
            "minItems": MIN_QUERY_CANDIDATES,
            "maxItems": MAX_QUERY_CANDIDATES,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        },
    },
    "required": ["queries"],
}


def _query_planner_prompt(seed: dict) -> str:
    return f"""RLR stage: L0.5 Scientific Literature Query Planning
Scientific question: {seed['scientific_question']}
Hypothesis seed: {seed['hypothesis_seed']}

Return JSON only with one field named queries. Produce between
{MIN_QUERY_CANDIDATES} and {MAX_QUERY_CANDIDATES} concise English scientific
literature-search queries suitable for PubMed, Europe PMC, OpenAlex, Crossref,
and Semantic Scholar. Preserve the scientific meaning of the question and
hypothesis, but express the retrieval concepts in standard English scientific
terminology. Use complementary query formulations rather than translations
that merely repeat the same wording.

Do not search literature. Do not browse the web. Do not return papers,
citations, DOI/PMID/PMCID values, evidence, conclusions, or claims about what
the literature contains. Do not include CJK characters in any query. Do not
include prose, Markdown, code fences, commentary, or fields other than queries.
"""


def _persist_query_planner_receipt(
    project_dir: str | Path,
    cand_id: str,
    *,
    seed: dict,
    queries: list[str],
    command: list[str],
    prompt: str,
    completed,
    spec,
) -> None:
    root = (
        Path(project_dir)
        / "08_Audit"
        / "l05_query_planner"
        / str(cand_id)
    )
    root.mkdir(parents=True, exist_ok=True)
    receipt = structured_execution.execution_receipt(
        spec.backend,
        command,
        prompt,
        exit_code=completed.returncode,
        stdout_hash=hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        model=spec.model,
        purpose="l05_scientific_query_planning",
    )
    payload = {
        "schema_version": "L05ScientificQueryPlanningReceipt/v1",
        "candidate_id": str(cand_id),
        "seed_sha256": research_seed.seed_sha256(seed),
        "queries": list(queries),
        "provider_receipt": receipt,
    }
    path = root / "query_planning_receipt.json"
    raw = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != raw:
        raise CurieContractError(
            "L0.5 query-planning receipt already exists with different content"
        )
    if not path.exists():
        path.write_text(raw, encoding="utf-8")


def _provider_planned_queries(
    project_dir: str | Path,
    cand_id: str,
    seed: dict,
) -> list[str]:
    try:
        spec, _skill_version = deep_research.load_runtime_spec(project_dir)
    except deep_research.DeepResearchError as exc:
        raise CurieContractError(
            f"L0.5 query planner runtime is not configured: {exc}"
        ) from exc
    consistent, reason = deep_research.validate_spec_consistency(spec)
    if not consistent:
        raise CurieContractError(
            f"L0.5 query planner runtime spec is inconsistent: {reason}"
        )
    ready, reason = structured_execution.runtime_ready(spec)
    if not ready:
        raise CurieContractError(
            f"L0.5 query planner runtime is not ready: {reason}"
        )

    work = (
        Path(project_dir)
        / "08_Audit"
        / "l05_query_planner"
        / str(cand_id)
    )
    work.mkdir(parents=True, exist_ok=True)
    schema_path = work / "query_planner_output.schema.json"
    schema_path.write_text(
        json.dumps(_QUERY_PLANNING_SCHEMA, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        command = structured_execution.build_invocation(spec, schema_path)
    except structured_execution.StructuredExecutionError as exc:
        raise CurieContractError(
            f"L0.5 query planner invocation is invalid: {exc}"
        ) from exc
    prompt = _query_planner_prompt(seed)
    command[0] = deep_research.resolve_subprocess_executable(command[0])
    execution_command, invocation_kwargs = deep_research.subprocess_invocation(
        command, prompt
    )
    completed = deep_research.execute_provider_invocation(
        execution_command,
        invocation_kwargs,
        timeout=spec.timeout,
        label="L0.5 scientific-query planner",
    )
    if completed.returncode != 0:
        raise CurieContractError(
            f"L0.5 scientific-query planner exited {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    try:
        payload = deep_research._parse_cli_output(completed.stdout)
    except deep_research.DeepResearchError as exc:
        raise CurieContractError(
            f"L0.5 scientific-query planner returned invalid JSON: {exc}"
        ) from exc
    queries = validate_english_retrieval_queries(
        payload.get("queries"),
        name="provider-planned English retrieval queries",
        min_items=MIN_QUERY_CANDIDATES,
        max_items=MAX_QUERY_CANDIDATES,
    )
    _persist_query_planner_receipt(
        project_dir,
        cand_id,
        seed=seed,
        queries=queries,
        command=command,
        prompt=prompt,
        completed=completed,
        spec=spec,
    )
    return queries


def _resolved_l05_queries(
    project_dir: str | Path,
    cand_id: str,
    explicit_queries: list[str] | None,
) -> list[str] | None:
    if explicit_queries:
        return validate_english_retrieval_queries(
            list(explicit_queries),
            name="explicit English retrieval queries",
        )
    try:
        seed = research_seed.load_l1_research_seed(project_dir, cand_id)
    except research_seed.ResearchSeedError as exc:
        raise CurieContractError(
            f"canonical ResearchSeed is invalid: {exc}"
        ) from exc
    if not requires_provider_planning(seed):
        return None
    return _provider_planned_queries(project_dir, cand_id, seed)


def cmd_l05_acquire_europepmc(args) -> int:
    try:
        queries = _resolved_l05_queries(
            args.project_dir, args.cand_id, args.queries or None
        )
        result = run_europepmc_acquisition(
            args.project_dir,
            args.cand_id,
            explicit_queries=queries,
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
        queries = _resolved_l05_queries(
            args.project_dir, args.cand_id, args.queries or None
        )
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
            explicit_queries=queries,
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
