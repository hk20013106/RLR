# Filename Versioning Policy

## Active files

Production code, CLI entry points, modules, and current templates use stable,
unversioned names. The filename must not encode the software release.

Examples: `src/research_loop/engine.py`, `src/research_loop/cli.py`,
`src/run_loop.py`, `templates/layers/`, and `templates/personas/`.

## Version source of truth

Release versions belong in `pyproject.toml` (when introduced),
`src/research_loop/__init__.py`, Git tags, GitHub releases, and release notes.
Do not infer the current release from a production filename.

## Legacy snapshots

Immutable, non-runtime historical implementations may retain versioned names,
but must live under `legacy/`, `docs/archive/`, or `tests/fixtures/legacy/`.

## Schema and migration versions

Versioned schema and migration artifacts are allowed when multiple versions must
coexist, for example `schema_v1.json` or `migration_v1_to_v2.py`.

## Compatibility shims

An old entry point may remain temporarily only when it is marked deprecated,
forwards to the canonical unversioned implementation, has a removal plan, and
is not referenced by new code or documentation. Do not add new `_v05.py` or
`_v06.py` active files.
