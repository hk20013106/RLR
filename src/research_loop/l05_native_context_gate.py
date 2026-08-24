"""Native v2.1 L1 acquisition gate replacement.

The historical ContextAssembler owns the legacy Deep Research pre-research gate.
For native v2.1 L1, that gate would preserve a second acquisition authority even
when a frozen Curie EvidencePack is already bound. This wrapper validates the
native binding first, then suppresses only the legacy L1 pre-research stage for
the duration of the canonical context assembly call. The shared map is restored
in ``finally`` so historical v2.0 and all other nodes retain their behavior.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from research_loop import research_seed
from research_loop.hypothesis_ledger import binding_path
from research_loop.preresearch import PRE_RESEARCH_MAP


class NativeL1EvidenceGateError(ValueError):
    """Raised when native L1 lacks one exact validated Curie binding."""


def _is_native_l1(args) -> bool:
    if str(getattr(args, "node", "")) != "L1":
        return False
    project = Path(args.project_dir)
    path = binding_path(project)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return str(payload.get("profile_id") or "") == "native-v2.1"


def _selected_run_id(project: Path, seed: dict, args) -> str:
    explicit = str(getattr(args, "evidence_run_id", "") or "").strip()
    if explicit:
        return explicit
    run_id = research_seed.unique_l1_native_evidence_run_id(project, seed)
    if run_id:
        return str(run_id)
    raise NativeL1EvidenceGateError(
        "native L1 evidence binding is missing or ambiguous; select one exact Curie acquisition run"
    )


def install(context_module) -> None:
    """Install the native evidence authority gate once."""
    if getattr(context_module, "_l05_native_context_gate_installed", False):
        return
    original = context_module.cmd_assemble_context

    def cmd_assemble_context(args):
        if not _is_native_l1(args):
            return original(args)

        project = Path(args.project_dir)
        try:
            seed = research_seed.load_l1_research_seed(project, str(args.cand_id))
            run_id = _selected_run_id(project, seed, args)
            binding = research_seed.load_l1_native_evidence_binding(
                project, seed, run_id
            )
            binding_entry = research_seed.native_evidence_binding_manifest_entry(
                project, seed, run_id
            )
        except (research_seed.ResearchSeedError, NativeL1EvidenceGateError) as exc:
            print(f"ERROR: native L1 evidence binding gate -- {exc}", file=sys.stderr)
            return 3

        # The canonical assembler still owns all non-acquisition gates and
        # context construction. For this native L1 call only, remove its legacy
        # Deep Research stage after the native binding has been validated.
        legacy_l1_config = PRE_RESEARCH_MAP.pop("L1", None)
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = original(args)
        finally:
            if legacy_l1_config is not None:
                PRE_RESEARCH_MAP["L1"] = legacy_l1_config

        original_stdout = stdout.getvalue()
        original_stderr = stderr.getvalue()
        if rc != 0:
            sys.stdout.write(original_stdout)
            sys.stderr.write(original_stderr)
            return rc

        prefix = "[audit] context manifest:"
        paths = [
            Path(line[len(prefix):].strip())
            for line in original_stderr.splitlines()
            if line.startswith(prefix)
        ]
        if len(paths) != 1:
            sys.stderr.write(original_stderr)
            print(
                "ERROR: native L1 evidence binding gate -- canonical context did not report exactly one manifest",
                file=sys.stderr,
            )
            return 3
        manifest_path = paths[0]
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if str(manifest.get("delta_schema_version") or "") != "2.1":
                raise NativeL1EvidenceGateError(
                    "native L1 context manifest is not schema 2.1"
                )
            manifest["pre_research"] = {
                "type": "curie_frozen_evidence",
                "present": True,
                "evidence_run_id": run_id,
                "native_evidence_binding": binding_entry,
                "evidence_pack": binding["evidence_pack"],
                "legacy_summary_injected": False,
            }
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except (
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            NativeL1EvidenceGateError,
        ) as exc:
            print(f"ERROR: native L1 evidence binding gate -- {exc}", file=sys.stderr)
            return 3

        sys.stdout.write(original_stdout)
        sys.stderr.write(original_stderr)
        return 0

    context_module.cmd_assemble_context = cmd_assemble_context
    context_module._l05_native_context_gate_installed = True
