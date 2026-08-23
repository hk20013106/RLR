"""Runtime topology annotations for conditional routing and method selection."""
from __future__ import annotations


def install(topology_module) -> None:
    topology = topology_module
    if getattr(topology, "_METHOD_AND_SKIP_TOPOLOGY_INSTALLED", False):
        return
    nodes = {item["node"]: item for item in topology.DAG_NODES}

    # Curie owns literature discovery for L1. Einstein consumes the frozen
    # evidence handoff and therefore receives no direct knowledge-base channel.
    # This explicit per-node policy wins over legacy fallback defaults applied
    # later by the engine via setdefault().
    nodes["L1"]["knowledge_base"] = "none"
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
        "Generate or recall testable hypotheses; label each as NEW, REACTIVATE, "
        "REVISE, or DERIVE. After commit, route directly to L3 when there are "
        "four or fewer, otherwise route to L2 falsification"
    )
    nodes["L1"]["must"].extend([
        "Inspect the bound historical-hypothesis recall before proposing L1 items",
        "Use REACTIVATE only for an unchanged recalled definition; use REVISE for "
        "a changed operationalization or falsification criterion within the same "
        "statement; use DERIVE when the statement changes",
        "Cite the recalled hypothesis and occurrence IDs, and provide an explicit "
        "reactivation basis whenever historical blockers or rejection exist",
    ])
    nodes["L1"]["must_not"].extend([
        "Silently copy a historical hypothesis as NEW or reuse a FALSIFIED "
        "hypothesis without formal reopening",
        "Access 09_Literature_Database directly; consume only the frozen Curie evidence supplied in context",
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
