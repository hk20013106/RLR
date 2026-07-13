<!-- Generated: 2026-07-08 | Honest gap list, not a guess dressed as fact -->

# Design Purpose — What I Understand vs. What's Unclear

Written in response to a direct question: do I actually understand why this system
(Research Loop Room / RLR) was designed the way it was, or am I just describing its mechanics?

## What I do understand (grounded in `docs/superpowers/specs/2026-07-06-v06-divergence-contract-design.md` + `DAG_TOPOLOGY.md` + real candidate data in `Yigene_WGCNA_v03/`, `Yigene_Enhancer_v04/`)

- v0.6 exists to fix a specific, documented failure: a real two-round research run was found
  (via meta-audit) to be **convergent, not divergent** — round 2 "looked like" it explored new
  territory only because an agent *remembered* the prior round, not because the system carried
  structured state forward. Concrete symptoms: stale pre-research caches reused across candidates,
  `new-candidate` unable to accept memory input, silent report overwrites, zero traceability from
  executed scripts back to the literature/critique that justified them.
- The fix is a set of **mechanically-checked proof requirements**, not agent self-report: ≥2 new
  query families per divergent round, every unresolved branch from the prior round must be
  explicitly statused, every script must trace to a real method card or named critique, every
  final decision must declare whether literature changed its direction.
- The DAG's 10-persona structure (Linnaeus/Einstein/Feynman/Oppenheimer/Fisher/Tukey/Turing/
  Curie/Darwin/Jobs) mirrors an actual scientific method pipeline: hypothesize -> attack ->
  triage -> design -> QC -> approve -> execute -> audit -> falsify -> interpret -> assess -> decide -> report.
- It's being run against real biology candidates (WGCNA gene co-expression networks, ECM/COL6A1
  analysis, ortholog validation) — this isn't a toy/demo project.

## What's genuinely unclear to me — not stated anywhere I've read

1. **End goal / success criterion.** Is the target output a publishable paper (biology/genomics),
   a reusable AI-research-agent framework/product where biology is just the first proving ground,
   or a research artifact about multi-agent system reliability itself? The design docs explain
   *how* divergence is enforced, never *what winning looks like*.

2. **Why "divergence" is the priority, specifically.** Is the concern (a) wasted compute/time
   from redundant rounds, (b) a p-hacking-style risk of converging on a weak conclusion because
   nothing forces genuine re-examination, (c) demonstrating something about agent reliability
   engineering for its own sake, or (d) something else? The spec treats "must diverge" as a given
   requirement, not a justified one.

3. **Why biology/genomics as the domain.** Personal research interest? Domain chosen because it
   has clean ground-truth (literature, databases) to check agent claims against? Client/
   collaborator requirement? Unstated.

4. **Audience for `FINAL_REPORT_<cand>.md`.** Just for the user's own read, or meant for
   collaborators/reviewers/eventual publication? Affects how much the report-formatting and
   citation-integrity gates actually matter downstream.

5. **Where this stops.** The refactor roadmap in `backend_final.md` goes to v1.0 (async/parallel
   execution). Is v1.0 a finish line for a specific deliverable, or an open-ended platform that
   keeps extending? Not stated.

6. **Relationship between this repo and the ARS (academic-research-skills) plugin.** v0.6 wires
   `synthesis_agent`/`research_architect_agent` in as the L1/L4 engine via `ars_card_adapter.py`.
   Is RLR meant to eventually replace ARS's own pipeline, sit alongside it, or is this a one-off
   integration for this specific project?

## Why this file exists instead of a guess

Answering "do you understand the purpose" with a plausible-sounding paragraph that's actually
inference dressed as certainty would be worse than useless here — it would look like understanding
without being checkable. The "what I understand" section above is traceable to specific files/lines;
the "unclear" section is what I could not find grounding for. If any of these have answers you
already gave me in an earlier session that got compacted out, say so and I'll fold them in instead
of re-asking.
