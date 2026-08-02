# Long-Lived Hypothesis Pool and Reactivation Design

## Goal

Extend the append-only hypothesis ledger into a usable long-lived hypothesis pool. Historical hypotheses remain searchable after attack, rejection, contradiction, or insufficient evidence. A later round may reactivate an unchanged hypothesis, revise its test definition, or derive a related hypothesis without rewriting any prior occurrence or event.

The central invariant is:

> Rejecting an occurrence does not delete or permanently reject the hypothesis version.

## Scope

This design covers:

- a rebuildable hypothesis-pool projection;
- mandatory historical recall before native L1 execution;
- L1 provenance for new, reactivated, revised, and derived hypotheses;
- new occurrences for unchanged historical hypotheses;
- L2/L3 review of unresolved historical objections;
- propagation of partially resolved objections into downstream QC obligations;
- strict reopening rules for formally falsified hypotheses;
- pool query, reporting, and cursor-bound export interfaces;
- tests and user documentation.

It does not replace the SQLite ledger, mutate old events, delete historical hypotheses, make embedding search mandatory, or retroactively change legacy profiles.

## Existing model retained

The current authoritative ledger remains the source of truth:

- `families` represent stable hypothesis families;
- `versions` represent exact combinations of statement, operationalization, and falsification criteria;
- `occurrences` represent use of a version in one project, candidate, and round;
- `events` contain append-only lifecycle facts;
- workflow and epistemic projections are rebuildable current-state views.

The pool, recall, and export layers are projections over finalized ledger facts, not replacement sources of truth.

## Identity and reuse rules

### Reactivation

Use `REACTIVATE` only when normalized statement, operationalization, and falsification criteria are unchanged.

- Reuse the existing `hypothesis_id` and family ID.
- Create a new occurrence for the current project/candidate/round.
- Record `REPROPOSED` with source hypothesis, source occurrence, recall artifact, and reactivation basis.
- Set only the new occurrence to `PROPOSED`.
- Preserve all historical rejected occurrences, attacks, and decisions.

### Revision

Use `REVISE` when the normalized statement is unchanged but operationalization or falsification criteria change.

- Create a new hypothesis version.
- Retain the source family ID.
- Record `REVISED` linking the new version to the source version.
- Create a current-round occurrence for the new version.

### Derivation

Use `DERIVE` when the normalized statement differs from the source statement.

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

Reactivation eligibility is computed from finalized facts:

- `ELIGIBLE`: no unresolved condition must be supplied before reproposal;
- `ELIGIBLE_WITH_BASIS`: reactivation requires a stated changed condition or new evidence;
- `REQUIRES_EXPLICIT_OVERRIDE`: archived or materially contradicted hypotheses require an explicit basis and L3 review;
- `BLOCKED_FALSIFIED`: ordinary L1 reactivation is forbidden until formal reopening succeeds.

This eligibility value is a projection. It never overwrites historical states.

## Hypothesis-pool projection

Add `src/research_loop/hypothesis_pool.py` as a pure read/projection module. It derives one pool record per hypothesis version at a specified finalized commit cursor.

Each record includes:

- hypothesis and family IDs;
- statement, operationalization, and falsification criteria;
- epistemic status;
- occurrence count and occurrence history;
- attack, confounder, diagnostic-test, and verdict counts;
- rejection count and last rejection details;
- latest occurrence and workflow status;
- unresolved historical blocker event IDs;
- related version and lineage IDs;
- reactivation eligibility and requirements;
- first-seen and last-seen metadata.

The projection must be deterministic and fully rebuildable. Deleting a cached projection must not delete information or change recomputed content at the same finalized cursor.

## Mandatory historical recall before L1

Native runs add a required pre-L1 recall gate without adding a new formal DAG node in the first implementation.

```text
L0 finalized
→ deterministic hypothesis-pool recall
→ immutable recall artifact
→ L1 context assembly binds exact artifact and hash
→ L1 execution
```

The canonical runner generates or validates the recall artifact before assembling L1 context. Manual workflows use the same `hypothesis-recall` command. A valid zero-result artifact passes; missing, stale, or invalid recall blocks native L1.

Artifacts are stored under:

```text
08_Audit/hypothesis_recall/<candidate_id>_round_<round_id>.json
```

Each artifact binds:

- store and project IDs;
- candidate and round IDs;
- finalized `as_of_commit_seq`;
- normalized query terms and filters;
- deterministic ranking method and result limit;
- returned hypothesis, family, version, and occurrence IDs;
- pool summaries and blocker event IDs;
- generation time and artifact hash.

The L1 `ContextManifest/v2` records the recall artifact path, SHA256, cursor, and returned IDs. Events committed later cannot appear retroactively in an older artifact.

Non-`NEW` L1 items may reference only historical sources present in the exact recall artifact bound to the L1 context.

## Recall implementation

The first version uses deterministic retrieval:

1. exact hypothesis ID;
2. exact family ID;
3. SQLite FTS over statement and operationalization;
4. normalized keyword matching over study entities, variables, and method terms;
5. workflow, epistemic, and eligibility filters.

Ordering is stable:

- exact hypothesis matches;
- exact family matches;
- FTS rank;
- keyword score;
- `hypothesis_id` as the final tie-breaker.

The default maximum is 50 pool records, configurable within a bounded limit. The artifact records all ranking inputs and scores.

Semantic embeddings may be added later as an optional recall channel. They cannot be required for correctness or silently merge identities.

## Node-specific visibility

### L1

L1 receives:

- historical statement and version ID;
- latest disposition and epistemic status;
- blocker codes and missing conditions;
- reactivation eligibility;
- source occurrence ID.

L1 does not receive all attack prose by default, reducing anchoring while preventing accidental duplication.

### L2

When five or more hypotheses cause L2 to run, L2 receives:

- full historical attacks, confounders, diagnostic tests, and verdicts;
- evidence or condition changes claimed in the current reactivation basis;
- unresolved blocker event IDs.

L2 assesses whether each material blocker is resolved, partially resolved, or unresolved.

### L3

L3 receives the full recall and review record. It decides whether the item is:

- a valid reactivation of the same version;
- a revision requiring a new version;
- a derived hypothesis;
- or still blocked and therefore rejected.

When L2 is skipped for 1–4 hypotheses, L3 performs the blocker assessment directly. Conditional L2 skipping never skips reactivation validation.

## L1 contract extension

Each hypothesis may add:

```json
{
  "origin": "NEW | REACTIVATE | REVISE | DERIVE",
  "source_hypothesis_id": "H:...",
  "source_occurrence_id": "HO:...",
  "parent_hypothesis_ids": ["H:..."],
  "change_summary": "...",
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

- omitted `origin` is normalized to `NEW` for backward compatibility;
- `NEW` carries no source or parent IDs;
- `REACTIVATE` requires source hypothesis and occurrence IDs and, when eligibility demands it, a reactivation basis;
- `REVISE` requires one source hypothesis ID and a non-empty change summary;
- `DERIVE` requires one or more parent hypothesis IDs and a non-empty change summary;
- engine-owned IDs remain assigned during persistence.

Missing `origin` never permits implicit historical reuse: if source IDs are supplied, `origin` must be explicit.

## Reactivation validation

Before committing L1:

1. Validate the exact recall artifact bound to the L1 context.
2. Resolve all source IDs from finalized ledger facts at the recall cursor.
3. Require every non-`NEW` source to appear in that artifact.
4. Reject duplicate use of the same hypothesis version within the current candidate/round.
5. For `REACTIVATE`, require exact definition-hash identity with the source version.
6. For `REVISE`, require the same normalized statement and a changed operationalization or falsification definition.
7. For `DERIVE`, require a different normalized statement and valid parent IDs.
8. Validate eligibility and required basis fields.
9. Reject ordinary reactivation of `FALSIFIED` versions.

`USER_RECONSIDERATION` is allowed for prior workflow rejection, but does not claim that scientific objections are resolved.

## L3 reactivation assessment and obligations

Reactivated, revised, and derived hypotheses add:

```json
{
  "reactivation_assessment": {
    "source_hypothesis_id": "H:...",
    "prior_blocking_event_ids": ["HE:..."],
    "basis_verdict": "RESOLVED | PARTIALLY_RESOLVED | UNRESOLVED | NOT_APPLICABLE",
    "reason": "...",
    "remaining_risks": [],
    "required_followups": [
      {
        "obligation_id": "RO:...",
        "type": "QC_CHECK | STOP_RULE | DATA_REQUIREMENT",
        "description": "..."
      }
    ]
  }
}
```

Constraints:

- `UNRESOLVED` cannot be `SELECTED`;
- `PARTIALLY_RESOLVED` may be selected only with at least one `required_followup`;
- L4/L5/L6 must carry each obligation ID forward and resolve it into an explicit method step, QC checkpoint, stop rule, or data requirement before L7;
- the execution gate rejects an approved plan with unresolved reactivation obligations;
- falsified hypotheses without a valid reopening event cannot be selected;
- the assessment records `REACTIVATION_REVIEWED` and never deletes prior attacks.

## Formal reopening of falsified hypotheses

`FALSIFIED` is not equivalent to workflow rejection. Add a separate `hypothesis-reopen` operation, reusing the existing `REOPENED` epistemic event semantics.

It requires:

- source hypothesis ID;
- exact prior `FALSIFIED` event ID;
- verified evidence committed after that falsification;
- explanation of why the prior criterion or evidence interpretation no longer holds;
- explicit `supersedes_event_id` binding.

The operation first records `REOPEN_REQUESTED`, then records one outcome:

- `REOPENED`: append-only epistemic supersession succeeds;
- `REOPEN_REJECTED`: request and reason remain in history, state remains falsified.

Only a successfully reopened version becomes eligible for later L1 reactivation.

## Event additions

Add:

- `REPROPOSED`
- `REACTIVATION_REVIEWED`
- `REOPEN_REQUESTED`
- `REOPEN_REJECTED`

Existing `REOPENED`, `PROPOSED`, `ATTACKED`, `SELECTED`, `REJECTED`, `REVISED`, `DERIVED`, `FALSIFIED`, `ARCHIVED`, and `SUPERSEDED` retain their meanings.

`REPROPOSED` is occurrence reuse. `REOPENED` is epistemic reversal of formal falsification. They are never interchangeable.

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
- a consistent SQLite snapshot created through SQLite's backup mechanism;
- Markdown pool report;
- manifest with schema version, cursor, record counts, file hashes, and generation time.

Exports cannot overwrite or import back into the authoritative ledger in this scope.

## Error handling

Fail closed for:

- unknown, unfinalized, or post-cursor source IDs;
- missing, stale, or hash-mismatched recall artifacts;
- a non-`NEW` source absent from the bound recall artifact;
- exact-definition mismatch for `REACTIVATE`;
- unchanged definition submitted as `REVISE`;
- same-statement submission classified as `DERIVE`;
- duplicate current-round occurrence;
- missing required basis or blocker assessment;
- selecting an unresolved reactivation;
- partially resolved selection without follow-up obligations;
- unresolved obligations at execution;
- falsified version without successful reopening;
- reopening without new verified post-falsification evidence;
- projection or export mismatch at a fixed cursor.

Diagnostics identify hypothesis, source event, eligibility rule, and corrective action.

## Compatibility

- Existing ledger facts and historical delta files are not rewritten.
- Omitted L1 `origin` is normalized to `NEW`; explicit historical reuse requires explicit non-`NEW` origin.
- Existing occurrence and version IDs retain their meaning.
- L1 remains 1–12 hypotheses.
- 1–4 hypotheses still skip L2; 5–12 still run L2.
- Legacy profiles remain read-only and do not gain recall or reactivation events.
- Native recall and pool projection operate only over finalized emissions.
- Enabling the feature requires native context manifests to bind a recall artifact; a valid zero-result artifact is sufficient.

## Implementation boundaries

New focused modules:

- `src/research_loop/hypothesis_pool.py`
- `src/research_loop/hypothesis_recall.py`
- `src/research_loop/hypothesis_reopening.py` if reopening logic would otherwise enlarge the ledger module excessively.

Likely modifications:

- `hypothesis_contracts.py`
- `hypothesis_ledger.py`
- `constraint_validation.py`
- `context.py`
- `topology.py`
- execution and traceability gates;
- CLI and ledger/lifecycle command modules;
- L1/L2/L3/L4/L5/L6 templates;
- runner orchestration, documentation, and tests.

No unrelated ledger refactor is included.

## Delivery decomposition

The implementation plan should use two reviewable milestones on one feature branch or two dependent PRs:

### Milestone 1: core pool, recall, and reactivation

- pool projection and query interfaces;
- mandatory cursor-bound recall;
- L1 NEW/REACTIVATE/REVISE/DERIVE handling;
- L2/L3 blocker review;
- obligation propagation through L6 and the execution gate.

### Milestone 2: strict reopening and preservation interfaces

- falsified-hypothesis reopening command and events;
- pool reports and exports;
- SQLite snapshot and manifest verification;
- complete end-to-end documentation.

Milestone 2 must not weaken Milestone 1's fail-closed recall or reactivation rules.

## Test strategy

Required tests include:

1. rejected hypotheses remain searchable;
2. unchanged reactivation reuses hypothesis ID and creates a new occurrence;
3. old rejected occurrence remains rejected;
4. revision creates a new version in the same family;
5. derivation creates a linked new family;
6. cross-project recall within the same store is correctly attributed;
7. recall retrieves attacked/rejected history at a fixed cursor;
8. later events cannot leak into an old recall artifact;
9. valid zero-result recall passes and missing/stale recall fails;
10. non-`NEW` sources absent from recall fail;
11. missing reactivation basis is rejected;
12. unresolved historical blockers prevent L3 selection;
13. partial resolution creates enforceable downstream obligations;
14. execution rejects unresolved obligations;
15. L2 receives history for five or more hypotheses;
16. L3 performs blocker review when L2 is skipped;
17. contradicted hypotheses require explicit treatment of contradictory evidence;
18. falsified hypotheses cannot use ordinary reactivation;
19. reopening requires new verified post-falsification evidence;
20. successful reopening permits later reactivation;
21. projection is deterministic and rebuildable;
22. JSONL, SQLite, and Markdown exports have verifiable manifests;
23. multi-round flow: rejected → recalled → new evidence → reproposed → selected, with old events preserved;
24. legacy and ordinary NEW submissions remain compatible.

## Acceptance criteria

Structured interfaces must answer:

- where and when a hypothesis was first proposed;
- every round in which it was attacked or rejected and why;
- its current workflow and epistemic states;
- whether it is eligible for reactivation;
- what evidence or changed condition supports the current reactivation;
- whether the item is the same version, a revision, or a derived hypothesis;
- whether historical blockers were resolved;
- which follow-up obligations remain before execution;
- whether old events remain intact after new selection;
- and whether the pool can be rebuilt and exported from finalized append-only facts.