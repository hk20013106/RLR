"""Acceptance contract for the single ProviderExecutor process boundary."""

import importlib
import sys
from pathlib import Path

import pytest


def _executor_module():
    return importlib.import_module("research_loop.providers.executor")


def test_provider_process_spawning_has_one_canonical_owner():
    root = Path(__file__).resolve().parents[1]
    executor_source = (root / "src/research_loop/providers/executor.py").read_text(
        encoding="utf-8"
    )
    observability_source = (
        root / "src/research_loop/provider_runtime_observability.py"
    ).read_text(encoding="utf-8")

    assert "subprocess.Popen(" in executor_source
    assert "_subprocess.Popen(" not in observability_source
    assert "_SubprocessProxy" not in observability_source


def test_provider_executor_captures_text_output():
    module = _executor_module()
    executor = module.ProviderExecutor()

    result = executor.run(
        [sys.executable, "-c", "print('provider-ok')"],
        timeout=10,
    )

    assert isinstance(result, module.ProviderExecutionResult)
    assert result.returncode == 0
    assert result.stdout.strip() == "provider-ok"
    assert result.stderr == ""


def test_provider_executor_normalizes_nonzero_exit():
    module = _executor_module()
    executor = module.ProviderExecutor()

    with pytest.raises(module.ProviderExecutionError) as excinfo:
        executor.run(
            [
                sys.executable,
                "-c",
                "import sys; print('bad-out'); print('bad-err', file=sys.stderr); sys.exit(7)",
            ],
            timeout=10,
        )

    error = excinfo.value
    assert error.returncode == 7
    assert "bad-out" in error.stdout
    assert "bad-err" in error.stderr
    assert error.timed_out is False


def test_provider_executor_normalizes_timeout():
    module = _executor_module()
    executor = module.ProviderExecutor()

    with pytest.raises(module.ProviderExecutionError) as excinfo:
        executor.run(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            timeout=0.05,
        )

    error = excinfo.value
    assert error.timed_out is True
    assert error.timeout == 0.05


def test_active_provider_and_deep_research_paths_use_executor_boundary():
    import research_loop.deep_research as deep_research
    import research_loop.providers.base as provider_base

    provider_source = Path(provider_base.__file__).read_text(encoding="utf-8")
    deep_source = Path(deep_research.__file__).read_text(encoding="utf-8")
    assert "subprocess.run(" not in provider_source
    assert "DEFAULT_EXECUTOR.run(" in provider_source
    assert "subprocess.run(" not in deep_source
    assert "DEFAULT_EXECUTOR.run(" in deep_source
    assert callable(deep_research.DEFAULT_EXECUTOR.run)
