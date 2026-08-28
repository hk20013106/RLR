"""Provider foundation: ABC, shared prompt/command runners, run receipt (Phase 4 leaf).

Stdlib only -> pure leaf. No engine import."""
import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
import datetime as _dt

from research_loop.providers.executor import DEFAULT_EXECUTOR, ProviderExecutionError


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
    # Fail closed: L0's prompt must carry the canonical structured input
    # contract. assemble-context already gates this (rc=3, empty stdout) so a
    # valid context always contains the block; this assertion guarantees an
    # invalid L0 input can reach neither a prompt file nor a manual provider.
    if node == "L0" and "=== L0 INPUT CONTRACT ===" not in (context or ""):
        raise ProviderError(
            "L0 context missing canonical '=== L0 INPUT CONTRACT ==='; "
            "prompt not written (input-contract gate not satisfied)")
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
    """Shared body for command-style providers using the ProviderExecutor boundary."""
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
    try:
        DEFAULT_EXECUTOR.run(cmd, shell=True, timeout=timeout)
    except ProviderExecutionError as exc:
        raise ProviderError(str(exc)) from exc
    try:
        return json.loads(of.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ProviderError(
            f"provider process wrote invalid JSON to {of}: {e}") from e

def run_text_command(command, prompt, run_dir, tag, timeout=None):
    """Run a headless command for a FREE-TEXT step through ProviderExecutor."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    pf = run_dir / f"{tag}_prompt.txt"
    of = run_dir / f"{tag}_out.md"
    pf.write_text(prompt, encoding="utf-8")
    cmd = command.format(prompt_file=str(pf), output_file=str(of), node=tag,
                         persona="Researcher", workspace="")
    try:
        DEFAULT_EXECUTOR.run(cmd, shell=True, timeout=timeout)
    except ProviderExecutionError as exc:
        raise ProviderError(str(exc)) from exc
    return of.read_text(encoding="utf-8")

@dataclass
class RunReceipt:
    node: str
    persona: str
    provider: str
    timestamp: str
    context_hash: str
    prompt_file: str | None = None
    prompt_hash: str | None = None
    delta_file: str | None = None
    delta_hash: str | None = None
    workspace: str = None
    allowed_tools: list = field(default_factory=list)
    everos_scope: list = field(default_factory=list)
    fresh_session: bool = None
    project_id: str | None = None
    candidate_id: str = None
    round_id: str | None = None
    profile_id: str | None = None
    context_manifest_path: str | None = None
    context_manifest_hash: str | None = None
    rendered_context_path: str | None = None
    rendered_context_hash: str | None = None
    provider_delta_path: str | None = None
    provider_delta_hash: str | None = None
    raw_provider_delta_path: str | None = None
    raw_provider_delta_hash: str | None = None
    transformation_receipt_path: str | None = None
    transformation_receipt_hash: str | None = None
    git_head: str | None = None
    git_dirty: bool | None = None
    working_tree_diff_sha256: str | None = None
    config_sha256: str | None = None
    code_state_id: str | None = None
    schema_version: str = "RunReceipt/v1"

    def validate(self):
        if self.schema_version not in {"RunReceipt/v1", "RunReceipt/v2"}:
            raise ValueError("RunReceipt schema_version must be 'RunReceipt/v1' or 'RunReceipt/v2'")
        for name in (
            "node", "persona", "provider", "timestamp", "context_hash",
            "project_id", "candidate_id", "round_id", "profile_id",
            "context_manifest_path", "context_manifest_hash",
            "rendered_context_path", "rendered_context_hash",
            "prompt_file", "prompt_hash", "provider_delta_path",
            "provider_delta_hash",
        ):
            if not str(getattr(self, name, "") or "").strip():
                raise ValueError(f"RunReceipt {name} is required")
        for name in (
            "context_hash", "context_manifest_hash", "rendered_context_hash",
            "prompt_hash", "delta_hash", "provider_delta_hash",
            "raw_provider_delta_hash", "transformation_receipt_hash",
        ):
            value = getattr(self, name, None)
            if value is not None and (
                not isinstance(value, str)
                or re.fullmatch(r"[0-9a-f]{64}", value) is None
            ):
                raise ValueError(f"RunReceipt {name} must be a SHA-256 hex digest")
        if self.rendered_context_hash and self.rendered_context_hash != self.context_hash:
            raise ValueError("RunReceipt rendered_context_hash must equal context_hash")
        if self.schema_version == "RunReceipt/v2":
            for name in (
                "git_head", "working_tree_diff_sha256", "config_sha256",
                "code_state_id", "raw_provider_delta_path",
                "raw_provider_delta_hash",
            ):
                if not str(getattr(self, name, "") or "").strip():
                    raise ValueError(f"RunReceipt {name} is required for v2")
            if not isinstance(self.git_dirty, bool):
                raise ValueError("RunReceipt git_dirty must be a bool for v2")
            if re.fullmatch(r"[0-9a-f]{40,64}", str(self.git_head)) is None:
                raise ValueError("RunReceipt git_head must be a Git object ID for v2")
            for name in ("working_tree_diff_sha256", "config_sha256", "code_state_id"):
                if re.fullmatch(r"[0-9a-f]{64}", str(getattr(self, name))) is None:
                    raise ValueError(f"RunReceipt {name} must be a SHA-256 hex digest for v2")
            if self.raw_provider_delta_path != self.provider_delta_path:
                for name in ("transformation_receipt_path", "transformation_receipt_hash"):
                    if not str(getattr(self, name, "") or "").strip():
                        raise ValueError(
                            f"RunReceipt {name} is required when provider delta is transformed"
                        )
        return self

    def write(self, path):
        self.validate()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False),
                     encoding="utf-8")
        return str(p)

    @classmethod
    def read(cls, path):
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid RunReceipt: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("invalid RunReceipt: expected object")
        try:
            return cls(**value).validate()
        except TypeError as exc:
            raise ValueError(f"invalid RunReceipt fields: {exc}") from exc

def now():
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
