"""Test-only support for canonical native ProjectReady bootstrap fixtures."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def install(native_helpers) -> None:
    """Give positive ProjectReady fixtures one scoped inert Codex sentinel."""
    if getattr(native_helpers, "_project_ready_support_installed", False):
        return

    original = native_helpers.bootstrap_project_ready

    def bootstrap_project_ready(*args, extra_env=None, **kwargs):
        env = dict(extra_env or {})
        current_path = str(os.environ.get("PATH") or "")
        captured_path = str(env.get("PATH") or "")
        inherited_path = current_path + (
            os.pathsep + captured_path
            if captured_path and captured_path != current_path
            else ""
        )
        with tempfile.TemporaryDirectory(prefix="rlr-project-ready-provider-") as temp_dir:
            bin_dir = Path(temp_dir)
            executable = bin_dir / ("codex.exe" if os.name == "nt" else "codex")
            executable.write_text(
                "test-only project-ready provider sentinel\n", encoding="utf-8"
            )
            if os.name != "nt":
                executable.chmod(0o755)
            env["PATH"] = str(bin_dir) + (
                os.pathsep + inherited_path if inherited_path else ""
            )
            return original(*args, extra_env=env, **kwargs)

    native_helpers.bootstrap_project_ready = bootstrap_project_ready
    native_helpers._project_ready_support_installed = True
