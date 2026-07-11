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
import io
import json
from dataclasses import dataclass


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


class EngineAPI:
    """In-process facade over the RLR engine CLI.

    Construct once and reuse. `engine_main` is injectable (tests pass a fake);
    by default the real `research_loop_v04.main` is imported lazily on first use.
    """

    def __init__(self, engine_main=None):
        self._engine_main = engine_main

    def _main(self):
        if self._engine_main is None:
            import research_loop_v04
            self._engine_main = research_loop_v04.main
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

    def assemble_context(self, project, cand, node):
        """cmd_assemble_context: return (context_text, manifest_or_None). Raises
        RuntimeError (same message) on the fail-closed gate (rc != 0), preserving
        the hard-stop semantics — the runner never continues without context."""
        r = self.run_cli("assemble-context", project, cand, "--node", node)
        if r.returncode != 0:
            raise RuntimeError(f"assemble-context {node} failed: "
                               f"{r.stderr.strip() or r.stdout.strip()}")
        manifest = None
        for line in r.stderr.splitlines():
            if "context manifest:" in line:
                manifest = line.split("context manifest:", 1)[1].strip()
        return r.stdout, manifest

    def emit_delta(self, project, cand, node, persona, file, receipt=None) -> CtlResult:
        """cmd_emit_delta: validate+save a delta JSON file. Returns the raw
        CtlResult; the caller decides success by `returncode == 0` as before."""
        args = ["emit-delta", project, cand, "--node", node, "--persona", persona,
                "--file", str(file)]
        if receipt:
            args += ["--receipt", receipt]
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
