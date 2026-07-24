# Handoff: P2-BATCH-B

## Branch

Direct commits on `codex/hypothesis-ledger-cutover` (no separate worktree branch merged -- Antigravity committed B-1/B-2 directly, Hermes completed B-3).

## Commits

- `face0ea` - refactor(engine): extract ranking CLI to commands/ranking.py (Batch B-1)
- `f453456` - refactor(engine): extract pitfall CLI to commands/pitfall.py (Batch B-2)
- `2089e94` - refactor(engine): extract reporting CLI to commands/reporting.py (Batch B-3)

## Files changed

- `src/research_loop/engine.py` (-741 lines, replaced with inward shims)
- `src/research_loop/commands/__init__.py` (new, empty package init)
- `src/research_loop/commands/ranking.py` (new, 496 lines)
- `src/research_loop/commands/pitfall.py` (new, 103 lines)
- `src/research_loop/commands/reporting.py` (new, 179 lines)
- `docs/handoffs/P2-BATCH-B-preaudit.md` (Antigravity pre-audit)
- `docs/handoffs/P1B-blocked-handoff.md` (P1B blocker record)

## Test results

- Phase-0 + family tests: 62 passed, 0 failed
- `research_loop_v04.py --help`: pass
- `git diff --check`: clean

## Claude review verdict

PASS with one noted deviation:
- `ranking.py:136` uses `sys.modules.get("research_loop.engine")` to detect monkeypatched `_ranking_judge` from tests. This is a runtime coupling (not static import, no cycle), but violates the "no engine import" rule. It is an intentional test-compat seam. Recommend future refactoring to use dependency injection instead.

## Known deviation

- `ranking.py` has `sys.modules.get("research_loop.engine")` at line 136. Not a static import. `test_no_cycles.py` passes (AST-based, doesn't detect runtime sys.modules access). Should be resolved in a future cleanup by inverting the dependency (engine injects judge into ranking command).

## P1B status

P1B is BLOCKED_ESCALATION. v2 gates not wired in `_emit_delta_v2()`. See `docs/handoffs/P1B-blocked-handoff.md` for details. Requires human decision on scope expansion.
