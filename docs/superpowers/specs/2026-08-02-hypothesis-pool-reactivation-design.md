# Long-Lived Hypothesis Pool and Reactivation Design

## Goal

Extend the append-only hypothesis ledger into a usable long-lived hypothesis pool. Historical hypotheses must remain searchable after attack, rejection, contradiction, or insufficient evidence. A later round may reactivate an unchanged hypothesis, revise its test definition, or derive a related hypothesis without rewriting any prior occurrence or event.

The central invariant is:

> Rejecting an occurrence does not delete or permanently reject the hypothesis version.

## Scope

This change covers:

- a rebuildable hypothesis-pool projection;
- historical hypothesis recall before L1;
- L1 provenance for new, reactivated, revised, and derived hypotheses;
- creation of a new occurrence when an unchanged historical hypothesis is reused;
- L2/L3 review of unresolved historical objections;
- strict reopening rules for formally falsified hypotheses;
- pool query, reporting, and export interfaces;
- tests and user documentation.

This change does not replace the SQLite ledger, mutate old events, delete historical hypotheses, or introduce embedding search as a required dependency.

## Existing model retained

The current authoritative ledger remains unchanged in principle:

- `families` represent stable hypothesis families;
- `versions` represent exact combinations of statement, operationalization, and falsification criteria;
- `occurrences` represent use of a version in one project, candidate, and round;
- `events` contain append-only lifecycle facts;
- workflow and epistemic projections are rebuildable current-state views.

The pool and recall layers are projections over those facts, not replacement sources of truth.

## Identity and reuse rules

### Reactivation

Use `REACTIVATE` when statement, operationalization, and falsification criteria are unchanged.

- Reuse the existing `hypothesis_id` and family ID.
- Create a new occurrence for the current project/candidate/round.
- Record `REPROPOSED` with the source hypothesis, source occurrence, and reactivation basis.
- Set only the new occurrence to `PROPOSED`.
- Preserve all historical rejected occurrences and attacks.

### Revision

Use `REVISE` when the core statement is unchanged but operationalization or falsification criteria change.

- Create a new hypothesis version.
- Retain the parent family ID.
- Record a `REVISED` lineage event linking the new version to the source version.
- Create a current-round occurrence for the new version.

### Derivation

Use `DERIVE` when the scientific statement changes materially.

- Create a new family and version.
- Record `DERIVED` with one or more parent hypothesis IDs.
- Create a current-round occurrence for the derived version.

### New hypothesis

Use `NEW` when no historical source is intentionally reused.

All four origins count toward the L1 limit of 1–12 hypotheses and toward conditional L2 routing.

## Workflow and epistemic state

Workflow status remains occurrence-specific. A historical `REJECTED` status means only that the occurrence did not advance in that round.

Epistemic status remains version-specific:

- `UNASSESSED`
- `INSUFFICIENT_EVIDENCE`
- `PROVISIONALLY_SUPPORTED`
- `CONTRADICTED`
- `FALSIFIED`

Reactivation eligibility is computed, not stored as an authoritative mutable state:

- `ELIGIBLE`: prior attacks/rejections do not impose an unresolved evidence condition;
- `ELIGIBLE_WITH_BASIS`: reactivation requires a stated changed condition or new evidence;
- `REQUIRES_EXPLICIT_OVERRIDE`: archived or substantially contradicted hypotheses require an explicit reviewed reason;
- `BLOCKED_FALSIFIED`: ordinary L1 reactivation is forbidden until formal reopening succeeds.

## Hypothesis-pool projection

Add `src/research_loop/hypothesis_pool.py` as a pure read/projection module. It derives one pool record per hypothesis version from finalized ledger facts.

Each record includes:

- hypothesis and family IDs;
- statement, operationalization, and falsification criteria;
- epistemic status;
- occurrence count and occurrence history;
- attack, confounder, diagnostic-test, and verdict counts;
- rejection count and last rejection details;
- latest occurrence and workflow status;
- unresolved historical blockers;
- related version and lineage IDs;
- reactivation eligibility and requirements;
- first-seen and last-seen metadata.

The projection must be fully rebuildable. Deleting a cached projection must not delete information or change its recomputed content at the same finalized commit cursor.

## Historical recall before L1

Introduce a pre-L1 recall operation without adding a new formal DAG node in the first implementation.

Flow:

```text
current question and candidate context
→ deterministic pool search
→ status and blocker filtering
→ immutable recall artifact
→ authorized, node-specific context injection
```

Recall artifacts are stored under:

```text
08_Audit/hypothesis_recall/<candidate_id>_round_<round_id>.json
```

Each artifact binds:

- store and project IDs;
- candidate and round IDs;
- finalized `as_of_commit_seq`;
- normalized query terms and filters;
- returned hypothesis/version/occurrence IDs;
- pool summaries and blocker event IDs;
- generation time and artifact hash.

A recall artifact is immutable and cursor-bound. Events committed later must not appear retroactively in it.

## Recall implementation

The first version uses deterministic, auditable retrieval:

1. exact hypothesis ID;
2. same family ID;
3. SQLite FTS over statement and operationalization;
4. normalized keyword matching over study entities, variables, and method terms;
5. workflow, epistemic, and eligibility filters.

Semantic embeddings may be added later as an optional recall channel. They must not be required for correctness and must not silently merge identities.

## Node-specific visibility

### L1

L1 receives a concise recall summary:

- historical statement and version ID;
- latest disposition and epistemic status;
- blocker codes and missing conditions;
- reactivation eligibility;
- source occurrence ID.

L1 does not receive all historical attack prose by default, reducing anchoring while still preventing accidental duplication.

### L2

When five or more hypotheses cause L2 to run, L2 receives:

- full historical attacks, confounders, diagnostic tests, and verdicts;
- evidence/condition changes claimed in the current reactivation basis;
- unresolved blocker event IDs.

L2 must assess whether the current basis resolves each material historical blocker.

### L3

L3 receives the complete recall and review record. It decides whether the item is:

- a valid reactivation of the same version;
- a revision requiring a new version;
- a derived hypothesis;
- or still blocked and therefore rejected.

When L2 is skipped for 1–4 hypotheses, L3 must perform the historical-blocker assessment directly. Conditional L2 skipping never skips reactivation validation.

## L1 contract extension

Each L1 hypothesis adds:

```json
{
  "origin": "NEW | REACTIVATE | REVISE | DERIVE",
  "source_hypothesis_id": "H:...",
  "source_occurrence_id": "HO:...",
  "parent_hypothesis_ids": ["H:..."],
  "reactivation_basis": {
    "basis_type": "NEW_EVIDENCE | NEW_DATA | NEW_METHOD | CHANGED_SCOPE | CHANGED_FEASIBILITY | USER_RECONSIDERATION",
    "summary": "...",
    "evidence_ids": ["E:..."],
    "artifact_refs": [],
    "changed_conditions": []
  }
}
```

Rules:

- `NEW` does not carry source IDs.
- `REACTIVATE` requires source hypothesis and occurrence IDs plus a basis when prior state is rejected, archived, contradicted, or evidence-limited.
- `REVISE` requires one source hypothesis ID and an explicit change summary.
- `DERIVE` requires one or more parent hypothesis IDs.
- engine-owned IDs remain assigned during persistence.

## Reactivation validation

Before committing L1:

1. Resolve all source IDs from finalized ledger facts.
2. Confirm the recalled source existed at the recall cursor.
3. Confirm candidate/round does not already contain the same occurrence.
4. For `REACTIVATE`, recompute the definition hash and require exact identity with the source version.
5. For `REVISE`, require the same normalized statement but a changed operationalization or falsification definition.
6. For `DERIVE`, require a materially different statement and valid parent IDs.
7. Validate eligibility and required basis fields.
8. Reject ordinary reactivation of `FALSIFIED` versions.

A `USER_RECONSIDERATION` basis is allowed for workflow rejection but does not assert that historical scientific objections were resolved.

## L3 reactivation assessment

Reactivated, revised, and derived hypotheses add:

```json
{
  "reactivation_assessment": {
    "source_hypothesis_id": "H:...",
    "prior_blocking_event_ids": ["HE:..."],
    "basis_verdict": "RESOLVED | PARTIALLY_RESOLVED | UNRESOLVED | NOT_APPLICABLE",
    "reason": "...",
    "remaining_risks": []
  }
}
```

Constraints:

- `UNRESOLVED` cannot be `SELECTED`.
- `PARTIALLY_RESOLVED` may be selected only with explicit downstream QC or stop-rule obligations.
- falsified hypotheses without a valid reopening event cannot be selected.
- the assessment produces `REACTIVATION_REVIEWED`; it never deletes prior attacks.

## Formal reopening of falsified hypotheses

`FALSIFIED` is not equivalent to workflow rejection. Add a separate `hypothesis-reopen` operation.

It requires:

- source hypothesis ID;
- exact prior `FALSIFIED` event ID;
- verified evidence committed after the prior falsification;
- explanation of why the prior criterion/evidence interpretation no longer holds;
- `supersedes_event_id` binding.

Outcomes:

- `REOPENED`: epistemic state changes through an append-only superseding event;
- `REOPEN_REJECTED`: request and reason remain in history, state remains falsified.

Only a successfully reopened version becomes eligible for later L1 reactivation.

## Event additions

Add:

- `REPROPOSED`
- `REACTIVATION_REVIEWED`
- `REOPEN_REQUESTED`
- `REOPENED`
- `REOPEN_REJECTED`

Existing `PROPOSED`, `ATTACKED`, `SELECTED`, `REJECTED`, `REVISED`, `DERIVED`, `FALSIFIED`, `ARCHIVED`, and `SUPERSEDED` events retain their meanings.

`REPROPOSED` is occurrence reuse. `REOPENED` is an epistemic reversal of formal falsification. They must never be treated as synonyms.

## Interfaces

Add stable CLI surfaces:

```text
hypothesis-pool list
hypothesis-pool search
hypothesis-pool show
hypothesis-pool history
hypothesis-pool eligible
hypothesis-recall
hypothesis-reopen
hypothesis-export
```

Pool filters include epistemic status, workflow status, eligibility, attack/rejection presence, project, candidate, round, family, and time range.

`show` presents definition, occurrences, attacks, verdicts, evidence relations, workflow and epistemic history, lineage, eligibility, and required reactivation conditions.

## Export and long-term preservation

SQLite remains authoritative. Add read-only, cursor-bound exports under:

```text
08_Audit/hypothesis_exports/
```

Supported forms:

- JSONL families, versions, occurrences, and events;
- verified SQLite snapshot;
- Markdown pool report;
- manifest with schema version, cursor, record counts, file hashes, and generation time.

Exports cannot overwrite or import back into the authoritative ledger in this scope.

## Error handling

Fail closed for:

- unknown, unfinalized, or post-cursor source IDs;
- recall artifact/hash mismatch;
- exact-definition mismatch for `REACTIVATE`;
- unchanged definition submitted as `REVISE`;
- duplicate current-round occurrence;
- missing required basis or blocker assessment;
- selecting an unresolved reactivation;
- falsified version without successful reopening;
- reopening without new verified post-falsification evidence;
- projection/export mismatch at a fixed cursor.

Diagnostics identify the hypothesis, source event, eligibility rule, and required corrective action.

## Compatibility

- Existing ledger facts and historical delta files are not rewritten.
- Existing `NEW` L1 submissions remain readable; native new submissions may default omitted `origin` to `NEW` during a documented transition period.
- Existing occurrence and version IDs retain their meaning.
- L1 remains 1–12 hypotheses.
- 1–4 hypotheses still skip L2; 5–12 still run L2.
- Legacy profiles remain read-only and are not retroactively assigned recall or reactivation events.
- Pool projection and recall operate only over finalized emissions.

## Expected implementation boundaries

New focused modules:

- `src/research_loop/hypothesis_pool.py`
- `src/research_loop/hypothesis_recall.py`
- optional `src/research_loop/hypothesis_reopening.py` if reopening logic would otherwise enlarge the ledger module excessively.

Likely modifications:

- `hypothesis_contracts.py`
- `hypothesis_ledger.py`
- `constraint_validation.py`
- `context.py`
- `topology.py`
- CLI and ledger command modules;
- L1/L2/L3 templates;
- documentation and tests.

No unrelated ledger refactor is included.

## Test strategy

Required tests include:

1. rejected hypotheses remain searchable;
2. unchanged reactivation reuses hypothesis ID and creates a new occurrence;
3. old rejected occurrence remains rejected;
4. revision creates a new version in the same family;
5. derivation creates a linked new family;
6. recall retrieves attacked/rejected history at a fixed cursor;
7. later events cannot leak into an old recall artifact;
8. missing or stale recall artifacts fail closed;
9. missing reactivation basis is rejected;
10. unresolved historical blockers prevent L3 selection;
11. partial resolution creates downstream QC obligations;
12. L2 receives history for five or more hypotheses;
13. L3 performs blocker review when L2 is skipped;
14. contradicted hypotheses require explicit treatment of contradictory evidence;
15. falsified hypotheses cannot use ordinary reactivation;
16. reopening requires new verified post-falsification evidence;
17. successful reopening permits later reactivation;
18. projection is deterministic and rebuildable;
19. JSONL/SQLite/Markdown exports have verifiable manifests;
20. multi-round end-to-end flow: rejected → recalled → new evidence → reproposed → selected, with all old events preserved.

## Acceptance criteria

The implementation is complete only when structured interfaces can answer:

- where and when a hypothesis was first proposed;
- every round in which it was attacked or rejected and why;
- its current workflow and epistemic states;
- whether it is currently eligible for reactivation;
- what evidence or changed condition supports the current reactivation;
- whether the current item is the same version, a revision, or a derived hypothesis;
- whether historical blockers were resolved;
- whether old events remain intact after new selection;
- and whether the entire pool can be rebuilt and exported from finalized append-only facts.