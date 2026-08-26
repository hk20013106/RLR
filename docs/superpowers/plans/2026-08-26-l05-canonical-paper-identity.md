# L0.5 Canonical Paper Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give L0.5 one provider-neutral owner for identifier normalization, paper identity, metadata fallback, identity-graph reconciliation, and deterministic deduplication, while keeping Europe PMC source identifiers as provenance only.

**Architecture:** `src/research_loop/l05_curie/multisource.py` becomes the sole owner of DOI/PMID/PMCID normalization, stable namespace priority, canonical `paper_id` derivation, and graph deduplication. `src/research_loop/l05_curie/europepmc.py` remains a Europe PMC field adapter and source-retrieval/verifier module: it extracts provider fields and calls the multisource canonical-record constructor, retaining `source` and `ext_id` in provenance rather than identity. Deduplication forms connected components over stable identifiers (or metadata fallback only when no stable identifier exists), rejects conflicting values in one stable namespace, recomputes each component's `paper_id` after merging, and sorts canonical output and provenance deterministically.

**Tech Stack:** Python 3, pytest, immutable L05 EvidencePack contracts.

---

## Global constraints

- Preserve the `UNVERIFIED -> LOCATED -> semantic admission -> EvidencePack` authority boundary.
- Do not rewrite frozen artifacts or alter their hashes.
- Do not add another generic identity utility: the existing provider-neutral multisource module is the canonical owner.
- Do not begin Phase B or Phase C from this branch.
- Keep the public Europe PMC discovery, retrieval, verification, and acquisition paths behaviorally compatible.

### Task 1: Prove the desired identity-graph contract with failing regressions

**Files:**

- Modify: `tests/test_l05_curie_multisource_discovery.py`
- Modify: `tests/test_l05_curie_europepmc_discovery.py`

- [ ] **Step 1: Write red regressions**

Add tests that use real Europe PMC and generic provider canonicalizers:

```python
def test_dedup_recomputes_canonical_id_independent_of_provider_order():
    # Europe PMC DOI+PMID plus PubMed PMID-only resolves to one DOI-derived ID
    # in both input orders.

def test_dedup_merges_a_transitive_multi_identifier_graph():
    # DOI-only, PMID-only, and DOI+PMID records resolve to one component.

def test_dedup_rejects_two_values_for_one_stable_identifier_namespace():
    # Same DOI paired with distinct PMIDs raises CurieContractError.

def test_metadata_fallback_is_deterministic_and_provider_ids_are_provenance():
    # Same Europe PMC metadata with different source/ext_id values has one
    # metadata-derived identity and retains source/ext_id only in provenance.
```

Also cover a Europe PMC/PubMed PMCID-only pair. Assert exact provider-order equality, one resulting component, unioned canonical identifiers, deterministic duplicate receipt ordering, fail-closed namespace conflict, and no `europepmc_source` or `europepmc_id` inside `identifiers`. The DOI test expects the hand-derived literal `P_21e82b6410993caee6a5`, not a value produced by code under test.

- [ ] **Step 2: Verify RED**

Run:

```powershell
rtk proxy python -m pytest tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_europepmc_discovery.py -q
```

Expected: FAIL for source/ext-ID fallback, transitive graph reconciliation, and provider-order-independent post-merge identity. Each failure must identify the old behavior rather than a fixture or import error.

- [ ] **Step 3: Commit red tests**

```powershell
git add tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_europepmc_discovery.py
git commit -m "test: specify canonical l05 paper identity graph"
```

### Task 2: Centralize canonical construction and remove Europe PMC identity ownership

**Files:**

- Modify: `src/research_loop/l05_curie/multisource.py:1-420`
- Modify: `src/research_loop/l05_curie/europepmc.py:1-170`
- Test: `tests/test_l05_curie_multisource_discovery.py`
- Test: `tests/test_l05_curie_europepmc_discovery.py`

- [ ] **Step 1: Move canonical primitives into multisource**

Define `normalize_doi`, `normalize_pmid`, `normalize_pmcid`, and a public canonical-record constructor in `multisource.py`. The constructor must derive the ID only from the listed stable namespaces or normalized title/year/first-author fallback and preserve the existing discovery record shape.

```python
def canonicalize_provider_record(
    provider: str, raw: dict, *, title: str, identifiers: dict,
    authors: str = "", year: str = "", journal: str = "",
    abstract: str = "", publication_types: list[str] | None = None,
    is_open_access: bool = False, extra_metadata: dict | None = None,
    extra_provenance: dict | None = None,
) -> dict:
    normalized = _canonical_identifiers(identifiers)
    normalized_title = _require_text(title, f"{provider} result title")
    metadata = {
        "authors": authors, "year": year, "journal": journal,
        "abstract": abstract, "publication_types": list(publication_types or []),
        "is_open_access": bool(is_open_access),
    }
    metadata.update(dict(extra_metadata or {}))
    provenance = {"provider": provider, "raw_record_sha256": hashlib.sha256(_canonical_bytes(raw)).hexdigest()}
    provenance.update({key: value for key, value in dict(extra_provenance or {}).items() if value})
    return {"paper_id": _paper_id(normalized, title=normalized_title, year=year, authors=authors),
            "title": normalized_title, "identifiers": normalized,
            "metadata": metadata, "provenance": provenance}
```

Route PubMed, OpenAlex, Crossref, and Semantic Scholar through this same constructor. Remove `multisource.py`'s import of Europe PMC normalizers.

```python
def _canonical_identifiers(identifiers: dict) -> dict[str, str]:
    normalizers = {"doi": normalize_doi, "pmid": normalize_pmid, "pmcid": normalize_pmcid}
    normalized = {}
    for key, value in identifiers.items():
        text = normalizers.get(key, lambda item: str(item or "").strip())(value)
        if text:
            normalized[key] = text
    return normalized
```

- [ ] **Step 2: Convert Europe PMC to a field adapter**

Delete Europe PMC's local DOI/PMID/PMCID normalizers, metadata fingerprint, local hash/paper-ID helpers, and source/ext-ID identity fallback. Call the multisource constructor, forwarding `source` and `ext_id` through `extra_provenance`; retain `in_europe_pmc` as explicit provider metadata for full-text eligibility.

```python
return canonicalize_provider_record(
    PROVIDER, raw, title=title, identifiers=identifiers,
    authors=authors, year=year, journal=journal, abstract=abstract,
    publication_types=publication_types, is_open_access=is_open_access,
    extra_metadata={"in_europe_pmc": in_europe_pmc},
    extra_provenance={"source": source, "ext_id": ext_id},
)
```

- [ ] **Step 3: Verify GREEN**

Run:

```powershell
rtk proxy python -m pytest tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_europepmc_discovery.py tests/test_l05_curie_europepmc_evidence.py -q
```

Expected: PASS. Europe PMC retrieval tests must still exercise PMCID propagation to the exact-source boundary.

- [ ] **Step 4: Commit the central-owner change**

```powershell
git add src/research_loop/l05_curie/multisource.py src/research_loop/l05_curie/europepmc.py
git commit -m "refactor: centralize l05 paper identity authority"
```

### Task 3: Replace sequential deduplication with deterministic identity-graph reconciliation

**Files:**

- Modify: `src/research_loop/l05_curie/multisource.py:320-420`
- Test: `tests/test_l05_curie_multisource_discovery.py`

- [ ] **Step 1: Implement connected components and conflict checks**

Replace sequential `paper_owner`/`id_owner` behavior in `deduplicate_provider_records` with a deterministic graph pass. Join records sharing a stable `(namespace, value)`; records without stable keys may join only on normalized metadata fallback. For each component, reject more than one value in an individual stable namespace, merge all identifiers and provenance, recompute `paper_id`, sort `source_records`, sort canonical records, and produce deterministic duplicate IDs.

```python
def _identity_keys(record: dict) -> set[tuple[str, str]]:
    stable = _stable_ids(record)
    return stable or {("metadata", _metadata_identity(record))}

def _metadata_identity(record: dict) -> str:
    metadata = record.get("metadata") or {}
    return _metadata_fingerprint(record["title"], str(metadata.get("year") or ""),
                                 str(metadata.get("authors") or ""))

def _record_sort_key(record: dict) -> tuple[str, bytes]:
    metadata = record.get("metadata") or {}
    return (_paper_id(record["identifiers"], title=record["title"],
                      year=str(metadata.get("year") or ""),
                      authors=str(metadata.get("authors") or "")),
            _canonical_bytes(_source_record(record)))

def deduplicate_provider_records(records: list[dict]) -> tuple[list[dict], list[str]]:
    parents = list(range(len(records)))
    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index
    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)
    owner: dict[tuple[str, str], int] = {}
    for index, record in enumerate(records):
        for identity in _identity_keys(record):
            if identity in owner:
                union(index, owner[identity])
            else:
                owner[identity] = index
    components: dict[int, list[dict]] = {}
    for index, record in enumerate(records):
        components.setdefault(find(index), []).append(record)
    canonical, duplicates = [], []
    for component in components.values():
        ordered = sorted(component, key=_record_sort_key)
        merged = _copy_record(ordered[0])
        for duplicate in ordered[1:]:
            _merge(merged, duplicate)
        merged["paper_id"] = _paper_id(merged["identifiers"], title=merged["title"],
                                       year=merged["metadata"].get("year", ""),
                                       authors=merged["metadata"].get("authors", ""))
        merged["provenance"]["source_records"].sort(key=_canonical_bytes)
        canonical.append(merged)
        duplicates.extend(record["paper_id"] for record in ordered[1:])
    return sorted(canonical, key=lambda record: record["paper_id"]), sorted(duplicates)
```

- [ ] **Step 2: Verify graph tests and production path**

Run:

```powershell
rtk proxy python -m pytest tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_europepmc_discovery.py -q
rtk proxy python -m pytest tests/test_l05_curie_europepmc_runtime.py::test_runtime_freezes_end_to_end_europepmc_evidence_pack tests/test_l05_curie_fullcycle.py -q
```

Expected: PASS. The second command proves the selector, independent source verifier, semantic admission, and frozen EvidencePack path still consume the canonical discovery result.

- [ ] **Step 3: Commit deterministic reconciliation**

```powershell
git add src/research_loop/l05_curie/multisource.py tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_europepmc_discovery.py
git commit -m "fix: make l05 identity reconciliation deterministic"
```

### Task 4: Validate and review Phase A

**Files:**

- Review: `src/research_loop/l05_curie/multisource.py`
- Review: `src/research_loop/l05_curie/europepmc.py`
- Review: `tests/test_l05_curie_multisource_discovery.py`
- Review: `tests/test_l05_curie_europepmc_discovery.py`

- [ ] **Step 1: Run focused L0.5 suite**

```powershell
rtk proxy python -m pytest tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_europepmc_discovery.py tests/test_l05_curie_europepmc_evidence.py tests/test_l05_curie_europepmc_runtime.py tests/test_l05_curie_fullcycle.py tests/test_l05_curie_provenance_hardening.py tests/test_l05_curie_selector.py -q
```

- [ ] **Step 2: Run complete regression and entry checks**

```powershell
rtk proxy python -m pytest -q
rtk git diff --check
python research_loop_v04.py --help
python run_loop.py --help
```

Record each exit status, test count, and skip count exactly.

- [ ] **Step 3: Conduct correctness and thermo-nuclear diff reviews**

Review `git diff 876140228b1a80dbb37979ea8b608d131a72d59a...HEAD` separately for correctness and structural criteria. Confirm: Europe PMC no longer derives a paper ID; multisource no longer imports Europe PMC for normalization; provider IDs are provenance; the graph recomputes canonical IDs; and no duplicate identity owner was introduced.

- [ ] **Step 4: Push and exact-head CI gate**

```powershell
git status --short
git push -u origin codex/l05-canonical-paper-identity
```

Verify the pushed SHA's CI in the repository's CI provider. With a clean worktree and both reviews recorded, stop and report Phase A; do not begin Phase B.

## Plan self-review

- Spec coverage: Tasks 1 and 3 cover DOI, PMID, PMCID, multiple identifiers, conflicts, metadata fallback, Europe PMC provenance, provider order, deterministic deduplication, and the production EvidencePack path.
- Scope: Task 2 removes the Europe PMC parallel authority; it leaves retrieval, independent verification, semantic admission, frozen artifacts, and all Phase B/C/P2 work untouched.
- No placeholders: Each code change has concrete file paths, contract, and command-level verification.
