"""Durable, immutable storage for current-host cognitive requests and replies.

This module owns only the request/response files and their compare-and-set
boundary. RLR's ledger, context and delta owners remain authoritative for
state, authorization and scientific validation.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


class HostHandoffError(ValueError):
    """A host request or response cannot be safely bound to RLR state."""


class HandoffConflict(HostHandoffError):
    """An immutable request slot or response was submitted with new content."""


def _canonical_bytes(value: dict) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _project_root(project: str | Path) -> Path:
    root = Path(project).resolve(strict=True)
    if not root.is_dir():
        raise HostHandoffError("project path must be a directory")
    return root


def _inside(root: Path, path: str | Path, label: str) -> Path:
    candidate = Path(path).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HostHandoffError(f"{label} path escapes the project") from exc
    return candidate


def _internal_path(root: Path, path: str | Path, label: str) -> Path:
    """Resolve an internally derived path and keep it inside the project."""
    candidate = Path(path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HostHandoffError(f"{label} path escapes the project") from exc
    return candidate


def _store_root(root: Path) -> Path:
    return root / "08_Audit" / "host_handoff"


@contextlib.contextmanager
def _short_lock(path: Path):
    """Hold a cross-process lock only around a short file compare-and-set."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            unlock = lambda: msvcrt.locking(  # noqa: E731
                handle.fileno(), msvcrt.LK_UNLCK, 1
            )
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            unlock = lambda: fcntl.flock(  # noqa: E731
                handle.fileno(), fcntl.LOCK_UN
            )
        try:
            yield
        finally:
            unlock()


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _ledger_snapshot(root: Path, identity: dict) -> tuple[dict, str]:
    """Read the existing ledger owner and return its exact candidate cursor."""
    from research_loop.commands.ledger import _ledger_for

    ledger = _ledger_for(root)
    binding = ledger.require_activated_project(root)
    if str(binding["project_id"]) != str(identity.get("project_id")):
        raise HostHandoffError("request project identity does not match ledger binding")
    if ledger.project_profile(root) != identity.get("profile_id"):
        raise HostHandoffError("request profile does not match ledger binding")
    candidate_id = str(identity.get("candidate_id") or "")
    round_id = str(identity.get("round_id") or "")
    cursor = ledger.snapshot_candidate(root, candidate_id, round_id)
    return cursor, ledger.project_profile(root)


def _cursor_value(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise HostHandoffError("cursor must be a serialized ledger snapshot") from exc
        if isinstance(parsed, dict):
            return parsed
    raise HostHandoffError("cursor must be the authoritative ledger snapshot")


def _validate_identity(root: Path, identity: dict) -> dict:
    required = (
        "project_id", "candidate_id", "round_id", "node", "stage",
        "attempt", "cursor", "persona", "profile_id",
    )
    for name in required:
        if name not in identity or identity[name] in (None, ""):
            raise HostHandoffError(f"request identity {name} is required")
    if not isinstance(identity["attempt"], int) or isinstance(identity["attempt"], bool) or identity["attempt"] < 1:
        raise HostHandoffError("request attempt must be a positive integer")
    return identity


def _request_payload(kind, identity, inputs, tools_policy, output_contract):
    if not isinstance(kind, str) or not kind.strip():
        raise HostHandoffError("request kind is required")
    if not isinstance(identity, dict) or not isinstance(inputs, dict):
        raise HostHandoffError("request identity and inputs must be objects")
    if not isinstance(output_contract, dict):
        raise HostHandoffError("request output contract must be an object")
    if not isinstance(tools_policy, str) or not tools_policy.strip():
        raise HostHandoffError("request tools policy is required")
    return {
        "schema_version": "HostRequest/v1",
        "kind": kind,
        "identity": identity,
        "inputs": inputs,
        "tools_policy": tools_policy,
        "output_contract": output_contract,
    }


def _slot_hash(root: Path, payload: dict) -> str:
    identity = payload["identity"]
    slot = {
        "project": str(root),
        "project_id": identity["project_id"],
        "candidate_id": str(identity["candidate_id"]),
        "round_id": str(identity["round_id"]),
        "node": identity["node"],
        "stage": identity["stage"],
        "attempt": identity["attempt"],
        "cursor": identity["cursor"],
    }
    return _sha256(_canonical_bytes(slot))


def _load_request_at(root: Path, request_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", str(request_id)):
        raise HostHandoffError("request ID must be a SHA-256 digest")
    store = _internal_path(root, _store_root(root), "host handoff store")
    path = _internal_path(
        root, store / "requests" / f"{request_id}.json", "host request"
    )
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostHandoffError(f"host request is missing or invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise HostHandoffError("host request must contain a JSON object")
    allowed_fields = {
        "schema_version", "kind", "identity", "inputs", "tools_policy",
        "output_contract", "request_id",
    }
    if set(value) != allowed_fields:
        raise HostHandoffError("host request contains unknown or missing fields")
    request_body = {
        name: value[name]
        for name in ("schema_version", "kind", "identity", "inputs", "tools_policy", "output_contract")
        if name in value
    }
    computed_id = _sha256(_canonical_bytes(request_body))
    if value.get("request_id") != request_id or computed_id != request_id:
        raise HostHandoffError("host request ID does not match immutable request content")
    if raw != _canonical_bytes(value) + b"\n":
        raise HostHandoffError("host request bytes are not canonical")
    return {
        **value,
        "request_path": str(path),
        "request_sha256": _sha256(raw),
    }


def prepare_request(
    project: str | Path,
    *,
    kind: str,
    identity: dict,
    inputs: dict,
    tools_policy: str,
    output_contract: dict,
) -> dict:
    root = _project_root(project)
    identity = dict(_validate_identity(root, identity))
    payload = _request_payload(kind, identity, inputs, tools_policy, output_contract)
    cursor, _ = _ledger_snapshot(root, identity)
    supplied_cursor = _cursor_value(identity["cursor"])
    if supplied_cursor != cursor:
        raise HostHandoffError("request cursor is stale against snapshot_candidate")
    body = {
        **payload,
        "identity": {**identity, "cursor": cursor},
    }
    request_id = _sha256(_canonical_bytes(body))
    request_value = {**body, "request_id": request_id}
    request_raw = _canonical_bytes(request_value) + b"\n"
    request_hash = _sha256(request_raw)
    store = _internal_path(root, _store_root(root), "host handoff store")
    request_path = _internal_path(
        root, store / "requests" / f"{request_id}.json", "host request"
    )
    slot_hash = _slot_hash(root, request_value)
    slot_path = _internal_path(root, store / "slots" / f"{slot_hash}.json", "request slot")
    lock_path = _internal_path(root, store / "locks" / f"{slot_hash}.lock", "request lock")
    with _short_lock(lock_path):
        current_cursor, _ = _ledger_snapshot(root, identity)
        if current_cursor != cursor:
            raise HandoffConflict(
                "request cursor changed before its immutable slot was prepared"
            )
        if slot_path.is_file():
            try:
                prior = json.loads(slot_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise HostHandoffError(f"immutable request slot is unreadable: {exc}") from exc
            if prior.get("request_id") != request_id:
                raise HandoffConflict("request slot conflict: inputs are immutable")
            if prior.get("request_sha256") != request_hash:
                raise HostHandoffError(
                    "immutable request slot hash does not match request bytes"
                )
        if request_path.exists():
            if request_path.read_bytes() != request_raw:
                raise HandoffConflict("immutable host request content conflicts")
        else:
            _atomic_write(request_path, request_raw)
        if not slot_path.exists():
            _atomic_write(slot_path, _canonical_bytes({
                "request_id": request_id,
                "request_sha256": request_hash,
            }) + b"\n")
    return _load_request_at(root, request_id)


def load_request(project: str | Path, request_id: str) -> dict:
    return _load_request_at(_project_root(project), request_id)


def load_request_for_identity(project: str | Path, identity: dict) -> dict | None:
    """Load an immutable request occupying the identity's single-use slot."""
    root = _project_root(project)
    identity = dict(_validate_identity(root, identity))
    cursor, _ = _ledger_snapshot(root, identity)
    if _cursor_value(identity["cursor"]) != cursor:
        raise HostHandoffError("request cursor is stale against snapshot_candidate")
    identity["cursor"] = cursor
    slot_hash = _slot_hash(root, {"identity": identity})
    store = _internal_path(root, _store_root(root), "host handoff store")
    slot_path = _internal_path(
        root, store / "slots" / f"{slot_hash}.json", "request slot"
    )
    if not slot_path.is_file():
        return None
    try:
        slot_raw = slot_path.read_bytes()
        slot = json.loads(slot_raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostHandoffError(f"immutable request slot is unreadable: {exc}") from exc
    if (not isinstance(slot, dict)
            or set(slot) != {"request_id", "request_sha256"}
            or slot_raw != _canonical_bytes(slot) + b"\n"):
        raise HostHandoffError("immutable request slot is malformed")
    request = _load_request_at(root, str(slot["request_id"]))
    if (request.get("request_sha256") != slot.get("request_sha256")
            or request.get("identity") != identity):
        raise HostHandoffError("request slot does not match immutable request identity")
    return request


def _check_submission_cursor(root: Path, request: dict, expected_cursor: str) -> dict:
    expected = _cursor_value(expected_cursor)
    identity = request["identity"]
    current, _ = _ledger_snapshot(root, identity)
    if expected != current:
        raise HandoffConflict("stale cursor conflicts with current snapshot_candidate")
    if identity["cursor"] != current:
        raise HandoffConflict("request cursor is stale against snapshot_candidate")
    if (
        str(expected.get("project_id")) != str(identity["project_id"])
        or str(expected.get("candidate_id")) != str(identity["candidate_id"])
        or str(expected.get("round_id")) != str(identity["round_id"])
    ):
        raise HandoffConflict("stale candidate or round in request identity")
    return current


def submit_response(
    project: str | Path,
    request_id: str,
    response_path: str | Path,
    *,
    expected_cursor: str,
) -> dict:
    root = _project_root(project)
    request = _load_request_at(root, request_id)
    source_path = _inside(root, response_path, "response")
    try:
        raw_response = source_path.read_bytes()
    except OSError as exc:
        raise HostHandoffError(f"host response is unreadable: {exc}") from exc
    output_type = request["output_contract"].get("type")
    if output_type == "object":
        try:
            parsed_response = json.loads(raw_response.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise HostHandoffError(
                f"host response is incomplete or invalid JSON: {exc}"
            ) from exc
        if not isinstance(parsed_response, dict):
            raise HostHandoffError("host response must be a JSON object")
    elif output_type in {"string", "text"}:
        try:
            raw_response.decode("utf-8")
        except UnicodeError as exc:
            raise HostHandoffError("host text response is not valid UTF-8") from exc
    response_hash = _sha256(raw_response)
    store = _internal_path(root, _store_root(root), "host handoff store")
    response_dir = store / "responses"
    raw_path = _internal_path(
        root, response_dir / f"{request_id}.raw", "host response artifact"
    )
    receipt_path = _internal_path(
        root, response_dir / f"{request_id}.json", "host response receipt"
    )
    lock_path = _internal_path(
        root, store / "locks" / f"response-{request_id}.lock", "response lock"
    )
    record = {
        "schema_version": "HostResponseReceipt/v1",
        "request_id": request_id,
        "request_path": request["request_path"],
        "request_sha256": request["request_sha256"],
        "raw_response_path": str(raw_path),
        "raw_response_sha256": response_hash,
        "cursor": request["identity"]["cursor"],
    }
    record_raw = _canonical_bytes(record) + b"\n"
    with _short_lock(lock_path):
        if receipt_path.is_file():
            try:
                prior = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise HostHandoffError(f"host response receipt is unreadable: {exc}") from exc
            if prior.get("raw_response_sha256") != response_hash:
                raise HandoffConflict(
                    "same request ID conflicts with previously submitted response bytes"
                )
            if prior != record:
                raise HostHandoffError("host response receipt was modified after submission")
            if not raw_path.is_file() or _sha256(raw_path.read_bytes()) != response_hash:
                raise HostHandoffError("persisted host response is missing or changed")
            return prior
        _check_submission_cursor(root, request, expected_cursor)
        if raw_path.exists():
            if _sha256(raw_path.read_bytes()) != response_hash:
                raise HandoffConflict(
                    "incomplete response recovery conflicts with persisted response bytes"
                )
        else:
            _atomic_write(raw_path, raw_response)
        _atomic_write(receipt_path, record_raw)
    return record


def load_response_receipt(
    project: str | Path,
    request_id: str,
    *,
    expected_cursor: str,
) -> dict | None:
    """Load a completed response handoff only after rechecking its durable bytes."""
    root = _project_root(project)
    request = _load_request_at(root, request_id)
    store = _internal_path(root, _store_root(root), "host handoff store")
    response_dir = store / "responses"
    raw_path = _internal_path(
        root, response_dir / f"{request_id}.raw", "host response artifact"
    )
    receipt_path = _internal_path(
        root, response_dir / f"{request_id}.json", "host response receipt"
    )
    lock_path = _internal_path(
        root, store / "locks" / f"response-{request_id}.lock", "response lock"
    )
    with _short_lock(lock_path):
        _check_submission_cursor(root, request, expected_cursor)
        if not receipt_path.is_file():
            if raw_path.exists():
                raise HostHandoffError(
                    "persisted host response bytes have no durable receipt"
                )
            return None
        try:
            receipt_raw = receipt_path.read_bytes()
            receipt = json.loads(receipt_raw.decode("utf-8"))
            raw_response = raw_path.read_bytes()
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HostHandoffError(f"persisted host response receipt is incomplete: {exc}") from exc
        expected = {
            "schema_version": "HostResponseReceipt/v1",
            "request_id": request_id,
            "request_path": request["request_path"],
            "request_sha256": request["request_sha256"],
            "raw_response_path": str(raw_path),
            "raw_response_sha256": _sha256(raw_response),
            "cursor": request["identity"]["cursor"],
        }
        if (not isinstance(receipt, dict)
                or receipt_raw != _canonical_bytes(receipt) + b"\n"
                or receipt != expected):
            raise HostHandoffError(
                "persisted host response receipt differs from its request or raw bytes"
            )
        if _sha256(raw_response) != receipt.get("raw_response_sha256"):
            raise HostHandoffError("persisted host response bytes differ from receipt hash")
        return receipt
