# L0 Pre-flight + State Restore Design

## Goal

Keep one formal `L0` DAG node, but make it the deterministic boundary that proves the current research round can run and that any inherited evidence from the previous round still exists, is unchanged, and is explicitly bound for reuse.

## Core rule

L0 may discover, verify, bind, and expose evidence. L0 must not interpret scientific meaning.

A continuation round is not a fresh pipeline. It starts from the previous round's immutable-by-hash research state.

A blocking dependency must have a real downstream consumer in the current codebase. A planned future dependency may be probed for readiness, but it must not be promoted to a hard gate before its consumer exists.

## Internal L0 sections

1. **Core runtime** — Python/packages and project filesystem permissions. Provider/main-agent readiness is runner-bound because the active runner config/override is known only at invocation time; it is checked after deterministic state restore and before any provider work.
2. **Research infrastructure** — Academic Research is currently blocking because L1/L4/L8.5 consume it. PubMed MCP and Zotero are currently readiness-only probes for the planned literature transport/reference-management layer; they become blocking only when those consumers are wired.
3. **Research persistence** — hypothesis ledger, evidence-store writability, and Obsidian vault. Obsidian is currently blocking because L10c has a real required projection consumer.
4. **Previous-round restore** — round manifest identity/schema, artifact existence, SHA-256, producer lineage/receipt references.
5. **Current-round input** — existing authoritative `l0_input.yaml` contract plus inherited evidence references.
6. **Deferred execution readiness** — L7 execution capability is checked at the existing L7 workspace/execution gate when the loop reaches L7; L0 does not build candidate workspaces speculatively.

Each failed blocking check has a component-specific error code. A generic `L0 FAILED` without a concrete failing component is not sufficient. Readiness-only failures are persisted as warnings and do not claim that the future consumer is already operational.

## Probe ownership and enforcement

`research_loop/l0_preflight.py` is the single framework-owned authority for static/service probes. `commands/lifecycle.py` only formats and enforces its results; it must not repeat Academic Research or service checks.

Current enforcement:

- **blocking:** core Python/packages, filesystem, Academic Research, hypothesis ledger, evidence store, Obsidian;
- **readiness-only:** PubMed MCP, Zotero;
- **runner-bound:** provider/main-agent readiness;
- **deferred to L7:** execution workspace/runtime.

`00_Preflight/preflight_receipt.json` records the component, status, error code, detail, downstream consumer, and enforcement class for each static/service probe.

## Evidence persistence model

The evidence store is a logical layer over existing project locations; large files are not copied per round.

- source/raw data remain in their original registered paths;
- analysis outputs remain under `04_Analysis_Outputs/`;
- literature evidence remains under `09_Literature_Database/`;
- runtime receipts remain under `08_Run_Receipts/`;
- audit and restore artifacts remain under `08_Audit/`.

Large artifacts are immutable by `(path, sha256)`, not by physical duplication. A changed or missing inherited artifact causes fail-closed restore.

## Round evidence manifest

Successful L10c finalization freezes one immutable manifest at:

`08_Audit/round_manifests/<candidate_id>_round_<round_id>.json`

Schema `RLRRoundEvidenceManifest/v1` contains:

- project identity;
- candidate identity;
- round identity;
- source artifacts;
- intermediate analysis artifacts;
- explicit result artifacts;
- literature artifacts;
- candidate delta/audit artifacts;
- runtime receipts.

Every artifact record contains at least:

- `artifact_id`;
- `class` (`source`, `intermediate`, `result`, `literature`, `audit`, `receipt`);
- project-relative or absolute registered `path`;
- `sha256`;
- `producer_node` where known;
- `producer_receipt` where known;
- `created_in_round`.

Authoritative inputs are explicit: the L0 source contract, the existing L7 execution manifest, L7 `results[*].artifact_refs`, candidate-scoped reports, candidate-owned literature evidence, emitted candidate deltas/audit artifacts, and runtime receipts. No broad directory scan may silently invent inherited evidence.

If an L7 script output is later explicitly declared by the committed L7 delta as a scientific result, the same path is promoted from `intermediate` to `result`; it is not duplicated.

## L10c finalization ownership

There is one owner for round finalization: `aggregate-report` / L10c.

The required order is:

1. generate candidate-scoped final reports;
2. complete required Obsidian projection;
3. freeze the round evidence manifest only after projection succeeds.

If Obsidian sync fails, L10c fails and no round manifest is frozen. `run_loop.py` consumes the `aggregate-report` return code and must not run a second independent Obsidian sync path.

## Loop memory vs evidence manifest

`next_loop_memory.json` remains the semantic continuation seed: hypothesis lineage, decision, next-round proposal, explored branches and retained/dropped evidence identifiers.

`round_manifest.json` is the physical evidence continuation record: exact artifacts, bytes/hashes and provenance links.

L10c creates the physical manifest. `emit-loop-memory` does not create or rebuild it; it requires the already-frozen manifest, verifies it, and records the manifest path/hash in the semantic seed. The two artifacts are therefore linked but have one owner each.

## L0 evidence binding

A continuation L0 verifies the previous manifest and writes:

`08_Audit/l0_restore/<current_candidate_id>_evidence_binding.json`

Schema `L0EvidenceBinding/v1` contains previous candidate/round, manifest path/hash, verified artifact records, any failures, and `binding_status`.

The canonical runner executes this deterministic restore after component dependency checks but before provider readiness or main-agent handoff. A bad continuation therefore cannot consume provider quota or receive an orchestration prompt.

Cognitive nodes consume the binding/authorized context rather than independently walking previous-round directories.

## Failure codes

Representative codes include:

- `L0_CORE_PYTHON_PACKAGE_MISSING`
- `L0_CORE_PROJECT_NOT_WRITABLE`
- `L0_RESEARCH_ARS_UNAVAILABLE`
- `L0_RESEARCH_PUBMED_MCP_START_FAILED` *(readiness-only until the transport consumer is wired)*
- `L0_RESEARCH_PUBMED_MCP_REQUIRED_TOOL_MISSING` *(readiness-only until the transport consumer is wired)*
- `L0_RESEARCH_ZOTERO_UNREACHABLE` *(readiness-only until the Zotero consumer is wired)*
- `L0_RESEARCH_ZOTERO_LIBRARY_UNREADABLE` *(readiness-only until the Zotero consumer is wired)*
- `L0_STATE_LEDGER_BINDING_INVALID`
- `L0_STATE_LEDGER_NOT_WRITABLE`
- `L0_STATE_EVIDENCE_STORE_NOT_WRITABLE`
- `L0_STATE_OBSIDIAN_INVALID_VAULT`
- `L0_STATE_OBSIDIAN_NOT_WRITABLE`
- `L0_RESTORE_MANIFEST_MISSING`
- `L0_RESTORE_MANIFEST_SCHEMA_INVALID`
- `L0_RESTORE_MANIFEST_HASH_MISMATCH`
- `L0_RESTORE_PROJECT_MISMATCH`
- `L0_RESTORE_CANDIDATE_MISMATCH`
- `L0_RESTORE_ROUND_MISMATCH`
- `L0_RESTORE_ARTIFACT_MISSING`
- `L0_RESTORE_ARTIFACT_HASH_MISMATCH`
- `L0_RESTORE_RECEIPT_INVALID`
- current-round input errors remain owned by the existing `l0_contract.py` validator.

## Compatibility and reuse

- Keep the single authoritative `l0_contract.py`; do not create another current-input schema.
- Reuse `next_loop_memory.json` for semantic continuation; add only the manifest pointer/hash required to bind evidence state.
- Reuse the existing L7 execution manifest as an input to round-manifest construction.
- PubMed MCP and Zotero readiness probes do not justify a new base dependency or literature business layer in this PR.
- Do not change the closed-corpus L4A→L4B contract merged in PR #12.
- Do not create new formal DAG nodes L0a/L0b/L0c.

## Completion criteria

1. Initial-round L0 passes without requiring a previous manifest.
2. Continuation-round L0 fails closed before provider work/L1 when manifest identity/schema/path/hash/artifact bytes are invalid.
3. Valid continuation writes a stable evidence binding and can reuse unchanged source/intermediate/result evidence.
4. L10c completes required Obsidian projection before freezing the round evidence manifest.
5. `emit-loop-memory` consumes that existing manifest and cannot silently invent one.
6. Preflight failures identify the exact component/error code and distinguish blocking failures from future readiness warnings.
7. Existing L4 contract and full suite remain green.
8. Real environment acceptance is performed separately on the user's machine because GitHub CI cannot validate the user's actual Academic Research runtime, PubMed MCP, Zotero Desktop, Obsidian vault, and cross-round filesystem state.