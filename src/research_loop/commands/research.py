"""Research CLI command family extracted from engine.py."""

import json
import sys
from pathlib import Path

from research_loop import deep_research, deep_research_task
from research_loop.common import _now
from research_loop.compatibility import PROFILE_V20, get_profile
from research_loop.delta import _delta_for_candidate, artifact_for_node
from research_loop.hypothesis_ledger import binding_path
from research_loop.paths import _candidate_file, _pre_research_file
from research_loop.preresearch import (
    PRE_RESEARCH_MAP, _LIT_PRE_RESEARCH_TYPES, _validate_pre_research_content,
)
from research_loop.yamlio import _load_yaml_front
from research_loop.topology import topology_for_profile


def _bound_profile(project_dir):
    path = binding_path(project_dir)
    if not path.is_file():
        return get_profile(PROFILE_V20), {"project_id": Path(project_dir).name}
    try:
        binding = json.loads(path.read_text(encoding="utf-8"))
        return get_profile(str(binding["profile_id"])), binding
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise deep_research.DeepResearchError(
            f"invalid project profile binding: {exc}"
        ) from exc


def _l8_storage_key(project_dir):
    profile, _ = _bound_profile(project_dir)
    return artifact_for_node(profile, "L8").storage_key

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
        profile, binding = _bound_profile(project_dir)
        _, node_map, _ = topology_for_profile(profile.profile_id)
        deep_research.persist_run(
            project_dir, args.cand_id, node, synthetic_payload,
            deep_research.skill_receipt("codex", ["synthetic-test"],
                                         "synthetic-test", "test-only"),
            project_id=str(binding["project_id"]),
            round_id=str(round_id),
            profile_id=profile.profile_id,
            research_persona=str(
                node_map[node].get("research_persona") or "Curie"
            ),
        )

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
        try:
            l8_key = _l8_storage_key(project_dir)
        except deep_research.DeepResearchError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        l8 = _ld(l8_key) or {}
        findings = json.dumps({"L7_key_results": l7.get("key_results"),
                               "L8_evidence_level": l8.get("evidence_level"),
                               "L8_evidence_verified": l8.get("evidence_verified"),
                               "L8_evidence_assessments": l8.get("evidence_assessments")},
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
    if not getattr(args, "allow_host_mismatch", False):
        try:
            same_host, host_reason = deep_research.host_matches(
                spec, explicit=getattr(args, "backend", None) is not None)
        except deep_research.DeepResearchError as exc:
            print(f"ERROR: Deep Research host is not declarable: {exc}", file=sys.stderr)
            return 3
        if not same_host:
            print(f"ERROR: Deep Research host mismatch: {host_reason}", file=sys.stderr)
            return 3
    consistent, consistency_reason = deep_research.validate_spec_consistency(spec)
    if not consistent:
        print(f"ERROR: Deep Research runtime spec is inconsistent: {consistency_reason}",
              file=sys.stderr)
        return 3
    ready, reason = deep_research.runtime_ready(spec)
    if not ready:
        print(f"ERROR: Deep Research runtime is not ready: {reason}", file=sys.stderr)
        return 3
    fm = _load_yaml_front(cf)
    try:
        profile, binding = _bound_profile(project_dir)
        _, node_map, _ = topology_for_profile(profile.profile_id)
        research_persona = str(
            node_map[args.node].get("research_persona") or ""
        )
        if not node_map[args.node].get("research_required") or not research_persona:
            raise deep_research.DeepResearchError(
                f"{args.node} has no declared research persona"
            )
    except (deep_research.DeepResearchError, KeyError, ValueError) as exc:
        print(f"ERROR: Deep Research identity is invalid: {exc}", file=sys.stderr)
        return 3
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
        l8_key = artifact_for_node(profile, "L8").storage_key
        result_context = json.dumps({
            "L7_key_results": _result_delta("L7_turing").get("key_results", {}),
            "L8_evidence_verified": _result_delta(l8_key).get("evidence_verified", []),
            "L8_evidence_level": _result_delta(l8_key).get("evidence_level", ""),
            "L8_evidence_assessments": _result_delta(l8_key).get(
                "evidence_assessments", []
            ),
        }, ensure_ascii=False, sort_keys=True)
    try:
        artifact = deep_research.run_and_persist(
            project_dir, args.cand_id, args.node, fm.get("question", ""), fm.get("claim", ""),
            spec, run_dir, skill_version, result_context,
            project_id=str(binding["project_id"]),
            round_id=str(fm.get("round_id") or "1"),
            profile_id=profile.profile_id,
            research_persona=research_persona,
        )
        ok, reason = deep_research.audit_evidence_pack(
            project_dir, args.cand_id, args.node, run_id=artifact["run_id"]
        )
    except deep_research.DeepResearchError as exc:
        print(f"ERROR: Deep Research failed: {exc}", file=sys.stderr)
        return 3
    if not ok:
        print(f"ERROR: Deep Research evidence gate failed: {reason}", file=sys.stderr)
        return 3
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


def cmd_deep_research_start(args):
    """Start the existing Deep Research command in a detached worker."""
    try:
        artifact = deep_research_task.start_task(args)
    except deep_research_task.DetachedTaskError as exc:
        print(f"ERROR: Deep Research task could not start: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


def cmd_deep_research_status(args):
    """Read the last status written by a detached Deep Research worker."""
    try:
        artifact = deep_research_task.get_status(args.project_dir, args.task_id)
    except deep_research_task.DetachedTaskError as exc:
        print(f"ERROR: Deep Research task status failed: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


def cmd_deep_research_collect(args):
    """Collect a detached result after repeating the existing exact-run audit."""
    try:
        artifact = deep_research_task.collect_task(
            args.project_dir, args.task_id, deep_research.audit_evidence_pack
        )
    except deep_research_task.DetachedTaskError as exc:
        print(f"ERROR: Deep Research task collection failed: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


def cmd_deep_research_worker(args):
    """Hidden detached entry point; reuse the full synchronous handler."""
    return deep_research_task.run_worker(
        args.project_dir, args.task_id, cmd_deep_research_run
    )

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
