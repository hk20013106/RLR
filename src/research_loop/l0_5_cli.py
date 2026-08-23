"""CLI compatibility for the explicit L0.5 research stage."""
from __future__ import annotations


def install(cli_module) -> None:
    if getattr(cli_module, "_L0_5_CLI_INSTALLED", False):
        return

    def _add_deep_research_run_arguments(parser):
        parser.add_argument("project_dir")
        parser.add_argument("cand_id")
        parser.add_argument(
            "--node",
            required=True,
            choices=["L0.5", "L1", "L4", "L8.5"],
            help=(
                "L0.5 is the canonical native discovery stage; L1 remains "
                "accepted only for historical compatibility"
            ),
        )
        parser.add_argument(
            "--backend",
            choices=list(cli_module.SUPPORTED_BACKENDS),
            help=(
                "override configured backend; also declares the agent host "
                "when it cannot be detected (or set RLR_HOST_BACKEND)"
            ),
        )
        parser.add_argument(
            "--allow-host-mismatch",
            action="store_true",
            help=(
                "run a backend that differs from the detected agent host "
                "(spends that provider's quota on purpose)"
            ),
        )
        parser.add_argument("--executable", help="override configured CLI executable")
        parser.add_argument(
            "--plugin-dir",
            help="required Academic Research Skills plugin path for Claude",
        )
        parser.add_argument(
            "--skill-path",
            help="Codex academic-research-suite installation path",
        )
        parser.add_argument("--skill-version", help="override configured ARS package version")
        parser.add_argument("--model")
        parser.add_argument("--timeout", type=int)
        parser.add_argument(
            "--l4a-manifest",
            help="resume native L4B from an existing project-relative L4A manifest",
        )

    cli_module._add_deep_research_run_arguments = _add_deep_research_run_arguments
    cli_module._L0_5_CLI_INSTALLED = True
