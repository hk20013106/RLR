"""Shared tiny helpers: persona titles, timestamps, input-alias, everos scopes (Phase 2b-1 leaf).

Depends only on stdlib (datetime, re) -> pure leaf.
"""
import re
import datetime as _dt


PERSONA_TITLE = {
    "Linnaeus": "Catalog Master",
    "Einstein": "Conceptual Explorer",
    "Feynman": "Reality Checker",
    "Oppenheimer": "Cold Director",
    "Fisher": "Design Architect",
    "Tukey": "EDA Scout",
    "Turing": "Execution Engine",
    "Curie": "Evidence Auditor",
    "Darwin": "Evolutionary Biologist",
    "Jobs": "Story Strategist",
}

def _now():
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

def _stamp():
    return _dt.datetime.now().strftime("%Y%m%d%H%M%S%f")

def _input_alias(source_input):
    """Path-free alias for a source_input description: directory parts of any
    path-like token are dropped, keeping only file/basename + free text. Lets
    cognitive nodes see *what* the inputs are without the raw filesystem layout.
    """
    if not source_input:
        return ""
    return re.sub(r"\S*[\\/]\S*",
                  lambda m: re.split(r"[\\/]", m.group(0).rstrip("\\/"))[-1],
                  source_input)

def _everos_scopes_for(node_info, project_id):
    """Concrete EverOS read scopes for a node (declared, not enforced here)."""
    return [s.replace("<id>", project_id)
            for s in node_info.get("everos_read_scopes", [])]
