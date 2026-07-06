# v0.6 Divergence-Contract Hardening — Design Spec

- **Date:** 2026-07-06
- **Branch:** v0.6 (do NOT start v0.7)
- **Target:** `research_loop_v04.py` + new `ars_card_adapter.py` + test suite
- **Status:** Approved (brainstorming) — pending implementation plan
- **Origin:** meta-audit `Yigene_Enhancer_v04/08_Audit/meta_audit_divergence_information_flow_20260706020000.md` (verdict PARTIAL: convergent, not divergent)

## Problem

The two-loop run was convergent, not divergent. Context moved between loops through **agent memory**, not **system state**. Concrete structural causes:

1. `DELTA_SCHEMAS["L0_linnaeus"]` (research_loop_v04.py:440-443) has no cross-loop memory field.
2. `_pre_research_file` (research_loop_v04.py:826) is project-scoped + node-keyed → stale digests reused across candidates (L1/L4 artifacts predated candidate 2 by ~4.5 h).
3. `cmd_new_candidate` (research_loop_v04.py:2855) accepts no memory input.
4. `cmd_aggregate_report` (research_loop_v04.py:3829) writes fixed `FINAL_REPORT.md` → silent overwrite of a prior candidate's report.
5. No branch / method / modality traceability anywhere (L6 `scripts` are bare strings at :472; L7 `scripts_run` has no branch/method link at :475).

10 known failures (from audit) all reduce to: **no structured loop memory + no traceability manifests + no divergence gate.**

## Locked decisions

- **Q1 gate hardness:** Hard-fail + `loop_type`. `new-candidate --from-memory` requires `--loop-type {divergent|correction|data-acquisition}`. Divergence + branch gates hard-fail for `divergent`. `correction`/`data-acquisition` bypass the query-family requirement but still emit branch + modality ledgers and still pass L6/L7/L10 traceability gates.
- **Q2 ARS depth:** ARS agents as the L1/L4 engine. L1 → `synthesis_agent` (cross-source gap/divergence). L4 → `research_architect_agent` (method blueprint). **Mandatory adapter** `ars_card_adapter.py` converts ARS output → compact paper/method card JSON (strips APA prose). `ars-citation-check` validates DOI/PMID before card commit. Adapter is the token firewall; ARS output never reaches deltas/context.
- **Q3 divergence proof:** `divergence.min_new_query_families = 2`. L1 requires ≥2 genuinely-new query families (vs `query_families.json` cache) aligned to `required_new_search_directions`, AND every prior `unexplored_branch` gets explicit status in the branch ledger.

## Invariants (enforceable, not vibes)

1. No delta carries full paper/method text — card IDs + hashes only.
2. Every `--from-memory` candidate's L0 delta carries `prior_loop_memory` with `memory_hash` matching the seed JSON.
3. Every L7 output maps to an L6 script → `branch_id` → (`method_card_id` | named critique ref).
4. `next_loop_memory.json` is a deterministic function of deltas + ledgers. Regenerable. No hidden state.
5. `aggregate-report` never silently clobbers another candidate's report.
6. Gates fail-closed for divergent loops, no-op for legacy/first loops. All new schema fields optional; hard-fail only when `--from-memory`. C1/C2 artifacts still validate.
7. Divergence proven mechanically: ≥2 new query families + all prior `unexplored_branches` statused.

## Schema changes (`DELTA_SCHEMAS`, all new fields optional)

### A/N. `next_loop_memory` seed (Markdown + JSON)
New `08_Audit/loop_memory/<cand>_next_loop_memory.json` + `.md` human twin. Fields:
`source_candidate_id, terminal_node, terminal_decision, original_question, previous_hypothesis, final_reason, next_round_hypothesis, required_new_search_directions[], evidence_kept[], evidence_dropped[], explored_branches[], unexplored_branches[{id,why,data_available,data_path}], data_modalities_used[], data_modalities_available_unused[], paper_card_ids[], method_card_ids[], hashes{}`.
New subcommand `emit-loop-memory --cand-id` assembles from L1/L8/L9/L10b deltas + ledgers. Invents nothing.

### B. `L0_linnaeus += prior_loop_memory{}`
`source_candidate_id, loaded_from, memory_hash, previous_hypothesis, final_decision, next_round_hypothesis, required_new_search_directions[], evidence_kept[], evidence_dropped[], unexplored_branches[], data_modalities_available_unused[]`.

### E. Paper cards
`09_Literature_Database/paper_cards/<id>.json`: `{id, pmid, doi, url, title, year, journal, one_line, claims_used[], query_family_id, retrieved_at, hash}`. `L8.5_curie.papers[]` drops inlined `abstract`, references card IDs.

### F. Method cards
`09_Literature_Database/method_cards/<id>.json`: `{id, source_paper_card_id, method_name, measurement_type, data_modality, key_parameters, applicability, extracted_from:"full_text|abstract", full_text_fetched, extracted_at}`. `L4_fisher.scripts_needed[] += grounded_in_method_card_ids[]`.

### H. L6 scripts become objects
`analysis_plan.scripts[]`: `{name, purpose, grounding:{type:"method_card|internal_critique|prior_reuse", method_card_ids?[], critique_delta_ref?, reused_from?}, branch_id, data_modality}`.

### I. L7 traceability
`scripts_run[] += branch_id, method_card_ids[], grounded_by, input_hashes[], output_hashes[]`; + manifest `04_Analysis_Outputs/_exec_manifest/<cand>_L7.json`.

### J. L10b decision traceability
`+= literature_changed_direction:bool, decision_grounding{paper_card_ids,method_card_ids,branch_ids}, evidence_kept[], evidence_dropped[]`.

### K/L. Ledgers
`08_Audit/branch_ledger/<cand>.json` + `08_Audit/modality_ledger/<cand>.json`. `L1_einstein += candidate_branches[]`.

## Gates

- **L0 memory gate** (emit-delta L0): if `from-memory`, require `prior_loop_memory` with `memory_hash` == seed file hash. (fixes #1,#2,#9)
- **D. L1 divergence gate** `_audit_divergence`: parse `## Query log` → families vs `query_families.json`; require ≥2 new families aligned to `required_new_search_directions`; staleness flag if artifact mtime < candidate `created_at`. Hard-fail only for `loop_type=divergent`. (fixes #3)
- **Branch gate** (L1): every prior `unexplored_branch` must appear in the new branch ledger with explicit status. No silent drop. (fixes #8 — unread atrial DEG files)
- **F. L4 method gate**: method-dependent script without a `method_card(extracted_from=full_text)` or explicit `internally_motivated` → fail. (fixes #4)
- **G. Full-text policy**: `get_full_text_article` required only when a method_card drives a NEW L6 design; else abstract OK. (token)
- **H. L6 traceability gate** `_audit_l6_traceability`: every script needs a valid grounding ref (real method_card / real L2·L5 attack / named prior candidate). (fixes #5)
- **I. L7 manifest gate**: every output maps to an approved L6 script + branch + method. (fixes #6)
- **J. L10 gate**: `literature_changed_direction` mandatory; grounding refs valid. (fixes #7)
- **M. aggregate-report fix**: write canonical `FINAL_REPORT_<cand>.md`/`_CN_<cand>.md`; `FINAL_REPORT.md` = latest with candidate banner; refuse overwrite of a different candidate's report without `--force`; maintain `00_Reports_Index.md`. (fixes overwrite bug)

### C. `new-candidate --from-memory <path> --loop-type <t>`
Reads seed JSON, fills frontmatter question/claim from `next_round_hypothesis`, records `prior_candidate` + `memory_hash` + `loop_type`, registers memory so L0 `assemble-context` injects it. Fail on missing/invalid seed.

## Skill / tool use (no reinvention)

- **Meta-workflow:** `superpowers:brainstorming` → `superpowers:writing-plans` → implement. `superpowers:systematic-debugging` only if a bug surfaces.
- **ARS engine:** L1 `synthesis_agent`, L4 `research_architect_agent`, `ars-citation-check` for provenance. Adapter `ars_card_adapter.py` maps ARS output → local cards.
- **caveman:** existing `_runtime_digest` compressor (research_loop_v04.py:845) for provenance-preserving digest compression.

## Token plan

Papers/methods → card files, never in deltas/context. Nodes pass IDs + paths + sha256. `query_families.json` cache dedups searches. Full text only when a method_card drives a new design. `assemble-context` injects card IDs + one-line, not abstracts. Ledgers are tiny JSON. No pasted papers, no repeated long summaries. ARS invoked once per node; output cached to cards, never re-summarized.

## Test plan (pytest, research_loop suite)

1. `emit-loop-memory` deterministic + schema-valid + hash stable.
2. `new-candidate --from-memory` fills frontmatter; rejects missing/invalid seed; records `loop_type`.
3. L0 memory-hash gate: reject mismatch/absent when `from-memory`.
4. L1 divergence gate: 0-new-family fails (divergent); ≥2 passes; staleness flag when artifact older than candidate; `correction` loop_type bypasses family requirement.
5. Paper/method card round-trip + assert no abstract text stored in delta.
6. L4 method gate: method-dependent script without full-text method_card fails; `internally_motivated` allowed.
7. L6 traceability gate: script without valid grounding fails; each grounding type validated.
8. L7 manifest gate: output not mapping to L6-script+branch+method fails.
9. L10b `literature_changed_direction` required; `decision_grounding` refs valid.
10. Branch ledger: prior unexplored branch absent from new ledger → fail (divergent).
11. Modality ledger detects unused registered input.
12. aggregate-report no-clobber: second candidate does not overwrite first's `FINAL_REPORT_<id>.md`; index updated.
13. Regression: existing C1/C2 deltas still validate under extended (optional-field) schemas.

## Risks

- ARS-agent output volume/latency + APA mismatch → adapter is a mandatory pre-delta firewall; ARS invoked once per node, cached to cards; fallback to PubMed/bioRxiv MCP on ARS error, recorded in tool receipt.
- Hard divergence gate could wrongly block a legitimate re-analysis/correction loop → gate keyed to declared `loop_type`.
- Query-family normalization false-negative → config threshold + manual override with recorded reason.
- Schema break → all new fields optional; hard-fail only on `--from-memory`.
- Scope creep (51 files already touched this session) → implementation limited to `research_loop_v04.py` + `ars_card_adapter.py` + tests. No candidate/report/provenance-core edits.

## Out of scope (do NOT touch)

Provenance gates core logic, caveman-lite, candidate-isolation logic (unless a concrete bug is reproduced), the hand-verified BH/FDR implementation, v0.7. No push.
