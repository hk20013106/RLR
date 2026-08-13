# Docs-only CI fast path design

## Goal

Avoid running the expensive Windows/Python regression suites when a change is documentation-only, while preserving full verification for any runtime, workflow, contract, configuration, or test change.

## Scope classification

A change is `docs-only` only when the changed-file set is non-empty and every changed path is either:

- a root README matching `README*.md`; or
- under `docs/**`.

Everything else is `full`. In particular, `AGENTS.md`, `.github/**`, `src/**`, `tests/**`, `requirements*.txt`, templates, contracts, and mixed docs+code changes are `full`.

## Architecture

`tools/ci_change_scope.py` is the single repository-owned classifier for this policy. Both `.github/workflows/ci.yml` and `.github/workflows/l4-evidence-ci.yml` consume the same classifier output.

The workflows continue to trigger normally. A lightweight Ubuntu scope job checks out full history, computes the exact changed files, and emits `docs-only` or `full`. Heavy Windows jobs use job-level `if` conditions. This intentionally avoids workflow-level `paths-ignore`: a workflow skipped by path filtering can leave a required check pending, whereas a conditionally skipped job reports success.

`l0-contract.yml` already has narrow path filters and does not need this change.

## Docs-only behavior

For `docs-only` changes:

- skip the Windows/Python full CI test job;
- skip L4 targeted and L4 full-regression jobs;
- run `git diff --check` in the lightweight standard CI scope job.

No dependency installation, coverage run, provider/L4 regression, or full pytest run occurs.

## Full behavior

For any `full` change, existing heavy verification semantics remain unchanged:

- standard Windows/Python import, CLI, pytest+coverage CI;
- L4 targeted provider/runtime tests;
- L4 full regression and whitespace check;
- L0 contract workflow continues to use its existing path-specific trigger.

`workflow_dispatch` for L4 is always treated as `full`.

## Safety / fail-closed behavior

- Empty or indeterminate diffs classify as `full`.
- A missing/invalid base SHA classifies as `full`.
- Any file not explicitly inside the docs-only allowlist classifies as `full`.
- Mixed documentation + code/config/test changes classify as `full`.
- The classifier is repository-owned; no third-party path-filter action is added.

## Verification

The classifier has focused tests for docs-only, mixed, workflow, governance, and empty input cases. The CI optimization PR itself must run the pre-existing full GitHub regression because it modifies `.github/**` and tests. After merge, the fast path is operational when a future docs-only PR reports the lightweight scope check and the heavy jobs as skipped rather than executing Python regression suites.
