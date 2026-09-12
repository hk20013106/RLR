"""Test-only support for canonical native ProjectReady bootstrap fixtures."""
from __future__ import annotations

import os


def install(native_helpers) -> None:
    """Keep the scoped provider sentinel ahead of caller-captured PATH values."""
    if getattr(native_helpers, "_project_ready_support_installed", False):
        return

    original = native_helpers.bootstrap_project_ready

    def bootstrap_project_ready(*args, extra_env=None, **kwargs):
        env = dict(extra_env or {})
        current_path = str(os.environ.get("PATH") or "")
        captured_path = str(env.get("PATH") or "")
        if current_path:
            env["PATH"] = current_path + (
                os.pathsep + captured_path
                if captured_path and captured_path != current_path
                else ""
            )
        return original(*args, extra_env=env, **kwargs)

    native_helpers.bootstrap_project_ready = bootstrap_project_ready
    native_helpers._project_ready_support_installed = True
