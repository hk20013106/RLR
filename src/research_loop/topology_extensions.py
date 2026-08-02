"""Runtime topology annotations for conditional routing and method selection."""
from __future__ import annotations


def install(topology_module) -> None:
    topology = topology_module
    if getattr(topology, "_METHOD_AND_SKIP_TOPOLOGY_INSTALLED", False):
        return
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
        "Generate testable hypotheses; after commit, route directly to L3 when "
        "there are four or fewer, otherwise route to L2 falsification"
    )
    nodes["L3"]["must"].append(
        "When a verified L2 skip receipt is present, independently triage the L1 "
        "hypotheses and explicitly acknowledge that no Feynman attack occurred"
    )
    nodes["L3"]["must_not"].append(
        "Treat an L2 skip as evidence that the hypotheses survived falsification"
    )

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
