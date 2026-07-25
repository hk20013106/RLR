#!/usr/bin/env python3
"""Research Loop Room V0.7 — canonical gated runtime engine.

This IS the V0.7 runtime. The filename `research_loop_v04.py` is retained only
for import/CLI stability (run_loop.py and the main-agent protocol import it);
it is not a legacy engine. As of V0.7, `assemble-context` enforces the
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

__version__ = "0.7.0"


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

# --- DAG topology (15 nodes, L9a/L9b parallel) ------------------------------
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

# Order of single-path nodes (L9a and L9b are parallel, listed together)

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
# and are checked the same way.
_common.REQUIRED_DEPENDENCIES = REQUIRED_DEPENDENCIES


from research_loop import templates as _templates
from research_loop.templates import (  # inward shim (Phase 7a)
    LAYERS, _knowledge_base_md, _dependencies_md, _candidate_template,
    _index_template, _handoff_template, _decision_log_template,
    _note_template, _preflight_template,
)
_templates.REQUIRED_DEPENDENCIES = REQUIRED_DEPENDENCIES
_templates.VALID_STATUSES = VALID_STATUSES
_templates.__version__ = __version__
_common._decision_log_template = _decision_log_template

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



def cmd_pre_research(args):
    """Output a pre-research prompt for the orchestrator to execute before a node.

    For L1: deep research (academic-research-suite) on the scientific question.
    For L4: literature review on methods used in similar studies.
    For L7: code search on GitHub/Bioconductor for existing pipelines.

    The orchestrator runs the research, saves results to
    02_Agent_Notes/_pre_research/<node>_research.md, then proceeds.
    """
    project_dir = Path(args.project_dir)
    node = args.node

    research_config = PRE_RESEARCH_MAP.get(node)
    if research_config is None:
        print(f"ERROR: no pre-research defined for node {node}", file=sys.stderr)
        return 2

    research_type = research_config["type"]
    queries = research_config["queries"]

    # Ground the research in THIS candidate's question/claim so it generalizes
    # beyond the seed queries (which are domain examples to adapt, not fixed).
    cf = _candidate_file(project_dir, args.cand_id)
    fm = _load_yaml_front(cf) if cf.exists() else {}
    question = fm.get("question", "")
    claim = fm.get("claim", "")
    title = fm.get("title", args.cand_id)
    round_id = 1
    try:
        round_id = int(fm.get("round_id", 1))
    except Exception:
        pass

    if getattr(args, "output_dir", None):
        output_file = Path(args.output_dir) / f"{node}_research.md"
    else:
        output_file = _pre_research_file(project_dir, node)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    write_placeholder = getattr(args, "write_placeholder", False)
    write_synthetic = getattr(args, "write_synthetic", False)

    # Missing file may get a placeholder; existing file should not be overwritten unless --write-placeholder is explicitly passed.
    should_write_placeholder = False
    if write_placeholder:
        should_write_placeholder = True
    elif not write_synthetic:
        if not output_file.exists():
            should_write_placeholder = True

    if should_write_placeholder and research_type in ("deep_research", "literature_review"):
        placeholder_content = f"""# Pre-Research: {research_type.replace('_', ' ').title()} (before {node})

## Runtime digest
NOT YET RUN

## Query log
- NOT YET RUN

## Tool receipt
- tool: none | time: {_now()} | summary: NOT YET RUN

## Source count
0
"""
        output_file.write_text(placeholder_content, encoding="utf-8")

    elif write_synthetic and research_type in ("deep_research", "literature_review"):
        if research_type == "deep_research":
            synthetic_content = f"""# Pre-Research: Deep Literature Search (before {node})

## Key Findings
- Finding 1 (citing [[09_Literature_Database/smith2020|Smith 2020]], 2020)

## Methods Used in Literature
- Method 1

## Gaps Our Study Addresses
- Gap 1

## Runtime digest
- [[09_Literature_Database/smith2020|Smith 2020]] doi:10.1000/abc123 — core finding: X associates with Y.

## Query log
- convergent evolution heart rate
- cardiac co-expression bat (0 results)

## Tool receipt
- tool: pubmed | time: 2026-07-05T10:00:00 | summary: 1 hit

## Source count
1
"""
        else:  # literature_review
            synthetic_content = f"""# Pre-Research: Method Literature Review (before {node})

## Methods Found
- Method 1 (citing [[09_Literature_Database/smith2020|Smith 2020]], parameters/settings used)

## Recommended Approach
- What to adopt and why (referencing papers in the database)

## Pitfalls to Avoid
- Pitfall 1 (how others failed, citing [[09_Literature_Database/smith2020|Smith 2020]])

## Runtime digest
- [[09_Literature_Database/smith2020|Smith 2020]] doi:10.1000/abc123 — core finding: X associates with Y.

## Query log
- WGCNA module preservation cross-species Zsummary
- signed vs unsigned WGCNA network cardiac

## Tool receipt
- tool: pubmed | time: 2026-07-05T10:00:00 | summary: 1 hit

## Source count
1
"""
        output_file.write_text(synthetic_content, encoding="utf-8")
        synthetic_extracts = [
            {"section": "Results", "text": "Synthetic result.", "locator": "Results"},
            {"section": "Discussion", "text": "Synthetic discussion.", "locator": "Discussion"},
            {"section": "Conclusion", "text": "Synthetic conclusion.", "locator": "Conclusion"},
            {"section": "Methods", "text": "Synthetic method.", "locator": "Methods"},
        ]
        synthetic_payload = {
            "schema_version": deep_research.SCHEMA_VERSION, "queries": list(queries),
            "papers": [{"doi": "10.1000/abc123", "title": "Synthetic Smith 2020",
                        "source_database": "synthetic-test", "metadata": {},
                        "source_metadata_response": {"fixture": "write-synthetic"},
                        "open_access": False, "extracts": synthetic_extracts}],
        }
        if research_type == "literature_review":
            synthetic_payload["review_search"] = {
                "query": "synthetic review query", "status": "none_found",
                "receipt": "synthetic-test 0"}
        deep_research.persist_run(
            project_dir, args.cand_id, node, synthetic_payload,
            deep_research.skill_receipt("codex", ["synthetic-test"],
                                         "synthetic-test", "test-only"))

    focus = research_config.get("description", "")
    grounding = (f"## This study\n"
                 f"- Title: {title}\n"
                 f"- Question: {question}\n"
                 f"- Claim: {claim}\n"
                 f"- Research focus for this step: {focus}\n\n"
                 f"Adapt the seed queries below to THIS question/claim and the "
                 f"actual data; they are domain examples, not a fixed list.\n")

    if research_type == "deep_research":
        prompt = f"""# Pre-Research: Deep Literature Search (before {node})

You MUST run this BEFORE generating the {node} delta.
This is Round {round_id} of the research loop.

{grounding}

## Core Requirements:
1. **CRITICAL**: You MUST use the `academic-research-suite` skill (which includes literature search tools like PubMed/bioRxiv/OpenAlex/Tavily) to perform a real-literature review.
2. **Database Verification & Reuse**:
   - First, scan the literature database directory `{project_dir.as_posix()}/09_Literature_Database` (if it exists) to see what papers have been reviewed in previous rounds.
   - If there are relevant papers, read them and incorporate/expand on their findings.
   - Search the web/academic databases for new papers to answer the queries and expand our understanding.
3. **Database Registration**:
   - For every new paper you find and select, you MUST add it to the growable literature database by running:
     `python manage_literature_db.py add {project_dir.as_posix()} --round {round_id} --json-data "<JSON_STRING>"`
   - Ensure the `<JSON_STRING>` is a single-line valid JSON string. Escape quotes properly. It must contain the following keys:
     - "doi": string (or empty)
     - "title": string
     - "authors": string (or list of strings)
     - "journal": string
     - "year": integer/string
     - "core_arguments": list of strings (key findings or arguments)
     - "evidence_level": "STRONG", "MODERATE", or "WEAK"
     - "tags": list of strings
     - "summary": string (relevance, methods, results summary)
     - "url": string (or empty)

Use the academic-research-suite / search tools to query (seed queries):
"""
        for i, q in enumerate(queries, 1):
            prompt += f"{i}. {q}\n"
        prompt += f"""
Write a structured summary to: {output_file.as_posix()}

Format of {output_file.as_posix()}:
IMPORTANT: Cite papers using Obsidian Wikilinks pointing to the literature database files (e.g., `[[09_Literature_Database/citekey|Paper Title]]` where `citekey` is the filename without `.md`).

## Key Findings
- Finding 1 (citing [[09_Literature_Database/citekey|Paper Title]], Year)
- Finding 2 (citing [[09_Literature_Database/citekey|Paper Title]], Year)

## Methods Used in Literature
- Method 1
- Method 2

## Gaps Our Study Addresses
- Gap 1
- Gap 2

## Query log
The ACTUAL search queries you issued (one bullet per query). Record zero-result
queries explicitly; do NOT omit them.
- <query string> (e.g. "0 results" when empty)

## Tool receipt
One bullet per tool call: tool name, timestamp, one-line return summary.
- tool: <name> | time: <ISO-8601> | summary: <what it returned>

## Source count
<integer> — distinct sources actually retrieved (0 is allowed but must be stated).

This summary will be injected into the {node} assemble-context as additional input.
"""
    elif research_type == "literature_review":
        prompt = f"""# Pre-Research: Method Literature Review (before {node})

You MUST run this BEFORE generating the {node} delta.
This is Round {round_id} of the research loop.

{grounding}

## Core Requirements:
1. **CRITICAL**: You MUST use the `academic-research-suite` skill (which includes literature search tools like PubMed/bioRxiv/OpenAlex/Tavily) to perform a real-literature review.
2. **Database Verification & Reuse**:
   - First, scan the literature database directory `{project_dir.as_posix()}/09_Literature_Database` (if it exists) to see what papers have been reviewed in previous rounds.
   - If there are relevant papers, read them and incorporate/expand on their findings.
   - Search the web/academic databases for new papers to answer the queries and expand our understanding.
3. **Database Registration**:
   - For every new paper you find and select, you MUST add it to the growable literature database by running:
     `python manage_literature_db.py add {project_dir.as_posix()} --round {round_id} --json-data "<JSON_STRING>"`
   - Ensure the `<JSON_STRING>` is a single-line valid JSON string. Escape quotes properly. It must contain the following keys:
     - "doi": string (or empty)
     - "title": string
     - "authors": string (or list of strings)
     - "journal": string
     - "year": integer/string
     - "core_arguments": list of strings (key findings or arguments)
     - "evidence_level": "STRONG", "MODERATE", or "WEAK"
     - "tags": list of strings
     - "summary": string (relevance, methods, results summary)
     - "url": string (or empty)

Search for papers on methodology used in similar studies (seed queries):
"""
        for i, q in enumerate(queries, 1):
            prompt += f"{i}. {q}\n"
        prompt += f"""
Focus on:
- What analysis approaches others have used for similar questions
- Standard pipelines and parameters
- Common pitfalls and how they were addressed

Write a structured summary to: {output_file.as_posix()}

Format of {output_file.as_posix()}:
IMPORTANT: Cite papers using Obsidian Wikilinks pointing to the literature database files (e.g., `[[09_Literature_Database/citekey|Paper Title]]` where `citekey` is the filename without `.md`).

## Methods Found
- Method 1 (citing [[09_Literature_Database/citekey|Paper Title]], parameters/settings used)
- Method 2 (citing [[09_Literature_Database/citekey|Paper Title]], parameters/settings used)

## Recommended Approach
- What to adopt and why (referencing papers in the database)

## Pitfalls to Avoid
- Pitfall 1 (how others failed, citing [[09_Literature_Database/citekey|Paper Title]])

## Query log
The ACTUAL search queries you issued (one bullet per query). Record zero-result
queries explicitly; do NOT omit them.
- <query string> (e.g. "0 results" when empty)

## Tool receipt
One bullet per tool call: tool name, timestamp, one-line return summary.
- tool: <name> | time: <ISO-8601> | summary: <what it returned>

## Source count
<integer> — distinct sources actually retrieved (0 is allowed but must be stated).

This summary will be injected into the {node} assemble-context as additional input.
"""
    elif research_type == "code_search":
        prompt = f"""# Pre-Research: Code Search (before {node})

You MUST run this BEFORE generating the {node} delta.

{grounding}
Search GitHub, Bioconductor, and CRAN for existing code (seed queries):
"""
        for i, q in enumerate(queries, 1):
            prompt += f"{i}. {q}\n"
        prompt += f"""
Check:
- Bioconductor packages (WGCNA, clusterProfiler, fgsea, etc.)
- GitHub repos with WGCNA pipelines
- Existing R scripts for module preservation, GSEA, ECM scoring

Write a structured summary to: {output_file}

Format:
## Existing Tools Found
- tool 1 (repo/package, what it does, URL)
- tool 2 (repo/package, what it does, URL)

## Reusable Code
- script/function 1 (what it does, how to use)

## Gap: What We Must Write Ourselves
- gap 1 (why no existing tool fits)

This summary will be injected into the {node} assemble-context as additional input.
"""
    elif research_type == "literature_verification":
        # Ground the search in the ACTUAL L7/L8 findings, not just the question,
        # so L8.5 verifies real results against published literature.
        def _ld(key):
            p = _delta_for_candidate(project_dir, key, args.cand_id)
            if p and p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    return None
            return None
        l7 = _ld("L7_turing") or {}
        l8 = _ld("L8_curie") or {}
        findings = json.dumps({"L7_key_results": l7.get("key_results"),
                               "L8_evidence_level": l8.get("evidence_level"),
                               "L8_evidence_verified": l8.get("evidence_verified")},
                              ensure_ascii=False, indent=2)
        prompt = f"""# Pre-Research: Literature Verification (before {node})

You MUST run this BEFORE generating the {node} delta.

{grounding}
## Actual results to verify (from L7 execution + L8 audit)
{findings}

Knowledge base (your access for L8.5 is read-write):
1. First, scan `{project_dir.as_posix()}/09_Literature_Database` (if it exists) to
   reuse papers already reviewed in previous rounds.
2. Use the academic-research-suite skill to search PubMed/EuropePMC for papers that
   CONFIRM or CONTRADICT these SPECIFIC findings (concrete entities: the genes,
   modules, phenotypes, methods above).
3. For every new paper you select, you MUST add it to the database:
   `python manage_literature_db.py add {project_dir.as_posix()} --round {round_id} --json-data "<JSON_STRING>"`
4. Cite papers via Obsidian wikilinks `[[09_Literature_Database/<citekey>|Title]]`.

Seed queries (adapt to the actual results above):
"""
        for i, q in enumerate(queries, 1):
            prompt += f"{i}. {q}\n"
        prompt += f"""
Write a structured summary to: {output_file}

Format:
## Papers Found (verifying actual results)
- [[09_Literature_Database/<citekey>|Title]] (PMID) -- confirms / contradicts / extends WHICH finding above

## Verdict
- Does the published literature support the L7/L8 findings? Any contradictions?

This summary will be injected into the {node} assemble-context as additional input.
"""

    print(prompt)
    print(f"\n[pre-research] output target: {output_file}")
    return 0


def cmd_audit_pre_research(args):
    """Audit existing pre-research artifacts in a project directory."""
    project_dir = Path(args.project_dir)
    results = {}
    for node, pr_cfg in PRE_RESEARCH_MAP.items():
        is_lit = pr_cfg.get("type") in _LIT_PRE_RESEARCH_TYPES
        if not is_lit:
            results[node] = {
                "status": "NOT_APPLICABLE",
                "reason": "non-literature node"
            }
            continue

        prf = _pre_research_file(project_dir, node)
        if not prf.exists():
            results[node] = {
                "status": "FAIL",
                "reason": f"artifact missing ({prf.as_posix()})"
            }
            continue

        try:
            text = prf.read_text(encoding="utf-8", errors="replace")
            ok, reason = _validate_pre_research_content(text, pr_cfg)
            if ok:
                results[node] = {
                    "status": "PASS",
                    "reason": ""
                }
            else:
                results[node] = {
                    "status": "FAIL",
                    "reason": reason
                }
        except Exception as e:
            results[node] = {
                "status": "FAIL",
                "reason": f"error reading/parsing: {e}"
            }

    report = {
        "project_dir": project_dir.as_posix(),
        "results": results
    }
    print(json.dumps(report, indent=2))
    return 0


def _deep_research_spec_from_args(args):
    overrides = {
        "backend": args.backend, "executable": args.executable,
        "plugin_dir": args.plugin_dir, "model": args.model,
        "timeout": args.timeout, "skill_path": args.skill_path,
        "skill_version": args.skill_version,
    }
    return deep_research.load_runtime_spec(args.project_dir, overrides)


def cmd_deep_research_run(args):
    """Execute an explicit Academic Research Skills CLI run and persist evidence."""
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: candidate not found: {args.cand_id}", file=sys.stderr)
        return 2
    try:
        spec, skill_version = _deep_research_spec_from_args(args)
    except deep_research.DeepResearchError as exc:
        print(f"ERROR: Deep Research runtime is not configured: {exc}", file=sys.stderr)
        return 3
    ready, reason = deep_research.runtime_ready(spec)
    if not ready:
        print(f"ERROR: Deep Research runtime is not ready: {reason}", file=sys.stderr)
        return 3
    fm = _load_yaml_front(cf)
    run_dir = project_dir / "08_Audit" / "deep_research_runtime" / args.cand_id / args.node.replace(".", "_")
    result_context = ""
    if args.node == "L8.5":
        def _result_delta(key):
            path = _delta_for_candidate(project_dir, key, args.cand_id)
            if not path or not path.exists():
                return {}
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
        result_context = json.dumps({
            "L7_key_results": _result_delta("L7_turing").get("key_results", {}),
            "L8_evidence_verified": _result_delta("L8_curie").get("evidence_verified", []),
            "L8_evidence_level": _result_delta("L8_curie").get("evidence_level", ""),
        }, ensure_ascii=False, sort_keys=True)
    try:
        artifact = deep_research.run_and_persist(
            project_dir, args.cand_id, args.node, fm.get("question", ""), fm.get("claim", ""),
            spec, run_dir, skill_version, result_context)
        ok, reason = deep_research.audit_evidence_pack(project_dir, args.cand_id, args.node)
    except deep_research.DeepResearchError as exc:
        print(f"ERROR: Deep Research failed: {exc}", file=sys.stderr)
        return 3
    if not ok:
        print(f"ERROR: Deep Research evidence gate failed: {reason}", file=sys.stderr)
        return 3
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


def cmd_audit_literature_evidence(args):
    ok, reason = deep_research.audit_evidence_pack(args.project_dir, args.cand_id, args.node)
    print(json.dumps({"candidate_id": args.cand_id, "node": args.node,
                      "status": "PASS" if ok else "FAIL", "reason": reason}, indent=2))
    return 0 if ok else 3


def cmd_literature_report(args):
    nodes = args.node or ["L1", "L4", "L8.5"]
    text = deep_research.render_evidence_digest(args.project_dir, args.cand_id, nodes)
    if args.format == "json":
        print(json.dumps({"candidate_id": args.cand_id, "nodes": nodes, "digest": text}, ensure_ascii=False))
    else:
        print(text, end="")
    return 0
















# --- 2. Pre-research injection mode-aware logic ---










# --- Phase 2 commands -------------------------------------------------------









































def cmd_execution_gate(args):
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    pf = project_dir / "00_Preflight"
    missing = []
    if not (pf / "skill_use_plan.md").exists():
        missing.append("00_Preflight/skill_use_plan.md")
    if not (pf / "input_manifest.md").exists():
        missing.append("00_Preflight/input_manifest.md")
    fm = _load_yaml_front(cf)
    status = fm.get("current_status", "?")
    if status != "METHOD_APPROVED":
        missing.append(f"approved analysis plan (candidate is {status}, "
                       f"need METHOD_APPROVED)")
    if missing:
        print("EXECUTION GATE: REJECT")
        for m in missing:
            print(f"  missing: {m}")
        print("  Turing may NOT execute. Resolve the above (Linnaeus L0 / "
              "Oppenheimer L6) first.")
        return 1
    _append_decision(project_dir, args.cand_id, status, "NEEDS_EXECUTION",
                     "execution gate passed: preflight + approved plan present",
                     route_to="Turing", agent="Oppenheimer",
                     kind="execution_gate")
    _set_status(project_dir, args.cand_id, "NEEDS_EXECUTION", "Turing")
    print("EXECUTION GATE: PASS")
    print("  skill_use_plan.md ........ OK")
    print("  input_manifest.md ........ OK")
    print("  approved analysis plan ... OK (METHOD_APPROVED)")
    print(f"  {args.cand_id} -> NEEDS_EXECUTION (route: Turing)")
    return 0


def _registered_candidate_inputs(project_dir, cand_id):
    """Resolve only key files registered for this candidate's input aliases."""
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf)
    aliases = {x.strip() for x in str(fm.get("input_alias", "")).split(",")
               if x.strip()}
    manifest = Path(project_dir) / "00_Preflight" / "input_manifest.md"
    resolved, missing = [], []
    if not manifest.exists():
        return resolved, ["missing required input manifest: 00_Preflight/input_manifest.md"]
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        columns = [x.strip().strip("`") for x in line.strip().strip("|").split("|")]
        if len(columns) < 3 or columns[0] not in aliases:
            continue
        alias, root, key_files = columns[:3]
        root_path = Path(root)
        for raw in key_files.split(";"):
            relative = raw.strip().strip("`")
            if not relative:
                continue
            src = root_path / Path(relative.replace("/", os.sep))
            if src.exists() and src.is_file():
                resolved.append((src, alias, relative))
            else:
                missing.append(
                    f"missing required input: {alias}/{relative} ({src})")
    found_aliases = {alias for _, alias, _ in resolved}
    for alias in sorted(aliases - found_aliases):
        if not any(f"{alias}/" in item for item in missing):
            missing.append(f"missing required input registration for alias: {alias}")
    return resolved, missing


def _approved_execution_scripts(project_dir, cand_id):
    """Resolve exact script names from the candidate-owned L6 analysis plan."""
    delta = _delta_for_candidate(project_dir, "L6_oppenheimer", cand_id)
    if not delta:
        return [], ["missing execution script plan: L6_oppenheimer delta"]
    try:
        data = json.loads(delta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], ["missing execution script plan: unreadable L6_oppenheimer delta"]
    plan = data.get("analysis_plan", [])
    if isinstance(plan, dict):
        names = plan.get("scripts", [])
    elif isinstance(plan, list):
        names = [name for item in plan if isinstance(item, dict)
                 for name in item.get("scripts", [])]
    else:
        names = []
    roots = [
        Path(project_dir) / "04_Analysis_Outputs",
        Path(project_dir) / "scripts_v05b",
        Path(project_dir) / "02_Agent_Notes" / "Turing",
    ]
    resolved, missing = [], []
    for name in names:
        script_name = Path(str(name)).name
        matches = []
        for root in roots:
            if root.is_dir():
                matches.extend(p for p in root.rglob(script_name)
                               if p.is_file() and "_turing_workspace_" not in str(p))
        matches = sorted(set(matches))
        if len(matches) == 1:
            resolved.append(matches[0])
        elif not matches:
            missing.append(f"missing execution script: {script_name}")
        else:
            missing.append(
                f"ambiguous execution script: {script_name} ({len(matches)} matches)")
    return resolved, missing


def cmd_prepare_turing_workspace(args):
    """Path A: build an isolated execution workspace for Turing (L7).

    Copies the deltas Turing is allowed to see (L0, L6), the preflight files,
    and any explicitly allowlisted input data files into a fresh
    PROJECT_DIR/_turing_workspace_<ts>/ tree (same disk, shutil.copy2, never
    hard links). Turing runs scripts in scripts/, writes to results/, and reads
    only from inputs/; the project tree and raw inputs stay untouched.
    """
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    fm = _load_yaml_front(cf)
    status = fm.get("current_status", "?")
    if status != "NEEDS_EXECUTION":
        print(f"ERROR: {args.cand_id} is {status}; Turing workspace requires "
              f"NEEDS_EXECUTION (run execution-gate first).", file=sys.stderr)
        return 1

    if args.clean:
        for old in sorted(project_dir.glob("_turing_workspace_*")):
            if old.is_dir():
                shutil.rmtree(old, ignore_errors=True)

    ws = project_dir / f"_turing_workspace_{args.cand_id}_{_stamp()}"
    inputs = ws / "inputs"
    for sub in (inputs, ws / "scripts", ws / "results"):
        sub.mkdir(parents=True, exist_ok=True)

    copied, missing, staged_files = [], [], []

    def stage(src, dest, reason):
        src = Path(src)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(str(dest.relative_to(ws)).replace("\\", "/"))
        staged_files.append({
            "original_path": str(src.resolve()),
            "workspace_path": str(dest.resolve()),
            "sha256": _sha256(dest),
            "reason": reason,
            "candidate_id": args.cand_id,
            "node": "L7",
        })

    # Deltas Turing is allowed to see per the DAG (L6 approved plan, L0 skills).
    for delta_key in ("L0_linnaeus", "L6_oppenheimer"):
        df = _delta_for_candidate(project_dir, delta_key, args.cand_id)
        if df and df.exists():
            stage(df, inputs / df.name, f"DAG-allowed {delta_key} delta")
        else:
            missing.append(f"{delta_key} delta")

    # Preflight files (skill plan, manifests, forbidden shortcuts).
    pf = project_dir / "00_Preflight"
    for fname in PREFLIGHT_FILES:
        src = pf / fname
        if src.exists():
            stage(src, inputs / fname, f"L0 preflight allowlist: {fname}")
        else:
            missing.append(f"00_Preflight/{fname}")

    # Candidate-declared inputs: only registered key files enter the workspace.
    registered, input_missing = _registered_candidate_inputs(
        project_dir, args.cand_id)
    missing.extend(input_missing)
    for src, alias, relative in registered:
        dest = inputs / alias / Path(relative.replace("/", os.sep))
        stage(src, dest, f"registered candidate input: {alias}/{relative}")

    # Explicit CLI files remain a narrow additive allowlist.
    for raw in (args.file or []):
        src = Path(raw)
        if src.exists() and src.is_file():
            stage(src, inputs / "explicit" / src.name,
                  "explicit --file allowlist")
        else:
            missing.append(f"allowlisted file not found: {raw}")

    # Candidate-owned L6 plan: stage exact existing script names only.
    approved_scripts, script_missing = _approved_execution_scripts(
        project_dir, args.cand_id)
    missing.extend(script_missing)
    for src in approved_scripts:
        stage(src, ws / "scripts" / src.name,
              "exact script approved by candidate L6 analysis_plan")

    json_manifest = {
        "workspace": str(ws.resolve()),
        "candidate_id": args.cand_id,
        "node": "L7",
        "created_at": _now(),
        "status_at_creation": status,
        "staged_files": staged_files,
        "missing": missing,
    }
    (ws / "WORKSPACE_MANIFEST.json").write_text(
        json.dumps(json_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    manifest = [
        "---",
        f"workspace: {_yaml_value(ws.name)}",
        f"candidate_id: {_yaml_value(args.cand_id)}",
        f"created_at: {_yaml_value(_now())}",
        f"status_at_creation: {_yaml_value(status)}",
        "---",
        "",
        f"# Turing Workspace (Path A) - {args.cand_id}",
        "",
        "Isolated execution workspace. Turing runs scripts in `scripts/`, writes",
        "outputs to `results/`, and reads only the files in `inputs/`. The project",
        "tree and the raw inputs are NOT modified from here.",
        "",
        "## Copied in",
        "",
    ]
    manifest += ([f"- {c}" for c in copied] or ["- _none_"])
    if missing:
        manifest += ["", "## Missing (not copied)", ""]
        manifest += [f"- {m}" for m in missing]
    (ws / "WORKSPACE_MANIFEST.md").write_text("\n".join(manifest) + "\n",
                                              encoding="utf-8")

    print(f"Turing workspace ready: {ws}")
    print(f"  inputs/ ... {len(copied)} file(s) copied")
    print("  scripts/ .. (Turing writes modular scripts here)")
    print("  results/ .. (Turing writes outputs here)")
    if missing:
        print(f"  WARN: {len(missing)} expected item(s) missing:", file=sys.stderr)
        for m in missing:
            print(f"    - {m}", file=sys.stderr)
        return 1
    return 0


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



# --- cli --------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="research_loop_v04.py",
        description="Research Loop Room V0.7 - canonical gated runtime engine "
                    "(DAG-driven subagent architecture; assemble-context "
                    "enforces the V0.7 deep-research gate).")
    p.add_argument("--version", action="version", version=f"v{__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    # demo
    sp = sub.add_parser("demo", help="generate a v0.4 demo project with DAG structure")
    sp.set_defaults(func=cmd_demo)

    # new-project
    sp = sub.add_parser("new-project", help="create a new v0.4 project folder")
    sp.add_argument("name")
    sp.add_argument("topic", nargs="?", default="")
    sp.add_argument("--knowledge-store", dest="knowledge_store",
                    help="shared HypothesisLedger SQLite store; binds this project")
    sp.set_defaults(func=cmd_new_project)

    # preflight
    sp = sub.add_parser("preflight", help="L0 Linnaeus boot gate (00_Preflight/)")
    sp.add_argument("project_dir")
    sp.add_argument("--force", action="store_true", help="overwrite existing files")
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
    sp.add_argument("--knowledge-store", dest="knowledge_store")
    sp.set_defaults(func=cmd_assemble_context)

    # emit-delta
    sp = sub.add_parser("emit-delta", help="validate and save a delta JSON")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--node", required=True)
    sp.add_argument("--persona", required=True)
    sp.add_argument("--file", required=True, help="delta JSON file to import")
    sp.add_argument("--receipt", help="context_manifest JSON from assemble-context; "
                    "verifies upstream delta hashes if provided")
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
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--node", required=True, choices=["L1", "L4", "L8.5"])
    sp.add_argument("--backend", choices=["codex", "claude"], help="override configured backend")
    sp.add_argument("--executable", help="override configured CLI executable")
    sp.add_argument("--plugin-dir", help="required Academic Research Skills plugin path for Claude")
    sp.add_argument("--skill-path", help="Codex academic-research-suite installation path")
    sp.add_argument("--skill-version", help="override configured ARS package version")
    sp.add_argument("--model")
    sp.add_argument("--timeout", type=int)
    sp.set_defaults(func=cmd_deep_research_run)

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
                    help="default draft; only L8 Curie confirms")
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
                        help="L8 Curie: confirm / false_positive / obsolete a pitfall")
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



