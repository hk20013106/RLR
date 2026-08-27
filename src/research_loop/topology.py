"""DAG topology constants (Phase 1a leaf extraction).

Pure data + compatibility profile selection. ``DAG_NODES`` represents the
current native topology; ``topology_for_profile`` removes native-only stages
when reading historical projects.
"""

import copy

from research_loop.compatibility import DEFAULT_NATIVE_PROFILE, PROFILE_V20, get_profile

AGENTS = ["Linnaeus", "Einstein", "Feynman", "Oppenheimer", "Fisher",
          "Tukey", "Turing", "Curie", "Darwin", "Jobs"]

DECISION_TRANSITIONS = {
    "NEW": {"IDEA_PROPOSED"},
    "IDEA_PROPOSED": {"IDEA_SELECTED", "IDEA_REJECTED", "DROP"},
    "IDEA_SELECTED": {"METHOD_PROPOSED"},
    "IDEA_REJECTED": {"DROP"},
    "METHOD_PROPOSED": {"METHOD_APPROVED", "METHOD_REJECTED", "DROP"},
    "METHOD_REJECTED": {"IDEA_SELECTED", "METHOD_PROPOSED", "DROP"},
    "METHOD_APPROVED": {"NEEDS_EXECUTION"},
    "NEEDS_EXECUTION": {"EXECUTED"},
    "EXECUTED": {"AUDITED"},
    "AUDITED": {"UNDER_REVIEW"},
    "UNDER_REVIEW": {"KEEP", "REVISE", "DOWNGRADE", "DROP"},
    "REVISE": {"IDEA_PROPOSED", "METHOD_PROPOSED", "NEEDS_EXECUTION", "UNDER_REVIEW"},
    "DOWNGRADE": {"DROP"},
    "KEEP": set(),
    "DROP": set(),
    "ARCHIVED": set(),
}

# Canonical per-node authority for the external literature knowledge base.
# Topology owns this policy because topology_for_profile() is the canonical
# construction path consumed by both the modular CLI/context code and engine.
KNOWLEDGE_BASE_ACCESS = {
    "L0.5": "read-write", "L1": "none", "L4": "read-write",
    "L8.5": "read-write", "L0": "read",
    "L9a": "read", "L9b": "read",
    "L10a": "read", "L10b": "read", "L10c": "read",
}

DAG_NODES = [
    {
        "node": "L0", "persona": "Linnaeus",
        "status_before": "NEW", "advance_command": "decision",
        "must": [
            "Validate the authoritative l0_input declaration and verify current-round inputs",
            "For continuation rounds, restore the exact prior round manifest and verify selected inherited path/SHA references",
            "Freeze one CurrentRoundDataBinding before downstream consumers use scientific data",
            "Fill skill_use_plan with real skills, not template placeholders",
        ],
        "must_not": [
            "Execute code", "Interpret data", "Change candidate status",
            "Treat input_manifest.md or input_alias as scientific-data authority",
            "Leave template placeholders in preflight files",
        ],
        "stop_conditions": [
            "Any required dependency missing",
            "Current input declaration invalid or current file hash mismatch",
            "Continuation restore or inherited selector verification fails",
        ],
        "advance_status": "IDEA_PROPOSED", "advance_reason": "Preflight complete, route to Curie retrieval",
        "context_inputs": ["candidate_frontmatter"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Verify runtime + l0_input, restore prior evidence when needed, freeze current-round data binding",
        "agent_type": "default",
    },
    {
        "node": "L0.5", "persona": "Curie",
        "status_before": "IDEA_PROPOSED", "advance_command": None,
        "advance_status": None, "advance_reason": None,
        "context_inputs": ["L0"],
        "is_parallel": False, "is_execution": False,
        "node_kind": "research",
        "research_required": True,
        "research_persona": "Curie",
        "pre_research": "deep_research",
        "tools_policy": "research",
        "action_hint": (
            "Derive literature searches from the canonical L0 ResearchSeed, "
            "persist a source-located EvidencePack, and freeze the exact run"
        ),
        "must": [
            "Use only the validated L0 scientific question and current-round hypothesis as semantic seed",
            "Persist actual search queries, retrieval receipts, source identifiers, and located extracts",
            "Freeze exactly one successful evidence run to the current ResearchSeed before L1",
        ],
        "must_not": [
            "Generate an L1 hypothesis delta",
            "Change candidate status",
            "Use project-specific hardcoded search queries",
            "Replace an already frozen evidence run for the same ResearchSeed",
        ],
        "stop_conditions": [
            "Canonical L0 ResearchSeed is missing or invalid",
            "Evidence cannot be source-located or the research runtime fails",
        ],
        "agent_type": "research",
    },
    {
        "node": "L1", "persona": "Einstein",
        "status_before": "IDEA_PROPOSED", "advance_command": "decision",
        "advance_status": "IDEA_PROPOSED", "advance_reason": "Einstein hypotheses generated, route to Feynman",
        "context_inputs": ["candidate_frontmatter", "L0"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Generate scientific hypotheses from the frozen L0.5 EvidencePack",
        "must": ["Generate testable scientific hypotheses from candidate question and frozen research evidence", "Each proposal must include statement, operationalization, and at least one predeclared falsification criterion; IDs are engine-assigned"],
        "must_not": ["Execute code", "Change candidate status", "Design analysis methods", "Run independent literature searches"],
        "stop_conditions": ["No testable hypothesis generated"],
        "agent_type": "default",
    },
    {
        "node": "L2", "persona": "Feynman",
        "status_before": "IDEA_PROPOSED", "advance_command": "decision",
        "advance_status": "IDEA_PROPOSED", "advance_reason": "Feynman falsification complete, route to Oppenheimer",
        "context_inputs": ["candidate_frontmatter", "L1"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Blind-review and attack the L1 hypotheses",
        "must": ["Blind-review every L1 hypothesis", "Bind every attack, confounder, diagnostic test, and exhaustive verdict to one hypothesis_id", "Rate each attack by severity"],
        "must_not": ["Execute code", "Change candidate status", "Soft-pedal criticism"],
        "stop_conditions": ["No attacks generated"],
        "agent_type": "default",
    },
    {
        "node": "L3", "persona": "Oppenheimer",
        "status_before": "IDEA_PROPOSED", "advance_command": "triage-idea",
        "advance_status": "IDEA_SELECTED", "advance_reason": "",
        "context_inputs": ["L1", "L2"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Triage hypotheses: select testable ones, reject weak ones",
        "must": ["Select testable hypotheses from L1/L2 debate", "Reject weak ones with reason"],
        "must_not": ["Execute code", "Act on unverified deltas"],
        "stop_conditions": ["No hypotheses selected"],
        "agent_type": "default",
    },
    {
        "node": "L4", "persona": "Fisher",
        "status_before": "IDEA_SELECTED", "advance_command": "decision",
        "advance_status": "METHOD_PROPOSED", "advance_reason": "Fisher method design complete, route to Tukey",
        "context_inputs": ["L1", "L3", "L2"],
        "is_parallel": False, "is_execution": False,
        "pre_research": "literature_review",
        "research_persona": "Curie", "research_required": True,
        "action_hint": "Design experimental/analysis strategies",
        "must": ["Design experimental strategies for selected hypotheses", "Reuse existing skills and code patterns", "Define scripts_needed list with purpose"],
        "must_not": ["Execute code", "Change candidate status", "Design without reading L1/L3"],
        "stop_conditions": ["No strategy defined"],
        "agent_type": "default",
    },
    {
        "node": "L5", "persona": "Tukey",
        "status_before": "METHOD_PROPOSED", "advance_command": "decision",
        "advance_status": "METHOD_PROPOSED", "advance_reason": "Tukey QC review complete, route to Oppenheimer",
        "context_inputs": ["L4", "L2"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Critique the method design from EDA/QC perspective",
        "must": ["Critique every selected hypothesis and its L4 strategy from an EDA/QC perspective", "Bind attacks, QC checkpoints, and failure stop rules to hypothesis_ids and strategy_id"],
        "must_not": ["Execute code", "Change status"],
        "stop_conditions": ["No QC checkpoints defined"],
        "agent_type": "default",
    },
    {
        "node": "L6", "persona": "Oppenheimer",
        "status_before": "METHOD_PROPOSED", "advance_command": "triage-method",
        "advance_status": "METHOD_APPROVED", "advance_reason": "",
        "context_inputs": ["L4", "L5"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Approve or reject the analysis plan",
        "must": ["Approve or reject the analysis plan", "Record modifications and reason"],
        "must_not": ["Execute code", "Approve without reading L4/L5"],
        "stop_conditions": ["No approved_strategy"],
        "agent_type": "default",
    },
    {
        "node": "L7", "persona": "Turing",
        "status_before": "METHOD_APPROVED", "advance_command": "execution-gate",
        "advance_status": "NEEDS_EXECUTION", "advance_reason": "",
        "context_inputs": ["L6", "L0"],
        "is_parallel": False, "is_execution": True,
        "pre_research": "code_search",
        "action_hint": "Execute approved scripts against binding-staged data in the controlled workspace",
        "must": [
            "Execute ONLY scripts in approved analysis_plan",
            "Stage scientific data only from the verified CurrentRoundDataBinding",
            "Run in prepared Turing workspace ONLY",
            "Record exit_code and output_files",
        ],
        "must_not": [
            "Execute unapproved scripts", "Access files outside workspace", "Change status",
            "Use input_manifest.md, input_alias, or --file to expand scientific-data authority",
        ],
        "stop_conditions": [
            "CurrentRoundDataBinding missing/changed or any bound input fails hash verification",
            "Any script fails",
        ],
        "agent_type": "worker",
    },
    {
        "node": "L8", "persona": "Curie",
        "status_before": "EXECUTED", "advance_command": "decision",
        "advance_status": "AUDITED", "advance_reason": "Curie evidence audit complete, route to literature verification",
        "context_inputs": ["L7", "L6", "candidate_frontmatter"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Audit execution results, verify reproducibility, assign evidence level",
        "must": ["Verify every output file L7 claims", "Assign evidence_level", "Audit reproducibility"],
        "must_not": ["Execute code", "Change status", "Trust without verification"],
        "stop_conditions": ["Key output files missing"],
        "agent_type": "default",
    },
    {
        "node": "L8.5", "persona": "Curie",
        "status_before": "AUDITED", "advance_command": "decision",
        "advance_status": "UNDER_REVIEW", "advance_reason": "L8.5 literature verification complete, route to review",
        "context_inputs": ["L7", "L8", "candidate_frontmatter"],
        "is_parallel": False, "is_execution": False,
        "research_persona": "Curie", "research_required": True,
        "action_hint": "Search PubMed/EuropePMC based on L7/L8 actual results to verify findings",
        "must": ["Search PubMed based on L7/L8 results", "Assess every active hypothesis exactly once using source-located deep-research evidence IDs and the completed run receipt", "Cite real PMIDs/DOIs"],
        "must_not": ["Fabricate citations", "Change status"],
        "stop_conditions": ["No real papers found"],
        "agent_type": "default",
    },
    {
        "node": "L9a", "persona": "Feynman",
        "status_before": "UNDER_REVIEW", "advance_command": "decision",
        "advance_status": "UNDER_REVIEW", "advance_reason": "L9a falsification complete",
        "context_inputs": ["L1", "L7", "L8", "L8.5"],
        "is_parallel": True, "is_execution": False,
        "action_hint": "Hard falsification of results from statistical/logical completeness",
        "must": ["Hard-falsify results from statistical/logical completeness", "Identify risks, surviving claims, falsified claims"],
        "must_not": ["Execute code", "Change status", "Influenced by L9b"],
        "stop_conditions": ["No falsification analysis"],
        "agent_type": "default",
    },
    {
        "node": "L9b", "persona": "Darwin",
        "status_before": "UNDER_REVIEW", "advance_command": None,
        "advance_status": None, "advance_reason": None,
        "context_inputs": ["L1", "L7", "L8", "L8.5"],
        "is_parallel": True, "is_execution": False,
        "action_hint": "Biological interpretation of results",
        "must": ["Interpret every active hypothesis exactly once", "Ground every interpretation only in verified evidence IDs and state limitations"],
        "must_not": ["Execute code", "Change status", "Influenced by L9a"],
        "stop_conditions": ["No interpretations"],
        "agent_type": "default",
    },
    {
        "node": "L10a", "persona": "Jobs",
        "status_before": "UNDER_REVIEW", "advance_command": "decision",
        "advance_status": "UNDER_REVIEW", "advance_reason": "Jobs value assessment complete",
        "context_inputs": ["candidate_frontmatter", "L8", "L8.5", "L9a", "L9b"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Assess value, frame manuscript direction",
        "must": ["Assess scientific value and manuscript potential for every active hypothesis", "Frame manuscript direction", "Be honest about limitations"],
        "must_not": ["Execute code", "Change status", "Overhype weak results"],
        "stop_conditions": ["No value_assessment"],
        "agent_type": "default",
    },
    {
        "node": "L10b", "persona": "Oppenheimer",
        "status_before": "UNDER_REVIEW", "advance_command": "decision",
        "advance_status": "KEEP", "advance_reason": "",
        "context_inputs": ["L10a", "L8", "L8.5", "L9a", "L9b"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Final decision: KEEP / REVISE / DOWNGRADE / DROP",
        "must": ["Make final decision: KEEP/REVISE/DOWNGRADE/DROP", "Reason must reference L8/L8.5/L9a/L9b"],
        "must_not": ["Execute code", "Decide without reading all inputs"],
        "stop_conditions": ["No final_decision"],
        "agent_type": "default",
    },
    {
        "node": "L10c", "persona": "Linnaeus",
        "status_before": "KEEP", "advance_command": "aggregate-report",
        "advance_status": None, "advance_reason": None,
        "context_inputs": ["ALL"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Aggregate all deltas into FINAL_REPORT",
        "must": ["Aggregate all deltas in DAG order", "Generate FINAL_REPORT.md and FINAL_REPORT_CN.md"],
        "must_not": ["Execute code", "Change status", "Skip any delta"],
        "stop_conditions": ["Any delta missing"],
        "agent_type": "default",
    },
]

# Every topology view carries an explicit KB permission from this single policy
# table. This prevents import-order-dependent authority in modular consumers.
for _node in DAG_NODES:
    _node["knowledge_base"] = KNOWLEDGE_BASE_ACCESS.get(_node["node"], "none")
del _node

NODE_MAP = {n["node"]: n for n in DAG_NODES}

DAG_SEQUENCE = ["L0", "L0.5", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L8.5",
                "L9_parallel", "L10a", "L10b", "L10c"]

DELTA_DAG_ORDER = [
    "L0_linnaeus", "L1_einstein", "L2_feynman", "L3_oppenheimer",
    "L4_fisher", "L5_tukey", "L6_oppenheimer", "L7_turing",
    "L8_curie", "L8.5_curie", "L9a_feynman", "L9b_darwin",
    "L10a_jobs", "L10b_oppenheimer",
]


def topology_for_profile(profile_id: str) -> tuple[list[dict], dict[str, dict], list[str]]:
    """Return the DAG view selected by an immutable compatibility profile."""
    profile = get_profile(profile_id)
    nodes = copy.deepcopy(DAG_NODES)
    sequence = list(DAG_SEQUENCE)

    # L0.5 belongs only to the current native profile. Historical projects keep
    # their original L1-owned pre-research contract and artifact semantics.
    if profile.profile_id != DEFAULT_NATIVE_PROFILE:
        nodes = [item for item in nodes if item["node"] != "L0.5"]
        sequence = [item for item in sequence if item != "L0.5"]
        legacy_l1 = next(item for item in nodes if item["node"] == "L1")
        legacy_l1.update({
            "pre_research": "deep_research",
            "research_persona": "Curie",
            "research_required": True,
        })

    if not profile.l9_parallel:
        by_node = {item["node"]: item for item in nodes}
        by_node["L8"]["persona"] = "Tukey"
        by_node["L9a"]["is_parallel"] = False
        by_node["L9b"].update({
            "is_parallel": False,
            "advance_command": "decision",
            "advance_status": "UNDER_REVIEW",
            "advance_reason": "L9b interpretation complete",
            "context_inputs": ["L1", "L7", "L8", "L8.5", "L9a"],
            "must_not": ["Execute code", "Change status"],
        })
        sequence = [item for item in sequence if item != "L9_parallel"]
        sequence[sequence.index("L10a"):sequence.index("L10a")] = ["L9a", "L9b"]
    elif not profile.l9_parallel:
        raise ValueError(f"unsupported topology profile: {profile.profile_id}")

    return nodes, {item["node"]: item for item in nodes}, sequence


class DAGTopology:
    """Thin read-only namespace over the module-level topology constants."""
    AGENTS = AGENTS
    DECISION_TRANSITIONS = DECISION_TRANSITIONS
    DAG_NODES = DAG_NODES
    NODE_MAP = NODE_MAP
    DAG_SEQUENCE = DAG_SEQUENCE
    DELTA_DAG_ORDER = DELTA_DAG_ORDER
