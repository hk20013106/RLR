import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop import context
from research_loop import l0_contract
from research_loop import hypothesis_recall_context as recall_context
from research_loop.commands import research
from research_loop.hypothesis_ledger import LedgerError
from research_loop.preresearch import PRE_RESEARCH_MAP


def _write_candidate(project: Path, *, cand_id: str = "C1"):
    candidates = project / "01_Candidates"
    candidates.mkdir(parents=True, exist_ok=True)
    source_input = l0_contract.build_source_input(
        input_type="inline",
        description="declared synthetic source",
        fmt="text",
    )
    contract = l0_contract.build_initial_contract(
        cand_id,
        "7",
        "CANONICAL scientific question from L0",
        source_input,
        "CANONICAL current-round hypothesis from L0",
    )
    path, digest = l0_contract.write_contract(project, cand_id, contract)
    candidate = candidates / f"{cand_id}.md"
    candidate.write_text(
        "---\n"
        f"candidate_id: {cand_id}\n"
        "title: Deliberately drifted duplicate frontmatter\n"
        "question: WRONG frontmatter question\n"
        "claim: WRONG frontmatter claim\n"
        "round_type: initial\n"
        "round_id: '7'\n"
        f"input_contract_path: {path.relative_to(project).as_posix()}\n"
        f"input_contract_hash: {digest}\n"
        "---\n",
        encoding="utf-8",
    )
    return candidate, contract, digest


def test_l1_research_seed_is_a_projection_of_the_validated_l0_contract(tmp_path):
    project = tmp_path / "P"
    _candidate, _contract, digest = _write_candidate(project)

    module = importlib.import_module("research_loop.research_seed")
    seed = module.load_l1_research_seed(project, "C1")

    assert seed["schema_version"] == "L1ResearchSeed/v1"
    assert seed["scientific_question"] == "CANONICAL scientific question from L0"
    assert seed["hypothesis_seed"] == "CANONICAL current-round hypothesis from L0"
    assert seed["round_id"] == "7"
    assert seed["candidate_id"] == "C1"
    assert seed["l0_contract_sha256"] == digest
    assert "WRONG frontmatter" not in module.render_context_block(seed)


def test_l1_candidate_context_hides_duplicate_frontmatter_semantics(tmp_path):
    project = tmp_path / "P"
    candidate, _contract, _digest = _write_candidate(project)

    selector = getattr(context, "candidate_frontmatter_for_node", None)
    assert callable(selector), "L1 needs a node-aware candidate frontmatter boundary"
    l1_frontmatter = selector(candidate, "L1")

    assert "question" not in l1_frontmatter
    assert "claim" not in l1_frontmatter
    assert l1_frontmatter["candidate_id"] == "C1"


def test_l1_deep_research_uses_canonical_l0_seed_not_frontmatter(
    tmp_path, monkeypatch, capsys
):
    project = tmp_path / "P"
    _write_candidate(project)
    captured = {}

    monkeypatch.setattr(
        research,
        "_deep_research_spec_from_args",
        lambda _args: (SimpleNamespace(), "fixture"),
    )
    monkeypatch.setattr(research.deep_research, "host_matches", lambda *_a, **_k: (True, ""))
    monkeypatch.setattr(research.deep_research, "validate_spec_consistency", lambda _s: (True, ""))
    monkeypatch.setattr(research.deep_research, "runtime_ready", lambda _s: (True, ""))

    def fake_run_and_persist(*args, **kwargs):
        captured["question"] = args[3]
        captured["hypothesis"] = args[4]
        captured["round_id"] = kwargs["round_id"]
        return {"run_id": "R1", "status": "completed"}

    monkeypatch.setattr(research.deep_research, "run_and_persist", fake_run_and_persist)
    monkeypatch.setattr(research.deep_research, "audit_evidence_pack", lambda *_a, **_k: (True, ""))

    args = SimpleNamespace(
        project_dir=str(project),
        cand_id="C1",
        node="L1",
        l4a_manifest="",
        backend=None,
        executable=None,
        plugin_dir=None,
        model=None,
        timeout=None,
        skill_path=None,
        skill_version=None,
        allow_host_mismatch=True,
    )
    assert research.cmd_deep_research_run(args) == 0
    capsys.readouterr()

    assert captured == {
        "question": "CANONICAL scientific question from L0",
        "hypothesis": "CANONICAL current-round hypothesis from L0",
        "round_id": "7",
    }


def test_l1_auto_recall_uses_the_same_canonical_l0_seed(tmp_path, monkeypatch):
    project = tmp_path / "P"
    _candidate, _contract, _digest = _write_candidate(project)
    captured = {}

    def missing_recall(*_args, **_kwargs):
        raise LedgerError("missing")

    def fake_create_recall(_ledger, _project, _cand_id, _round_id, *, query_text):
        captured["query_text"] = query_text
        return {"schema_version": "HypothesisRecall/v1"}

    monkeypatch.setenv("RLR_AUTO_HYPOTHESIS_RECALL", "1")
    monkeypatch.setattr(recall_context, "load_recall", missing_recall)
    monkeypatch.setattr(recall_context, "create_recall", fake_create_recall)
    monkeypatch.setattr(recall_context, "validate_recall", lambda *_a, **_k: None)

    args = SimpleNamespace(project_dir=str(project), cand_id="C1")
    recall_context._load_bound_recall(
        args,
        object(),
        {"question": "WRONG frontmatter question", "claim": "WRONG frontmatter claim"},
        "7",
    )

    assert captured["query_text"] == (
        "CANONICAL scientific question from L0 "
        "CANONICAL current-round hypothesis from L0"
    )


def test_l1_pre_research_has_no_project_specific_seed_queries():
    config = PRE_RESEARCH_MAP["L1"]
    serialized = json.dumps(config, ensure_ascii=False).lower()

    assert config["queries"] == []
    for leaked_example in ("heart rate", "cardiac", "wgcna", "bat", "shrew"):
        assert leaked_example not in serialized
