"""ManualProvider: DEBUG-only human-in-the-loop provider (Phase 4)."""
import json
from pathlib import Path

from research_loop.providers.base import (
    AgentProvider, ProviderError, _schema_repr,
)


class ManualProvider(AgentProvider):
    """DEBUG / manual-test provider only. Human-in-the-loop: writes the prompt,
    waits for a delta JSON path. NOT a default -- enable with `--provider manual`.
    The automatic path is HostAgentProvider / CommandProvider."""

    type = "manual"

    def __init__(self, spec=None):
        self.spec = spec or {}
        self.name = "manual"
        self.last_prompt_file = None
        self.last_delta_file = None
        self.last_fresh_session = None

    def run_agent(self, node, persona, context, output_schema=None,
                  workspace=None, tools=None, run_dir=None):
        run_dir = Path(run_dir or ".")
        run_dir.mkdir(parents=True, exist_ok=True)
        pf = run_dir / f"{node}_{persona}_prompt.txt"
        fresh = bool(self.spec.get("fresh_session", True))
        self.last_fresh_session = fresh
        lines = []
        if fresh:
            lines += [
                "############################################################",
                "# START A NEW / FRESH AGENT SESSION FOR THIS PROMPT.",
                "# Do NOT carry over history from any previous node. Use ONLY",
                "# the information below -- prior context would pollute it.",
                "# 请在【新会话】中执行本 prompt，不要带入上一节点的任何历史，",
                "# 只使用下方提供的信息。",
                "############################################################",
                "",
            ]
        lines += [f"# RLR manual agent prompt — node={node} persona={persona}", ""]
        if workspace:
            lines.append(f"# WORKSPACE (Path A; read/write ONLY inside): {workspace}")
        if tools:
            lines.append(f"# allowed tools / policy: {tools}")
        if output_schema:
            lines += ["# Return a JSON delta matching this schema:",
                      json.dumps(_schema_repr(output_schema), indent=2,
                                 ensure_ascii=False), ""]
        lines += ["=== CONTEXT ===", context]
        pf.write_text("\n".join(lines), encoding="utf-8")
        self.last_prompt_file = str(pf)

        print(f"\n[ManualProvider] node={node} persona={persona}")
        print(f"  prompt written: {pf}")
        print("  Run this prompt in your agent of choice (Codex / Claude / "
              "AntiGravity / ...),")
        print("  then enter the path to the returned delta JSON file.")
        path = input("  delta JSON path (blank to abort): ").strip().strip('"')
        if not path:
            raise RuntimeError("ManualProvider aborted by user")
        self.last_delta_file = path
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise ProviderError(
                f"cannot read delta JSON from {path}: {e}") from e
