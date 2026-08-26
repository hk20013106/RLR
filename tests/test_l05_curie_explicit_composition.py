"""Regression tests for Curie behavior without import-time installer mutation."""

import os
import subprocess
import sys
from pathlib import Path


SRC = str(Path(__file__).resolve().parents[1] / "src")


def _fresh(code: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
    )


_BLOCK_INSTALLER_TEMPLATE = r'''
import importlib.abc
import importlib.util
import sys
import types


class _BlockOptionalInstallers(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    _names = __NAMES__

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self._names:
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        module = types.ModuleType(spec.name)
        module.install = self._unexpected_install
        return module

    def exec_module(self, module):
        return None

    @staticmethod
    def _unexpected_install(*args, **kwargs):
        raise AssertionError("optional Curie installer was imported and called")


sys.meta_path.insert(0, _BlockOptionalInstallers())
'''


def _block_installers(*names: str) -> str:
    return _BLOCK_INSTALLER_TEMPLATE.replace("__NAMES__", repr(set(names)))


def test_store_owns_semantic_admission_without_installer():
    proc = _fresh(
        _block_installers("research_loop.l05_curie.semantic_pack")
        + """
import inspect
from research_loop.l05_curie import store

assert "semantic_verifications" in inspect.signature(
    store.build_evidence_pack
).parameters
assert store.build_evidence_pack.__module__ == "research_loop.l05_curie.store"
"""
    )
    assert proc.returncode == 0, proc.stderr


def test_multisource_owns_query_lineage_without_installer():
    proc = _fresh(
        _block_installers("research_loop.l05_curie.provenance_hardening")
        + """
from research_loop.l05_curie.multisource import (
    build_multisource_query_plan,
    run_multisource_discovery,
)
import research_loop.l05_curie.multisource as multisource
from research_loop.l05_curie import DISCOVERY_BATCH_SCHEMA_VERSION
from research_loop.l05_curie import DISCOVERY_TRANSPORT_SCHEMA_VERSION

assert not hasattr(multisource, "_record_matches")


seed = {
    "candidate_id": "C001",
    "round_id": "1",
    "scientific_question": "question",
    "hypothesis_seed": "hypothesis",
}
plan = build_multisource_query_plan(
    seed,
    seed_sha256="a" * 64,
    explicit_queries=["first query"],
    providers=["pubmed"],
)


class Transport:
    def handshake(self):
        return {
            "schema_version": DISCOVERY_TRANSPORT_SCHEMA_VERSION,
            "provider": "pubmed",
            "capabilities": ["search:test"],
        }

    def search(self, request):
        return {
            "schema_version": DISCOVERY_BATCH_SCHEMA_VERSION,
            "provider": "pubmed",
            "query_id": request["query_id"],
            "receipt": {
                "request_sha256": "1" * 64,
                "response_sha256": "2" * 64,
            },
            "records": [{
                "paper_id": "P1",
                "title": "Paper",
                "identifiers": {"pmid": "123"},
                "metadata": {},
                "provenance": {
                    "provider": "pubmed",
                    "raw_record_sha256": "3" * 64,
                    "originating_query_ids": ["FORGED"],
                },
            }],
        }


result = run_multisource_discovery(plan, {"pubmed": Transport()})
assert result["records"][0]["provenance"]["originating_query_ids"] == ["Q001"]
"""
    )
    assert proc.returncode == 0, proc.stderr


def test_multisource_binds_each_batch_to_the_current_query_and_provider():
    proc = _fresh(
        _block_installers("research_loop.l05_curie.provenance_hardening")
        + """
from research_loop.l05_curie import CurieContractError
from research_loop.l05_curie import DISCOVERY_BATCH_SCHEMA_VERSION
from research_loop.l05_curie import DISCOVERY_TRANSPORT_SCHEMA_VERSION
from research_loop.l05_curie.multisource import (
    build_multisource_query_plan,
    run_multisource_discovery,
)

seed = {
    "candidate_id": "C001",
    "round_id": "1",
    "scientific_question": "question",
    "hypothesis_seed": "hypothesis",
}
plan = build_multisource_query_plan(
    seed,
    seed_sha256="a" * 64,
    explicit_queries=["first query", "second query"],
    providers=["pubmed"],
)


class Transport:
    def handshake(self):
        return {
            "schema_version": DISCOVERY_TRANSPORT_SCHEMA_VERSION,
            "provider": "pubmed",
            "capabilities": ["search:test"],
        }

    def search(self, request):
        return {
            "schema_version": DISCOVERY_BATCH_SCHEMA_VERSION,
            "provider": "other-provider",
            "query_id": "Q001",
            "receipt": {
                "request_sha256": "1" * 64,
                "response_sha256": "2" * 64,
            },
            "records": [{
                "paper_id": "P1",
                "title": "Paper",
                "identifiers": {"pmid": "123"},
                "metadata": {},
                "provenance": {
                    "provider": "other-provider",
                    "raw_record_sha256": "3" * 64,
                },
            }],
        }


try:
    run_multisource_discovery(plan, {"pubmed": Transport()})
except CurieContractError:
    pass
else:
    raise AssertionError("discovery must bind returned batch to current query/provider")
"""
    )
    assert proc.returncode == 0, proc.stderr


def test_multisource_rejects_a_batch_from_another_query():
    proc = _fresh(
        _block_installers("research_loop.l05_curie.provenance_hardening")
        + """
from research_loop.l05_curie import CurieContractError
from research_loop.l05_curie import DISCOVERY_BATCH_SCHEMA_VERSION
from research_loop.l05_curie import DISCOVERY_TRANSPORT_SCHEMA_VERSION
from research_loop.l05_curie.multisource import (
    build_multisource_query_plan,
    run_multisource_discovery,
)

seed = {
    "candidate_id": "C001",
    "round_id": "1",
    "scientific_question": "question",
    "hypothesis_seed": "hypothesis",
}
plan = build_multisource_query_plan(
    seed,
    seed_sha256="a" * 64,
    explicit_queries=["first query", "second query"],
    providers=["pubmed"],
)


class Transport:
    def handshake(self):
        return {
            "schema_version": DISCOVERY_TRANSPORT_SCHEMA_VERSION,
            "provider": "pubmed",
            "capabilities": ["search:test"],
        }

    def search(self, request):
        return {
            "schema_version": DISCOVERY_BATCH_SCHEMA_VERSION,
            "provider": "pubmed",
            "query_id": "Q001",
            "receipt": {
                "request_sha256": "1" * 64,
                "response_sha256": "2" * 64,
            },
            "records": [{
                "paper_id": "P1",
                "title": "Paper",
                "identifiers": {"pmid": "123"},
                "metadata": {},
                "provenance": {
                    "provider": "pubmed",
                    "raw_record_sha256": "3" * 64,
                },
            }],
        }


try:
    run_multisource_discovery(plan, {"pubmed": Transport()})
except CurieContractError:
    pass
else:
    raise AssertionError("discovery must bind each batch to its current query")
"""
    )
    assert proc.returncode == 0, proc.stderr


def test_selector_requires_query_lineage_without_installer():
    proc = _fresh(
        _block_installers("research_loop.l05_curie.provenance_hardening")
        + """
from research_loop import l05_curie
from research_loop.l05_curie.selector import select_candidates


try:
    select_candidates(
        [{
            "paper_id": "P1",
            "title": "Paper",
            "identifiers": {"pmid": "123"},
            "metadata": {},
            "provenance": {"provider": "pubmed"},
        }],
        seed={"scientific_question": "q", "hypothesis_seed": "h"},
        scorer=lambda _record, _seed: {
            "relevance": 0.5,
            "directness": 0.5,
            "methodological_value": 0.5,
            "contradiction_value": 0.5,
            "evidence_diversity": 0.5,
            "reason": "fixture",
        },
        eligibility=lambda _record: (True, "OK"),
    )
except l05_curie.CurieContractError:
    pass
else:
    raise AssertionError("selector accepted a record without query provenance")
"""
    )
    assert proc.returncode == 0, proc.stderr


def test_historical_curie_installers_are_explicit_noop_facades():
    proc = _fresh(
        """
from research_loop.l05_curie.provenance_hardening import install as install_provenance
from research_loop.l05_curie.semantic_pack import install as install_semantic

assert install_provenance() is None
assert install_semantic() is None
"""
    )
    assert proc.returncode == 0, proc.stderr
