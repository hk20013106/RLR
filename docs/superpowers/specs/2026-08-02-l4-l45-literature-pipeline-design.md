# L4/L4.5 Literature Pipeline Design

## Decision

Use two pre-research stages and do not add L3.5.

- **L4 Discovery** owns query generation, literature search, metadata normalization, deduplication, relevance selection, open-access/full-text status, and immutable discovery receipts.
- **L4.5 Evidence Construction** consumes the frozen L4 selection, resolves available full text, extracts source-located Methods evidence, verifies verbatim containment and section location, and constructs the method-component catalog consumed by Fisher.
- The existing cognitive node remains `L4_fisher`; downstream node numbers and delta contracts are unchanged.

L3.5 is unnecessary because query planning has no independent scientific decision, state transition, or downstream consumer. It is an internal responsibility of L4 Discovery and remains inspectable through the discovery manifest.

## Root cause addressed

The current L4 provider request asks one sub-agent to search, retrieve metadata, obtain full text, identify sections, copy verbatim evidence, classify source types, execute a review search, and synthesize a complete method catalog in one response. One failure invalidates the entire batch. The new boundary separates metadata discovery from evidence construction without weakening evidence gates.

## Runtime flow

```text
L3 selected hypotheses
        |
        v
L4 Discovery
  - query plan
  - online/local candidate metadata
  - global deduplication
  - selected/rejected/manual-review records
  - OA/full-text availability status
        |
        | LiteratureDiscoveryRun/v1
        v
L4.5 Evidence Construction
  - only selected records are eligible inputs
  - full-text/source resolution
  - Methods-section extraction
  - verbatim source-payload verification
  - method components/candidates/anchors
        |
        | EvidenceRunReceipt/v1.3
        v
L4 Fisher method design
```

## Compatibility boundary

The split is implemented as a focused extension around `research_loop.deep_research.run_and_persist` after the existing method-evidence extensions are installed.

- Non-L4 stages delegate unchanged.
- Existing `L4_fisher` delta schema, topology, status transitions, and L5/L6 contracts remain unchanged.
- Existing legacy L4 evidence packs remain readable.
- New split-pipeline packs contain an explicit discovery linkage and are audited against the immutable discovery manifest.

## L4 Discovery contract

The provider returns metadata only. It must not fabricate full text or evidence extracts.

Required paper fields:

- DOI, PMID, or stable URL
- title, source database, year, journal
- actual source metadata response
- abstract when available
- open-access flag and candidate PDF URL
- `full_text_status`: `available_local`, `available_oa`, `metadata_only`, or `manual_required`
- relevance score from 0 to 10
- `selection_status`: `selected`, `rejected`, or `manual_review`
- selection reason

The persisted artifact is written under:

`09_Literature_Database/discovery_runs/<run_id>.json`

RLR performs deterministic identifier-first deduplication after provider output. Duplicate records remain auditable in the discovery artifact.

## L4.5 Evidence contract

The evidence request includes the frozen selected-paper catalog. The provider may resolve the selected records and registered local PDFs, but may not silently replace the selected corpus with a new broad search.

Existing strict gates remain:

- source payload is real retained source text;
- verbatim extract is a contiguous substring of the retained payload;
- primary-study and supplementary anchors come from Methods or a Methods subsection;
- Results, Discussion, abstracts, tables, and review text are navigation-only;
- required method components have an eligible accepted anchor or an explicit source-blocked candidate;
- review-search receipt is truthful and present.

The evidence artifact adds:

- `pipeline_stage: L4.5`
- `discovery_run_id`
- `discovery_manifest_path`
- `discovery_manifest_sha256`

## Failure semantics

- Discovery failure: no evidence invocation occurs.
- Discovery succeeds but no paper is selected: fail with an explicit selection error.
- L4.5 fails: the immutable discovery artifact remains for inspection and retry; no completed evidence pack is written.
- Individual metadata duplicates are merged deterministically rather than failing the batch.
- Evidence validation remains fail-closed.

## Future adapters

The stage boundary is intentionally transport-neutral. The current implementation uses the configured Academic Research runtime for both calls. A future `literature-search-mcp` adapter can replace only the L4 Discovery executor while Zotero and local-corpus adapters feed the same canonical discovery contract. L4.5 remains unchanged.
