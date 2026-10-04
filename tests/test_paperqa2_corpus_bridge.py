"""Bridge boundary tests; native computational proof is the separate offline driver."""
import asyncio
import copy
import hashlib
import io
import json
import logging
import sys
from types import SimpleNamespace

import pytest

from test_l05_curie_corpus_contracts import CORPUS, SETTINGS, task_fixture, wire_bytes
from test_paperqa2_bridge_transport import _bridge_module


def install_worker(monkeypatch, tmp_path, *, outcome="normal"):
    bridge = _bridge_module()
    project = tmp_path / "project"; project.mkdir()
    repo = tmp_path / "repo"; (repo / "src" / "paperqa").mkdir(parents=True)
    raw = b'<article><body><p>source</p></body></article>'
    (project / "snapshots").mkdir(); (project / "snapshots" / "p1.xml").write_bytes(raw)
    task = task_fixture()
    task["corpus"][0]["document_sha256"] = hashlib.sha256(raw).hexdigest()
    request = {"worker_mode": "corpus-evidence-v1", "task": task, "settings": copy.deepcopy(SETTINGS),
               "project_root": str(project), "paperqa_repo": str(repo), "pqa_home": str(tmp_path)}
    calls = []
    class FakeContextError(ValueError): pass
    class NativeValue:
        def __init__(self, **values): self.__dict__.update(values)
    class Settings:
        def __init__(self, **values):
            self.__dict__.update(values)
            self.answer = SimpleNamespace(**values["answer"])
            self.parsing = SimpleNamespace(**values["parsing"])
    class Docs:
        def __init__(self): self.docs = {}; self.texts = []
        async def aadd_texts(self, texts, doc, settings):
            calls.append("aadd_texts")
            if outcome == "ingestion_false": return False
            self.docs[doc.dockey] = doc; self.texts.extend(texts)
            if outcome == "count_mismatch": self.texts.append(texts[0])
            return True
        async def aget_evidence(self, question, *, settings):
            calls.append("aget_evidence")
            assert question == request["task"]["question"]
            text = self.texts[0]
            assert text.doc.dockey == text.doc.docname == "P1"
            assert text.source_locator == "sec:1/p:1" and text.section == "Methods"
            text.name = "arbitrary-label-without-a-locator"
            context = SimpleNamespace(text=text, score=5, context="AUDIT_ONLY_SUMMARY")
            if outcome == "terminal":
                try: raise FakeContextError("terminal")
                except FakeContextError: logging.getLogger("paperqa.core").exception("native terminal")
            if outcome == "empty": return SimpleNamespace(contexts=[])
            if outcome == "surrogate": text.text = "\ud800"
            if outcome == "duplicate_conflict": return SimpleNamespace(contexts=[context, SimpleNamespace(text=text, score=6, context="other")])
            return SimpleNamespace(contexts=[context])
        def __getattr__(self, name): raise AssertionError(f"forbidden manual pipeline: {name}")
    paperqa = SimpleNamespace(Docs=Docs, Settings=Settings, __version__="2026.8.12",
                             __file__=str(repo / "src" / "paperqa" / "__init__.py"))
    monkeypatch.setitem(sys.modules, "paperqa", paperqa)
    monkeypatch.setitem(sys.modules, "paperqa.types", SimpleNamespace(Doc=NativeValue, Text=NativeValue))
    monkeypatch.setitem(sys.modules, "paperqa.core", SimpleNamespace(LLMContextError=FakeContextError))
    def git(repo, *args):
        if args == ("rev-parse", "HEAD"): return "57e89f7223b0960d5ee5ea048c69e3c47e088572"
        if args[:1] == ("describe",): return "v2026.08.12"
        if args[:1] == ("status",): return ""
        raise AssertionError(args)
    monkeypatch.setattr(bridge, "_git", git)
    return bridge, request, calls


def require_corpus(bridge):
    assert callable(getattr(bridge, "_run_corpus", None)), "missing native corpus worker boundary"


def test_native_source_identity_survives_context(monkeypatch, tmp_path, capsys):
    bridge, request, calls = install_worker(monkeypatch, tmp_path)
    require_corpus(bridge)
    result = asyncio.run(bridge._run(request))
    assert result["evidence"] == [{"paper_id": "P1", "source_locator": "sec:1/p:1",
                                   "source_text": CORPUS[0]["source_units"][0]["source_text"],
                                   "relevance_score": 5, "contextual_summary": "AUDIT_ONLY_SUMMARY"}]
    assert result["task_sha256"] == hashlib.sha256(wire_bytes(request["task"])).hexdigest()
    diagnostic = json.loads(capsys.readouterr().err)["paperqa2_corpus_diagnostic"]
    assert diagnostic["capture_established"] is True and diagnostic["terminal_context_error_count"] == 0


def test_one_native_aget_evidence_no_manual_pipeline(monkeypatch, tmp_path):
    bridge, request, calls = install_worker(monkeypatch, tmp_path)
    require_corpus(bridge)
    asyncio.run(bridge._run(request))
    assert calls == ["aadd_texts", "aget_evidence"]


@pytest.mark.parametrize("outcome", ["empty", "terminal", "ingestion_false", "count_mismatch", "surrogate", "duplicate_conflict"])
def test_empty_context_vs_terminal_failure(monkeypatch, tmp_path, capsys, outcome):
    bridge, request, calls = install_worker(monkeypatch, tmp_path, outcome=outcome)
    require_corpus(bridge)
    if outcome == "empty":
        assert asyncio.run(bridge._run(request))["evidence"] == []
    else:
        with pytest.raises(ValueError): asyncio.run(bridge._run(request))
    frame = json.loads(capsys.readouterr().err)["paperqa2_corpus_diagnostic"]
    assert frame["terminal_context_error_count"] == (1 if outcome == "terminal" else 0)


@pytest.mark.parametrize("raw", [
    '{"worker_mode":"corpus-evidence-v1","worker_mode":"corpus-evidence-v1"}',
    '{"worker_mode":"corpus-evidence-v1","task":{"question":"x","question":"x"}}',
    '{"worker_mode":"corpus-evidence-v1","settings":{"embedding":"x","embedding":"x"}}',
    r'{"worker_mode":"corpus-evidence-v1","task":{"question":"x","\u0071uestion":"x"}}',
    '{"worker_mode":"corpus-evidence-v1","task":{"budget":{"evidence_k":NaN}}}',
])
def test_raw_stdin_rejects_duplicate_json_keys(monkeypatch, raw):
    bridge = _bridge_module()
    require_corpus(bridge)
    calls = []
    async def forbidden(request): calls.append(request); raise AssertionError("must not dispatch")
    monkeypatch.setattr(bridge, "_run_corpus", forbidden)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw.encode("utf-8")), encoding="gbk"))
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="utf-8"))
    with pytest.raises(ValueError): bridge.main()
    assert calls == []


def test_capture_failure_blocks_instead_of_reporting_zero(monkeypatch, tmp_path, capsys):
    bridge, request, calls = install_worker(monkeypatch, tmp_path)
    require_corpus(bridge)
    def broken(*args, **kwargs): raise RuntimeError("capture could not be established")
    monkeypatch.setattr(logging.getLogger("paperqa.core"), "addHandler", broken)
    with pytest.raises((ValueError, RuntimeError)): asyncio.run(bridge._run(request))
    assert calls == []
    frame = json.loads(capsys.readouterr().err)["paperqa2_corpus_diagnostic"]
    assert frame["capture_established"] is False and frame["capture_failed"] is True
