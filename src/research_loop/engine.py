#!/usr/bin/env python3
"""Research Loop v0.9.2 — canonical gated runtime engine.

This is the v0.9.2 runtime. The filename `research_loop_v04.py` is retained only
for import/CLI stability (run_loop.py and the main-agent protocol import it);
it is not a legacy engine. As of v0.9.2, `assemble-context` enforces the
Deep Research gate (`_audit_pre_research`) on L1, L4, and L8.5: it fails closed
(rc=3) unless a successful Academic Research Skills receipt and source-located
evidence pack are persisted. A handwritten prose digest or an environment
variable attestation is not proof of retrieval.

Each persona is an independent subagent with physical context isolation via DAG
topology. Cognitive agents receive context as embedded text (Path B); Turing
executes in a controlled workspace (Path A). Each agent outputs a structured
delta JSON; the candidate file stays read-only. L10c Linnaeus aggregates all
deltas into FINAL_REPORT.

Usage:
    python research_loop_v04.py --help
    python research_loop_v04.py demo
    python research_loop_v04.py new-project NAME [TOPIC]
    python research_loop_v04.py new-candidate PROJECT_DIR --title T --question Q --claim C --input I
    python research_loop_v04.py preflight PROJECT_DIR
    python research_loop_v04.py next-step PROJECT_DIR CAND_ID
    python research_loop_v04.py assemble-context PROJECT_DIR CAND_ID --node NODE
    python research_loop_v04.py emit-delta PROJECT_DIR CAND_ID --node NODE --persona P --file F
    python research_loop_v04.py decision PROJECT_DIR CAND_ID --status S --reason R [--route P]
    python research_loop_v04.py route PROJECT_DIR CAND_ID --to PERSONA --reason R
    python research_loop_v04.py triage-idea PROJECT_DIR CAND_ID --decision select|reject --reason R
    python research_loop_v04.py triage-method PROJECT_DIR CAND_ID --decision approve|reject --reason R
    python research_loop_v04.py execution-gate PROJECT_DIR CAND_ID
    python research_loop_v04.py prepare-turing-workspace PROJECT_DIR CAND_ID [--file F ...] [--clean]
    python research_loop_v04.py aggregate-report PROJECT_DIR CAND_ID
    python research_loop_v04.py obsidian-sync PROJECT_DIR [--vault PATH]
    python research_loop_v04.py list PROJECT_DIR
    python research_loop_v04.py show PROJECT_DIR CAND_ID
"""

import argparse
import os
import datetime as _dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pitfall_ledger as pl  # additive: pitfall ledger (no DAG/schema coupling)

from research_loop.version import VERSION

__version__ = VERSION


from research_loop.errors import RLRError  # inward shim (Phase 1a)
from research_loop import ranking
from research_loop.providers import ProviderConfig, ProviderError, make_provider

# --- personas ---------------------------------------------------------------

from research_loop.topology import (  # inward shim (Phase 1a)
    AGENTS, DECISION_TRANSITIONS, DAG_NODES, NODE_MAP,
    DAG_SEQUENCE, DELTA_DAG_ORDER,
)

from research_loop import common as _common
from research_loop.common import (  # inward shim (Phase 7a)
    PERSONA_TITLE, _now, _stamp, _input_alias, _everos_scopes_for,
    _port_open, _dep_present, _dep_fix_hint, _parse_declared_deps,
    _check_dependencies, _slug, _next_seq, _require_status, _set_status,
    _append_decision, _mkdirs, _fmt_list, _fmt_dict,
    _empty_value_for_schema, _sha256_file, _load_loop_memory,
    _render_extra_front,
)

from research_loop.commands.lifecycle import (  # inward shim (Phase 7d)
    VALID_STATUSES, KNOWLEDGE_BASE_ACCESS, FINAL_STATUSES, PREFLIGHT_FILES,
    REQUIRED_DEPENDENCIES, _pitfall_warnings_for_node, cmd_next_step,
    cmd_new_project, cmd_new_candidate, _print_intake_failure,
    cmd_normalize_l0_input, cmd_preflight, cmd_check_deps, cmd_note, cmd_demo,
    cmd_decision, cmd_route, cmd_triage_idea, cmd_triage_method,
)

# Legal status transitions for the generic `decision` command. triage-idea,
# triage-method and execution-gate use their own commands and are NOT gated by
# this table. A same-status decision (logging only) and a transition to
# ARCHIVED are always allowed; any other transition not listed here requires
# `decision --force` (so KEEP-from-NEW and similar jumps fail by default while
# manual recovery stays possible).

# --- DAG topology (15 nodes; profile selects native serial or legacy parallel L9)
# Each node: node_id, persona, status_before, status_after_optional,
#            context_inputs, is_parallel, is_execution, advance_command,
#            action_hint


from research_loop.preresearch import (  # inward shim (Phase 3a)
    LIT_RUNTIME_DIGEST_TOKEN_BUDGET, _LIT_PRE_RESEARCH_TYPES, _DOI_PMID_URL_RE, _runtime_digest_budget_error, _extract_section, _estimate_tokens,
)


# Map: node_id -> node dict
from research_loop.preresearch import PRE_RESEARCH_MAP  # inward shim (Phase 2b-1)


# Per-node access to the external KNOWLEDGE BASE (09_Literature_Database/).
# Declared explicitly (not derivable -- it is a policy choice):
#   - read-write: the literature SEARCHERS (they find + add papers).
#   - read:       L0 (catalogs/declares the KB) + the review/decision/report nodes
#                 (L9/L10) that CONSULT accumulated literature to falsify/interpret/
#                 value/decide/report. They cite existing entries; they do NOT add.
#   - none:       everyone else -- they get literature only via embedded deltas
#                 (pre-research summaries + the L8.5 papers), never direct DB access.

# Attach the declared info-flow policy to each node (surfaced by next-step and
# the assemble-context manifest; ENFORCEMENT is the orchestrator's job, not the
# script's). Derived where possible so they cannot drift from the DAG:
#   - tools_policy: only the execution node (Turing/L7) gets filesystem access,
#     and only inside its workspace ("workspace-fs"); every cognitive node is
#     "no-fs" (its entire input is the embedded context text).
#   - everos_read_scopes: mirror the node's context_inputs so EverOS routing can
#     never grant a node a memory channel the delta DAG doesn't already grant.
#     "<id>" is substituted with the project id when a manifest is built.
#   - knowledge_base: per the explicit KNOWLEDGE_BASE_ACCESS policy above.
for _n in DAG_NODES:
    _n.setdefault("tools_policy",
                  "workspace-fs" if _n.get("is_execution") else "no-fs")
    _n.setdefault("knowledge_base",
                  KNOWLEDGE_BASE_ACCESS.get(_n["node"], "none"))
    if "everos_read_scopes" not in _n:
        _scopes = ["global_methods", "projects/<id>/public"]
        for _inp in _n["context_inputs"]:
            if _inp == "candidate_frontmatter":
                continue
            if _inp == "ALL":
                _scopes.append("projects/<id>/node_outputs/*")
                continue
            _scopes.append(f"projects/<id>/node_outputs/{_inp}")
        if _n.get("is_execution"):
            _scopes.append(f"projects/<id>/execution/{_n['node']}")
        _n["everos_read_scopes"] = _scopes
del _n

# Profile-specific order is owned by topology_for_profile().

# Map: node_id -> layer template filename on disk. The files are named
# descriptively (e.g. L7_execution.md), not L7.md, so next-step must map the
# node id to the real filename or the orchestrator gets a dead path.
from research_loop.paths import (  # inward shim (Phase 1b)
    LAYER_TEMPLATE_FILE, PERSONA_TEMPLATE_FILE,
    _layer_template_path, _persona_template_path,
    _candidate_file, _sha256, _audit_dir, _pre_research_file,
)

# Map: persona -> persona template filename on disk (numbered 01..10 in AGENTS
# order, e.g. 02_Einstein.md). next-step must map to the real filename.





# --- delta schemas ----------------------------------------------------------
# Each persona outputs a structured delta JSON. Schemas are Python dicts
# checked by a simple validator (no external JSON Schema library).

from research_loop.delta import (  # inward shim (Phase 2a)
    DELTA_SCHEMAS, DELTA_PERSONA, _validate_delta,
    _delta_file, _candidate_delta_file,
    _delta_for_candidate, _delta_belongs_to_candidate, _v2_candidate_delta_file,
)
from research_loop.hypothesis_ledger import (
    DELTA_SCHEMA_VERSION, NODE_SCHEMAS, HypothesisLedger, LedgerError,
    canonical_json, binding_path,
)
from research_loop import hypothesis_migration

# Map: delta key -> persona name (for file path resolution)

# DAG order for reading deltas in aggregate-report



# --- L0 dependency gate -----------------------------------------------------
# Runtime dependencies the L0 preflight HARD-CHECKS. A missing REQUIRED
# dependency STOPS the loop (preflight exits non-zero) -- it must NEVER be
# skipped. Project-specific deps are declared in 00_Preflight/dependencies.md
# and are checked the same way. The constant itself is owned by
# research_loop.common and imported directly by templates/lifecycle -- engine
# only re-exports it (line 81) for the research_loop_v04 symbol contract.


from research_loop import templates as _templates
from research_loop.templates import (  # inward shim (Phase 7a)
    LAYERS, _knowledge_base_md, _dependencies_md, _candidate_template,
    _index_template, _handoff_template, _decision_log_template,
    _note_template, _preflight_template,
)
_templates.VALID_STATUSES = VALID_STATUSES
_templates.__version__ = __version__

# --- small helpers ----------------------------------------------------------

















# V0.7 deep-research gate ----------------------------------------------------
# The mandatory gate covers L1 (deep research), L4 (method literature), and
# L8.5 (post-result literature verification). L7 code search remains separate.




from research_loop.preresearch import (  # inward shim (Phase 3b)
    _validate_pre_research_content, _parse_section_bullets, _parse_pre_research_provenance, _QF_STOP, _query_family_key, _load_query_family_cache, _merge_query_family_cache,
)


from research_loop.gates import (  # inward shim (Phase 3b)
    _audit_pre_research, _audit_branch_coverage, DIVERGENCE_MIN_NEW_QUERY_FAMILIES, _audit_divergence, _audit_l10_traceability, _audit_l10_evidence, _l6_script_branches, _audit_l7_manifest, _critique_ref_valid, _audit_l6_traceability, _audit_l4_methods, _audit_l0_memory, _audit_l0_contract,
)
from research_loop import l0_contract
from research_loop import l0_intake
from research_loop import deep_research


# V0.6 pre-research provenance ------------------------------------------------
# Structured evidence-of-search the artifact MUST carry so a deep-research run is
# reviewable: which queries were issued, which tools ran, and how many sources
# were found. PR1 only PARSES + PERSISTS these (into the context manifest); the
# gate that ENFORCES them lands in PR2 -- this function does not judge.






from research_loop.yamlio import (  # inward shim (Phase 3a)
    _yaml_value, _load_yaml_front, _replace_field,
)



from research_loop.context import (  # inward shim (Phase 2b-2)
    strip_candidate_to_frontmatter, _condense_delta, _generate_contract, cmd_assemble_context, _caveman_required_literals, _caveman_lite, _inject_pre_research,
)

# --- templates --------------------------------------------------------------
# --- Phase 1 commands: next-step, assemble-context, emit-delta --------------



from research_loop.commands.research import (  # inward shim (Phase 7d)
    cmd_pre_research, cmd_audit_pre_research, _deep_research_spec_from_args,
    cmd_deep_research_run, cmd_audit_literature_evidence, cmd_literature_report,
)























# --- 2. Pre-research injection mode-aware logic ---









# --- Phase 2 commands -------------------------------------------------------







































from research_loop.commands.execution import (  # inward shim (Phase 7d)
    cmd_execution_gate, _approved_execution_scripts, cmd_prepare_turing_workspace,
)








from research_loop.commands.reporting import (  # inward shim (Phase 7b)
    cmd_list, cmd_show, cmd_obsidian_sync,
)


# --- aggregate report (L10c Linnaeus) ---------------------------------------

# Section titles for English and Chinese reports
from research_loop.delta_render import (  # inward shim (Phase 7a)
    SECTION_TITLES_EN, SECTION_TITLES_CN, DELTA_LABELS_CN, SEED_SCHEMA_KEYS,
    _translate_delta_body_cn, _format_delta_body,
)

# --- v0.6 next-loop memory (divergence contract) ----------------------------

from research_loop.ledger import (  # inward shim (Phase 3a)
    _branch_ledger_path, _read_branch_ledger, _modality_ledger_path, _read_modality_ledger, _prior_unexplored_ids,
)











from research_loop.commands.continuation import (  # inward shim (Phase 7c)
    _list_card_ids, _build_loop_memory, _write_exec_manifest,
    _loop_memory_to_md, cmd_branch_status, cmd_modality_scan,
    cmd_emit_loop_memory,
)

















from research_loop.commands import ledger as _ledger_commands
from research_loop.commands.ledger import (  # inward shim (Phase 7c)
    _ledger_for, _write_hypothesis_commit_receipt, _emit_delta_v2,
    cmd_emit_delta, cmd_finalize_candidate, _ledger_cli,
    cmd_hypothesis_show, cmd_hypothesis_history, cmd_hypothesis_search,
    cmd_hypothesis_verify, cmd_hypothesis_migrate,
    cmd_hypothesis_authorize_context,
)
_ledger_commands._write_exec_manifest = _write_exec_manifest










from research_loop.commands.reporting import (  # inward shim (Phase 7b)
    _shared_report_owner, _update_reports_index, cmd_aggregate_report,
)


# --- pitfall ledger commands ------------------------------------------------

from research_loop.commands.pitfall import (  # inward shim (Phase 7b)
    cmd_list_pitfalls,
    cmd_pitfall_scan,
    cmd_pitfall_status,
    cmd_promote_pitfall,
    cmd_record_pitfall,
)



# --- shadow ranking commands ------------------------------------------------

from research_loop.commands.ranking import (  # inward shim (Phase 7b)
    _SyntheticPositionBiasedJudge,
    _average,
    _fair_false_first_win_rate,
    _load_benchmark_gold,
    _naive_benchmark,
    _ranking_accuracy,
    _ranking_advisory_records,
    _ranking_candidates,
    _ranking_events,
    _ranking_formal_decisions,
    _ranking_judge,
    _ranking_output_targets,
    _ranking_write_outputs,
    _read_ranking_delta,
    _validate_ranking_report_artifact,
    _validate_ranking_resume_provenance,
    _write_ranking_complete_marker,
    cmd_ranking_benchmark,
    cmd_ranking_report,
    cmd_ranking_shadow,
)

from research_loop.cli import build_parser, main  # inward shim (Phase 8)
