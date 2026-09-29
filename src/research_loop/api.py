"""research_loop.api — in-process EngineAPI facade (Phase 5).

The PRIMARY stable interface between the loop runner (`run_loop.py`) and the
engine. It replaces the fragile `subprocess.run([python, research_loop_v04.py,
*args])` transport with an in-process call into the engine's `main(argv)` —
**same entry point, no serialization, no JSON-RPC** (plan §3.1, §10; Rev-2 C5).

Why this is byte-for-byte equivalent to the old subprocess:
  * `run_cli()` invokes the identical `research_loop_v04.main(argv)` the CLI runs,
    under `redirect_stdout`/`redirect_stderr`, and normalizes `SystemExit` to a
    return code exactly as a child process would surface it.
  * The engine has no process-global mutable state (no lru_cache, no module-level
    mutable dict/list, no chdir/sys.argv use; the only caches are file-based and
    project-scoped), so reusing one interpreter across calls cannot drift from a
    fresh-process-per-call model.

`CtlResult` mirrors the `.returncode/.stdout/.stderr` surface of
`subprocess.CompletedProcess`, so existing run_loop callsites read it unchanged.
Typed methods (`next_step`, `assemble_context`, …) layer the exact parsing the
runner already did onto that transport.

This module does NOT import the engine at import time — the engine entry point is
resolved lazily (or injected), keeping the dependency pointing inward and letting
Phase 6 repoint it to `research_loop.engine`/`research_loop.cli` with no churn.
"""
import contextlib
import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CtlResult:
    """In-process stand-in for subprocess.CompletedProcess (the fields run_loop
    reads). `returncode` is always an int; `stdout`/`stderr` are captured text."""
    returncode: int
    stdout: str
    stderr: str


def _norm_exit(code) -> int:
    """Map a SystemExit code to a process-style return code (argparse errors
    raise SystemExit(2); --help/--version raise SystemExit(0); None -> 0)."""
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1


def load_rendered_context_artifact(manifest_path):
    """Load the manifest-owned context bytes without using stdout as an artifact.

    Returns ``(manifest, rendered_path, rendered_bytes, rendered_text)``.  The
    caller receives the exact persisted bytes after the manifest hash is
    verified, preserving the context artifact's single canonical identity.
    """
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"context manifest is unreadable: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("context manifest must be a JSON object")
    rendered_path = Path(str(manifest.get("rendered_context_path") or ""))
    if not rendered_path.is_file():
        raise ValueError("context manifest rendered context is missing")
    try:
        rendered_bytes = rendered_path.read_bytes()
    except OSError as exc:
        raise ValueError("context manifest rendered context is unreadable") from exc
    rendered_hash = hashlib.sha256(rendered_bytes).hexdigest()
    if rendered_hash != manifest.get("rendered_context_sha256"):
        raise ValueError("context manifest rendered context hash is invalid")
    try:
        rendered_text = rendered_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("context manifest rendered context is not valid UTF-8") from exc
    return manifest, rendered_path, rendered_bytes, rendered_text


class EngineAPI:
    """In-process facade over the RLR engine CLI.

    Construct once and reuse. `engine_main` is injectable (tests pass a fake);
    by default the real `research_loop_v04.main` is imported lazily on first use.
    """

    def __init__(self, engine_main=None):
        self._engine_main = engine_main

    def _main(self):
        if self._engine_main is None:
            from research_loop.engine import main  # inward dep (Phase 6)
            self._engine_main = main
        return self._engine_main

    # --- transport core ------------------------------------------------------

    def run_cli(self, *argv) -> CtlResult:
        """Run one engine command in-process and capture (rc, stdout, stderr),
        exactly as `subprocess.run([python, controller, *argv], capture_output=
        True, text=True)` would. Never raises for a non-zero command; SystemExit
        (argparse) is normalized to `returncode` just like a child process."""
        out, err = io.StringIO(), io.StringIO()
        rc = 0
        main = self._main()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = main(list(argv))
            except SystemExit as e:  # argparse / --help / --version
                rc = _norm_exit(e.code)
        return CtlResult(0 if rc is None else int(rc),
                         out.getvalue(), err.getvalue())

    # --- typed methods (parsing identical to the legacy run_loop helpers) -----

    def next_step(self, project, cand) -> dict:
        """cmd_next_step: return the parsed JSON step. Raises RuntimeError with
        the same message run_loop used when the command does not emit JSON."""
        r = self.run_cli("next-step", project, cand)
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"next-step did not return JSON: "
                               f"{r.stdout!r} {r.stderr!r}")

    def assemble_context(self, project, cand, node, authorization_id=None,
                         evidence_run_id=None, context_token_budget=None):
        """Return the manifest-owned rendered context and its manifest path.

        Successful context assembly must identify a persisted artifact.  stdout
        remains a diagnostic/CLI view and is never used as the context artifact
        when the manifest is present.
        """
        args = ["assemble-context", project, cand, "--node", node]
        if authorization_id:
            args.extend(["--authorization-id", authorization_id])
        if evidence_run_id:
            args.extend(["--evidence-run-id", evidence_run_id])
        if context_token_budget is not None:
            args.extend(["--context-token-budget", str(context_token_budget)])
        r = self.run_cli(*args)
        if r.returncode != 0:
            raise RuntimeError(f"assemble-context {node} failed: "
                               f"{r.stderr.strip() or r.stdout.strip()}")
        manifest = None
        for line in r.stderr.splitlines():
            if "context manifest:" in line:
                manifest = line.split("context manifest:", 1)[1].strip()
        if not manifest:
            raise RuntimeError(
                f"assemble-context {node} did not report a rendered context manifest"
            )
        try:
            _, _, _, context = load_rendered_context_artifact(manifest)
        except ValueError as exc:
            raise RuntimeError(
                f"assemble-context {node} rendered artifact invalid: {exc}"
            ) from exc
        return context, manifest

    def emit_delta(self, project, cand, node, persona, file, receipt=None,
                   context_manifest=None, provider_receipt=None) -> CtlResult:
        """cmd_emit_delta: validate+save a delta JSON file. Returns the raw
        CtlResult; the caller decides success by `returncode == 0` as before."""
        args = ["emit-delta", str(project), cand, "--node", node, "--persona", persona,
                "--file", str(file)]
        if context_manifest:
            args += ["--context-manifest", str(context_manifest)]
        elif receipt:
            args += ["--receipt", str(receipt)]
        if provider_receipt:
            args += ["--provider-receipt", str(provider_receipt)]
        return self.run_cli(*args)

    def decision(self, project, cand, status, reason, route=None) -> CtlResult:
        args = ["decision", project, cand, "--status", status, "--reason", reason]
        if route:
            args += ["--route", route]
        return self.run_cli(*args)

    def aggregate_report(self, project, cand) -> CtlResult:
        return self.run_cli("aggregate-report", project, cand)

    def check_deps(self, project=None) -> CtlResult:
        return self.run_cli("check-deps", project) if project \
            else self.run_cli("check-deps")

    def emit_loop_memory(self, project, cand) -> CtlResult:
        return self.run_cli("emit-loop-memory", project, cand)

    # --- durable current-host handoff --------------------------------------

    def prepare_host_request(self, project, *, kind, identity, inputs,
                             tools_policy, output_contract) -> dict:
        """Persist one immutable request through the host-handoff owner."""
        from research_loop.host_handoff import prepare_request

        return prepare_request(
            project,
            kind=kind,
            identity=identity,
            inputs=inputs,
            tools_policy=tools_policy,
            output_contract=output_contract,
        )

    def load_host_request(self, project, request_id) -> dict:
        """Reload one already-persisted host request by its stable ID."""
        from research_loop.host_handoff import load_request

        return load_request(project, request_id)

    def load_host_request_for_identity(self, project, identity) -> dict | None:
        """Reload the immutable request already occupying an action's slot."""
        from research_loop.host_handoff import load_request_for_identity

        return load_request_for_identity(project, identity)

    def load_host_response_receipt(self, project, request_id, *, expected_cursor) -> dict | None:
        """Reload a response only when its request binding and raw bytes still verify."""
        from research_loop.host_handoff import load_response_receipt

        return load_response_receipt(
            project, request_id, expected_cursor=expected_cursor
        )

    def submit_host_response(self, project, request_id, response_path, *,
                             expected_cursor) -> dict:
        """Persist an exact host response under the request's compare-and-set."""
        from research_loop.host_handoff import submit_response

        return submit_response(
            project,
            request_id,
            response_path,
            expected_cursor=expected_cursor,
        )

    @contextlib.contextmanager
    def host_step_commit_lock(self, project, request_id):
        """Serialize short native validation/emit/advance commits per request."""
        from research_loop.host_handoff import HostHandoffError, _short_lock

        if not re.fullmatch(r"[0-9a-f]{64}", str(request_id)):
            raise HostHandoffError("host request ID must be a SHA-256 digest")
        root = Path(project).resolve(strict=True)
        lock_path = (
            root / "08_Audit" / "host_handoff" / "locks"
            / f"commit-{request_id}.lock"
        ).resolve(strict=False)
        try:
            lock_path.relative_to(root)
        except ValueError as exc:
            raise HostHandoffError(
                "host step commit lock path escapes the project"
            ) from exc
        with _short_lock(lock_path):
            yield
