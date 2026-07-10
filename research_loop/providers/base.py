"""Provider foundation: ABC, shared prompt/command runners, run receipt (Phase 4 leaf).

Stdlib only -> pure leaf. No engine import."""
import json
import subprocess
from dataclasses import dataclass, asdict, field
from pathlib import Path
import datetime as _dt


class ProviderError(Exception):
    """Raised when a provider cannot be constructed / resolved. The runner turns
    this into a fail-loud error (it never silently falls back to manual)."""

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
    try:
        return json.loads(of.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ProviderError(
            f"subprocess wrote invalid JSON to {of}: {e}") from e

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
