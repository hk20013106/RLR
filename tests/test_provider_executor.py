"""Behavior and authority contracts for the R3 process boundary."""
from __future__ import annotations

import importlib
import sys
import threading
from pathlib import Path

import pytest


def _executor_module():
    return importlib.import_module("research_loop.providers.executor")


def _runner_module():
    return importlib.import_module("research_loop.process_runner")


class _StreamingObserver:
    def __init__(self) -> None:
        self.first_stdout = threading.Event()
        self.chunks: list[bytes] = []

    def on_stdout(self, chunk: bytes) -> None:
        self.chunks.append(bytes(chunk))
        if b"stream-ready" in b"".join(self.chunks):
            self.first_stdout.set()


def test_process_runner_streams_stdout_before_process_exit():
    module = _runner_module()
    runner = module.ProcessRunner()
    observer = _StreamingObserver()
    outcome: dict[str, object] = {}

    def invoke() -> None:
        outcome["result"] = runner.run(
            [
                sys.executable,
                "-c",
                "import time; print('stream-ready', flush=True); time.sleep(1.5); print('done')",
            ],
            timeout=5,
            observer=observer,
        )

    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()
    assert observer.first_stdout.wait(0.8), "stdout was buffered until process exit"
    assert thread.is_alive(), "process exited before streaming behavior could be observed"
    thread.join(timeout=5)
    assert not thread.is_alive()
    result = outcome["result"]
    assert result.returncode == 0
    assert "stream-ready" in result.stdout
    assert "done" in result.stdout


def test_process_runner_reports_hard_timeout_and_cleanup():
    module = _runner_module()
    result = module.ProcessRunner().run(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout=0.1,
    )
    assert result.terminal_state == "timed_out"
    assert result.process_tree_cleanup["attempted"] is True
    assert result.process_tree_cleanup["alive_after_cleanup"] is False


def test_provider_executor_is_thin_facade_over_process_runner():
    executor = _executor_module()
    runner = _runner_module()
    assert executor.ProcessRunner is runner.ProcessRunner
    assert "subprocess" not in Path(executor.__file__).read_text(encoding="utf-8")
    result = executor.ProviderExecutor().run(
        [sys.executable, "-c", "print('provider-ok')"], timeout=5
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "provider-ok"


def test_provider_executor_normalizes_nonzero_exit():
    module = _executor_module()
    with pytest.raises(module.ProviderExecutionError) as excinfo:
        module.ProviderExecutor().run(
            [
                sys.executable,
                "-c",
                "import sys; print('bad-out'); print('bad-err', file=sys.stderr); sys.exit(7)",
            ],
            timeout=5,
        )
    error = excinfo.value
    assert error.returncode == 7
    assert "bad-out" in error.stdout
    assert "bad-err" in error.stderr
    assert error.timed_out is False


def test_provider_executor_normalizes_timeout():
    module = _executor_module()
    with pytest.raises(module.ProviderExecutionError) as excinfo:
        module.ProviderExecutor().run(
            [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.1
        )
    error = excinfo.value
    assert error.timed_out is True
    assert error.timeout == 0.1


def test_external_execution_authority_is_not_duplicated_across_research_modules():
    root = Path(__file__).resolve().parents[1]
    paths = [
        "src/research_loop/providers/base.py",
        "src/research_loop/deep_research.py",
        "src/research_loop/l4_inventory.py",
        "src/research_loop/l4_pipeline.py",
        "src/research_loop/method_evidence.py",
        "src/research_loop/method_review_navigation.py",
        "src/research_loop/l05_curie/paperqa2_runtime.py",
    ]
    for relative in paths:
        source = (root / relative).read_text(encoding="utf-8")
        assert "subprocess.run(" not in source, relative
        assert "subprocess.Popen(" not in source, relative


def test_observability_is_not_a_process_owner():
    import research_loop.provider_runtime_observability as observability

    source = Path(observability.__file__).read_text(encoding="utf-8")
    assert "subprocess.Popen(" not in source
    assert "_SubprocessProxy" not in source
    assert "_BoundedReader" not in source


def test_maintenance_reuses_shared_process_runner_contract():
    runner = _runner_module()
    from rlr_maintenance import bounded_process

    assert bounded_process.ProcessRunner is runner.ProcessRunner
    result = bounded_process.run_bounded_process(
        [sys.executable, "-c", "print('maintenance-ok')"], timeout=5
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "maintenance-ok"
