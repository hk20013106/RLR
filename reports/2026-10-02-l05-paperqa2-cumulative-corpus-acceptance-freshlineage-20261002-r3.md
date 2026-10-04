# Task 11 acceptance — fresh lineage r3

Date: 2026-10-02

`REAL_E2E=BLOCKED`

Blocker classification: `MODEL CONTRACT FAILURE / L0 HOST OUTPUT CONTRACT MISMATCH`

Stop stage: current-host L0 Linnaeus cognition, before `host-submit`

## Fresh lineage

Created a new native project through the public RLR lifecycle, bound to the authorized shared hypothesis store, copied the currently approved non-secret runtime bytes, ran public preflight, then created one new initial candidate from the same four-species scientific question, hypothesis, and source files.

- Project: `D:\research_loop\e2e_phase2c_20260925_clean_02\four-species-task11-freshlineage-20261002-r3`
- Project ID: `PROJECT:ff8be38e-4a9f-511f-8a64-d35c9f250a51`
- Shared store: `D:\research_loop\e2e_phase2c_20260925_clean_02\hypothesis.sqlite`
- Candidate: `C20261002183251113784`
- Round: initial / 1
- Approved source runtime SHA-256: `8aae5d38a60ae7fc67fc0a8fbe93762efd0d24137cb25d69dd7be3e9cd332f5d`
- New public preflight receipt SHA-256: `6e713bc2de6b7e8e0a2eaf7681d7b970fe871179cadc7be1a19617e86e9d1682`
- Candidate frontmatter SHA-256: `5f0592fbd04e3d82c3842e23f558e558806919027657fc01e6e54f9b31f7250b`
- New L0 input-contract SHA-256: `3fc7e29131d781429e2bfb1f2d38b9d75b1a6f82727a7c2c8f849c112d562375`

Public preflight exited 0 with `PASS WITH WARNINGS`. The only warning was that the official PubMed MCP Python SDK is unavailable for a future PubMed MCP consumer; it was readiness-only. The authoritative `validate_project_ready(project, candidate_path, expected_backend="codex")` returned `PASS` / `PROJECT_READY`; the candidate's receipt pin exactly equals the current receipt SHA-256. The PaperQA2 worker configuration was validated by preflight. `08_Audit/l05_acquisition` contains no files, and `01_Candidates` contains only this candidate's Markdown and L0 input contract.

The source files were re-materialized from `D:\R-HK\yigene\newdata_260727`; no old candidate output, receipt, receipt pin, or acquisition checkpoint was copied. Current source-input SHA-256 values:

- `FOUR_SPECIES_107SAMPLE_DATA_HANDOFF_CN.md` — `da4323e29f6257320cf7e3c4729b3e7a9d9f2ed37b6eda3e1c7fd1de3c1d98b4`
- `four_species_gene_ids_lengths.tsv` — `223a0129b2f6fe4b916eae924d54de02c8af63db57f97ddc229d9cbf18c1dbc4`
- `four_species_length_scaled_counts.tsv` — `2a15a1ab23eca5d8a98b9101db43c2a57332fcb51f8c5b5911db35ebcb33b9d1`
- `four_species_raw_counts.tsv` — `0609c940d846ca353329ed269afb6b89957353a959a5b3d51b749aba8c31df64`
- `sample107_260716_with_AV_group.csv` — `5aa35ffdb3e61c57660b915e77789cf1870b45160e1b3944c3fbf5c6a816fb45`

The first runtime-copy command used an unsupported PowerShell `Copy-Item -NoNewline` parameter and failed before copying any bytes. A normal file copy then succeeded; the destination SHA-256 matches the approved source. No second project was created.

## Task 11 host protocol

The existing acceptance driver invoked the public `host-next` owner and returned `NEEDS_HOST` with `host_provider_calls=0`:

- Request ID: `baee5f5a9744eeb5b52d453a90a2a120ee4a11ea3d6f82a9a604068a59a36070`
- Request SHA-256: `e09f9226bb1e215973db11196d2d7433024486e49ac9d8f3d68d05882547b2f4`
- Context-manifest SHA-256: `6a89cf367d98819e661422574c3340679077711a06f325f8272e9a4f0bbb23ad`
- Rendered-context SHA-256: `0f30b1aa95e2e008964424fa6e93b306a6932cdd77e82cd493873e68e5e782ea`
- Hypothesis store ID in the request: `STORE:5e3439e4-5a30-5711-9615-52ef2348cb1f`

The rendered L0 context says `tools_policy=no-fs` and allows only `candidate_frontmatter`. It asks Linnaeus to verify the authoritative input declaration and current-round source files, freeze a `CurrentRoundDataBinding`, and fill `skill_use_plan`. The supplied context includes the five source paths but no source hashes or file contents. The output contract identifies an L0 delta with only `schema_version` and `candidate_id` fields, requires only `schema_version`, and defines no shape for the binding or skill plan. A response claiming those checks succeeded would be unsupported; a schema-minimal response would not fulfill the stated L0 action. Therefore no response artifact was created or submitted, and no alternate model/provider was invoked.

This is a host/model-contract blocker, not a PaperQA2 or Europe PMC failure. No Europe PMC acquisition, PaperQA2 corpus/summary call, source verification, semantic admission, coverage, focus/replan, or later attempt ran. These stages are `NOT ATTEMPTED`; live corpus size, `evidence_k`, latency, worker retries/recovery, and scientific outcomes are `NOT VERIFIED`.

## Authorization and preservation

- `DEEPSEEK_API_KEY` was not read or checked because no PaperQA2 worker was reached; no credential was persisted.
- The consumed candidate `C20260925211546881294`, its project receipt and receipt pin, and the r2 lineage were not passed to any mutating command. No old readiness authority or acquisition checkpoint was copied.
- Task 1–10 were not rerun. No production code, validator, dependency, or old project artifact was modified. No commit, push, or merge was performed.
