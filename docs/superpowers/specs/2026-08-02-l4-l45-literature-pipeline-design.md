# L4A/L4B/L4C and L4.5 Method-Planning Architecture

## Decision

Keep the public scientific DAG and downstream numbering stable, but make the
method-planning boundary explicit:

```text
L3 selected hypotheses
  -> L4A Literature Discovery
  -> L4B Evidence Construction
  -> L4C Fisher Method Design (`L4_fisher`)
  -> L4.5 Deterministic Commit Gate
  -> L5 Tukey
```

L4A, L4B, and L4C are the three ordered responsibilities of the global L4
method-planning pipeline. L4.5 is not another model persona. It is a
deterministic provenance and commit boundary executed after the L4 Fisher delta
has been validated.

The candidate remains `IDEA_SELECTED` through L4A and L4B. The existing L4C
Fisher delta and existing transition to `METHOD_PROPOSED` remain authoritative.
L5-L10 numbering, personas, schemas, and authority boundaries are unchanged.

## Reuse-first rule

RLR owns only the contracts, stage boundaries, deterministic validation,
persistence, and provenance links. It does not reimplement mature retrieval or
parsing systems.

- Academic Research Skills remains the default L4 research runtime.
- Existing `deep_research`, `method_evidence`, navigation, user-source, and
  review-status extensions remain the L4B implementation.
- Literature-search MCP, Zotero, OpenAlex, Europe PMC, PaperQA2, GROBID, and
  Docling are optional adapters behind the L4A/L4B contracts; none becomes a
  hard base dependency.
- Existing `L4_fisher` remains L4C.
- Existing evidence validators remain the single source of truth; the new
  pipeline must not duplicate or weaken them.

## L4A: Literature Discovery

L4A answers: which sources may contain methods relevant to the selected
hypotheses and diagnostics?

It performs query planning, metadata search, identifier normalization,
deduplication, relevance selection, and full-text availability registration.
It must not return source payloads, located extracts, method anchors, method
components, or final method choices.

Provider output is metadata-only and is persisted as:

```text
09_Literature_Database/l4/discovery/manifests/<run_id>.json
```

The canonical artifact is `L4ADiscoveryManifest/v1`. It includes query
receipts, selected/reserve/rejected assets, deterministic duplicate records,
the runtime receipt, and a content hash. Identity priority is DOI, PMID, stable
URL, then normalized title plus year. The higher-relevance duplicate is kept.

L4A failure prevents L4B. A successful discovery with zero selected records is
an explicit blocker, not an empty success.

## L4B: Evidence Construction

L4B consumes only the frozen selected L4A records plus registered user sources.
It may resolve identifiers and retrieve legal full text for those records, but
may not silently replace the frozen corpus with a new broad search.

L4B reuses the existing strict L4 method-evidence implementation:

- actual retained source payload;
- verbatim contiguous substring validation;
- accepted source kinds;
- Methods-heading restrictions where required;
- review/navigation separation;
- registered PDF ID and SHA256 binding;
- required-component coverage by an eligible accepted anchor or an explicit
  source blocker.

The existing evidence pack remains the canonical L4B artifact. New packs add
only versioned linkage fields:

```text
l4_pipeline_schema: L4MethodPlanningPipeline/v1
pipeline_stage: L4B
l4a_discovery_run_id
l4a_discovery_manifest_path
l4a_discovery_manifest_sha256
```

Existing pre-pipeline evidence packs remain readable. New L4B packs must fail
closed when the linked L4A manifest is missing or changed.

## L4C: Fisher Method Design

L4C is the existing cognitive `L4_fisher` node. It consumes the hash-bound L4B
method catalog through the existing context-manifest path and creates the
existing method-design delta. No second Fisher implementation is introduced.

L4C does not perform broad literature discovery and does not alter retained
source text. Its delta schema, storage key, persona, and state transition remain
unchanged.

## L4.5: Deterministic Commit Gate

L4.5 runs after a valid L4C delta is ready to be committed. It performs no LLM
call and no scientific method selection.

For new pipeline artifacts it verifies:

1. the exact L4A manifest exists and its SHA256 matches the L4B link;
2. the exact L4B evidence run passes the existing audit;
3. the context-bound evidence manifest has not changed;
4. the committed L4C delta file exists and its SHA256 is recorded;
5. method component, method candidate, and anchor identifiers are projected
   from the audited L4B artifact without invention.

It writes an immutable `L45MethodCommit/v1` projection under:

```text
08_Audit/l4_method_commits/<commit_id>.json
```

The projection binds L4A, L4B, and L4C hashes. It is a rebuildable audit
projection, not a competing scientific source of truth. Identical retries are
idempotent; a path collision with different content fails closed.

Legacy evidence packs without `L4MethodPlanningPipeline/v1` remain compatible
and are not retroactively rewritten into an L4.5 projection.

## Runtime integration

A focused `research_loop.l4_pipeline` extension is installed after the current
method-evidence, navigation, and compatibility extensions.

- Non-L4 `run_and_persist` calls delegate unchanged.
- L4 calls execute L4A first, persist it, then call the captured mature L4B
  implementation with the frozen selected-asset catalog injected into the
  request.
- `evidence_artifact_manifest` and `audit_evidence_pack` are extended only for
  new pipeline-linked runs so the L4A manifest participates in context hashing.
- The native delta persistence transaction creates the L4.5 projection at the
  same fail-closed boundary as the L4C delta and ledger receipt.

## Failure semantics

- L4A invocation or schema failure: no L4B call.
- No selected L4A records: manifest persists; L4B does not run.
- L4B failure: L4A remains available for retry; no completed linked evidence
  pack is exposed.
- L4A hash mismatch or missing manifest: L4B audit and L4.5 fail.
- L4C failure: no L4.5 projection.
- L4.5 failure: native transaction fails rather than reporting a successful L4
  commit without the required projection.
- Non-L4 behavior and legacy evidence readers remain unchanged.
