# PaperQA2 ↔ RLR L0.5 Interface Audit

Status: DESIGN DECISION
Date: 2026-08-24
RLR branch: `codex/l1-kb-authority-single-source` (PR #38)
PaperQA2 upstream: `Future-House/paper-qa`
Audited upstream main: `57e89f7223b0960d5ee5ea048c69e3c47e088572` (2026-08-12)
License: Apache-2.0

## Decision

**Use PaperQA2 through a thin adapter, but do not make PaperQA2 the owner of L0.5 and do not replace the whole L0.5 research stage with `agent_query()`.**

PaperQA2 is a strong fit for the *evidence retrieval/extraction* part of L0.5 after candidate documents are available. It is not a drop-in replacement for RLR's complete literature-research boundary because its default agentic paper search operates on a pre-built/local index rather than performing general internet-wide literature acquisition, and its full agent also performs answer synthesis that would overlap Einstein/L1 authority.

The target architecture is therefore:

```text
L0 / Linnaeus
  |
  v
canonical ResearchSeed
  |
  v
L0.5 / Curie  (RLR remains the stage owner)
  |
  +--> literature discovery/acquisition backend
  |      - existing Academic Research first
  |      - future alternative: Semantic Scholar/OpenAlex/OpenScholar where justified
  |
  +--> PaperQA2 evidence backend
  |      - parse acquired PDFs/full text
  |      - retrieve/rank relevant chunks
  |      - contextual evidence summarization
  |      - page-located source grounding
  |
  v
RLR EvidencePack normalization + validation
  |
  v
immutable ResearchSeed -> EvidenceRun binding
  |
  v
L1 / Einstein
  - no independent search
  - reasons only over frozen evidence
```

PaperQA2 is a replaceable implementation detail beneath the L0.5 Curie boundary. It must never become an authority over ResearchSeed identity, evidence freezing, candidate status, hypothesis identity, or L1 reasoning.

## Why PaperQA2 is worth reusing

PaperQA2 already implements mature scientific-document machinery that RLR should not reproduce:

1. PDF/text/Office/code parsing, including page-aware PDF chunking.
2. Content hashes and structured document metadata.
3. DOI/metadata enrichment through mature clients including Crossref and Semantic Scholar, with OpenAlex and Unpaywall clients also available.
4. Dense, sparse and hybrid retrieval; MMR selection; optional Qdrant for larger stores.
5. LLM contextual summarization and relevance scoring of retrieved chunks.
6. Agentic query refinement when that behavior is desired.
7. Grounded citation formatting from the selected contexts.
8. Configurable LiteLLM-backed model and embedding providers.
9. A tested Python library API; Python >=3.11; Apache-2.0.

The upstream `Context` model preserves both the contextual summary and the originating `Text` object. For PDF content, chunk names are page-located (`<doc> pages X-Y`), while the original text chunk and source `DocDetails` remain attached before user-display filtering. This is sufficient for an RLR adapter to create source-located evidence without reimplementing embedding, MMR, reranking, summarization, PDF chunking, or citation handling.

## Why `agent_query()` must NOT be the L0.5 API

PaperQA2's full agent workflow contains the tools:

```text
paper_search -> gather_evidence -> gen_answer -> complete
```

The `gen_answer` step performs synthesis. In RLR, synthesis of scientific hypotheses belongs downstream to Einstein/L1. Allowing a PaperQA2 agent to answer the scientific question inside L0.5 would collapse the Curie/Einstein authority boundary.

For RLR, the preferred PaperQA2 integration point is the lower-level evidence API:

```python
Docs.aget_evidence(...)
```

not:

```python
agent_query(...)
Docs.aquery(...)
```

`Docs.aget_evidence()` retrieves text chunks, creates scored `Context` objects, and returns a `PQASession` containing evidence contexts without requiring final answer generation. This matches Curie's role much more closely.

## Important limitation: PaperQA2 is not a complete online discovery backend

PaperQA2's documented `paper_search` tool queries the configured PaperQA search index. The normal library workflow expects a paper directory/local index. Its own documentation treats acquisition of external papers as a separate problem and provides examples for OpenReview and Zotero, while pointing to external tooling for broader paper scraping.

Therefore this would be architecturally incorrect:

```text
ResearchSeed -> PaperQA2 -> complete L0.5 EvidencePack
```

unless RLR has already supplied an adequate source corpus.

The correct decomposition is:

```text
ResearchSeed
  -> Discovery / acquisition
  -> Corpus snapshot
  -> PaperQA2 evidence retrieval
  -> RLR EvidencePack
```

For PR #38, the existing Academic Research runtime should remain the default online-discovery implementation until a better mature discovery backend is proven. PaperQA2 can first be introduced as an optional evidence backend for acquired/registered literature.

## RLR contract mapping

### Input

RLR canonical input:

```text
ResearchSeed
- candidate_id
- round_id
- round_type
- scientific_question
- hypothesis_seed
- l0_contract_path
- l0_contract_sha256
- seed_sha256
```

PaperQA2 requires a query plus `Settings` and a `Docs`/index corpus. The adapter must therefore receive the canonical ResearchSeed from RLR and derive the evidence query inside the Curie boundary. PaperQA2 must never load candidate-frontmatter question/claim as an alternative authority.

### Evidence passages

PaperQA2 `Context` provides:

```text
Context
- id
- context                # LLM contextual summary
- question
- score
- text.text              # original retrieved chunk before display filtering
- text.name              # page/chunk locator
- text.doc               # source document metadata
```

This maps naturally to an RLR evidence extract:

```text
EvidenceExtract
- text             <- context.text.text (canonical quoted/source text)
- summary          <- context.context (derived contextual summary; optional)
- locator          <- context.text.name / parser page metadata
- relevance_score  <- context.score
- source identity  <- context.text.doc
```

RLR should distinguish **source text** from **PaperQA2's derived contextual summary**. The summary must never be persisted as though it were a verbatim extract.

### Source identity and metadata

PaperQA2 `DocDetails` includes DOI, URL, title, year, journal, PDF URL, citation count, retraction state, license, file location, content hash and an `other` metadata dictionary. The Semantic Scholar adapter also records its client source and retained provider fields.

This is sufficient for source identity and most metadata normalization, but it is **not guaranteed to preserve the exact original HTTP metadata response byte-for-byte**. RLR currently treats retrieval provenance more strictly than PaperQA2's public answer/session contract.

Therefore the RLR adapter must keep its own immutable retrieval receipt. It must not pretend that a normalized `DocDetails` serialization is an untouched database response.

### Query log

`PQASession.tool_history` records tool names but not a complete immutable record of every tool argument. If RLR uses `Docs.aget_evidence()` directly, this is simpler: RLR owns the exact evidence query and records it before calling PaperQA2.

If PaperQA2 agentic search is ever enabled, RLR must capture full tool calls through PaperQA2 callbacks/action hooks and persist their arguments. A tool-name-only history is insufficient for the RLR query-log contract.

### Runtime receipt

RLR remains responsible for:

```text
- backend identity
- PaperQA2 package version
- audited/pinned upstream commit or exact release
- model + embedding configuration hash
- ResearchSeed SHA256
- corpus manifest SHA256
- actual query log
- execution start/end/status
- output artifact hashes
```

PaperQA2's session `config_md5`, document `content_hash`, token/cost fields and structured contexts are useful inputs to this receipt but do not replace it.

## Required change to the current RLR evidence gate

PR #38 currently requires L0.5 to contain source-located evidence labelled specifically as `Results`, `Discussion`, and `Conclusion`.

PaperQA2's robust native locator is page/chunk provenance, not guaranteed IMRaD section classification. Requiring those three literal section classes is stronger than necessary for the scientific invariant and makes the integration depend on fragile heading recognition.

The invariant RLR actually needs is:

> Every evidence assertion consumed downstream must resolve to an identifiable source and an immutable source-located passage/anchor.

Recommended contract:

```text
required:
- source identity (DOI/PMID/stable URL or registered local source)
- immutable source/corpus identity
- exact located passage or resolvable anchor
- locator (page/range/section/paragraph/structured anchor)
- extraction method
- verification status

optional/derived:
- section label (Results/Discussion/etc.)
- PaperQA2 contextual summary
- relevance score
```

For studies with standard headings, a section classifier may enrich the evidence record, but `Results/Discussion/Conclusion` should not be the universal provenance gate. This change strengthens generality without weakening traceability.

## PaperQA2 versioning policy

PaperQA2 moved from SemVer to CalVer in December 2025 and explicitly reduces backwards-compatibility guarantees across releases. RLR must therefore not depend on an unbounded `paper-qa>=5` range for reproducible research.

When integration is implemented:

1. select and test an exact PaperQA2 release;
2. pin that release in the optional dependency set;
3. record both package version and upstream Git commit in the EvidenceRun receipt;
4. upgrade only through an explicit compatibility test.

The audited upstream head for this design decision is:

```text
57e89f7223b0960d5ee5ea048c69e3c47e088572
```

This audit does **not** imply that RLR should pin to that development head in production. A tagged release should be selected during the implementation spike.

## Alternatives reviewed

### OpenScholar

OpenScholar is highly relevant for *global scientific retrieval*. Its published system searches a 45-million-paper open corpus and uses retrieval, reranking and self-feedback. Its 2025 Nature paper reports stronger correctness than PaperQA2 on ScholarQABench.

However, the released local datastore is very large (200+ million embeddings), and its repository warns of substantial CPU-memory requirements. It is therefore not the default RLR backend for PR #38. It remains a strong future discovery/retrieval candidate if a hosted/smaller supported interface becomes practical.

### ScientistOne / Science One Chain-of-Evidence

The 2026 ScientistOne / Science One work is highly relevant to RLR's *architecture*, not currently a mature drop-in library for L0.5. Its Chain-of-Evidence principle requires every claim to carry a traceable evidence chain, and its architecture grounds literature before downstream discovery and verifies claims against declared evidence.

This strongly supports the RLR design decision to keep evidence freezing and provenance as first-class architecture rather than outsourcing them to the retrieval model.

The publicly linked GitHub repository currently exposes generated papers/solver artifacts rather than a reusable complete framework implementation. Therefore RLR should borrow the CoE invariants and audit ideas, not copy nonexistent/unreleased framework code.

## Minimal adapter design

Do not create another L0.5 installer/wrapper layer. The canonical integration should be a normal backend implementation behind one stable interface.

Suggested conceptual API:

```python
class EvidenceRetrievalBackend(Protocol):
    def retrieve(
        self,
        *,
        seed: ResearchSeed,
        corpus: FrozenLiteratureCorpus,
        runtime: ResearchRuntime,
    ) -> RetrievedEvidence:
        ...
```

PaperQA2 implementation responsibilities:

```text
PaperQA2EvidenceBackend
- receive an already-authorized corpus
- build/reuse PaperQA2 Docs/index
- call Docs.aget_evidence only
- return structured contexts + source metadata + backend receipt data
- never persist canonical RLR state directly
- never freeze/replace ResearchSeed binding
- never generate hypotheses or candidate decisions
```

RLR responsibilities after the backend returns:

```text
Curie/L0.5 canonical service
- validate source identities
- preserve/copy source artifacts when authorized
- normalize Context -> EvidenceExtract
- write EvidencePack
- hash all artifacts
- write EvidenceRunReceipt
- freeze ResearchSeed -> exact EvidenceRun once
- expose only frozen evidence to L1
```

## Recommended implementation order for PR #38

1. **Finish current PR #38 authority cleanup first.** One owner for topology, ResearchSeed binding and provider execution; remove migration-time L0.5 wrappers where canonical modules already own the behavior.
2. **Generalize the evidence-backend receipt contract.** `audit_evidence_pack()` must validate capabilities/provenance, not hard-code that only `academic-research-suite` or `academic-research-skills` can ever produce valid evidence.
3. **Correct the locator invariant.** Replace the universal Results/Discussion/Conclusion requirement with resolvable source-located passages; keep section labels as enrichment where available.
4. **Add an optional PaperQA2 dependency and adapter.** Do not fork PaperQA2. Pin one tested tagged release.
5. **Use a fixture corpus for RED -> GREEN.** Verify DOI/source identity, page locator, raw source text vs summary separation, query/receipt capture, corpus hash and exact ResearchSeed binding.
6. **Run a real small-corpus pilot.** Compare the same ResearchSeed through the current Academic Research evidence path and the PaperQA2 evidence path. The test is provenance completeness and retrieval quality, not identical wording.
7. **Only then decide whether PaperQA2 becomes the preferred evidence backend.** It should not become the default merely because it is integrated.

## Final verdict

```text
Directly replace all of L0.5 with PaperQA2?        NO
Fork/modify PaperQA2 now?                          NO
Reuse PaperQA2 mature retrieval/evidence code?     YES
Integration form                                   THIN ADAPTER
Preferred API                                      Docs.aget_evidence()
Use PaperQA2 final answer generation in L0.5?      NO
RLR keeps ResearchSeed/evidence-freeze authority?  YES
Keep current online discovery initially?           YES
Revisit current section-specific evidence gate?    YES
```

This preserves the central RLR principle: **reuse mature scientific retrieval code, while RLR owns only the scientific-state, authority, provenance and evidence-binding semantics that define the research loop.**
