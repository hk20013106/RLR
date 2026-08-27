# P0 Scientific State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three P0 gaps as one coherent path: first-class ResearchQuestion lifecycle, deterministic scientific-state relations, and evidence-aware hypothesis ranking.

**Architecture:** `HypothesisLedger` remains the only scientific fact authority. Question facts live in the same SQLite store; Scientific State and `EvidenceProfile` are deterministic read-only projections; the existing ranking scheduler consumes those profiles without changing Elo, DAG authority, or formal decisions.

**Tech Stack:** Python stdlib, SQLite, existing JSON Schema/jsonschema contracts, existing RLR CLI/runtime, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-p0-scientific-state-design.md`

## Global Constraints

- Target native v2.1/new runs only; do not enlarge v2.0 compatibility.
- `HypothesisLedger` is the single scientific persistence authority.
- Graphs, EvidenceProfiles, ranking artifacts, and reports are rebuildable projections only.
- Do not add Neo4j, ORKG, OpenAlex, MLflow, DVC, AiiDA, LangGraph, or another scientific-state database.
- Do not change the DAG or create a new decision authority.
- L10b owns Question revision decisions; intake/L0 may only bind or verify an already-authorized identity.
- Preserve ranking scheduler, A/B+B/A fairness, checkpoint/replay, and advisory-only semantics.
- Use TDD and the smallest change at each canonical owner.
- No unrelated refactor, dependency upgrade, compatibility patch stack, or legacy migration.

---

## File Structure

- Modify `src/research_loop/hypothesis_ledger.py`: Question storage/binding; graph query support; ranking input enrichment.
- Modify `src/research_loop/hypothesis_contracts.py`: native-v2.1 L10b `question_transition` contract.
- Modify `src/research_loop/commands/lifecycle.py`: native candidate Question binding.
- Modify `src/research_loop/commands/continuation.py`: freeze Question identity/transition into loop memory.
- Modify `templates/layers/L10b_final_decision.md`: concise Question-transition instruction.
- Create `src/research_loop/scientific_state.py`: pure projection and EvidenceProfile construction.
- Modify `src/research_loop/ranking.py`: carry profile snapshots/hashes into prompts/checkpoints.
- Modify tests in `tests/test_hypothesis_ledger.py`, `tests/test_cross_round_e2e.py`, `tests/test_ranking_cli.py`.
- Create `tests/test_scientific_state.py`.

---

### Task 1: First-class ResearchQuestion facts in the existing ledger

**Files:**
- Modify: `src/research_loop/hypothesis_ledger.py`
- Modify: `tests/test_hypothesis_ledger.py`

**Interfaces:**
- `HypothesisLedger.bind_question(project_dir, candidate_id, round_id, statement, *, parent_question_id=None, relationship=None, source_commit_seq=None) -> dict`
- `HypothesisLedger.question_binding(project_dir, candidate_id, round_id) -> dict`
- Initial: no parent, no relationship.
- KEEP: parent supplied, `relationship=None`, statement must equal parent after normalization; create only a new occurrence pointing to the same `question_id`.
- REVISE: parent supplied, `relationship="REVISION_OF"`, statement must differ; create a new version in the parent's family.

- [ ] **Step 1: Write failing tests for initial, KEEP, REVISE, idempotency, append-only behavior**

```python
def test_question_binding_is_versioned_and_append_only(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "shared.sqlite")
    ledger.bind_project(project, "P1")

    q1 = ledger.bind_question(project, "C1", "1", "Does A alter B?")
    kept = ledger.bind_question(
        project, "C2", "2", "Does A alter B?",
        parent_question_id=q1["question_id"],
    )
    revised = ledger.bind_question(
        project, "C3", "3", "Under condition X, does A alter B?",
        parent_question_id=q1["question_id"],
        relationship="REVISION_OF",
        source_commit_seq=7,
    )

    assert kept["question_id"] == q1["question_id"]
    assert revised["question_id"] != q1["question_id"]
    assert revised["question_family_id"] == q1["question_family_id"]
    assert revised["parent_question_id"] == q1["question_id"]
    assert revised["relationship"] == "REVISION_OF"
    assert ledger.question_binding(project, "C3", "3") == revised
```

Add mutation tests proving UPDATE/DELETE of Question family/version/occurrence rows raises `sqlite3.IntegrityError`. Add a conflicting rebind test proving one project/candidate/round cannot point to two Question versions.

- [ ] **Step 2: Run focused tests and confirm they fail**

```powershell
rtk proxy python -m pytest tests\test_hypothesis_ledger.py -k "question_binding or question_append" -q
```

Expected: FAIL because Question tables/APIs do not exist.

- [ ] **Step 3: Implement the minimum tables in the existing store**

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

Use existing `normalize_statement`, `_uuid`, project-binding checks, transaction style, and append-only triggers. Derive initial family identity from normalized Question text. Derive `definition_hash` from `{question_family_id, normalized_statement}` so retries are deterministic within a family.

- [ ] **Step 4: Add a native-v2.1 L1 integrity test**

For a project bound with profile `v2.1-catalog-1`, committing L1 without a Question occurrence for that candidate/round must raise `LedgerError`. A v2.0 historical fixture must retain its existing behavior; do not migrate it.

- [ ] **Step 5: Implement the native-v2.1 L1 precondition in `commit_delta`**

Before normalizing a native-v2.1 L1 submission, resolve exactly one Question occurrence for `(project_id, candidate_id, round_id)`. Fail closed if absent or ambiguous. Do not add a new validator module.

- [ ] **Step 6: Run focused ledger tests**

```powershell
rtk proxy python -m pytest tests\test_hypothesis_ledger.py -k "question or native" -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/research_loop/hypothesis_ledger.py tests/test_hypothesis_ledger.py
git commit -m "feat: add first-class research questions to ledger"
```

---

### Task 2: Bind Question lifecycle to L10b continuation authority

**Files:**
- Modify: `src/research_loop/hypothesis_contracts.py`
- Modify: `src/research_loop/commands/lifecycle.py`
- Modify: `src/research_loop/commands/continuation.py`
- Modify: `templates/layers/L10b_final_decision.md`
- Modify: `tests/test_hypothesis_ledger.py`
- Modify: `tests/test_cross_round_e2e.py`

**Interfaces:**
- Native-v2.1 L10b adds:

```json
{
  "question_transition": {
    "action": "KEEP",
    "reason": "The original research question remains the correct scope."
  }
}
```

or:

```json
{
  "question_transition": {
    "action": "REVISE",
    "statement": "Under condition X, does A alter B?",
    "reason": "The completed round narrowed the valid scope."
  }
}
```

`CLOSE` is permitted only for terminal decisions that do not open a child round. If `decision == "REVISE"`, the transition is required and its action is `KEEP` or `REVISE`.

- [ ] **Step 1: Write failing native-v2.1 L10b schema tests**

Use a complete valid native L10b payload. Verify: `decision=REVISE` + KEEP passes; `decision=REVISE` + REVISE with statement passes; missing transition fails; REVISE without statement fails; `decision=REVISE` + CLOSE fails. Verify v2.0 schema is unchanged.

- [ ] **Step 2: Run schema tests and confirm failure**

```powershell
rtk proxy python -m pytest tests\test_hypothesis_ledger.py -k "question_transition" -q
```

Expected: FAIL because v2.1 has no Question transition field/rules.

- [ ] **Step 3: Extend only `_V21_NODE_SCHEMAS["L10b"]`**

Create one `_question_transition` schema object and JSON-Schema conditionals. Do not add a CLI-side duplicate validator. Do not modify the v2.0 schema registry.

- [ ] **Step 4: Write failing native candidate/continuation tests**

The initial `new-candidate` path must bind the contract's `scientific_question` in the activated ledger before a native L1 can be committed. For continuation:

```python
q1 = ledger.question_binding(project, parent_candidate, "1")
transition = memory["question_transition"]
assert memory["question_id"] == q1["question_id"]
assert transition["action"] in {"KEEP", "REVISE"}
```

KEEP must create a child occurrence with Q1. REVISE must create Q2 with `REVISION_OF Q1`. Supplying a child question that differs from the L10b-authorized text must fail before the child candidate is finalized.

- [ ] **Step 5: Run continuation tests and confirm failure**

```powershell
rtk proxy python -m pytest tests\test_cross_round_e2e.py -k "question" -q
```

Expected: FAIL because candidate creation and loop memory do not yet carry Question identity.

- [ ] **Step 6: Implement initial binding in `cmd_new_candidate`**

After strict native intake has produced the final `scientific_question` and deterministic candidate/round IDs, call:

```python
question_binding = ledger.bind_question(
    project_dir,
    cand_id,
    str(contract["round_id"]),
    contract["scientific_question"],
)
```

Do this only on the activated native path. Preserve deterministic retry semantics and fail candidate creation if the ledger binding conflicts.

- [ ] **Step 7: Freeze Question authority in `_build_loop_memory`**

Load the source round's Question via `ledger.question_binding(project_dir, cand_id, source_round_id)` and add these fields to loop memory:

```python
memory["question_id"] = source_question["question_id"]
memory["question_family_id"] = source_question["question_family_id"]
memory["question_statement"] = source_question["statement"]
memory["question_transition"] = l10["question_transition"]
```

The transition comes only from the finalized L10b delta; do not infer it by comparing strings.

- [ ] **Step 8: Implement continuation binding in `cmd_new_candidate`**

For KEEP, require normalized child `scientific_question` to equal `memory["question_statement"]`, then call `bind_question` with the parent ID and no relationship. For REVISE, require normalized child text to equal `memory["question_transition"]["statement"]`, then call `bind_question` with `relationship="REVISION_OF"` and the parent ID. Use the frozen source ledger cursor as `source_commit_seq`.

- [ ] **Step 9: Update the L10b layer instruction**

Add one rule to `templates/layers/L10b_final_decision.md`: when a continuation is proposed, explicitly choose KEEP or REVISE for the ResearchQuestion; never silently rewrite the Question.

- [ ] **Step 10: Run focused tests**

```powershell
rtk proxy python -m pytest tests\test_hypothesis_ledger.py tests\test_cross_round_e2e.py -k "question" -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add src/research_loop/hypothesis_contracts.py src/research_loop/commands/lifecycle.py src/research_loop/commands/continuation.py templates/layers/L10b_final_decision.md tests/test_hypothesis_ledger.py tests/test_cross_round_e2e.py
git commit -m "feat: bind question lifecycle to L10b authority"
```

---

### Task 3: Deterministic Scientific State projection

**Files:**
- Create: `src/research_loop/scientific_state.py`
- Modify: `src/research_loop/hypothesis_ledger.py`
- Create: `tests/test_scientific_state.py`

**Interfaces:**
- Keep `HypothesisLedger.graph(hypothesis_id, *, as_of=None) -> dict` as the public graph seam.
- Allowed predicates: `ADDRESSES`, `REVISION_OF`, `DERIVED_FROM`, `TESTS`, `PRODUCES`, `SUPPORTS`, `CONTRADICTS`, `INCONCLUSIVE_FOR`, `FALSIFIES`.
- Every projected edge carries provenance: `subject_id`, `predicate`, `object_id`, `source_event_id` or `source_delta_hash`, `source_node`, `commit_seq`, `round_id`, and artifact reference when one exists.
- `scientific_state.py` is pure/read-only; it may not write ledger rows or import engine/provider/CLI modules.

- [ ] **Step 1: Write a failing projection fixture using finalized L1/L6/L7/L8/L8.5/L9a data**

The fixture binds Q1, commits H1, a tested result, explicit support/contradiction/inconclusive relations, and a falsification event. Assert:

```python
edges = ledger.graph(hid)["edges"]
assert any(e["predicate"] == "ADDRESSES" and e["object_id"] == q1["question_id"] for e in edges)
assert any(e["predicate"] == "SUPPORTS" and e["object_id"] == hid for e in edges)
assert any(e["predicate"] == "CONTRADICTS" and e["object_id"] == hid for e in edges)
assert any(e["predicate"] == "INCONCLUSIVE_FOR" and e["object_id"] == hid for e in edges)
assert any(e["predicate"] == "FALSIFIES" and e["object_id"] == hid for e in edges)
```

Also assert the same `as_of` cursor yields identical `canonical_json(graph)` and that prose alone never creates an edge.

- [ ] **Step 2: Run projection test and confirm failure**

```powershell
rtk proxy python -m pytest tests\test_scientific_state.py -q
```

Expected: FAIL because current `graph()` returns no useful edges.

- [ ] **Step 3: Extend the existing graph projection, not persistence**

Use only finalized emissions/events up to `as_of`.

- `ADDRESSES`: join hypothesis and Question occurrences by project/candidate/round.
- Question `REVISION_OF`: from immutable Question version lineage.
- Hypothesis `REVISION_OF`/`DERIVED_FROM`: only from explicit committed L10b successor metadata.
- `TESTS` and `PRODUCES`: derive a projection-only run node `RUN:<L7 delta_hash>` from a finalized L7 emission and its explicit `hypothesis_ids`/result evidence IDs.
- `SUPPORTS`, `CONTRADICTS`, `INCONCLUSIVE_FOR`: only explicit L8/L8.5 relations.
- `FALSIFIES`: only finalized L9a FALSIFIED events with referenced evidence.

Sort nodes by `(kind, id)` and edges by `(subject_id, predicate, object_id, commit_seq)`.

- [ ] **Step 4: Create pure helpers in `scientific_state.py`**

Implement `normalize_edges(edges: list[dict]) -> list[dict]` to canonicalize ordering and reject unknown predicates. Do not create a graph query language or cache.

- [ ] **Step 5: Run projection plus ledger replay tests**

```powershell
rtk proxy python -m pytest tests\test_scientific_state.py tests\test_hypothesis_ledger.py -q
```

Expected: PASS and existing `verify(rebuild=True)` remains green.

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
- `build_evidence_profile(graph: dict) -> dict`
- Profile fields: `hypothesis_id`, `statement`, `falsification_criteria`, `question_id`, `supporting_evidence`, `contradicting_evidence`, `inconclusive_evidence`, `falsification_events`, `result_relations`, `unresolved_attacks`, `current_epistemic_status`, `profile_hash`.
- `HypothesisLedger.ranking_inputs(...)` attaches the profile and hash for each ranked hypothesis using the same authorized ledger state/cursor used by that ranking call.
- `ranking.hypothesis_candidate(...)` and `pairwise_prompt_payload(...)` preserve the profile snapshot/hash.

- [ ] **Step 1: Write a failing EvidenceProfile test**

Assert support, contradiction, inconclusive, falsification, Question identity, status, and deterministic `profile_hash`. The profile may contain concise summaries/reasons and stable provenance IDs; it must not duplicate full papers or large artifacts.

- [ ] **Step 2: Run profile test and confirm failure**

```powershell
rtk proxy python -m pytest tests\test_scientific_state.py -k "evidence_profile" -q
```

Expected: FAIL because no profile builder exists.

- [ ] **Step 3: Implement `build_evidence_profile` as a pure projection**

Canonicalize and sort every list before hashing. Build `profile_hash` from canonical JSON of all profile fields except `profile_hash` itself.

- [ ] **Step 4: Write failing ranking integration tests**

Build two finalized hypotheses with different evidence. After `ranking-shadow`, assert each stored candidate has `evidence_profile` and matching `evidence_profile_hash`, and each raw pairwise prompt contains both profiles.

Create a checkpoint, then finalize additional evidence for one hypothesis. Resume with the stale checkpoint and assert fail-closed before provider execution because the candidate snapshot/profile hash changed.

- [ ] **Step 5: Run ranking tests and confirm failure**

```powershell
rtk proxy python -m pytest tests\test_ranking_cli.py -k "evidence_profile or resume" -q
```

Expected: FAIL before ranking integration is implemented.

- [ ] **Step 6: Enrich `HypothesisLedger.ranking_inputs`**

For every candidate/hypothesis, call the existing graph seam at the ranking-visible ledger state, build one EvidenceProfile, and return both profile and hash. Do not create a second ranking data store.

- [ ] **Step 7: Thread profiles through existing `ranking.py` snapshots/prompts**

Add `evidence_profile` and `evidence_profile_hash` to candidate snapshots. `pairwise_prompt_payload` must present the profiles and instruct the judge to weigh supporting versus contradictory/falsifying evidence. Keep the response schema `A|B` plus concise reason.

Do not modify `_choose_pair`, `_apply_elo`, A/B+B/A fairness, scheduler state, formal decision comparison, or advisory-only behavior.

- [ ] **Step 8: Run projection and ranking tests**

```powershell
rtk proxy python -m pytest tests\test_scientific_state.py tests\test_ranking_cli.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/research_loop/scientific_state.py src/research_loop/hypothesis_ledger.py src/research_loop/ranking.py tests/test_scientific_state.py tests/test_ranking_cli.py
git commit -m "feat: rank hypotheses from evidence profiles"
```

---

### Task 5: Native cross-round acceptance and regression qualification

**Files:**
- Modify: `tests/test_cross_round_e2e.py`

**Interfaces:**
- Acceptance flow: `Q1 -> H1 -> contradictory evidence -> L10b REVISE -> Question KEEP or Q2 REVISION_OF Q1 -> H2 ADDRESSES child Question -> new evidence -> ranking compares EvidenceProfiles`.

- [ ] **Step 1: Add one end-to-end native-v2.1 acceptance test**

Use production/public seams for project/candidate creation, finalized deltas, loop-memory, continuation creation, ledger graph, and ranking command. Verify ranking does not mutate formal candidate status or epistemic status.

- [ ] **Step 2: Run the acceptance test**

```powershell
rtk proxy python -m pytest tests\test_cross_round_e2e.py -k "scientific_state" -q
```

Expected: PASS after Tasks 1–4.

- [ ] **Step 3: Run the affected regression set**

```powershell
rtk proxy python -m pytest tests\test_hypothesis_ledger.py tests\test_scientific_state.py tests\test_ranking_cli.py tests\test_cross_round_e2e.py tests\test_l0_input_contract.py tests\test_l0_completion_contract.py -q
```

Expected: PASS.

- [ ] **Step 4: Run the full suite**

```powershell
rtk proxy python -m pytest -q
```

Expected: all collected tests pass; report skipped tests exactly.

- [ ] **Step 5: Run repository/CLI integrity checks**

```powershell
rtk git diff --check
python run_loop.py --help
python research_loop_v04.py --help
```

Expected: zero diff-check errors and successful CLI help exits.

- [ ] **Step 6: Review the final diff against architecture invariants**

The final diff must show exactly one scientific fact store (`HypothesisLedger` SQLite), no graph database, no second Question/Evidence ledger, no new DAG node, L10b as the only Question-revision decision owner, rebuildable Scientific State/EvidenceProfile projections, unchanged ranking authority, and no P1/P2 dependencies.

- [ ] **Step 7: Commit the acceptance test if it is not already part of a previous task commit**

```bash
git add tests/test_cross_round_e2e.py
git commit -m "test: cover P0 scientific state full loop"
```

If `git diff --quiet -- tests/test_cross_round_e2e.py` reports no changes, skip this commit rather than creating an empty commit.
