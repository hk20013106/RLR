# P2-RANKING-BOUNDARY Symbol Ownership Audit

## Scope

This audit traces `_SyntheticPositionBiasedJudge` across production source,
tests, and root-level Python entry points. It is an ownership decision only; no
production extraction is part of this audit.

## Definition

- `src/research_loop/engine.py:3962` — class
  `_SyntheticPositionBiasedJudge`.
- Its docstring identifies it as a deterministic benchmark judge with
  deliberately measurable order bias.

## Complete reference inventory

A repository-wide search over `src/`, `tests/`, and root `*.py` found exactly
three occurrences:

| Location | Enclosing symbol | Use |
| --- | --- | --- |
| `src/research_loop/engine.py:3962` | `_SyntheticPositionBiasedJudge` | Class definition. |
| `src/research_loop/engine.py:3992` | `_naive_benchmark` | Instantiates the synthetic judge for the intentionally single-order benchmark control. |
| `src/research_loop/engine.py:4059` | `cmd_ranking_benchmark` | Instantiates the synthetic judge for the fair-flipping benchmark run passed to `ranking.run_elo_ranking`. |

There are no references in `tests/`, root-level Python files, or any other
production source module. In particular,
`src/research_loop/ranking.py` contains no reference to
`_SyntheticPositionBiasedJudge`.

## Runtime judge distinction

`DeterministicFakeJudge`, not `_SyntheticPositionBiasedJudge`, is the normal
network-free runtime judge:

- `src/research_loop/ranking.py:47` defines `DeterministicFakeJudge` as the
  free default judge for reproducible tests and network-free runs.
- `src/research_loop/ranking.py:125` selects it when
  `fair_pairwise_judge` receives no judge.
- `src/research_loop/ranking.py:353` selects it when `run_elo_ranking`
  receives no judge.
- `src/research_loop/engine.py:3807-3809`, in `_ranking_judge`, returns
  `ranking.DeterministicFakeJudge()` for the ranking CLI's `fake` judge mode.
- `tests/test_ranking_cli.py:148`, inside
  `test_provider_shadow_ranking_uses_run_owned_audit_directory`, also
  constructs `engine.ranking.DeterministicFakeJudge()` while testing the
  runtime ranking CLI path.

By comparison, both uses of `_SyntheticPositionBiasedJudge` are downstream of
`cmd_ranking_benchmark` (`src/research_loop/engine.py:4045`). The command is
registered only as the `ranking-benchmark` CLI subcommand at
`src/research_loop/engine.py:4256-4262`. Its biased behavior exists to generate
benchmark measurements and is not the default or selectable fake judge for the
normal shadow-ranking command.

## Ownership decision

**Do not move `_SyntheticPositionBiasedJudge` to the `ranking.py` logic leaf
now. Keep it with the ranking benchmark command code and move it with
`commands/ranking.py` in Batch B.**

Evidence:

1. Every executable reference belongs to ranking CLI benchmark code:
   `_naive_benchmark` or `cmd_ranking_benchmark`.
2. The logic leaf has no dependency on the symbol and already owns its real
   network-free runtime implementation, `DeterministicFakeJudge`.
3. The synthetic judge encodes benchmark-fixture behavior—gold ranks and
   deliberate position bias—rather than reusable ranking semantics.
4. Moving it into `ranking.py` now would add benchmark-only policy to a module
   documented as independent ranking primitives, without satisfying any
   current caller.
5. Keeping the class beside its only consumers preserves cohesion and allows
   the whole benchmark command surface to move together during the separately
   authorized Batch B extraction.

## Search evidence

The authoritative tracked-file search used was:

```text
git grep -n -e '_SyntheticPositionBiasedJudge' -- 'src/**' 'tests/**' '*.py'
```

It returned only the three `engine.py` sites listed above. A separate inspection
of `src/research_loop/ranking.py` confirmed the absence of the symbol and the
runtime/default `DeterministicFakeJudge` selections described above.
