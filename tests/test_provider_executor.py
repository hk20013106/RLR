import importlib
import sys

import pytest


def _executor_module():
    return importlib.import_module("research_loop.providers.executor")


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


def test_core_external_runtime_modules_do_not_call_subprocess_run_directly():
    from pathlib import Path
    import research_loop.deep_research as deep_research
    import research_loop.providers.base as provider_base

    for module in (deep_research, provider_base):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "subprocess.run(" not in source
