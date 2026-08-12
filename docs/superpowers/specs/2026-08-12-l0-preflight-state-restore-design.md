# L0 Pre-flight + State Restore Design

## Goal

Keep one formal `L0` DAG node, but make it the deterministic boundary that proves the current research round can run and that any inherited evidence from the previous round still exists, is unchanged, and is explicitly bound for reuse.

## Core rule

L0 may discover, verify, bind, and expose evidence. L0 must not interpret scientific meaning.

A continuation round is not a fresh pipeline. It starts from the previous round's immutable-by-hash research state.

## Internal L0 sections

1. **Core runtime** — Python/packages, provider/main-agent readiness, project filesystem permissions.
2. **Research infrastructure** — Academic Research runtime, PubMed MCP readiness, Zotero readiness.
3. **Research persistence** — hypothesis ledger, evidence-store writability, Obsidian vault readiness.
4. **Previous-round restore** — round manifest identity/schema, artifact existence, SHA-256, producer lineage/receipt references.
5. **Current-round input** — existing authoritative `l0_input.yaml` contract plus inherited evidence references.
6. **Deferred execution readiness** — L7 execution capability is declared at L0 but candidate workspace/runtime is checked again when L7 is reached.

Each failed check has a component-specific error code. A generic `L0 FAILED` without a concrete failing component is not sufficient.

## Evidence persistence model

The evidence store is a logical layer over existing project locations; large files are not copied per round.

- source/raw data remain in their original registered paths;
- analysis outputs remain under `04_Analysis_Outputs/`;
- literature evidence remains under `09_Literature_Database/`;
- runtime receipts remain under `08_Run_Receipts/`;
- audit and restore artifacts remain under `08_Audit/`.

Large artifacts are immutable by `(path, sha256)`, not by physical duplication. A changed or missing inherited artifact causes fail-closed restore.

## Round evidence manifest

L10c emits one immutable manifest at:

`08_Audit/round_manifests/<candidate_id>_round_<round_id>.json`

Schema `RLRRoundEvidenceManifest/v1` contains:

- project identity;
- candidate identity;
- round identity;
- source artifacts;
- intermediate analysis artifacts;
- result artifacts;
- literature artifacts;
- audit/receipt artifacts.

Every artifact record contains at least:

- `artifact_id`;
- `class` (`source`, `intermediate`, `result`, `literature`, `audit`, `receipt`);
- project-relative or absolute registered `path`;
- `sha256`;
- `producer_node` where known;
- `producer_receipt` where known;
- `created_in_round`.

No directory scan may silently invent inherited evidence. The manifest is the authority for cross-round restoration.

## Loop memory vs evidence manifest

`next_loop_memory.json` remains the semantic continuation seed: hypothesis lineage, decision, next-round proposal, explored branches and retained/dropped evidence identifiers.

`round_manifest.json` is the physical evidence continuation record: exact artifacts, bytes/hashes and provenance links.

The two are linked by candidate/round identity and manifest path/hash; neither replaces the other.

## L0 evidence binding

A continuation L0 verifies the previous manifest and writes:

`08_Audit/l0_restore/<current_candidate_id>_evidence_binding.json`

Schema `L0EvidenceBinding/v1` contains previous candidate/round, manifest path/hash, verified artifact records, any failures, and `binding_status`.

Cognitive nodes consume the binding/authorized context rather than independently walking previous-round directories.

## Failure codes

Representative required codes:

- `L0_CORE_PYTHON_PACKAGE_MISSING`
- `L0_CORE_PROVIDER_UNAVAILABLE`
- `L0_CORE_PROJECT_NOT_WRITABLE`
- `L0_RESEARCH_ARS_UNAVAILABLE`
- `L0_RESEARCH_PUBMED_MCP_START_FAILED`
- `L0_RESEARCH_PUBMED_MCP_REQUIRED_TOOL_MISSING`
- `L0_RESEARCH_ZOTERO_UNREACHABLE`
- `L0_RESEARCH_ZOTERO_LIBRARY_UNREADABLE`
- `L0_STATE_LEDGER_BINDING_INVALID`
- `L0_STATE_EVIDENCE_STORE_NOT_WRITABLE`
- `L0_STATE_OBSIDIAN_INVALID_VAULT`
- `L0_RESTORE_MANIFEST_MISSING`
- `L0_RESTORE_MANIFEST_SCHEMA_INVALID`
- `L0_RESTORE_PROJECT_MISMATCH`
- `L0_RESTORE_CANDIDATE_MISMATCH`
- `L0_RESTORE_ARTIFACT_MISSING`
- `L0_RESTORE_ARTIFACT_HASH_MISMATCH`
- `L0_RESTORE_RECEIPT_INVALID`
- `L0_INPUT_CONTRACT_INVALID`
- `L0_INPUT_SOURCE_MISSING`

## Compatibility and reuse

- Keep the single authoritative `l0_contract.py`; do not create another current-input schema.
- Reuse `next_loop_memory.json` for semantic continuation; add only the manifest pointer/hash required to bind evidence state.
- Reuse the existing L7 execution manifest as an input to round-manifest construction.
- Do not change the closed-corpus L4A→L4B contract merged in PR #12.
- Do not create new formal DAG nodes L0a/L0b/L0c.

## Completion criteria

1. Initial-round L0 passes without requiring a previous manifest.
2. Continuation-round L0 fails closed before L1 when manifest identity/schema/path/hash/artifact bytes are invalid.
3. Valid continuation writes a stable evidence binding and can reuse unchanged source/intermediate/result evidence.
4. L10c emits loop memory plus round evidence manifest.
5. Preflight failures identify the exact component and error code.
6. Existing L4 contract and full suite remain green.
