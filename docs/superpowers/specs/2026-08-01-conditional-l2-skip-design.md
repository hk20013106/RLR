# Conditional L2 Skip Design

## Goal

Skip the L2 Feynman attack stage when L1 produces four or fewer valid hypotheses. Route directly from L1 to L3 while preserving an auditable record that L2 was intentionally skipped rather than omitted accidentally.

## Exact rule

Count the committed, schema-valid, unique hypotheses in the candidate-owned L1 delta.

- `1-4` hypotheses: skip L2 and route directly to L3.
- `5+` hypotheses: run L2 normally.
- `0` hypotheses: do not skip forward; L1 remains invalid under its existing stop condition.

The threshold is inclusive: exactly four hypotheses skips L2; exactly five runs L2.

## Audit semantics

Do not create a fake L2 delta. No attack occurred, so an empty or synthetic `L2_feynman` artifact would be misleading.

Instead write an immutable skip receipt under:

```text
08_Audit/node_skips/<candidate_id>_L2.json
```

The receipt contains:

- schema version;
- project and candidate IDs;
- skipped node `L2`;
- source node `L1`;
- committed L1 delta path and SHA256;
- valid hypothesis count;
- threshold `4`;
- reason `hypothesis_count_lte_4`;
- timestamp.

The receipt is generated deterministically when routing evaluates a committed L1 delta with one to four hypotheses. Repeated `next-step` calls must not create conflicting receipts.

## Routing and context

`next-step` for status `IDEA_PROPOSED` behaves as follows after L1 is committed:

- one to four hypotheses: return L3 as the next node and include `skipped_nodes: [{node: "L2", reason: "hypothesis_count_lte_4", hypothesis_count: N}]`;
- five or more hypotheses: return L2;
- absent or invalid L1: preserve existing fail-closed behavior.

L3 context assembly becomes conditional:

- normal path: consume L1 and L2;
- skip path: consume L1 plus the verified L2 skip receipt, with no requirement for an L2 delta.

L3 must not infer that hypotheses survived falsification. Its instructions explicitly state that the small set bypassed L2 for efficiency and still requires independent triage against L1 evidence, testability, redundancy, feasibility, and predeclared falsification criteria.

## Topology presentation

The static DAG still documents L2 as the attack node. L1/L3 descriptions add the conditional edge:

```text
L1 -- hypothesis_count <= 4 --> L3
L1 -- hypothesis_count >= 5 --> L2 --> L3
```

This is a route policy, not a new candidate status transition. Candidate status remains `IDEA_PROPOSED` until L3 triage changes it to `IDEA_SELECTED` or rejection/drop behavior applies.

## Compatibility

- Existing candidates with committed L2 deltas continue to use them.
- The current real-data candidate has already completed L2 and is unaffected.
- Existing L2 artifacts are never deleted or replaced by skip receipts.
- L1 and L3 delta schemas remain unchanged unless implementation discovers that an explicit route field is necessary; the skip receipt is the preferred compatibility mechanism.

## Expected files

- `src/research_loop/commands/lifecycle.py`: conditional next-node selection and skip-receipt creation/validation;
- `src/research_loop/context.py` or its current context-resolution owner: conditional L3 inputs;
- `src/research_loop/topology.py`: human-readable conditional routing metadata/instructions;
- focused helper module if skip receipt logic would otherwise enlarge lifecycle routing;
- `tests/test_candidate_aware_next_step.py` and context tests;
- DAG/user documentation.

## Tests

Cover at minimum:

- one, two, three, and four valid hypotheses route directly to L3;
- five hypotheses route to L2;
- zero hypotheses do not route to L3;
- duplicate hypothesis IDs or malformed hypotheses are not silently counted as valid;
- skip receipt binds to the committed L1 delta hash;
- repeated routing is idempotent;
- L3 context accepts a valid skip receipt without L2;
- L3 context rejects a missing, stale, mismatched, or tampered skip receipt;
- existing candidates with an L2 delta still route normally;
- current full suite remains green.