"""Native v2.1 ResearchSeed -> frozen Curie EvidencePack binding.

Bindings are immutable per acquisition run.  The currently authoritative native
binding is derived from append-only activation receipts rather than a mutable
pointer, preserving the complete EvidencePack lineage across Curie retries.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION = "L1NativeEvidenceBinding/v2"
LEGACY_NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION = "L1NativeEvidenceBinding/v1"
NATIVE_EVIDENCE_ACTIVATION_SCHEMA_VERSION = "L1NativeEvidenceActivation/v1"
NATIVE_RETRY_COMMIT_SCHEMA_VERSION = "L05NativeRetryCommit/v1"
_ROOT = Path("08_Audit") / "research_seed_bindings" / "native"


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
    )


def _text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must be a non-empty string")
    return text


def _binding_dir(project_dir: str | Path, seed: dict) -> Path:
    candidate_id = _text(seed.get("candidate_id"), "native binding candidate_id")
    round_id = _text(seed.get("round_id"), "native binding round_id")
    return Path(project_dir) / _ROOT / candidate_id / round_id


def _binding_path(project_dir: str | Path, seed: dict, acquisition_run_id: str) -> Path:
    run_id = _text(acquisition_run_id, "native binding acquisition_run_id")
    identity = f"{seed['candidate_id']}:{seed['round_id']}:{run_id}"
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return _binding_dir(project_dir, seed) / f"L1_native_{suffix}.json"


def _activation_dir(project_dir: str | Path, seed: dict) -> Path:
    return _binding_dir(project_dir, seed) / "activations"


def _activation_path(project_dir: str | Path, seed: dict, version: int,
                     acquisition_run_id: str) -> Path:
    run_id = _text(acquisition_run_id, "native activation acquisition_run_id")
    suffix = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
    return _activation_dir(project_dir, seed) / f"v{int(version):03d}_{suffix}.json"


def _retry_transactions_dir(project_dir: str | Path, seed: dict) -> Path:
    return _binding_dir(project_dir, seed) / "retry_transactions"


def _retry_transaction_dir(project_dir: str | Path, seed: dict,
                           authorization_id: str) -> Path:
    token = _text(authorization_id, "native retry authorization_id")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
           for character in token):
        raise ValueError("native retry authorization_id is not a safe token")
    return _retry_transactions_dir(project_dir, seed) / token


def _load_pack(project_dir: Path, seed: dict, pack_manifest: dict, research_seed_module):
    from research_loop import l05_curie

    try:
        return l05_curie.load_frozen_evidence_pack(
            project_dir,
            pack_manifest,
            candidate_id=str(seed["candidate_id"]),
            round_id=str(seed["round_id"]),
            seed_sha256=research_seed_module.seed_sha256(seed),
        )
    except l05_curie.CurieContractError as exc:
        raise research_seed_module.ResearchSeedError(
            f"frozen L0.5 EvidencePack is invalid: {exc}"
        ) from exc


def _parent_manifest(project_dir: Path, seed: dict, parent_pack_sha256: str,
                     research_seed_module) -> dict:
    """Find a validated bound parent pack without treating a mutable pointer as authority."""
    for path in sorted(_binding_dir(project_dir, seed).glob("L1_native_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise research_seed_module.ResearchSeedError(
                f"native L1 evidence binding is unreadable: {exc}"
            ) from exc
        manifest = payload.get("evidence_pack") if isinstance(payload, dict) else None
        if not isinstance(manifest, dict):
            continue
        frozen = _load_pack(project_dir, seed, manifest, research_seed_module)
        if str(frozen.get("content_sha256") or "") == parent_pack_sha256:
            return manifest
    transaction_root = _retry_transactions_dir(project_dir, seed)
    if transaction_root.is_dir():
        for commit_path in sorted(transaction_root.glob("*/commit.json")):
            try:
                commit = json.loads(commit_path.read_text(encoding="utf-8"))
                binding_relative = commit["artifacts"]["binding"]["path"]
                binding_path = (project_dir / Path(binding_relative)).resolve()
                transaction_dir = commit_path.parent.resolve()
                if binding_path.parent != transaction_dir:
                    continue
                binding = json.loads(binding_path.read_text(encoding="utf-8"))
                manifest = binding.get("evidence_pack")
                if not isinstance(manifest, dict):
                    continue
                frozen = _load_pack(project_dir, seed, manifest, research_seed_module)
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if str(frozen.get("content_sha256") or "") == parent_pack_sha256:
                return manifest
    raise research_seed_module.ResearchSeedError(
        "native L1 retry binding parent pack is not an existing native binding"
    )


def _validated_retry_authorization(project_dir: Path, seed: dict, frozen: dict,
                                   retry_authorization: object,
                                   research_seed_module) -> dict | None:
    """Prove a retry pack is tied to an existing request and bounded authority."""
    from research_loop import l05_curie

    version = int(frozen["version"])
    parent_sha = frozen.get("parent_pack_sha256")
    gap_id = frozen.get("source_gap_request_id")
    if version == 1:
        if parent_sha not in (None, "") or gap_id not in (None, ""):
            raise research_seed_module.ResearchSeedError(
                "native L1 v1 binding must not have retry lineage"
            )
        if retry_authorization not in (None, {}):
            raise research_seed_module.ResearchSeedError(
                "native L1 v1 binding must not carry retry authorization"
            )
        return None
    if version > l05_curie.MAX_ACQUISITION_ROUNDS:
        raise research_seed_module.ResearchSeedError(
            f"native L1 retry binding exceeds {l05_curie.MAX_ACQUISITION_ROUNDS} rounds"
        )
    if not isinstance(retry_authorization, dict):
        raise research_seed_module.ResearchSeedError(
            "native L1 retry binding requires persisted retry authorization"
        )
    try:
        authorization = l05_curie.validate_gap_retry_authorization(
            seed, retry_authorization
        )
    except l05_curie.CurieContractError as exc:
        raise research_seed_module.ResearchSeedError(
            f"native L1 retry authorization is invalid: {exc}"
        ) from exc
    expected = {
        "next_version": version,
        "parent_pack_sha256": str(parent_sha or ""),
        "source_gap_request_id": str(gap_id or ""),
    }
    for field, value in expected.items():
        observed = authorization.get(field)
        matches = (
            int(observed or 0) == value
            if field == "next_version"
            else str(observed or "") == value
        )
        if not matches:
            raise research_seed_module.ResearchSeedError(
                f"native L1 retry authorization {field} does not match EvidencePack lineage"
            )
    parent_manifest = _parent_manifest(
        project_dir, seed, str(parent_sha), research_seed_module
    )
    try:
        l05_curie.load_open_gap_request(
            project_dir, seed, parent_manifest, str(gap_id)
        )
    except l05_curie.CurieContractError as exc:
        raise research_seed_module.ResearchSeedError(
            f"native L1 retry gap lineage is invalid: {exc}"
        ) from exc
    return authorization


def _payload(project_dir: Path, seed: dict, pack_manifest: dict,
             acquisition_run_id: str, research_seed_module,
             retry_authorization: object = None) -> dict:
    run_id = _text(acquisition_run_id, "native binding acquisition_run_id")
    frozen = _load_pack(project_dir, seed, pack_manifest, research_seed_module)
    if str(frozen.get("source_run_id") or "") != run_id:
        raise research_seed_module.ResearchSeedError(
            "frozen L0.5 EvidencePack source_run_id does not match native acquisition_run_id"
        )
    authorization = _validated_retry_authorization(
        project_dir, seed, frozen, retry_authorization, research_seed_module
    )
    payload = {
        "schema_version": NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION,
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "research_seed": research_seed_module.manifest_entry(seed),
        "acquisition_run_id": run_id,
        "evidence_pack": dict(pack_manifest),
        "pack_lineage": {
            "version": int(frozen["version"]),
            "parent_pack_sha256": frozen.get("parent_pack_sha256"),
            "source_gap_request_id": frozen.get("source_gap_request_id"),
            "content_sha256": str(frozen["content_sha256"]),
        },
    }
    if authorization is not None:
        payload["retry_authorization"] = authorization
    return payload


def _entry_at_path(project_dir: Path, seed: dict, acquisition_run_id: str,
                   payload: dict, path: Path, *, artifact_sha256: str | None = None) -> dict:
    try:
        relative = path.relative_to(project_dir).as_posix()
    except ValueError:
        relative = path.as_posix()
    manifest = payload["evidence_pack"]
    return {
        "schema_version": str(payload["schema_version"]),
        "artifact_path": relative,
        "artifact_sha256": artifact_sha256 or hashlib.sha256(path.read_bytes()).hexdigest(),
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "seed_sha256": str(payload["research_seed"]["seed_sha256"]),
        "evidence_run_id": str(payload["acquisition_run_id"]),
        "evidence_pack_id": str(manifest["pack_id"]),
        "evidence_pack_version": int(manifest["version"]),
        "evidence_pack_path": str(manifest["artifact_path"]),
        "evidence_pack_sha256": str(manifest["artifact_sha256"]),
        "evidence_pack_content_sha256": str(manifest["content_sha256"]),
    }


def _entry(project_dir: Path, seed: dict, acquisition_run_id: str,
           payload: dict) -> dict:
    return _entry_at_path(
        project_dir, seed, acquisition_run_id, payload,
        _binding_path(project_dir, seed, acquisition_run_id),
    )


def _write_durable_json(path: Path, payload: dict) -> bytes:
    raw = _canonical_bytes(payload)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return raw


def _validate_payload(project_dir: Path, seed: dict, acquisition_run_id: str,
                      payload: dict, research_seed_module) -> dict:
    run_id = _text(acquisition_run_id, "native binding acquisition_run_id")
    if not isinstance(payload, dict):
        raise research_seed_module.ResearchSeedError("native L1 evidence binding must be an object")
    schema_version = payload.get("schema_version")
    if schema_version not in {
        LEGACY_NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION,
        NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION,
    }:
        raise research_seed_module.ResearchSeedError("native L1 evidence binding schema is invalid")
    if str(payload.get("candidate_id") or "") != str(seed["candidate_id"]):
        raise research_seed_module.ResearchSeedError("native L1 evidence binding candidate mismatch")
    if str(payload.get("round_id") or "") != str(seed["round_id"]):
        raise research_seed_module.ResearchSeedError("native L1 evidence binding round mismatch")
    if payload.get("research_seed") != research_seed_module.manifest_entry(seed):
        raise research_seed_module.ResearchSeedError("native L1 evidence binding research seed has changed")
    if str(payload.get("acquisition_run_id") or "") != run_id:
        raise research_seed_module.ResearchSeedError("native L1 evidence binding acquisition_run_id mismatch")
    manifest = payload.get("evidence_pack")
    if not isinstance(manifest, dict):
        raise research_seed_module.ResearchSeedError("native L1 evidence binding has no frozen EvidencePack")
    frozen = _load_pack(project_dir, seed, manifest, research_seed_module)
    if str(frozen.get("source_run_id") or "") != run_id:
        raise research_seed_module.ResearchSeedError(
            "frozen L0.5 EvidencePack source_run_id changed since native binding"
        )
    expected_lineage = {
        "version": int(frozen["version"]),
        "parent_pack_sha256": frozen.get("parent_pack_sha256"),
        "source_gap_request_id": frozen.get("source_gap_request_id"),
        "content_sha256": str(frozen["content_sha256"]),
    }
    if payload.get("pack_lineage") != expected_lineage:
        raise research_seed_module.ResearchSeedError("native L1 evidence binding pack lineage has changed")
    retry_authorization = payload.get("retry_authorization")
    if schema_version == LEGACY_NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION:
        if int(frozen["version"]) != 1:
            raise research_seed_module.ResearchSeedError(
                "legacy native L1 retry binding has no authenticated retry lineage"
            )
        if retry_authorization not in (None, {}):
            raise research_seed_module.ResearchSeedError(
                "legacy native L1 binding must not carry retry authorization"
            )
    else:
        _validated_retry_authorization(
            project_dir, seed, frozen, retry_authorization, research_seed_module
        )
    return payload


def install(research_seed_module) -> None:
    """Install native binding and activation APIs on canonical ``research_seed``."""
    if getattr(research_seed_module, "_l05_native_binding_installed", False):
        return
    legacy_evidence_binding_manifest_entry = research_seed_module.evidence_binding_manifest_entry

    def write_l1_native_evidence_binding(project_dir, seed, pack_manifest,
                                         acquisition_run_id, *,
                                         retry_authorization=None) -> dict:
        project = Path(project_dir)
        try:
            payload = _payload(project, seed, pack_manifest, acquisition_run_id,
                               research_seed_module, retry_authorization)
        except ValueError as exc:
            raise research_seed_module.ResearchSeedError(str(exc)) from exc
        path = _binding_path(project, seed, acquisition_run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = _canonical_bytes(payload)
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise research_seed_module.ResearchSeedError(
                    f"native L1 evidence binding is unreadable: {exc}"
                ) from exc
            if existing != payload:
                if (
                    existing.get("schema_version")
                    == LEGACY_NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION
                    and retry_authorization in (None, {})
                    and existing.get("evidence_pack") == pack_manifest
                ):
                    validated = _validate_payload(
                        project, seed, acquisition_run_id, existing,
                        research_seed_module
                    )
                    return _entry(project, seed, acquisition_run_id, validated)
                raise research_seed_module.ResearchSeedError(
                    "native L1 evidence binding already exists with different provenance"
                )
        else:
            if int(payload["pack_lineage"]["version"]) > 1:
                active_run_id = active_l1_native_evidence_run_id(project, seed)
                if not active_run_id:
                    raise research_seed_module.ResearchSeedError(
                        "native L1 retry binding requires an active parent binding"
                    )
                active_binding = load_l1_native_evidence_binding(
                    project, seed, active_run_id
                )
                if (
                    str(active_binding["pack_lineage"]["content_sha256"])
                    != str(payload["pack_lineage"]["parent_pack_sha256"])
                ):
                    raise research_seed_module.ResearchSeedError(
                        "native L1 retry binding parent is not the active native pack"
                    )
            path.write_bytes(raw)
        validated = _validate_payload(project, seed, acquisition_run_id, payload,
                                      research_seed_module)
        return _entry(project, seed, acquisition_run_id, validated)

    def load_l1_native_evidence_binding(project_dir, seed, acquisition_run_id) -> dict:
        project = Path(project_dir)
        try:
            path = _binding_path(project, seed, acquisition_run_id)
        except ValueError as exc:
            raise research_seed_module.ResearchSeedError(str(exc)) from exc
        if not path.is_file():
            committed = _find_retry_transaction_by_run(
                project, seed, str(acquisition_run_id)
            )
            if committed is not None:
                return committed["binding"]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise research_seed_module.ResearchSeedError(
                f"native L1 evidence binding is missing or invalid: {exc}"
            ) from exc
        return _validate_payload(project, seed, acquisition_run_id, payload,
                                 research_seed_module)

    def native_evidence_binding_manifest_entry(project_dir, seed,
                                               acquisition_run_id) -> dict:
        project = Path(project_dir)
        committed = _find_retry_transaction_by_run(
            project, seed, str(acquisition_run_id)
        )
        if committed is not None:
            return committed["binding_entry"]
        payload = load_l1_native_evidence_binding(project, seed, acquisition_run_id)
        return _entry(project, seed, acquisition_run_id, payload)

    def evidence_binding_manifest_entry(project_dir, seed, evidence_run_id) -> dict:
        """Return authoritative receipt for this run, native when present."""
        project = Path(project_dir)
        native_path = _binding_path(project, seed, evidence_run_id)
        if native_path.is_file():
            return native_evidence_binding_manifest_entry(project, seed, evidence_run_id)
        if _find_retry_transaction_by_run(project, seed, str(evidence_run_id)) is not None:
            return native_evidence_binding_manifest_entry(project, seed, evidence_run_id)
        return legacy_evidence_binding_manifest_entry(project_dir, seed, evidence_run_id)

    def unique_l1_native_evidence_run_id(project_dir, seed):
        project = Path(project_dir)
        root = _binding_dir(project, seed)
        if not root.is_dir():
            return None
        run_ids = []
        for path in sorted(root.glob("L1_native_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise research_seed_module.ResearchSeedError(
                    f"native L1 evidence binding is unreadable: {exc}"
                ) from exc
            run_id = str(payload.get("acquisition_run_id") or "")
            if not run_id:
                raise research_seed_module.ResearchSeedError(
                    "native L1 evidence binding has no acquisition_run_id"
                )
            if path.resolve() != _binding_path(project, seed, run_id).resolve():
                raise research_seed_module.ResearchSeedError(
                    "native L1 evidence binding path does not match its acquisition_run_id"
                )
            _validate_payload(project, seed, run_id, payload, research_seed_module)
            if run_id not in run_ids:
                run_ids.append(run_id)
        transaction_root = _retry_transactions_dir(project, seed)
        if transaction_root.is_dir():
            for commit_path in sorted(transaction_root.glob("*/commit.json")):
                transaction = _load_retry_transaction(
                    project, seed, commit_path.parent
                )
                run_id = str(transaction["acquisition_run_id"])
                if run_id not in run_ids:
                    run_ids.append(run_id)
        return run_ids[0] if len(run_ids) == 1 else None

    def _activation_payload(project: Path, seed: dict, acquisition_run_id: str) -> dict:
        binding = load_l1_native_evidence_binding(project, seed, acquisition_run_id)
        if int(binding["pack_lineage"]["version"]) > 1:
            from research_loop import l05_curie

            try:
                l05_curie.load_gap_retry_consumption(
                    project,
                    seed,
                    binding["retry_authorization"],
                    acquisition_run_id,
                )
            except l05_curie.CurieContractError as exc:
                raise research_seed_module.ResearchSeedError(
                    f"native L1 retry activation lacks a valid consumption receipt: {exc}"
                ) from exc
        entry = native_evidence_binding_manifest_entry(project, seed, acquisition_run_id)
        lineage = binding["pack_lineage"]
        return {
            "schema_version": NATIVE_EVIDENCE_ACTIVATION_SCHEMA_VERSION,
            "candidate_id": str(seed["candidate_id"]),
            "round_id": str(seed["round_id"]),
            "research_seed": research_seed_module.manifest_entry(seed),
            "acquisition_run_id": str(acquisition_run_id),
            "evidence_pack_version": int(lineage["version"]),
            "evidence_pack_content_sha256": str(lineage["content_sha256"]),
            "parent_pack_sha256": lineage.get("parent_pack_sha256"),
            "source_gap_request_id": lineage.get("source_gap_request_id"),
            "binding": entry,
        }

    def _load_retry_transaction(project: Path, seed: dict,
                                transaction_dir: Path) -> dict:
        from research_loop import l05_curie

        expected_dir = _retry_transaction_dir(
            project, seed,
            transaction_dir.name,
        ).resolve()
        if transaction_dir.resolve() != expected_dir:
            raise research_seed_module.ResearchSeedError(
                "native L05 retry transaction path is not canonical"
            )
        try:
            commit = json.loads(
                (transaction_dir / "commit.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise research_seed_module.ResearchSeedError(
                f"native L05 retry commit is unreadable: {exc}"
            ) from exc
        if commit.get("schema_version") != NATIVE_RETRY_COMMIT_SCHEMA_VERSION:
            raise research_seed_module.ResearchSeedError(
                "native L05 retry commit schema is invalid"
            )
        authorization = commit.get("authorization")
        if not isinstance(authorization, dict):
            raise research_seed_module.ResearchSeedError(
                "native L05 retry commit has no authorization"
            )
        try:
            authorization = l05_curie.validate_gap_retry_authorization(
                seed, authorization
            )
            run_id = _text(
                commit.get("acquisition_run_id"),
                "native retry commit acquisition_run_id",
            )
            if str(commit.get("authorization_id") or "") != str(
                authorization["authorization_id"]
            ):
                raise ValueError("authorization_id does not match authorization")
            if str(commit.get("candidate_id") or "") != str(seed["candidate_id"]):
                raise ValueError("candidate_id does not match ResearchSeed")
            if str(commit.get("round_id") or "") != str(seed["round_id"]):
                raise ValueError("round_id does not match ResearchSeed")
            if commit.get("authorization") != authorization:
                raise ValueError("authorization was changed")
            artifacts = commit["artifacts"]
            if set(artifacts) != {"binding", "consumption", "activation"}:
                raise ValueError("retry commit artifact set is invalid")
        except (KeyError, TypeError, ValueError, l05_curie.CurieContractError) as exc:
            raise research_seed_module.ResearchSeedError(
                f"native L05 retry commit lineage is invalid: {exc}"
            ) from exc

        loaded = {}
        paths = {}
        for name in ("binding", "consumption", "activation"):
            try:
                relative = Path(str(artifacts[name]["path"]))
                path = (project / relative).resolve()
                expected_sha = str(artifacts[name]["sha256"])
            except (KeyError, TypeError, ValueError) as exc:
                raise research_seed_module.ResearchSeedError(
                    f"native L05 retry {name} artifact metadata is invalid"
                ) from exc
            if path.parent != transaction_dir.resolve() or path.name != f"{name}.json":
                raise research_seed_module.ResearchSeedError(
                    f"native L05 retry {name} artifact path is not canonical"
                )
            try:
                raw = path.read_bytes()
                payload = json.loads(raw.decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise research_seed_module.ResearchSeedError(
                    f"native L05 retry {name} artifact is unreadable: {exc}"
                ) from exc
            if hashlib.sha256(raw).hexdigest() != expected_sha:
                raise research_seed_module.ResearchSeedError(
                    f"native L05 retry {name} artifact hash changed"
                )
            loaded[name] = payload
            paths[name] = path

        binding = loaded["binding"]
        try:
            _validate_payload(
                project, seed, run_id, binding, research_seed_module
            )
            if binding.get("retry_authorization") != authorization:
                raise ValueError("binding authorization does not match commit")
            expected_consumption = l05_curie.build_gap_retry_consumption(
                seed, authorization, run_id
            )
            if loaded["consumption"] != expected_consumption:
                raise ValueError("consumption does not match authorization")
            binding_entry = _entry_at_path(
                project, seed, run_id, binding, paths["binding"]
            )
            lineage = binding["pack_lineage"]
            expected_activation = {
                "schema_version": NATIVE_EVIDENCE_ACTIVATION_SCHEMA_VERSION,
                "candidate_id": str(seed["candidate_id"]),
                "round_id": str(seed["round_id"]),
                "research_seed": research_seed_module.manifest_entry(seed),
                "acquisition_run_id": run_id,
                "evidence_pack_version": int(lineage["version"]),
                "evidence_pack_content_sha256": str(lineage["content_sha256"]),
                "parent_pack_sha256": lineage.get("parent_pack_sha256"),
                "source_gap_request_id": lineage.get("source_gap_request_id"),
                "binding": binding_entry,
            }
            if loaded["activation"] != expected_activation:
                raise ValueError("activation does not match binding")
        except (KeyError, TypeError, ValueError) as exc:
            raise research_seed_module.ResearchSeedError(
                f"native L05 retry transaction lineage is invalid: {exc}"
            ) from exc
        return {
            "authorization_id": str(authorization["authorization_id"]),
            "authorization": authorization,
            "acquisition_run_id": run_id,
            "binding": binding,
            "binding_entry": binding_entry,
            "consumption": loaded["consumption"],
            "activation": loaded["activation"],
            "evidence_pack": dict(binding["evidence_pack"]),
            "transaction_dir": transaction_dir,
        }

    def _find_retry_transaction_by_run(project: Path, seed: dict,
                                       acquisition_run_id: str) -> dict | None:
        root = _retry_transactions_dir(project, seed)
        if not root.is_dir():
            return None
        found = None
        for commit_path in sorted(root.glob("*/commit.json")):
            transaction = _load_retry_transaction(project, seed, commit_path.parent)
            if transaction["acquisition_run_id"] != str(acquisition_run_id):
                continue
            if found is not None:
                raise research_seed_module.ResearchSeedError(
                    "multiple committed native L05 retries use one acquisition_run_id"
                )
            found = transaction
        return found

    def load_l1_native_retry_commit(project_dir, seed, request_id) -> dict | None:
        project = Path(project_dir)
        root = _retry_transactions_dir(project, seed)
        if not root.is_dir():
            return None
        found = None
        for commit_path in sorted(root.glob("*/commit.json")):
            transaction = _load_retry_transaction(project, seed, commit_path.parent)
            if str(transaction["authorization"].get("request_id") or "") != str(request_id):
                continue
            if found is not None:
                raise research_seed_module.ResearchSeedError(
                    "multiple committed native L05 retries use one request_id"
                )
            found = transaction
        return found

    def _load_activations(project: Path, seed: dict) -> list[dict]:
        root = _activation_dir(project, seed)
        if not root.is_dir():
            return []
        activations = []
        for path in sorted(root.glob("v*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise research_seed_module.ResearchSeedError(
                    f"native L1 activation receipt is unreadable: {exc}"
                ) from exc
            if payload.get("schema_version") != NATIVE_EVIDENCE_ACTIVATION_SCHEMA_VERSION:
                raise research_seed_module.ResearchSeedError("native L1 activation schema is invalid")
            if str(payload.get("candidate_id") or "") != str(seed["candidate_id"]):
                raise research_seed_module.ResearchSeedError("native L1 activation candidate mismatch")
            if str(payload.get("round_id") or "") != str(seed["round_id"]):
                raise research_seed_module.ResearchSeedError("native L1 activation round mismatch")
            if payload.get("research_seed") != research_seed_module.manifest_entry(seed):
                raise research_seed_module.ResearchSeedError("native L1 activation ResearchSeed changed")
            run_id = str(payload.get("acquisition_run_id") or "")
            expected = _activation_payload(project, seed, run_id)
            if payload != expected:
                raise research_seed_module.ResearchSeedError(
                    "native L1 activation no longer matches its immutable binding"
                )
            expected_path = _activation_path(
                project, seed, int(payload["evidence_pack_version"]), run_id
            ).resolve()
            if path.resolve() != expected_path:
                raise research_seed_module.ResearchSeedError(
                    "native L1 activation path does not match its pack version/run"
                )
            activations.append(payload)
        transaction_root = _retry_transactions_dir(project, seed)
        if transaction_root.is_dir():
            for commit_path in sorted(transaction_root.glob("*/commit.json")):
                transaction = _load_retry_transaction(
                    project, seed, commit_path.parent
                )
                activations.append(transaction["activation"])
        activations.sort(key=lambda item: int(item["evidence_pack_version"]))
        for index, item in enumerate(activations, start=1):
            if int(item["evidence_pack_version"]) != index:
                raise research_seed_module.ResearchSeedError(
                    "native L1 activation versions are not contiguous from v1"
                )
            if index == 1:
                if item.get("parent_pack_sha256") not in (None, ""):
                    raise research_seed_module.ResearchSeedError(
                        "native L1 v1 activation must not have a parent pack"
                    )
            else:
                previous = activations[index - 2]
                if item.get("parent_pack_sha256") != previous.get(
                    "evidence_pack_content_sha256"
                ):
                    raise research_seed_module.ResearchSeedError(
                        "native L1 activation parent lineage is discontinuous"
                    )
                if not str(item.get("source_gap_request_id") or ""):
                    raise research_seed_module.ResearchSeedError(
                        "native L1 retry activation requires source_gap_request_id"
                    )
        return activations

    def commit_l1_native_retry(project_dir, seed, parent_pack_manifest,
                               pack_manifest, acquisition_run_id,
                               retry_authorization, *, failure_step=None) -> dict:
        """Commit binding, consumption, and activation as one filesystem transaction."""
        from research_loop import l05_curie

        allowed_failures = {
            None, "before_stage", "after_binding", "after_consumption",
            "during_activation",
        }
        if failure_step not in allowed_failures:
            raise research_seed_module.ResearchSeedError(
                f"unknown injected retry failure step: {failure_step}"
            )
        project = Path(project_dir)
        try:
            authorization = l05_curie.validate_gap_retry_authorization(
                seed, retry_authorization
            )
            authorization_id = str(authorization["authorization_id"])
            final_dir = _retry_transaction_dir(
                project, seed, authorization_id
            )
        except (KeyError, TypeError, ValueError, l05_curie.CurieContractError) as exc:
            raise research_seed_module.ResearchSeedError(
                f"native L05 retry authorization is invalid: {exc}"
            ) from exc

        if final_dir.exists():
            return _load_retry_transaction(project, seed, final_dir)

        active_run_id = active_l1_native_evidence_run_id(project, seed)
        if not active_run_id:
            raise research_seed_module.ResearchSeedError(
                "native L05 retry requires an active parent binding"
            )
        active_binding = load_l1_native_evidence_binding(
            project, seed, active_run_id
        )
        if str(active_binding["pack_lineage"]["content_sha256"]) != str(
            authorization["parent_pack_sha256"]
        ):
            raise research_seed_module.ResearchSeedError(
                "native L05 retry parent is not the current active pack"
            )

        binding = _payload(
            project, seed, pack_manifest, acquisition_run_id,
            research_seed_module, authorization,
        )
        if int(binding["pack_lineage"]["version"]) <= 1:
            raise research_seed_module.ResearchSeedError(
                "native L05 retry transaction requires EvidencePack version greater than one"
            )
        consumption = l05_curie.build_gap_retry_consumption(
            seed, authorization, acquisition_run_id
        )

        def inject(step: str) -> None:
            if failure_step == step:
                raise research_seed_module.ResearchSeedError(
                    f"injected native L05 retry failure at {step}"
                )

        inject("before_stage")
        transaction_root = _retry_transactions_dir(project, seed)
        transaction_root.mkdir(parents=True, exist_ok=True)
        staging_dir = transaction_root / (
            f".staging-{authorization_id}-{uuid4().hex}"
        )
        staging_dir.mkdir()
        stage_binding = staging_dir / "binding.json"
        stage_consumption = staging_dir / "consumption.json"
        stage_activation = staging_dir / "activation.json"
        final_binding = final_dir / "binding.json"
        final_consumption = final_dir / "consumption.json"
        final_activation = final_dir / "activation.json"

        binding_raw = _write_durable_json(stage_binding, binding)
        inject("after_binding")
        consumption_raw = _write_durable_json(stage_consumption, consumption)
        binding_entry = _entry_at_path(
            project, seed, acquisition_run_id, binding, final_binding,
            artifact_sha256=hashlib.sha256(binding_raw).hexdigest(),
        )
        lineage = binding["pack_lineage"]
        activation = {
            "schema_version": NATIVE_EVIDENCE_ACTIVATION_SCHEMA_VERSION,
            "candidate_id": str(seed["candidate_id"]),
            "round_id": str(seed["round_id"]),
            "research_seed": research_seed_module.manifest_entry(seed),
            "acquisition_run_id": str(acquisition_run_id),
            "evidence_pack_version": int(lineage["version"]),
            "evidence_pack_content_sha256": str(lineage["content_sha256"]),
            "parent_pack_sha256": lineage.get("parent_pack_sha256"),
            "source_gap_request_id": lineage.get("source_gap_request_id"),
            "binding": binding_entry,
        }
        inject("after_consumption")
        activation_raw = _write_durable_json(stage_activation, activation)
        inject("during_activation")
        commit = {
            "schema_version": NATIVE_RETRY_COMMIT_SCHEMA_VERSION,
            "authorization_id": authorization_id,
            "candidate_id": str(seed["candidate_id"]),
            "round_id": str(seed["round_id"]),
            "acquisition_run_id": str(acquisition_run_id),
            "authorization": authorization,
            "artifacts": {
                "binding": {
                    "path": final_binding.relative_to(project).as_posix(),
                    "sha256": hashlib.sha256(binding_raw).hexdigest(),
                },
                "consumption": {
                    "path": final_consumption.relative_to(project).as_posix(),
                    "sha256": hashlib.sha256(consumption_raw).hexdigest(),
                },
                "activation": {
                    "path": final_activation.relative_to(project).as_posix(),
                    "sha256": hashlib.sha256(activation_raw).hexdigest(),
                },
            },
        }
        _write_durable_json(staging_dir / "commit.json", commit)
        try:
            os.replace(staging_dir, final_dir)
        except FileExistsError:
            return _load_retry_transaction(project, seed, final_dir)
        return _load_retry_transaction(project, seed, final_dir)

    def activate_l1_native_evidence_binding(project_dir, seed,
                                            acquisition_run_id) -> dict:
        project = Path(project_dir)
        committed = _find_retry_transaction_by_run(
            project, seed, str(acquisition_run_id)
        )
        if committed is not None:
            return committed["activation"]
        payload = _activation_payload(project, seed, acquisition_run_id)
        version = int(payload["evidence_pack_version"])
        existing = _load_activations(project, seed)
        if existing:
            latest = existing[-1]
            if (version == int(latest["evidence_pack_version"]) and
                    str(acquisition_run_id) == str(latest["acquisition_run_id"])):
                return latest
            if version != int(latest["evidence_pack_version"]) + 1:
                raise research_seed_module.ResearchSeedError(
                    "native L1 activation must advance exactly one EvidencePack version"
                )
            if payload.get("parent_pack_sha256") != latest.get(
                "evidence_pack_content_sha256"
            ):
                raise research_seed_module.ResearchSeedError(
                    "native L1 activation parent pack does not match current active pack"
                )
        elif version != 1:
            raise research_seed_module.ResearchSeedError(
                "first native L1 activation must bind EvidencePack v1"
            )
        path = _activation_path(project, seed, version, acquisition_run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = _canonical_bytes(payload)
        if path.exists() and path.read_bytes() != raw:
            raise research_seed_module.ResearchSeedError(
                "native L1 activation receipt already exists with different provenance"
            )
        if not path.exists():
            path.write_bytes(raw)
        _load_activations(project, seed)
        return payload

    def active_l1_native_evidence_run_id(project_dir, seed):
        activations = _load_activations(Path(project_dir), seed)
        if not activations:
            return None
        return str(activations[-1]["acquisition_run_id"])

    research_seed_module.NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION = NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION
    research_seed_module.NATIVE_EVIDENCE_ACTIVATION_SCHEMA_VERSION = NATIVE_EVIDENCE_ACTIVATION_SCHEMA_VERSION
    research_seed_module.write_l1_native_evidence_binding = write_l1_native_evidence_binding
    research_seed_module.load_l1_native_evidence_binding = load_l1_native_evidence_binding
    research_seed_module.native_evidence_binding_manifest_entry = native_evidence_binding_manifest_entry
    research_seed_module.evidence_binding_manifest_entry = evidence_binding_manifest_entry
    research_seed_module.unique_l1_native_evidence_run_id = unique_l1_native_evidence_run_id
    research_seed_module.commit_l1_native_retry = commit_l1_native_retry
    research_seed_module.load_l1_native_retry_commit = load_l1_native_retry_commit
    research_seed_module.activate_l1_native_evidence_binding = activate_l1_native_evidence_binding
    research_seed_module.active_l1_native_evidence_run_id = active_l1_native_evidence_run_id
    research_seed_module._l05_native_binding_installed = True
