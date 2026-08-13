# L4B Closed-Corpus Full-Text Retrieval Root Cause

## Scope and evidence

This report archives the read-only investigation of the real pilot at commit
`29fe8777183438c4ff15147094ed851270ad9391`.

Investigated runs:

- L4A: `c88d37b991d72d888bf8`
- L4B: `C20260802150025462724_L4_92337d45855a`
- candidate: `C20260802150025462724`

Primary evidence files from the pilot project:

- `09_Literature_Database/l4/discovery/manifests/C20260802150025462724_c88d37b991d72d888bf8.json`
- `09_Literature_Database/evidence_packs/runs/C20260802150025462724_L4_92337d45855a.json`
- `09_Literature_Database/evidence_packs/papers/053351df0f737c8a.json`
- `02_Agent_Notes/_pre_research/L4_research.md`

The investigation used only A1's existing DOI, PMID, PMCID, and registered
full-text locations. It did not search for or introduce another paper.

## Responsibilities of the staged L4 pipeline

The formal DAG still contains one L4 node. Internally it is divided into four
auditable stages:

- **L4A** is metadata-only discovery. It plans queries, discovers metadata,
  deduplicates and selects assets, and records full-text availability. It does
  not create source payloads, Methods extracts, or method anchors.
- **L4B** consumes the frozen L4A selection and constructs evidence. It is
  responsible for resolving allowed full text, retaining source payloads,
  extracting located Methods, validating anchors, and constructing method
  candidates. It must not search for or add papers outside the frozen catalog.
- **L4C** is the existing Fisher cognitive node. It consumes audited L4B
  evidence and produces the `L4_fisher` method-design delta.
- **L4.5** is deterministic and non-cognitive. It revalidates the exact L4A
  manifest, L4B evidence artifact, and L4C delta hash before writing the
  immutable method projection.

No independent full-text stage before L4 is required by this architecture;
full-text resolution belongs inside the L4B evidence-construction boundary.

Relevant documentation:

- `docs/DAG_TOPOLOGY.md`
- `docs/L4_METHOD_EVIDENCE.md`
- `docs/MAIN_AGENT_RUN.md`

## A1 was correctly discovered and frozen by L4A

The selected L4A asset A1 is:

- title: `Moderated estimation of fold change and dispersion for RNA-seq data with DESeq2`
- DOI: `10.1186/s13059-014-0550-8`
- PMID: `25516281`
- PMCID: `PMC4302049`
- PMC full text: `https://pmc.ncbi.nlm.nih.gov/articles/PMC4302049/`
- `full_text_status`: `available_oa`
- `role`: `method`
- `selection_status`: `selected`

The manifest also recorded the PubMed URL and the DOI URL as full-text
locations. The complete metadata response in L4A included the PMCID, DOI,
PMID, title, journal, authors, publication, and year.

The frozen catalog contained A1's DOI, PMID, PMCID/PMC location,
`full_text_locations`, `full_text_status`, role, and selection state. These
values were included in the final L4B prompt. The reconstructed prompt hash
matched the L4B receipt exactly:

```text
02dc9e976127ae6c321ff20b0146e257256b6196943d327188c33057aa4fe1ba
```

The L4B handoff also explicitly allowed full-text resolution through an alias
URL for the same selected DOI/PMID while prohibiting corpus expansion.

## What L4B returned for A1

The persisted A1 paper record retained the correct DOI, PMID, PubMed URL,
title, and `open_access=true`, but it did not contain:

- `source_payload`;
- `source_payload_path`;
- `content_hash`;
- a located Methods extract;
- an accepted method anchor.

The only retained A1 extract was the frozen-catalog Abstract and was treated as
navigation evidence, not a Methods anchor.

The MC1 candidate ended as:

```text
status = needs_user_source
method_anchor_ids = []
```

The L4B report explicitly stated that A1 had only the frozen catalog abstract
and that PMC full-text parsing had not been permitted.

## Persistence did not discard the payload

Persistence is not the first failure boundary.

`src/research_loop/method_evidence.py` validates an anchored extract against a
real retained payload, requiring at least 500 bytes and requiring the exact
extract to occur as a contiguous substring. For a non-empty payload it writes
the source file, `source_payload_path`, and `content_hash`.

`src/research_loop/method_review_navigation.py` preserves a non-empty payload
even when an extract is navigation-only. The frozen-corpus validator is called
before persistence by `src/research_loop/l4_provenance.py`.

Therefore, A1's empty `source_payload_path` and empty `content_hash` show that
the payload was absent before persistence. There is no evidence that
persistence, navigation splitting, or provenance validation removed a payload.

## Audit correctly failed closed

The first deterministic gate failure was the L4 evidence audit in
`src/research_loop/method_evidence.py`:

```text
L4 required component MC1 needs a user-supplied source: ...
```

The audit found no eligible candidate with an accepted Methods anchor for the
required MC1 component and correctly rejected the run. This was not an
overly-strict audit gate and the gate was not weakened.

## A1 full text is objectively available

Read-only probes restricted to A1's registered identifiers showed:

- PMC HTML: HTTP 200, approximately 304 KB, containing Methods text;
- Europe PMC `fullTextXML`: HTTP 200, approximately 234 KB, containing a
  `Materials and methods` section;
- DOI URL: HTTP 200, containing the article and Methods text;
- PubMed page: HTTP 200, containing the A1 record and linked article context.

The Europe PMC XML contained a `Materials and methods` section with tens of
thousands of bytes and content covering DESeq2 normalization and
variance-stabilizing transformation. A1 therefore has sufficient real source
material for MC1; it is not intrinsically a user-PDF-only source.

## Ephemeral Codex capability finding

The L4B command is constructed as:

```text
codex exec --ephemeral --ignore-user-config --output-schema ...
```

The child has no RLR PMC/Europe PMC retrieval adapter, no dedicated full-text
parser, and no Zotero connector path. `--ignore-user-config` also prevents the
interactive MCP fleet from being inherited. A probe using the same ephemeral
mode found only limited URL-opening behavior: PMC reached a browser-check
barrier, Europe PMC was rejected by URL-safety policy, and a direct PowerShell
fallback was rejected by the child execution policy.

The Zotero connector is a dependency gate; it is not wired into the L4B
full-text retrieval path.

The raw provider stdout from the real run was not persisted; only its hash was
recorded in the receipt. Thus the exact low-level HTTP attempt sequence from
the original provider invocation cannot be reconstructed. However, the
provider's persisted rejection reason, empty payload fields, and the matching
ephemeral capability probe establish that no usable A1 full-text retrieval or
Methods extraction completed.

## Root cause

The primary root cause is the combination of three conditions:

1. L4B has no closed-corpus deterministic full-text resolver. The frozen
   catalog is passed to the provider as prompt context, but there is no
   executable resolver that opens only those registered locations and returns
   a verified payload.
2. The ephemeral Codex child lacks a stable PMC/Europe PMC HTTP and parsing
   capability under the actual invocation flags.
3. The provider operationally interpreted “禁止 literature search” as also
   prohibiting reading the full text of an already-selected paper, despite the
   frozen handoff allowing same-DOI/PMID full-text resolution.

This explains why L4A found and selected A1 while L4B retained only its
Abstract navigation record and marked MC1 `needs_user_source`.

## Minimal repair direction

The minimal direction is an L4B-local deterministic resolver, not a new
pre-L4 stage:

1. Allow only `full_text_locations`, DOI, PMID, and PMCID already present in the
   frozen catalog.
2. Permit exact-asset retrieval but prohibit search, discovery, and new
   citations.
3. Fetch and parse the allowed PMC/Europe PMC representation.
4. Persist a retrieval receipt containing the exact URL, status, content hash,
   and section locator.
5. Return the real payload and contiguous Methods extract to the existing L4B
   validation path.
6. Keep the 500-byte, contiguous-text, Methods-section, provenance, and
   frozen-corpus gates unchanged.

The provider prompt should also explicitly distinguish “no literature search”
from “read the full text of a selected asset.” Prompt clarification alone is
not sufficient without an executable retrieval capability.

A local PDF is therefore only the current implementation's workaround. It is
not a provenance or scientific necessity for A1, whose OA full text is
available.

## Investigation boundaries and non-actions

This investigation did not:

- modify production code;
- modify tests or test logic;
- run L4C;
- run L4.5;
- modify the pilot project or pilot evidence;
- modify the source project;
- modify the source ledger;
- modify real data;
- rerun the real pilot;
- rewrite Git history.
