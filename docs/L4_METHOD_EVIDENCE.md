# L4 Methods Evidence and User PDF Workflow

The formal DAG still contains one L4 node and retains the `L4_fisher` storage
key. Internally, new staged runs use five separate responsibilities:

```text
L4A: method inventory and exact source metadata
→ L4B: deterministic exact-source resolution and Methods extraction
→ L4C: Fisher method design (`L4_fisher` delta)
→ L4.5: deterministic required-path and lineage validation
→ L5/L6: critique, final method selection, and frozen execution plan
→ L7: execute only the approved plan
```

L4A/L4B/L4C/L4.5 are internal stages, not additional formal DAG nodes. The
formal node numbering and authority model are unchanged.

## Responsibility boundary

### L4A — method inventory

L4A uses the configured Academic Research Skills runtime for metadata-only
work. It persists the existing immutable `L4ADiscoveryManifest/v1` plus the
additive marker `inventory_schema: L4MethodInventory/v2` and a
`method_inventory` array.

The inventory identifies explicit methods and carries forward exact DOI, PMID,
PMCID, stable URL, or matching asset IDs already present in authorized context.
Inventory-referenced reserve assets are promoted into the exact-source corpus.
An exact source hint not already represented by an asset is materialized as a
selected identifier-bearing asset. Therefore, a known method source does not
disappear merely because ordinary literature ranking changes between runs.

L4A does not emit source payloads, verbatim extracts, method components,
candidate eligibility, `required` flags, or an analysis plan.

### L4B — deterministic evidence service

L4B calls no cognitive provider. It consumes only the exact sources represented
by the L4A method inventory and candidate-scoped registered local sources. It
may follow deterministic aliases for those exact DOI/PMID/PMCID records, but it
must not search for or substitute other papers.

For each exact source L4B records:

- the exact-source retrieval contract;
- every attempted route and truthful failure reason;
- retained source payload when resolved;
- payload size and SHA-256;
- a contiguous Methods extract of at least 500 bytes when available;
- section and locator;
- retrieval receipt;
- an accepted evidence card or an unresolved evidence gap.

The staged artifact is marked `evidence_bundle_schema: L4BEvidenceBundle/v2`.
It contains `method_inventory`, `evidence_cards`, `evidence_gaps`, and
`full_text_retrieval`. It must not contain method components, method
candidates, eligibility decisions, alternatives, or `required` obligations.

An inaccessible source, metadata/abstract-only page, missing explicit Methods
section, or insufficient extract becomes an evidence gap. Such a truthful gap
does not by itself invalidate L4B. L4B still fails closed for identity
substitution, unregistered search, unsafe paths, malformed receipts, tampered
payloads, false extract claims, or broken immutable linkage.

### L4C — Fisher method design

Fisher receives the method inventory, accepted evidence cards, explicit
evidence gaps, the selected hypothesis, and authorized project context. Fisher
then defines components and candidates.

New staged candidates add:

- `execution_required`: whether this candidate is an implementation path needed
  to cover a required component;
- `evidence_card_ids`: accepted L4B cards supporting the candidate;
- `evidence_gap_ids`: unresolved source gaps relevant to the candidate.

Only an `eligible` candidate with `execution_required: true` must reference an
accepted evidence card. Optional alternatives may remain visible without a
strong card when their gaps and limitations are explicit. An evidence gap is
never an anchor.

Historical native-v2.1 candidates remain readable under their original
`method_anchor_ids` rules.

### L4.5 — required-path and lineage audit

L4.5 calls no model. It verifies:

1. the persisted L4A manifest and hash;
2. the L4B evidence bundle and its artifact manifest;
3. the persisted L4C delta and hash;
4. the exact `deep_research_run_id` binding between L4C and L4B;
5. every required component has an eligible `execution_required` candidate;
6. every such candidate references an accepted L4B evidence card;
7. no unresolved gap is passed off as accepted evidence.

Optional alternatives do not block L4.5 solely because their strong evidence
is incomplete. L6 remains the final method-selection authority, and L7 remains
the only execution authority.

## Source integrity

Accepted evidence retains the existing strict guarantees:

- exact source identity;
- closed-corpus resolution;
- public-network and credential safety;
- project-bound local paths;
- retained payload and content hash;
- at least 500 bytes of substantive text;
- a contiguous source extract;
- Methods or a Methods subsection where required;
- a non-empty locator and immutable receipt.

Reviews, abstracts, table mentions, placeholders, and unlocated summaries are
not accepted method evidence.

## Registering a user-supplied PDF

Use a legally obtained local PDF when an exact necessary source cannot be
retrieved:

```powershell
python scripts/import_literature_pdf.py <project_dir> <candidate_id> `
  --file "D:\papers\paper.pdf" `
  [--doi "10.xxxx/xxxx" | --pmid "12345678" | --url "https://..."]
```

Registration verifies candidate ownership, PDF magic bytes, byte size, and
SHA-256 and stores the source under:

```text
09_Literature_Database/user_sources/<candidate_id>/<sha256-prefix>_<filename>.pdf
```

Registration alone is not evidence. A later deterministic evidence run must
retain extracted source text, locate a substantive contiguous Methods passage,
and emit an accepted evidence card bound to the registered source identity and
hash. Scanned image-only, encrypted, damaged, or incomplete PDFs remain
unresolved evidence gaps. OCR is outside the current RLR scope.

## Artifacts

Stable staged artifacts include:

```text
09_Literature_Database/l4/discovery/manifests/          L4A manifests
09_Literature_Database/evidence_packs/runs/             L4B bundles and summaries
09_Literature_Database/evidence_packs/papers/           paper records
09_Literature_Database/evidence_packs/sources/          retained payloads
09_Literature_Database/evidence_packs/retrieval_receipts/ retrieval receipts
08_Audit/l4_method_commits/                             L4.5 commits
```

Raw source excerpts remain in the evidence store and are referenced by card or
anchor ID instead of being copied wholesale into Fisher, L6, or execution
artifacts.

## Compatibility

Historical staged artifacts continue to use their original semantics and
readers. New staged runs are identified by `L4MethodInventory/v2` and
`L4BEvidenceBundle/v2`. Public CLI spellings, formal DAG nodes, candidate
identity, ledger rules, and artifact roots remain unchanged.
