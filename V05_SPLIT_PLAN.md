# RLR v0.5 split plan (v0.4.5-accurate)

> Supersedes the three earlier drafts (`HANDOFF_V05_SPLIT_PLAN.md`,
> `HANDOFF_V05_SPLIT_CLAUDE_CODE.md`, `HANDOFF_v0.5_split_plan.md`), which were
> written at v0.4.0 / 14 nodes / 2877 lines and are now stale.
> **This is a plan only — not executed.**
> Date: 2026-06-26.

## 1. Current state (measured)

| metric | earlier drafts assumed | actual now |
|--------|------------------------|-----------|
| controller version | 0.4.0 | **0.4.5** |
| `research_loop_v04.py` | 2877 lines | **3079 lines** |
| DAG nodes | 14 | **15** (adds **L8.5**) |
| statuses | 15 | 16 (adds **AUDITED**) |
| new since drafts | — | L8.5 lit-verify node; **L0 dependency gate**; `_condense_delta` |

Goal: split `research_loop_v04.py` into single-responsibility modules as
`v0.5`, **behaviour-identical** (pure mechanical refactor). `research_loop_v04.py`
is kept untouched as the fallback.

**Honest motivation note.** The original driver ("apply_patch/`__edit` fail on big
files") is a *tool* limitation (Codex/apply_patch), not an architecture flaw — the
Edit tool handles the 3k-line file fine. The real, tool-independent benefit is
maintainability (change isolation, readability, testability). Worth doing, but
not urgent unless an editor that struggles with large files is the main author.

## 2. Target modules + EXACT symbol assignment

Line numbers are the current location in `research_loop_v04.py`.

### `rlr_constants.py` — pure data (+ tiny derived maps)
`AGENTS` (52), `PERSONA_TITLE` (55), `VALID_STATUSES` (68),
`DECISION_TRANSITIONS` (81), `DAG_NODES` (105) **and its derivation loop**
(tools_policy / everos_read_scopes, ~275-302, mutates DAG_NODES — keep here),
`PRE_RESEARCH_MAP` (247), `NODE_MAP` (275), `DAG_SEQUENCE` (304),
`LAYER_TEMPLATE_FILE` (310), `PERSONA_TEMPLATE_FILE` (330), `DELTA_SCHEMAS` (348),
`DELTA_PERSONA` (412), `DELTA_DAG_ORDER` (423), `FINAL_STATUSES` (430),
`PREFLIGHT_FILES` (432), `LAYERS` (590). No imports.

### `rlr_utils.py` — low-level helpers → imports `rlr_constants`
`RLRError` (47), `_layer_template_path` (333), `_persona_template_path` (339),
`_now/_stamp/_date/_slug` (609-618), `_candidate_file` (623), `_delta_file` (626),
`_sha256` (633), `_audit_dir` (640), `_pre_research_file` (645),
`_input_alias` (651), `_everos_scopes_for` (662), `_next_seq` (667),
`_yaml_value` (677), `_load_yaml_front` (686), `_save_yaml_front` (706),
`_replace_field` (726), `strip_candidate_to_frontmatter` (744),
`_require_status` (767), `_set_status` (775), `_mkdirs` (800),
`_fmt_list` (812), `_fmt_dict` (819), `_empty_value_for_schema` (826),
`_validate_delta` (844).
**Do NOT put `_append_decision` here** (it needs a template → would create a
utils↔templates cycle). It goes to `rlr_project_cmds`.

### `rlr_templates.py` — static template strings → imports `rlr_constants`, `rlr_utils`
`_candidate_template_v03` (892), `_index_template_v03` (970),
`_handoff_template` (1023), `_decision_log_template` (1067),
`_note_template` (1091), `_preflight_template` (1105).

### `rlr_deps.py` — the L0 dependency gate (NEW cohesive module) → imports `rlr_utils`
`REQUIRED_DEPENDENCIES` (442), `_port_open` (457), `_dep_present` (466),
`_dep_fix_hint` (491), `_parse_declared_deps` (508), `_check_dependencies` (529),
`_dependencies_md` (546), `cmd_check_deps` (1946).
(Separating this keeps it out of `rlr_utils` — it is its own ~150-line subsystem.)

### `rlr_dag_runtime.py` — the hot loop → imports `rlr_constants`, `rlr_utils`
`cmd_next_step` (1184), `cmd_pre_research` (1313), `cmd_assemble_context` (1556),
`cmd_emit_delta` (1709). (The four commands the main-agent calls every node.)

### `rlr_project_cmds.py` — setup/management → imports `rlr_constants`, `rlr_utils`, `rlr_templates`, `rlr_deps`
`_append_decision` (782, moved from utils), `cmd_new_project` (1860),
`cmd_new_candidate` (1876), `cmd_preflight` (1896, calls `rlr_deps`),
`cmd_note` (1964), `cmd_demo` (1993), `cmd_decision` (2068), `cmd_route` (2120),
`cmd_triage_idea` (2147), `cmd_triage_method` (2184), `cmd_execution_gate` (2223),
`cmd_prepare_turing_workspace` (2260), `cmd_list` (2356), `cmd_show` (2375).

### `rlr_obsidian.py` — Obsidian sync → imports `rlr_constants`, `rlr_utils`
`cmd_obsidian_sync` (2388). (Optional: fold into `rlr_project_cmds`; keeping it
separate holds project_cmds ~520 lines.)

### `rlr_report.py` — L10c report → imports `rlr_constants`, `rlr_utils`
`SECTION_TITLES_EN` (2569), `SECTION_TITLES_CN` (2585), `DELTA_LABELS_CN` (2606),
`_condense_delta` (1508, moved here — it is only used by aggregate-report),
`_translate_delta_body_cn` (2665), `_format_delta_body` (2672),
`cmd_aggregate_report` (2796).

### `research_loop_v05.py` — entry + **facade**
`build_parser` (2887), `main` (3059). **Plus a re-export facade** (see §3).

## 3. Dependency graph (acyclic) and the run_loop facade

```
rlr_constants                      (leaf, no imports)
rlr_utils       -> constants
rlr_templates   -> constants, utils
rlr_deps        -> utils
rlr_dag_runtime -> constants, utils
rlr_project_cmds-> constants, utils, templates, deps
rlr_obsidian    -> constants, utils
rlr_report      -> constants, utils
research_loop_v05 (entry) -> all the above
```

**CRITICAL — the facade (the earlier drafts missed this).** `run_loop.py` does
`import research_loop_v04 as rl` and uses, today:
`rl.DAG_SEQUENCE`, `rl.DELTA_SCHEMAS`, `rl.NODE_MAP`, `rl.PRE_RESEARCH_MAP`,
`rl._candidate_file`, `rl._delta_file`, `rl._load_yaml_front`, `rl._replace_field`
(grep `rl\.` in run_loop.py to confirm the full set before executing — also
`_now`, `_empty_value_for_schema`, `RLRError` if present).

So `research_loop_v05.py` MUST re-export the public surface so `rl.*` keeps
resolving:

```python
# research_loop_v05.py
from rlr_constants import *      # noqa: F401,F403
from rlr_utils import *          # noqa
from rlr_templates import *      # noqa
from rlr_deps import *           # noqa
from rlr_dag_runtime import *    # noqa
from rlr_project_cmds import *   # noqa
from rlr_obsidian import *       # noqa
from rlr_report import *         # noqa
```

Then `run_loop.py` changes exactly one line: `import research_loop_v05 as rl`.
(Because Python `import *` skips `_underscore` names, either give each module an
explicit `__all__` that lists the needed `_helpers`, or have run_loop import the
private helpers directly, e.g. `from rlr_utils import _candidate_file, ...`.
Recommended: explicit `__all__` per module, including the `_` helpers run_loop
needs.) `orchestrator.py` (subprocess) and `sync_to_obsidian.py` (independent) are
unaffected.

## 4. Must NOT change (pure mechanical refactor)

- CLI: every `command`, arg, and output unchanged.
- DAG: 15 nodes, dependencies, status machine, gates unchanged.
- Delta schemas + recursive validation unchanged.
- Path B (`strip_candidate_to_frontmatter` returns frontmatter only) + Path A
  (`shutil.copy2`, same-disk workspace) unchanged.
- Pre-research (L1/L4/L7), L8.5, L0 dependency gate behaviour unchanged.
- Bilingual FINAL_REPORT generation unchanged.
- `research_loop_v04.py` kept (not deleted); existing projects still run on it.
- `templates/`, `sync_to_obsidian.py`, `orchestrator.py`, project data untouched.

## 5. Order

0. **Re-inventory** against the live file (done — this doc).
1. `rlr_constants.py` → `python -c "import rlr_constants"`.
2. `rlr_utils.py` → import OK.
3. `rlr_templates.py` → import OK.
4. `rlr_deps.py` → `python -c "import rlr_deps"`.
5. `rlr_dag_runtime.py`, `rlr_project_cmds.py`, `rlr_obsidian.py`, `rlr_report.py`.
6. `research_loop_v05.py` (facade + parser + main); add `__all__` where needed.
7. Change `run_loop.py` import line; grep-verify every `rl.*` resolves.
8. Run the smoke test (§6).
9. Bump docs to v0.5 (README / MAIN_AGENT_* / RUNNER) — version string only.

## 6. Verification / smoke test (codify, don't just eyeball)

Add `test_smoke.py` (or `test_smoke.sh`) asserting v04≡v05:
1. `v05 --help` lists the SAME commands as `v04 --help`.
2. `v05 demo` walks to KEEP; `v05 aggregate-report` makes EN+CN reports.
3. `v05 next-step` / `assemble-context --node L1` produce the same bytes as v04
   on a fixed fixture project (golden output).
4. `v05 emit-delta` accepts a valid delta, rejects a malformed one.
5. `v05 check-deps` STOPS (rc=3) on a declared-missing dep, PASSes otherwise.
6. `run_loop.py --help` and `run_loop.py run <demo> <cand> --dry-run` work after
   the import change.
7. Every module imports standalone with no error.
8. `git diff` adds only new `.py` files + the one-line run_loop import change.

## 7. Risks

- **Module-level globals / closures** referenced inside moved functions — grep
  each moved function for names that now live in another module; wire imports.
- **`import *` drops `_helpers`** → run_loop's `rl._candidate_file` etc. break
  unless `__all__` exports them (the facade detail in §3).
- **utils↔templates cycle** if `_append_decision` is left in utils — it is placed
  in `rlr_project_cmds` precisely to avoid this.
- **Timing:** this churns the whole controller; do it at a stable checkpoint,
  behind the smoke test, NOT in the middle of a live research round. v04 stays as
  the fallback.

## 8. Open decisions (pick before executing)

1. `rlr_obsidian.py` separate, or folded into `rlr_project_cmds`? (Recommend
   separate.)
2. Report-only constants (`SECTION_TITLES_*`, `DELTA_LABELS_CN`) in `rlr_report`
   (recommended, cohesion) or `rlr_constants`?
3. `__all__` per module vs run_loop importing private helpers directly?
   (Recommend `__all__`.)
4. Delete the three stale `HANDOFF_V05_*` drafts once this is accepted?
