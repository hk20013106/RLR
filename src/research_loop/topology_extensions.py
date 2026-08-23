"""Runtime topology annotations for research, conditional routing, and methods."""
from __future__ import annotations


def _install_l0_5(topology) -> None:
    if any(item.get("node") == "L0.5" for item in topology.DAG_NODES):
        return

    l05 = {
        "node": "L0.5",
        "persona": "Curie",
        "status_before": "IDEA_PROPOSED",
        "advance_command": None,
        "context_inputs": ["L0"],
        "is_parallel": False,
        "is_execution": False,
        "node_kind": "research",
        "research_required": True,
        "research_persona": "Curie",
        "pre_research": "deep_research",
        "tools_policy": "research",
        "knowledge_base": "read-write",
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
    }
    l1_index = next(
        index for index, item in enumerate(topology.DAG_NODES)
        if item.get("node") == "L1"
    )
    topology.DAG_NODES.insert(l1_index, l05)
    topology.NODE_MAP = {item["node"]: item for item in topology.DAG_NODES}

    if "L0.5" not in topology.DAG_SEQUENCE:
        topology.DAG_SEQUENCE.insert(topology.DAG_SEQUENCE.index("L1"), "L0.5")

    l1 = topology.NODE_MAP["L1"]
    for key in ("pre_research", "research_required", "research_persona"):
        l1.pop(key, None)

    # DAGTopology is a read-only namespace over the live module globals. Refresh
    # references when the extension replaces NODE_MAP or mutates the sequence.
    topology.DAGTopology.DAG_NODES = topology.DAG_NODES
    topology.DAGTopology.NODE_MAP = topology.NODE_MAP
    topology.DAGTopology.DAG_SEQUENCE = topology.DAG_SEQUENCE


def install(topology_module) -> None:
    topology = topology_module
    if getattr(topology, "_METHOD_AND_SKIP_TOPOLOGY_INSTALLED", False):
        return

    _install_l0_5(topology)
    nodes = {item["node"]: item for item in topology.DAG_NODES}

    nodes["L1"]["conditional_routes"] = [
        {
            "condition": "1 <= committed_unique_hypothesis_count <= 4",
            "route_to": "L3",
            "skip": "L2",
            "audit_receipt": "08_Audit/node_skips/<candidate_id>_L2.json",
        },
        {
            "condition": "committed_unique_hypothesis_count >= 5",
            "route_to": "L2",
        },
    ]
    nodes["L1"]["action_hint"] = (
        "Generate or recall testable hypotheses from the frozen L0.5 evidence; "
        "label each as NEW, REACTIVATE, REVISE, or DERIVE. After commit, route "
        "directly to L3 when there are four or fewer, otherwise route to L2 falsification"
    )
    nodes["L1"]["must"].extend([
        "Inspect the bound historical-hypothesis recall before proposing L1 items",
        "Use REACTIVATE only for an unchanged recalled definition; use REVISE for "
        "a changed operationalization or falsification criterion within the same "
        "statement; use DERIVE when the statement changes",
        "Cite the recalled hypothesis and occurrence IDs, and provide an explicit "
        "reactivation basis whenever historical blockers or rejection exist",
        "Reason only over the exact frozen L0.5 EvidencePack bound to the current ResearchSeed",
    ])
    nodes["L1"]["must_not"].extend([
        "Silently copy a historical hypothesis as NEW or reuse a FALSIFIED "
        "hypothesis without formal reopening",
        "Access 09_Literature_Database directly; consume only the frozen Curie evidence supplied in context",
        "Run independent literature searches or replace the L0.5 evidence corpus",
    ])
    nodes["L3"]["must"].extend([
        "When a verified L2 skip receipt is present, independently triage the L1 "
        "hypotheses and explicitly acknowledge that no Feynman attack occurred",
        "For every REACTIVATE, REVISE, or DERIVE item, review every historical "
        "blocking event and record RESOLVED, PARTIALLY_RESOLVED, or UNRESOLVED",
        "Attach explicit QC, stop-rule, or data obligations before selecting a "
        "partially resolved historical hypothesis",
    ])
    nodes["L3"]["must_not"].extend([
        "Treat an L2 skip as evidence that the hypotheses survived falsification",
        "Select an historical hypothesis whose prior blockers remain UNRESOLVED",
    ])

    nodes["L4"]["action_hint"] = (
        "Build an evidence-backed method candidate catalog for every required "
        "component; do not select the final method"
    )
    nodes["L4"]["must"].extend([
        "Describe every serious method candidate by stable method_id, applicable "
        "input, steps, assumptions, outputs, strengths, limitations, alternatives, "
        "and method-anchor IDs",
        "Identify source-blocked candidates and provide the exact user-PDF import command",
    ])
    nodes["L5"]["action_hint"] = (
        "Critique every eligible L4 candidate by method_id from an EDA/QC perspective"
    )
    nodes["L5"]["must"].append(
        "Return one explicit ACCEPT/MODIFY/REJECT critique for every eligible method_id"
    )
    nodes["L6"]["action_hint"] = (
        "Select the final method or combined strategy for every required component"
    )
    nodes["L6"]["must"].append(
        "Record selected method IDs, rejected alternatives, parameters, software, "
        "scripts, anchor IDs, and L5 QC obligations"
    )

    topology._METHOD_AND_SKIP_TOPOLOGY_INSTALLED = True
