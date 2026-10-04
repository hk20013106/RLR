"""Regression tests for the PaperQA2 bridge's strict UTF-8 boundary."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import asyncio
import types

import pytest


def _bridge_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "paperqa2_rlr_bridge.py"
    spec = importlib.util.spec_from_file_location("paperqa2_rlr_bridge", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_bridge_drops_lone_surrogate_before_strict_json_transport():
    bridge = _bridge_module()

    assert bridge._utf8_transport_text("valid UTF-8") == "valid UTF-8"
    assert bridge._utf8_transport_text("bad\ud800hit") is None

    safe = bridge._utf8_transport_text("valid UTF-8")
    encoded = json.dumps({"text": safe}, ensure_ascii=False).encode("utf-8")
    assert encoded == b'{"text": "valid UTF-8"}'


@pytest.mark.parametrize("payload,expected", [
    ('{"worker_mode":"corpus-evidence-v1","question":"é 中文","project_root":"C:/语料"}'.encode("utf-8"),
     {"worker_mode": "corpus-evidence-v1", "question": "é 中文", "project_root": "C:/语料"}),
    (b'{"worker_mode":"corpus-evidence-v1","question":"\xd6\xd0"}', None),
])
def test_actual_bridge_main_uses_strict_utf8_stdin(payload, expected):
    """Exercise the transport entry point without invoking a native model."""
    bridge_path = Path(__file__).resolve().parents[1] / "scripts" / "paperqa2_rlr_bridge.py"
    script = """import importlib.util, sys
spec = importlib.util.spec_from_file_location('bridge', sys.argv[1])
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
async def echo(request):
    return request
bridge._run = echo
bridge.main()
"""
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONIOENCODING", None)
    # Reproduce Windows' default pipe encoding even on a UTF-8-default host.
    env["PYTHONUTF8"] = "0"
    env["PYTHONIOENCODING"] = "gbk:strict"
    process = subprocess.run([sys.executable, "-c", script, str(bridge_path)],
                             input=payload, capture_output=True, env=env, timeout=20)
    if expected is None:
        assert process.returncode != 0
        assert not process.stdout
    else:
        assert process.returncode == 0, process.stderr
        assert json.loads(process.stdout.decode("utf-8")) == expected


def _search_query_bridge(monkeypatch, tmp_path):
    bridge = _bridge_module()
    repo = tmp_path / "paperqa-repo"
    module_path = repo / "src" / "paperqa" / "agents" / "helpers.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# pinned helper fixture\n", encoding="utf-8")
    home = tmp_path / "pqa-home"
    home.mkdir()
    model = object()
    calls = []

    class Settings:
        def __init__(self, **kwargs):
            self.summary_llm = kwargs["summary_llm"]
            self.values = kwargs

        def get_summary_llm(self):
            return model

    paperqa = types.ModuleType("paperqa")
    paperqa.__version__ = "2026.8.12"
    paperqa.__file__ = str(repo / "src" / "paperqa" / "__init__.py")
    paperqa.Settings = Settings
    agents = types.ModuleType("paperqa.agents")
    helpers = types.ModuleType("paperqa.agents.helpers")
    helpers.__file__ = str(module_path)

    async def generate(question, count, *, template, llm):
        calls.append((question, count, template, llm))
        return ["broad evidence", "narrow evidence"]

    helpers.litellm_get_search_query = generate
    helpers.get_year = lambda: "2026"
    monkeypatch.setitem(sys.modules, "paperqa", paperqa)
    monkeypatch.setitem(sys.modules, "paperqa.agents", agents)
    monkeypatch.setitem(sys.modules, "paperqa.agents.helpers", helpers)
    monkeypatch.setattr(bridge, "_git", lambda _repo, *args: {
        ("rev-parse", "HEAD"): "57e89f7223b0960d5ee5ea048c69e3c47e088572",
        ("describe", "--tags", "--exact-match", "HEAD"): "v2026.08.12",
        ("status", "--porcelain"): "",
    }[args])
    expected = {
        "package": "paper-qa", "version": "2026.8.12",
        "upstream_tag": "v2026.08.12",
        "upstream_commit": "57e89f7223b0960d5ee5ea048c69e3c47e088572",
        "module_path": str(module_path.resolve()), "clean_checkout": True,
        "llm_model": "test-provider/test-model",
    }
    settings = {"embedding": "unused-local-model", "summary_llm": expected["llm_model"],
                "embedding_config": {}, "summary_llm_config": {}}
    request = {"worker_mode": "search-query-v1", "question": "full frozen claim",
               "count": 3, "settings": settings, "paperqa_repo": str(repo),
               "pqa_home": str(home), "expected_runtime": expected}
    monkeypatch.setenv("PQA_HOME", str(tmp_path / "prior-home"))
    return bridge, request, calls, model, expected, module_path


def test_search_query_operation_calls_pinned_helper_once_with_explicit_settings_model(monkeypatch, tmp_path):
    bridge, request, calls, model, expected, module_path = _search_query_bridge(monkeypatch, tmp_path)
    run = getattr(bridge, "_run_search_queries", None)
    assert callable(run), "missing planned PaperQA2 keyword operation"

    result = asyncio.run(run(request))

    assert calls == [("full frozen claim", 3, None, model)]
    assert set(result) == {"proposals", "runtime"}
    assert result["proposals"] == ["broad evidence", "narrow evidence"]
    assert result["runtime"] == {**expected, "generation_year": 2026}
    assert type(result["runtime"]["generation_year"]) is int


@pytest.mark.parametrize("change", ["count", "model"])
def test_search_query_bridge_rejects_bad_request_before_helper(monkeypatch, tmp_path, change):
    bridge, request, calls, _model, _expected, _module_path = _search_query_bridge(monkeypatch, tmp_path)
    run = getattr(bridge, "_run_search_queries", None)
    assert callable(run), "missing planned PaperQA2 keyword operation"
    if change == "count":
        request["count"] = 1
    else:
        request["expected_runtime"]["llm_model"] = "different/model"

    with pytest.raises(ValueError):
        asyncio.run(run(request))

    assert calls == []


def test_search_query_backend_uses_bound_interpreter_and_inherits_environment(monkeypatch, tmp_path):
    from research_loop.l05_curie.paperqa2_runtime import PaperQA2SubprocessBackend
    from research_loop.process_runner import ProcessResult

    repo = tmp_path / "paperqa-repo"
    repo.mkdir()
    home = tmp_path / "pqa-home"
    script = tmp_path / "controlled_bridge.py"
    script.write_text(
        "import json, os, sys\n"
        "request=json.loads(sys.stdin.buffer.read().decode('utf-8'))\n"
        "sys.stderr.write('SYNTHETIC_CREDENTIAL=' + ('AVAILABLE' if os.getenv('SYNTHETIC_CREDENTIAL') == 'sentinel' else 'MISSING') + '\\n')\n"
        "sys.stderr.write('BOUND_INTERPRETER=' + sys.executable + '\\n')\n"
        "runtime={**request['expected_runtime'], 'module_path': request['expected_runtime']['module_path'], 'clean_checkout': True, 'generation_year': 2026}\n"
        "print(json.dumps({'proposals':['broad query'], 'runtime':runtime}, separators=(',',':')))\n",
        encoding="utf-8",
    )
    expected = {
        "package": "paper-qa", "version": "2026.8.12",
        "upstream_tag": "v2026.08.12",
        "upstream_commit": "57e89f7223b0960d5ee5ea048c69e3c47e088572",
        "llm_model": "test-provider/test-model",
        "module_path": str(repo / "src" / "paperqa" / "agents" / "helpers.py"),
        "clean_checkout": True,
    }
    settings = {
        "embedding": "not-used", "summary_llm": expected["llm_model"],
        "embedding_config": {}, "summary_llm_config": {},
        "answer": {"evidence_k": 60, "evidence_retrieval": True,
                   "evidence_skip_summary": False, "evidence_text_only_fallback": False,
                   "max_concurrent_requests": 4},
        "parsing": {"use_doc_details": False, "multimodal": False,
                    "doc_filters": [], "defer_embedding": False},
        "texts_index_mmr_lambda": 1.0,
    }
    monkeypatch.setenv("SYNTHETIC_CREDENTIAL", "sentinel")
    backend = PaperQA2SubprocessBackend(
        python_executable=sys.executable, bridge_script=script, paperqa_repo=repo,
        pqa_home=home, timeout_seconds=10,
    )

    process, result = backend.execute_search_queries(
        question="frozen claim", count=3, settings=settings, expected_runtime=expected,
    )

    assert isinstance(process, ProcessResult)
    assert process.terminal_state == "completed" and process.returncode == 0
    assert result["proposals"] == ["broad query"]
    assert "SYNTHETIC_CREDENTIAL=AVAILABLE" in process.stderr
    assert f"BOUND_INTERPRETER={Path(sys.executable).resolve()}" in process.stderr
