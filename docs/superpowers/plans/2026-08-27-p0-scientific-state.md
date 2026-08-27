# P0 Scientific State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three P0 gaps as one coherent path: first-class ResearchQuestion lifecycle, deterministic scientific-state relations, and evidence-aware hypothesis ranking.

**Architecture:** Keep `HypothesisLedger` as the only scientific fact authority. Add question facts to the same SQLite store, project committed ledger facts into a read-only Scientific State view, derive `EvidenceProfile` from that projection, and feed the profile into the existing ranking machinery without replacing Elo, DAG authority, or formal decisions.

**Tech Stack:** Python stdlib, SQLite, existing JSON Schema/jsonschema contracts, existing RLR CLI/runtime, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-p0-scientific-state-design.md`

## Global Constraints

- Target only native v2.1/new runs; do not enlarge v2.0 compatibility.
- `HypothesisLedger` remains the single scientific persistence authority.
- Graphs, EvidenceProfiles, ranking artifacts, and reports are rebuildable projections only.
- Do not add Neo4j, ORKG, OpenAlex, MLflow, DVC, AiiDA, LangGraph, or a second ledger/database in P0.
- Do not change the DAG or create a new decision authority.
- L10b owns any Question revision decision; L0/new-candidate may only bind/validate an already-authorized Question identity.
- Preserve existing ranking scheduler, A/B+B/A fairness, checkpoint/replay, and advisory-only semantics.
- TDD: write a failing boundary test before each production change.
- No unrelated refactor, formatting sweep, dependency upgrade, or legacy migration work.

---

## File Structure

- Modify `src/research_loop/hypothesis_ledger.py`: question tables/binding APIs; deterministic graph projection query support; ranking inputs source.
- Modify `src/research_loop/hypothesis_contracts.py`: native-v2.1 L10b `question_transition` contract only.
- Modify `src/research_loop/commands/lifecycle.py`: initial/continuation question binding at candidate creation and fail-closed validation.
- Modify `src/research_loop/commands/continuation.py`: freeze L10b question transition and question identity into loop memory.
- Modify `templates/layers/L10b_final_decision.md`: tell Oppenheimer when/how to emit question transition; dynamic schema remains authority.
- Create `src/research_loop/scientific_state.py`: pure transformations from ledger graph facts to normalized relations and `EvidenceProfile`; no writes, no provider/filesystem authority.
- Modify `src/research_loop/ranking.py`: carry EvidenceProfile snapshots/hashes into candidate snapshots and pairwise prompt/checkpoint validation.
- Test primarily in `tests/test_hypothesis_ledger.py`, `tests/test_ranking_cli.py`, `tests/test_cross_round_e2e.py`; add one focused `tests/test_scientific_state.py` for pure projection behavior.

---

### Task 1: First-class Question facts in the existing ledger

**Files:**
- Modify: `src/research_loop/hypothesis_ledger.py`
- Test: `tests/test_hypothesis_ledger.py`

**Interfaces:**
- Produce `HypothesisLedger.bind_question(project_dir, candidate_id, round_id, statement, *, parent_question_id=None, relationship=None, source_commit_seq=None) -> dict`.
- Produce `HypothesisLedger.question_binding(project_dir, candidate_id, round_id) -> dict`.
- Returned binding keys: `question_id`, `question_family_id`, `statement`, `parent_question_id`, `relationship`, `candidate_id`, `round_id`.
- Initial question: `parent_question_id=None`, `relationship=None`.
- Revised question: same family as parent and `relationship="REVISION_OF"`.
- KEEP continuation: same `question_id` in a new occurrence; no new version.

- [ ] **Step 1: Write failing ledger tests for initial, KEEP, REVISE, append-only behavior**

```python
def test_question_binding_is_first_class_and_append_only(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "shared.sqlite")
    ledger.bind_project(project, "P1")

    q1 = ledger.bind_question(project, "C1", "1", "Does A alter B?")
    kept = ledger.bind_question(
        project, "C2", "2", "Does A alter B?", parent_question_id=q1["question_id"],
        relationship="KEEP",
    )
    revised = ledger.bind_question(
        project, "C3", "3", "Under condition X, does A alter B?",
        parent_question_id=q1["question_id"], relationship="REVISION_OF",
        source_commit_seq=7,
    )

    assert kept["question_id"] == q1["question_id"]
    assert revised["question_id"] != q1["question_id"]
    assert revised["question_family_id"] == q1["question_family_id"]
    assert revised["parent_question_id"] == q1["question_id"]
    assert ledger.question_binding(project, "C3", "3") == revised
```

Add direct SQLite mutation assertions mirroring existing append-only hypothesis tests: UPDATE/DELETE of question families/versions/occurrences must raise `sqlite3.IntegrityError`.

- [ ] **Step 2: Run the focused test and verify failure**

Run:
```powershell
rtk proxy python -m pytest tests\test_hypothesis_ledger.py -k "question_binding" -q
```
Expected: FAIL because question tables/APIs do not yet exist.

- [ ] **Step 3: Implement the minimal ledger model**

In `_initialize()` add only these append-only tables/triggers:

```sql
CREATE TABLE IF NOT EXISTS question_families (
    question_family_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_versions (
    question_id TEXT PRIMARY KEY,
    question_family_id TEXT NOT NULL REFERENCES question_families(question_family_id),
    statement TEXT NOT NULL,
    definition_hash TEXT UNIQUE NOT NULL,
    parent_question_id TEXT REFERENCES question_versions(question_id),
    relationship TEXT CHECK(relationship IS NULL OR relationship='REVISION_OF'),
    source_commit_seq INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_occurrences (
    question_occurrence_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES question_versions(question_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    candidate_id TEXT NOT NULL,
    round_id TEXT NOT NULL,
    UNIQUE(project_id, candidate_id, round_id)
);
```

Use existing `normalize_statement`, `_uuid`, transaction, project-binding checks, and append-only trigger style. Do not create a second connection/store abstraction.

`KEEP` means create only a new occurrence pointing at the parent version. `REVISION_OF` means create one new immutable version in the parent's family, then its occurrence. Identical retries must be idempotent; conflicting rebinding of the same project/candidate/round must fail closed.

- [ ] **Step 4: Run focused ledger tests**

```powershell
rtk proxy python -m pytest tests\test_hypothesis_ledger.py -k "question_binding" -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research_loop/hypothesis_ledger.py tests/test_hypothesis_ledger.py
git commit -m "feat: add first-class research questions to ledger"
```

---

### Task 2: Put Question transition under L10b authority and bind continuations

**Files:**
- Modify: `src/research_loop/hypothesis_contracts.py`
- Modify: `src/research_loop/commands/continuation.py`
- Modify: `src/research_loop/commands/lifecycle.py`
- Modify: `templates/layers/L10b_final_decision.md`
- Test: `tests/test_hypothesis_ledger.py`
- Test: `tests/test_cross_round_e2e.py`

**Interfaces:**
- Native v2.1 L10b adds `question_transition`:

```json
{
  "action": "KEEP|REVISE|CLOSE",
  "reason": "non-empty",
  "statement": "required only for REVISE"
}
```

- If L10b `decision == "REVISE"`, `question_transition` is required and action must be `KEEP` or `REVISE` because a child round will be opened.
- `REVISE` requires a non-empty new statement.
- `KEEP` must not silently accept a changed statement.
- `CLOSE` is valid only when no continuation is being opened.
- Loop memory carries `question_id`, `question_family_id`, `question_transition` and the source L10b commit cursor/hash already available through the ledger snapshot.

- [ ] **Step 1: Write failing contract tests**

Add assertions that native v2.1 accepts:

```python
{"decision": "REVISE", ..., "question_transition": {
    "action": "KEEP", "reason": "same research question"
}}
```

and:

```python
{"decision": "REVISE", ..., "question_transition": {
    "action": "REVISE", "statement": "Refined question", "reason": "evidence narrowed scope"
}}
```

Reject `decision=REVISE` with missing transition, and reject `action=REVISE` without statement. Do not change v2.0 schemas.

- [ ] **Step 2: Run contract tests and verify failure**

```powershell
rtk proxy python -m pytest tests\test_hypothesis_ledger.py -k "question_transition" -q
```
Expected: FAIL on missing schema support.

- [ ] **Step 3: Add only the v2.1 L10b schema extension**

Build `_question_transition` once and add it to `_V21_NODE_SCHEMAS["L10b"]`. Use JSON-Schema conditional rules rather than a second Python validator. Do not create CLI-specific validation logic.

- [ ] **Step 4: Write failing continuation test**

Extend the native cross-round fixture so round 1 is bound to Q1, L10b emits `question_transition`, loop-memory preserves it, and child creation must produce either the same question ID (`KEEP`) or Q2 with `REVISION_OF Q1` (`REVISE`). A user-supplied continuation question that conflicts with the authorized transition must return error code 2 before the child candidate is committed.

- [ ] **Step 5: Run continuation test and verify failure**

```powershell
rtk proxy python -m pytest tests\test_cross_round_e2e.py -k "question" -q
```
Expected: FAIL because loop memory/candidate creation does not bind question identity.

- [ ] **Step 6: Implement initial and continuation binding at the existing candidate-creation seam**

In `cmd_new_candidate`/its current helper path:

```python
if initial_native:
    q = ledger.bind_question(project_dir, cand_id, round_id, contract["scientific_question"])
else:
    transition = mem["question_transition"]
    if transition["action"] == "KEEP":
        expected = mem["question_statement"]
        if normalize_statement(contract["scientific_question"]) != normalize_statement(expected):
            raise ValueError("continuation question changed without L10b REVISE authority")
        q = ledger.bind_question(..., parent_question_id=mem["question_id"], relationship="KEEP")
    elif transition["action"] == "REVISE":
        expected = transition["statement"]
        if normalize_statement(contract["scientific_question"]) != normalize_statement(expected):
            raise ValueError("continuation question does not match L10b-authorized revision")
        q = ledger.bind_question(..., parent_question_id=mem["question_id"], relationship="REVISION_OF",
                                 source_commit_seq=mem["hypothesis_ledger"]["as_of_commit_seq"])
```

Do not let L0 or CLI invent a revision. L0 remains a validation/binding boundary only.

In `_build_loop_memory`, read the source candidate's ledger `question_binding(...)`, copy its IDs/statement, and freeze the normalized L10b `question_transition`.

Update `templates/layers/L10b_final_decision.md` with one concise rule: if opening a revised round, explicitly decide whether the ResearchQuestion is KEEP or REVISE; never change it implicitly.

- [ ] **Step 7: Run focused contract + cross-round tests**

```powershell
rtk proxy python -m pytest tests\test_hypothesis_ledger.py tests\test_cross_round_e2e.py -k "question" -q
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/research_loop/hypothesis_contracts.py src/research_loop/commands/continuation.py src/research_loop/commands/lifecycle.py templates/layers/L10b_final_decision.md tests/test_hypothesis_ledger.py tests/test_cross_round_e2e.py
git commit -m "feat: bind question lifecycle to L10b continuation authority"
```

---

### Task 3: Deterministic Scientific State projection

**Files:**
- Create: `src/research_loop/scientific_state.py`
- Modify: `src/research_loop/hypothesis_ledger.py`
- Create: `tests/test_scientific_state.py`

**Interfaces:**
- `HypothesisLedger.graph(hypothesis_id, *, as_of=None) -> dict` remains the public graph seam.
- Graph nodes may include `question`, `hypothesis_version`, `analysis_run`, and `evidence`.
- Graph edges use only: `ADDRESSES`, `REVISION_OF`, `DERIVED_FROM`, `TESTS`, `PRODUCES`, `SUPPORTS`, `CONTRADICTS`, `INCONCLUSIVE_FOR`, `FALSIFIES`.
- Every edge contains `subject_id`, `predicate`, `object_id`, `source_event_id` or `source_delta_hash`, `source_node`, `commit_seq`, `round_id`, and `artifact_ref` when available.
- `src/research_loop/scientific_state.py` exports pure helpers `normalize_edges(graph_facts) -> list[dict]` and `build_evidence_profile(graph) -> dict`.

- [ ] **Step 1: Write failing projection tests from committed real ledger events**

Create a fixture that commits L1, L6, L7, L8, L8.5 and L9a against one hypothesis/question. Assert at minimum:

```python
predicates = {(e["predicate"], e["object_id"]) for e in graph["edges"]}
assert ("ADDRESSES", q1["question_id"]) in predicates
assert ("SUPPORTS", hid) in predicates
assert ("CONTRADICTS", hid) in predicates
assert ("INCONCLUSIVE_FOR", hid) in predicates
assert ("FALSIFIES", hid) in predicates
```

Also assert two calls at the same `as_of` return byte-equivalent canonical JSON and that no edge is inferred from unstructured reason prose.

- [ ] **Step 2: Run and verify failure**

```powershell
rtk proxy python -m pytest tests\test_scientific_state.py -q
```
Expected: FAIL because `graph()` still exposes no useful edges.

- [ ] **Step 3: Extend existing `HypothesisLedger.graph()` instead of adding a graph store**

Query only finalized emissions/events up to `as_of`. Derive:

- `ADDRESSES`: join hypothesis occurrence to question occurrence on project/candidate/round.
- `REVISION_OF`: from immutable hypothesis/question parent lineage already stored.
- `TESTS`/`PRODUCES`: from finalized L7 emission and its normalized L7 payload/evidence records; derive a stable projection-only run ID from the L7 `delta_hash`, e.g. `RUN:<delta_hash>`.
- `SUPPORTS`/`CONTRADICTS`/`INCONCLUSIVE_FOR`: only from explicit L8/L8.5 relation events/payloads.
- `FALSIFIES`: only from finalized L9a `FALSIFIED` event with evidence IDs.

Do not infer `DERIVED_FROM` unless the committed L10b proposal explicitly provides parent IDs/relationship.

Keep ordering deterministic: sort nodes by `(kind,id)` and edges by `(subject_id,predicate,object_id,commit_seq)`.

- [ ] **Step 4: Implement pure normalization helpers**

`scientific_state.py` must import no engine/provider/CLI module. It may use `hashlib`, `json`, and immutable dict/list transformations only.

- [ ] **Step 5: Run projection + existing ledger replay tests**

```powershell
rtk proxy python -m pytest tests\test_scientific_state.py tests\test_hypothesis_ledger.py -q
```
Expected: PASS; existing `verify(rebuild=True)` semantics remain intact.

- [ ] **Step 6: Commit**

```bash
git add src/research_loop/scientific_state.py src/research_loop/hypothesis_ledger.py tests/test_scientific_state.py tests/test_hypothesis_ledger.py
git commit -m "feat: project scientific relations from ledger facts"
```

---

### Task 4: EvidenceProfile and evidence-aware ranking

**Files:**
- Modify: `src/research_loop/scientific_state.py`
- Modify: `src/research_loop/hypothesis_ledger.py`
- Modify: `src/research_loop/ranking.py`
- Modify: `tests/test_scientific_state.py`
- Modify: `tests/test_ranking_cli.py`

**Interfaces:**
- `build_evidence_profile(graph) -> dict` returns:

```python
{
    "hypothesis_id": str,
    "statement": str,
    "falsification_criteria": list[str],
    "question_id": str | None,
    "supporting_evidence": list[dict],
    "contradicting_evidence": list[dict],
    "inconclusive_evidence": list[dict],
    "falsification_events": list[dict],
    "result_relations": list[dict],
    "unresolved_attacks": list[dict],
    "current_epistemic_status": str,
    "profile_hash": str,
}
```

- `HypothesisLedger.ranking_inputs(...)` adds `evidence_profile` and `evidence_profile_hash` to each candidate using the same authorized ledger cursor used for the ranking stage.
- `ranking.hypothesis_candidate(...)` accepts those fields.
- `pairwise_prompt_payload(...)` physically includes the two evidence profiles.
- Checkpoint candidate snapshot equality continues to reject resume when profile evidence/hash changed.

- [ ] **Step 1: Write failing EvidenceProfile test**

Assert exact classification of support/contradiction/inconclusive/falsification relations and deterministic hash. Full paper text/artifacts must not be copied into the profile.

- [ ] **Step 2: Run focused profile test and verify failure**

```powershell
rtk proxy python -m pytest tests\test_scientific_state.py -k "evidence_profile" -q
```
Expected: FAIL.

- [ ] **Step 3: Implement `build_evidence_profile` as a pure projection**

Use canonical JSON hashing. Preserve stable IDs, concise summaries/reasons, source node/commit/event/artifact refs. Sort every list deterministically before hashing.

- [ ] **Step 4: Write failing ranking tests**

In `tests/test_ranking_cli.py`, build C1 and C2 with different finalized evidence, then assert:

```python
snapshot = artifact["hypothesis_candidates"][0]
assert snapshot["evidence_profile_hash"] == snapshot["evidence_profile"]["profile_hash"]
raw = artifact["pairwise_judgments"][0]["raw_verdicts"][0]
assert raw["prompt_payload"]["positions"]["A"]["evidence_profile"]
assert raw["prompt_payload"]["positions"]["B"]["evidence_profile"]
```

Create a resume checkpoint, add/finalize new evidence for one hypothesis, rerun with `--resume`, and assert fail-closed before provider execution because candidate snapshots/profile hashes differ.

- [ ] **Step 5: Run ranking tests and verify failure**

```powershell
rtk proxy python -m pytest tests\test_ranking_cli.py -k "evidence_profile or resume" -q
```
Expected: FAIL before production changes.

- [ ] **Step 6: Thread EvidenceProfile through the existing ranking seam**

Change only candidate snapshot/prompt fields; do not alter `_choose_pair`, `_apply_elo`, A/B+B/A adjudication, scheduler, ranking result semantics, or formal decision comparison.

Update `pairwise_prompt_payload` instruction to require comparison of the supplied evidence state and explicitly treat contradictory/falsifying evidence as adverse evidence. Keep response schema unchanged (`A|B`, reason).

- [ ] **Step 7: Run ranking + projection tests**

```powershell
rtk proxy python -m pytest tests\test_scientific_state.py tests\test_ranking_cli.py -q
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/research_loop/scientific_state.py src/research_loop/hypothesis_ledger.py src/research_loop/ranking.py tests/test_scientific_state.py tests/test_ranking_cli.py
git commit -m "feat: rank hypotheses from evidence profiles"
```

---

### Task 5: Cross-round acceptance and full regression

**Files:**
- Modify: `tests/test_cross_round_e2e.py`
- Modify only if required by real failures: the canonical owner identified by the failing invariant; no patch-only compatibility helpers.

**Interfaces:**
- Acceptance path: `Q1 -> H1 -> contradictory evidence -> L10b REVISE + question transition -> child Q1 KEEP or Q2 REVISION_OF Q1 -> H2 ADDRESSES child question -> new support evidence -> ranking artifact contains distinct EvidenceProfiles`.

- [ ] **Step 1: Add one integrated native-v2.1 acceptance test**

The test must use public/production seams for project/candidate creation, committed deltas, loop-memory, continuation creation, ledger graph, and ranking command. Assert no formal candidate status changes after ranking.

- [ ] **Step 2: Run the acceptance test**

```powershell
rtk proxy python -m pytest tests\test_cross_round_e2e.py -k "scientific_state" -q
```
Expected: PASS after Tasks 1–4.

- [ ] **Step 3: Run affected contract/context/CLI tests**

```powershell
rtk proxy python -m pytest tests\test_hypothesis_ledger.py tests\test_scientific_state.py tests\test_ranking_cli.py tests\test_cross_round_e2e.py tests\test_l0_input_contract.py tests\test_l0_completion_contract.py -q
```
Expected: PASS.

- [ ] **Step 4: Run full regression**

```powershell
rtk proxy python -m pytest -q
```
Expected: all collected tests pass; report any skips exactly.

- [ ] **Step 5: Run repository integrity and CLI smoke checks**

```powershell
rtk git diff --check
python run_loop.py --help
python research_loop_v04.py --help
```
Expected: zero diff-check errors and both commands exit successfully.

- [ ] **Step 6: Architecture review before completion**

Verify from the final diff:

```text
- exactly one scientific fact store: HypothesisLedger SQLite
- no graph database/new KG framework
- no second Question/Evidence ledger
- no new DAG node or decision authority
- L10b is the only question-revision decision owner
- Scientific State and EvidenceProfile are rebuildable projections
- ranking remains advisory and its Elo/fairness machinery is unchanged
- no P1/P2 dependencies entered the branch
```

- [ ] **Step 7: Final commit**

```bash
git add tests/test_cross_round_e2e.py
git commit -m "test: cover P0 scientific state full loop"
```

If no file changed in this task because the integrated test was already committed with a preceding task, do not create an empty commit.
