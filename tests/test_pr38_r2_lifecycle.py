import json
from types import SimpleNamespace

from research_loop.commands import lifecycle
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE


def _candidate(tmp_path):
    project = tmp_path / "P"
    candidates = project / "01_Candidates"
    candidates.mkdir(parents=True)
    (candidates / "C1.md").write_text(
        "---\ncandidate_id: C1\ncurrent_status: IDEA_PROPOSED\n---\n",
        encoding="utf-8",
    )
    marker = project / "binding.json"
    marker.write_text("{}", encoding="utf-8")
    return project, marker


def _native(monkeypatch, marker):
    monkeypatch.setattr(lifecycle, "binding_path", lambda _project: marker)
    monkeypatch.setattr(
        lifecycle,
        "_ledger_for",
        lambda *_a, **_k: SimpleNamespace(
            project_profile=lambda _project: DEFAULT_NATIVE_PROFILE
        ),
    )
    monkeypatch.setattr(lifecycle, "_delta_belongs_to_candidate", lambda *_a, **_k: False)
    monkeypatch.setattr(
        lifecycle.research_seed,
        "load_l1_research_seed",
        lambda *_a, **_k: {"candidate_id": "C1", "round_id": "1"},
    )


def test_native_next_step_schedules_l05_when_no_frozen_binding(tmp_path, monkeypatch, capsys):
    project, marker = _candidate(tmp_path)
    _native(monkeypatch, marker)
    monkeypatch.setattr(lifecycle.research_seed, "active_l1_native_evidence_run_id", lambda *_a, **_k: None)
    monkeypatch.setattr(lifecycle.research_seed, "unique_l1_native_evidence_run_id", lambda *_a, **_k: None)

    rc = lifecycle.cmd_next_step(SimpleNamespace(
        project_dir=str(project), cand_id="C1", knowledge_store=None
    ))
    result = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert result["node"] == "L0.5"
    assert result["node_kind"] == "research"
    assert result["template_path"] is None
    assert result["persona_template_path"] is None


def test_native_next_step_routes_to_l1_after_exact_frozen_binding(tmp_path, monkeypatch, capsys):
    project, marker = _candidate(tmp_path)
    _native(monkeypatch, marker)
    monkeypatch.setattr(lifecycle.research_seed, "active_l1_native_evidence_run_id", lambda *_a, **_k: "RUN1")
    monkeypatch.setattr(lifecycle.research_seed, "unique_l1_native_evidence_run_id", lambda *_a, **_k: None)
    monkeypatch.setattr(
        lifecycle.research_seed,
        "load_l1_native_evidence_binding",
        lambda *_a, **_k: {"evidence_run_id": "RUN1"},
    )

    rc = lifecycle.cmd_next_step(SimpleNamespace(
        project_dir=str(project), cand_id="C1", knowledge_store=None
    ))
    result = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert result["node"] == "L1"
    assert result["evidence_run_id"] == "RUN1"
    assert result["l0_5_evidence_run_id"] == "RUN1"
