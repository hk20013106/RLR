# L4 Evidence v2 Real Pilot — PARTIAL (2026-08-05)

## Scope

- Tested commit: `055ac472b3679bb157c562942a8e56998c11dc1e`
- Result: `PARTIAL`
- Focused regression: `85 passed`
- Full regression: `638 passed`
- L4A run: `bc41b5770e1cbd3bae63`
- L4B run: `C20260802150025462724_L4_a5e8a408ef8b`
- Formal L4B audit command: `PASS`

No L4C or L4.5 artifact was produced. PR #13 did not satisfy its merge conditions.

## A1 resolution

A1 was discovered and selected with these exact identifiers:

- DOI: `10.1186/s13059-014-0550-8`
- PMID: `25516281`
- PMCID: `PMC4302049`

L4B retrieved Europe PMC JATS XML successfully:

- HTTP status: `200`
- Retained payload size: `233,904` bytes
- Methods locator: `JATS sec[id=Sec18] title=Materials and methods`
- Contiguous Methods extract: `29,563` characters
- Accepted evidence cards: `3`

No source payload or verbatim Methods text is included in this report.

## Integrity defect 1: persisted payload bytes

The retrieval receipt/content hash was `f58d746d...af90dcf`, while the SHA-256 of the persisted file was `57e043b9...74036da`. The receipt recorded `233,850` bytes and the persisted file contained `233,904` bytes.

Normalizing the persisted file to LF produced the receipt hash. This isolates the defect to Windows text-mode newline conversion during source-payload persistence. A recorded content hash therefore did not identify the actual retained file bytes.

## Integrity defect 2: registry projection

The registry exposed canonical IDs `combat`, `deseq2`, and `sva`, but the runtime receipt recorded only `combat` as matched. DESeq2 and SVA were not matched through their already-linked exact source identifiers.

The persisted A1 asset also remained:

- `full_text_status=metadata_only`
- `full_text_locations=[]`

Its PMCID and open-access locations were added only by the L4B runtime compatibility projection. New L4A manifests should persist canonical registry identifiers and OA locations before the L4B handoff.

## Safety and conclusion

The run did not add papers outside the frozen corpus, retain credentials, access private-network URLs, or modify source project files, real data, source ledger, or older pilots.

The staged L4 responsibility split remains valid, but the two deterministic integrity boundaries above require correction and a new independent controlled real pilot. This report is not evidence that PR #13 is production-ready, and PR #13 must not be merged on this result.
