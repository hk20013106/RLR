<!-- Generated: 2026-07-07 | Project: Research Loop Room v0.6 | Files scanned: 95 | Token estimate: ~500 -->

# Dependencies - Research Loop Room (RLR) v0.6

## Python Runtime

- **Python 3.13** (tested on 3.13.12, Windows)
- **PyYAML** - candidate/config YAML parsing
- **pytest 9.1** - test suite (25 tests)

## External Skills/Services

| Dependency | Used By | Purpose |
|-----------|---------|---------|
| Academic Research skill | L1, L4 pre-research | PubMed/EuropePMC literature search |
| PubMed/EuropePMC API | L1, L4, L8.5 | Literature retrieval + verification |
| GitHub API | L7 code search | Find analysis tools/scripts |
| Obsidian vault | sync_to_obsidian.py | End-of-round sync, wikilinks, lit DB |
| Zotero | (optional) | Literature management |
| ARS agents | L1 (synthesis_agent), L4 (research_architect_agent) | Cross-source gap analysis, method blueprints |

## Python Standard Library (no install needed)

| Module | Usage |
|--------|-------|
| `argparse` | CLI |
| `json` | Delta serialization, card files, ledgers |
| `hashlib` | sha256 (memory hash), sha1 (card IDs) |
| `pathlib` | File I/O |
| `subprocess` | L7 execution, provider dispatch |
| `re` | Schema validation, query log parsing |
| `shutil` | Turing workspace preparation (Path A) |
| `datetime` | Timestamps |
| `os` | Environment, path handling |

## Test Dependencies

- pytest (25 tests in tests/test_v06_divergence.py)
- No additional test-only packages

## Optional

- `caveman-lite` (runtime digest compressor, referenced in v0.6 spec)
- `everos-mem` (cross-session durable memory, optional layer)
