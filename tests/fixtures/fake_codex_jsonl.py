"""Deterministic Codex-like JSONL fixture; never accesses network or credentials."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


def _final_path(argv: list[str]) -> Path:
    for flag in ("--output-last-message", "-o"):
        if flag in argv:
            return Path(argv[argv.index(flag) + 1])
    raise SystemExit("missing --output-last-message")


def _write_final(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "queries": ["fixture query"],
        "papers": [{
            "doi": "10.1000/fixture",
            "pmid": "",
            "url": "https://example.invalid/fixture",
            "title": "Fixture paper",
            "source_database": "fixture",
            "metadata": {"year": 2026, "journal": "Fixture"},
            "source_metadata_response": {"id": "fixture", "title": "Fixture paper"},
            "open_access": False,
            "content_type": "text/plain",
            "source_payload": "",
            "paper_type": "primary",
            "extracts": [{
                "section": "Results",
                "text": "Fixture result.",
                "locator": "Results 1",
                "extraction_method": "fixture",
                "verification_status": "located",
            }, {
                "section": "Discussion",
                "text": "Fixture discussion.",
                "locator": "Discussion 1",
                "extraction_method": "fixture",
                "verification_status": "located",
            }, {
                "section": "Conclusion",
                "text": "Fixture conclusion.",
                "locator": "Conclusion 1",
                "extraction_method": "fixture",
                "verification_status": "located",
            }],
        }],
        "review_search": {"query": "", "status": "none_found", "receipt": "fixture"},
        "verification": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    if "--version" in sys.argv:
        print("codex-cli 0.fixture")
        return 0
    mode = os.environ.get("RLR_FAKE_CODEX_MODE", "stream")
    delay = float(os.environ.get("RLR_FAKE_CODEX_DELAY", "0.15"))
    final_path = _final_path(sys.argv)
    _emit({"type": "thread.started", "thread_id": "thread-fixture"})
    _emit({"type": "turn.started"})
    if mode == "silent":
        time.sleep(delay * 4)
        _emit({"type": "turn.completed", "usage": {}})
        _write_final(final_path)
        return 0
    if mode == "stderr_noise":
        for index in range(100):
            print(f"ordinary diagnostic noise {index}", file=sys.stderr, flush=True)
            time.sleep(delay)
        return 9
    if mode == "child_busy":
        child_code = (
            "import time\n"
            "end = time.monotonic() + 10\n"
            "value = 0\n"
            "while time.monotonic() < end:\n"
            "    value += 1\n"
        )
        child = subprocess.Popen([sys.executable, "-c", child_code])
        try:
            time.sleep(delay * 100)
        finally:
            child.terminate()
            child.wait(timeout=2)
        return 9
    if mode == "recoverable_error":
        _emit({"type": "error", "message": "temporary fixture error"})
        time.sleep(delay)
    item_type = "mcp_tool_call" if mode == "stuck_mcp" else "command_execution"
    item = {"id": "item-1", "type": item_type, "status": "in_progress"}
    if item_type == "mcp_tool_call":
        item.update({"server": "fixture-mcp", "tool": "search", "arguments": {}})
    else:
        item.update({"command": "fixture command", "aggregated_output": ""})
    _emit({"type": "item.started", "item": item})
    print("fixture diagnostic", file=sys.stderr, flush=True)
    if mode in {"stuck_mcp", "timeout"}:
        time.sleep(delay * 20)
        return 9
    time.sleep(delay)
    completed = dict(item)
    completed["status"] = "completed"
    if item_type == "command_execution":
        completed["exit_code"] = 0
    _emit({"type": "item.completed", "item": completed})
    time.sleep(delay)
    _emit({"type": "turn.completed", "usage": {}})
    _write_final(final_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
