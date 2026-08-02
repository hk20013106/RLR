# Flexible L1 Hypothesis Cardinality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow native v2.1 L1 deltas to contain one or more hypotheses without forcing agents to manufacture three proposals, while preserving the existing 12-hypothesis upper bound and conditional L2 routing.

**Architecture:** Change only the v2.1 L1 JSON Schema cardinality override from `minItems: 3` to `minItems: 1`. Add contract tests for zero, one, and two hypotheses, and retain route tests proving that one through four hypotheses skip L2 while five or more enter L2.

**Tech Stack:** Python 3.11/3.12, jsonschema Draft 2020-12, pytest, GitHub Actions on Windows.

## Global Constraints

- v2.0 behavior remains unchanged.
- v2.1 accepts 1–12 hypotheses at L1.
- Zero hypotheses remain invalid.
- One through four committed unique hypotheses skip L2 and proceed to L3 with an immutable skip receipt.
- Five through twelve hypotheses proceed to L2.
- Do not weaken hypothesis item validation, proposal-key uniqueness, ledger identity, or downstream evidence contracts.

---

### Task 1: Lock the relaxed v2.1 contract with RED tests

**Files:**
- Modify: `tests/test_v21_acceptance.py`
- Modify: `tests/test_ledger_receipt_idempotency.py`

**Interfaces:**
- Consumes: `validate_submission(node, delta, schema_version="2.1") -> list[str]`
- Produces: explicit regression coverage for 0/1/2-hypothesis L1 submissions.

- [ ] **Step 1: Add tests showing one and two hypotheses are valid**
- [ ] **Step 2: Add a test showing zero hypotheses remain invalid**
- [ ] **Step 3: Reduce the receipt-idempotency fixture to one hypothesis**
- [ ] **Step 4: Run targeted tests and verify the one/two-hypothesis tests fail because the current v2.1 minimum is three**
- [ ] **Step 5: Commit the RED tests**

### Task 2: Apply the minimal schema change

**Files:**
- Modify: `src/research_loop/hypothesis_contracts.py`

**Interfaces:**
- Produces: v2.1 L1 `hypotheses` cardinality of 1–12.

- [ ] **Step 1: Change the v2.1 L1 override to `minItems: 1, maxItems: 12`**
- [ ] **Step 2: Run targeted contract and receipt tests and verify they pass**
- [ ] **Step 3: Run conditional-routing tests for 1–4 skip and 5+ attack behavior**
- [ ] **Step 4: Commit the GREEN implementation**

### Task 3: Full verification and integration

**Files:**
- No production-file changes expected.

**Interfaces:**
- Consumes: PR branch `feat/l4-method-anchors`.
- Produces: passing Windows Python 3.11/3.12 CI and merged `main`.

- [ ] **Step 1: Reopen PR #3 as draft and run the full CI matrix**
- [ ] **Step 2: Verify import check, CLI help, all pytest tests, coverage summary, and mergeability**
- [ ] **Step 3: Review the final diff for unrelated changes and unresolved review threads**
- [ ] **Step 4: Mark the PR ready and merge only after all required checks pass**
