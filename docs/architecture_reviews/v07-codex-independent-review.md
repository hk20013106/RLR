<!-- Independent architect review by Codex (GPT), 2026-07-10. All factual claims verified against the real repo before integration (grep-confirmed): orchestrator.run_agent signature, 14 root test_*.py, rlr_v05b imports engine, gate rc=3/rc=1/rc=2 split sites. SESSION_ID: 019f4aee-5c96-7610-aca7-b91d64d44fed -->

# Independent Architect Review: v0.7 Architecture Migration (Codex)

**Reviewer:** Codex (GPT) via ccg-workflow, independent context, read-only.
**Verification:** Every checkable claim below was grep-confirmed against the real repo before acceptance (per CLAUDE.md "verify tool output" rule). All verified TRUE.

---

## Verified Repo Observations (Codex found, Claude confirmed)

- `run_loop.py` is genuinely dual-coupled: `import research_loop_v04 as rl` AND `_ctl()` subprocess. ✓
- Gate behavior is NOT centralized: some gates run in `assemble-context`, others in `emit-delta`. ✓ (rc=3 at lines 2255/2261/2265; rc=1 at 1515/1585/2834/2867; rc=2 for bad input)
- `orchestrator.py` already defines `AgentProvider.run_agent(node, persona, context, output_schema=None, workspace=None, tools=None, run_dir=None)` — 4 impls + `make_provider()`. ✓
- 14 root-level `test_*.py` files exist, not only `tests/` (test_pr1-4, test_rlr_v05b, test_turing_workspace_hydration, test_pitfall_ledger, test_obsidian_sync, …). ✓
- `rlr_v05b.py` line 77 `import research_loop_v04 as rl`; `test_rlr_v05b.py` targets it. ✓
- `.context/` absent — no `.context/prefs/*` constraints apply. ✓

---

## Agree / Disagree on Claude's Key Decisions

**AGREE — reject JSON-RPC for run_loop↔engine.** Both sides are same-repo Python; JSON-RPC preserves the current serialization failure modes instead of removing them. The real problem is duplicated control paths (import for metadata + subprocess for behavior), not a missing transport. In-process EngineAPI gives typed returns/exceptions/paths while CLI stays as compat adapter. JSON-RPC only justified if non-Python clients become a first-class target — not a v0.7 goal.

**AGREE — modularize into topology / context / delta / gates / providers / EngineAPI.**

**DISAGREE — Provider.run(prompt,...) shape.** `orchestrator.py` already has `run_agent(node, persona, context, output_schema, workspace, tools, run_dir)`, and `run_loop.exec_cognitive()/exec_turing()` already call `prov.run_agent(...)`. A new `run(prompt,...)` erases schema injection, tools policy, run-receipt metadata, and the context-text vs composed-prompt separation. → **Formalize the existing `run_agent` contract; do NOT replace it.** Add optional internal `invoke(AgentRequest)->dict` only after tests prove equivalence; `run_agent` delegates to it.

**DISAGREE — phases are independently runnable as written.** Moving path helpers / topology constants / schemas out before a stable import facade risks breaking root tests and external imports expecting `research_loop_v04.DELTA_SCHEMAS`, `.NODE_MAP`, helper fns. → Add a **compat-facade-first phase** that pins exactly which names `research_loop_v04.py` must keep exporting, with an import-compatibility test.

**DISAGREE — generic GateResult(ok, rc, reason) is enough.** Gates enforce at two sites with different contracts:
- `assemble-context`: L1/L4 pre-research fail-closed rc=3; L1 divergence + branch coverage rc=3; L7 pre-research soft (still assembles).
- `emit-delta`: L0 memory, L4 methods, L6 traceability, L7 manifest, L10b traceability append validation errors → rc=1; malformed input → rc=2.
→ **GateRegistry must be phase-aware:** `ASSEMBLE_PRE_CONTEXT`, `ASSEMBLE_PRE_RESEARCH`, `EMIT_DELTA_VALIDATION`, `EXECUTION_GATE`. Each gate registers: applicable node(s), enforcement phase, legacy rc, legacy message formatter, fail-open/closed policy. Do NOT funnel all through one generic `run_for_node()`.

**DISAGREE — ContextAssembler description too vague on isolation.** Risk: refactor from "iterate declared `context_inputs`, fetch matching deltas" into "load available deltas then filter" weakens physical absence — leaks can surface in manifest, provider request, trace logs, receipt metadata, exceptions, or debug dumps even if final prompt looks filtered. Highest-risk: L9a/L9b (mutually invisible), L10c (only legit ALL reader). → Topology visibility must be the ONLY delta-path resolver; never pass a project-wide delta map or raw dir-walker into ContextAssembler; make `ContextManifest.injected` the authoritative audit list and assert it holds only allowed keys; preserve L0's special `source_input` exception exactly.

**DISAGREE — Phase 7 is merely "drop transitional adapters."** `_ctl()` is embedded in ~11 command categories (pitfall, next-step, assemble-context, emit-delta, status advance, execution-gate, prepare-turing-workspace, pre-research prompts, aggregate-report, new-candidate, check-deps), each with distinct stdout/stderr/rc. → EngineAPI migration must be **command-by-command with per-command parity tests**, not one big replacement.

---

## Additional Gaps Codex Flagged

- **Circular import risk understated.** `context` needs topology, paths, pre-research helpers, pitfall ledger, condensation, templates, manifests. If `engine` imports `context` and `context` imports engine helpers → immediate cycles. Enforce direction hard.
- **DeltaValidator versioning stub is dangerous if it mutates.** A no-op hook is fine; it must NOT mutate data or silently accept `delta_version` semantics. No version negotiation in v0.7.
- **main_agent provider is special** — `make_provider()` intentionally does not dispatch for `main_agent` (host agent IS orchestrator). Target provider package must preserve this.
- **Golden full-report byte-hash is brittle** (timestamps, receipt paths, manifests, Obsidian vary). Use targeted command-level golden snapshots (rc + stdout/stderr for gate fixtures) + semantic assertions for receipts/reports.
- **Obsidian sync conflict.** Target tree marks it "optional plugin", but hard-invariant #6 says end-of-round sync is required. Making it optional = an explicit behavior change that must be declared, OR preserve current "attempt sync, log skip on failure" semantics.
- **Test plan path wrong.** Must run all 14 root `test_*.py` + `tests/test_v06_divergence.py`, not just `pytest tests/`.

---

## Codex Recommended Phase Ordering (12 phases)

0. Compat + characterization safety net (public-symbol export test; command-level rc + stdout/stderr golden; context-isolation absence tests; run ALL root + tests/).
1. Create `research_loop/` package shell, wrappers import from `research_loop_v04` (no moves; prove no change).
2. Extract topology + immutable constants (re-export from old module).
3. Extract paths + errors (re-export).
4. Extract DeltaValidator only (schemas/output exact; no version behavior).
5. Extract ContextAssembler only (HIGH-RISK isolation phase; allowed-delta resolver only).
6. Extract GateRegistry by enforcement phase (preserve assemble rc=3 vs emit rc=1 separately).
7. Formalize provider interface without renaming behavior (keep `run_agent`; adapter only after compat tests).
8. Introduce EngineAPI in parallel with `_ctl` (API methods command-by-command + parity tests).
9. Migrate `run_loop.py` callsites incrementally (replace `_ctl` one category at a time; keep as fallback).
10. Rename active engine body, keep `research_loop_v04.py` shim (only after all compat tests green).
11. Isolate legacy (move only after runtime-import grep + test policy explicit; account for test_rlr_v05b importing it).

---

## Codex Final Position

- AGREE: modularize (topology/context/delta/gates/providers/EngineAPI); reject JSON-RPC for v0.7.
- DISAGREE: changing provider method shape without an adapter; that phases are independently runnable as written; that gate extraction is validated by logical pass/fail alone.
- REQUIRE: command-level rc+stdout/stderr snapshots and physical-absence tests BEFORE any extraction.
