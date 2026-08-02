# L4 Method Anchors and Conditional Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an evidence-backed L4 method candidate catalog with user-PDF registration, carry it through L5/L6 selection, and skip L2 when L1 has four or fewer valid hypotheses.

**Architecture:** Add a focused `user_sources` module for immutable PDF registration. Extend L4 deep-research output with method components, candidates, and anchors; validate source payload authenticity before persistence; render the method catalog in Markdown; extend native v2.1 L4/L5/L6 contracts. Add a separate skip-receipt helper so dynamic L1→L3 routing remains auditable without fabricating an L2 delta.

**Tech Stack:** Python 3.13, argparse, pathlib, hashlib, JSON Schema/jsonschema, pytest, GitHub Actions.

## Global Constraints

- Preserve fail-closed evidence behavior.
- Do not treat PDF registration alone as accepted evidence.
- Do not add an RLR PDF parser, OCR, network downloader, authentication flow, or MCP integration.
- Keep L0 schema `1.0`, L1, and L8.5 behavior compatible.
- Extend native delta schema `2.1`; do not break legacy `2.0` contracts.
- Existing immutable evidence and delta files are never rewritten.
- The current real-data candidate must resume at L4; L0-L3 are not rerun.
- L2 is skipped only for 1-4 committed valid hypotheses; 0 fails closed; 5+ runs L2.

---

### Task 1: Immutable user-PDF registration

**Files:**
- Create: `src/research_loop/user_sources.py`
- Create: `scripts/import_literature_pdf.py`
- Modify: `src/research_loop/commands/research.py`
- Modify: `src/research_loop/cli.py`
- Test: `tests/test_user_sources.py`

**Interfaces:**
- Produces: `register_pdf(project_dir, candidate_id, source_file, *, doi="", pmid="", url="") -> dict`
- Produces: `registered_sources(project_dir, candidate_id) -> list[dict]`
- Produces: `verify_registered_source(project_dir, candidate_id, user_source_id, sha256) -> tuple[bool, str]`

- [ ] Write failing tests for PDF magic validation, immutable candidate-scoped storage, SHA256 sidecar, idempotency, candidate isolation, standalone script output, and CLI parity.
- [ ] Run targeted tests and verify RED because `research_loop.user_sources` and the command do not exist.
- [ ] Implement the minimal registration module and thin script/CLI wrappers.
- [ ] Run targeted tests and verify GREEN.
- [ ] Commit `feat: register user-supplied literature PDFs`.

### Task 2: Node-specific L4 research schema and prompt

**Files:**
- Modify: `src/research_loop/deep_research.py`
- Test: `tests/test_deep_research.py`

**Interfaces:**
- Change: `_runtime_schema(node: str | None = None) -> dict`
- Change: `build_invocation(..., user_sources: list[dict] | None = None)`
- Change: `validate_payload(payload: dict, *, node: str, project_dir=None, candidate_id="")`

- [ ] Write failing tests that L4 schema requires `method_components` and `method_candidates`, anchors reference valid IDs, prompt lists registered PDFs, and L1/L8.5 schemas remain unchanged.
- [ ] Verify RED in CI.
- [ ] Extend only the L4 runtime schema with explicit component/candidate/anchor fields and accepted source kinds.
- [ ] In `run_and_persist`, discover candidate-registered PDFs and include their paths, IDs, and hashes in the L4 prompt.
- [ ] Verify targeted tests GREEN.
- [ ] Commit `feat: request structured L4 method candidates`.

### Task 3: Source authenticity and method-anchor persistence

**Files:**
- Modify: `src/research_loop/deep_research.py`
- Modify: `src/research_loop/user_sources.py`
- Test: `tests/test_deep_research.py`

**Interfaces:**
- Produce: `_normalize_source_text(value: str) -> str`
- Produce: `_validate_anchor_payload(paper: dict, extract: dict) -> tuple[bool, str]`

- [ ] Write failing tests for placeholder payloads, payloads below 500 bytes, extract text absent from payload, review/abstract/table evidence, valid protocol/official-doc anchors, and mismatched user-source ID/hash.
- [ ] Verify RED.
- [ ] Implement normalization using HTML unescape, tag removal, Unicode-dash normalization, casefold, and whitespace collapse.
- [ ] Accept identifiers by DOI/PMID/URL or valid registered `user_source_id`.
- [ ] Persist `method_components`, `method_candidates`, anchor IDs, component IDs, method IDs, source kinds, and user-source binding fields.
- [ ] Preserve source payload for OA sources and verified user PDFs.
- [ ] Verify GREEN and commit `feat: validate and persist method anchors`.

### Task 4: Component-level L4 gate and Markdown catalog

**Files:**
- Modify: `src/research_loop/deep_research.py`
- Modify: `templates/layers/L4_method_brainstorm.md`
- Create: `docs/L4_METHOD_EVIDENCE.md`
- Test: `tests/test_deep_research.py`
- Test: `tests/test_user_sources.py`

**Interfaces:**
- Change: `audit_evidence_pack` computes required-component coverage through eligible candidates and accepted anchors.
- Change: `render_pre_research_markdown` renders the full L4 candidate catalog.

- [ ] Write failing tests for required/optional component coverage, multiple candidates, precise missing-source diagnostics, full method descriptions, evidence provenance, and exact PDF-import instructions.
- [ ] Verify RED.
- [ ] Implement component coverage without weakening the review-search receipt requirement.
- [ ] Render each candidate's purpose, applicable inputs, implementation steps, assumptions, outputs, strengths, limitations, alternatives, anchors, and user-source status.
- [ ] Update L4 layer instructions and static user guide.
- [ ] Verify GREEN and commit `feat: render auditable L4 method catalog`.

### Task 5: Native L4→L5→L6 structured decision flow

**Files:**
- Modify: `src/research_loop/hypothesis_contracts.py`
- Modify: `src/research_loop/topology.py`
- Modify: `templates/layers/L5_method_falsification.md`
- Modify: `templates/layers/L6_analysis_plan.md`
- Test: `tests/test_hypothesis_contracts.py` or nearest existing schema tests

**Interfaces:**
- v2.1 L4 adds required `deep_research_run_id`, `method_components`, and `method_candidates` while retaining `strategies`.
- v2.1 L5 adds required `method_critiques`, keyed by `method_id`.
- v2.1 L6 adds required `selected_methods`, keyed by component ID, while retaining `analysis_plan`.

- [ ] Write failing schema tests for candidate retention, candidate-level critique, final selected methods, rejected alternatives, anchor IDs, and L5 QC obligations.
- [ ] Verify RED.
- [ ] Extend only v2.1 schemas and update topology/template contracts.
- [ ] Verify GREEN and commit `feat: carry method candidates through L6 selection`.

### Task 6: Conditional L2 skip receipt and routing

**Files:**
- Create: `src/research_loop/node_skips.py`
- Modify: `src/research_loop/commands/lifecycle.py`
- Modify: `src/research_loop/context.py`
- Modify: `src/research_loop/topology.py`
- Test: `tests/test_candidate_aware_next_step.py`
- Test: nearest context-assembly test file

**Interfaces:**
- Produce: `ensure_l2_skip_receipt(project_dir, candidate_id, l1_path, hypothesis_count) -> dict`
- Produce: `validate_l2_skip_receipt(project_dir, candidate_id, l1_path) -> tuple[bool, dict | str]`

- [ ] Write failing tests for counts 1-4 routing to L3, count 5 routing to L2, count 0 failing closed, deterministic skip receipt, hash binding, tamper rejection, and L3 context without a fake L2 delta.
- [ ] Verify RED.
- [ ] Implement skip receipt under `08_Audit/node_skips/` and dynamic routing/context inputs.
- [ ] Ensure L3 explicitly receives the skip reason and does not claim Feynman review occurred.
- [ ] Verify GREEN and commit `feat: skip L2 for small hypothesis sets`.

### Task 7: End-to-end verification and delivery

**Files:**
- Modify documentation only if tests reveal missing usage details.

- [ ] Run targeted test groups.
- [ ] Run `pytest -q` and confirm all tests pass.
- [ ] Run `git diff --check` and `python run_loop.py --help`.
- [ ] Confirm legacy `research_loop_v04.py` remains a thin compatibility shim with no new logic.
- [ ] Confirm the real input data and previous run directories are untouched.
- [ ] Push the branch, update the pull request, wait for GitHub CI, and merge only after all checks pass.
