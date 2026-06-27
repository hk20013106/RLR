# RLR v0.5b — literature-gated branch

A surgical branch of RLR that makes literature research **mandatory, auditable,
and transmitted downstream**. v0.4.5 (`research_loop_v04.py`) is left fully
intact as the reference engine; v0.5b is a standalone overlay
(`rlr_v05b.py`) that imports v0.4.5 helpers and overrides only the DAG,
schemas, and the three hot commands.

## 1. Why (audit of v0.4.5 — HARD BUG)

| # | Question | v0.4.5 reality |
|---|---|---|
| 1 | Does L1 execute search or only print a prompt? | **Only prints** (`cmd_pre_research` → `print(prompt); return 0`). |
| 2 | Does L1 force hypotheses to cite literature? | **No** — `L1_einstein` schema has no literature fields. |
| 3 | Is L1 literature passed downstream verifiably? | **No** — research `.md` injected into L1's own context only; not in the delta, no hash. |
| 4 | Does L4 execute method review or only declare it? | **Only declares/prompts.** |
| 5 | Does L4 pass methods downstream structurally? | **No** — `L4_fisher` schema is `strategies/recommended`, no digest/citekeys. |
| 6 | Is `academic-research-suite` really invoked? | **Named only** in prompt text + `PRE_RESEARCH_MAP`; no code invokes/checks it. |
| 7 | Is missing pre-research a hard stop? | **No** — `assemble-context` prints `NOT YET RUN` and `return 0`s. |

**Verdict: hard bug.** The pipeline declares/prompts research but never executes,
validates, forces citation, or hard-stops — so L1 hypotheses and L4 methods can
be (and were) generated with zero real literature grounding.

## 2. What v0.5b changes

**DAG:** `L0 → L1 → L4a → L4b → L5 → L7 → (L8+ reuse v0.4.5)`
- **Removed:** L2, L3, L6.
- **Split:** old L4 → **L4a** (method literature review) + **L4b** (divergent ideation).
- **Merged planning:** old L5+L6 → single **L5** final executable plan gate.

**Hard literature gates (enforced offline by `rlr_v05b.py`):**
- `assemble-context` **fails closed (rc=3)** for L1/L4a unless the research file
  exists, is not the `NOT YET RUN` placeholder, has a populated `## Runtime
  digest`, that digest carries DOI/PMID/URL identifiers, and references ≥1
  citekey resolving in `09_Literature_Database/` or inline in the digest.
- `emit-delta` runs structural schema validation **plus** semantic gates:
  - **L1** rejected without `literature_used`; every hypothesis needs
    `literature_basis` unless `exploratory: true`; all citekeys must resolve.
  - **L4a** rejected without `method_literature_digest`; citekeys must resolve.
  - **L4b** rejected unless it consumes **both** L1 and L4a (`consumes.L1`,
    `consumes.L4a`) and every idea has `idea_provenance`.
  - **L5** rejected unless `analysis_plan` is complete (all 11 fields incl.
    `script_list`).
- **Receipts:** every assemble/emit writes `08_Audit/v05b_receipt_<node>_<ts>.json`
  with research path, sha256, `runtime_digest_found`, `digest_injected`,
  `consumed_by`, injected upstream delta hashes.

## 2b. Using academic-research-skills as the literature engine

RLR v0.5b's preferred external literature engine is **academic-research-skills
(ARS)** — `Imbad0202/academic-research-skills`. ARS Deep Research / lit-review
mode is what generates the L1 and L4a literature artifacts; RLR then validates
those artifacts.

**Install (Claude Code):**
```text
/plugin marketplace add Imbad0202/academic-research-skills
/plugin install academic-research-skills
```
Then run ARS Deep Research in literature-review mode for L1, and in
method-focused literature-review mode for L4a, using the prompt templates:
- `templates/v05b/L1_ars_pre_research_prompt.md`
- `templates/v05b/L4a_ars_pre_research_prompt.md`

**Codex CLI:** the sibling distribution `academic-research-skills-codex` exposes
the same workflow content as `$academic-research-suite`; invoke that instead.

**Division of responsibility (important):**
- **ARS** *generates* the literature: it reads sources and writes the
  `L1_research.md` / `L4a_research.md` artifact, ending with the required
  `## Runtime digest` + `## RLR handoff summary` sections.
- **RLR v0.5b does NOT prove a live ARS tool/network call occurred** — the skill
  runs outside the engine's visibility.
- **RLR v0.5b validates the resulting artifact**, offline: the file exists, has a
  non-empty `## Runtime digest`, each paper carries a DOI/PMID/URL identifier,
  citekeys resolve in `09_Literature_Database/` (or inline), and the result is
  consumed downstream (`literature_used` in L1, `method_literature_digest` in
  L4a, and L4b/L5 consuming upstream deltas). This is the artifact-based
  guarantee; it is intentionally not a proof of invocation.

**Licensing — do not vendor ARS:** the ARS repository is **CC BY-NC 4.0**. Do
**not** copy, vendor, or re-implement ARS into this repo unless license
compatibility is explicitly accepted. v0.5b only *calls* ARS as an external,
separately-installed engine and consumes its text output; no ARS code or content
is bundled here.

**v0.5b stays artifact-based (no hard Python dependency on ARS):** the Python
engine never imports or shells out to ARS. L0 may *report* ARS availability as
recommended/attested (e.g. in `skills_found` / `skill_use_plan`), but the L1/L4a
**hard gates remain based on artifact validity**, never on live skill invocation.
If ARS is absent, you may produce the `## Runtime digest` artifact by any
literature method — the gates judge the artifact, not the tool.

## 3. Run

```bash
# what's next + whether literature is required for that node
python rlr_v05b.py next-step        PROJECT_DIR CAND_ID

# validate a node's pre-research (rc=0 valid, rc=3 blocked)
python rlr_v05b.py check-research   PROJECT_DIR CAND_ID --node L1

# assemble node context (hard-fails on missing/empty literature for L1/L4a)
python rlr_v05b.py assemble-context PROJECT_DIR CAND_ID --node L1

# validate + write a node delta (structural + literature/provenance gates)
python rlr_v05b.py emit-delta       PROJECT_DIR CAND_ID --node L4b \
                                    --persona Fisher --file delta.json
```

### Required `## Runtime digest` shape (per paper)
`citekey, doi, pmid, url, title, year, core finding, relevance,
downstream implication, caveat, limitation`. The block must contain at least one
DOI/PMID/URL and reference citekeys via `[[09_Literature_Database/<key>|Title]]`.

### Delta shapes
See `SCHEMAS_V05B` in `rlr_v05b.py` for L1 (`hypotheses` + `literature_used`),
L4a (`method_literature_digest` + constraints + methods_to_avoid), L4b
(`analysis_ideas` + `consumes`), L5 (`analysis_plan`).

## 4. Tests

```bash
python test_rlr_v05b.py     # 10/10 expected
```
Covers all 9 required gates + a happy-path L4b acceptance. The two
`ASSEMBLE-CONTEXT FAILED` lines printed during the run are the expected stderr
from the negative tests (2 and 5).

## 5. Migration / coexistence

- v0.4.5: keep running existing projects on `research_loop_v04.py` unchanged.
- v0.5b: opt in per project by driving the loop with `rlr_v05b.py` for nodes
  L0–L7; L8+ deltas reuse v0.4.5 schemas, so the existing L8/L8.5/L9/L10
  tooling and `aggregate-report` continue to work.
- The `pre-research` prompt itself is still produced by v0.4.5
  (`cmd_pre_research`) — v0.5b does not change how the prompt is generated; it
  changes whether the **result** is required, validated, and transmitted.
- No files in v0.4.5, `templates/`, or project data were modified. New files
  only: `rlr_v05b.py`, `test_rlr_v05b.py`, this README.

## 6. Known boundary (honest)

v0.5b verifies that **real, identified literature with a structured digest
exists and is cited** — it cannot, offline, prove a network call to
`academic-research-suite` happened (the main agent runs the skill outside the
engine's visibility). This is the chosen, pragmatic strictness level
(digest + citekey existence). It defeats empty/placeholder/uncited research,
which was the actual failure mode in v0.4.5.
