# L0 Pre-flight + State Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make L0 a deterministic pre-flight + previous-round evidence restore boundary with granular failure codes, immutable-by-hash round manifests, and explicit evidence bindings.

**Architecture:** Keep one formal L0 node. Add a focused `l0_state.py` leaf that owns round-manifest and evidence-binding schemas/validation. Reuse `l0_contract.py`, `next_loop_memory.json`, the existing L7 execution manifest, current evidence directories, and the hypothesis ledger. Integrate manifest emission at L10c/continuation creation and restore before any continuation-round provider work.

**Tech Stack:** Python 3.11/3.12, pathlib, hashlib, json, pytest, existing RLR controller/runner APIs.

## Global Constraints

- Base commit: `e669ca3bc5229deabf46e89ca353fde510de5f98`.
- Do not modify the merged PR #12 L4A→L4B closed-corpus contract.
- One formal `L0` DAG node; no L0a/L0b/L0c nodes.
- Large artifacts are retained in place and bound by exact path + SHA-256; do not copy them into a new store.
- `l0_contract.py` remains the sole current-round input schema/validator.
- `next_loop_memory.json` remains semantic continuation state; round manifests hold physical evidence state.
- Continuation restore must fail before L1/provider execution on missing/tampered inherited evidence.
- Failure output must include a specific component error code.

---

### Task 1: Round Evidence Manifest Core

**Files:**
- Create: `src/research_loop/l0_state.py`
- Create: `tests/test_l0_state_restore.py`

**Interfaces:**
- Produces: `build_round_manifest(project_dir, cand_id) -> dict`
- Produces: `write_round_manifest(project_dir, cand_id) -> tuple[Path, str]`
- Produces: `load_round_manifest(path) -> dict`
- Produces: `verify_round_manifest(project_dir, manifest, expected_candidate, expected_round) -> list[dict]`

- [ ] Write failing tests for schema identity, source hash capture, L7 output capture, missing artifact and hash mismatch.
- [ ] Confirm tests fail because `research_loop.l0_state` does not exist.
- [ ] Implement minimal manifest collection from existing authoritative inputs: `l0_input.yaml`, L7 execution manifest/output files, candidate-scoped reports, literature cards/evidence packs, and run/audit receipts.
- [ ] Keep artifact records deterministic and sorted.
- [ ] Confirm targeted tests pass.

### Task 2: Evidence Binding and Continuation Restore

**Files:**
- Modify: `src/research_loop/l0_state.py`
- Modify: `src/research_loop/commands/continuation.py`
- Modify: `src/research_loop/commands/lifecycle.py`
- Modify: `tests/test_l0_state_restore.py`
- Modify: `tests/test_cross_round_e2e.py`

**Interfaces:**
- Produces: `restore_previous_round(project_dir, cand_id) -> dict`
- Produces: `write_evidence_binding(project_dir, cand_id, binding) -> Path`

- [ ] Write failing tests: initial round restore is a no-op; continuation requires linked manifest; missing manifest fails with `L0_RESTORE_MANIFEST_MISSING`; tampered artifact fails with `L0_RESTORE_ARTIFACT_HASH_MISMATCH`; valid restore writes `L0EvidenceBinding/v1`.
- [ ] Extend loop memory with `round_manifest_path` and `round_manifest_sha256`; never embed all artifact records in loop memory.
- [ ] Validate previous candidate/round/project identity before bytes.
- [ ] Fail closed without modifying the prior manifest.
- [ ] Confirm targeted continuation tests pass.

### Task 3: Canonical Runner Binding Gate

**Files:**
- Modify: `src/run_loop.py`
- Modify: `tests/test_run_loop_guards.py`
- Modify: `tests/test_l0_state_restore.py`

**Interfaces:**
- Consumes: `restore_previous_round(project, cand_id)`.

- [ ] Write failing runner test proving a continuation cannot reach provider setup when restore fails.
- [ ] Call deterministic restore after dependency checks and before provider execution/main-agent handoff.
- [ ] Log the exact restore error code and return hard-stop code 3.
- [ ] Preserve initial-round behavior.
- [ ] Confirm runner guard tests pass.

### Task 4: Granular Preflight Probe Contract

**Files:**
- Create: `src/research_loop/l0_preflight.py`
- Modify: `src/research_loop/common.py`
- Modify: `src/research_loop/commands/lifecycle.py`
- Create: `tests/test_l0_preflight_probes.py`

**Interfaces:**
- Produces: `ProbeResult(component, status, code, detail, consumer)`.
- Produces: `run_preflight_probes(project_dir) -> list[ProbeResult]`.
- Produces: `write_preflight_receipt(project_dir, results) -> Path`.

- [ ] Write failing tests for exact component codes for package/provider/filesystem, Academic Research, Zotero, evidence store, hypothesis ledger and Obsidian.
- [ ] Preserve current dependency declarations but route output through structured results rather than a single boolean gate.
- [ ] Probe Zotero beyond raw TCP where possible: local API endpoint readable; if only socket status is available, report that exact capability rather than claiming library readability.
- [ ] Validate Obsidian path, `.obsidian/`, and writability.
- [ ] Validate evidence-store directories with create/read/delete probe.
- [ ] Write `00_Preflight/preflight_receipt.json` on every preflight run.
- [ ] Confirm targeted tests pass.

### Task 5: PubMed MCP Readiness Boundary

**Files:**
- Modify: `src/research_loop/l0_preflight.py`
- Modify: `tests/test_l0_preflight_probes.py`
- Modify: `docs/DAG_TOPOLOGY.md`

**Interfaces:**
- Required capability names: `pubmed_search_articles`, `pubmed_fetch_articles`, `pubmed_fetch_fulltext`.

- [ ] Add tests for unconfigured/start-failed and required-tool-missing cases.
- [ ] Represent MCP readiness through explicit configuration/probe evidence; do not pretend an stdio MCP has a TCP port.
- [ ] Fail with `L0_RESEARCH_PUBMED_MCP_START_FAILED` or `L0_RESEARCH_PUBMED_MCP_REQUIRED_TOOL_MISSING` as appropriate.
- [ ] Document PubMed MCP as literature transport and Academic Research as reasoning/orchestration.
- [ ] Confirm targeted tests pass.

### Task 6: L10c Round Finalization

**Files:**
- Modify: `src/research_loop/commands/reporting.py`
- Modify: `src/research_loop/commands/continuation.py`
- Modify: `tests/test_cross_round_e2e.py`
- Modify: `tests/test_l0_state_restore.py`

**Interfaces:**
- L10c finalization emits candidate report, round manifest and loop memory linkage without copying large artifacts.

- [ ] Write failing test that aggregate-report/finalization leaves an immutable round manifest available to the next round.
- [ ] Emit the manifest after reports are written so result reports can be included.
- [ ] Ensure repeated emission with identical bytes is idempotent; conflicting existing manifest is a hard failure.
- [ ] Ensure child creation uses the manifest-linked loop memory.
- [ ] Confirm cross-round tests pass.

### Task 7: Verification

**Files:**
- No new production scope unless a failing test identifies a contract bug.

- [ ] Run targeted L0 state/continuation/runner/preflight tests.
- [ ] Run L4/L4.5 regression tests to prove PR #12 boundaries are untouched.
- [ ] Run full suite.
- [ ] Run `git diff --check` equivalent through CI/check tooling.
- [ ] Inspect CI for the feature head; do not merge automatically unless explicitly requested.
