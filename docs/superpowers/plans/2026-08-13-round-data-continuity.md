# Round Data Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace RLR's duplicated round-data authorities with one deterministic current-round data binding that combines selected verified inherited artifacts and newly declared data, and make L7 consume only that binding.

**Architecture:** `l0_contract.py` remains the declaration authority, `l0_state.py` remains previous-round physical evidence authority, and a focused `l0_data.py` module becomes the deterministic authorization projection between them. L7 keeps the existing isolated workspace mechanism but stages only files authorized by `CurrentRoundDataBinding/v1`; `input_manifest.md` loses machine-authority status.

**Tech Stack:** Python 3.13, PyYAML, pytest, existing RLR JSON/YAML contracts, SHA-256 provenance, GitHub Actions.

## Global Constraints

- Global architecture first; no local patch-stack fixes.
- One concern has one authoritative implementation.
- Reuse `l0_plan_intake`, `l0_state`, hypothesis/context authorization patterns, and the existing Turing workspace.
- Do not add DVC, DataLad, a generic Data Registry, another database, or a duplicate evidence store.
- Do not copy large scientific files between rounds; authorize by exact path + SHA-256.
- Preserve Path B cognitive isolation; authorization for execution must not dump raw previous-round data into cognitive prompts.
- Formal hypothesis lifecycle remains owned by Hypothesis Ledger and is out of scope.
- Existing `L0InputContract/1.0` artifacts remain readable; new native contracts use schema 1.1 rather than silently changing 1.0 semantics.
- A prior artifact is reusable only if it is an exact verified `source`, `intermediate`, or `result` artifact from the previous frozen manifest.
- The exact manifest path may be project-relative or normalized absolute for external/HPC data; the selector must match the previous manifest record exactly.
- At least one current-round authorized input must exist across inherited and newly declared inputs.

---

## File map

- Create `src/research_loop/l0_data.py`: deterministic current-round data authorization projection, binding persistence, revalidation, and error codes.
- Modify `src/research_loop/l0_contract.py`: schema 1.1 support and `inherited_inputs` validation.
- Modify `src/research_loop/l0_intake.py`: continuation normalization may produce new-only, inherited-only, or combined contracts.
- Modify `src/research_loop/l0_plan_intake.py`: structured continuation support using existing manifest verification rather than a parallel parser.
- Modify `src/research_loop/gates.py`: after L0 contract + previous restore succeeds, create/revalidate the current-round data binding before any provider work.
- Modify `src/research_loop/commands/execution.py`: remove `input_manifest.md` as data authority; execution gate and workspace consume `CurrentRoundDataBinding/v1`.
- Modify `src/research_loop/context.py`: expose only compact L0 data-binding metadata if needed for L0 audit, never raw file contents/catalog dumps.
- Modify `src/research_loop/topology.py` and `docs/DAG_TOPOLOGY.md`: document the single data-authority chain.
- Modify `.github/workflows/l0-contract.yml`: include data-continuity files/tests in targeted CI.
- Test `tests/test_l0_input_contract.py`, `tests/test_l0_intake.py`, `tests/test_l0_structured_intake.py`.
- Create `tests/test_round_data_binding.py`.
- Create/modify execution-focused tests in `tests/test_round_data_execution.py`.
- Extend `tests/test_cross_round_e2e.py` for real N -> N+1 data reuse.

---

### Task 1: Version the L0 declaration contract without creating a second intake model

**Files:**
- Modify: `src/research_loop/l0_contract.py`
- Modify: `src/research_loop/l0_intake.py`
- Modify: `src/research_loop/l0_plan_intake.py`
- Test: `tests/test_l0_input_contract.py`
- Test: `tests/test_l0_intake.py`
- Test: `tests/test_l0_structured_intake.py`

**Interfaces:**
- Consumes: existing `source_input`, loop-memory identity, existing file-manifest verification.
- Produces: schema-1.1 continuation contracts with optional `source_input` and `inherited_inputs`; new initial contracts remain current-data-only.

- [ ] **Step 1: Write RED tests for schema 1.1 semantics**

Add tests that assert:

```python
# initial: inherited reuse is illegal
errors = validate_l0_input_contract(initial_contract_with_inherited, ...)
assert any("inherited_inputs" in error for error in errors)

# continuation: inherited-only is valid when selector is complete
contract = build_continuation_contract(..., source_input=None,
    inherited_inputs=[{
        "path": "04_Analysis_Outputs/result.json",
        "sha256": result_hash,
        "role": "prior_result",
        "reuse_reason": "reanalyze the verified round-N result",
    }])
assert validate_l0_input_contract(contract, ...) == []

# continuation: union cannot be empty
assert validate_l0_input_contract(continuation_without_any_data, ...)
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```bash
pytest tests/test_l0_input_contract.py tests/test_l0_intake.py tests/test_l0_structured_intake.py -q
```

Expected: failures because schema 1.1 / inherited continuation is unsupported.

- [ ] **Step 3: Implement one versioned contract path**

Implement constants and validation equivalent to:

```python
SCHEMA_V1 = "1.0"
SCHEMA_V11 = "1.1"
CURRENT_SCHEMA_VERSION = SCHEMA_V11

_ALLOWED_INHERITED_FIELDS = {"path", "sha256", "role", "reuse_reason"}
```

Rules:

```python
if schema_version == "1.0":
    # preserve historical validation only
elif schema_version == "1.1":
    if round_type == "initial" and inherited_inputs:
        error(...)
    if round_type == "continuation" and not current_files and not inherited_inputs:
        error(...)
```

Do not invent a second top-level data model; `source_input` remains the current/new declaration and `inherited_inputs` is the continuation-only selector list.

- [ ] **Step 4: Extend existing intake, not a parallel parser**

`l0_intake.normalize_request()` and `l0_plan_intake.normalize_frontmatter()` must both call the same contract builders/validator. Remove the current hard rejection of structured continuation and map structured `inherited_inputs` into the canonical 1.1 contract.

For legacy rule-based continuation, keep existing `--data/--dataset` behavior; inherited selection can be absent. Do not infer inherited artifacts from prose.

- [ ] **Step 5: Run focused tests GREEN and commit**

```bash
pytest tests/test_l0_input_contract.py tests/test_l0_intake.py tests/test_l0_structured_intake.py -q
git diff --check
```

Commit: `feat: version L0 contract for inherited round data`

---

### Task 2: Build the deterministic CurrentRoundDataBinding projection

**Files:**
- Create: `src/research_loop/l0_data.py`
- Create: `tests/test_round_data_binding.py`

**Interfaces:**
- Consumes: `l0_contract.load_contract(project, cand_id)` and `l0_state.restore_previous_round(project, cand_id)` result.
- Produces:
  - `current_round_data_binding_path(project_dir, cand_id) -> Path`
  - `build_current_round_data_binding(project_dir, cand_id, evidence_binding) -> dict`
  - `write_current_round_data_binding(project_dir, cand_id, evidence_binding) -> tuple[Path, str]`
  - `load_current_round_data_binding(project_dir, cand_id) -> dict`
  - `verify_current_round_data_binding(project_dir, cand_id) -> dict`
  - `L0DataError(code, detail)`

- [ ] **Step 1: Write RED tests for authorization semantics**

Cover:

```python
assert [x["origin"] for x in binding["authorized_inputs"]] == ["current_round"]
assert inherited["source_candidate_id"] == cand_n
assert inherited["artifact_class"] in {"source", "intermediate", "result"}
assert combined_paths == sorted({new_path, inherited_path})
```

Negative tests must reject:

```python
selector_path_not_in_verified_manifest
selector_hash_mismatch
selector_targeting_literature_or_audit
same_path_with_conflicting_hash
current_file_changed_before_binding
```

- [ ] **Step 2: Run RED test**

```bash
pytest tests/test_round_data_binding.py -q
```

Expected: import/module failure or missing interfaces.

- [ ] **Step 3: Implement binding as a projection, not a registry**

Use:

```python
DATA_BINDING_SCHEMA = "CurrentRoundDataBinding/v1"
ELIGIBLE_INHERITED_CLASSES = {"source", "intermediate", "result"}
```

Current files:

```python
# prefer already-verified source_input.file_manifest metadata
# otherwise hash source_input.files at binding time
```

Inherited files:

```python
verified_index = {(item["path"], item["sha256"]): item
                  for item in evidence_binding["verified_artifacts"]}
selected = verified_index[(selector["path"], selector["sha256"])]
```

Persist under:

```text
08_Audit/l0_data/<candidate_id>_current_round_data_binding.json
```

The binding stores exact L0 contract path/hash and, when used, exact previous evidence-binding path/hash.

- [ ] **Step 4: Revalidate bytes on every consumer load**

`verify_current_round_data_binding()` must verify identity, contract hash, bound evidence-binding hash, file existence, and every authorized file SHA. It must never silently rebuild a changed binding.

- [ ] **Step 5: Run GREEN and commit**

```bash
pytest tests/test_round_data_binding.py -q
git diff --check
```

Commit: `feat: add current round data binding`

---

### Task 3: Make L0 produce the binding before provider work

**Files:**
- Modify: `src/research_loop/gates.py`
- Modify: `src/research_loop/context.py`
- Modify: `tests/test_l0_state_restore.py`
- Modify: `tests/test_round_data_binding.py`

**Interfaces:**
- Consumes: successful `_audit_l0_contract()` validation and `restore_previous_round()`.
- Produces: a verified binding artifact before L0 provider/main-agent execution.

- [ ] **Step 1: Write RED gate-order tests**

Prove that a bad inherited selector or changed current file yields nonzero L0 context assembly and provider invocation count remains zero.

- [ ] **Step 2: Wire one gate path**

`_audit_l0_contract()` must execute in this order:

```text
validate current L0 declaration
→ restore previous round when applicable
→ build/write/revalidate CurrentRoundDataBinding
→ PASS
```

Return the exact `L0DataError.code` / detail on authorization failure. Do not create another runner-specific data check.

- [ ] **Step 3: Keep context metadata compact**

If L0 prompt needs the binding, inject only identity/count/role/origin metadata and the binding hash. Do not inject file bytes or the full previous manifest.

- [ ] **Step 4: Run GREEN and commit**

```bash
pytest tests/test_l0_state_restore.py tests/test_round_data_binding.py tests/test_context_isolation.py -q
git diff --check
```

Commit: `feat: bind authorized data at L0 gate`

---

### Task 4: Remove input_manifest.md as L7 machine authority

**Files:**
- Modify: `src/research_loop/commands/execution.py`
- Create: `tests/test_round_data_execution.py`
- Modify: `src/research_loop/templates.py` only if wording is needed to mark `input_manifest.md` non-authoritative.

**Interfaces:**
- Consumes: `verify_current_round_data_binding(project_dir, cand_id)`.
- Produces: execution gate + Turing workspace whose scientific inputs are exactly `authorized_inputs`.

- [ ] **Step 1: Write RED execution tests**

Prove:

```python
# binding grants file A; legacy manifest grants A+B
# workspace contains A and not B

# binding has inherited result + current raw file
# workspace contains both under deterministic input destinations

# mutate a bound file after L0
# execution gate/workspace fails before copy
```

Also prove `input_manifest.md` missing/stale cannot independently reject a native candidate with a valid binding.

- [ ] **Step 2: Replace `_registered_candidate_inputs()` authority**

Execution gate no longer parses `input_manifest.md` to decide candidate data. It requires a valid current-round binding.

Workspace staging iterates:

```python
binding = verify_current_round_data_binding(project_dir, cand_id)
for item in binding["authorized_inputs"]:
    stage(resolve_bound_path(item), destination_for(item),
          f"authorized round input: {item['origin']}:{item['role']}")
```

Keep the existing `stage()` provenance record and isolated copy boundary.

- [ ] **Step 3: Preserve narrow explicit CLI files only if they are non-scientific execution support**

Audit current `--file` semantics. If it can inject scientific data, remove/bind it; if it is only explicit execution support, keep it in a separate `inputs/explicit/` class and ensure it cannot masquerade as round scientific data.

- [ ] **Step 4: Run GREEN and commit**

```bash
pytest tests/test_round_data_execution.py tests/test_run_loop_guards.py -q
git diff --check
```

Commit: `refactor: make L7 consume round data binding`

---

### Task 5: Prove real N -> N+1 reuse, new data, and inherited-only flow

**Files:**
- Modify: `tests/test_cross_round_e2e.py`
- Modify: `tests/native_v2_helpers.py` only if fixture ownership requires deterministic real files/hashes.

**Interfaces:**
- Consumes: completed round manifest, loop memory, 1.1 continuation contract, current-round binding, L7 staging.
- Produces: end-to-end proof that round N output is selectively reusable in N+1.

- [ ] **Step 1: Add three real continuation fixtures**

1. inherited-only: select round-N `04_Analysis_Outputs/result.json`;
2. new-only: no inherited selector, declare a fresh N+1 file;
3. combined: select round-N result plus a fresh N+1 file.

All files must exist and use real SHA-256 values; no fabricated hashes.

- [ ] **Step 2: Assert least-authority behavior**

Round N must contain at least one extra unselected artifact. Assert it is verified by restore but absent from N+1 `authorized_inputs` and absent from Turing workspace.

- [ ] **Step 3: Assert fail-closed tamper boundaries**

Tamper prior selected artifact: N+1 L0 fails before provider.

Tamper current N+1 file after binding: L7 fails before staging.

- [ ] **Step 4: Run GREEN and commit**

```bash
pytest tests/test_cross_round_e2e.py tests/test_round_data_binding.py tests/test_round_data_execution.py -q
git diff --check
```

Commit: `test: prove cross-round data continuity`

---

### Task 6: Remove architectural ambiguity from docs/topology and targeted CI

**Files:**
- Modify: `src/research_loop/topology.py`
- Modify: `templates/layers/L0_skill_memory_preflight.md`
- Modify: `docs/DAG_TOPOLOGY.md`
- Modify: `.github/workflows/l0-contract.yml`

**Interfaces:**
- Consumes: final behavior from Tasks 1-5.
- Produces: one documented machine-authority chain and targeted regression coverage.

- [ ] **Step 1: Update L0/L7 responsibility text**

L0 must say it verifies current declarations, restores prior state, and freezes authorized current-round data references without interpreting data. L7 must say it stages only the current-round data binding.

- [ ] **Step 2: Mark legacy input manifest correctly**

Documentation must not describe `00_Preflight/input_manifest.md` as an execution authorization source. If retained, call it legacy/human-readable only.

- [ ] **Step 3: Expand L0 contract CI file filters/tests**

Include `l0_data.py`, execution authority changes, and the new focused tests.

- [ ] **Step 4: Run targeted architecture regression**

```bash
pytest tests/test_l0_input_contract.py \
       tests/test_l0_intake.py \
       tests/test_l0_structured_intake.py \
       tests/test_l0_state_restore.py \
       tests/test_round_data_binding.py \
       tests/test_round_data_execution.py \
       tests/test_cross_round_e2e.py \
       tests/test_context_isolation.py \
       tests/test_run_loop_guards.py -q
git diff --check
```

Commit: `docs: define single round data authority`

---

### Task 7: Full verification and scope audit

**Files:**
- No production changes unless a verified test failure identifies a root-cause defect.

**Interfaces:**
- Consumes: complete feature branch.
- Produces: evidence that the redesign is integrated and has not regressed L4 or the full RLR suite.

- [ ] **Step 1: Run compile checks**

```bash
python -m py_compile \
  src/research_loop/l0_contract.py \
  src/research_loop/l0_intake.py \
  src/research_loop/l0_plan_intake.py \
  src/research_loop/l0_data.py \
  src/research_loop/l0_state.py \
  src/research_loop/gates.py \
  src/research_loop/context.py \
  src/research_loop/commands/execution.py
```

- [ ] **Step 2: Run the complete test suite**

```bash
pytest -q
git diff --check d6352c0ceeb649efa892e36acc66f209d33920be HEAD
```

Expected: all tests PASS; whitespace PASS.

- [ ] **Step 3: Explicit scope audit**

Confirm no new database/storage dependency, no L4 semantic changes, no hypothesis-ledger duplication, no second current-round input registry, no raw previous-round context dump, and no compatibility fallback that silently reconstructs missing bindings.

- [ ] **Step 4: Review CI and prepare PR for review**

Target branch: `codex/l4a-source-metadata-contract`.

Do not merge until GitHub CI is green and the real local acceptance path has validated external/local data behavior if the final implementation touches machine-local paths not representable in CI.
