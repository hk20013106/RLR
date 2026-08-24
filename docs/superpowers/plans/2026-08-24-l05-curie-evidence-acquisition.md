# L0.5 Curie Evidence Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core L0.5 Curie acquisition contracts and immutable EvidencePack freeze boundary between L0 ResearchSeed and L1 Einstein.

**Architecture:** L0.5 is a first-class non-delta staged phase. Pure contract validation is separated from filesystem persistence; discovery/retrieval providers are represented only by narrow protocols. L1-facing evidence becomes a hash-bound frozen artifact rather than a mutable search session.

**Tech Stack:** Python 3.13, stdlib `dataclasses`/`typing.Protocol`/`hashlib`/`json`/`pathlib`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-l05-curie-evidence-acquisition-design.md`

## Global Constraints

- Do not add L0.5 to the status-bearing `DAG_NODES` sequence in this slice.
- Existing `research_loop.research_seed` remains the only L0 semantic authority.
- No live PubMed/Europe PMC/OpenAlex/Crossref/Semantic Scholar/PaperQA2 dependency in this slice.
- Evidence acquisition is bounded to at most 3 rounds.
- Only `LOCATED` extracts with non-empty locators may enter a frozen pack.
- Freeze is append-only: existing pack artifacts are never overwritten.
- L4 and L8.5 behavior is unchanged.

---

### Task 1: Contract tests and pure validators

**Files:**
- Create: `tests/test_l05_curie_contracts.py`
- Create: `src/research_loop/l05_curie/__init__.py`
- Create: `src/research_loop/l05_curie/contracts.py`
- Create: `src/research_loop/l05_curie/interfaces.py`

**Interfaces:**
- `validate_query_plan(plan: dict, *, seed_sha256: str) -> dict`
- `validate_transport_handshake(handshake: dict) -> dict`
- `validate_discovery_batch(batch: dict, *, query_ids: set[str]) -> dict`
- `validate_evidence_extract(extract: dict) -> dict`
- `judge_coverage(coverage: dict, *, round_index: int, max_rounds: int = 3) -> dict`
- `build_gap_request(*, candidate_id: str, round_id: str, seed_sha256: str, pack_sha256: str, gaps: list[dict]) -> dict`
- `DiscoveryTransport` and `EvidenceRetriever` Protocols.

- [ ] **Step 1: Write failing tests**

Tests must prove schema identity, seed binding, query/provider provenance, `LOCATED` evidence-only admission, contradictory-evidence role preservation, bounded retry/stop decisions, and gap-request binding.

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src python -m pytest tests/test_l05_curie_contracts.py -q`

Expected: FAIL because `research_loop.l05_curie` does not exist.

- [ ] **Step 3: Implement minimal pure contract layer**

Implement fail-closed validators with one authoritative validator per contract. Do not perform filesystem or provider I/O in `contracts.py`.

- [ ] **Step 4: Run targeted tests**

Run: `PYTHONPATH=src python -m pytest tests/test_l05_curie_contracts.py -q`

Expected: PASS.

### Task 2: Immutable EvidencePack store

**Files:**
- Create: `tests/test_l05_curie_store.py`
- Create: `src/research_loop/l05_curie/store.py`
- Modify: `src/research_loop/l05_curie/__init__.py`

**Interfaces:**
- `build_evidence_pack(...) -> dict`
- `freeze_evidence_pack(project_dir, pack: dict) -> dict`
- `load_frozen_evidence_pack(project_dir, manifest: dict, *, candidate_id: str, round_id: str, seed_sha256: str) -> dict`
- `next_pack_version(previous_pack: dict, *, gap_request: dict, query_plan: dict, discovery_receipts: list[dict], selected_papers: list[dict], evidence: list[dict], coverage: dict, gaps: list[dict]) -> dict`

- [ ] **Step 1: Write failing tests**

Tests must prove deterministic content hashing, path confinement, append-only freeze, on-disk SHA verification, internal content-hash verification, tamper rejection, coverage PASS requirement, seed/candidate/round binding, and parent lineage for v2.

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src python -m pytest tests/test_l05_curie_store.py -q`

Expected: FAIL because store interfaces are missing.

- [ ] **Step 3: Implement minimal store**

Use canonical JSON (`sort_keys=True`, compact separators) for hashing. Persist under `09_Literature_Database/evidence_packs/l05/<candidate_id>/EP_<candidate>_R<round>_v<version>.json`. Refuse overwrite.

- [ ] **Step 4: Run targeted tests**

Run: `PYTHONPATH=src python -m pytest tests/test_l05_curie_store.py -q`

Expected: PASS.

### Task 3: Documentation and regression verification

**Files:**
- Modify: `docs/AGENT_CONTEXT.md`
- Modify: `docs/DAG_TOPOLOGY.md`

- [ ] **Step 1: Document L0.5 authority boundary**

State that L0.5 is non-status-bearing; Curie may search/retrieve/verify; Einstein consumes only frozen EvidencePack and emits EvidenceGapRequest rather than searching.

- [ ] **Step 2: Run focused suite**

Run: `PYTHONPATH=src python -m pytest tests/test_l05_curie_contracts.py tests/test_l05_curie_store.py -q`

Expected: PASS.

- [ ] **Step 3: Run full regression suite**

Run through repository CI equivalent: `python -m pytest -q --no-header -p no:cacheprovider --cov=src --cov-report=term-missing` with `PYTHONPATH=src`.

Expected: PASS.

- [ ] **Step 4: Verify imports and CLI**

Run:

```bash
python -c "import sys; sys.path.insert(0, 'src'); import research_loop; import research_loop.l05_curie"
python research_loop_v04.py --help
```

Expected: exit 0.

- [ ] **Step 5: Open PR and require GitHub Actions CI**

PR base: `main`; head: `codex/l05-curie-evidence-acquisition`. Do not merge in this task unless separately authorized.
