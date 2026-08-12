# Round Data Continuity Design

## Goal

Make one round-level data contract the sole machine authority for which scientific data a candidate may consume, including selected immutable artifacts inherited from round N and newly declared data for round N+1, without copying large data or introducing a second registry.

## Global architecture review

This change is required because RLR currently has two machine authorities for the same concern: L0 verifies `l0_input.yaml/source_input`, while L7 resolves executable inputs from `00_Preflight/input_manifest.md`. PR #15 solved evidence existence and cross-round hash verification, but not authorization of verified previous-round artifacts as current-round inputs. The root problem is therefore authority duplication and a missing authorization handoff, not a missing file-copy feature.

The redesign must preserve the existing responsibility boundaries:

- `l0_contract.py` remains the sole declaration authority for current-round scientific input intent.
- `l0_state.py` remains the sole round-manifest / previous-round evidence-restore authority.
- `L0EvidenceBinding/v1` continues to prove what previous-round artifacts were verified; it does not by itself authorize all of them for reuse.
- L7 workspace staging remains the only execution-file materialization boundary.
- Hypothesis Ledger remains the sole formal hypothesis lifecycle authority and is not changed by this work.
- Large scientific files remain in place and are identified by exact path + SHA-256; no new Evidence Store database, DVC dependency, DataLad dependency, or duplicate physical store is introduced.

## Single-authority model

The canonical flow becomes:

```text
l0_input.yaml
  ├── current/new source_input declaration
  └── optional inherited_inputs selectors (continuation only)
             │
             ▼
previous L0EvidenceBinding + previous round manifest
             │ exact verified match only
             ▼
CurrentRoundDataBinding/v1
  ├── current_inputs
  ├── inherited_inputs
  └── authorized_inputs
             │
       ┌─────┴─────┐
       ▼           ▼
context/audit   L7 workspace staging
metadata only   actual allowlisted files
```

`CurrentRoundDataBinding/v1` is a deterministic projection, not a new source of truth. Its inputs are the current `l0_input` contract and, for continuation rounds, the already verified previous-round evidence binding. It records exactly which files are authorized for this round and why.

## L0 input contract evolution

Newly created native candidates use `L0InputContract` schema 1.1. Existing 1.0 artifacts remain readable for compatibility but are not extended with new semantics.

Schema 1.1 keeps `source_input` for data newly declared in the current round and adds `inherited_inputs` for continuation reuse. Each inherited selector contains:

- `path`: project-relative artifact path from the previous round manifest;
- `sha256`: exact expected artifact hash;
- `role`: caller-declared role in the current round;
- `reuse_reason`: why this prior artifact is needed now.

Only previous `source_artifacts`, `intermediate_artifacts`, and `result_artifacts` are eligible. Literature, audit files, receipts, reports, and manifests cannot become execution data through this selector.

For continuation rounds, the authorized data set is:

```text
selected inherited inputs ∪ newly declared source_input files
```

At least one member must exist in the union. This permits three legitimate cases without duplication: inherited-only, new-only, and inherited+new.

Initial rounds prohibit `inherited_inputs`.

## CurrentRoundDataBinding/v1

A deterministic per-candidate artifact is written under `08_Audit/l0_data/` only after the L0 contract and any required previous-round restore have passed.

Required identity fields:

- schema version;
- project ID;
- candidate ID;
- round ID / round type;
- exact L0 input-contract path + SHA-256;
- previous evidence-binding path + SHA-256 when continuation reuse is requested.

Each authorized input records:

- project-relative or normalized source path;
- SHA-256;
- byte size where locally available;
- role;
- origin: `current_round` or `inherited`;
- inherited source candidate / round / artifact category when applicable;
- declaration or reuse reason.

Binding creation fails closed on missing files, hash mismatch, selector ambiguity, selector targeting a non-data artifact class, or duplicate paths with conflicting hashes.

No scientific interpretation occurs here.

## L7 execution authority

`prepare_turing_workspace()` and `execution-gate` stop using `00_Preflight/input_manifest.md` as a machine source of candidate data. They consume only the exact current-round data binding and stage its `authorized_inputs`.

The existing workspace copy-and-record mechanism remains unchanged in principle: each staged file still records original path, workspace path, SHA-256, reason, candidate, and node. This is wiring to an existing execution boundary, not a new execution system.

`00_Preflight/input_manifest.md` may remain as a legacy/human-readable project document, but its rows no longer authorize L7 input and its absence cannot independently block a native candidate once a valid current-round binding exists.

## Cognitive visibility

Path B isolation is preserved. Cognitive nodes do not receive raw inherited files merely because they are authorized for L7. L0 may render compact binding metadata; later cognitive nodes only receive data references through their existing allowed deltas/evidence paths. This change must not dump the full previous-round artifact catalog into prompts.

## Provenance and immutability

Previous-round files remain immutable by their frozen manifest hashes. Reuse is authorization by reference, not copying.

If a prior artifact changes, the existing restore hash gate fails before a data binding can be written. If a current-round declared file changes after binding, L7 revalidates the bound SHA before staging and fails closed.

A corrected or expanded dataset is a new current-round input with new bytes/hash; it does not overwrite the identity of a previously frozen artifact.

## Reuse of existing RLR components

This implementation must reuse rather than duplicate:

- `l0_plan_intake` file-manifest verification for path normalization, byte checks, SHA checks, duplicate detection, and optional roles;
- `l0_state` artifact classification and exact previous-round restore;
- the authorization-manifest pattern already used by hypothesis recall/context provenance;
- `commands/execution.py` workspace staging and per-file provenance;
- existing round manifests and receipts.

No generic Data Registry, data database, object store, DVC wrapper, or DataLad wrapper is introduced.

## Failure semantics

New failures are data-authorization failures, not generic restore failures. They must identify the violated boundary, for example:

- inherited selector not present in verified previous-round data artifacts;
- inherited selector hash mismatch;
- inherited selector targets non-data artifact category;
- current declared source changed before binding;
- current-round binding missing/invalid at execution;
- bound input changed before L7 staging.

Exact error-code names are finalized with tests before production code, following the repository's L0 fail-closed naming convention.

## Testing strategy

The vertical acceptance path must prove all of the following:

1. Initial round with only current data produces a valid data binding and L7 stages exactly those files.
2. Continuation round can select a previous source/result artifact without copying it into the new round declaration.
3. Continuation round can combine selected inherited data with newly declared files.
4. Continuation round can run inherited-only.
5. Unselected previous-round artifacts never enter the L7 workspace.
6. Literature/audit/receipt artifacts cannot be selected as executable data.
7. Tampering with an inherited artifact fails during restore/binding before provider work.
8. Tampering with current data after binding fails before L7 copies it.
9. `input_manifest.md` cannot grant an extra file that is absent from the data binding.
10. Existing PR #15 L0 restore tests, L4 evidence tests, and the full suite remain green.

## Non-goals

This PR does not redesign formal hypothesis lifecycle, add scientific-question versioning, implement human identity/authentication, refactor the literature transport, or introduce external data-versioning/storage infrastructure. Those are separate concerns unless a failing integration test proves they are required for this authority unification.
