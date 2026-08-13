from __future__ import annotations

import sys
from collections.abc import Iterable


def _normalize(path: str) -> str:
    return path.strip().replace("\\", "/")


def _is_docs_path(path: str) -> bool:
    if not path:
        return False
    if "/" not in path and path.startswith("README") and path.endswith(".md"):
        return True
    return path.startswith("docs/")


def classify_paths(paths: Iterable[str]) -> str:
    normalized = [_normalize(path) for path in paths]
    normalized = [path for path in normalized if path]
    if not normalized:
        return "full"
    return "docs-only" if all(_is_docs_path(path) for path in normalized) else "full"


def main() -> int:
    print(classify_paths(sys.stdin.read().splitlines()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
