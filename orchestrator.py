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
import subprocess
from dataclasses import dataclass, asdict, field
from pathlib import Path

import datetime as _dt


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
    if low in ("null", "none", "~", ""):
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
    """Provider-neutral runner config with per-node overrides."""

    def __init__(self, data=None):
        self.data = data or {}
        self.max_rounds = self.data.get("max_rounds", 3)
        prov = self.data.get("provider", {}) or {}
        self.default = prov.get("default", {"type": "manual"})
        self.nodes = prov.get("nodes", {}) or {}
        self.timeout = self.data.get("timeout")
        self.retry = self.data.get("retry", 0)
        self.review = self.data.get("review", {"enabled": True}) or {"enabled": True}
        self.stop_policy = self.data.get("stop_policy", {}) or {}
        self.everos = self.data.get("everos", {"enabled": False}) or {"enabled": False}
        self.override_type = None  # set from --provider on the CLI

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


class ManualProvider(AgentProvider):
    """Human-in-the-loop provider: write the prompt, wait for a delta JSON path."""

    type = "manual"

    def __init__(self, spec=None):
        self.spec = spec or {}
        self.name = "manual"
        self.last_prompt_file = None
        self.last_delta_file = None

    def run_agent(self, node, persona, context, output_schema=None,
                  workspace=None, tools=None, run_dir=None):
        run_dir = Path(run_dir or ".")
        run_dir.mkdir(parents=True, exist_ok=True)
        pf = run_dir / f"{node}_{persona}_prompt.txt"
        lines = [f"# RLR manual agent prompt — node={node} persona={persona}", ""]
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


class CommandProvider(AgentProvider):
    """Generic external-tool provider: run a shell command template.

    The command may use {prompt_file}, {output_file}, {node}, {persona},
    {workspace}. The command must write the delta JSON to {output_file}.
    """

    type = "command"

    def __init__(self, spec):
        self.spec = spec or {}
        self.name = "command"
        self.command = self.spec.get("command")
        self.timeout = self.spec.get("timeout")
        self.last_prompt_file = None
        self.last_delta_file = None
        if not self.command:
            raise ValueError("command provider requires a 'command' template")

    def run_agent(self, node, persona, context, output_schema=None,
                  workspace=None, tools=None, run_dir=None):
        run_dir = Path(run_dir or ".")
        run_dir.mkdir(parents=True, exist_ok=True)
        pf = run_dir / f"{node}_{persona}_prompt.txt"
        of = run_dir / f"{node}_{persona}_delta.json"
        pf.write_text(context, encoding="utf-8")
        self.last_prompt_file = str(pf)
        self.last_delta_file = str(of)
        cmd = self.command.format(prompt_file=str(pf), output_file=str(of),
                                  node=node, persona=persona,
                                  workspace=workspace or "")
        subprocess.run(cmd, shell=True, check=True, timeout=self.timeout)
        return json.loads(of.read_text(encoding="utf-8"))


def make_provider(spec, override_type=None):
    """Construct a provider from a spec dict (optionally forcing a type)."""
    t = override_type or (spec or {}).get("type", "manual")
    if t == "manual":
        return ManualProvider(spec)
    if t == "command":
        return CommandProvider(spec)
    raise ValueError(f"unknown provider type: {t}")


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
