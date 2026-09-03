"""Fail-closed runtime gate for formal L4A/SPECTER2 execution.

The ordinary L0 probes intentionally stay lightweight because they also run in
contract-only CI jobs.  This module is the heavier, explicit gate for a
formal L4A run: it proves the interpreter owner, imports the complete local
stack, and performs one real two-paper SPECTER2 adapter forward.  It never
installs packages, selects another interpreter, or falls back to another
environment.
"""
from __future__ import annotations

import importlib
import importlib.metadata as metadata
import json
import os
import site
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


RUNTIME_PREFLIGHT_SCHEMA = "RLRRuntimePreflight/v1"
FORMAL_ENVIRONMENT = "rlr"
REQUIRED_PYTHON = (3, 13)

# These are the versions that make the verified Python 3.13 composition
# reproducible.  Core RLR packages remain owned by requirements.txt and
# conda-forge; this gate reports their installed versions without inventing a
# second dependency owner.
PINNED_DISTRIBUTIONS = {
    "torch": "2.13.0",
    "transformers": "4.35.2",
    "adapters": "0.1.0",
    "tokenizers": "0.15.2",
    "huggingface-hub": "0.20.3",
    "fhaviary": "0.36.0",
    "fhlmi": "0.45.0",
    "litellm": "1.81.10",
    "paper-qa": "2026.8.12",
}
REQUIRED_DISTRIBUTIONS = tuple({
    *PINNED_DISTRIBUTIONS,
    "psutil",
    "jsonschema",
})
REQUIRED_IMPORTS = (
    "research_loop",
    "run_loop",
    "paperqa",
    "research_loop.l05_curie.paperqa2_runtime",
    "research_loop.l4a_specter2",
)


class RuntimePreflightError(RuntimeError):
    """Raised when the formal L4A runtime gate cannot be satisfied."""


@dataclass(frozen=True)
class RuntimeCheck:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _check(name: str, fn) -> RuntimeCheck:
    try:
        detail = str(fn())
    except Exception as exc:  # the gate must report and fail closed
        return RuntimeCheck(name, "FAIL", f"{type(exc).__name__}: {exc}")
    return RuntimeCheck(name, "PASS", detail)


def _resolved(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _interpreter_detail() -> str:
    executable = _resolved(sys.executable)
    prefix = _resolved(sys.prefix)
    reasons: list[str] = []

    if prefix.name.casefold() != FORMAL_ENVIRONMENT:
        reasons.append(f"sys.prefix is not the {FORMAL_ENVIRONMENT!r} environment: {prefix}")
    if executable.parent != prefix:
        reasons.append(f"sys.executable is outside sys.prefix: {executable}")

    conda_prefix = str(os.environ.get("CONDA_PREFIX") or "").strip()
    if not conda_prefix or _resolved(conda_prefix) != prefix:
        reasons.append(
            "CONDA_PREFIX does not identify sys.prefix as the formal environment"
        )
    if str(os.environ.get("CONDA_DEFAULT_ENV") or "").strip().casefold() != FORMAL_ENVIRONMENT:
        reasons.append("CONDA_DEFAULT_ENV is not 'rlr'")

    if sys.version_info[:2] != REQUIRED_PYTHON:
        reasons.append(
            f"Python {sys.version_info.major}.{sys.version_info.minor} is not "
            f"the required {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}"
        )
    if os.environ.get("PYTHONNOUSERSITE") != "1" or site.ENABLE_USER_SITE:
        reasons.append("user site-packages are not disabled")

    if reasons:
        raise RuntimePreflightError("; ".join(reasons))
    return (
        f"environment={FORMAL_ENVIRONMENT}; prefix={prefix}; executable={executable}; "
        f"python={sys.version.split()[0]}; user_site=disabled"
    )


def _distribution_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution in REQUIRED_DISTRIBUTIONS:
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError as exc:
            raise RuntimePreflightError(
                f"required distribution is missing: {distribution}"
            ) from exc
    return versions


def _packages_detail() -> str:
    versions = _distribution_versions()
    mismatches = [
        f"{name}=={versions[name]} (expected {expected})"
        for name, expected in PINNED_DISTRIBUTIONS.items()
        if versions.get(name) != expected
    ]
    if mismatches:
        raise RuntimePreflightError("pinned distribution mismatch: " + "; ".join(mismatches))
    return ", ".join(f"{name}=={versions[name]}" for name in sorted(versions))


def _imports_detail() -> str:
    imported = [importlib.import_module(name).__name__ for name in REQUIRED_IMPORTS]
    return "imported: " + ", ".join(imported)


def _paperqa_api_detail() -> str:
    from paperqa import Docs, Settings

    if not callable(Docs) or not callable(Settings):
        raise RuntimePreflightError("paperqa Docs/Settings are not callable")
    return "paperqa Docs and Settings are importable and callable"


def _specter2_import_detail() -> str:
    from research_loop.l4a_specter2 import Specter2Ranker

    if not callable(Specter2Ranker.from_pretrained):
        raise RuntimePreflightError("Specter2Ranker.from_pretrained is not callable")
    return "production Specter2Ranker importable"


def _minimal_adapter_forward_detail() -> str:
    from research_loop import l4a_specter2

    ranker = l4a_specter2.Specter2Ranker.from_pretrained(
        device="cpu", batch_size=2
    )
    model = getattr(ranker, "model", None)
    setter = getattr(model, "set_active_adapters", None)
    if not callable(setter):
        raise RuntimePreflightError("production model has no set_active_adapters")

    calls: list[str] = []

    def traced_set_active_adapters(adapter_name: Any, *args, **kwargs):
        calls.append(str(adapter_name))
        return setter(adapter_name, *args, **kwargs)

    setattr(model, "set_active_adapters", traced_set_active_adapters)
    try:
        results = l4a_specter2.rank_method_papers(
            "adapter-based scientific document representation",
            [
                {
                    "paper_id": "RUNTIME_PREFLIGHT_P1",
                    "title": "Adapter-based scientific document representation",
                    "metadata": {
                        "abstract": "A paper representation method for scientific retrieval."
                    },
                },
                {
                    "paper_id": "RUNTIME_PREFLIGHT_P2",
                    "title": "A control study of scientific document retrieval",
                    "metadata": {
                        "abstract": "A control comparison for document ranking."
                    },
                },
            ],
            ranker=ranker,
        )
    finally:
        setattr(model, "set_active_adapters", setter)

    if calls != ["proximity", "adhoc_query"]:
        raise RuntimePreflightError(
            f"unexpected adapter activation sequence: {calls!r}"
        )
    if len(results) != 2:
        raise RuntimePreflightError(f"expected two scores, received {len(results)}")
    for result in results:
        score = result.get("semantic_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise RuntimePreflightError(f"non-numeric score: {result!r}")
        if not -1.0 <= float(score) <= 1.0:
            raise RuntimePreflightError(f"score outside [-1, 1]: {result!r}")
    receipt = ranker.receipt()
    return (
        f"forward=PASS; adapters={calls!r}; scores="
        f"{[round(float(item['semantic_score']), 8) for item in results]!r}; "
        f"base_revision={receipt['base_revision']}"
    )


def build_report() -> dict[str, Any]:
    """Run every formal runtime check and return a JSON-serializable report."""

    versions: dict[str, str] = {}
    try:
        versions = _distribution_versions()
        package_check = RuntimeCheck(
            "versions", "PASS", _packages_detail()
        )
    except Exception as exc:
        package_check = RuntimeCheck(
            "versions", "FAIL", f"{type(exc).__name__}: {exc}"
        )

    checks = [
        _check("interpreter", _interpreter_detail),
        package_check,
        _check("rlr_and_runner_imports", _imports_detail),
        _check("paperqa_api", _paperqa_api_detail),
        _check("specter2_import", _specter2_import_detail),
        _check("specter2_minimal_adapter_forward", _minimal_adapter_forward_detail),
    ]
    status = "PASS" if all(item.status == "PASS" for item in checks) else "FAIL"
    return {
        "schema_version": RUNTIME_PREFLIGHT_SCHEMA,
        "status": status,
        "environment": FORMAL_ENVIRONMENT,
        "sys_executable": str(_resolved(sys.executable)),
        "sys_prefix": str(_resolved(sys.prefix)),
        "python_version": sys.version,
        "versions": versions,
        "checks": [item.to_dict() for item in checks],
        "no_install_or_fallback": True,
    }


def require_ready() -> dict[str, Any]:
    """Return a passing report or raise before any formal research starts."""

    report = build_report()
    if report["status"] != "PASS":
        failures = [
            f"{item['name']}: {item['detail']}"
            for item in report["checks"]
            if item["status"] != "PASS"
        ]
        raise RuntimePreflightError(
            "formal L4A runtime preflight failed closed: " + " | ".join(failures)
        )
    return report


def main() -> int:
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":  # pragma: no cover - exercised by the runtime command
    raise SystemExit(main())
