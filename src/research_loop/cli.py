"""Command-line parser and dispatch for Research Loop."""

import argparse
import os
import sys

import pitfall_ledger as pl

from research_loop.context import cmd_assemble_context
from research_loop.errors import RLRError
from research_loop.hypothesis_ledger import LedgerError
from research_loop.topology import AGENTS, NODE_MAP
from research_loop.commands.lifecycle import (
    VALID_STATUSES, cmd_check_deps, cmd_decision, cmd_demo, cmd_new_candidate,
    cmd_new_project, cmd_next_step, cmd_normalize_l0_input, cmd_note,
    cmd_preflight, cmd_route, cmd_triage_idea, cmd_triage_method,
)
from research_loop.commands.research import (
    cmd_audit_literature_evidence, cmd_audit_pre_research,
    cmd_deep_research_collect, cmd_deep_research_run, cmd_deep_research_start,
    cmd_deep_research_status, cmd_deep_research_worker, cmd_literature_report,
    cmd_pre_research,
)
from research_loop.commands.execution import cmd_execution_gate, cmd_prepare_turing_workspace
from research_loop.commands.reporting import cmd_aggregate_report, cmd_list, cmd_obsidian_sync, cmd_show
from research_loop.commands.continuation import (
    _write_exec_manifest, cmd_branch_status, cmd_emit_loop_memory, cmd_modality_scan,
)
from research_loop.commands import ledger as _ledger_commands
from research_loop.commands.ledger import (
    _ledger_for, cmd_emit_delta, cmd_finalize_candidate,
    cmd_hypothesis_authorize_context, cmd_hypothesis_history,
    cmd_hypothesis_migrate, cmd_hypothesis_search, cmd_hypothesis_show,
    cmd_hypothesis_verify,
)
from research_loop.commands.pitfall import (
    cmd_list_pitfalls, cmd_pitfall_scan, cmd_pitfall_status,
    cmd_promote_pitfall, cmd_record_pitfall,
)
from research_loop.commands.ranking import cmd_ranking_benchmark, cmd_ranking_report, cmd_ranking_shadow
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE, PROFILES
from research_loop.deep_research import SUPPORTED_BACKENDS
from research_loop.version import VERSION

__version__ = VERSION

_ledger_commands._write_exec_manifest = _write_exec_manifest


def _add_deep_research_run_arguments(parser):
    parser.add_argument("project_dir")
    parser.add_argument("cand_id")
    parser.add_argument("--node", required=True, choices=["L1", "L4", "L8.5"])
    parser.add_argument("--backend", choices=list(SUPPORTED_BACKENDS),
                        help=("override configured backend; also declares the agent host "
                              "when it cannot be detected (or set RLR_HOST_BACKEND)"))
    parser.add_argument("--allow-host-mismatch", action="store_true",
                        help=("run a backend that differs from the detected agent host "
                              "(spends that provider's quota on purpose)"))
    parser.add_argument("--executable", help="override configured CLI executable")
    parser.add_argument("--plugin-dir",
                        help="required Academic Research Skills plugin path for Claude")
    parser.add_argument("--skill-path",
                        help="Codex academic-research-suite installation path")
    parser.add_argument("--skill-version",
                        help="override configured ARS package version")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=int)
    parser.add_argument(
        "--l4a-manifest",
        help="resume native L4B from an existing project-relative L4A manifest",
    )

def build_parser():
    p = argparse.ArgumentParser(
        prog="research_loop_v04.py",
        description="Research Loop v0.9.1 - canonical gated runtime engine "
                    "(DAG-driven subagent architecture; assemble-context "
                    "enforces the v0.9.1 deep-research and provenance gates).")
    p.add_argument("--version", action="version", version=f"v{__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    # demo
    sp = sub.add_parser("demo", help="generate a demo project with DAG structure")
    sp.set_defaults(func=cmd_demo)

    # new-project
    sp = sub.add_parser("new-project", help="create a new native v0.9.1 project folder")
    sp.add_argument("name")
    sp.add_argument("topic", nargs="?", default="")
    sp.add_argument("--knowledge-store", dest="knowledge_store",
                    help="shared HypothesisLedger SQLite store; binds this project")
    sp.add_argument("--profile", choices=tuple(PROFILES),
                    default=DEFAULT_NATIVE_PROFILE,
                    help=("explicit compatibility profile; new projects default to "
                          f"{DEFAULT_NATIVE_PROFILE}"))
    sp.set_defaults(func=cmd_new_project)

    # preflight
    sp = sub.add_parser("preflight", help="L0 Linnaeus boot gate (00_Preflight/)")
    sp.add_argument("project_dir")
    sp.add_argument("--force", action="store_true", help="overwrite existing files")
    sp.add_argument("--backend", choices=list(SUPPORTED_BACKENDS),
                    help=("Deep Research backend for this project; defaults to the "
                          "detected agent host and fails loud when it is unknown"))
    sp.set_defaults(func=cmd_preflight)

    # check-deps (L0 dependency gate, standalone)
    sp = sub.add_parser("check-deps",
                        help="L0 dependency gate: verify required deps; STOP (non-zero) if missing")
    sp.add_argument("project_dir", nargs="?", default=None,
                    help="project dir (to also check 00_Preflight/dependencies.md)")
    sp.set_defaults(func=cmd_check_deps)

    # new-candidate
    sp = sub.add_parser("new-candidate", help="create a candidate with split frontmatter")
    sp.add_argument("project_dir")
    sp.add_argument("--title", required=True)
    sp.add_argument("--question", required=True, help="scientific question")
    sp.add_argument("--claim", required=True, help="testable claim/hypothesis")
    sp.add_argument("--input", required=True, help="source data description")
    sp.add_argument("--input-alias", dest="input_alias",
                    help="path-free input label for cognitive nodes "
                         "(default: derived from --input)")
    sp.add_argument("--from-memory", dest="from_memory", default=None,
                    help="path to a next_loop_memory.json seed (divergence loop)")
    sp.add_argument("--knowledge-store", dest="knowledge_store",
                    help="shared HypothesisLedger SQLite store (or RLR_HYPOTHESIS_STORE)")
    sp.add_argument("--loop-type", dest="loop_type", default=None,
                    choices=["divergent", "correction", "data-acquisition"],
                    help="required with --from-memory")
    sp.add_argument("--round-type", dest="round_type", default=None,
                    choices=["initial", "continuation"],
                    help="explicit round type (default: continuation if "
                         "--from-memory else initial)")
    sp.add_argument("--source-input-file", dest="source_input_file", default=None,
                    help="path to a json/yaml file carrying the source_input "
                         "struct {input_type,files,location,description,format}")
    sp.add_argument("--input-type", dest="input_type", default=None,
                    choices=["files", "directory", "dataset", "inline", "other"],
                    help="source_input.input_type")
    sp.add_argument("--input-files", dest="input_files", action="append",
                    default=None, help="source_input file (repeatable)")
    sp.add_argument("--input-location", dest="input_location", default=None,
                    help="source_input.location (path or dataset id)")
    sp.add_argument("--input-format", dest="input_format", default=None,
                    help="source_input.format (e.g. csv, fastq)")
    sp.set_defaults(func=cmd_new_candidate)

    sp = sub.add_parser("normalize-l0-input",
                        help="normalize a labelled request into a strict L0 contract")
    sp.add_argument("--project", required=True, help="existing RLR project directory")
    sp.add_argument("--input", required=True, help="UTF-8 natural-language request file")
    source = sp.add_mutually_exclusive_group(required=True)
    source.add_argument("--data", help="local data file or directory")
    source.add_argument("--dataset", help="stable remote dataset locator")
    sp.add_argument("--from-memory", help="verified next_loop_memory.json for continuation")
    sp.add_argument("--loop-type", choices=["divergent", "correction", "data-acquisition"],
                    help="required with --from-memory")
    sp.add_argument("--dry-run", action="store_true", help="validate and print without writing")
    sp.add_argument("--run-l0", action="store_true", help="start the canonical runner through L0 only")
    sp.set_defaults(func=cmd_normalize_l0_input)

    sp = sub.add_parser("ranking-shadow",
                        help="run an advisory, isolated shadow hypothesis ranking")
    sp.add_argument("project_dir")
    sp.add_argument("--stage", required=True, choices=["L3", "L10b"])
    sp.add_argument("--candidate", dest="candidates", action="append", required=True,
                    help="candidate ID with an owned L1 Einstein delta (repeatable)")
    sp.add_argument("--seed", type=int, required=True)
    sp.add_argument("--match-budget", type=int, required=True)
    sp.add_argument("--token-budget", type=int,
                    help="declared token-budget metadata only; not enforced (fake judge defaults to 0)")
    sp.add_argument("--cost-budget", type=float,
                    help="declared cost-budget metadata only; not enforced (fake judge defaults to 0)")
    sp.add_argument("--resume", help="isolated ranking checkpoint to resume")
    sp.add_argument("--judge", choices=["fake", "provider"], default="fake")
    sp.add_argument("--config", help="runner provider configuration for --judge provider")
    sp.add_argument("--evidence", action="append", default=[],
                    help="JSON evidence event or evidence_events file (repeatable)")
    sp.add_argument("--run-id", help="safe unique artifact name (default: timestamp)")
    sp.add_argument("--knowledge-store", dest="knowledge_store")
    sp.set_defaults(func=cmd_ranking_shadow)

    sp = sub.add_parser("ranking-benchmark",
                        help="run the free synthetic fair-vs-naive ranking benchmark")
    sp.add_argument("--gold", required=True, help="versioned synthetic gold-set JSON")
    sp.add_argument("--seeds", required=True, help="comma-separated deterministic seeds")
    sp.add_argument("--match-budget", type=int, required=True)
    sp.add_argument("--output", help="new JSON benchmark report path")
    sp.set_defaults(func=cmd_ranking_benchmark)

    sp = sub.add_parser("ranking-report", help="render an isolated shadow ranking artifact")
    sp.add_argument("project_dir")
    sp.add_argument("--run", dest="run_id", required=True)
    sp.add_argument("--format", choices=["json", "markdown"], default="json")
    sp.set_defaults(func=cmd_ranking_report)

    # next-step
    sp = sub.add_parser("next-step", help="get next DAG node for a candidate")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.set_defaults(func=cmd_next_step)

    # assemble-context
    sp = sub.add_parser("assemble-context", help="assemble context text for a DAG node")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--node", required=True, help="DAG node (e.g. L1)")
    sp.add_argument("--template-mode", choices=["contract", "refs", "full"],
                    default="contract",
                    help="contract: compact (default, ~200 tokens); refs: path+hash only; full: entire templates (debug only)")
    sp.add_argument("--pre-research-mode", choices=["digest", "excerpt", "full", "none"],
                    default="digest",
                    help="digest: Runtime digest section only (default); excerpt: truncated; full: entire file; none: manifest only")
    sp.add_argument("--pre-research-token-budget", type=int, default=None,
                    help="max tokens for pre-research injection (default: node-specific, e.g. L1=800)")
    sp.add_argument("--context-token-budget", type=int, default=8000,
                    help="max estimated tokens for assembled context (default: 8000; 0 disables)")
    sp.add_argument("--authorization-id",
                    help="fixed hypothesis context authorization to inject")
    sp.add_argument("--evidence-run-id",
                    help="exact pre-research evidence run to bind into ContextManifest/v2")
    sp.add_argument("--knowledge-store", dest="knowledge_store")
    sp.set_defaults(func=cmd_assemble_context)

    # emit-delta
    sp = sub.add_parser("emit-delta", help="validate and save a delta JSON")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--node", required=True)
    sp.add_argument("--persona", required=True)
    sp.add_argument("--file", required=True, help="delta JSON file to import")
    sp.add_argument("--context-manifest", help="ContextManifest/v2 from assemble-context")
    sp.add_argument("--provider-receipt", help="RunReceipt/v1 proving the provider used that context")
    sp.add_argument("--receipt", help="deprecated alias for --context-manifest")
    sp.add_argument("--knowledge-store", dest="knowledge_store",
                    help="shared HypothesisLedger SQLite store (or RLR_HYPOTHESIS_STORE)")
    sp.set_defaults(func=cmd_emit_delta)

    # route
    sp = sub.add_parser("route", help="hand a candidate to a persona")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--to", required=True, choices=AGENTS)
    sp.add_argument("--reason", required=True)
    sp.add_argument("--action")
    sp.add_argument("--input-files", dest="input_files")
    sp.add_argument("--constraints")
    sp.add_argument("--expected")
    sp.add_argument("--stop")
    sp.set_defaults(func=cmd_route)

    # note
    sp = sub.add_parser("note", help="append a persona note")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--agent", required=True, choices=AGENTS)
    sp.add_argument("--text")
    sp.add_argument("--file", help="read note body from a file")
    sp.set_defaults(func=cmd_note)

    # triage-idea
    sp = sub.add_parser("triage-idea",
                        help="L3 Oppenheimer: IDEA_PROPOSED -> SELECTED/REJECTED")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--decision", choices=["select", "reject"],
                    help="legacy-only; v2 derives this from its committed L3 delta")
    sp.add_argument("--reason", help="legacy-only; v2 derives this from its committed L3 delta")
    sp.set_defaults(func=cmd_triage_idea)

    # triage-method
    sp = sub.add_parser("triage-method",
                        help="L6 Oppenheimer: METHOD_PROPOSED -> APPROVED/REJECTED")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--decision", choices=["approve", "reject"],
                    help="legacy-only; v2 derives this from its committed L6 delta")
    sp.add_argument("--reason", help="legacy-only; v2 derives this from its committed L6 delta")
    sp.set_defaults(func=cmd_triage_method)

    sp = sub.add_parser("finalize-candidate",
                        help="derive the L10b candidate decision from a committed v2 delta")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--knowledge-store", dest="knowledge_store",
                    help="shared HypothesisLedger SQLite store (or RLR_HYPOTHESIS_STORE)")
    sp.set_defaults(func=cmd_finalize_candidate)

    sp = sub.add_parser("hypothesis-show", help="show a hypothesis graph DTO")
    sp.add_argument("project_dir")
    sp.add_argument("hypothesis_id")
    sp.add_argument("--as-of", dest="as_of", type=int)
    sp.add_argument("--knowledge-store", dest="knowledge_store")
    sp.set_defaults(func=cmd_hypothesis_show)

    sp = sub.add_parser("hypothesis-history", help="show append-only hypothesis events")
    sp.add_argument("project_dir")
    sp.add_argument("hypothesis_id")
    sp.add_argument("--after", type=int, default=0)
    sp.add_argument("--limit", type=int, default=100)
    sp.add_argument("--knowledge-store", dest="knowledge_store")
    sp.set_defaults(func=cmd_hypothesis_history)

    sp = sub.add_parser("hypothesis-lineage", help="show hypothesis lineage graph DTO")
    sp.add_argument("project_dir")
    sp.add_argument("hypothesis_id")
    sp.add_argument("--as-of", dest="as_of", type=int)
    sp.add_argument("--knowledge-store", dest="knowledge_store")
    sp.set_defaults(func=cmd_hypothesis_show)

    sp = sub.add_parser("hypothesis-search", help="search hypotheses by normalized statement")
    sp.add_argument("project_dir")
    sp.add_argument("--text", required=True)
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--knowledge-store", dest="knowledge_store")
    sp.set_defaults(func=cmd_hypothesis_search)

    sp = sub.add_parser("hypothesis-verify", help="verify ledger projections and emissions")
    sp.add_argument("project_dir")
    sp.add_argument("--knowledge-store", dest="knowledge_store")
    sp.add_argument("--rebuild", action="store_true",
                    help="transactionally replay and compare mutable projections")
    sp.set_defaults(func=cmd_hypothesis_verify)

    sp = sub.add_parser(
        "hypothesis-migrate",
        help="dry-run or atomically commit a legacy project migration",
    )
    sp.add_argument("project_dir")
    sp.add_argument("--knowledge-store", dest="knowledge_store", required=True)
    mode = sp.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--resolution")
    sp.add_argument("--resolved-by")
    sp.add_argument(
        "--target-profile",
        choices=("v2.1",),
        help="explicitly upgrade an activated v2.0 project to the selected profile",
    )
    sp.set_defaults(func=cmd_hypothesis_migrate)

    sp = sub.add_parser("hypothesis-authorize-context",
                        help="create fixed-cursor DAG-scoped context authorizations")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--node", action="append", required=True, choices=NODE_MAP)
    sp.add_argument("--round-id", required=True)
    sp.add_argument("--as-of", type=int)
    sp.add_argument("--knowledge-store", dest="knowledge_store")
    sp.set_defaults(func=cmd_hypothesis_authorize_context)

    # execution-gate
    sp = sub.add_parser("execution-gate",
                        help="reject Execution unless preflight + approved plan exist")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.set_defaults(func=cmd_execution_gate)

    # prepare-turing-workspace
    sp = sub.add_parser("prepare-turing-workspace",
                        help="Path A: build isolated execution workspace for Turing (L7)")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--file", action="append",
                    help="allowlisted input data file to copy into the workspace (repeatable)")
    sp.add_argument("--clean", action="store_true",
                    help="remove existing _turing_workspace_* dirs first")
    sp.set_defaults(func=cmd_prepare_turing_workspace)

    # decision
    sp = sub.add_parser("decision", help="Oppenheimer status change")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--status", required=True, choices=VALID_STATUSES)
    sp.add_argument("--reason", required=True)
    sp.add_argument("--route", help="next owner persona")
    sp.add_argument("--force", action="store_true",
                    help="override the legal-transition guard (manual recovery)")
    sp.set_defaults(func=cmd_decision)

    # emit-loop-memory
    sp = sub.add_parser("emit-loop-memory",
                        help="L10c: emit next_loop_memory seed (JSON+MD) for a candidate")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--knowledge-store", dest="knowledge_store",
                    help="shared HypothesisLedger SQLite store (or RLR_HYPOTHESIS_STORE)")
    sp.set_defaults(func=cmd_emit_loop_memory)

    # branch-status
    sp = sub.add_parser("branch-status",
                        help="set a branch's exploration status in the ledger")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--branch", required=True)
    sp.add_argument("--description", default="")
    sp.add_argument("--status", required=True, choices=["explored", "partial", "ignored"])
    sp.add_argument("--data-path", dest="data_path", default="")
    sp.add_argument("--why", default="")
    sp.set_defaults(func=cmd_branch_status)

    # modality-scan
    sp = sub.add_parser("modality-scan",
                        help="record used/available data modalities for a candidate")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--used", action="append", default=[])
    sp.add_argument("--available", action="append", default=[])
    sp.set_defaults(func=cmd_modality_scan)

    # aggregate-report
    sp = sub.add_parser("aggregate-report", help="L10c Linnaeus: generate FINAL_REPORT")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--force", action="store_true",
                    help="silence the repoint NOTE when the shared FINAL_REPORT changes owner")
    sp.set_defaults(func=cmd_aggregate_report)

    pr = sub.add_parser("pre-research",
                        help="prepare deep research / literature review / code search context for a node")
    pr.add_argument("project_dir")
    pr.add_argument("cand_id")
    pr.add_argument("--node", required=True,
                    help="which node to prepare research for (L1, L4, L7)")
    pr.add_argument("--output-dir",
                    help="override save dir (default: 02_Agent_Notes/_pre_research/, "
                         "which is where assemble-context reads it from)")
    pr.add_argument("--write-placeholder", action="store_true",
                    help="write initial placeholder template to output file")
    pr.add_argument("--write-synthetic", action="store_true",
                    help="[TEST-ONLY] write completed/synthetic valid pre-research artifact to output file")
    pr.set_defaults(func=cmd_pre_research)

    sp = sub.add_parser("deep-research-run",
                        help="invoke Academic Research Skills and persist verified paper evidence")
    _add_deep_research_run_arguments(sp)
    sp.set_defaults(func=cmd_deep_research_run)

    sp = sub.add_parser(
        "deep-research-start",
        help="start the existing Deep Research command in a detached worker",
    )
    _add_deep_research_run_arguments(sp)
    sp.set_defaults(func=cmd_deep_research_start)

    sp = sub.add_parser("deep-research-status",
                        help="read a detached Deep Research task status")
    sp.add_argument("project_dir")
    sp.add_argument("task_id")
    sp.set_defaults(func=cmd_deep_research_status)

    sp = sub.add_parser("deep-research-collect",
                        help="collect a completed detached Deep Research result")
    sp.add_argument("project_dir")
    sp.add_argument("task_id")
    sp.set_defaults(func=cmd_deep_research_collect)

    sp = sub.add_parser("_deep-research-worker", help=argparse.SUPPRESS)
    sp.add_argument("project_dir")
    sp.add_argument("task_id")
    sp.set_defaults(func=cmd_deep_research_worker)

    sp = sub.add_parser("audit-literature-evidence",
                        help="fail closed unless a node has a valid Academic Research evidence pack")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--node", required=True, choices=["L1", "L4", "L8.5"])
    sp.set_defaults(func=cmd_audit_literature_evidence)

    sp = sub.add_parser("literature-report", help="render source-located evidence for a candidate")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--node", action="append", choices=["L1", "L4", "L8.5"])
    sp.add_argument("--format", choices=["markdown", "json"], default="markdown")
    sp.set_defaults(func=cmd_literature_report)

    # audit-pre-research
    sp = sub.add_parser("audit-pre-research",
                        help="Audit pre-research artifacts in a project directory")
    sp.add_argument("project_dir")
    sp.set_defaults(func=cmd_audit_pre_research)

    sp = sub.add_parser("obsidian-sync", help="sync deltas + report to Obsidian vault")
    sp.add_argument("project_dir")
    sp.add_argument("--vault", help="Obsidian vault root (default: OBSIDIAN_VAULT env var)")
    sp.set_defaults(func=cmd_obsidian_sync)

    # list
    sp = sub.add_parser("list", help="list candidates")
    sp.add_argument("project_dir")
    sp.set_defaults(func=cmd_list)

    # show
    sp = sub.add_parser("show", help="show a candidate file")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.set_defaults(func=cmd_show)

    # --- pitfall ledger ---
    sp = sub.add_parser("record-pitfall",
                        help="record (or dedup-merge) a runtime pitfall")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--node", required=True, help="DAG node (e.g. L7) or '*' for global")
    sp.add_argument("--category", required=True,
                    help="e.g. provider_failure | emit_delta_failure | execution_failure | method_flaw")
    sp.add_argument("--symptom", required=True)
    sp.add_argument("--root-cause", dest="root_cause", default="")
    sp.add_argument("--prevention-rule", dest="prevention_rule", default="")
    sp.add_argument("--severity", default="warn",
                    choices=pl.VALID_SEVERITIES)
    sp.add_argument("--evidence", default="", help="path to log/trace/file")
    sp.add_argument("--provider", default="unknown")
    sp.add_argument("--status", default="draft", choices=pl.VALID_STATUSES,
                    help="default draft; only the profile-bound L8 auditor confirms")
    sp.add_argument("--scope", default="project", choices=["project", "global"],
                    help="project ledger (default) or the shared global ledger")
    sp.add_argument("--error-class", dest="error_class", default="agent",
                    choices=pl.VALID_ERROR_CLASSES,
                    help="agent (model/LLM issue) or system (platform/toolchain)")
    sp.set_defaults(func=cmd_record_pitfall)

    sp = sub.add_parser("list-pitfalls", help="list pitfalls (optionally filtered)")
    sp.add_argument("project_dir")
    sp.add_argument("--status", choices=pl.VALID_STATUSES)
    sp.add_argument("--node")
    sp.add_argument("--category")
    sp.add_argument("--severity", choices=pl.VALID_SEVERITIES)
    sp.add_argument("--global", dest="global_", action="store_true",
                    help="list the shared global ledger instead of this project's")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list_pitfalls)

    sp = sub.add_parser("pitfall-scan",
                        help="scan confirmed/promoted pitfalls relevant to a node")
    sp.add_argument("project_dir")
    sp.add_argument("--node")
    sp.add_argument("--category")
    sp.add_argument("--provider")
    sp.add_argument("--gate", action="store_true",
                    help="hard_stop gate: non-zero exit if a hard_stop applies")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_pitfall_scan)

    sp = sub.add_parser("pitfall-status",
                        help="L8 auditor: confirm / false_positive / obsolete a pitfall")
    sp.add_argument("project_dir")
    sp.add_argument("id")
    sp.add_argument("--status", required=True,
                    choices=["confirmed", "false_positive", "obsolete"])
    sp.add_argument("--by", default="Curie")
    sp.set_defaults(func=cmd_pitfall_status)

    sp = sub.add_parser("promote-pitfall",
                        help="promote a confirmed pitfall to a durable rule")
    sp.add_argument("project_dir")
    sp.add_argument("id")
    sp.add_argument("--to", required=True, choices=pl.VALID_PROMOTIONS)
    sp.add_argument("--scope", default="project", choices=["project", "global"],
                    help="project ledger (default) or global (protects all projects)")
    sp.set_defaults(func=cmd_promote_pitfall)

    return p

def main(argv=None):
    # Force UTF-8 stdout/stderr so context/report printing never crashes on a
    # non-default-codepage char (Windows console is often GBK/cp936). Deltas and
    # pre-research routinely contain arrows, em-dashes, Greek, <=, etc.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        if getattr(args, "knowledge_store", None):
            os.environ["RLR_HYPOTHESIS_STORE"] = str(args.knowledge_store)
        activated_commands = {
            "preflight", "new-candidate", "normalize-l0-input", "next-step",
            "assemble-context", "emit-delta", "triage-idea", "triage-method",
            "execution-gate", "prepare-turing-workspace", "finalize-candidate",
            "aggregate-report", "ranking-shadow", "emit-loop-memory",
        }
        if args.cmd in activated_commands:
            project = getattr(args, "project_dir", None) or getattr(args, "project", None)
            _ledger_for(project, getattr(args, "knowledge_store", None))
        return args.func(args)
    except (RLRError, LedgerError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())






__all__ = ["build_parser", "main"]
