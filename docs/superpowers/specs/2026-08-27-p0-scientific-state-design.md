# P0 Scientific State Integration Design

## Goal

Close the three P0 architectural gaps as one coherent scientific-state path:

1. make the scientific question a first-class, versioned research object;
2. expose deterministic Question–Hypothesis–Evidence–Result relations from the existing authoritative ledger;
3. rank hypotheses using actual evidence profiles instead of hypothesis text alone.

The purpose is functional: improve RLR's ability to run a falsification-oriented research loop and converge on the best-supported hypothesis or small hypothesis set. This is not a bug-fix exercise and must not add parallel authorities or generic infrastructure.

## Product invariant

RLR remains a structured, evidence-gated scientific loop:

```text
Question
  ↓
Hypotheses
  ↓ attack / triage
Methods
  ↓
Data analysis / experiment
  ↓
Results + literature verification
  ↓
Support / contradiction / falsification
  ↓
KEEP / REVISE / DROP
  ↓
next Question/Hypothesis round when scientifically justified
```

The HypothesisLedger remains the single authoritative persistence seam for scientific lifecycle facts. Graphs, evidence profiles, ranking views, and reports are rebuildable projections only.

## Non-goals

This P0 work MUST NOT:

- introduce Neo4j or another graph database;
- create a second QuestionLedger, EvidenceLedger, or ScientificState database;
- replace the existing DAG or add nodes;
- replace the existing ranking/Elo machinery;
- add MLflow, DVC, AiiDA, LangGraph, ORKG, OpenAlex, or other P1/P2 integrations;
- expand legacy v2.0 compatibility;
- refactor unrelated modules;
- duplicate ORKG/PROV ontology work beyond a deliberately small internal predicate vocabulary.

## Architecture

```text
L0 scientific question
        │
        ▼
Existing HypothesisLedger (ONLY fact authority)
        │
        ├── question/version facts
        ├── hypothesis/version facts
        ├── evidence/result/events
        └── lifecycle decisions
        │
        ▼
Scientific State projection (read-only, deterministic)
        │
        ├── typed relations
        └── EvidenceProfile(hypothesis_id)
        │
        ▼
Existing ranking.py
```

No projection may write scientific truth back into the ledger. All projection outputs must be reproducible from committed ledger emissions and their hash-bound artifacts.

---

## P0-1: First-class Research Question lifecycle

### Root cause

`scientific_question` is currently an L0 string. It has no stable identity or version lineage. Hypotheses can evolve across rounds, while the research question cannot be audited at the same semantic level.

### Minimal model

Add question facts to the existing HypothesisLedger store, following the same append-only design as hypothesis families/versions.

Required concepts:

- `question_family_id`: stable conceptual family;
- `question_id`: immutable version identity;
- `statement`: normalized question text;
- `definition_hash`: deterministic identity of the version;
- `created_at` / creation event provenance;
- occurrence binding to project/candidate/round;
- `REVISION_OF` lineage for revised questions.

Do not create a separate question status machine. A question version is active because a round is bound to it; terminality is already represented by the existing candidate/round decision flow.

### Decision authority

L0 must never decide whether the scientific question should change. That is a scientific decision.

For a continuing `REVISE` loop, the existing L10b decision authority explicitly declares one minimal `question_action` in the next-round proposal:

- `KEEP`: the child round keeps the current `question_id`;
- `REVISE`: the proposal supplies one new question statement, which becomes a new immutable version linked by `REVISION_OF`.

No `CLOSE` question status is needed: if there is no continuation, the existing terminal candidate/round decision already closes that research path.

### L0 contract behavior

Native L0 retains human-readable `scientific_question` for prompt/context compatibility and binds it to the authoritative `question_id`/question occurrence.

For an initial round:

- create or resolve the initial question version;
- bind the round to that exact version.

For a continuation:

- consume the committed parent L10b next-round proposal;
- `question_action=KEEP` reuses the exact parent question version;
- `question_action=REVISE` creates the declared new version with `REVISION_OF` lineage;
- changed question text without an authorized L10b `REVISE` fails closed.

The existing L0 contract remains the single L0 validator. Any schema change must be versioned once at that canonical owner; no CLI/context-specific validators.

---

## P0-2: Deterministic Scientific State relations

### Root cause

RLR already stores most relevant facts, but relations are distributed across node payloads and ledger events. The current graph projection does not expose a useful cross-entity evidence network.

### Design

Extend the existing ledger graph/projection path rather than creating a new graph store.

Use a deliberately small predicate vocabulary, initially limited to relations already supported by authoritative RLR events/artifacts:

- `ADDRESSES` — Hypothesis → Question
- `REVISION_OF` — Question → Question or Hypothesis → Hypothesis
- `DERIVED_FROM` — Hypothesis → Hypothesis/Evidence/Result when explicitly recorded
- `TESTS` — Run/analysis plan → Hypothesis when derivable from committed L6/L7 bindings
- `PRODUCES` — Run → Result
- `SUPPORTS` — Evidence/Result → Hypothesis
- `CONTRADICTS` — Evidence/Result → Hypothesis
- `INCONCLUSIVE_FOR` — Evidence/Result → Hypothesis
- `FALSIFIES` — verified falsification event → Hypothesis

No speculative edge may be inferred from prose. If an authoritative event does not encode the relation, the projection omits it.

### Edge representation

Each projected edge must retain enough provenance to trace it back to authority:

```text
subject_id
predicate
object_id
source_event_id
source_node
commit_seq
round_id
artifact_ref/hash when available
```

Edges are computed, not independently persisted as scientific truth. A cache is allowed only if it can be discarded and rebuilt without information loss.

### Scientific State projection

Provide a narrow read API that can answer at minimum:

- which Question a hypothesis addresses;
- parent/revised hypotheses/questions;
- supporting, contradicting, inconclusive, and falsifying evidence/results;
- which runs/results tested a hypothesis.

Do not build a generic query language.

---

## P0-3: Evidence-aware hypothesis ranking

### Root cause

The current pairwise ranking prompt asks for the “more scientifically supported” hypothesis while largely supplying hypothesis text and identity metadata. The ranking machinery is sound, but its scientific input is insufficient.

### Design

Keep the existing Elo scheduler, A/B+B/A fairness, checkpoint/replay, hashes, and advisory-only status.

Add a deterministic `EvidenceProfile` projection per hypothesis. The profile must be built only from authorized committed facts and should contain:

```text
hypothesis_id
statement
falsification_criteria
question_id
supporting_evidence[]
contradicting_evidence[]
inconclusive_evidence[]
falsification_events[]
result_relations[]
unresolved_attacks/confounders when already authoritative
current_epistemic_status
profile_hash
```

The profile contains concise scientific summaries plus stable IDs/provenance refs, not duplicate full papers or large artifacts.

### Ranking behavior

`hypothesis_candidate(...)` may carry an EvidenceProfile snapshot/hash. `pairwise_prompt_payload(...)` must present the evidence profiles used for that comparison.

The ranking artifact preserves the profile hash so a judgment can be replayed/audited against the exact evidence state used at ranking time.

Ranking remains advisory. It cannot change:

- L3 selection;
- L9a epistemic status;
- L10b formal decision;
- candidate workflow state.

---

## Data flow across one loop

```text
Q1 created/bound at L0
  ↓
H1/H2 created at L1 and linked ADDRESSES Q1
  ↓
L7 results linked to tested hypotheses
  ↓
L8/L8.5 relations produce SUPPORTS/CONTRADICTS/INCONCLUSIVE edges
  ↓
L9a may produce FALSIFIES + epistemic status
  ↓
Scientific State projection rebuilds current evidence network
  ↓
EvidenceProfile(H1), EvidenceProfile(H2)
  ↓
advisory ranking compares evidence, not naked text
  ↓
L10b formal decision remains authoritative
  ↓
if L10b REVISE:
  question_action KEEP   → child keeps Q1
  question_action REVISE → Q2 REVISION_OF Q1
  ↓
next-round hypotheses ADDRESSES the authorized question version
```

## Likely code ownership

Production changes should stay concentrated in existing canonical owners plus one narrow projection module if needed:

- `src/research_loop/l0_contract.py` — canonical native L0 question binding/schema validation;
- `src/research_loop/hypothesis_ledger.py` — authoritative question facts and event-to-projection access;
- `src/research_loop/hypothesis_contracts.py` — L10b next-round question action and only other explicit relation fields required by the existing delta model;
- `src/research_loop/ranking.py` — consume EvidenceProfile without replacing scheduler logic;
- optionally create `src/research_loop/scientific_state.py` — pure/read-only transformation from ledger facts to relations and EvidenceProfile.

Do not put projection logic into CLI, provider, or context modules.

## Compatibility policy

This work targets native v2.1/new runs. Existing v2.0 compatibility code must not be enlarged. Historical data may remain readable under existing rules, but no implicit migration of old question strings into new authoritative question objects is required for P0.

## Testing strategy

TDD is required. Tests must prove behavior at the actual authority boundaries.

### P0-1 tests

- initial native round creates/binds exactly one question version;
- L10b `question_action=KEEP` continuation preserves question identity;
- L10b `question_action=REVISE` creates a new version with explicit `REVISION_OF` lineage;
- changed question text without explicit L10b authorization fails closed;
- L0 cannot independently choose a question revision;
- append-only question facts cannot be modified/deleted.

### P0-2 tests

- committed L1/L7/L8/L8.5/L9a/L10b facts deterministically project expected edges;
- unsupported/speculative edges are not invented;
- graph rebuild from the same ledger produces identical output/hash;
- projection contains provenance back to commit/event/artifact.

### P0-3 tests

- EvidenceProfile contains supporting/contradicting/inconclusive/falsification facts from the ledger;
- pairwise prompt physically contains the EvidenceProfile for both candidates;
- prompt/profile hashes change when authorized evidence changes;
- checkpoint replay rejects mismatched evidence-profile snapshots;
- ranking remains advisory and cannot alter formal scientific state.

### Cross-round acceptance test

One native end-to-end fixture should demonstrate:

```text
Q1 → H1
H1 receives contradictory evidence
L10b REVISE + question_action=REVISE
Q2 REVISION_OF Q1
H2 ADDRESSES Q2
new evidence supports H2
ranking compares H1/H2 using their evidence profiles
```

This test proves software semantics only, not scientific truth.

## Success criteria

P0 is complete only when:

1. every new native round has an authoritative question identity;
2. question revisions are explicit, L10b-authorized, and auditable across rounds;
3. the existing ledger can deterministically project the core scientific relations without a second source of truth;
4. every ranked hypothesis is accompanied by an exact evidence profile/hash;
5. pairwise ranking judges evidence rather than hypothesis prose alone;
6. no DAG authority changes and no P1/P2 dependency is introduced;
7. targeted tests, cross-round acceptance test, full regression suite, `git diff --check`, and public CLI smoke tests pass in the implementation workspace.
