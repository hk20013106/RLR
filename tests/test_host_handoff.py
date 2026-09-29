"""RED contract tests for immutable, host-owned cognitive handoff artifacts."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.hypothesis_ledger import HypothesisLedger


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _handoff():
    """Keep a missing production seam as an assertion failure, not collection error."""
    spec = importlib.util.find_spec("research_loop.host_handoff")
    assert spec is not None, (
        "missing host handoff boundary: research_loop.host_handoff"
    )
    import research_loop.host_handoff as handoff

    return handoff


@pytest.fixture
def bound_project(tmp_path, monkeypatch):
    project = tmp_path / "P"
    project.mkdir()
    store = tmp_path / "ledger.sqlite"
    ledger = HypothesisLedger(store)
    binding = ledger.bind_project(
        project,
        "PROJECT:host-test",
        profile_id=PROFILE_V21_CATALOG_1,
    )
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    return project, ledger, binding


def _cursor_token(cursor):
    return json.dumps(cursor, sort_keys=True, separators=(",", ":"))


def _prepare(handoff, project, project_id, *, candidate="C1", round_id="1",
             cursor=None, inputs=None, kind="cognitive"):
    identity = {
        "project_id": project_id,
        "candidate_id": candidate,
        "round_id": round_id,
        "node": "L2",
        "stage": "cognitive",
        "attempt": 1,
        "cursor": cursor,
        "persona": "Linnaeus",
        "profile_id": "v2.1-catalog-1",
    }
    return handoff.prepare_request(
        project,
        kind=kind,
        identity=identity,
        inputs=inputs or {"context": "frozen context", "context_sha256": "a" * 64},
        tools_policy="no-fs",
        output_contract={"schema_version": "2.1", "type": "object"},
    )


def _request_id(prepared):
    return prepared["request_id"]


def test_prepare_request_is_immutable_and_load_returns_the_same_request(bound_project):
    handoff = _handoff()
    project, ledger, binding = bound_project
    cursor = ledger.snapshot_candidate(project, "C1", "1")
    first = _prepare(handoff, project, binding["project_id"], cursor=cursor)
    second = _prepare(handoff, project, binding["project_id"], cursor=cursor)

    assert _request_id(first) == _request_id(second)
    assert handoff.load_request(project, _request_id(first)) == first
    assert Path(first["request_path"]).is_file()


def test_changed_inputs_for_the_same_slot_conflict(bound_project):
    handoff = _handoff()
    project, ledger, binding = bound_project
    cursor = ledger.snapshot_candidate(project, "C1", "1")
    _prepare(handoff, project, binding["project_id"], cursor=cursor)

    with pytest.raises((ValueError, RuntimeError), match="(?i)(conflict|immutable|slot)"):
        _prepare(
            handoff,
            project,
            binding["project_id"],
            cursor=cursor,
            inputs={"context": "changed context", "context_sha256": "b" * 64},
        )


def test_submit_hashes_exact_raw_bytes_and_identical_submission_is_idempotent(bound_project):
    handoff = _handoff()
    project, ledger, binding = bound_project
    cursor = ledger.snapshot_candidate(project, "C1", "1")
    prepared = _prepare(handoff, project, binding["project_id"], cursor=cursor)
    response = project / "host-response.json"
    raw = b'{"hypotheses":[]}\r\n'
    response.write_bytes(raw)

    first = handoff.submit_response(
        project, _request_id(prepared), response, expected_cursor=_cursor_token(cursor)
    )
    second = handoff.submit_response(
        project, _request_id(prepared), response, expected_cursor=_cursor_token(cursor)
    )

    assert first == second
    assert first["raw_response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert Path(first["raw_response_path"]).read_bytes() == raw


def test_same_request_id_with_different_response_bytes_conflicts(bound_project):
    handoff = _handoff()
    project, ledger, binding = bound_project
    cursor = ledger.snapshot_candidate(project, "C1", "1")
    prepared = _prepare(handoff, project, binding["project_id"], cursor=cursor)
    response = project / "host-response.json"
    response.write_bytes(b'{"answer":1}\n')
    handoff.submit_response(
        project, _request_id(prepared), response, expected_cursor=_cursor_token(cursor)
    )

    response.write_bytes(b'{"answer":2}\n')
    with pytest.raises((ValueError, RuntimeError), match="(?i)(conflict|immutable|response)"):
        handoff.submit_response(
            project, _request_id(prepared), response, expected_cursor=_cursor_token(cursor)
        )


def test_stale_cursor_is_rejected_before_response_is_recorded(bound_project):
    handoff = _handoff()
    project, ledger, binding = bound_project
    cursor = ledger.snapshot_candidate(project, "C1", "1")
    prepared = _prepare(handoff, project, binding["project_id"], cursor=cursor)
    stale = {**cursor, "as_of_commit_seq": cursor["as_of_commit_seq"] + 1}
    response = project / "host-response.json"
    response.write_bytes(b'{"answer":1}\n')

    with pytest.raises((ValueError, RuntimeError), match="(?i)(stale|cursor|conflict)"):
        handoff.submit_response(
            project, _request_id(prepared), response, expected_cursor=_cursor_token(stale)
        )


@pytest.mark.parametrize(
    "candidate,round_id",
    [("C0", "1"), ("C1", "0")],
    ids=["stale-candidate", "stale-round"],
)
def test_response_for_stale_candidate_or_round_is_rejected(bound_project, candidate, round_id):
    handoff = _handoff()
    project, ledger, binding = bound_project
    current = ledger.snapshot_candidate(project, "C1", "1")
    stale_slot = ledger.snapshot_candidate(project, candidate, round_id)
    prepared = _prepare(
        handoff,
        project,
        binding["project_id"],
        candidate=candidate,
        round_id=round_id,
        cursor=stale_slot,
    )
    response = project / "host-response.json"
    response.write_bytes(b'{"answer":1}\n')

    with pytest.raises((ValueError, RuntimeError), match="(?i)(stale|candidate|round|binding|conflict)"):
        handoff.submit_response(
            project, _request_id(prepared), response, expected_cursor=_cursor_token(current)
        )


def test_response_path_outside_project_is_rejected(bound_project, tmp_path):
    handoff = _handoff()
    project, ledger, binding = bound_project
    cursor = ledger.snapshot_candidate(project, "C1", "1")
    prepared = _prepare(handoff, project, binding["project_id"], cursor=cursor)
    outside = tmp_path / "outside.json"
    outside.write_bytes(b'{"answer":1}\n')

    with pytest.raises((ValueError, RuntimeError), match="(?i)(outside|escape|project|path)"):
        handoff.submit_response(
            project, _request_id(prepared), outside, expected_cursor=_cursor_token(cursor)
        )


def test_prepare_rejects_internal_store_root_outside_project_before_writing(
    bound_project, tmp_path, monkeypatch
):
    handoff = _handoff()
    project, ledger, binding = bound_project
    cursor = ledger.snapshot_candidate(project, "C1", "1")
    outside_store = tmp_path / "outside-store"
    monkeypatch.setattr(handoff, "_store_root", lambda _root: outside_store)

    with pytest.raises((ValueError, RuntimeError), match="(?i)(outside|escape|project|path)"):
        _prepare(handoff, project, binding["project_id"], cursor=cursor)

    assert not outside_store.exists()


def test_incomplete_response_write_can_be_retried_without_poisoning_the_request(bound_project):
    handoff = _handoff()
    project, ledger, binding = bound_project
    cursor = ledger.snapshot_candidate(project, "C1", "1")
    prepared = _prepare(handoff, project, binding["project_id"], cursor=cursor)
    response = project / "host-response.json"
    response.write_bytes(b'{"answer":')

    with pytest.raises((ValueError, RuntimeError), match="(?i)(incomplete|invalid|json|response)"):
        handoff.submit_response(
            project, _request_id(prepared), response, expected_cursor=_cursor_token(cursor)
        )

    complete = b'{"answer":1}\n'
    response.write_bytes(complete)
    receipt = handoff.submit_response(
        project, _request_id(prepared), response, expected_cursor=_cursor_token(cursor)
    )
    assert receipt["raw_response_sha256"] == hashlib.sha256(complete).hexdigest()

