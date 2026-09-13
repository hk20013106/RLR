"""Canonical, result-driven L8.5 literature verification.

This module owns neither a second retriever nor evidence identity.  It derives
queries from completed L7/L8 findings, uses Curie discovery, and admits only
source-located evidence to a closed finding verdict.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from research_loop import research_seed
from research_loop.compatibility import get_profile
from research_loop.delta import _delta_for_candidate, artifact_for_node
from research_loop.hypothesis_ledger import binding_path
from research_loop.l05_curie import europepmc, multisource, selector
from research_loop.l05_curie.contracts import CurieContractError
from research_loop.l05_curie.semantic_verifier import SemanticEvidenceVerifier


RUN_SCHEMA_VERSION = "L85CanonicalLiteratureVerification/v1"
_VERDICTS = {"supports", "contradicts", "unresolved"}
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+/-]*")
_STOPWORDS = {
    "a", "an", "and", "are", "be", "by", "for", "from", "in", "is",
    "of", "on", "or", "the", "to", "with", "this", "that", "result",
    "results", "finding", "evidence", "verified", "observed",
}


class L85VerificationError(ValueError):
    """Raised when a canonical L8.5 run cannot be proved safe."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def active_findings(l7_delta: dict | None, l8_delta: dict | None) -> list[dict]:
    """Derive exactly one finding per active hypothesis from actual results."""
    by_id: dict[str, dict] = {}

    def add(hypothesis_id: object, text: object, source: str) -> None:
        finding_id = str(hypothesis_id or "").strip()
        statement = str(text or "").strip()
        if not finding_id or not statement:
            return
        item = by_id.setdefault(
            finding_id, {"finding_id": finding_id, "text": statement, "sources": []}
        )
        if source not in item["sources"]:
            item["sources"].append(source)

    for result in (l7_delta or {}).get("results") or []:
        if isinstance(result, dict):
            for hypothesis_id in result.get("hypothesis_ids") or []:
                add(hypothesis_id, result.get("summary") or result.get("result_key"), "L7")
    for assessment in (l8_delta or {}).get("evidence_assessments") or []:
        if isinstance(assessment, dict):
            for relation in assessment.get("relations") or []:
                if isinstance(relation, dict):
                    add(
                        relation.get("hypothesis_id"),
                        relation.get("reason") or assessment.get("reason") or assessment.get("evidence_id"),
                        "L8",
                    )
    if not by_id:
        raise L85VerificationError("L8.5 requires actual L7/L8 findings")
    return copy.deepcopy([by_id[key] for key in sorted(by_id)])


def finding_queries(findings: list[dict], *, max_chars: int = 240) -> list[str]:
    """Derive bounded, deterministic queries from actual findings."""
    queries = []
    for finding in findings:
        finding_id = str(finding.get("finding_id") or "").strip()
        if not finding_id:
            raise L85VerificationError("finding_id must be non-empty")
        words = []
        for token in _TOKEN.findall(str(finding.get("text") or "")):
            if len(token) < 3 or token.casefold() in _STOPWORDS:
                continue
            if token.casefold() not in {item.casefold() for item in words}:
                words.append(token)
        query = " ".join(words)[:max_chars].strip()
        if not query:
            raise L85VerificationError(f"finding {finding_id} has no searchable terms")
        queries.append(query)
    return queries


def build_query_plan(seed: dict, findings: list[dict]) -> dict:
    """Delegate planning to Curie; this module owns no query schema."""
    try:
        return multisource.build_multisource_query_plan(
            seed,
            seed_sha256=research_seed.seed_sha256(seed),
            round_index=int(str(seed.get("round_id") or "1")),
            explicit_queries=finding_queries(findings),
            providers=list(multisource._PROVIDERS),
        )
    except (CurieContractError, TypeError, ValueError) as exc:
        raise L85VerificationError(f"canonical L8.5 query planning failed: {exc}") from exc


def validate_finding_verdicts(
    findings: list[dict], verdicts: list[dict], *, known_evidence_ids: set[str]
) -> list[dict]:
    """Require one closed verdict per finding; identifiers alone are insufficient."""
    expected = [str(item.get("finding_id") or "").strip() for item in findings]
    if not expected or any(not item for item in expected) or len(expected) != len(set(expected)):
        raise ValueError("L8.5 findings must have unique finding_id values")
    grouped: dict[str, list[dict]] = {}
    for item in verdicts:
        if not isinstance(item, dict) or str(item.get("finding_id") or "") not in expected:
            raise ValueError("L8.5 verdict references an unknown finding")
        grouped.setdefault(str(item["finding_id"]), []).append(item)
    missing = [finding_id for finding_id in expected if len(grouped.get(finding_id, [])) != 1]
    if missing:
        raise ValueError("L8.5 requires exactly one verdict per active finding: " + ", ".join(missing))
    known = {str(item) for item in known_evidence_ids}
    normalized = []
    for finding_id in expected:
        item = grouped[finding_id][0]
        verdict = str(item.get("verdict") or "").casefold()
        evidence_ids = [str(value).strip() for value in item.get("evidence_ids") or [] if str(value).strip()]
        if verdict not in _VERDICTS:
            raise ValueError("L8.5 verdict must be supports, contradicts, or unresolved")
        if len(evidence_ids) != len(set(evidence_ids)) or any(value not in known for value in evidence_ids):
            raise ValueError(f"L8.5 verdict for {finding_id} references non-located evidence")
        if verdict in {"supports", "contradicts"} and not evidence_ids:
            raise ValueError(f"L8.5 {verdict} verdict for {finding_id} requires located evidence")
        normalized.append({
            "finding_id": finding_id, "verdict": verdict,
            "evidence_ids": evidence_ids, "reason": str(item.get("reason") or "").strip(),
        })
    return normalized


def _run_manifest_path(project: Path, candidate_id: str, run_id: str) -> Path:
    return project / "08_Audit" / "l85_literature_verification" / str(candidate_id) / f"{run_id}.json"


def persist_run_manifest(project_dir: str | Path, candidate_id: str, *, run_id: str, payload: dict) -> dict:
    """Persist an immutable, byte-bound canonical L8.5 result."""
    project = Path(project_dir)
    path = _run_manifest_path(project, candidate_id, run_id)
    body = {"schema_version": RUN_SCHEMA_VERSION, "run_id": str(run_id), "candidate_id": str(candidate_id), **copy.deepcopy(payload)}
    body.pop("run_sha256", None)
    body["run_sha256"] = _sha(body)
    raw = _canonical_bytes(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise L85VerificationError(f"L8.5 canonical run already exists with different bytes: {path}")
    if not path.exists():
        path.write_bytes(raw)
    return load_run_manifest(project, candidate_id, run_id)


def load_run_manifest(project_dir: str | Path, candidate_id: str, run_id: str) -> dict:
    path = _run_manifest_path(Path(project_dir), candidate_id, run_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise L85VerificationError(f"L8.5 canonical run is unreadable: {path}") from exc
    body = dict(payload)
    expected = str(body.pop("run_sha256", ""))
    if payload.get("schema_version") != RUN_SCHEMA_VERSION or expected != _sha(body):
        raise L85VerificationError("L8.5 canonical run hash does not match its bytes")
    return payload


def audit_run_manifest(project_dir: str | Path, candidate_id: str, *, run_id: str) -> tuple[bool, str, dict | None]:
    """Revalidate run bytes and every source snapshot referenced as LOCATED."""
    try:
        run = load_run_manifest(project_dir, candidate_id, run_id)
        located = [item for item in run.get("located_evidence") or [] if isinstance(item, dict)]
        located_ids = {str(item.get("evidence_id") or "") for item in located}
        validate_finding_verdicts(run.get("findings") or [], run.get("verdicts") or [], known_evidence_ids=located_ids)
        root = Path(project_dir).resolve()
        for item in located:
            if item.get("verification_status") != "LOCATED":
                raise L85VerificationError("located evidence is not LOCATED")
            retrieval = item.get("retrieval") or {}
            relative = Path(str(retrieval.get("snapshot_path") or retrieval.get("artifact_path") or ""))
            source = (root / relative).resolve()
            if relative.is_absolute() or not source.is_file() or root not in source.parents and source != root:
                raise L85VerificationError("located evidence source snapshot is missing")
            recorded_sha = str(retrieval.get("source_sha256") or retrieval.get("artifact_sha256") or "")
            if hashlib.sha256(source.read_bytes()).hexdigest() != recorded_sha:
                raise L85VerificationError("located evidence source snapshot hash mismatch")
        return True, "", run
    except (L85VerificationError, TypeError, ValueError) as exc:
        return False, str(exc), None


def _adjudicate(findings: list[dict], evidence: list[dict], assessor, assessor_id: str) -> tuple[list[dict], list[dict]]:
    verifier = SemanticEvidenceVerifier(assessor=assessor, assessor_id=assessor_id) if callable(assessor) else None
    semantic, verdicts = [], []
    for finding in findings:
        authorized = []
        if verifier is not None:
            for item in evidence:
                try:
                    result = verifier.verify(item, claim=str(finding["text"]))
                except CurieContractError:
                    continue
                semantic.append(result)
                if result.get("verdict") == "PASS" and result.get("entailment") in {"SUPPORTED", "CONTRADICTED"}:
                    authorized.append(result)
        if authorized:
            first = authorized[0]
            verdicts.append({"finding_id": finding["finding_id"], "verdict": "supports" if first["entailment"] == "SUPPORTED" else "contradicts", "evidence_ids": [str(first["evidence_id"])], "reason": str(first.get("reason") or "")})
        else:
            verdicts.append({"finding_id": finding["finding_id"], "verdict": "unresolved", "evidence_ids": [], "reason": "no independent authorized semantic verdict"})
    return validate_finding_verdicts(findings, verdicts, known_evidence_ids={str(item.get("evidence_id") or "") for item in evidence}), semantic


def run_native_l85(project_dir: str | Path, candidate_id: str, *, semantic_assessor=None, semantic_assessor_id: str = "l85-semantic-adjudicator/v1", timeout: int = 20) -> dict:
    """Run the native Curie discovery/retrieval/verifier path from real L7/L8 findings."""
    project = Path(project_dir)
    seed = research_seed.load_l1_research_seed(project, candidate_id)
    try:
        binding = json.loads(binding_path(project).read_text(encoding="utf-8"))
        profile = get_profile(str(binding["profile_id"]))
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise L85VerificationError(f"L8.5 project profile binding is unavailable: {exc}") from exc

    def load_delta(key: str) -> dict:
        path = _delta_for_candidate(project, key, candidate_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8")) if path else {}
        except (OSError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    findings = active_findings(load_delta("L7_turing"), load_delta(artifact_for_node(profile, "L8").storage_key))
    plan = build_query_plan(seed, findings)
    run_id = "L85_" + _sha({"seed_sha256": research_seed.seed_sha256(seed), "finding_ids": [item["finding_id"] for item in findings], "query_plan_id": plan["plan_id"]})[:20]
    common = {"project_dir": project, "candidate_id": candidate_id, "run_id": run_id, "timeout": timeout}
    transports = {
        "europe-pmc": europepmc.EuropePmcTransport(**common),
        "pubmed": multisource.PubMedTransport(**common),
        "openalex": multisource.OpenAlexTransport(**common),
        "crossref": multisource.CrossrefTransport(**common),
        "semantic-scholar": multisource.SemanticScholarTransport(**common),
    }
    discovery = multisource.run_multisource_discovery_strict(plan, transports, seed_sha256=research_seed.seed_sha256(seed), page_size=25, allow_partial=True)
    records = list(discovery.get("records") or [])
    if not records:
        raise L85VerificationError("canonical L8.5 discovery returned no real literature records")
    selected = selector.select_candidates_strict(records, seed=seed, scorer=lambda _record, _seed: {"relevance": .5, "directness": .5, "methodological_value": 0, "contradiction_value": .5, "evidence_diversity": .5, "reason": "result-driven source verification"}, eligibility=lambda record: (bool(record.get("identifiers")), "CANONICAL_IDENTITY_REQUIRED"), max_papers=3, query_ids={str(item["query_id"]) for item in plan["queries"]})
    selected_ids = set(selected.get("included_paper_ids") or [])
    located, snapshots = [], []
    for record in records:
        if str(record.get("paper_id") or "") not in selected_ids:
            continue
        identifiers = record.get("identifiers") or {}
        pmcid = multisource.normalize_pmcid(identifiers.get("pmcid"))
        if not pmcid:
            continue
        try:
            retrieval = europepmc.EuropePmcEvidenceRetriever(project, candidate_id=candidate_id, run_id=run_id, timeout=timeout).retrieve({**record, "identifiers": {**identifiers, "pmcid": pmcid}}, seed=seed)
            located.extend(europepmc.EuropePmcEvidenceVerifier(project, candidate_id=candidate_id).verify(retrieval["snapshot"], retrieval["candidates"]))
            snapshots.append(retrieval["snapshot"])
        except CurieContractError:
            continue
    verdicts, semantic = _adjudicate(findings, located, semantic_assessor, semantic_assessor_id)
    return persist_run_manifest(project, candidate_id, run_id=run_id, payload={"research_seed": research_seed.manifest_entry(seed), "query_plan": plan, "discovery": discovery, "selected_paper_ids": sorted(selected_ids), "source_snapshots": snapshots, "located_evidence": located, "semantic_verifications": semantic, "findings": findings, "verdicts": verdicts})
