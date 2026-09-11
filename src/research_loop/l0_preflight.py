"""Granular deterministic L0 readiness probes.

Every result names one concrete component and its downstream consumer. This
module does not decide scientific meaning and does not own the current-round
input contract.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from research_loop import deep_research, structured_execution
from research_loop.compatibility import get_profile
from research_loop.hypothesis_ledger import HypothesisLedger, LedgerError, binding_path

PREFLIGHT_RECEIPT_SCHEMA = "L0PreflightReceipt/v2"
ENFORCEMENT_BLOCKING = "blocking"
ENFORCEMENT_READINESS_ONLY = "readiness_only"
_PUBMED_REQUIRED_TOOLS = {
    "pubmed_search_articles",
    "pubmed_fetch_articles",
    "pubmed_fetch_fulltext",
}


@dataclass(frozen=True)
class ProbeResult:
    component: str
    status: str
    code: str
    detail: str
    consumer: str
    enforcement: str = ENFORCEMENT_BLOCKING

    def __post_init__(self):
        if self.enforcement not in {ENFORCEMENT_BLOCKING, ENFORCEMENT_READINESS_ONLY}:
            raise ValueError(f"invalid probe enforcement: {self.enforcement!r}")

    def to_dict(self) -> dict:
        return asdict(self)


def required_pubmed_tools() -> set[str]:
    return set(_PUBMED_REQUIRED_TOOLS)


def _pass(component: str, detail: str, consumer: str, *,
          enforcement: str = ENFORCEMENT_BLOCKING) -> ProbeResult:
    return ProbeResult(component, "PASS", "OK", detail, consumer, enforcement)


def _fail(component: str, code: str, detail: str, consumer: str, *,
          enforcement: str = ENFORCEMENT_BLOCKING) -> ProbeResult:
    return ProbeResult(component, "FAIL", code, detail, consumer, enforcement)


def _write_read_delete_probe(directory: Path) -> tuple[bool, str]:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, prefix=".rlr_l0_",
            suffix=".probe", delete=False
        ) as handle:
            handle.write("rlr-l0-probe\n")
            path = Path(handle.name)
        if path.read_text(encoding="utf-8") != "rlr-l0-probe\n":
            return False, "probe readback mismatch"
        path.unlink()
        return True, "write/read/delete probe passed"
    except OSError as exc:
        return False, str(exc)


def _python_packages_probe() -> ProbeResult:
    required = ("yaml", "jsonschema", "psutil")
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        return _fail(
            "core.python_packages", "L0_CORE_PYTHON_PACKAGE_MISSING",
            f"missing Python packages: {', '.join(missing)}", "RLR runtime",
        )
    return _pass("core.python_packages", "required Python packages importable", "RLR runtime")


def _filesystem_probe(project_dir: Path) -> ProbeResult:
    ok, detail = _write_read_delete_probe(project_dir / "00_Preflight")
    if not ok:
        return _fail("core.filesystem", "L0_CORE_PROJECT_NOT_WRITABLE", detail,
                     "project artifacts and audit receipts")
    return _pass("core.filesystem", detail, "project artifacts and audit receipts")


def _structured_execution_probe(project_dir: Path) -> ProbeResult:
    """Check the generic model boundary used by native planner stages.

    Literature discovery and evidence verification are separate Curie-owned
    components. PROJECT_READY must not be coupled to an optional historical
    academic-research skill/plugin installation.
    """
    try:
        spec, _version = deep_research.load_runtime_spec(project_dir)
        ready, reason = structured_execution.runtime_ready(spec)
    except deep_research.DeepResearchError as exc:
        ready, reason = False, str(exc)
    if not ready:
        return _fail(
            "research.structured_execution",
            "L0_RESEARCH_STRUCTURED_EXECUTION_UNAVAILABLE",
            reason,
            "native L4 planning/adjudication and configured provider boundary",
        )
    return _pass(
        "research.structured_execution",
        "generic structured provider runtime ready",
        "native L4 planning/adjudication and configured provider boundary",
    )


def _academic_research_probe(project_dir: Path) -> ProbeResult:
    """Historical function name retained as a test/plugin compatibility shim."""
    return _structured_execution_probe(project_dir)


def _runtime_binding_report(project_dir: Path, backend: str | None) -> dict:
    """Validate the explicit bootstrap backend against the persisted RuntimeSpec.

    RuntimeSpec remains owned by ``deep_research``.  This function only
    assembles the one preflight report consumed by the receipt and validator;
    it never writes or repairs the runtime configuration.
    """
    project = Path(project_dir)
    checks = []
    path = deep_research.runtime_config_path(project)
    report = {
        "status": "FAIL",
        "backend": backend or "",
        "runtime_config": {
            "absolute_path": str(path.resolve()),
            "relative_path": "00_Preflight/deep_research_runtime.json",
            "sha256": "",
            "bytes": 0,
        },
        "checks": checks,
    }

    def add(name: str, status: str, detail: str):
        checks.append({"name": name, "status": status, "detail": detail})

    if not backend:
        add("backend_declaration", "FAIL", "preflight requires --backend")
        return report
    if not path.is_file():
        add("runtime_config", "FAIL", f"runtime config missing: {path}")
        return report
    try:
        raw = path.read_bytes()
        report["runtime_config"].update({
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        })
        spec, _version = deep_research.load_runtime_spec(project)
    except (OSError, deep_research.DeepResearchError) as exc:
        add("runtime_config", "FAIL", str(exc))
        return report

    if spec.backend != backend:
        add(
            "backend_binding", "FAIL",
            f"requested backend {backend!r} does not match runtime backend {spec.backend!r}",
        )
    else:
        add("backend_binding", "PASS", f"runtime backend is {spec.backend!r}")

    consistent, reason = deep_research.validate_spec_consistency(spec)
    add("runtime_spec_consistency", "PASS" if consistent else "FAIL",
        reason or "runtime spec is internally consistent")

    try:
        same_host, host_reason = deep_research.host_matches(
            spec, explicit=True
        )
    except deep_research.DeepResearchError as exc:
        same_host, host_reason = False, str(exc)
    add("host_backend_authorization", "PASS" if same_host else "FAIL",
        host_reason or "host is authorized for the declared backend")

    report["status"] = "PASS" if all(
        item["status"] == "PASS" for item in checks
    ) else "FAIL"
    return report


def _runtime_binding_probe(project_dir: Path, backend: str) -> ProbeResult:
    report = _runtime_binding_report(project_dir, backend)
    if report["status"] != "PASS":
        failed = next(item for item in report["checks"] if item["status"] != "PASS")
        return _fail(
            "runtime.binding", "L0_RUNTIME_BINDING_INVALID", failed["detail"],
            "PROJECT_READY runtime/backend authority",
        )
    return _pass(
        "runtime.binding", "explicit backend/runtime binding authorized",
        "PROJECT_READY runtime/backend authority",
    )


def _pubmed_config(project_dir: Path) -> dict:
    config_path = project_dir / "00_Preflight" / "pubmed_mcp.json"
    config = {
        "command": "npx",
        "args": ["-y", "@cyanheads/pubmed-mcp-server@latest"],
        "env": {"MCP_TRANSPORT_TYPE": "stdio", "MCP_LOG_LEVEL": "error"},
        "timeout": 90,
    }
    if config_path.is_file():
        try:
            override = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid PubMed MCP config {config_path}: {exc}") from exc
        if not isinstance(override, dict):
            raise ValueError(f"PubMed MCP config must be an object: {config_path}")
        for key in ("command", "args", "timeout"):
            if key in override:
                config[key] = override[key]
        if isinstance(override.get("env"), dict):
            config["env"].update({str(k): str(v) for k, v in override["env"].items()})
    return config


async def _list_pubmed_mcp_tools(config: dict) -> set[str]:
    # Official MCP SDK; deliberately lazy so an absent dependency is reported as
    # a probe failure rather than making the whole RLR package unimportable.
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env.update({str(k): str(v) for k, v in (config.get("env") or {}).items()})
    params = StdioServerParameters(
        command=str(config["command"]),
        args=[str(x) for x in config.get("args") or []],
        env=env,
    )

    async def _run() -> set[str]:
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.list_tools()
                return {tool.name for tool in response.tools}

    return await asyncio.wait_for(_run(), timeout=float(config.get("timeout") or 90))


def _pubmed_mcp_probe(project_dir: Path) -> ProbeResult:
    # Target architecture requires this transport, but its RLR literature
    # consumer is not wired in PR #15. Report readiness without pretending the
    # dependency→consumer closure already exists.
    consumer = "future canonical literature discovery/full-text transport"
    enforcement = ENFORCEMENT_READINESS_ONLY
    try:
        config = _pubmed_config(project_dir)
    except ValueError as exc:
        return _fail("research.pubmed_mcp", "L0_RESEARCH_PUBMED_MCP_START_FAILED",
                     str(exc), consumer, enforcement=enforcement)
    command = str(config.get("command") or "")
    if not command or shutil.which(command) is None:
        return _fail(
            "research.pubmed_mcp", "L0_RESEARCH_PUBMED_MCP_START_FAILED",
            f"stdio command not found on PATH: {command or '<empty>'}", consumer,
            enforcement=enforcement,
        )
    if importlib.util.find_spec("mcp") is None:
        return _fail(
            "research.pubmed_mcp", "L0_RESEARCH_PUBMED_MCP_START_FAILED",
            "official MCP Python SDK is not installed", consumer,
            enforcement=enforcement,
        )
    try:
        tools = asyncio.run(_list_pubmed_mcp_tools(config))
    except Exception as exc:  # transport/process/protocol failures share one owner
        return _fail(
            "research.pubmed_mcp", "L0_RESEARCH_PUBMED_MCP_START_FAILED",
            f"stdio MCP initialize/list_tools failed: {exc}", consumer,
            enforcement=enforcement,
        )
    missing = sorted(required_pubmed_tools() - tools)
    if missing:
        return _fail(
            "research.pubmed_mcp", "L0_RESEARCH_PUBMED_MCP_REQUIRED_TOOL_MISSING",
            f"missing required MCP tools: {', '.join(missing)}", consumer,
            enforcement=enforcement,
        )
    return _pass(
        "research.pubmed_mcp",
        "stdio MCP initialized; required search/metadata/full-text tools present",
        consumer,
        enforcement=enforcement,
    )


def _zotero_probe() -> ProbeResult:
    # Zotero is part of the target canonical workflow, but PR #15 does not add
    # the item/PDF consumer. Keep the probe visible without a false hard gate.
    consumer = "future selected-literature/PDF management"
    enforcement = ENFORCEMENT_READINESS_ONLY
    request = urllib.request.Request(
        "http://127.0.0.1:23119/api/", headers={"Zotero-API-Version": "3"}
    )
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            api_version = response.headers.get("Zotero-API-Version", "")
            server_id = response.headers.get("Zotero-Server-ID", "")
            response.read(64)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            return _fail(
                "research.zotero", "L0_RESEARCH_ZOTERO_LIBRARY_UNREADABLE",
                "Zotero Local API returned 403; local API access is disabled",
                consumer, enforcement=enforcement,
            )
        return _fail(
            "research.zotero", "L0_RESEARCH_ZOTERO_LIBRARY_UNREADABLE",
            f"Zotero Local API HTTP {exc.code}", consumer,
            enforcement=enforcement,
        )
    except (OSError, urllib.error.URLError) as exc:
        return _fail(
            "research.zotero", "L0_RESEARCH_ZOTERO_UNREACHABLE",
            f"Zotero Local API unavailable at 127.0.0.1:23119: {exc}", consumer,
            enforcement=enforcement,
        )
    if str(api_version) != "3":
        return _fail(
            "research.zotero", "L0_RESEARCH_ZOTERO_LIBRARY_UNREADABLE",
            f"unexpected Zotero API version: {api_version!r}", consumer,
            enforcement=enforcement,
        )
    detail = "local API v3 readable"
    if server_id:
        detail += f"; server_id={server_id}"
    return _pass("research.zotero", detail, consumer, enforcement=enforcement)


def _hypothesis_ledger_probe(project_dir: Path) -> ProbeResult:
    consumer = "cross-round hypothesis lineage/state"
    bind = binding_path(project_dir)
    if not bind.is_file():
        return _fail(
            "state.hypothesis_ledger", "L0_STATE_LEDGER_BINDING_INVALID",
            f"project binding missing: {bind}", consumer,
        )
    store = str(os.environ.get("RLR_HYPOTHESIS_STORE") or "").strip()
    if not store:
        return _fail(
            "state.hypothesis_ledger", "L0_STATE_LEDGER_BINDING_INVALID",
            "RLR_HYPOTHESIS_STORE is not configured", consumer,
        )
    path = Path(store).expanduser()
    if not path.is_file():
        return _fail(
            "state.hypothesis_ledger", "L0_STATE_LEDGER_BINDING_INVALID",
            f"configured ledger does not exist: {path}", consumer,
        )
    try:
        ledger = HypothesisLedger(path)
        ledger.require_activated_project(project_dir)
    except (LedgerError, OSError, ValueError) as exc:
        return _fail(
            "state.hypothesis_ledger", "L0_STATE_LEDGER_BINDING_INVALID",
            str(exc), consumer,
        )
    if not os.access(path, os.W_OK):
        return _fail(
            "state.hypothesis_ledger", "L0_STATE_LEDGER_NOT_WRITABLE",
            f"ledger is not writable: {path}", consumer,
        )
    return _pass("state.hypothesis_ledger", "binding valid; ledger readable/writable", consumer)


def _evidence_store_probe(project_dir: Path) -> ProbeResult:
    consumer = "source/intermediate/result/literature evidence persistence"
    checked = []
    for rel in ("08_Audit", "09_Literature_Database", "04_Analysis_Outputs"):
        directory = project_dir / rel
        ok, detail = _write_read_delete_probe(directory)
        if not ok:
            return _fail(
                "state.evidence_store", "L0_STATE_EVIDENCE_STORE_NOT_WRITABLE",
                f"{rel}: {detail}", consumer,
            )
        checked.append(rel)
    return _pass(
        "state.evidence_store",
        f"write/read/delete probes passed: {', '.join(checked)}", consumer,
    )


def _obsidian_probe() -> ProbeResult:
    consumer = "required L10c human-readable projection"
    raw = str(os.environ.get("OBSIDIAN_VAULT") or "").strip()
    if not raw:
        return _fail(
            "state.obsidian", "L0_STATE_OBSIDIAN_INVALID_VAULT",
            "OBSIDIAN_VAULT is not configured", consumer,
        )
    vault = Path(os.path.expandvars(raw)).expanduser()
    if not vault.is_dir() or not (vault / ".obsidian").is_dir():
        return _fail(
            "state.obsidian", "L0_STATE_OBSIDIAN_INVALID_VAULT",
            f"not an Obsidian vault (missing directory or .obsidian): {vault}",
            consumer,
        )
    ok, detail = _write_read_delete_probe(vault)
    if not ok:
        return _fail(
            "state.obsidian", "L0_STATE_OBSIDIAN_NOT_WRITABLE", detail, consumer,
        )
    return _pass("state.obsidian", detail, consumer)


def run_preflight_probes(project_dir, *, backend: str | None = None) -> list[ProbeResult]:
    project = Path(project_dir)
    results = [
        _python_packages_probe(),
        _filesystem_probe(project),
    ]
    if backend:
        results.append(_runtime_binding_probe(project, backend))
    results.extend([
        _academic_research_probe(project),
        _pubmed_mcp_probe(project),
        _zotero_probe(),
        _hypothesis_ledger_probe(project),
        _evidence_store_probe(project),
        _obsidian_probe(),
    ])
    return results


def preflight_overall_status(results: list[ProbeResult]) -> str:
    if any(r.status == "FAIL" and r.enforcement == ENFORCEMENT_BLOCKING for r in results):
        return "FAIL"
    if any(r.status == "FAIL" for r in results):
        return "PASS_WITH_WARNINGS"
    return "PASS"


def _load_project_binding(project: Path) -> tuple[dict, str]:
    target = binding_path(project)
    if not target.is_file():
        raise LedgerError(f"hypothesis ledger binding missing: {target}")
    try:
        raw = target.read_bytes()
        binding = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LedgerError(f"invalid hypothesis ledger binding: {target}") from exc
    if not isinstance(binding, dict):
        raise LedgerError(f"hypothesis ledger binding must be an object: {target}")
    store_raw = str(os.environ.get("RLR_HYPOTHESIS_STORE") or "").strip()
    if not store_raw:
        raise LedgerError("RLR_HYPOTHESIS_STORE is not configured")
    store_path = Path(store_raw).expanduser().resolve()
    ledger = HypothesisLedger.open_readonly(store_path)
    verified = ledger.require_activated_project(project)
    return verified, str(store_path)


def build_project_ready_metadata(
    project_dir,
    results: list[ProbeResult],
    *,
    backend: str,
    declaration_source: str,
    hard_stop_passed: bool,
    hard_stop_blocking: list[dict],
    additional_blocking: list[dict] | None = None,
) -> dict:
    """Build the complete final receipt payload before it is written."""
    project = Path(project_dir)
    runtime_path = deep_research.runtime_config_path(project)
    runtime_report = _runtime_binding_report(project, backend)
    runtime_bytes = b""
    if runtime_path.is_file():
        try:
            runtime_bytes = runtime_path.read_bytes()
        except OSError:
            runtime_bytes = b""
    runtime_sha = hashlib.sha256(runtime_bytes).hexdigest() if runtime_bytes else ""

    try:
        binding, store_path = _load_project_binding(project)
        profile = get_profile(str(binding.get("profile_id") or ""))
        project_identity = {
            "project_id": str(binding["project_id"]),
            "project_path": str(project.resolve()),
            "project_name": project.name,
        }
        store_identity = {
            "store_id": str(binding["store_id"]),
            "store_path": store_path,
        }
        profile_identity = {
            "profile_id": profile.profile_id,
            "delta_schema_version": profile.delta_schema_version,
            "topology_version": profile.topology_version,
        }
    except (LedgerError, KeyError, ValueError) as exc:
        project_identity = {"project_path": str(project.resolve())}
        store_identity = {"store_path": str(
            Path(os.environ.get("RLR_HYPOTHESIS_STORE", "")).expanduser().resolve()
        ) if os.environ.get("RLR_HYPOTHESIS_STORE") else ""}
        profile_identity = {"profile_id": "", "error": str(exc)}

    blocking = [item.to_dict() for item in results
                if item.enforcement == ENFORCEMENT_BLOCKING]
    blocking.extend(dict(item) for item in (additional_blocking or []))
    readiness_only = [item.to_dict() for item in results
                      if item.enforcement == ENFORCEMENT_READINESS_ONLY]
    blocking_failed = [item for item in blocking if item["status"] != "PASS"]
    formal_checks = list(runtime_report.get("checks") or [])
    runtime_probe = next(
        (
            item for item in results
            if item.component in {
                "research.structured_execution",
                "research.academic_research",
            }
        ),
        None,
    )
    formal_checks.append({
        "name": "structured_runtime_ready",
        "status": "PASS" if runtime_probe and runtime_probe.status == "PASS" else "FAIL",
        "detail": (
            runtime_probe.detail
            if runtime_probe
            else "structured execution runtime probe missing"
        ),
    })
    formal_status = "PASS" if all(
        item["status"] == "PASS" for item in formal_checks
    ) else "FAIL"
    ready = (
        not blocking_failed
        and hard_stop_passed
        and formal_status == "PASS"
        and bool(project_identity.get("project_id"))
        and bool(store_identity.get("store_id"))
        and bool(profile_identity.get("profile_id"))
    )
    reason = "" if ready else (
        "blocking preflight failure" if blocking_failed else
        "hard-stop pitfall applies" if not hard_stop_passed else
        "formal runtime preflight failed" if formal_status != "PASS" else
        "project/store/profile identity is incomplete"
    )
    return {
        "project_identity": project_identity,
        "hypothesis_store_identity": store_identity,
        "profile_identity": profile_identity,
        "backend": {
            "name": backend,
            "declaration_source": declaration_source,
        },
        "runtime_config": {
            **runtime_report["runtime_config"],
            "sha256": runtime_sha or runtime_report["runtime_config"].get("sha256", ""),
            "consistency": next(
                (item for item in formal_checks
                 if item["name"] == "runtime_spec_consistency"),
                {"status": "FAIL", "detail": "runtime consistency check missing"},
            ),
            "host_backend_authorization": next(
                (item for item in formal_checks
                 if item["name"] == "host_backend_authorization"),
                {"status": "FAIL", "detail": "host authorization check missing"},
            ),
        },
        "formal_runtime_preflight": {
            "status": formal_status,
            "checks": formal_checks,
        },
        "blocking_dependencies": blocking,
        "readiness_only": readiness_only,
        "hard_stop": {
            "status": "PASS" if hard_stop_passed else "FAIL",
            "blocking": list(hard_stop_blocking or []),
        },
        "readiness": {
            "status": "PASS" if ready else "FAIL",
            "code": "PROJECT_READY" if ready else "PROJECT_NOT_READY",
            "reason": reason,
        },
    }


def write_preflight_receipt(
    project_dir,
    results: list[ProbeResult],
    *,
    metadata: dict | None = None,
) -> Path:
    project = Path(project_dir)
    path = project / "00_Preflight" / "preflight_receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": PREFLIGHT_RECEIPT_SCHEMA,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "overall_status": preflight_overall_status(results),
        "results": [r.to_dict() for r in results],
    }
    if metadata:
        payload.update(metadata)
        if metadata.get("readiness", {}).get("status") != "PASS":
            payload["overall_status"] = "FAIL"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def _project_not_ready(code: str, reason: str) -> dict:
    return {"status": "FAIL", "code": code, "reason": reason}


def validate_project_ready(
    project_dir,
    *,
    candidate_path: str | Path | None = None,
    expected_backend: str | None = None,
) -> dict:
    """Validate the sole PROJECT_READY authority without repairing anything."""
    project = Path(project_dir)
    binding_file = binding_path(project)
    # Hand-built legacy fixtures without a native store binding remain outside
    # the v0.9.7 first-mile contract. New-project always creates this binding.
    if not binding_file.is_file():
        return {"status": "PASS", "code": "LEGACY_UNBOUND_PROJECT", "legacy": True}
    receipt_path = project / "00_Preflight" / "preflight_receipt.json"
    if not receipt_path.is_file():
        return _project_not_ready("PROJECT_NOT_READY", f"preflight receipt missing: {receipt_path}")
    try:
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _project_not_ready("PROJECT_NOT_READY", f"preflight receipt invalid: {exc}")
    if not isinstance(receipt, dict) or receipt.get("schema_version") != PREFLIGHT_RECEIPT_SCHEMA:
        return _project_not_ready(
            "PROJECT_NOT_READY",
            f"preflight receipt schema is not {PREFLIGHT_RECEIPT_SCHEMA}",
        )
    readiness = receipt.get("readiness")
    if not isinstance(readiness, dict) or readiness.get("status") != "PASS" \
            or readiness.get("code") != "PROJECT_READY":
        return _project_not_ready(
            "PROJECT_NOT_READY",
            str((readiness or {}).get("reason") or "preflight readiness is not PASS"),
        )

    try:
        binding, store_path = _load_project_binding(project)
        if receipt.get("project_identity", {}).get("project_id") != binding["project_id"]:
            return _project_not_ready("PROJECT_READY_BINDING_MISMATCH", "project identity differs from receipt")
        if receipt.get("hypothesis_store_identity", {}).get("store_id") != binding["store_id"]:
            return _project_not_ready("PROJECT_READY_BINDING_MISMATCH", "hypothesis store identity differs from receipt")
        if receipt.get("profile_identity", {}).get("profile_id") != binding.get("profile_id"):
            return _project_not_ready("PROJECT_READY_BINDING_MISMATCH", "profile identity differs from receipt")
    except (LedgerError, KeyError, ValueError) as exc:
        return _project_not_ready("PROJECT_READY_BINDING_MISMATCH", str(exc))

    backend_record = receipt.get("backend") or {}
    backend = str(backend_record.get("name") or "")
    if expected_backend and backend != expected_backend:
        return _project_not_ready(
            "PROJECT_READY_BACKEND_MISMATCH",
            f"project is bound to backend {backend!r}, not {expected_backend!r}",
        )
    runtime_record = receipt.get("runtime_config") or {}
    runtime_path = deep_research.runtime_config_path(project)
    expected_runtime_relative = runtime_record.get("relative_path")
    expected_receipt_relative = receipt_path.relative_to(project).as_posix()
    expected_absolute = runtime_record.get("absolute_path")
    if expected_runtime_relative != "00_Preflight/deep_research_runtime.json" \
            or (expected_absolute and Path(expected_absolute).resolve() != runtime_path.resolve()):
        return _project_not_ready("PROJECT_READY_BINDING_MISMATCH", "runtime config identity differs from receipt")
    if not runtime_path.is_file():
        return _project_not_ready("PROJECT_NOT_READY", f"runtime config missing: {runtime_path}")
    runtime_bytes = runtime_path.read_bytes()
    runtime_sha = hashlib.sha256(runtime_bytes).hexdigest()
    if runtime_sha != runtime_record.get("sha256"):
        return _project_not_ready(
            "PROJECT_READY_RUNTIME_TAMPERED",
            "runtime config bytes differ from the PROJECT_READY receipt",
        )
    try:
        spec, _version = deep_research.load_runtime_spec(project)
    except deep_research.DeepResearchError as exc:
        return _project_not_ready("PROJECT_READY_RUNTIME_INVALID", str(exc))
    if spec.backend != backend:
        return _project_not_ready("PROJECT_READY_BACKEND_MISMATCH", "runtime backend differs from receipt")
    consistent, reason = deep_research.validate_spec_consistency(spec)
    if not consistent:
        return _project_not_ready("PROJECT_READY_RUNTIME_INVALID", reason)
    same_host, host_reason = deep_research.host_matches(spec, explicit=True)
    if not same_host:
        return _project_not_ready("PROJECT_READY_HOST_MISMATCH", host_reason)

    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    if candidate_path is not None:
        try:
            from research_loop.yamlio import _load_yaml_front
            fm = _load_yaml_front(Path(candidate_path))
        except (OSError, ValueError) as exc:
            return _project_not_ready("PROJECT_READY_CANDIDATE_INVALID", str(exc))
        if fm.get("project_ready_receipt_path") != expected_receipt_relative \
                or fm.get("project_ready_receipt_sha256") != receipt_sha:
            return _project_not_ready(
                "PROJECT_READY_CANDIDATE_BINDING_MISMATCH",
                "candidate does not pin the current PROJECT_READY receipt bytes",
            )
    return {
        "status": "PASS",
        "code": "PROJECT_READY",
        "receipt_path": receipt_path,
        "receipt_relative_path": expected_receipt_relative,
        "receipt_sha256": receipt_sha,
        "receipt_bytes": receipt_bytes,
        "runtime_config_path": runtime_path,
        "runtime_config_sha256": runtime_sha,
        "backend": backend,
        "store_path": store_path,
        "project_id": binding["project_id"],
        "profile_id": binding.get("profile_id"),
    }
