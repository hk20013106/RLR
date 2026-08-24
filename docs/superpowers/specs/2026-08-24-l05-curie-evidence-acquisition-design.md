# L0.5 Curie Evidence Acquisition Design

## Goal

Insert an auditable evidence-acquisition phase between the validated L0 ResearchSeed and L1 Einstein without adding a second status machine or allowing L1 to search ad hoc.

```text
L0 / ResearchSeed
      ↓
L0.5 / Curie
  QueryPlanner
      ↓
  DiscoveryTransport/v1
      ↓
  Selector
      ↓
  EvidenceRetrieval
      ↓
  EvidenceVerifier
      ↓
  CoverageJudge ── INSUFFICIENT → bounded QueryPlanner retry
      ↓ PASS
  EvidencePackBuilder
      ↓
    FREEZE
      ↓
L1 / Einstein
```

L0.5 is a first-class non-delta acquisition phase. It does not change candidate workflow status and therefore is not inserted into the status-bearing `DAG_NODES` sequence. This preserves the existing L0 → L1 transition while establishing an explicit authority boundary for literature evidence.

## Authority boundary

Curie owns evidence acquisition. Einstein owns hypothesis reasoning.

Curie may:

- derive explicit search plans from the canonical L0 ResearchSeed;
- call approved discovery transports;
- select candidate papers while preserving contradictory/negative evidence;
- retrieve source text through pluggable retrieval engines such as PaperQA2;
- verify source identity, locator and provenance;
- assess evidence coverage and request bounded additional discovery;
- build and freeze an immutable EvidencePack.

Einstein may:

- read a frozen EvidencePack;
- reason over the verified extracts in that pack;
- cite Evidence IDs present in the pack;
- emit an EvidenceGapRequest when the frozen state is insufficient.

Einstein must not:

- call PubMed, Europe PMC, OpenAlex, Crossref, Semantic Scholar or other discovery services;
- invoke PaperQA2 or another retrieval engine directly;
- add papers or extracts to the current frozen EvidencePack;
- silently repair a missing or invalid evidence artifact.

## Canonical contracts

### ResearchSeed

The existing `research_loop.research_seed` module remains the sole L0 → research semantic projection. L0.5 must bind to its `seed_sha256`; it must not copy candidate-frontmatter question/claim fields as an alternative authority.

### QueryPlan

Schema: `L05QueryPlan/v1`

Required fields:

- `schema_version`
- `candidate_id`
- `round_id`
- `seed_sha256`
- `plan_id`
- `round_index`
- `queries[]`

Each query requires:

- `query_id`
- `intent`
- `query`
- non-empty `providers[]`

`round_index` starts at 1 and is bounded by the CoverageJudge policy.

### DiscoveryTransport

Contract: `DiscoveryTransport/v1`

The transport is deterministic infrastructure, not a cognitive persona. Adapters may represent PubMed, Europe PMC, OpenAlex, Crossref, Semantic Scholar, MCP services, or future providers.

A transport handshake must identify:

- `schema_version = DiscoveryTransport/v1`
- `provider`
- `capabilities[]`

A discovery batch must bind every normalized record to:

- the originating `query_id`;
- provider identity;
- an immutable request/response receipt or hash;
- a stable paper identifier when available.

Discovery metadata is candidate metadata, not scientific evidence.

### EvidenceExtract

Schema: `L05EvidenceExtract/v1`

The extract, not the paper, is the minimal scientific evidence unit. Required fields:

- `evidence_id`
- `paper_id`
- `section`
- `text`
- `locator`
- `role` = `SUPPORTING | CONTRADICTORY | CONTEXT | METHOD`
- `verification_status` = `LOCATED`
- retrieval provenance

PaperQA2 is an optional implementation of EvidenceRetrieval. It may retrieve/rerank located evidence but is not the authority for final scientific interpretation.

### CoverageDecision

Schema: `L05CoverageDecision/v1`

Verdict is one of:

- `PASS`
- `INSUFFICIENT_RETRY`
- `INSUFFICIENT_STOP`

Retry is allowed only when `round_index < max_rounds`. The default and hard maximum for this design are 3 acquisition rounds.

### EvidenceGapRequest

Schema: `L05EvidenceGapRequest/v1`

A gap request is the only authorized path from downstream reasoning back into evidence acquisition. It binds to the exact frozen EvidencePack hash and contains explicit gaps/search directions. It never mutates the previous pack.

### EvidencePack

Schema: `L05EvidencePack/v1`

Required identity/provenance fields:

- `candidate_id`
- `round_id`
- `seed_sha256`
- `pack_id`
- integer `version >= 1`
- optional `parent_pack_sha256`
- query-plan receipts
- discovery receipts
- selected paper records
- verified evidence extracts
- coverage decision
- gaps

Before freeze the pack status is `READY_TO_FREEZE`. Freeze canonicalizes the payload, computes the content hash, writes a new immutable artifact, and persists `status = FROZEN`.

Artifact root:

`09_Literature_Database/evidence_packs/l05/<candidate_id>/`

A later acquisition round creates a new version and sets `parent_pack_sha256`; it never edits the earlier pack.

## Freeze invariant

The freeze boundary is the L0.5 → L1 authority boundary.

A pack is consumable by L1 only if all of the following hold at the boundary of use:

1. schema is `L05EvidencePack/v1`;
2. status is `FROZEN`;
3. the artifact path is inside the L0.5 evidence-pack root;
4. the file SHA-256 matches the manifest;
5. the internal content hash recomputes exactly;
6. candidate, round and ResearchSeed hash match the active L1 seed;
7. every evidence item has `verification_status = LOCATED` and a non-empty locator;
8. coverage verdict is `PASS`.

Missing or changed evidence fails closed.

## Versioning

`EP_<candidate>_R<round>_v<version>.json`

- v1: initial Curie acquisition.
- v2+: produced only after an explicit EvidenceGapRequest or a deliberately restarted L0.5 acquisition.
- every child records `parent_pack_sha256`.
- old packs are immutable and remain auditable.

The frozen pack hash, not a mutable “latest” pointer, is the binding consumed by L1.

## Migration / compatibility

The current `deep_research.py` L1 path remains an upstream acquisition implementation during this slice. It is not a second L1 evidence authority: L0.5 contracts/freeze are the new boundary to which future QueryPlanner, DiscoveryTransport and PaperQA2 adapters attach.

This change does not alter L4 or L8.5 and does not create L3.5.

## Implementation slice

This branch implements the core layer rather than live database adapters:

1. pure validators/contracts for QueryPlan, discovery handshake/batch, EvidenceExtract, CoverageDecision and EvidenceGapRequest;
2. deterministic EvidencePack construction, content hashing, immutable freeze/load, lineage versioning;
3. protocol interfaces for DiscoveryTransport and EvidenceRetriever;
4. tests proving fail-closed behavior, bounded coverage retry, immutable freeze, tamper detection and version lineage;
5. architecture documentation.

Live PubMed/Europe PMC/OpenAlex adapters and PaperQA2 integration are intentionally outside this slice; they plug into the new interfaces without changing the freeze or L1 authority contracts.
