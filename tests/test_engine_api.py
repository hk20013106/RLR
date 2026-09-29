"""Phase 5 acceptance: EngineAPI in-process transport == subprocess, and the
typed methods parse exactly as the legacy run_loop helpers did.

Two guarantees are tested:
  1. TRANSPORT PARITY — `EngineAPI.run_cli(*argv)` reproduces, byte-for-byte,
     what `subprocess.run([python, research_loop_v04.py, *argv])` produced:
     same returncode, same stdout, same stderr. This is what lets run_loop swap
     the subprocess `_ctl()` for an in-process call with zero behavior change.
  2. SEMANTICS — SystemExit (argparse) is normalized to a return code just like
     a child process; typed methods (next_step / assemble_context / emit_delta)
     return / raise identically to the old run_loop code paths.

Fake-engine tests keep the parsing/normalization logic hermetic; the real
subprocess-vs-run_cli parity test proves the transport equivalence end-to-end on
actual engine commands (`--version`, `check-deps`).
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from research_loop.api import CtlResult, EngineAPI

REPO = Path(__file__).resolve().parent.parent
CONTROLLER = REPO / "research_loop_v04.py"


# --- transport: SystemExit / return-code normalization ----------------------

@pytest.mark.parametrize("raised, expected_rc", [
    (SystemExit(2), 2),      # argparse error
    (SystemExit(None), 0),   # --help / --version style clean exit
    (SystemExit("boom"), 1),  # non-int exit code -> 1 (process would be 1)
])
def test_run_cli_normalizes_systemexit(raised, expected_rc):
    def fake_main(argv):
        raise raised
    r = EngineAPI(engine_main=fake_main).run_cli("whatever")
    assert isinstance(r, CtlResult)
    assert r.returncode == expected_rc


@pytest.mark.parametrize("ret, expected_rc", [(0, 0), (3, 3), (None, 0)])
def test_run_cli_passes_through_returncode(ret, expected_rc):
    r = EngineAPI(engine_main=lambda argv: ret).run_cli("x")
    assert r.returncode == expected_rc


def test_run_cli_captures_stdout_and_stderr():
    def fake_main(argv):
        print("to-out")
        print("to-err", file=sys.stderr)
        return 3
    r = EngineAPI(engine_main=fake_main).run_cli("cmd", "arg")
    assert r.returncode == 3
    assert r.stdout == "to-out\n"
    assert r.stderr == "to-err\n"


def test_run_cli_forwards_argv_verbatim():
    seen = {}
    def fake_main(argv):
        seen["argv"] = argv
        return 0
    EngineAPI(engine_main=fake_main).run_cli("emit-delta", "P", "C", "--node", "L0")
    assert seen["argv"] == ["emit-delta", "P", "C", "--node", "L0"]


def test_run_cli_normalizes_pathlike_before_real_argparse(tmp_path):
    project_path = tmp_path / "project"
    try:
        result = EngineAPI().run_cli("audit-pre-research", project_path)
    except TypeError as exc:
        pytest.fail(
            "run_cli passed pathlib.Path to the real argparse parser without "
            f"converting it to a CLI string: {exc}"
        )

    assert result.returncode == 0
    assert Path(json.loads(result.stdout)["project_dir"]) == project_path


# --- typed methods: same parse / raise as the old run_loop helpers -----------

def test_next_step_parses_json():
    api = EngineAPI(engine_main=lambda argv: print('{"node": "L1"}') or 0)
    assert api.next_step("P", "C") == {"node": "L1"}


def test_next_step_raises_on_non_json():
    api = EngineAPI(engine_main=lambda argv: print("not json") or 0)
    with pytest.raises(RuntimeError, match="did not return JSON"):
        api.next_step("P", "C")


def test_assemble_context_raises_on_gate_failure():
    """rc != 0 (fail-closed gate, e.g. rc=3) must raise — the runner never
    continues without context."""
    def fake_main(argv):
        print("GATE: pre-research missing", file=sys.stderr)
        return 3
    api = EngineAPI(engine_main=fake_main)
    with pytest.raises(RuntimeError, match="assemble-context L1 failed"):
        api.assemble_context("P", "C", "L1")


def test_assemble_context_reads_manifest_owned_rendered_context(tmp_path):
    rendered = tmp_path / "rendered_context.txt"
    rendered.write_bytes(b"<<context body>>\r\n")

    def fake_main(argv):
        print("<<context body>>")
        manifest = tmp_path / "context_manifest.json"
        manifest.write_text(json.dumps({
            "rendered_context_path": str(rendered),
            "rendered_context_sha256": hashlib.sha256(
                rendered.read_bytes()
            ).hexdigest(),
        }), encoding="utf-8")
        print(f"context manifest: {manifest}", file=sys.stderr)
        return 0
    ctx, manifest = EngineAPI(engine_main=fake_main).assemble_context(
        "P", "C", "L2"
    )
    assert ctx.encode("utf-8") == rendered.read_bytes()
    assert manifest == str(tmp_path / "context_manifest.json")


def test_emit_delta_builds_argv_and_returns_result():
    seen = {}
    def fake_main(argv):
        seen["argv"] = argv
        return 0
    api = EngineAPI(engine_main=fake_main)
    r = api.emit_delta("P", "C", "L0", "Linnaeus", "/tmp/d.json", receipt="RCPT")
    assert r.returncode == 0
    assert seen["argv"] == ["emit-delta", "P", "C", "--node", "L0",
                            "--persona", "Linnaeus", "--file", "/tmp/d.json",
                            "--receipt", "RCPT"]


def test_emit_delta_omits_receipt_when_absent():
    seen = {}
    def fake_main(argv):
        seen["argv"] = argv
        return 0
    EngineAPI(engine_main=fake_main).emit_delta("P", "C", "L0", "Linnaeus",
                                                "/tmp/d.json")
    assert "--receipt" not in seen["argv"]


def test_emit_delta_normalizes_pathlike_argv_before_argparse(tmp_path):
    from research_loop.cli import build_parser

    seen = {"argv": [], "parsed": []}

    def parse_with_real_cli_parser(argv):
        seen["argv"].append(list(argv))
        seen["parsed"].append(build_parser().parse_args(argv))
        return 0

    api = EngineAPI(engine_main=parse_with_real_cli_parser)
    delta_path = tmp_path / "delta.json"
    context_manifest = tmp_path / "context-manifest.json"
    provider_receipt = tmp_path / "provider-receipt.json"
    api.emit_delta(
        "P", "C", "L0", "Linnaeus", delta_path,
        context_manifest=context_manifest,
        provider_receipt=provider_receipt,
    )

    project_path = tmp_path / "project"
    legacy_receipt = tmp_path / "legacy-receipt.json"
    api.emit_delta(
        project_path, "C", "L0", "Linnaeus", delta_path,
        receipt=legacy_receipt,
    )

    assert seen["argv"] == [
        [
            "emit-delta", "P", "C", "--node", "L0", "--persona", "Linnaeus",
            "--file", str(delta_path),
            "--context-manifest", str(context_manifest),
            "--provider-receipt", str(provider_receipt),
        ],
        [
            "emit-delta", str(project_path), "C", "--node", "L0", "--persona",
            "Linnaeus", "--file", str(delta_path), "--receipt", str(legacy_receipt),
        ],
    ]
    assert all(
        isinstance(argument, str)
        for argv in seen["argv"]
        for argument in argv
    )
    assert seen["parsed"][0].context_manifest == str(context_manifest)
    assert seen["parsed"][0].provider_receipt == str(provider_receipt)
    assert seen["parsed"][1].project_dir == str(project_path)
    assert seen["parsed"][1].receipt == str(legacy_receipt)


def test_default_engine_main_is_the_real_controller():
    """With no injection, the facade lazily binds to research_loop_v04.main."""
    import research_loop_v04
    api = EngineAPI()
    assert api._main() is research_loop_v04.main


# --- end-to-end transport parity: run_cli == subprocess ----------------------

def _subprocess(*argv):
    return subprocess.run([sys.executable, str(CONTROLLER), *argv],
                          capture_output=True, text=True)


@pytest.mark.parametrize("argv", [("--version",), ("check-deps",)])
def test_run_cli_matches_subprocess(argv):
    """The load-bearing guarantee: an in-process command yields the SAME
    (returncode, stdout, stderr) as spawning the controller as a child."""
    child = _subprocess(*argv)
    inproc = EngineAPI().run_cli(*argv)
    assert inproc.returncode == child.returncode
    assert inproc.stdout == child.stdout
    assert inproc.stderr == child.stderr
