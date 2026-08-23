"""Executor-backed Deep Research process boundary.

Installed before provider-runtime observability so observability supervises the
final executor-backed implementation rather than a legacy subprocess path.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from research_loop.providers.executor import (
    DEFAULT_EXECUTOR,
    ProviderExecutionError,
)


def install(deep_research_module) -> None:
    dr = deep_research_module
    if getattr(dr, "_PROVIDER_EXECUTOR_INSTALLED", False):
        return

    def run_and_persist(
        project_dir,
        candidate_id,
        node,
        question,
        claim,
        spec,
        work_dir,
        skill_version="unknown",
        result_context="",
        *,
        project_id="",
        round_id="",
        profile_id="",
        research_persona="Curie",
    ):
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        schema_path = work_dir / "deep_research_output.schema.json"
        schema_path.write_text(
            dr.json.dumps(dr._runtime_schema(node), indent=2),
            encoding="utf-8",
        )
        command, prompt = dr.build_invocation(
            spec, node, question, claim, work_dir, result_context
        )
        command[0] = dr.resolve_subprocess_executable(command[0])
        execution_command, invocation_kwargs = dr.subprocess_invocation(
            command, prompt
        )
        input_text = invocation_kwargs.get("input")
        try:
            completed = DEFAULT_EXECUTOR.run(
                execution_command,
                timeout=spec.timeout,
                input_text=input_text,
                check=False,
                encoding="utf-8",
                errors="strict",
            )
        except ProviderExecutionError as exc:
            detail = exc.stderr.strip() or str(exc)
            if exc.timed_out:
                raise dr.DeepResearchError(
                    f"Academic Research CLI timed out after {exc.timeout}s: {detail}"
                ) from exc
            raise dr.DeepResearchError(
                f"Academic Research CLI invocation failed: {detail}"
            ) from exc

        receipt = dr.skill_receipt(
            spec.backend,
            command,
            prompt,
            skill_version,
            exit_code=completed.returncode,
            stdout_hash=dr._sha(completed.stdout),
            model=spec.model,
        )
        if completed.returncode != 0:
            raise dr.DeepResearchError(
                f"Academic Research CLI exited {completed.returncode}: "
                f"{completed.stderr.strip()}"
            )
        artifact = dr.persist_run(
            project_dir,
            candidate_id,
            node,
            dr._parse_cli_output(completed.stdout),
            receipt,
            result_context,
            project_id=project_id,
            round_id=round_id,
            profile_id=profile_id,
            research_persona=research_persona,
        )
        target = (
            Path(project_dir)
            / "02_Agent_Notes"
            / "_pre_research"
            / f"{node}_research.md"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            dr.render_pre_research_markdown(artifact), encoding="utf-8"
        )
        return artifact

    # Make the installed owner explicit to tests/introspection.
    run_and_persist.__name__ = "run_and_persist"
    run_and_persist.__qualname__ = "run_and_persist"
    dr.run_and_persist = run_and_persist
    dr._PROVIDER_EXECUTOR_INSTALLED = True
