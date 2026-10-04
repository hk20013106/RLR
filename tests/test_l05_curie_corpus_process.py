"""Real controlled subprocesses exercise the corpus transport boundary offline."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from research_loop.l05_curie import contracts, paperqa2_runtime as runtime
from test_l05_curie_corpus_contracts import api, SETTINGS, identify, task_fixture


CHILD = '''import hashlib,json,pathlib,sys,time
r=json.loads(sys.stdin.buffer.read().decode('utf-8')); t=r['task']; s=r['settings']; mode=MODE
pathlib.Path(r['project_root'],'child-called').write_text('called')
if mode == 'timeout': time.sleep(3)
def enc(x): return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\\n').encode('utf-8')
e=[{'paper_id':p['paper_id'],'source_locator':u['source_locator'],'source_text':u['source_text'],'relevance_score':5} for p in t['corpus'] for u in p['source_units']]
result={'schema_version':'PaperQA2CorpusResult/v1','task_id':t['task_id'],'task_sha256':hashlib.sha256(enc(t)).hexdigest(),
'runtime':{'package':'paper-qa','version':'2026.8.12','upstream_commit':'57e89f7223b0960d5ee5ea048c69e3c47e088572','upstream_tag':'v2026.08.12','embedding_model':s['embedding'],'summary_llm_model':s['summary_llm'],'settings_sha256':t['settings_sha256']},
'execution':{'status':'COMPLETE','ingested_paper_count':len(t['corpus']),'ingested_text_count':len(e),'terminal_context_error_count':0},'evidence':e[:1] if mode=='one-context' else e[:t['budget']['evidence_k']]}
raw=enc(result)
if mode.startswith('duplicate'):
 if mode=='duplicate-top': raw=raw.replace(b'{',b'{"task_id":"'+t['task_id'].encode()+b'",',1)
 elif mode=='duplicate-nested': raw=raw.replace(b'"relevance_score":5',b'"relevance_score":5,"relevance_score":5',1)
 else: raw=raw.replace(b'"package":"paper-qa"',b'"package":"paper-qa","\\\\u0070ackage":"paper-qa"',1)
sys.stdout.buffer.write(raw); sys.stdout.buffer.flush()
frame={'paperqa2_corpus_diagnostic':{'task_id':t['task_id'],'capture_established':True,'capture_failed':False,'terminal_context_error_count':1 if mode=='terminal' else 0}}
if mode=='wrong': frame['paperqa2_corpus_diagnostic']['task_id']='wrong'
if mode!='missing':
 sys.stderr.buffer.write(enc(frame))
 if mode=='duplicate-diagnostic': sys.stderr.buffer.write(enc(frame))
sys.stderr.buffer.flush()
if mode=='malformed-diagnostic':
 sys.stderr.buffer.write(b'{"paperqa2_corpus_diagnostic":bad}\\n'); sys.stderr.buffer.flush()
if mode=='nonzero': sys.exit(4)
'''


def setup(tmp_path, *, mode="normal", long=False, prefix=""):
    project = tmp_path / "project"; project.mkdir()
    repo = tmp_path / "repo"; repo.mkdir()
    home = tmp_path / "home"; home.mkdir()
    script = tmp_path / "child.py"; script.write_text(CHILD.replace("MODE", repr(mode)), encoding="utf-8")
    task = task_fixture()
    unit = task["corpus"][0]["source_units"][0]
    text = prefix + ("中文完整段落" * 1000 if long else "Entire original paragraph.")
    units = [{**unit, "source_locator": f"sec:1/p:{i+1}", "source_text": text} for i in range(60 if long else 1)]
    raw = ("<article><body><sec><title>Methods</title>" + "".join("<p>"+text+"</p>" for _ in units) + "</sec></body></article>").encode()
    path = project / task["corpus"][0]["document_path"]; path.parent.mkdir(); path.write_bytes(raw)
    task["corpus"][0].update(document_sha256=hashlib.sha256(raw).hexdigest(), source_units=units)
    identify(task)
    backend = runtime.PaperQA2SubprocessBackend(python_executable=sys.executable, bridge_script=script,
        paperqa_repo=repo, pqa_home=home, timeout_seconds=1 if mode=="timeout" else 5)
    return project, backend, task, project / "worker"


def execute(project, backend, task, worker):
    return api(backend, "execute_corpus")(project_dir=project, task=task, settings=copy.deepcopy(SETTINGS),
        worker_dir=worker, acquisition_run_id="run-1", attempt_index=1)


@pytest.mark.parametrize("prefix", ["", "a", "aa"])
def test_stdout_over_256k_uses_full_spooled_json(tmp_path, prefix):
    project, backend, task, worker = setup(tmp_path, long=True, prefix=prefix)
    result = execute(project, backend, task, worker)
    completion = result["completion"]
    assert completion["stdout"]["truncated"] is True
    raw = (project / completion["stdout"]["path"]).read_bytes()
    assert len(raw) > 256 * 1024
    assert completion["stdout"]["byte_count"] == len(raw)
    assert completion["stdout"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert len(result["result"]["evidence"]) == 60
    assert result["result"]["evidence"][0]["source_text"] == task["corpus"][0]["source_units"][0]["source_text"]
    assert json.loads((worker / "completion.json").read_bytes()) == completion


@pytest.mark.parametrize("mode", ["terminal", "timeout", "nonzero", "missing", "wrong", "duplicate-diagnostic", "malformed-diagnostic"])
def test_known_process_failures_never_complete(tmp_path, mode):
    project, backend, task, worker = setup(tmp_path, mode=mode)
    with pytest.raises(runtime.PaperQA2ExecutionError) as caught:
        execute(project, backend, task, worker)
    assert not (worker / "result.json").exists()
    completion = json.loads((worker / "completion.json").read_bytes())
    assert completion["result_sha256"] is None and completion["error"]
    assert getattr(caught.value, "completion", None) == completion


@pytest.mark.parametrize("mode", ["duplicate-top", "duplicate-nested", "duplicate-escaped"])
def test_raw_stdout_rejects_duplicate_json_keys(tmp_path, mode):
    project, backend, task, worker = setup(tmp_path, mode=mode)
    with pytest.raises(runtime.PaperQA2ExecutionError): execute(project, backend, task, worker)
    assert b'"task_id"' in (worker / "stdout.log").read_bytes()
    assert not (worker / "result.json").exists()
    assert json.loads((worker / "completion.json").read_bytes())["result_sha256"] is None


def test_observer_write_or_fsync_failure_blocks(tmp_path, monkeypatch):
    project, backend, task, worker = setup(tmp_path)
    observer = getattr(runtime, "_CorpusOutputObserver", None)
    assert observer is not None, "missing full output observer"
    def broken(self, chunk): raise OSError("controlled output write failure")
    monkeypatch.setattr(observer, "on_stdout", broken)
    with pytest.raises(runtime.PaperQA2ExecutionError, match="PERSISTENCE_ERROR"):
        execute(project, backend, task, worker)
    assert not (worker / "result.json").exists()


def test_observer_fsync_failure_blocks(tmp_path, monkeypatch):
    project, backend, task, worker = setup(tmp_path)
    def broken(self): raise OSError("controlled fsync failure")
    monkeypatch.setattr(runtime._CorpusOutputObserver, "finish", broken)
    with pytest.raises(runtime.PaperQA2ExecutionError, match="PERSISTENCE_ERROR") as caught:
        execute(project, backend, task, worker)
    assert not (worker / "result.json").exists()
    assert caught.value.completion["result_sha256"] is None


def test_snapshot_replacement_blocks_before_dispatch(tmp_path):
    project, backend, task, worker = setup(tmp_path)
    (project / task["corpus"][0]["document_path"]).write_bytes(b"replaced")
    with pytest.raises(contracts.CurieContractError): execute(project, backend, task, worker)
    assert not (project / "child-called").exists()


def test_symlink_snapshot_escape_blocks_before_dispatch(tmp_path):
    project, backend, task, worker = setup(tmp_path)
    path = project / task["corpus"][0]["document_path"]
    external = tmp_path / "external.xml"; external.write_bytes(path.read_bytes()); path.unlink()
    try: path.symlink_to(external)
    except OSError: pytest.skip("Windows account cannot create symbolic links")
    with pytest.raises(contracts.CurieContractError): execute(project, backend, task, worker)
    assert not (project / "child-called").exists()
