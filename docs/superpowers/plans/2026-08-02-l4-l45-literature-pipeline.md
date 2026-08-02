# L4/L4.5 Literature Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the overloaded L4 pre-research invocation into an auditable metadata-discovery stage and a frozen-corpus evidence-construction stage without renumbering the existing RLR DAG.

**Architecture:** A new focused extension wraps the already-installed Deep Research runtime. Non-L4 calls remain unchanged. L4 calls execute a metadata-only discovery request, persist and deduplicate `LiteratureDiscoveryRun/v1`, then execute the existing strict method-evidence request against only the selected records and link the resulting evidence pack to the discovery manifest.

**Tech Stack:** Python 3.11/3.12, pytest, JSON Schema, existing `research_loop.deep_research` extension pattern, GitHub Actions Windows CI.

## Global Constraints

- Do not modify L0-L3 behavior, existing topology numbering, `L4_fisher` delta schema, or L5-L10 contracts.
- Do not weaken source-payload, verbatim-containment, Methods-section, review-receipt, or required-component gates.
- Do not vendor or hard-code `literature-search-mcp`; preserve a replaceable discovery-executor boundary.
- Persist discovery artifacts independently so L4.5 failure does not erase successful discovery.
- Keep legacy evidence-pack readers compatible.

---

### Task 1: Specify split-pipeline behavior with failing tests

**Files:**
- Create: `tests/test_l4_pipeline.py`

**Interfaces:**
- Consumes: `research_loop.deep_research.run_and_persist`, `RuntimeSpec`, existing L4 evidence payload contract.
- Produces: executable behavioral requirements for `l4_discovery_schema()`, `build_l4_discovery_prompt()`, and the two-stage L4 wrapper.

- [ ] **Step 1: Write a failing schema-boundary test**

Assert that the discovery schema requires metadata, availability, relevance, and selection fields but has no `source_payload`, `extracts`, `method_components`, or `method_candidates` properties.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_l4_pipeline.py::test_l4_discovery_schema_is_metadata_only -q
```

Expected: FAIL because the L4 pipeline extension and schema do not exist.

- [ ] **Step 3: Write a failing two-stage execution test**

Use a sequential fake subprocess response: the first response is a discovery payload and the second is a valid strict L4 evidence payload. Assert two invocations, persisted discovery artifact, linked evidence artifact, and frozen selected records in the evidence prompt.

- [ ] **Step 4: Run the test and verify RED**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_l4_pipeline.py::test_l4_runs_discovery_then_evidence_and_links_artifacts -q
```

Expected: FAIL because current L4 performs one overloaded invocation.

- [ ] **Step 5: Commit failing tests**

```bash
git add tests/test_l4_pipeline.py
git commit -m "test: specify split L4 discovery and evidence pipeline"
```

### Task 2: Implement metadata-only L4 discovery

**Files:**
- Create: `src/research_loop/l4_pipeline.py`
- Modify: `src/research_loop/__init__.py`
- Test: `tests/test_l4_pipeline.py`

**Interfaces:**
- Produces: `l4_discovery_schema() -> dict`, `build_l4_discovery_prompt(...) -> str`, `persist_discovery_run(...) -> dict`, and `install(deep_research_module) -> None`.
- Discovery artifact schema: `LiteratureDiscoveryRun/v1`.

- [ ] **Step 1: Implement the strict metadata-only discovery schema**

Include query records, source-status receipts, paper identifiers and metadata, abstract, OA/PDF availability, relevance score, selection status, and reason. Require every declared property for provider strict-schema compatibility.

- [ ] **Step 2: Implement deterministic identifier-first deduplication**

Identity order: normalized DOI, PMID, stable URL, then normalized title + year. Retain the higher relevance-score record and record duplicates in the discovery artifact.

- [ ] **Step 3: Implement immutable discovery persistence**

Write `09_Literature_Database/discovery_runs/<run_id>.json`; include request/response receipt, selected paper records, duplicate records, question/claim hashes, and artifact SHA linkage fields.

- [ ] **Step 4: Install the extension after existing method-evidence extensions**

Import and call `l4_pipeline.install(deep_research)` in `research_loop.__init__`. Capture the current post-extension functions so non-L4 behavior delegates unchanged.

- [ ] **Step 5: Run the schema test and verify GREEN**

```bash
PYTHONPATH=src python -m pytest tests/test_l4_pipeline.py::test_l4_discovery_schema_is_metadata_only -q
```

Expected: PASS.

### Task 3: Implement frozen-corpus L4.5 evidence construction

**Files:**
- Modify: `src/research_loop/l4_pipeline.py`
- Test: `tests/test_l4_pipeline.py`

**Interfaces:**
- Consumes: selected records from `LiteratureDiscoveryRun/v1` and registered local user sources.
- Produces: existing strict L4 evidence pack with `pipeline_stage`, discovery ID/path/hash linkage.

- [ ] **Step 1: Add a generic JSON-stage executor**

Build stage-specific schema files and prompts, execute the configured Codex/Claude runtime, create a normal skill receipt, parse JSON, and fail closed on non-zero exit or malformed output.

- [ ] **Step 2: Execute discovery first for node L4**

Persist the discovery result before evidence construction. Stop before L4.5 when no paper has `selection_status=selected`.

- [ ] **Step 3: Build the L4.5 evidence prompt**

Start from the existing strict L4 method-evidence prompt and append the frozen selected-paper catalog. Explicitly prohibit replacing the corpus with a new broad search while permitting identifier/full-text resolution for selected records and registered local PDFs.

- [ ] **Step 4: Execute and persist strict evidence construction**

Use the existing extended L4 schema, validator, and persistence functions. Add discovery linkage fields to the resulting run artifact and rewrite the immutable run record before exposing success.

- [ ] **Step 5: Run the two-stage test and verify GREEN**

```bash
PYTHONPATH=src python -m pytest tests/test_l4_pipeline.py::test_l4_runs_discovery_then_evidence_and_links_artifacts -q
```

Expected: PASS.

### Task 4: Add failure and compatibility coverage

**Files:**
- Modify: `tests/test_l4_pipeline.py`
- Modify: `src/research_loop/l4_pipeline.py`

**Interfaces:**
- Verifies record-level failure semantics and non-L4 compatibility.

- [ ] **Step 1: Add a failing test for zero selected papers**

Assert that discovery persists, evidence is not invoked, and the error names the selection blocker.

- [ ] **Step 2: Add a failing test for L4.5 failure after discovery success**

Assert that discovery remains readable and no completed L4 evidence pack is created.

- [ ] **Step 3: Add a non-L4 delegation test**

Assert that L1 still invokes the captured original `run_and_persist` path exactly once.

- [ ] **Step 4: Implement only the behavior required by these tests**

Keep failure messages stage-specific and do not broaden fallback behavior.

- [ ] **Step 5: Run focused tests**

```bash
PYTHONPATH=src python -m pytest tests/test_l4_pipeline.py tests/test_deep_research.py -q
```

Expected: PASS.

### Task 5: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/README_CN.md`
- Modify: `docs/未来方向-AI4AI-PaSa-v21-MCP.md`

**Interfaces:**
- Documents L4 as discovery, L4.5 as evidence construction, Fisher as the unchanged cognitive L4 node, and the future MCP/Zotero adapter boundary.

- [ ] **Step 1: Update architecture documentation**

State explicitly that no L3.5 node is added and why.

- [ ] **Step 2: Run import and syntax checks**

```bash
python -m compileall -q src tests/test_l4_pipeline.py
PYTHONPATH=src python -c "import research_loop"
```

Expected: exit 0.

- [ ] **Step 3: Run the full test suite on Python 3.11 and 3.12 through GitHub CI**

Expected: both Windows matrix jobs pass with no coverage regression below the repository gate.

- [ ] **Step 4: Review the complete branch diff**

Verify only architecture docs, the focused extension, installation hook, and tests changed. Confirm no real-data files, SQLite databases, evidence packs, runtime logs, PDFs, or local artifacts are committed.

- [ ] **Step 5: Open a pull request without merging**

Title:

```text
feat: split L4 discovery from L4.5 evidence construction
```

The PR must state that the real-data full loop is not claimed successful unless an actual real-data run is performed separately.
