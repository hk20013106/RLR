"""L1 frozen-evidence context injection for L0.5 Curie.

Historical v2.0 keeps its legacy path. Native v2.1 arrives here only after the
native evidence gate has validated one exact Curie binding and removed the
legacy Deep Research acquisition stage from the canonical context assembly.
This wrapper injects the exact bound frozen EvidencePack into Einstein's
rendered context and records the injection receipt.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from research_loop import l05_curie, research_seed
from research_loop.paths import _sha256


_L05_HEADER = "=== L0.5 CURIE FROZEN EVIDENCEPACK ==="
_PRE_RESEARCH_PREFIX = "=== PRE-RESEARCH"
_CONTRACT_PREFIX = "=== CONTRACT: L1"


class L05ContextError(ValueError):
    """Raised when L1 cannot consume its frozen L0.5 evidence state."""


def _manifest_path(stderr_text: str) -> Path:
    prefix = "[audit] context manifest:"
    matches = [
        line[len(prefix):].strip()
        for line in stderr_text.splitlines()
        if line.startswith(prefix)
    ]
    if len(matches) != 1:
        raise L05ContextError(
            "assembled L1 context did not report exactly one manifest"
        )
    return Path(matches[0])


def _replace_legacy_pre_research(context_text: str, evidence_text: str) -> str:
    """Compatibility helper for historical native bridge fixtures."""
    lines = context_text.splitlines()
    starts = [
        index for index, line in enumerate(lines)
        if line.startswith(_PRE_RESEARCH_PREFIX)
    ]
    if len(starts) != 1:
        raise L05ContextError(
            "rendered context must contain exactly one legacy pre-research block"
        )
    start = starts[0]
    end = None
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("=== ") and not line.startswith(_PRE_RESEARCH_PREFIX):
            end = index
            break
    if end is None:
        raise L05ContextError(
            "legacy pre-research block has no following context boundary"
        )
    replacement = evidence_text.rstrip().splitlines() + [""]
    rendered = "\n".join(lines[:start] + replacement + lines[end:])
    if context_text.endswith("\n"):
        rendered += "\n"
    return rendered


def _insert_native_evidence(context_text: str, evidence_text: str) -> str:
    """Insert frozen Curie evidence before the L1 contract boundary exactly once."""
    lines = context_text.splitlines()
    contract_indexes = [
        index for index, line in enumerate(lines)
        if line.startswith(_CONTRACT_PREFIX)
    ]
    if len(contract_indexes) != 1:
        raise L05ContextError(
            "native L1 rendered context must contain exactly one L1 contract boundary"
        )
    if any(line.startswith(_L05_HEADER) for line in lines):
        raise L05ContextError("native L1 rendered context already contains L0.5 evidence")
    index = contract_indexes[0]
    insertion = evidence_text.rstrip().splitlines() + [""]
    rendered = "\n".join(lines[:index] + insertion + lines[index:])
    if context_text.endswith("\n"):
        rendered += "\n"
    return rendered


def _remove_generated_context(manifest_path: Path | None, rendered_path: Path | None) -> None:
    if rendered_path is not None:
        rendered_path.unlink(missing_ok=True)
    if manifest_path is not None:
        manifest_path.unlink(missing_ok=True)


def install(context_module) -> None:
    """Install frozen-evidence injection once."""
    if getattr(context_module, "_l05_context_installed", False):
        return
    original = context_module.cmd_assemble_context

    def cmd_assemble_context(args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = original(args)
        original_stdout = stdout.getvalue()
        original_stderr = stderr.getvalue()
        if rc != 0 or str(getattr(args, "node", "")) != "L1":
            sys.stdout.write(original_stdout)
            sys.stderr.write(original_stderr)
            return rc

        manifest_path: Path | None = None
        rendered_path: Path | None = None
        try:
            manifest_path = _manifest_path(original_stderr)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            # Historical v2.0 remains untouched.
            if str(manifest.get("delta_schema_version") or "") != "2.1":
                sys.stdout.write(original_stdout)
                sys.stderr.write(original_stderr)
                return 0

            project = Path(args.project_dir)
            seed = research_seed.load_l1_research_seed(project, str(args.cand_id))
            pre_research = manifest.get("pre_research")
            if not isinstance(pre_research, dict):
                raise L05ContextError(
                    "native L1 context manifest has no exact acquisition provenance"
                )
            run_id = str(pre_research.get("evidence_run_id") or "")
            if not run_id:
                raise L05ContextError(
                    "native L1 context manifest has no exact evidence_run_id"
                )

            native_entry = pre_research.get("native_evidence_binding")
            legacy_source_identity = not isinstance(native_entry, dict)
            if isinstance(native_entry, dict):
                binding = research_seed.load_l1_native_evidence_binding(
                    project, seed, run_id
                )
                injection_mode = "l05_native_frozen_pack"
                native_mode = True
            else:
                # Temporary compatibility for historical native bridge fixtures.
                # New native v2.1 runtime is gated earlier and cannot reach this
                # branch without an explicit native binding.
                binding = research_seed.load_l1_evidence_binding(
                    project, seed, run_id
                )
                injection_mode = "l05_frozen_pack"
                native_mode = False

            pack_manifest = binding.get("evidence_pack")
            if not isinstance(pack_manifest, dict):
                raise L05ContextError(
                    "L1 evidence binding has no frozen EvidencePack"
                )
            frozen = l05_curie.load_frozen_evidence_pack(
                project,
                pack_manifest,
                candidate_id=str(seed["candidate_id"]),
                round_id=str(seed["round_id"]),
                seed_sha256=research_seed.seed_sha256(seed),
                allow_legacy_source_identity=legacy_source_identity,
            )
            if str(frozen.get("source_run_id") or "") != run_id:
                raise L05ContextError(
                    "frozen EvidencePack is not derived from the selected acquisition run"
                )
            evidence_text = l05_curie.render_evidence_context(
                frozen,
                allow_legacy_frozen_acquisition_metadata=True,
                allow_legacy_source_identity=legacy_source_identity,
            )

            rendered_path = Path(str(manifest["rendered_context_path"]))
            current_context = rendered_path.read_text(encoding="utf-8")
            context_text = (
                _insert_native_evidence(current_context, evidence_text)
                if native_mode else
                _replace_legacy_pre_research(current_context, evidence_text)
            )
            budget = int(getattr(args, "context_token_budget", 8000) or 0)
            estimated = context_module._estimate_tokens(context_text)
            if budget and estimated > budget:
                raise L05ContextError(
                    "context token budget exceeded after frozen EvidencePack "
                    f"injection (~{estimated} > {budget})"
                )

            rendered_path.write_text(context_text, encoding="utf-8")
            manifest["rendered_context_sha256"] = _sha256(rendered_path)
            manifest["pre_research"] = {
                **pre_research,
                "injected_mode": injection_mode,
                "injected_tokens_est": context_module._estimate_tokens(evidence_text),
                "full_text_injected": False,
                "legacy_summary_injected": False,
                "evidence_pack": pack_manifest,
            }
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            research_seed.ResearchSeedError,
            l05_curie.CurieContractError,
            L05ContextError,
        ) as exc:
            _remove_generated_context(manifest_path, rendered_path)
            print(f"ERROR: L0.5 evidence pack gate -- {exc}", file=sys.stderr)
            return 3

        print(context_text)
        sys.stderr.write(original_stderr)
        return 0

    context_module.cmd_assemble_context = cmd_assemble_context
    context_module._l05_context_installed = True
