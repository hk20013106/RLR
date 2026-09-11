"""Canonical L8.5 literature verification.

L8.5 is a post-result verifier, not a second Deep Research acquisition stage.
The controller derives queries from actual L7/L8 findings, sends them through
the existing Curie multisource discovery layer, retains canonical paper
identity there, and only admits source-located evidence to the existing
semantic verifier. A DOI, PMID, or title without located source evidence never
becomes a verification verdict.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Callable

from research_loop import research_seed
from research_loop.compatibility import get_profile
from research_loop.delta import _delta_for_candidate, artifact_for_node
from research_loop.hypothesis_ledger import binding_path
from research_loop.l05_curie import europepmc, multisource, selector
from research_loop.l05_curie.contracts import CurieContractError
from research_loop.l05_curie.semantic_verifier import (
    SemanticEvidenceVerifier,
    reasoning_authorized,
)


RUN_SCHEMA_VERSION = "L85CanonicalLiteratureVerification/v1"
RECEIPT_SCHEMA_VERSION = "L85CanonicalVerificationReceipt/v1"
_VERDICTS = {"supports", "contradicts", "unresolved"}
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+/-]*")
_STOPWORDS = {
    "a", "an", "and", "are", "be", "by", "for", "from", "in", "is", "of",
    "on", "or", "the", "to", "with", "this", "that", "result", "results",
    "finding", "evidence", "verified", "observed",
}


class L85VerificationError(ValueError):
    """Raised when canonical L8.5 verification cannot be completed safely."""


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
    )


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise L85VerificationError(f"{name} must be non-empty")
    return text


def active_findings(
    l7_delta: dict | None,
    l8_delta: dict | None,
    *,
    active_hypothesis_ids: list[str] | None = None,
) -> list[dict]:
    """Project actual execution/audit results into one finding per hypothesis."""
    l7 = l7_delta if isinstance(l7_delta, dict) else {}
    l8 = l8_delta if isinstance(l8_delta, dict) else {}
    by_id: dict[str, dict] = {}

    def add(hypothesis_id: object, text: object, source: str) -> None:
        hid = str(hypothesis_id or "").strip()
        statement = str(text or "").strip()
        if not hid or not statement:
            return
        entry = by_id.setdefault(
            hid,
            {"finding_id": hid, "text": statement, "sources": []},
        )
        if source not in entry["sources"]:
            entry["sources"].append(source)

    for result in l7.get("results") or []:
        if not isinstance(result, dict):
            continue
        statement = result.get("summary") or result.get("result_key")
        for hid in result.get("hypothesis_ids") or []:
            add(hid, statement, "L7")

    for assessment in l8.get("evidence_assessments") or []:
        if not isinstance(assessment, dict):
            continue
        reason = assessment.get("reason") or assessment.get("evidence_id")
        for relation in assessment.get("relations") or []:
            if isinstance(relation, dict):
                add(relation.get("hypothesis_id"), relation.get("reason") or reason, "L8")

    if active_hypothesis_ids:
        requested = [str(item).strip() for item in active_hypothesis_ids if str(item).strip()]
        missing = [item for item in requested if item not in by_id]
        if missing:
            raise L85VerificationError(
                "active findings are missing actual L7/L8 result context: "
                + ", ".join(missing)
            )
        ordered = [by_id[item] for item in requested]
    else:
        ordered = [by_id[key] for key in sorted(by_id)]
    if not ordered:
        raise L85VerificationError("L8.5 requires actual L7/L8 findings")
    return copy.deepcopy(ordered)


def finding_queries(findings: list[dict], *, max_chars: int = 240) -> list[str]:
    """Derive bounded deterministic search strings from finding text."""
    queries = []
    for finding in findings:
        finding_id = _text(finding.get("finding_id"), "finding_id")
        words = []
        for token in _TOKEN.findall(str(finding.get("text") or "")):
            lowered = token.casefold()
            if lowered in _STOPWORDS or len(lowered) < 3:
                continue
            if lowered not in {item.casefold() for item in words}:
                words.append(token)
        query = " ".join(words)
        if not query:
            raise L85VerificationError(f"finding {finding_id} has no searchable terms")
        queries.append(query[:max_chars].strip())
    return queries


def build_query_plan(seed: dict, findings: list[dict]) -> dict:
    """Use the canonical Curie planner; this module does not own query schema."""
    try:
        return multisource.build_multisource_query_plan(
            seed,
            seed_sha256=research_seed.seed_sha256(seed),
            round_index=int(str(seed.get("round_id") or "1")),
            explicit_queries=finding_queries(findings),
            providers=list(multisource._PROVIDERS),
        )
    except (CurieContractError, ValueError, TypeError) as exc:
        raise L85VerificationError(f"canonical L8.5 query planning failed: {exc}") from exc


def validate_finding_verdicts(
    findings: list[dict],
    verdicts: list[dict],
    *,
    known_evidence_ids: set[str],
) -> list[dict]:
    """Require exactly one closed verdict for every active finding."""
    if not isinstance(findings, list) or not findings:
        raise ValueError("L8.5 findings must be a non-empty list")
    if not isinstance(verdicts, list):
        raise ValueError("L8.5 verdicts must be a list")
    expected = [str(item.get("finding_id") or "").strip() for item in findings]
    if any(not item for item in expected) or len(expected) != len(set(expected)):
        raise ValueError("L8.5 findings must have unique finding_id values")
    grouped: dict[str, list[dict]] = {}
    for item in verdicts:
        if not isinstance(item, dict):
            raise ValueError("L8.5 verdict must be an object")
        finding_id = str(item.get("finding_id") or "").strip()
        if finding_id not in expected:
            raise ValueError(f"L8.5 verdict references unknown finding {finding_id!r}")
        grouped.setdefault(finding_id, []).append(item)
    missing = [item for item in expected if len(grouped.get(item, [])) != 1]
    if missing:
        raise ValueError(
            "L8.5 requires exactly one verdict per active finding: "
            + ", ".join(missing)
        )

    known = {str(item) for item in (known_evidence_ids or set())}
    normalized = []
    for finding_id in expected:
        item = grouped[finding_id][0]
        verdict = str(item.get("verdict") or "").strip().casefold()
        if verdict not in _VERDICTS:
            raise ValueError(
                f"L8.5 verdict for {finding_id} must be supports, contradicts, or unresolved"
            )
        evidence_ids = item.get("evidence_ids")
        if not isinstance(evidence_ids, list) or len(evidence_ids) != len(set(map(str, evidence_ids))):
            raise ValueError(f"L8.5 evidence_ids for {finding_id} must be a unique list")
        evidence_ids = [str(value).strip() for value in evidence_ids if str(value).strip()]
        unknown = [value for value in evidence_ids if value not in known]
        if unknown:
            raise ValueError(
                f"L8.5 verdict for {finding_id} references non-located evidence {unknown[0]}"
            )
        if verdict in {"supports", "contradicts"} and not evidence_ids:
            raise ValueError(
                f"L8.5 {verdict} verdict for {finding_id} requires located evidence"
            )
        normalized.append({
            "finding_id": finding_id,
            "verdict": verdict,
            "evidence_ids": evidence_ids,
            "reason": str(item.get("reason") or "").strip(),
        })
    return normalized


def adjudicate_findings(
    findings: list[dict],
    evidence: list[dict],
    *,
    semantic_assessor: Callable | None,
    assessor_id: str = "l85-semantic-adjudicator/v1",
) -> tuple[list[dict], list[dict]]:
    """Map source-located extracts through the existing semantic verifier."""
    evidence = [item for item in evidence if isinstance(item, dict)]
    known_ids = {str(item.get("evidence_id") or "") for item in evidence}
    semantic_results: list[dict] = []
    verdicts: list[dict] = []
    verifier = (
        SemanticEvidenceVerifier(assessor=semantic_assessor, assessor_id=assessor_id)
        if callable(semantic_assessor)
        else None
    )
    for finding in findings:
        finding_id = str(finding["finding_id"])
        claim = str(finding["text"])
        if verifier is None:
            verdicts.append({
                "finding_id": finding_id,
                "verdict": "unresolved",
                "evidence_ids": [],
                "reason": "no independent semantic assessor was available",
            })
            continue
        assessments = []
        for extract in evidence:
            try:
                result = verifier.verify(extract, claim=claim)
            except CurieContractError:
                continue
            semantic_results.append(result)
            assessments.append(result)
        passing = [
            item for item in assessments
            if item.get("verdict") == "PASS"
            and item.get("entailment") in {"SUPPORTED", "CONTRADICTED"}
        ]
        if not passing:
            verdicts.append({
                "finding_id": finding_id,
                "verdict": "unresolved",
                "evidence_ids": [],
                "reason": "located evidence did not yield an authorized semantic verdict",
            })
            continue
        # The first authorized assessment is deterministic because evidence is
        # supplied in canonical pack order. Conflicting papers remain visible in
        # semantic_results; the closed finding verdict stays one-per-finding.
        first = passing[0]
        verdicts.append({
            "finding_id": finding_id,
            "verdict": (
                "supports" if first["entailment"] == "SUPPORTED" else "contradicts"
            ),
            "evidence_ids": [str(first["evidence_id"])],
            "reason": str(first.get("reason") or ""),
        })
    return (
        validate_finding_verdicts(findings, verdicts, known_evidence_ids=known_ids),
        semantic_results,
    )


def _default_transports(project_dir: Path, candidate_id: str, run_id: str, timeout: int):
    common = {
        "project_dir": project_dir,
        "candidate_id": candidate_id,
        "run_id": run_id,
        "timeout": timeout,
    }
    return {
        "europe-pmc": europepmc.EuropePmcTransport(**common),
        "pubmed": multisource.PubMedTransport(**common),
        "openalex": multisource.OpenAlexTransport(**common),
        "crossref": multisource.CrossrefTransport(**common),
        "semantic-scholar": multisource.SemanticScholarTransport(**common),
    }


def _run_manifest_path(project_dir: Path, candidate_id: str, run_id: str) -> Path:
    return (
        project_dir
        / "08_Audit"
        / "l85_literature_verification"
        / str(candidate_id)
        / f"{run_id}.json"
    )


def load_run_manifest(project_dir: str | Path, candidate_id: str, run_id: str) -> dict:
    path = _run_manifest_path(Path(project_dir), candidate_id, run_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise L85VerificationError(f"L8.5 canonical run is unreadable: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != RUN_SCHEMA_VERSION:
        raise L85VerificationError("L8.5 canonical run schema is invalid")
    expected_hash = str(payload.get("run_sha256") or "")
    body = dict(payload)
    body.pop("run_sha256", None)
    if expected_hash != _sha(body):
        raise L85VerificationError("L8.5 canonical run hash does not match its bytes")
    return payload


def run_ids_for_candidate(project_dir: str | Path, candidate_id: str) -> list[str]:
    """Return valid immutable native runs in stable filename order."""
    root = Path(project_dir)
    directory = root / "08_Audit" / "l85_literature_verification" / str(candidate_id)
    if not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            run_id = str(payload.get("run_id") or "")
            if run_id and path.name == f"{run_id}.json":
                loaded = load_run_manifest(root, candidate_id, run_id)
                if loaded.get("candidate_id") == str(candidate_id):
                    found.append(run_id)
        except (OSError, json.JSONDecodeError, L85VerificationError):
            continue
    return found


def _bound_source_file(project_dir: Path, value: object, label: str) -> Path:
    relative = Path(str(value or ""))
    if not str(value or "").strip() or relative.is_absolute():
        raise L85VerificationError(f"L8.5 {label} path is invalid")
    root = project_dir.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise L85VerificationError(f"L8.5 {label} path escapes the project") from exc
    return path


def audit_run_manifest(
    project_dir: str | Path,
    candidate_id: str,
    *,
    run_id: str | None = None,
) -> tuple[bool, str, dict | None]:
    """Audit one native run without choosing an arbitrary filesystem latest."""
    if run_id:
        selected = str(run_id).strip()
    else:
        ids = run_ids_for_candidate(project_dir, candidate_id)
        if not ids:
            return False, "native L8.5 canonical literature run is missing", None
        if len(ids) != 1:
            return False, "native L8.5 canonical literature run is ambiguous", None
        selected = ids[0]
    try:
        run = load_run_manifest(project_dir, candidate_id, selected)
        located = [
            item for item in run.get("located_evidence") or []
            if isinstance(item, dict)
        ]
        located_ids = {
            str(item.get("evidence_id") or "")
            for item in located
            if str(item.get("evidence_id") or "")
        }
        verdicts = validate_finding_verdicts(
            list(run.get("findings") or []),
            list(run.get("verdicts") or []),
            known_evidence_ids=located_ids,
        )
        semantic_by_id = {
            str(item.get("evidence_id") or ""): item
            for item in run.get("semantic_verifications") or []
            if isinstance(item, dict) and str(item.get("evidence_id") or "")
        }
        root = Path(project_dir)
        for item in located:
            if item.get("verification_status") != "LOCATED":
                raise L85VerificationError(
                    f"located evidence is not LOCATED: {item.get('evidence_id')}"
                )
            retrieval = item.get("retrieval")
            if not isinstance(retrieval, dict):
                raise L85VerificationError(
                    f"located evidence has no retrieval receipt: {item.get('evidence_id')}"
                )
            source_path = retrieval.get("snapshot_path") or retrieval.get("artifact_path")
            source_sha = str(
                retrieval.get("source_sha256")
                or retrieval.get("artifact_sha256")
                or ""
            ).lower()
            if not re.fullmatch(r"[0-9a-f]{64}", source_sha):
                raise L85VerificationError(
                    f"located evidence has invalid source SHA-256: {item.get('evidence_id')}"
                )
            source_file = _bound_source_file(root, source_path, "source snapshot")
            if not source_file.is_file():
                raise L85VerificationError(
                    f"located evidence source snapshot is missing: {source_path}"
                )
            if hashlib.sha256(source_file.read_bytes()).hexdigest() != source_sha:
                raise L85VerificationError(
                    f"located evidence source snapshot hash mismatch: {source_path}"
                )
        for verdict in verdicts:
            if verdict["verdict"] not in {"supports", "contradicts"}:
                continue
            for evidence_id in verdict["evidence_ids"]:
                semantic = semantic_by_id.get(evidence_id)
                if semantic is None or not reasoning_authorized(semantic):
                    raise L85VerificationError(
                        f"semantic authorization is missing for evidence: {evidence_id}"
                    )
        return True, "", run
    except (L85VerificationError, TypeError, ValueError) as exc:
        return False, str(exc), None


def persist_run_manifest(
    project_dir: str | Path,
    candidate_id: str,
    *,
    run_id: str,
    payload: dict,
) -> dict:
    root = Path(project_dir)
    path = _run_manifest_path(root, candidate_id, run_id)
    body = {
        "schema_version": RUN_SCHEMA_VERSION,
        "receipt_schema": RECEIPT_SCHEMA_VERSION,
        "run_id": str(run_id),
        "candidate_id": str(candidate_id),
        **copy.deepcopy(payload),
    }
    body.pop("run_sha256", None)
    body["run_sha256"] = _sha(body)
    raw = _canonical_bytes(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise L85VerificationError(
            f"L8.5 canonical run already exists with different bytes: {path}"
        )
    if not path.exists():
        path.write_bytes(raw)
    return load_run_manifest(root, candidate_id, run_id)


def run_native_l85(
    project_dir: str | Path,
    candidate_id: str,
    *,
    semantic_assessor: Callable | None = None,
    semantic_assessor_id: str = "l85-semantic-adjudicator/v1",
    active_hypothesis_ids: list[str] | None = None,
    transports: dict[str, object] | None = None,
    timeout: int = 20,
    page_size: int = 25,
) -> dict:
    """Run canonical discovery/source verification and persist one immutable run."""
    project = Path(project_dir)
    seed = research_seed.load_l1_research_seed(project, candidate_id)

    def load_delta(key: str) -> dict:
        path = _delta_for_candidate(project, key, candidate_id)
        if not path or not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    l7 = load_delta("L7_turing")
    try:
        binding = json.loads(binding_path(project).read_text(encoding="utf-8"))
        profile = get_profile(str(binding["profile_id"]))
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise L85VerificationError(
            f"L8.5 project profile binding is unavailable: {exc}"
        ) from exc
    l8 = load_delta(artifact_for_node(profile, "L8").storage_key)
    findings = active_findings(
        l7,
        l8,
        active_hypothesis_ids=active_hypothesis_ids,
    )
    plan = build_query_plan(seed, findings)
    run_id = "L85_" + _sha({
        "seed_sha256": research_seed.seed_sha256(seed),
        "finding_ids": [item["finding_id"] for item in findings],
        "query_plan_id": plan["plan_id"],
    })[:20]
    if transports is None:
        transports = _default_transports(project, candidate_id, run_id, timeout)
    discovery = multisource.run_multisource_discovery_strict(
        plan,
        transports,
        seed_sha256=research_seed.seed_sha256(seed),
        page_size=page_size,
        allow_partial=True,
    )
    records = list(discovery.get("records") or [])
    if not records:
        raise L85VerificationError(
            "canonical L8.5 discovery returned no real literature records"
        )
    selected = selector.select_candidates_strict(
        records,
        seed=seed,
        scorer=lambda _record, _seed: {
            "relevance": 0.5,
            "directness": 0.5,
            "methodological_value": 0.0,
            "contradiction_value": 0.5,
            "evidence_diversity": 0.5,
            "reason": "canonical L8.5 record retained for source verification",
        },
        eligibility=lambda record: (
            bool(record.get("identifiers")),
            "CANONICAL_IDENTITY_REQUIRED",
        ),
        max_papers=3,
        query_ids={str(item["query_id"]) for item in plan["queries"]},
    )
    selected_ids = set(selected.get("included_paper_ids") or [])
    selected_records = [
        record for record in records if str(record.get("paper_id") or "") in selected_ids
    ]
    located: list[dict] = []
    retrieval_receipts = []
    for record in selected_records:
        identifiers = record.get("identifiers")
        identifiers = identifiers if isinstance(identifiers, dict) else {}
        pmcid = multisource.normalize_pmcid(identifiers.get("pmcid"))
        if not pmcid:
            continue
        retriever = europepmc.EuropePmcEvidenceRetriever(
            project, candidate_id=candidate_id, run_id=run_id, timeout=timeout
        )
        verifier = europepmc.EuropePmcEvidenceVerifier(project, candidate_id=candidate_id)
        try:
            retrieval = retriever.retrieve(
                {**record, "identifiers": {**identifiers, "pmcid": pmcid}},
                seed=seed,
            )
            verified = verifier.verify(
                retrieval["snapshot"], retrieval["candidates"]
            )
        except CurieContractError:
            continue
        located.extend(verified)
        retrieval_receipts.append(retrieval["snapshot"])
    verdicts, semantic_results = adjudicate_findings(
        findings,
        located,
        semantic_assessor=semantic_assessor,
        assessor_id=semantic_assessor_id,
    )
    return persist_run_manifest(
        project,
        candidate_id,
        run_id=run_id,
        payload={
            "research_seed": research_seed.manifest_entry(seed),
            "query_plan": plan,
            "discovery": discovery,
            "selected_paper_ids": sorted(selected_ids),
            "source_snapshots": retrieval_receipts,
            "located_evidence": located,
            "semantic_verifications": semantic_results,
            "findings": findings,
            "verdicts": verdicts,
            "receipt": {
                "query_plan_id": str(plan["plan_id"]),
                "discovery_record_count": len(records),
                "located_evidence_ids": [
                    str(item["evidence_id"]) for item in located
                ],
                "semantic_verification_ids": [
                    str(item["verification_id"]) for item in semantic_results
                ],
            },
        },
    )


__all__ = [
    "RUN_SCHEMA_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "L85VerificationError",
    "active_findings",
    "finding_queries",
    "build_query_plan",
    "validate_finding_verdicts",
    "adjudicate_findings",
    "load_run_manifest",
    "run_ids_for_candidate",
    "audit_run_manifest",
    "persist_run_manifest",
    "run_native_l85",
]
