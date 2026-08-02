# Hypothesis Pool Core Reactivation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic long-lived hypothesis-pool projection, mandatory pre-L1 historical recall, and append-only reuse/revision/derivation of historical hypotheses with L3 blocker review.

**Architecture:** The existing SQLite hypothesis ledger remains authoritative. New pure read modules build cursor-bound pool and recall artifacts; `ContextManifest/v2` binds the exact recall used by L1. L1 persistence reuses or creates hypothesis identities according to explicit `origin`, while L3 records append-only reactivation reviews and downstream obligations. Strict reopening of `FALSIFIED` hypotheses and long-term export are deliberately deferred to the second implementation plan.

**Tech Stack:** Python 3.11/3.12, SQLite, `jsonschema`, argparse CLI, pytest, GitHub Actions on Windows.

## Global Constraints

- SQLite ledger facts remain append-only; no historical event, occurrence, version, or workflow state may be rewritten.
- Pool and recall operate only over finalized emissions.
- Native L1 recall is mandatory; a valid zero-result recall passes, but missing/stale/hash-invalid recall blocks L1.
- L1 remains limited to 1–12 hypotheses.
- 1–4 hypotheses skip L2; 5–12 run L2.
- `REACTIVATE` reuses the exact `hypothesis_id` and creates a new occurrence.
- `REVISE` creates a new version in the same family.
- `DERIVE` creates a new family/version linked to one or more parents.
- Ordinary reactivation of `FALSIFIED` versions remains blocked in this phase.
- Omitted `origin` normalizes to `NEW`; source IDs are forbidden unless `origin` is explicit.
- No embedding service or new runtime dependency is introduced.
- Legacy profiles remain readable and do not receive new recall/reactivation events.

---

## File structure

**New files**

- `src/research_loop/hypothesis_pool.py`: deterministic cursor-bound pool projection and query filters.
- `src/research_loop/hypothesis_recall.py`: deterministic recall ranking, immutable artifact creation, loading, and validation.
- `tests/test_hypothesis_pool.py`: pool projection and eligibility tests.
- `tests/test_hypothesis_recall.py`: recall ranking, hash/cursor integrity, and zero-result tests.
- `tests/test_hypothesis_reactivation.py`: L1 identity reuse/revision/derivation and L3 blocker review tests.
- `tests/test_hypothesis_recall_cli.py`: CLI and `ContextManifest/v2` integration tests.
- `docs/HYPOTHESIS_POOL.md`: user-facing pool, recall, and reactivation workflow.

**Modified files**

- `src/research_loop/hypothesis_contracts.py`: L1 origin fields, L2 blocker reviews, L3 reactivation assessment and obligations.
- `src/research_loop/hypothesis_ledger.py`: read-only finalized cursor helpers plus append-only `REPROPOSED`, `REVISED`, `DERIVED`, and `REACTIVATION_REVIEWED` persistence.
- `src/research_loop/constraint_validation.py`: source/recall constraints, L2/L3 blocker coverage, selection restrictions, and obligation propagation checks.
- `src/research_loop/context.py`: load and bind recall artifact; inject node-specific recall views.
- `src/research_loop/commands/ledger.py`: pool/recall CLI commands and native receipt verification.
- `src/research_loop/cli.py`: stable CLI parsers and activated-command registration.
- `src/research_loop/topology.py`: L1/L2/L3 instructions for recall and blocker review.
- `src/run_loop.py`: generate recall before native L1 context assembly.
- `tests/native_v2_helpers.py`: create valid recall artifacts in native receipt fixtures.
- `templates/layers/L1_*.md`, `templates/layers/L2_*.md`, `templates/layers/L3_*.md`: explicit output and review instructions.
- `README.md`: concise command and lifecycle documentation.

---

### Task 1: Deterministic hypothesis-pool projection

**Files:**
- Create: `src/research_loop/hypothesis_pool.py`
- Create: `tests/test_hypothesis_pool.py`
- Modify: `src/research_loop/hypothesis_ledger.py`

**Interfaces:**
- Consumes: an existing `HypothesisLedger`, optional finalized `as_of` commit cursor, and optional filters.
- Produces:
  - `latest_finalized_commit_seq(con: sqlite3.Connection) -> int`
  - `build_pool(ledger: HypothesisLedger, *, as_of: int | None = None) -> dict[str, Any]`
  - `search_pool(ledger: HypothesisLedger, *, text: str = "", as_of: int | None = None, eligibility: set[str] | None = None, epistemic_status: set[str] | None = None, workflow_status: set[str] | None = None, limit: int = 50) -> dict[str, Any]`
  - pool envelope fields: `schema_version`, `store_id`, `as_of_commit_seq`, `records`, `projection_hash`.

- [ ] **Step 1: Write failing projection tests**

Create fixtures that commit and finalize L1, L2, and L3 facts. Assert that a rejected hypothesis remains present with attack/rejection history and computed eligibility.

```python
def test_pool_keeps_rejected_hypothesis_with_attack_history(native_project):
    ledger, hid = seed_rejected_hypothesis(native_project)

    pool = build_pool(ledger)
    record = next(item for item in pool["records"] if item["hypothesis_id"] == hid)

    assert record["occurrence_count"] == 1
    assert record["attack_count"] >= 1
    assert record["rejection_count"] == 1
    assert record["latest_workflow_status"] == "REJECTED"
    assert record["reactivation_eligibility"] == "ELIGIBLE_WITH_BASIS"
    assert record["last_rejection"]["round_id"] == "1"
```

Add deterministic cursor and rebuild tests:

```python
def test_pool_is_stable_at_fixed_finalized_cursor(native_project):
    ledger, first_hid = seed_rejected_hypothesis(native_project)
    first = build_pool(ledger)
    seed_second_hypothesis(native_project)
    rebuilt = build_pool(ledger, as_of=first["as_of_commit_seq"])

    assert rebuilt == first
    assert all(item["hypothesis_id"] != second_hid for item in rebuilt["records"])
```

- [ ] **Step 2: Run the projection tests and verify RED**

Run:

```bash
pytest tests/test_hypothesis_pool.py -v
```

Expected: collection/import failure because `research_loop.hypothesis_pool` does not exist.

- [ ] **Step 3: Add a finalized-cursor read helper**

In `HypothesisLedger`, add a read-only method rather than exposing private SQL internals:

```python
def latest_finalized_commit_seq(self) -> int:
    con = self._connect(readonly=True)
    try:
        row = con.execute(
            "SELECT COALESCE(MAX(m.commit_seq),0) "
            "FROM emissions m JOIN committed_emissions c "
            "ON c.delta_hash=m.delta_hash"
        ).fetchone()
        return int(row[0])
    finally:
        con.close()
```

- [ ] **Step 4: Implement the minimal pool projection**

`hypothesis_pool.py` must query finalized events at or before the cursor and aggregate by hypothesis version. Decode `payload_json` and `falsification_criteria_json` before returning records. Compute eligibility using this pure rule:

```python
def _eligibility(epistemic_status: str, latest_workflow_status: str,
                 rejection_count: int, unresolved_blockers: list[str]) -> tuple[str, list[str]]:
    if epistemic_status == "FALSIFIED":
        return "BLOCKED_FALSIFIED", ["formal reopening is required"]
    if latest_workflow_status == "ARCHIVED" or epistemic_status == "CONTRADICTED":
        return "REQUIRES_EXPLICIT_OVERRIDE", ["explicit reviewed basis is required"]
    if rejection_count or unresolved_blockers or epistemic_status == "INSUFFICIENT_EVIDENCE":
        return "ELIGIBLE_WITH_BASIS", ["new evidence or changed conditions are required"]
    return "ELIGIBLE", []
```

Use stable ordering by `hypothesis_id`; derive `projection_hash` from canonical JSON excluding the hash field.

- [ ] **Step 5: Run projection tests and full ledger regression tests**

Run:

```bash
pytest tests/test_hypothesis_pool.py tests/test_hypothesis_ledger.py tests/test_profile_aware_consumers.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/research_loop/hypothesis_pool.py src/research_loop/hypothesis_ledger.py tests/test_hypothesis_pool.py
git commit -m "feat: add deterministic hypothesis pool projection"
```

---

### Task 2: Cursor-bound historical recall artifacts

**Files:**
- Create: `src/research_loop/hypothesis_recall.py`
- Create: `tests/test_hypothesis_recall.py`
- Modify: `src/research_loop/hypothesis_pool.py`

**Interfaces:**
- Consumes: pool projection, candidate question/claim text, project/candidate/round identity, bounded limit.
- Produces:
  - `recall_path(project_dir: str | Path, candidate_id: str, round_id: str) -> Path`
  - `create_recall(ledger: HypothesisLedger, project_dir: str | Path, candidate_id: str, round_id: str, *, query_text: str, limit: int = 50, as_of: int | None = None) -> dict[str, Any]`
  - `load_recall(project_dir: str | Path, candidate_id: str, round_id: str) -> dict[str, Any]`
  - `validate_recall(ledger: HypothesisLedger, project_dir: str | Path, artifact: dict[str, Any], *, expected_candidate_id: str, expected_round_id: str) -> None`

- [ ] **Step 1: Write failing recall tests**

```python
def test_recall_returns_rejected_history_and_records_scores(native_project):
    ledger, hid = seed_rejected_hypothesis(native_project, statement="ECM expression declines")

    artifact = create_recall(
        ledger, native_project, "C2", "2",
        query_text="declining ECM expression", limit=10,
    )

    assert artifact["results"][0]["hypothesis_id"] == hid
    assert artifact["results"][0]["reactivation_eligibility"] == "ELIGIBLE_WITH_BASIS"
    assert artifact["results"][0]["scores"]["keyword"] > 0
    assert artifact["artifact_hash"]
```

Add tests for a valid zero-result artifact, later-event non-leakage, tampering, store/project mismatch, and a limit outside `1..200`.

- [ ] **Step 2: Run recall tests and verify RED**

```bash
pytest tests/test_hypothesis_recall.py -v
```

Expected: import failure for `research_loop.hypothesis_recall`.

- [ ] **Step 3: Implement deterministic query normalization and ranking**

Use Unicode NFC, lowercase, and alphanumeric token extraction. Ranking fields are explicit:

```python
scores = {
    "exact_hypothesis": 1 if requested_hypothesis_id == record["hypothesis_id"] else 0,
    "exact_family": 1 if requested_family_id == record["hypothesis_family_id"] else 0,
    "fts": fts_score,
    "keyword": keyword_score,
}
```

Sort by descending exact-hypothesis, exact-family, FTS, keyword, then ascending `hypothesis_id`. The first implementation may use deterministic token overlap when SQLite FTS is unavailable, but the artifact must label the ranking channel actually used.

- [ ] **Step 4: Implement immutable artifact creation and validation**

Write artifacts with exclusive creation. On retry, identical canonical content is accepted; different content at the same candidate/round path raises `LedgerError`. Store `artifact_hash` over all fields except `artifact_hash` and `generated_at`; store the file SHA256 separately when bound into a context manifest.

Validation must confirm:

```python
artifact["schema_version"] == "HypothesisRecall/v1"
artifact["store_id"] == ledger.store_id
artifact["project_id"] == ledger.require_binding(project_dir)["project_id"]
artifact["candidate_id"] == expected_candidate_id
artifact["round_id"] == expected_round_id
artifact["as_of_commit_seq"] <= ledger.latest_finalized_commit_seq()
content_hash(without_hash_and_generated_at) == artifact["artifact_hash"]
```

Every returned hypothesis/version/occurrence and blocker event must exist in finalized facts at the artifact cursor.

- [ ] **Step 5: Run recall and pool tests**

```bash
pytest tests/test_hypothesis_recall.py tests/test_hypothesis_pool.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/research_loop/hypothesis_recall.py src/research_loop/hypothesis_pool.py tests/test_hypothesis_recall.py
git commit -m "feat: add immutable hypothesis recall artifacts"
```

---

### Task 3: Pool and recall CLI surfaces

**Files:**
- Modify: `src/research_loop/commands/ledger.py`
- Modify: `src/research_loop/cli.py`
- Create: `tests/test_hypothesis_recall_cli.py`

**Interfaces:**
- Produces commands:
  - `hypothesis-pool-list PROJECT --as-of N --eligibility VALUE --limit N`
  - `hypothesis-pool-search PROJECT --text TEXT --as-of N --limit N`
  - `hypothesis-pool-show PROJECT HYPOTHESIS_ID --as-of N`
  - `hypothesis-recall PROJECT CAND --round-id ROUND --query TEXT --limit N`

- [ ] **Step 1: Write failing CLI parser and output tests**

```python
def test_hypothesis_recall_cli_writes_artifact(native_project, capsys):
    rc = main([
        "hypothesis-recall", str(native_project), "C2",
        "--round-id", "2", "--query", "ECM decline",
        "--knowledge-store", os.environ["RLR_HYPOTHESIS_STORE"],
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["artifact_path"]).is_file()
```

Test all commands require an activated bound project and reject invalid limits.

- [ ] **Step 2: Run CLI tests and verify RED**

```bash
pytest tests/test_hypothesis_recall_cli.py -v
```

Expected: argparse reports unknown commands.

- [ ] **Step 3: Add thin command handlers**

Handlers must call the new modules; they must not duplicate SQL or ranking logic. Print JSON only on stdout and diagnostics on stderr.

- [ ] **Step 4: Add argparse definitions and activation enforcement**

Add the four command names to `activated_commands`. Use `choices` for eligibility values and bounded integer validation in command handlers.

- [ ] **Step 5: Run CLI tests and CLI help smoke test**

```bash
pytest tests/test_hypothesis_recall_cli.py -v
python research_loop_v04.py --help
python research_loop_v04.py hypothesis-recall --help
```

Expected: PASS/exit 0.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/research_loop/commands/ledger.py src/research_loop/cli.py tests/test_hypothesis_recall_cli.py
git commit -m "feat: expose hypothesis pool and recall CLI"
```

---

### Task 4: Mandatory native L1 recall binding

**Files:**
- Modify: `src/research_loop/context.py`
- Modify: `src/research_loop/commands/ledger.py`
- Modify: `src/run_loop.py`
- Modify: `tests/native_v2_helpers.py`
- Modify: `tests/test_hypothesis_recall_cli.py`
- Test: `tests/test_run_receipts.py`

**Interfaces:**
- `ContextManifest/v2` adds:

```json
"hypothesis_recall": {
  "artifact_path": "...",
  "artifact_sha256": "...",
  "artifact_hash": "...",
  "as_of_commit_seq": 12,
  "returned_hypothesis_ids": ["H:..."]
}
```

- [ ] **Step 1: Write failing context and receipt tests**

Test that native L1 context assembly fails when recall is missing, accepts a zero-result artifact, injects a concise L1 view, and writes exact recall metadata into `ContextManifest/v2`.

```python
def test_native_l1_context_requires_recall(native_project):
    result = EngineAPI().assemble_context(native_project, "C1", "L1")
    assert result.returncode == 2
    assert "hypothesis recall" in result.stderr.lower()
```

Test emit-delta rejects a manifest whose recall file changed after context assembly.

- [ ] **Step 2: Run targeted tests and verify RED**

```bash
pytest tests/test_hypothesis_recall_cli.py tests/test_run_receipts.py -v
```

Expected: L1 currently assembles without recall and manifests lack `hypothesis_recall`.

- [ ] **Step 3: Bind recall in context assembly**

For native L1:

1. Load candidate question and claim.
2. Require the candidate/round recall artifact.
3. Validate it against the ledger and current candidate/round.
4. Inject only the concise recall fields into rendered L1 context.
5. Add the exact path, SHA256, artifact hash, cursor, and IDs to the manifest.

For L2 and L3, load the recall referenced by the finalized L1 provenance and inject progressively deeper views; do not perform a fresh search.

- [ ] **Step 4: Verify recall again at native emission boundary**

In `_validate_native_receipts`, when `args.node == "L1"`, require `manifest["hypothesis_recall"]`, recompute file SHA256, load/validate its contents, and confirm IDs/cursor/hash match the manifest. Store the recall metadata in the L1 commit receipt provenance.

- [ ] **Step 5: Generate recall automatically in the canonical runner**

Before native L1 `assemble_context`, call the in-process `hypothesis-recall` command using the candidate question and claim as `query_text`. Do not overwrite an existing different artifact. A zero-result artifact proceeds normally.

- [ ] **Step 6: Update native test helpers**

`write_native_emission_receipts(..., node="L1")` must create a valid recall artifact and include its metadata in synthetic manifests. Existing native receipt tests must not bypass the new gate.

- [ ] **Step 7: Run context, receipt, and runner tests**

```bash
pytest tests/test_hypothesis_recall_cli.py tests/test_run_receipts.py tests/test_main_agent_mode.py tests/test_engine_api.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/research_loop/context.py src/research_loop/commands/ledger.py src/run_loop.py tests/native_v2_helpers.py tests/test_hypothesis_recall_cli.py tests/test_run_receipts.py
git commit -m "feat: require cursor-bound recall before native L1"
```

---

### Task 5: Extend the L1/L2/L3 contracts

**Files:**
- Modify: `src/research_loop/hypothesis_contracts.py`
- Create: `tests/test_hypothesis_reactivation.py`

**Interfaces:**
- L1 item fields: `origin`, `source_hypothesis_id`, `source_occurrence_id`, `parent_hypothesis_ids`, `change_summary`, `reactivation_basis`.
- L2 optional `historical_blocker_reviews` items.
- L3 conditional `reactivation_assessment` and `downstream_obligations`.

- [ ] **Step 1: Write schema RED tests**

```python
def test_l1_reactivate_requires_source_and_basis():
    delta = l1_delta(origin="REACTIVATE")
    errors = validate_submission("L1", delta, schema_version="2.1")
    assert any("source_hypothesis_id" in error for error in errors)
```

Add cases for omitted origin normalizing later to NEW, source IDs forbidden for NEW, REVISE requiring `change_summary`, DERIVE requiring non-empty parents, L3 unresolved+selected invalid at the cross-delta layer, and partial resolution requiring obligations.

- [ ] **Step 2: Run schema tests and verify RED**

```bash
pytest tests/test_hypothesis_reactivation.py -v
```

Expected: new fields are absent or accepted without conditional validation.

- [ ] **Step 3: Add reusable schema definitions**

Define exact enums:

```python
ORIGINS = {"NEW", "REACTIVATE", "REVISE", "DERIVE"}
BASIS_TYPES = {
    "NEW_EVIDENCE", "NEW_DATA", "NEW_METHOD", "CHANGED_SCOPE",
    "CHANGED_FEASIBILITY", "USER_RECONSIDERATION",
}
BLOCKER_VERDICTS = {"RESOLVED", "PARTIALLY_RESOLVED", "UNRESOLVED", "NOT_APPLICABLE"}
OBLIGATION_TYPES = {"QC", "STOP_RULE", "DATA_REQUIREMENT"}
```

Use JSON Schema `allOf/if/then/not` so invalid combinations fail before persistence.

- [ ] **Step 4: Preserve backward compatibility**

Do not make `origin` globally required in the submission schema. The ledger normalizer will insert `origin: NEW` before persisted validation. The persisted L1 schema requires `origin`.

- [ ] **Step 5: Run schema and compatibility tests**

```bash
pytest tests/test_hypothesis_reactivation.py tests/test_compatibility_profiles.py tests/test_v21_acceptance.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/research_loop/hypothesis_contracts.py tests/test_hypothesis_reactivation.py
git commit -m "feat: define hypothesis reactivation contracts"
```

---

### Task 6: Append-only L1 identity reuse, revision, and derivation

**Files:**
- Modify: `src/research_loop/hypothesis_ledger.py`
- Modify: `src/research_loop/constraint_validation.py`
- Modify: `tests/test_hypothesis_reactivation.py`

**Interfaces:**
- L1 persistence receives recall provenance from the validated native receipt boundary.
- New event types: `REPROPOSED`, `REVISED`, `DERIVED`.
- Existing `occurrences` identity remains `project_id + candidate_id + round_id + hypothesis_id`.

- [ ] **Step 1: Write identity and history RED tests**

```python
def test_reactivate_reuses_version_and_creates_new_occurrence(native_project):
    ledger, source = seed_rejected_hypothesis(native_project, candidate="C1", round_id="1")
    recall = create_recall(ledger, native_project, "C2", "2", query_text=source.statement)

    result = commit_reactivated_l1(native_project, recall, source)
    item = result.normalized_delta["hypotheses"][0]

    assert item["hypothesis_id"] == source.hypothesis_id
    assert item["hypothesis_family_id"] == source.family_id
    graph = ledger.graph(source.hypothesis_id)
    assert len(graph["occurrences"]) == 2
    assert [event["event_type"] for event in graph["events"]].count("REPROPOSED") == 1
    assert prior_occurrence_status(ledger, source.occurrence_id) == "REJECTED"
```

Add tests that REACTIVATE rejects changed definitions, REVISE creates same-family new ID, DERIVE creates a new family, duplicate current-round reuse fails, FALSIFIED fails, and post-cursor source IDs fail.

- [ ] **Step 2: Run identity tests and verify RED**

```bash
pytest tests/test_hypothesis_reactivation.py -k "reactivate or revise or derive" -v
```

Expected: current L1 always creates/uses identity solely from the submitted definition and emits only `PROPOSED`.

- [ ] **Step 3: Add finalized source lookup helpers**

Implement private transaction-scoped helpers in `HypothesisLedger`:

```python
def _version_at_cursor(con, hypothesis_id: str, as_of: int) -> sqlite3.Row: ...
def _occurrence_at_cursor(con, occurrence_id: str, as_of: int) -> sqlite3.Row: ...
def _epistemic_status_at_cursor(con, hypothesis_id: str, as_of: int) -> str: ...
```

They must require at least one finalized event at or before the cursor.

- [ ] **Step 4: Normalize omitted origin and validate recall sources**

Before schema persistence validation, insert `origin = "NEW"` where omitted. For non-NEW items, require the exact source IDs to be present in the recall metadata bound to the L1 commit provenance. Never infer historical reuse from identical text alone.

- [ ] **Step 5: Implement each origin path**

- `NEW`: retain current behavior and emit `PROPOSED`.
- `REACTIVATE`: verify exact definition hash, reuse source IDs, insert a new occurrence, emit `REPROPOSED` with source IDs, basis, recall hash, and cursor.
- `REVISE`: verify normalized statement equality and changed definition hash, reuse family ID, create new version/occurrence, emit `REVISED` with parent.
- `DERIVE`: verify different normalized statement, create new family/version/occurrence, emit `DERIVED` with parents.

All paths set the new occurrence workflow status to `PROPOSED`. None updates prior occurrences.

- [ ] **Step 6: Run reactivation and ledger regression tests**

```bash
pytest tests/test_hypothesis_reactivation.py tests/test_hypothesis_ledger.py tests/test_v21_acceptance.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 6**

```bash
git add src/research_loop/hypothesis_ledger.py src/research_loop/constraint_validation.py tests/test_hypothesis_reactivation.py
git commit -m "feat: persist reactivated and revised hypothesis occurrences"
```

---

### Task 7: Historical blocker review and downstream obligations

**Files:**
- Modify: `src/research_loop/constraint_validation.py`
- Modify: `src/research_loop/hypothesis_ledger.py`
- Modify: `tests/test_hypothesis_reactivation.py`

**Interfaces:**
- L2 reviews historical blocker event IDs when L2 runs.
- L3 records `REACTIVATION_REVIEWED` and obligations.
- L4/L5/L6/L7 consume obligations through finalized upstream facts.

- [ ] **Step 1: Write blocker/obligation RED tests**

```python
def test_l3_cannot_select_unresolved_reactivation(native_project):
    with pytest.raises(LedgerError, match="UNRESOLVED"):
        commit_l3(
            disposition="SELECTED",
            reactivation_assessment={"basis_verdict": "UNRESOLVED", ...},
        )
```

```python
def test_partial_resolution_requires_and_propagates_obligation(native_project):
    l3 = commit_l3(
        disposition="SELECTED",
        reactivation_assessment={"basis_verdict": "PARTIALLY_RESOLVED", ...},
        downstream_obligations=[{
            "obligation_id": "RO1", "type": "QC",
            "description": "repeat analysis after covariate adjustment",
            "source_blocker_event_ids": [blocker_id],
        }],
    )
    assert l3.normalized_delta["triage"][0]["downstream_obligations"][0]["obligation_id"] == "RO1"
```

Add tests that L3 performs this review when an L2 skip receipt exists, and L2 review must cover all material blockers when five or more hypotheses run L2.

- [ ] **Step 2: Run blocker tests and verify RED**

```bash
pytest tests/test_hypothesis_reactivation.py -k "blocker or obligation or partial" -v
```

Expected: no blocker constraints or reactivation review events exist.

- [ ] **Step 3: Validate L2/L3 coverage**

For non-NEW hypotheses, derive material historical blocker IDs from the exact recall artifact. When L2 exists, `historical_blocker_reviews` must cover every material blocker exactly once. When L2 is skipped, L3 `prior_blocking_event_ids` must cover them directly.

- [ ] **Step 4: Enforce selection constraints**

- `UNRESOLVED + SELECTED` fails.
- `PARTIALLY_RESOLVED + SELECTED` requires one or more obligations.
- `RESOLVED` may select without obligations.
- Rejected items may retain unresolved assessments without obligations.
- FALSIFIED items remain unselectable.

- [ ] **Step 5: Persist append-only review facts**

Emit `REACTIVATION_REVIEWED` for each reviewed non-NEW hypothesis. Store verdict, blocker IDs, remaining risks, and obligations in payload; do not create a mutable obligation table in this phase.

- [ ] **Step 6: Enforce obligations before execution**

L4 strategies must reference selected hypotheses with obligations. L5 must map each obligation to a matching QC checkpoint, stop rule, or data requirement. L6 APPROVE fails if any obligation remains unmatched; therefore L7 automatically inherits the existing finalized-L6 gate.

- [ ] **Step 7: Run blocker and downstream regression tests**

```bash
pytest tests/test_hypothesis_reactivation.py tests/test_v21_acceptance.py tests/test_conditional_l2_skip.py tests/test_gates_v2.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 7**

```bash
git add src/research_loop/constraint_validation.py src/research_loop/hypothesis_ledger.py tests/test_hypothesis_reactivation.py
git commit -m "feat: review and propagate historical hypothesis blockers"
```

---

### Task 8: Topology, templates, and user documentation

**Files:**
- Modify: `src/research_loop/topology.py`
- Modify: `templates/layers/L1_*.md`
- Modify: `templates/layers/L2_*.md`
- Modify: `templates/layers/L3_*.md`
- Create: `docs/HYPOTHESIS_POOL.md`
- Modify: `README.md`
- Test: `tests/test_persona_catalog.py`
- Test: `tests/test_template_layering.py`

**Interfaces:**
- Human and agent instructions use the same origin/eligibility/blocker terminology as the schemas.

- [ ] **Step 1: Write failing documentation/template assertions**

Assert the rendered L1 contract mentions `NEW/REACTIVATE/REVISE/DERIVE`, L2 mentions historical blocker review, and L3 mentions direct review when L2 is skipped.

- [ ] **Step 2: Run template tests and verify RED**

```bash
pytest tests/test_persona_catalog.py tests/test_template_layering.py -v
```

Expected: required wording is absent.

- [ ] **Step 3: Update topology instructions**

Keep the DAG unchanged. Add precise MUST rules to L1/L2/L3; do not expose full historical attack prose to L1.

- [ ] **Step 4: Update templates**

Document exact JSON fields and the distinction between workflow rejection, epistemic falsification, reproposal, revision, and derivation.

- [ ] **Step 5: Write the user guide**

`docs/HYPOTHESIS_POOL.md` must include:

```text
hypothesis-pool-list
hypothesis-pool-search
hypothesis-pool-show
hypothesis-recall
```

Include one end-to-end example: Round 1 rejected; Round 2 recall; new evidence; `REACTIVATE`; Round 2 selected. State explicitly that old rejection and attacks remain unchanged.

- [ ] **Step 6: Run documentation/template tests**

```bash
pytest tests/test_persona_catalog.py tests/test_template_layering.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 8**

```bash
git add src/research_loop/topology.py templates/layers docs/HYPOTHESIS_POOL.md README.md tests/test_persona_catalog.py tests/test_template_layering.py
git commit -m "docs: explain hypothesis recall and reactivation"
```

---

### Task 9: Multi-round end-to-end verification

**Files:**
- Modify: `tests/native_v2_helpers.py`
- Create: `tests/test_hypothesis_reactivation_e2e.py`
- Modify: `.github/workflows/ci.yml` only if the new tests expose an existing omission; otherwise leave workflow unchanged.

**Interfaces:**
- Validates the complete first-phase flow without strict FALSIFIED reopening or export.

- [ ] **Step 1: Write the end-to-end test**

```python
def test_rejected_hypothesis_is_recalled_reproposed_and_selected(native_project):
    source = run_round_one_to_rejected(native_project)
    recall = run_recall_for_round_two(native_project, source)
    reproposed = run_round_two_l1_reactivation(native_project, recall, source)
    selected = run_round_two_l3_selection(native_project, reproposed)

    graph = source.ledger.graph(source.hypothesis_id)
    assert any(e["event_type"] == "REJECTED" and e["round_id"] == "1" for e in graph["events"])
    assert any(e["event_type"] == "REPROPOSED" and e["round_id"] == "2" for e in graph["events"])
    assert any(e["event_type"] == "SELECTED" and e["round_id"] == "2" for e in graph["events"])
    assert len(graph["occurrences"]) == 2
    assert selected["hypothesis_id"] == source.hypothesis_id
```

Also test fixed-cursor recall, L2 skipped at 1–4 with L3 blocker review, and five hypotheses causing L2 history review.

- [ ] **Step 2: Run E2E test and verify any remaining RED**

```bash
pytest tests/test_hypothesis_reactivation_e2e.py -v
```

Expected: any missing integration is exposed before full-suite execution.

- [ ] **Step 3: Apply only minimal integration corrections**

Do not add new features. Fix only wiring needed for the approved first-phase flow.

- [ ] **Step 4: Run all targeted tests**

```bash
pytest tests/test_hypothesis_pool.py tests/test_hypothesis_recall.py tests/test_hypothesis_recall_cli.py tests/test_hypothesis_reactivation.py tests/test_hypothesis_reactivation_e2e.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite and static checks**

```bash
pytest -q
git diff --check
python research_loop_v04.py --help
python run_loop.py --help
```

Expected: all tests pass on the local Python version and both CLI commands exit 0.

- [ ] **Step 6: Push branch and open draft PR**

PR title:

```text
feat: add long-lived hypothesis recall and reactivation
```

PR body must list the deferred second phase: strict FALSIFIED reopening and cursor-bound export/snapshot support.

- [ ] **Step 7: Verify GitHub Actions matrix**

Require Windows Python 3.11 and 3.12 to pass all tests. Review exact job logs rather than relying solely on aggregate status.

- [ ] **Step 8: Request code review and resolve findings**

Require no unresolved review threads and rerun CI after substantive changes.

- [ ] **Step 9: Commit any final review-only corrections**

```bash
git add <reviewed-files>
git commit -m "fix: address hypothesis reactivation review"
```

Do not merge until verification-before-completion and finishing-development-branch checks are complete.
