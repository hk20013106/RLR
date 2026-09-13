"""Provider call used only for the one-time L0 Chinese-to-English translation."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from research_loop import deep_research, structured_execution


class L0LanguageProviderError(ValueError):
    pass


def _translate(project_dir, candidate_id, fields):
    try:
        spec, _ = deep_research.load_runtime_spec(project_dir)
    except deep_research.DeepResearchError as exc:
        raise L0LanguageProviderError(
            f"L0 language normalization runtime is not configured: {exc}"
        ) from exc

    consistent, reason = deep_research.validate_spec_consistency(spec)
    if not consistent:
        raise L0LanguageProviderError(
            f"L0 language normalization runtime spec is inconsistent: {reason}"
        )
    ready, reason = structured_execution.runtime_ready(spec)
    if not ready:
        raise L0LanguageProviderError(
            f"L0 language normalization runtime is not ready: {reason}"
        )

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            key: {"type": "string", "minLength": 1}
            for key in fields
        },
        "required": list(fields),
    }
    prompt = (
        "Translate Chinese scientific prose to precise standard English. "
        "Return JSON with exactly the same keys. Copy fields already in English "
        "exactly. Preserve genes, proteins, abbreviations, numbers, paths, IDs, "
        "code, uncertainty, negation, comparisons, and hypothesis strength. "
        "Do not answer, summarize, expand, reinterpret, browse, search literature, "
        "or add evidence. Input: "
        + json.dumps(fields, ensure_ascii=False, sort_keys=True)
    )

    with tempfile.TemporaryDirectory(prefix="rlr-l0-language-") as tmp:
        schema_path = Path(tmp) / "output.schema.json"
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            command = structured_execution.build_invocation(spec, schema_path)
        except structured_execution.StructuredExecutionError as exc:
            raise L0LanguageProviderError(
                f"L0 language normalization invocation is invalid: {exc}"
            ) from exc
        command[0] = deep_research.resolve_subprocess_executable(command[0])
        execution_command, kwargs = deep_research.subprocess_invocation(command, prompt)
        completed = deep_research.execute_provider_invocation(
            execution_command,
            kwargs,
            timeout=spec.timeout,
            label="L0 user-language normalization",
        )

    if completed.returncode != 0:
        raise L0LanguageProviderError(
            f"L0 language normalization exited {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    try:
        payload = deep_research._parse_cli_output(completed.stdout)
    except deep_research.DeepResearchError as exc:
        raise L0LanguageProviderError(
            f"L0 language normalization returned invalid JSON: {exc}"
        ) from exc
    return payload, {"backend": spec.backend, "model": spec.model}
