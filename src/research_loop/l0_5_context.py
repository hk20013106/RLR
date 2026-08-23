"""Inject the exact frozen L0.5 EvidencePack into native L1 context."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from research_loop import deep_research, research_evidence_binding, research_seed
from research_loop.compatibility import get_profile


_SECTION = "=== L0.5 FROZEN RESEARCH EVIDENCE ==="


def _manifest_path(stderr_text: str) -> Path:
    prefix = "[audit] context manifest:"
    matches = [
        line[len(prefix):].strip()
        for line in stderr_text.splitlines()
        if line.startswith(prefix)
    ]
    if len(matches) != 1:
        raise ValueError("assembled context did not report exactly one manifest")
    return Path(matches[0])


def _remove_generated(manifest_path: Path | None) -> None:
    if manifest_path is None:
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rendered = Path(str(manifest.get("rendered_context_path") or ""))
        if rendered.is_file():
            rendered.unlink()
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    manifest_path.unlink(missing_ok=True)


def install(context_module) -> None:
    if getattr(context_module, "_L0_5_CONTEXT_INSTALLED", False):
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

        manifest_path = None
        try:
            manifest_path = _manifest_path(original_stderr)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            profile = get_profile(str(manifest.get("profile_id") or ""))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _remove_generated(manifest_path)
            print(f"ERROR: L0.5 context gate -- {exc}", file=sys.stderr)
            return 3
        if profile.delta_schema_version != "2.1":
            sys.stdout.write(original_stdout)
            sys.stderr.write(original_stderr)
            return 0

        try:
            seed = research_seed.load_l1_research_seed(
                args.project_dir, str(args.cand_id)
            )
            binding = research_evidence_binding.manifest_entry(
                args.project_dir, seed
            )
            run_id = str(binding["evidence_run_id"])

            ok, reason = context_module._audit_divergence(
                Path(args.project_dir), "L1", args.cand_id
            )
            if not ok:
                raise ValueError(reason)
            ok, reason = context_module._audit_branch_coverage(
                Path(args.project_dir), args.cand_id
            )
            if not ok:
                raise ValueError(reason)

            ok, reason = deep_research.audit_evidence_pack(
                args.project_dir, args.cand_id, "L0.5", run_id=run_id
            )
            if not ok:
                raise ValueError(f"L0.5 evidence gate failed: {reason}")
            artifacts = deep_research.evidence_artifact_manifest(
                args.project_dir, args.cand_id, "L0.5", run_id
            )
            expected = {
                "project_id": str(manifest["project_id"]),
                "candidate_id": str(args.cand_id),
                "round_id": str(seed["round_id"]),
                "profile_id": profile.profile_id,
                "target_node": "L0.5",
                "research_phase": "pre_research",
                "research_persona": "Curie",
                "receipt_schema": "EvidenceRunReceipt/v1.1",
            }
            for field, expected_value in expected.items():
                if str(artifacts.get(field) or "") != expected_value:
                    raise ValueError(
                        f"L0.5 evidence receipt {field} does not match bound run"
                    )

            digest = deep_research.render_evidence_digest(
                args.project_dir,
                args.cand_id,
                ["L0.5"],
                run_ids={"L0.5": run_id},
            ).strip()
            if digest == "=== DEEP RESEARCH EVIDENCE ===":
                raise ValueError("L0.5 bound evidence digest is empty")

            rendered = Path(str(manifest["rendered_context_path"]))
            context_text = rendered.read_text(encoding="utf-8").rstrip()
            context_text += f"\n\n{_SECTION}\n{digest}\n"
            budget = int(getattr(args, "context_token_budget", 8000) or 0)
            estimated = context_module._estimate_tokens(context_text)
            if budget and estimated > budget:
                raise ValueError(
                    f"context token budget exceeded after L0.5 evidence (~{estimated} > {budget})"
                )
            rendered.write_text(context_text, encoding="utf-8")
            manifest["rendered_context_sha256"] = context_module._sha256(rendered)
            manifest["pre_research"] = {
                "type": "deep_research",
                "present": True,
                "research_node": "L0.5",
                "evidence_run_id": run_id,
                "evidence_artifacts": artifacts,
            }
            manifest["deep_research_evidence"] = {
                "nodes": ["L0.5"],
                "evidence_ids": deep_research.evidence_ids(
                    args.project_dir,
                    args.cand_id,
                    ["L0.5"],
                    run_ids={"L0.5": run_id},
                ),
            }
            manifest["l0_5_evidence_binding"] = binding
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
            research_evidence_binding.ResearchEvidenceBindingError,
            deep_research.DeepResearchError,
        ) as exc:
            _remove_generated(manifest_path)
            print(f"ERROR: L0.5 context gate -- {exc}", file=sys.stderr)
            return 3

        print(context_text)
        sys.stderr.write(original_stderr)
        return 0

    context_module.cmd_assemble_context = cmd_assemble_context
    context_module._L0_5_CONTEXT_INSTALLED = True
