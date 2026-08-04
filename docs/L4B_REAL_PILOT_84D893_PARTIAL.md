# L4B Real Pilot Validation — PARTIAL

## Scope

- Tested code commit: `84d89324d04411453bd65229165062b8a150de9d`
- Branch: `fix/l4b-closed-corpus-fulltext-resolver`
- Pilot: `D:\research_loop\RLR-realdata-pilot-84d893-20260804-231325`
- Candidate: `C20260802150025462724`
- Source project: `D:\research_loop\research_loop\.v09-realdata-fullcycle-20260802-150024`
- Source ledger: `D:\research_loop\research_loop\.v09-realdata-fullcycle-20260802-150024.sqlite`
- Python: `3.13.12`

This was a controlled real-data run. No L4C or L4.5 execution was attempted.

## Commands and exit codes

| Command or operation | Exit code | Result |
|---|---:|---|
| Zotero connector probe `http://127.0.0.1:23119/connector/ping` | 0 | HTTP 200; Zotero 9.0.6; `Zotero is running` |
| Project copy with Robocopy | 1 | Normal Robocopy success code; 131 files copied |
| SQLite Python `backup()` API | 0 | Pilot ledger created; integrity check `ok`; 16 tables |
| `research_loop_v04.py check-deps <pilot-project>` | 0 | Dependency and pitfall gates PASS |
| `research_loop_v04.py hypothesis-verify <pilot-project> --knowledge-store <pilot-ledger>` | 0 | Hypothesis ledger PASS |
| `research_loop_v04.py next-step <pilot-project> C20260802150025462724` | 0 | Returned `node=L4` |
| `research_loop_v04.py deep-research-run <pilot-project> C20260802150025462724 --node L4 --backend codex` | 3 | L4 evidence gate failed closed |
| `research_loop_v04.py audit-literature-evidence <pilot-project> C20260802150025462724 --node L4` | 3 | Audit FAIL; same required-source blocker |
| `git diff --check` | 0 | Passed |

The first attempts to run `hypothesis-verify` and `next-step` without the real
pilot ledger binding returned exit code 2. They were not used as pilot results;
the commands were rerun with the actual pilot ledger binding and passed.

## L4A

- Manifest: `project/09_Literature_Database/l4/discovery/manifests/C20260802150025462724_61286b6e734bdfa6a51f.json`
- L4A run ID: `61286b6e734bdfa6a51f`
- Manifest SHA-256: `f7e04dd94d72b4f183e1ebe081b2db0ea527a0d4b9b8f97dd3f554e5673d2910`
- Selected assets: 9; reserve assets: 1

The current L4A manifest does not contain the previously discussed A1 asset:

- DOI: `10.1186/s13059-014-0550-8`
- PMID: `25516281`
- PMCID: `PMC4302049`

A1 was present in the old pilot manifest, but not in this new L4A frozen
catalog. Consequently, this run did not create an A1 resolver contract or
attempt A1 retrieval.

## L4B

- L4B run ID: `C20260802150025462724_L4_ff34727dacc4`
- Evidence artifact: `project/09_Literature_Database/evidence_packs/runs/C20260802150025462724_L4_ff34727dacc4.json`
- Provider response: `project/09_Literature_Database/evidence_packs/provider_responses/C20260802150025462724_L4_ff34727dacc4.json`
- Audit: `FAIL` (exit code 3)

The first deterministic failure was the required `MC_IDENTIFIABILITY` evidence
gate:

```text
The selected ComBat paper (PMID 16632515) resolved only to PubMed
metadata/abstract HTML; selected SVA full text failed resolution.
A qualifying registered Methods payload is unavailable.
```

ComBat (PMID `16632515`) produced a 118,941-byte PubMed HTML payload with hash
`ea43f59cf84a10943c581bf2978424b137dfd6f84618a37e377c3f073d0afc0b`, but its
locator was only `HTML h1 title=Adjusting batch effects in microarray expression data using empirical Bayes methods`; it was not accepted as a qualifying Methods payload.

SVA (PMID `22257669`) failed the permitted retrieval plan: Europe PMC returned
404, PMC HTML did not yield an explicit Methods section, DOI access returned
403, and PubMed did not yield a qualifying Methods section.

Other frozen assets successfully resolved with non-empty payloads and located
Methods text:

| PMID | Payload bytes | Content SHA-256 | Methods locator |
|---|---:|---|---|
| 24485249 | 182630 | `e20ab776e62b9d8cae85d2e81c6280c53e088413b4b806b21758011f897ae63a` | `JATS sec[id=] title=Materials and methods` |
| 27884101 | 135131 | `f3a269e8e00afd6ef6d0971279d61f9013fc8b578164b398409cf48ec81bfee7` | `JATS sec[id=Sec6] title=Relationship to existing methods` |
| 29491377 | 122000 | `8bcca7ceee3e09f9d9eaf65ad79a75de530f391adeb3e7a27df038ee76c37168` | `JATS sec[id=Sec10] title=Methods` |
| 32730587 | 232002 | `381254b00690e9e15f175ec45ed27be85da791a991118e4316356fbab30e19fb` | `HTML h2 title=2 Materials and methods` |

No A1 payload, A1 `source_payload_path`, A1 content hash, A1 receipt, A1
Methods locator, or A1 accepted method anchor exists in this run.

## Safety checks

- No A1 PDF was manually imported.
- No L4C or L4.5 command was run.
- No code, test, source project, source ledger, or real-data file was modified.
- Source project baseline: 131 files; post-run hash comparison had no mismatches.
- Real data baseline: 5 files; post-run hash comparison had no mismatches.
- Source ledger SHA-256 remained `69d368bc692d7a983c26fd56b59406a211dc65c23d30903677f4cbcc01dd37ef`.
- Pilot ledger `PRAGMA integrity_check` returned `ok`.
- Receipt credential scan found no authorization, cookie, API-key, password,
  secret, or token-bearing values.
- The latest L4B run contained no paper outside the current L4A frozen catalog.
- The original failed pilot had no files updated after this run began.
- The code worktree remained clean at the tested commit.

## Conclusion

`PARTIAL`

The dependency gates and L4A persisted successfully, and the resolver produced
valid Methods payloads for several current frozen assets. L4B correctly failed
closed at `MC_IDENTIFIABILITY` because ComBat was only metadata/abstract HTML
and SVA lacked a qualifying full-text Methods payload. The current L4A catalog
did not contain A1, so the A1 resolver path was not realistically exercised.

This report does not claim that the real pilot is fixed and does not satisfy
the conditions for merging PR #12.
