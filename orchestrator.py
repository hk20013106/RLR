#!/usr/bin/env python3
"""RLR v0.3 orchestration layer — provider-neutral agent invocation.

This module is the *external* orchestration the controller (research_loop_v03.py)
deliberately does not do: it actually invokes a subagent for a DAG node. It is
tool-agnostic by design -- it never hard-codes Codex / Claude / AntiGravity. Two
providers ship here:

  - ManualProvider  : writes the prompt to a file, asks the human to run it in
                      whatever agent they like, and reads back the delta JSON.
  - CommandProvider : runs a generic shell command template with {prompt_file}
                      and {output_file} placeholders.

Config is provider-neutral (ProviderConfig, loaded from YAML or JSON; PyYAML is
optional -- a tiny built-in parser covers the default template). Every agent
call can be recorded as a RunReceipt under 08_Run_Receipts/.
"""

import json
import os
import subprocess
from dataclasses import dataclass, asdict, field
from pathlib import Path

import datetime as _dt


class ProviderError(Exception):
    """Raised when a provider cannot be constructed / resolved. The runner turns
    this into a fail-loud error (it never silently falls back to manual)."""


# --- config loading (dependency-free; PyYAML used if available) -------------

def _scalar(v):
    s = v.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _mini_yaml(text):
    """Parse the restricted YAML subset used by rlr_runner.yaml (nested maps +
    scalars; no flow collections, no lists). Sufficient for the default config
    template when PyYAML is not installed."""
    root = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, sep, val = line.strip().partition(":")
        if not sep:
            continue
        key = key.strip()
        val = val.strip()
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if val == "":
            d = {}
            parent[key] = d
            stack.append((indent, d))
        else:
            parent[key] = _scalar(val)
    return root


def load_config(path):
    """Load a YAML or JSON config into a dict (PyYAML optional)."""
    text = Path(path).read_text(encoding="utf-8")
    if text.lstrip().startswith("{"):
        return json.loads(text)
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except Exception:
        return _mini_yaml(text)


class ProviderConfig:
    """Runner config. Top-level `mode` selects how nodes are executed:
      - main_agent (default): the current host agent IS the orchestrator; NO
        python provider is used (an execution protocol, not a provider).
      - headless: python calls an external AI CLI/wrapper per node.
      - manual: DEBUG-ONLY human-in-the-loop.
    """

    def __init__(self, data=None):
        self.data = data or {}
        self.mode = self.data.get("mode", "main_agent")
        self.max_rounds = self.data.get("max_rounds", 3)
        self.main_agent = self.data.get("main_agent", {}) or {}
        self.headless = self.data.get("headless", {}) or {}
        self.manual = self.data.get("manual", {}) or {}
        prov = self.data.get("provider", {}) or {}
        self.default = prov.get("default", {"type": "none"})
        self.nodes = prov.get("nodes", {}) or {}
        self.timeout = self.data.get("timeout")
        self.review = self.data.get("review", {"enabled": True}) or {"enabled": True}
        self.stop_policy = self.data.get("stop_policy", {}) or {}
        self.everos = self.data.get("everos", {"enabled": False}) or {"enabled": False}

    def for_node(self, node):
        spec = dict(self.default)
        spec.update(self.nodes.get(node, {}) or {})
        return spec

    @classmethod
    def load(cls, path):
        if path and Path(path).exists():
            return cls(load_config(path))
        return cls({})


# --- provider abstraction ---------------------------------------------------

class AgentProvider:
    """Provider interface. Subclasses turn (node, persona, context) into a delta
    dict using whatever backend they wrap."""

    type = "base"
    name = "base"

    def run_agent(self, node, persona, context, output_schema=None,
                  workspace=None, tools=None, run_dir=None):
        raise NotImplementedError


def _schema_repr(s):
    """Human-readable rendering of a delta schema (turns type objects into
    their names) for inclusion in a manual prompt."""
    if isinstance(s, dict):
        return {k: _schema_repr(v) for k, v in s.items()}
    if isinstance(s, list):
        return [_schema_repr(x) for x in s] if s else []
    if isinstance(s, type):
        return s.__name__
    return str(s)


def _compose_auto_prompt(node, persona, context, output_schema=None,
                         workspace=None, tools=None):
    """Prompt for an automatic (non-interactive) provider: instruct the agent to
    return ONLY the JSON delta, include the schema, then the scoped context."""
    lines = [
        f"# RLR auto agent task — node={node} persona={persona}",
        "# Return ONLY a single JSON object (the delta) and nothing else.",
    ]
    if workspace:
        lines.append(f"# WORKSPACE (Path A; read/write ONLY inside): {workspace}")
    if tools:
        lines.append(f"# tools / policy: {tools}")
    if output_schema:
        lines += ["# JSON delta schema:",
                  json.dumps(_schema_repr(output_schema), indent=2,
                             ensure_ascii=False)]
    lines += ["", "=== CONTEXT ===", context]
    return "\n".join(lines)


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
        return json.loads(Path(path).read_text(encoding="utf-8"))


def _run_command_agent(command, node, persona, context, output_schema,
                       workspace, tools, run_dir, timeout, provider):
    """Shared body for command-style providers: write prompt, run the command
    template (one fresh subprocess), read the delta JSON it must write."""
    run_dir = Path(run_dir or ".")
    run_dir.mkdir(parents=True, exist_ok=True)
    pf = run_dir / f"{node}_{persona}_prompt.txt"
    of = run_dir / f"{node}_{persona}_delta.json"
    pf.write_text(_compose_auto_prompt(node, persona, context, output_schema,
                                       workspace, tools), encoding="utf-8")
    provider.last_prompt_file = str(pf)
    provider.last_delta_file = str(of)
    cmd = command.format(prompt_file=str(pf), output_file=str(of), node=node,
                         persona=persona, workspace=workspace or "")
    subprocess.run(cmd, shell=True, check=True, timeout=timeout)
    return json.loads(of.read_text(encoding="utf-8"))


def run_text_command(command, prompt, run_dir, tag, timeout=None):
    """Run a headless command for a FREE-TEXT step (e.g. v0.4 pre-research):
    write the prompt, run the command (which must write its output to
    {output_file}), and return the raw text (NOT parsed as JSON)."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    pf = run_dir / f"{tag}_prompt.txt"
    of = run_dir / f"{tag}_out.md"
    pf.write_text(prompt, encoding="utf-8")
    cmd = command.format(prompt_file=str(pf), output_file=str(of), node=tag,
                         persona="Researcher", workspace="")
    subprocess.run(cmd, shell=True, check=True, timeout=timeout)
    return of.read_text(encoding="utf-8")


class CommandProvider(AgentProvider):
    """Automatic provider for an external headless CLI. Runs a shell command
    template once per node; the command MUST write the delta JSON to
    {output_file}. Placeholders: {prompt_file} {output_file} {node} {persona}
    {workspace}. Each node = a fresh subprocess (fresh session)."""

    type = "command"

    def __init__(self, spec):
        self.spec = spec or {}
        self.name = "command"
        self.command = self.spec.get("command")
        self.timeout = self.spec.get("timeout")
        self.last_prompt_file = None
        self.last_delta_file = None
        self.last_fresh_session = True
        if not self.command:
            raise ProviderError(
                "command provider requires a 'command' template (using "
                "{prompt_file} and {output_file})")

    def run_agent(self, node, persona, context, output_schema=None,
                  workspace=None, tools=None, run_dir=None):
        return _run_command_agent(self.command, node, persona, context,
                                  output_schema, workspace, tools, run_dir,
                                  self.timeout, self)


class HeadlessProvider(AgentProvider):
    """Headless-command-mode provider: invokes an external AI CLI / wrapper
    headlessly, once per node (a fresh subprocess = fresh session). This is
    Python automatically calling an external AI -- it is NOT the current live
    chat session (Python cannot drive that). The command is resolved, in order,
    from: spec['command']; $RLR_HEADLESS_CMD (or legacy $RLR_HOST_AGENT_CMD);
    best-effort detection. If none resolves it raises ProviderError -- it NEVER
    falls back to manual.
    """

    type = "headless"

    def __init__(self, spec=None):
        self.spec = spec or {}
        self.name = "headless"
        self.timeout = self.spec.get("timeout")
        self.last_prompt_file = None
        self.last_delta_file = None
        self.last_fresh_session = True
        self.command = (self.spec.get("command")
                        or os.environ.get("RLR_HEADLESS_CMD")
                        or os.environ.get("RLR_HOST_AGENT_CMD")
                        or self._detect())
        if not self.command:
            raise ProviderError(
                "headless mode could not resolve a command. Set $RLR_HEADLESS_CMD "
                "to a headless command template (it MUST write the delta JSON to "
                "{output_file}), e.g.\n"
                "  export RLR_HEADLESS_CMD='claude -p < {prompt_file} > {output_file}'\n"
                "or set headless.command in rlr_runner.yaml. "
                "(For interactive use prefer main-agent mode; manual is debug-only.)")

    @staticmethod
    def _detect():
        env = os.environ
        if env.get("CLAUDECODE") or env.get("CLAUDE_CODE"):
            return "claude -p < {prompt_file} > {output_file}"
        return None

    def run_agent(self, node, persona, context, output_schema=None,
                  workspace=None, tools=None, run_dir=None):
        return _run_command_agent(self.command, node, persona, context,
                                  output_schema, workspace, tools, run_dir,
                                  self.timeout, self)


def make_provider(spec, override_type=None):
    """Construct a python provider from a spec dict (optionally forcing a type).
    No silent default. Note: main-agent mode uses NO python provider -- the host
    agent itself orchestrates; do not call this for it."""
    t = override_type or (spec or {}).get("type")
    if t in ("headless", "host", "auto"):
        return HeadlessProvider(spec)
    if t == "command":
        return CommandProvider(spec)
    if t == "manual":
        return ManualProvider(spec)
    if t in (None, "none"):
        raise ProviderError(
            "no python provider for this mode. main-agent mode is the default "
            "and uses NO python provider (the host agent orchestrates). For "
            "unattended runs set mode=headless + a command; manual is debug-only.")
    raise ProviderError(f"unknown provider type: {t!r}")


# --- run receipt ------------------------------------------------------------

@dataclass
class RunReceipt:
    node: str
    persona: str
    provider: str
    timestamp: str
    context_hash: str
    prompt_file: str = None
    delta_file: str = None
    workspace: str = None
    allowed_tools: list = None
    everos_scope: list = None
    fresh_session: bool = None
    candidate_id: str = None
    round_id: int = None

    def write(self, path):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False),
                     encoding="utf-8")
        return str(p)


def now():
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
