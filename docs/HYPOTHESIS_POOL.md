# Long-lived Hypothesis Pool

RLR stores hypotheses in the append-only hypothesis ledger. A rejection applies
to one occurrence in one project/candidate/round. It does not delete the
hypothesis version and does not permanently forbid later testing.

## Lifecycle

```text
historical hypothesis version
├── round 1 occurrence: ATTACKED → REJECTED
└── round 2 occurrence: REPROPOSED → REACTIVATION_REVIEWED/SELECTED
```

The old occurrence remains `REJECTED`. Reactivation creates a new occurrence;
it never edits the old workflow state or removes the old attack events.

## Recall before L1

Create the cursor-bound recall artifact before assembling native L1 context:

```powershell
python research_loop_v04.py hypothesis-recall PROJECT CANDIDATE_ID `
  --round-id 2 `
  --query "extracellular matrix heart rate" `
  --knowledge-store PATH_TO_SHARED_LEDGER
```

The artifact is stored at:

```text
08_Audit/hypothesis_recall/<candidate_id>_round_<round_id>.json
```

Native L1 context and provider receipts bind the exact file hash, artifact hash,
ledger cursor, and returned hypothesis IDs. A non-`NEW` hypothesis may only
reference a source actually present in this artifact.

## L1 formats

### New hypothesis

`origin` may be omitted by old callers; new commits normalize it to `NEW`.

```json
{
  "proposal_key": "p1",
  "origin": "NEW",
  "statement": "...",
  "operationalization": "...",
  "falsification_criteria": ["..."],
  "rationale": "..."
}
```

### Reactivate the unchanged version

Use `REACTIVATE` only when statement, operationalization, and falsification
criteria are exactly unchanged. RLR reuses the historical `hypothesis_id` and
creates a new `occurrence_id`.

```json
{
  "proposal_key": "p1",
  "origin": "REACTIVATE",
  "source_hypothesis_id": "H:...",
  "source_occurrence_id": "HO:...",
  "statement": "exact historical statement",
  "operationalization": "exact historical operationalization",
  "falsification_criteria": ["exact historical criterion"],
  "rationale": "Why this hypothesis should be tested again",
  "reactivation_basis": {
    "basis_type": "NEW_EVIDENCE",
    "summary": "What changed since the rejection",
    "evidence_ids": [],
    "artifact_refs": [],
    "changed_conditions": ["larger sample size is now available"]
  }
}
```

### Revise the existing hypothesis family

Use `REVISE` when the normalized statement remains the same but the
operationalization or falsification criteria change. RLR creates a new
`hypothesis_id` in the same `hypothesis_family_id`.

```json
{
  "proposal_key": "p1",
  "origin": "REVISE",
  "source_hypothesis_id": "H:...",
  "source_occurrence_id": "HO:...",
  "statement": "same normalized statement",
  "operationalization": "revised test",
  "falsification_criteria": ["revised criterion"],
  "rationale": "Why the revised version is testable",
  "change_summary": "What changed from the historical version"
}
```

### Derive a new hypothesis

Use `DERIVE` when the statement changes. RLR creates a new family/version and
records the recalled parent IDs.

```json
{
  "proposal_key": "p1",
  "origin": "DERIVE",
  "parent_hypothesis_ids": ["H:..."],
  "statement": "new derived statement",
  "operationalization": "...",
  "falsification_criteria": ["..."],
  "rationale": "Why the derivative should be tested",
  "change_summary": "How it differs from the parent"
}
```

## L2 routing

- 1–4 committed hypotheses: L2 is skipped using a hash-bound
  `NodeSkipReceipt/v1`; L3 still performs the historical-blocker review.
- 5–12 committed hypotheses: L2 attacks the hypotheses before L3.

The ledger accepts L3 without an L2 delta only when the exact L1-bound skip
receipt verifies.

## L3 reactivation review

Every `REACTIVATE`, `REVISE`, or `DERIVE` item requires an explicit review:

```json
{
  "hypothesis_id": "H:...",
  "disposition": "SELECTED",
  "reason_code": "TESTABLE",
  "reason": "...",
  "assessments": {
    "testability": {"verdict": "PASS", "evidence": "..."},
    "novelty": {"verdict": "PASS", "evidence": "..."},
    "feasibility": {"verdict": "PASS", "evidence": "..."},
    "impact": {"verdict": "PASS", "evidence": "..."}
  },
  "reactivation_assessment": {
    "source_hypothesis_id": "H:...",
    "prior_blocking_event_ids": ["HE:..."],
    "basis_verdict": "RESOLVED",
    "reason": "How the new basis addresses the old blocker",
    "remaining_risks": []
  }
}
```

Allowed verdicts:

- `RESOLVED`: may be selected.
- `PARTIALLY_RESOLVED`: may be selected only with explicit downstream QC,
  stop-rule, or data obligations.
- `UNRESOLVED`: cannot be selected.
- `NOT_APPLICABLE`: must still explain why the historical blocker no longer
  applies.

## Falsified hypotheses

A hypothesis with epistemic status `FALSIFIED` cannot be reused through normal
L1 reactivation, revision, or derivation. Formal reopening is a separate
workflow and is not part of this implementation phase.

## Pool inspection

```powershell
python research_loop_v04.py hypothesis-pool-list PROJECT `
  --knowledge-store PATH_TO_SHARED_LEDGER

python research_loop_v04.py hypothesis-pool-search PROJECT `
  --text "matrix expression" `
  --knowledge-store PATH_TO_SHARED_LEDGER

python research_loop_v04.py hypothesis-pool-show PROJECT HYPOTHESIS_ID `
  --knowledge-store PATH_TO_SHARED_LEDGER
```

The pool projection shows every occurrence, historical attacks and rejections,
current epistemic status, unresolved blockers, and reactivation eligibility.
It is rebuildable from immutable ledger facts and is not a second source of
truth.
