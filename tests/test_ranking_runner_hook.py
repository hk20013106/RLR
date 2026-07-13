"""Shadow ranking hook tests at the canonical runner execution boundary."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import run_loop


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _Provider:
    name = "test-provider"

    def run_agent(self, *args, **kwargs):
        return {"selected": True, "decision": "KEEP"}


def _args(*, enabled=True, peers=None):
    return SimpleNamespace(
        provider=None,
        shadow_ranking=enabled,
        shadow_candidate=list(peers or ["C-current", "C-peer", "C-peer"]),
        shadow_seed=17,
        shadow_match_budget=6,
        shadow_timeout=60,
    )


def _step(node):
    return {"node": node, "persona": "Oppenheimer", "advance_command": "decision",
            "advance_status": "KEEP", "advance_reason": "formal decision"}


def _patch_success_path(monkeypatch, advances, events=None):
    def successful_emit(*args, **kwargs):
        if events is not None:
            events.append("emit")
        return True

    def record_advance(*args):
        if events is not None:
            events.append("advance")
        else:
            advances.append(args)

    monkeypatch.setattr(run_loop, "assemble_context", lambda *args: ("context", {}))
    monkeypatch.setattr(run_loop, "provider_for", lambda *args: _Provider())
    monkeypatch.setattr(run_loop, "emit_delta", successful_emit)
    monkeypatch.setattr(run_loop, "write_receipt", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_loop, "advance", record_advance)


def test_run_parser_exposes_default_disabled_shadow_options():
    args = run_loop.build_parser().parse_args(["run", "Project", "C1"])

    assert args.shadow_ranking is False
    assert args.shadow_candidate == []
    assert args.shadow_seed == 0
    assert args.shadow_match_budget == 10
    assert args.shadow_timeout == 60


def test_shadow_ranking_is_disabled_by_default_at_cognitive_boundary(monkeypatch, tmp_path):
    advances = []
    _patch_success_path(monkeypatch, advances)
    monkeypatch.setattr(
        run_loop.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("hook invoked")),
    )

    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L3"), SimpleNamespace(), _args(enabled=False),
        tmp_path, 2,
    )
    assert len(advances) == 1


def test_l3_and_l10b_shadow_hook_use_canonical_command_then_advance(monkeypatch, tmp_path):
    advances, commands, events = [], [], []
    _patch_success_path(monkeypatch, advances, events)

    def fake_run(command, **kwargs):
        events.append("ranking")
        commands.append((command, kwargs))
        return _Result()

    monkeypatch.setattr(run_loop.subprocess, "run", fake_run)
    for node in ("L3", "L10b"):
        assert run_loop.exec_cognitive(
            str(tmp_path), "C-current", _step(node), SimpleNamespace(), _args(), tmp_path, 2,
        )

    assert events == ["emit", "ranking", "advance", "emit", "ranking", "advance"]
    assert [command[0][2] for command in commands] == ["ranking-shadow", "ranking-shadow"]
    for (command, kwargs), stage in zip(commands, ("L3", "L10b")):
        assert command[:4] == [run_loop.sys.executable, str(run_loop.CONTROLLER),
                                "ranking-shadow", str(tmp_path)]
        assert command[command.index("--stage") + 1] == stage
        assert [command[index + 1] for index, value in enumerate(command)
                if value == "--candidate"] == ["C-current", "C-peer"]
        assert command[command.index("--seed") + 1] == "17"
        assert command[command.index("--match-budget") + 1] == "6"
        assert kwargs == {"capture_output": True, "text": True, "timeout": 60}


def test_l6_never_runs_shadow_hook(monkeypatch, tmp_path):
    advances = []
    _patch_success_path(monkeypatch, advances)
    monkeypatch.setattr(
        run_loop.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("L6 must skip hook")),
    )

    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L6"), SimpleNamespace(), _args(), tmp_path, 2,
    )
    assert len(advances) == 1


def test_failed_emit_never_runs_shadow_or_advances(monkeypatch, tmp_path):
    monkeypatch.setattr(run_loop, "assemble_context", lambda *args: ("context", {}))
    monkeypatch.setattr(run_loop, "provider_for", lambda *args: _Provider())
    monkeypatch.setattr(run_loop, "emit_delta", lambda *args, **kwargs: False)
    monkeypatch.setattr(run_loop, "write_receipt", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        run_loop.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ranking invoked")),
    )
    monkeypatch.setattr(
        run_loop, "advance",
        lambda *args: (_ for _ in ()).throw(AssertionError("advance invoked")),
    )

    assert not run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L3"), SimpleNamespace(), _args(), tmp_path, 2,
    )
    assert not (tmp_path / "08_Audit" / "ranking").exists()


def test_single_unique_shadow_candidate_skips_cli_writes_audit_then_advances(monkeypatch, tmp_path):
    advances = []
    _patch_success_path(monkeypatch, advances)
    monkeypatch.setattr(
        run_loop.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ranking invoked")),
    )

    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L3"), SimpleNamespace(),
        _args(peers=["C-current"]), tmp_path, 2,
    )
    audits = list((tmp_path / "08_Audit" / "ranking").glob("*.skipped.json"))
    assert len(advances) == 1
    assert len(audits) == 1
    audit = json.loads(audits[0].read_text(encoding="utf-8"))
    assert audit["outcome"] == "skipped"
    assert "two distinct candidates" in audit["error"]


def test_repeated_shadow_failures_and_skips_preserve_each_audit(monkeypatch, tmp_path):
    advances = []
    _patch_success_path(monkeypatch, advances)
    monkeypatch.setattr(run_loop.subprocess, "run",
                        lambda *args, **kwargs: _Result(2, "", "ranking rejected"))

    for _ in range(2):
        assert run_loop.exec_cognitive(
            str(tmp_path), "C-current", _step("L3"), SimpleNamespace(), _args(), tmp_path, 2,
        )
    for _ in range(2):
        assert run_loop.exec_cognitive(
            str(tmp_path), "C-solo", _step("L10b"), SimpleNamespace(),
            _args(peers=["C-solo"]), tmp_path, 2,
        )

    audit_dir = tmp_path / "08_Audit" / "ranking"
    audits = list(audit_dir.glob("*.failed*.json")) + list(audit_dir.glob("*.skipped*.json"))
    assert len(list(audit_dir.glob("*.failed*.json"))) == 2
    assert len(list(audit_dir.glob("*.skipped*.json"))) == 2
    assert all(json.loads(path.read_text(encoding="utf-8"))["schema_version"]
               == "shadow-ranking-failure-v1" for path in audits)
    assert not list(audit_dir.glob(".*.tmp"))
    assert len(advances) == 4


def test_shadow_timeout_writes_audit_and_still_advances(monkeypatch, tmp_path):
    advances = []
    _patch_success_path(monkeypatch, advances)

    def timeout(command, **kwargs):
        assert kwargs["timeout"] == 60
        raise run_loop.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(run_loop.subprocess, "run", timeout)
    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L10b"), SimpleNamespace(), _args(), tmp_path, 2,
    )
    audits = list((tmp_path / "08_Audit" / "ranking").glob("*.failed.json"))
    assert len(advances) == 1
    assert len(audits) == 1
    assert "timed out after 60s" in json.loads(audits[0].read_text(encoding="utf-8"))["error"]


def test_completed_shadow_artifact_deduplicates_retry_without_blocking_advance(monkeypatch, tmp_path):
    advances, commands = [], []
    _patch_success_path(monkeypatch, advances)

    def successful_run(command, **kwargs):
        commands.append(command)
        run_id = command[command.index("--run-id") + 1]
        target = tmp_path / "08_Audit" / "ranking"
        target.mkdir(parents=True, exist_ok=True)
        document = json.dumps(_valid_ranking_document(run_id))
        (target / f"{run_id}.json").write_text(document, encoding="utf-8")
        (target / f"{run_id}.checkpoint.json").write_text(document, encoding="utf-8")
        (target / f"{run_id}.md").write_text("# Shadow Ranking Report\n", encoding="utf-8")
        _write_complete_marker(target, run_id)
        return _Result()

    monkeypatch.setattr(run_loop.subprocess, "run", successful_run)
    for _ in range(2):
        assert run_loop.exec_cognitive(
            str(tmp_path), "C-current", _step("L3"), SimpleNamespace(), _args(), tmp_path, 2,
        )
    assert len(commands) == 1
    assert len(advances) == 2


def _stable_run_id(node="L3"):
    return run_loop._shadow_run_id(
        node, "C-current", 2, ["C-current", "C-peer"], 17, 6)


def _valid_ranking_document(run_id):
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "hypothesis_candidates": [
            {"candidate_id": "C-current", "hypothesis_id": "C-current"},
            {"candidate_id": "C-peer", "hypothesis_id": "C-peer"},
        ],
        "scheduler": {"algorithm": "elo", "seed": 17, "match_budget": 6},
        "budget": {"matches": 6},
        "pairwise_judgments": [],
        "ranking_results": [],
        "checkpoint": {"status": "complete", "completed_matches": 0},
    }


def _write_complete_marker(target, run_id, *, stage="L3", hashes=None):
    hashes = hashes or {
        "artifact": hashlib.sha256((target / f"{run_id}.json").read_bytes()).hexdigest(),
        "checkpoint": hashlib.sha256(
            (target / f"{run_id}.checkpoint.json").read_bytes()).hexdigest(),
        "report": hashlib.sha256((target / f"{run_id}.md").read_bytes()).hexdigest(),
    }
    marker = {"schema_version": "1.0", "run_id": run_id, "stage": stage,
              "judge_mode": "fake", "sha256": hashes}
    (target / f"{run_id}.complete.json").write_text(
        json.dumps(marker), encoding="utf-8")


def test_zero_exit_without_marker_writes_partial_audit_and_advances(monkeypatch, tmp_path):
    advances = []
    _patch_success_path(monkeypatch, advances)
    monkeypatch.setattr(run_loop.subprocess, "run", lambda *args, **kwargs: _Result())

    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L3"), SimpleNamespace(), _args(), tmp_path, 2,
    )
    audits = list((tmp_path / "08_Audit" / "ranking").glob("*.partial.json"))
    assert len(advances) == 1
    assert len(audits) == 1
    assert "exited successfully without a valid completion marker" in \
        json.loads(audits[0].read_text(encoding="utf-8"))["error"]


def test_zero_exit_with_marker_hash_mismatch_writes_partial_audit_and_advances(monkeypatch, tmp_path):
    advances = []
    _patch_success_path(monkeypatch, advances)

    def fake_run(command, **kwargs):
        run_id = command[command.index("--run-id") + 1]
        target = tmp_path / "08_Audit" / "ranking"
        target.mkdir(parents=True, exist_ok=True)
        document = json.dumps(_valid_ranking_document(run_id))
        (target / f"{run_id}.json").write_text(document, encoding="utf-8")
        (target / f"{run_id}.checkpoint.json").write_text(document, encoding="utf-8")
        (target / f"{run_id}.md").write_text("# Shadow Ranking Report\n", encoding="utf-8")
        _write_complete_marker(target, run_id, hashes={"artifact": "0" * 64,
            "checkpoint": hashlib.sha256((target / f"{run_id}.checkpoint.json").read_bytes()).hexdigest(),
            "report": hashlib.sha256((target / f"{run_id}.md").read_bytes()).hexdigest()})
        return _Result()

    monkeypatch.setattr(run_loop.subprocess, "run", fake_run)
    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L3"), SimpleNamespace(), _args(), tmp_path, 2,
    )
    audits = list((tmp_path / "08_Audit" / "ranking").glob("*.partial.json"))
    assert len(advances) == 1
    assert len(audits) == 1
    assert "hash mismatch" in json.loads(audits[0].read_text(encoding="utf-8"))["error"]


def test_zero_exit_with_valid_marker_logs_success_without_partial(monkeypatch, tmp_path, capsys):
    advances = []
    _patch_success_path(monkeypatch, advances)

    def fake_run(command, **kwargs):
        run_id = command[command.index("--run-id") + 1]
        target = tmp_path / "08_Audit" / "ranking"
        target.mkdir(parents=True, exist_ok=True)
        document = json.dumps(_valid_ranking_document(run_id))
        (target / f"{run_id}.json").write_text(document, encoding="utf-8")
        (target / f"{run_id}.checkpoint.json").write_text(document, encoding="utf-8")
        (target / f"{run_id}.md").write_text("# Shadow Ranking Report\n", encoding="utf-8")
        _write_complete_marker(target, run_id)
        return _Result()

    monkeypatch.setattr(run_loop.subprocess, "run", fake_run)
    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L3"), SimpleNamespace(), _args(), tmp_path, 2,
    )
    assert len(advances) == 1
    assert "shadow ranking complete:" in capsys.readouterr().out
    assert not list((tmp_path / "08_Audit" / "ranking").glob("*.partial.json"))


def test_lone_ranking_json_is_partial_audit_without_cli_and_still_advances(monkeypatch, tmp_path):
    advances = []
    _patch_success_path(monkeypatch, advances)
    target = tmp_path / "08_Audit" / "ranking"
    target.mkdir(parents=True)
    (target / f"{_stable_run_id()}.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        run_loop.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("partial run invoked CLI")),
    )

    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L3"), SimpleNamespace(), _args(), tmp_path, 2,
    )
    audits = list(target.glob("*.partial.json"))
    assert len(advances) == 1
    assert len(audits) == 1
    assert "without a completion marker" in json.loads(audits[0].read_text(encoding="utf-8"))["error"]


def test_malformed_ranking_triple_is_partial_audit_without_cli_and_still_advances(monkeypatch, tmp_path):
    advances = []
    _patch_success_path(monkeypatch, advances)
    target = tmp_path / "08_Audit" / "ranking"
    target.mkdir(parents=True)
    run_id = _stable_run_id()
    (target / f"{run_id}.json").write_text("not json", encoding="utf-8")
    (target / f"{run_id}.checkpoint.json").write_text("not json", encoding="utf-8")
    (target / f"{run_id}.md").write_text("# Shadow Ranking Report\n", encoding="utf-8")
    monkeypatch.setattr(
        run_loop.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("partial run invoked CLI")),
    )

    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L3"), SimpleNamespace(), _args(), tmp_path, 2,
    )
    audits = list(target.glob("*.partial.json"))
    assert len(advances) == 1
    assert len(audits) == 1
    assert "without a completion marker" in json.loads(audits[0].read_text(encoding="utf-8"))["error"]


def test_typed_junk_ranking_triple_without_marker_is_partial_without_cli_and_advances(monkeypatch, tmp_path):
    advances = []
    _patch_success_path(monkeypatch, advances)
    target = tmp_path / "08_Audit" / "ranking"
    target.mkdir(parents=True)
    run_id = _stable_run_id()
    for suffix in (".json", ".checkpoint.json"):
        (target / f"{run_id}{suffix}").write_text("{}", encoding="utf-8")
    (target / f"{run_id}.md").write_text("# Shadow Ranking Report\n", encoding="utf-8")
    monkeypatch.setattr(
        run_loop.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("invalid triple invoked CLI")),
    )

    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L3"), SimpleNamespace(), _args(), tmp_path, 2,
    )
    audits = list(target.glob("*.partial.json"))
    assert len(advances) == 1
    assert len(audits) == 1
    assert "without a completion marker" in json.loads(audits[0].read_text(encoding="utf-8"))["error"]


def test_completion_marker_hash_mismatch_is_partial_without_cli_and_advances(monkeypatch, tmp_path):
    advances = []
    _patch_success_path(monkeypatch, advances)
    target = tmp_path / "08_Audit" / "ranking"
    target.mkdir(parents=True)
    run_id = _stable_run_id()
    document = json.dumps(_valid_ranking_document(run_id))
    (target / f"{run_id}.json").write_text(document, encoding="utf-8")
    (target / f"{run_id}.checkpoint.json").write_text(document, encoding="utf-8")
    (target / f"{run_id}.md").write_text("# Shadow Ranking Report\n", encoding="utf-8")
    _write_complete_marker(target, run_id, hashes={
        "artifact": "0" * 64,
        "checkpoint": hashlib.sha256(
            (target / f"{run_id}.checkpoint.json").read_bytes()).hexdigest(),
        "report": hashlib.sha256((target / f"{run_id}.md").read_bytes()).hexdigest(),
    })
    monkeypatch.setattr(
        run_loop.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("hash-mismatched run invoked CLI")),
    )

    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L3"), SimpleNamespace(), _args(), tmp_path, 2,
    )
    audits = list(target.glob("*.partial.json"))
    assert len(advances) == 1
    assert len(audits) == 1
    assert "hash mismatch" in json.loads(audits[0].read_text(encoding="utf-8"))["error"]


def test_complete_ranking_triple_deduplicates_without_cli_and_still_advances(monkeypatch, tmp_path):
    advances = []
    _patch_success_path(monkeypatch, advances)
    target = tmp_path / "08_Audit" / "ranking"
    target.mkdir(parents=True)
    run_id = _stable_run_id()
    document = json.dumps(_valid_ranking_document(run_id))
    (target / f"{run_id}.json").write_text(document, encoding="utf-8")
    (target / f"{run_id}.checkpoint.json").write_text(document, encoding="utf-8")
    (target / f"{run_id}.md").write_text("# Shadow Ranking Report\n", encoding="utf-8")
    _write_complete_marker(target, run_id)
    monkeypatch.setattr(
        run_loop.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("complete run invoked CLI")),
    )

    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L3"), SimpleNamespace(), _args(), tmp_path, 2,
    )
    assert len(advances) == 1
    assert not list(target.glob("*.partial.json"))


def test_shadow_failure_writes_isolated_audit_and_preserves_formal_advance(monkeypatch, tmp_path):
    formal_decision = {"status": "UNCHANGED"}
    original = tmp_path / "01_Candidates" / "C-current.md"
    original.parent.mkdir()
    original.write_text("---\ncurrent_status: UNCHANGED\n---\n", encoding="utf-8")
    monkeypatch.setattr(run_loop, "assemble_context", lambda *args: ("context", {}))
    monkeypatch.setattr(run_loop, "provider_for", lambda *args: _Provider())
    monkeypatch.setattr(run_loop, "emit_delta", lambda *args, **kwargs: True)
    monkeypatch.setattr(run_loop, "write_receipt", lambda *args, **kwargs: None)
    advances = []

    def formal_advance(*args):
        advances.append(args)
        assert formal_decision == {"status": "UNCHANGED"}

    monkeypatch.setattr(run_loop, "advance", formal_advance)
    monkeypatch.setattr(run_loop.subprocess, "run",
                        lambda *args, **kwargs: _Result(2, "", "ranking rejected"))

    assert run_loop.exec_cognitive(
        str(tmp_path), "C-current", _step("L10b"), SimpleNamespace(), _args(), tmp_path, 2,
    )
    audits = list((tmp_path / "08_Audit" / "ranking").glob("*.failed.json"))
    assert len(advances) == 1
    assert formal_decision == {"status": "UNCHANGED"}
    assert original.read_text(encoding="utf-8") == "---\ncurrent_status: UNCHANGED\n---\n"
    assert len(audits) == 1
    audit = json.loads(audits[0].read_text(encoding="utf-8"))
    assert audit["stage"] == "L10b"
    assert audit["candidate_id"] == "C-current"
    assert "ranking rejected" in audit["error"]
    assert audit["provenance"]["shadow_mode"] == "fail-soft"
