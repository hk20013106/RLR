"""Provider foundation: interfaces, shared command runners, and run receipts.

This module does not import the engine. External execution delegates retry
mechanics to the existing :mod:`research_loop.external_resilience` owner.
"""
import hashlib
import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
import datetime as _dt

from research_loop import external_resilience
from research_loop.providers.executor import DEFAULT_EXECUTOR, ProviderExecutionError


class ProviderError(Exception):
    """Raised when a provider invocation cannot satisfy its runtime contract."""

    def __init__(self, message, *, returncode=None, timed_out=None,
                 terminal_state=None):
        super().__init__(message)
        # These values are copied from ProviderExecutionError. They are
        # intentionally not inferred from the exception text.
        self.returncode = returncode
        self.timed_out = timed_out
        self.terminal_state = terminal_state


class ProviderOutputContractError(ProviderError):
    """Provider execution completed, but its persisted output contract failed."""


class AgentProvider:
    """Provider interface. Subclasses turn (node, persona, context) into a delta
    dict using whatever backend they wrap."""

    type = "base"
    name = "base"

    def run_agent(self, node, persona, context, output_schema=None,
                  workspace=None, tools=None, run_dir=None):
        raise NotImplementedError

    def run_text(self, prompt, run_dir, tag, timeout=None):
        raise ProviderError(
            f"provider {self.name!r} does not support free-text execution"
        )


def _render_command_template(command, *, prompt_file, output_file, node,
                             persona, workspace):
    """Render a command template with the same Python formatting used at runtime."""
    return command.format(
        prompt_file=prompt_file,
        output_file=output_file,
        node=node,
        persona=persona,
        workspace=workspace,
    )


def _validate_command_template(command, provider_name):
    """Render once with inert strings to catch static template errors only."""
    if not isinstance(command, str):
        raise ProviderError(
            f"invalid command template for {provider_name} provider: "
            f"expected a string, got {type(command).__name__}"
        )
    try:
        _render_command_template(
            command,
            prompt_file="RLR_PREFLIGHT_PROMPT_FILE",
            output_file="RLR_PREFLIGHT_OUTPUT_FILE",
            node="RLR_PREFLIGHT_NODE",
            persona="RLR_PREFLIGHT_PERSONA",
            workspace="RLR_PREFLIGHT_WORKSPACE",
        )
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise ProviderError(
            f"invalid command template for {provider_name} provider: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

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
    if node == "L4":
        lines.extend([
            "# L4 method-input contract:",
            "# For every method candidate, separate required_inputs from optional_diagnostics.",
            "# Missing source means exact method evidence only; never put missing user data there.",
            "# If an executable candidate lacks required user data, use needs_user_data and list missing_inputs.",
        ])
    if output_schema:
        lines += ["# JSON delta schema:",
                  json.dumps(_schema_repr(output_schema), indent=2,
                             ensure_ascii=False)]
    lines += ["", "=== CONTEXT ===", context]
    return "\n".join(lines)


def provider_attempt_path(run_dir, node, persona, artifact, suffix, attempt):
    """Return the stable path for one logical provider invocation attempt."""
    if (not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1):
        raise ValueError("provider attempt must be a positive integer")
    marker = "" if attempt == 1 else f".{attempt}"
    return Path(run_dir) / f"{node}_{persona}_{artifact}{marker}{suffix}"


def _reserve_provider_attempt(run_dir, node, persona, prompt_text):
    """Reserve an append-only logical invocation slot using the prompt file."""
    for attempt in range(1, 1000):
        prompt_path = provider_attempt_path(
            run_dir, node, persona, "prompt", ".txt", attempt
        )
        output_path = provider_attempt_path(
            run_dir, node, persona, "delta", ".json", attempt
        )
        receipt_path = provider_attempt_path(
            run_dir, node, persona, "receipt", ".json", attempt
        )
        if output_path.exists() or receipt_path.exists():
            continue
        try:
            with prompt_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(prompt_text)
        except FileExistsError:
            continue
        return attempt, prompt_path, output_path
    raise ProviderError(
        f"unable to reserve provider attempt for {node}/{persona} in {run_dir}"
    )


def _run_command_agent(command, node, persona, context, output_schema,
                       workspace, tools, run_dir, timeout, provider):
    """Shared body for command-style providers using the ProviderExecutor boundary."""
    run_dir = Path(run_dir or ".")
    run_dir.mkdir(parents=True, exist_ok=True)
    provider.last_attempt_number = None
    prompt_text = _compose_auto_prompt(
        node, persona, context, output_schema, workspace, tools
    )
    attempt, pf, of = _reserve_provider_attempt(
        run_dir, node, persona, prompt_text
    )
    provider.last_attempt_number = attempt
    provider.last_prompt_file = str(pf)
    provider.last_delta_file = str(of)
    provider.last_exit_code = None
    provider.last_timed_out = None
    provider.last_terminal_state = None
    provider.last_execution_status = None
    cmd = _render_command_template(
        command, prompt_file=str(pf), output_file=str(of), node=node,
        persona=persona, workspace=workspace or "",
    )

    def execute_once():
        try:
            of.unlink(missing_ok=True)
        except OSError as exc:
            raise ProviderError(
                f"provider output could not be reset before execution at {of}: {exc}"
            ) from exc
        return DEFAULT_EXECUTOR.run(
            cmd, shell=True, timeout=timeout, check=True
        )

    try:
        result = external_resilience.run_provider_with_retry(
            execute_once
        )
        provider.last_exit_code = result.returncode
        provider.last_timed_out = result.timed_out
        provider.last_terminal_state = result.terminal_state
        provider.last_execution_status = "succeeded"
    except ProviderExecutionError as exc:
        provider.last_exit_code = exc.returncode
        provider.last_timed_out = exc.timed_out
        provider.last_terminal_state = exc.terminal_state or None
        provider.last_execution_status = "failed"
        raise ProviderError(
            str(exc), returncode=exc.returncode, timed_out=exc.timed_out,
            terminal_state=exc.terminal_state or None,
        ) from exc
    try:
        raw_output = of.read_text(encoding="utf-8")
    except OSError as exc:
        provider.last_execution_status = "failed"
        raise ProviderOutputContractError(
            f"provider output artifact is unreadable at {of}: {exc}",
            returncode=provider.last_exit_code,
            timed_out=provider.last_timed_out,
            terminal_state=provider.last_terminal_state,
        ) from exc
    try:
        return json.loads(raw_output)
    except json.JSONDecodeError as exc:
        provider.last_execution_status = "failed"
        raise ProviderOutputContractError(
            f"provider output artifact failed JSON contract at {of}: {exc}",
            returncode=provider.last_exit_code,
            timed_out=provider.last_timed_out,
            terminal_state=provider.last_terminal_state,
        ) from exc

def run_text_command(command, prompt, run_dir, tag, timeout=None):
    """Run a headless command for a FREE-TEXT step through ProviderExecutor."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    pf = run_dir / f"{tag}_prompt.txt"
    of = run_dir / f"{tag}_out.md"
    pf.write_text(prompt, encoding="utf-8")
    cmd = _render_command_template(
        command, prompt_file=str(pf), output_file=str(of), node=tag,
        persona="Researcher", workspace="",
    )

    def execute_once():
        try:
            of.unlink(missing_ok=True)
        except OSError as exc:
            raise ProviderError(
                f"provider output could not be reset before execution at {of}: {exc}"
            ) from exc
        return DEFAULT_EXECUTOR.run(
            cmd, shell=True, timeout=timeout, check=True
        )

    try:
        external_resilience.run_provider_with_retry(
            execute_once
        )
    except ProviderExecutionError as exc:
        raise ProviderError(
            str(exc), returncode=exc.returncode, timed_out=exc.timed_out,
            terminal_state=exc.terminal_state or None,
        ) from exc
    try:
        return of.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProviderError(
            f"provider process did not produce readable text at {of}: {exc}"
        ) from exc

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
    host_request_path: str | None = None
    host_request_hash: str | None = None
    raw_response_path: str | None = None
    raw_response_hash: str | None = None
    canonical_delta_path: str | None = None
    canonical_delta_hash: str | None = None
    host_session_id: str | None = None
    host_session_id_source: str | None = None
    schema_version: str = "RunReceipt/v1"
    exit_code: int | None = None
    timed_out: bool | None = None
    terminal_state: str | None = None
    execution_status: str | None = None

    def validate(self):
        if self.schema_version not in {
            "RunReceipt/v1", "RunReceipt/v2", "RunReceipt/v3-host"
        }:
            raise ValueError(
                "RunReceipt schema_version must be 'RunReceipt/v1', "
                "'RunReceipt/v2', or 'RunReceipt/v3-host'"
            )
        common_required = (
            "node", "persona", "provider", "timestamp", "context_hash",
            "project_id", "candidate_id", "round_id", "profile_id",
            "context_manifest_path", "context_manifest_hash",
            "rendered_context_path", "rendered_context_hash",
        )
        required = common_required if self.schema_version == "RunReceipt/v3-host" else (
            *common_required, "prompt_file", "prompt_hash"
        )
        for name in required:
            if not str(getattr(self, name, "") or "").strip():
                raise ValueError(f"RunReceipt {name} is required")
        has_provider_delta = bool(str(self.provider_delta_path or "").strip())
        if not has_provider_delta and self.execution_status != "failed":
            raise ValueError("RunReceipt provider_delta_path is required")
        if has_provider_delta and not str(self.provider_delta_hash or "").strip():
            raise ValueError("RunReceipt provider_delta_hash is required")
        if self.execution_status is not None and self.execution_status not in {
            "succeeded", "failed"
        }:
            raise ValueError("RunReceipt execution_status must be 'succeeded' or 'failed'")
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise ValueError("RunReceipt exit_code must be an integer or null")
        if self.timed_out is not None and not isinstance(self.timed_out, bool):
            raise ValueError("RunReceipt timed_out must be a bool or null")
        if self.terminal_state is not None and not str(self.terminal_state).strip():
            raise ValueError("RunReceipt terminal_state must be non-empty or null")
        for name in (
            "context_hash", "context_manifest_hash", "rendered_context_hash",
            "prompt_hash", "delta_hash", "provider_delta_hash",
            "raw_provider_delta_hash", "transformation_receipt_hash",
            "host_request_hash", "raw_response_hash", "canonical_delta_hash",
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
                "code_state_id",
            ):
                if not str(getattr(self, name, "") or "").strip():
                    raise ValueError(f"RunReceipt {name} is required for v2")
            if has_provider_delta:
                for name in ("raw_provider_delta_path", "raw_provider_delta_hash"):
                    if not str(getattr(self, name, "") or "").strip():
                        raise ValueError(f"RunReceipt {name} is required for v2")
            if not isinstance(self.git_dirty, bool):
                raise ValueError("RunReceipt git_dirty must be a bool for v2")
            if re.fullmatch(r"[0-9a-f]{40,64}", str(self.git_head)) is None:
                raise ValueError("RunReceipt git_head must be a Git object ID for v2")
            for name in ("working_tree_diff_sha256", "config_sha256", "code_state_id"):
                if re.fullmatch(r"[0-9a-f]{64}", str(getattr(self, name))) is None:
                    raise ValueError(f"RunReceipt {name} must be a SHA-256 hex digest for v2")
            if has_provider_delta and self.raw_provider_delta_path != self.provider_delta_path:
                for name in ("transformation_receipt_path", "transformation_receipt_hash"):
                    if not str(getattr(self, name, "") or "").strip():
                        raise ValueError(
                            f"RunReceipt {name} is required when provider delta is transformed"
                        )
        if self.schema_version == "RunReceipt/v3-host":
            for name in (
                "host_request_path", "host_request_hash", "raw_response_path",
                "raw_response_hash", "canonical_delta_path",
                "canonical_delta_hash",
                "host_session_id_source", "git_head",
                "working_tree_diff_sha256", "config_sha256", "code_state_id",
            ):
                if not str(getattr(self, name, "") or "").strip():
                    raise ValueError(f"RunReceipt {name} is required for v3-host")
            if self.host_session_id_source not in {
                "verified", "declared", "unavailable"
            }:
                raise ValueError(
                    "RunReceipt host_session_id_source must be verified, declared, or unavailable"
                )
            if self.host_session_id_source in {"verified", "declared"}:
                if not str(self.host_session_id or "").strip():
                    raise ValueError(
                        "RunReceipt host_session_id is required for verified or declared source"
                    )
            elif self.host_session_id is not None and str(self.host_session_id).strip():
                raise ValueError(
                    "RunReceipt unavailable host_session_id_source cannot claim a session ID"
                )
            if self.provider != "host_session":
                raise ValueError("RunReceipt v3-host provider must be host_session")
            if self.fresh_session is not None:
                raise ValueError(
                    "RunReceipt v3-host cannot claim physical fresh-session state"
                )
            if not isinstance(self.git_dirty, bool):
                raise ValueError("RunReceipt git_dirty must be a bool for v3-host")
            if re.fullmatch(r"[0-9a-f]{40,64}", str(self.git_head)) is None:
                raise ValueError("RunReceipt git_head must be a Git object ID for v3-host")
            for name in (
                "working_tree_diff_sha256", "config_sha256", "code_state_id"
            ):
                if re.fullmatch(r"[0-9a-f]{64}", str(getattr(self, name))) is None:
                    raise ValueError(
                        f"RunReceipt {name} must be a SHA-256 hex digest for v3-host"
                    )
            if self.exit_code is not None or self.timed_out is not None:
                raise ValueError(
                    "RunReceipt v3-host cannot claim subprocess exit or timeout data"
                )
            if self.terminal_state is not None or self.execution_status is not None:
                raise ValueError(
                    "RunReceipt v3-host cannot claim subprocess execution state"
                )
            if (
                self.provider_delta_path != self.canonical_delta_path
                or self.provider_delta_hash != self.canonical_delta_hash
            ):
                raise ValueError(
                    "RunReceipt v3-host canonical delta must match provider delta"
                )
            self._validate_host_artifacts()
        return self

    def _validate_host_artifacts(self):
        """Bind v3-host identity and hashes to the exact persisted artifacts."""
        artifacts = (
            ("context manifest", self.context_manifest_path,
             self.context_manifest_hash),
            ("host request", self.host_request_path, self.host_request_hash),
            ("raw response", self.raw_response_path, self.raw_response_hash),
            ("canonical delta", self.canonical_delta_path,
             self.canonical_delta_hash),
            ("rendered context", self.rendered_context_path,
             self.rendered_context_hash),
        )
        for label, raw_path, expected_hash in artifacts:
            try:
                raw = Path(str(raw_path)).read_bytes()
            except OSError as exc:
                raise ValueError(
                    f"RunReceipt {label} is missing or unreadable"
                ) from exc
            if hashlib.sha256(raw).hexdigest() != expected_hash:
                raise ValueError(
                    f"RunReceipt {label} hash does not match artifact bytes"
                )

        def read_json(path, label):
            try:
                value = json.loads(Path(str(path)).read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"RunReceipt {label} is unreadable: {exc}"
                ) from exc
            if not isinstance(value, dict):
                raise ValueError(f"RunReceipt {label} must contain a JSON object")
            return value

        request = read_json(self.host_request_path, "host request")
        manifest = read_json(self.context_manifest_path, "context manifest")
        request_body_fields = (
            "schema_version", "kind", "identity", "inputs", "tools_policy",
            "output_contract",
        )
        if (
            any(name not in request for name in request_body_fields)
            or set(request) != {*request_body_fields, "request_id"}
        ):
            raise ValueError("RunReceipt v3-host request lacks canonical request fields")
        request_body = {name: request[name] for name in request_body_fields}
        expected_request_id = hashlib.sha256(json.dumps(
            request_body, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
        if request.get("request_id") != expected_request_id:
            raise ValueError(
                "RunReceipt v3-host request ID does not match canonical request content"
            )
        identity = request.get("identity") or request
        inputs = request.get("inputs") or {}
        expected = {
            "project_id": self.project_id,
            "candidate_id": self.candidate_id,
            "round_id": self.round_id,
            "node": self.node,
            "persona": self.persona,
            "profile_id": self.profile_id,
        }
        for field_name, expected_value in expected.items():
            if (
                identity.get(field_name) != expected_value
                or manifest.get(field_name) != expected_value
            ):
                raise ValueError(
                    f"RunReceipt v3-host {field_name} does not match request/context"
                )
        request_context_hash = (
            request.get("context_hash")
            or inputs.get("context_hash")
            or inputs.get("rendered_context_sha256")
        )
        if request_context_hash != self.context_hash:
            raise ValueError(
                "RunReceipt v3-host context hash does not match host request"
            )
        if manifest.get("rendered_context_sha256") != self.context_hash:
            raise ValueError(
                "RunReceipt v3-host context hash does not match manifest"
            )
        request_policy = request.get("tools_policy")
        if (
            request_policy is not None
            and (
                self.allowed_tools != [request_policy]
                or manifest.get("tools_policy") != request_policy
            )
        ):
            raise ValueError(
                "RunReceipt v3-host tool policy does not match request/context"
            )
        for field_name, expected_value in {
            "context_manifest_path": self.context_manifest_path,
            "context_manifest_sha256": self.context_manifest_hash,
            "rendered_context_path": self.rendered_context_path,
            "rendered_context_sha256": self.rendered_context_hash,
        }.items():
            if field_name not in inputs:
                raise ValueError(
                    f"RunReceipt v3-host host request lacks {field_name} binding"
                )
            if str(inputs[field_name]) != str(expected_value):
                raise ValueError(
                    f"RunReceipt v3-host {field_name} does not match host request"
                )

    def write(self, path):
        self.validate()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        value = asdict(self)
        if self.schema_version != "RunReceipt/v3-host":
            for name in (
                "host_request_path", "host_request_hash", "raw_response_path",
                "raw_response_hash", "canonical_delta_path",
                "canonical_delta_hash", "host_session_id",
                "host_session_id_source",
            ):
                value.pop(name, None)
        p.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
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
