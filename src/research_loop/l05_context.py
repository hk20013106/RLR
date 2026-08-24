"""Native L1 context handoff from legacy acquisition to frozen L0.5 evidence.

This wrapper is deliberately installed *inside* the historical-hypothesis-recall
wrapper.  The canonical ContextAssembler therefore performs all existing Deep
Research, identity, divergence, and branch-coverage gates first.  Only after
those gates pass do we replace the human-facing legacy pre-research summary in
Einstein's context with the exact frozen L0.5 EvidencePack bound to that run.
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


class L05ContextError(ValueError):
    """Raised when native L1 cannot consume its frozen L0.5 evidence state."""


def _manifest_path(stderr_text: str) -> Path:
    prefix = "[audit] context manifest:"
    matches = [
        line[len(prefix):].strip()
        for line in stderr_text.splitlines()
        if line.startswith(prefix)
    ]
    if len(matches) != 1:
        raise L05ContextError(
            "assembled native L1 context did not report exactly one manifest"
        )
    return Path(matches[0])


def _replace_legacy_pre_research(context_text: str, evidence_text: str) -> str:
    """Replace exactly one generated PRE-RESEARCH block with frozen evidence."""
    lines = context_text.splitlines()
    starts = [
        index for index, line in enumerate(lines)
        if line.startswith(_PRE_RESEARCH_PREFIX)
    ]
    if len(starts) != 1:
        raise L05ContextError(
            "native L1 rendered context must contain exactly one pre-research block"
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
            "native L1 pre-research block has no following context boundary"
        )
    replacement = evidence_text.rstrip().splitlines() + [""]
    rendered = "\n".join(lines[:start] + replacement + lines[end:])
    if context_text.endswith("\n"):
        rendered += "\n"
    return rendered


def _remove_generated_context(manifest_path: Path | None, rendered_path: Path | None) -> None:
    if rendered_path is not None:
        rendered_path.unlink(missing_ok=True)
    if manifest_path is not None:
        manifest_path.unlink(missing_ok=True)


def install(context_module) -> None:
    """Install the native L1 frozen-evidence handoff once."""
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
            # Historical v2.0 remains untouched.  L0.5 is the native v2.1
            # evidence boundary and does not silently change legacy behavior.
            if str(manifest.get("delta_schema_version") or "") != "2.1":
                sys.stdout.write(original_stdout)
                sys.stderr.write(original_stderr)
                return 0

            project = Path(args.project_dir)
            seed = research_seed.load_l1_research_seed(
                project, str(args.cand_id)
            )
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

            binding = research_seed.load_l1_evidence_binding(
                project, seed, run_id
            )
            pack_manifest = binding.get("evidence_pack")
            if not isinstance(pack_manifest, dict):
                raise L05ContextError(
                    "native L1 evidence binding has no frozen EvidencePack"
                )
            frozen = l05_curie.load_frozen_evidence_pack(
                project,
                pack_manifest,
                candidate_id=str(seed["candidate_id"]),
                round_id=str(seed["round_id"]),
                seed_sha256=research_seed.seed_sha256(seed),
            )
            if str(frozen.get("source_run_id") or "") != run_id:
                raise L05ContextError(
                    "frozen EvidencePack is not derived from the selected acquisition run"
                )
            evidence_text = l05_curie.render_evidence_context(frozen)

            rendered_path = Path(str(manifest["rendered_context_path"]))
            current_context = rendered_path.read_text(encoding="utf-8")
            context_text = _replace_legacy_pre_research(
                current_context, evidence_text
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
                "injected_mode": "l05_frozen_pack",
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
