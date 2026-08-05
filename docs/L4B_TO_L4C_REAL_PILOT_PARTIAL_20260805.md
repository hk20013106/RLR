# Staged L4B to L4C real pilot — PARTIAL

Date: 2026-08-05

## Scope

A new independent Windows/Python 3.13 controlled real-data pilot was run against PR #13 head `f6fec3c7a2b19c8ef65156ef17f35ff70b80ec68`.

The source project, real data, source ledger, and ten earlier pilot directories remained unchanged. L4.5 and later nodes were not run.

## Result

- pilot: `D:\research_loop\RLR-realdata-pilot-pr13-rawbytes-20260805-180022`
- L4A run: `0c1a7d0a54aa7b3ba302`
- L4B run: `C20260802150025462724_L4_f5df9ed8e149`
- formal L4B audit: PASS
- L4C context assembly: blocked, exit code 3
- final disposition: `PARTIAL`

## L4B integrity passed

A1/DESeq2 raw-byte persistence closed correctly:

- retained XML: `245cdc585f4891b3.xml`
- persisted bytes: 233,850
- CRLF sequences: 0
- LF sequences: 54
- persisted, paper, selected receipt, extract, and accepted-card SHA-256:
  `f58d746de6bb7a446de7c5a49a0bf48861258ffe7ea8f25f7f8d31efaaf90dcf`
- no LF/CRLF normalization was used

Manifest closure, registry matching for DESeq2/ComBat/SVA, truthful evidence gaps, closed-corpus scope, and staged L4B responsibility boundaries also passed.

## L4C boundary failure

The staged L4B summary producer generated an `L4_research.md` whose Runtime digest contained only the bundle/run ID. The shared pre-research gate requires an identifier-bearing Runtime digest plus nonempty Query log, Tool receipt, and declared Source count. The first exposed error was:

```text
Runtime digest carries no DOI/PMID/URL identifier
```

The staged artifact also declared `EvidenceRunReceipt/v2`, while native v2.1 context identity expects `EvidenceRunReceipt/v1.1`.

## Corrective design

The generic pre-research gate remains unchanged. The staged L4B producer is aligned to the established interface:

- Runtime digest includes the exact run ID, persisted DOI/PMID/URL identifiers, compact accepted-card IDs, compact evidence-gap IDs, method IDs, and the L4B/L4C responsibility boundary;
- Query log is rendered from persisted artifact queries;
- Tool receipt is rendered from the persisted deterministic resolver receipt;
- Source count is declared from persisted paper references;
- the evidence run identity remains `EvidenceRunReceipt/v1.1`;
- the staged content marker remains `L4BEvidenceBundle/v2`.

A Windows/Python 3.13 integration test exercises the real transition:

```text
persist L4A inventory
→ run staged L4B
→ formal L4B audit PASS
→ cmd_assemble_context(L4, exact L4B run ID)
→ context contains run/card/gap/method IDs and responsibility boundary
```

## GitHub implementation validation

The integration test first reproduced the pilot failure on the unmodified producer:

```text
1 failed, 116 passed
Runtime digest carries no DOI/PMID/URL identifier
```

After the producer-contract correction:

- targeted L4 Windows/Python 3.13: `117 passed`;
- full regression Windows/Python 3.13: `647 passed`;
- repository full suite with coverage: `647 passed`, total coverage 70%;
- import check and CLI help: passed;
- `git diff --check`: passed.

These results verify the software boundary only. PR #13 must remain open until a new independent pilot passes L4A → L4B → L4C → L4.5 without manual artifact edits.
