# Staged L4B byte-integrity pilot — PARTIAL

Date: 2026-08-05

## Scope

A new independent Windows/Python 3.13 controlled real-data pilot was run against PR #13 head `2fc51c827188fb89a310379e7943f1298b57a36d`.

The source project, real data, source ledger, and all earlier pilot directories remained unchanged. L4C/L4.5 and later nodes were not run.

## Result

- L4A run: `aa25185f02ed01a137a5`
- L4B run: `C20260802150025462724_L4_c597233d8e96`
- formal L4B audit: PASS
- final disposition: `PARTIAL`

A1/DESeq2 manifest closure, registry matching, Methods extraction, closed-corpus scope, and accepted evidence cards were correct.

The retained A1 XML nevertheless failed the strict byte-integrity gate:

- persisted file: 233,904 bytes
- retrieval receipt: 233,850 bytes
- persisted SHA-256: `57e043b994dc3aa97861ef8cc0935e906aebbf4fd0754ea213c479d7174036da`
- receipt/paper/extract/card SHA-256: `f58d746de6bb7a446de7c5a49a0bf48861258ffe7ea8f25f7f8d31efaaf90dcf`

The persisted XML contained 54 CRLF sequences. Diagnostic LF normalization reproduced the receipt byte count and hash, but normalization was not accepted as a pass condition.

## Root cause and follow-up fix

The staged-v2 production path in `l4_evidence_bundle.run_l4b_evidence()` still wrote the retained source with `Path.write_text()`. Earlier fixes covered canonical/legacy `deep_research.persist_run()` but did not cover this staged L4B implementation.

The follow-up change on PR #13 now:

- retains the raw HTTP response bytes in the deterministic resolver result;
- writes those exact bytes with `Path.write_bytes()` in staged L4B;
- derives paper, extract, and card hashes from those exact bytes;
- preserves raw bytes in the resolver work-directory handoff;
- makes `audit_bundle()` verify the actual persisted bytes against paper/card/extract hashes and the selected receipt hash and byte count;
- adds a Windows regression that reproduced the CRLF failure before the fix.

## Software validation after the fix

Validated implementation head: `8a7087307a3dd03b1ba8e1194ba0f85d08d9296f`.

Windows/Python 3.13 only:

- targeted L4 tests: `116 passed`;
- full regression suite: `646 passed`;
- repository full suite with coverage: `646 passed`, total coverage 70%;
- import check and CLI help: passed;
- `git diff --check`: passed.

These checks establish software regression safety and reproduce the Windows newline boundary. They do not replace a new independent real-data pilot.

PR #13 must remain unmerged until a current-head pilot confirms, without LF/CRLF normalization:

```text
SHA256(persisted source bytes)
== paper content_hash
== selected retrieval receipt content_hash
== every relevant extract source_hash
== every relevant accepted-card content_hash
```

and:

```text
persisted source byte count
== selected retrieval receipt byte_length
```
