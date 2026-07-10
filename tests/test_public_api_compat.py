"""Phase 0 safety net: public-symbol export contract for research_loop_v04.

Rev-2 C-C1/C5 (Codex): before ANY module extraction, pin exactly which names
`research_loop_v04` must keep exporting. Phases 2-4 move these constants/helpers
into research_loop/* and re-export them from the old module; this test fails the
instant a re-export is dropped, so a "runnable after every phase" guarantee is
actually enforced rather than assumed.

Grounded: every symbol asserted here was grep-confirmed present in
research_loop_v04.py at v0.6 (branch v0.7-migration baseline, 108 tests green).
Do not add speculative symbols — only ones that exist today and that a
downstream module (run_loop.py, tests, external importers) actually relies on.
"""
import importlib

import pytest

rl = importlib.import_module("research_loop_v04")


# Constants that Phases 2-4 relocate into research_loop.{topology,delta} and
# must re-export. run_loop.py and the test suite import several of these.
REQUIRED_CONSTANTS = [
    "AGENTS",
    "PERSONA_TITLE",
    "VALID_STATUSES",
    "DECISION_TRANSITIONS",
    "DAG_NODES",
    "NODE_MAP",
    "DAG_SEQUENCE",
    "DELTA_SCHEMAS",
    "DELTA_PERSONA",
    "DELTA_DAG_ORDER",
    "PRE_RESEARCH_MAP",
]

# Error type (Phase 3 moves to research_loop.errors, re-exported).
REQUIRED_TYPES = ["RLRError"]

# CLI entry + a representative sample of command handlers that cli.py will host
# (Phase 5). If the shim ever stops exposing main(), the CLI compat breaks.
REQUIRED_CALLABLES = [
    "main",
    "cmd_next_step",
    "cmd_assemble_context",
    "cmd_emit_delta",
    "cmd_decision",
    "cmd_emit_loop_memory",
    "cmd_aggregate_report",
]


@pytest.mark.parametrize("name", REQUIRED_CONSTANTS)
def test_constant_exported(name):
    assert hasattr(rl, name), f"research_loop_v04 must export constant {name!r}"


@pytest.mark.parametrize("name", REQUIRED_TYPES)
def test_type_exported(name):
    assert hasattr(rl, name), f"research_loop_v04 must export type {name!r}"
    assert isinstance(getattr(rl, name), type)


@pytest.mark.parametrize("name", REQUIRED_CALLABLES)
def test_callable_exported(name):
    obj = getattr(rl, name, None)
    assert callable(obj), f"research_loop_v04 must export callable {name!r}"


def test_topology_shapes_stable():
    """Lock the load-bearing shapes so an extraction cannot silently drop nodes."""
    assert len(rl.DAG_NODES) == len(rl.NODE_MAP)
    assert rl.DAG_SEQUENCE[0] == "L0"
    assert rl.DAG_SEQUENCE[-1] == "L10c"
    assert set(rl.AGENTS) >= {
        "Linnaeus", "Einstein", "Feynman", "Oppenheimer", "Fisher",
        "Tukey", "Turing", "Curie", "Darwin", "Jobs",
    }
