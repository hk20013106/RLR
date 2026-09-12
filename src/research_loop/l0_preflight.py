"""Granular deterministic L0 readiness probes.

Every result names one concrete component and its downstream consumer. This
module does not decide scientific meaning and does not own the current-round
input contract.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import importlib.util
import hashlib
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
    try:
        spec, _version = deep_research.load_runtime_spec(project_dir)
        ready, reason = structured_execution.runtime_ready(spec)
    except deep_research.DeepResearchError as exc:
        ready, reason = False, str(exc)
    if not ready:
        return _fail(
            "research.structured_execution", "L0_RESEARCH_STRUCTURED_EXECUTION_UNAVAILABLE", reason,
            "native structured model execution",
        )
    return _pass(
        "research.structured_execution", "generic structured provider runtime ready",
        "native structured model execution",
    )


def _academic_research_probe(project_dir: Path) -> ProbeResult:
    """Compatibility shim; native readiness has no ARS skill dependency."""
    return _structured_execution_probe(project_dir)


def _runtime_binding_report(project_dir: Path, backend: str | None) -> dict:
    """Bind the declared provider to the immutable runtime config bytes."""
    project = Path(project_dir)
    path = deep_research.runtime_config_path(project)
    checks = []
    report = {
        "status": "FAIL", "backend": backend or "",
        "runtime_config": {
            "absolute_path": str(path.resolve()),
            "relative_path": "00_Preflight/deep_research_runtime.json",
            "sha256": "", "bytes": 0,
        },
        "checks": checks,
    }
    if not backend:
        checks.append({"name": "backend_declaration", "status": "FAIL", "detail": "preflight requires --backend"})
        return report
    if not path.is_file():
        checks.append({"name": "runtime_config", "status": "FAIL", "detail": f"runtime config missing: {path}"})
        return report
    try:
        raw = path.read_bytes()
        report["runtime_config"].update({"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        spec, _version = deep_research.load_runtime_spec(project)
    except (OSError, deep_research.DeepResearchError) as exc:
        checks.append({"name": "runtime_config", "status": "FAIL", "detail": str(exc)})
        return report
    checks.append({
        "name": "backend_binding", "status": "PASS" if spec.backend == backend else "FAIL",
        "detail": f"runtime backend is {spec.backend!r}" if spec.backend == backend else f"requested backend {backend!r} does not match runtime backend {spec.backend!r}",
    })
    consistent, reason = deep_research.validate_spec_consistency(spec)
    checks.append({"name": "runtime_spec_consistency", "status": "PASS" if consistent else "FAIL", "detail": reason or "runtime spec is internally consistent"})
    try:
        same_host, reason = deep_research.host_matches(spec, explicit=True)
    except deep_research.DeepResearchError as exc:
        same_host, reason = False, str(exc)
    checks.append({"name": "host_backend_authorization", "status": "PASS" if same_host else "FAIL", "detail": reason or "host is authorized for the declared backend"})
    report["status"] = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    return report


def _runtime_binding_probe(project_dir: Path, backend: str) -> ProbeResult:
    report = _runtime_binding_report(project_dir, backend)
    if report["status"] != "PASS":
        failed = next(item for item in report["checks"] if item["status"] != "PASS")
        return _fail("runtime.binding", "L0_RUNTIME_BINDING_INVALID", failed["detail"], "PROJECT_READY runtime/backend authority")
    return _pass("runtime.binding", "explicit backend/runtime binding authorized", "PROJECT_READY runtime/backend authority")


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


def write_preflight_receipt(project_dir, results: list[ProbeResult], *, metadata: dict | None = None) -> Path:
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
        if payload.get("readiness", {}).get("status") != "PASS":
            payload["overall_status"] = "FAIL"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def _load_project_binding(project: Path) -> tuple[dict, str]:
    target = binding_path(project)
    if not target.is_file():
        raise LedgerError(f"hypothesis ledger binding missing: {target}")
    try:
        binding = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"invalid hypothesis ledger binding: {target}") from exc
    store_raw = str(os.environ.get("RLR_HYPOTHESIS_STORE") or "").strip()
    if not store_raw:
        raise LedgerError("RLR_HYPOTHESIS_STORE is not configured")
    store_path = str(Path(store_raw).expanduser().resolve())
    verified = HypothesisLedger.open_readonly(store_path).require_activated_project(project)
    return verified, store_path


def build_project_ready_metadata(project_dir, results: list[ProbeResult], *, backend: str, declaration_source: str, hard_stop_passed: bool, hard_stop_blocking: list[dict], additional_blocking: list[dict] | None = None) -> dict:
    """Build one receipt payload after all blocking checks have been evaluated."""
    project = Path(project_dir)
    runtime_report = _runtime_binding_report(project, backend)
    blocking = [item.to_dict() for item in results if item.enforcement == ENFORCEMENT_BLOCKING]
    blocking.extend(additional_blocking or [])
    failed = [item for item in blocking if item.get("status") != "PASS"]
    try:
        binding, store_path = _load_project_binding(project)
        profile = get_profile(str(binding.get("profile_id") or ""))
        project_identity = {"project_id": str(binding["project_id"]), "project_path": str(project.resolve())}
        store_identity = {"store_id": str(binding["store_id"]), "store_path": store_path}
        profile_identity = {"profile_id": profile.profile_id, "delta_schema_version": profile.delta_schema_version, "topology_version": profile.topology_version}
    except (LedgerError, KeyError, ValueError) as exc:
        project_identity = {"project_path": str(project.resolve())}
        store_identity = {"store_path": ""}
        profile_identity = {"profile_id": "", "error": str(exc)}
    runtime_probe = next((item for item in results if item.component == "research.structured_execution"), None)
    formal_status = "PASS" if runtime_report["status"] == "PASS" and runtime_probe and runtime_probe.status == "PASS" else "FAIL"
    ready = not failed and hard_stop_passed and formal_status == "PASS" and bool(project_identity.get("project_id")) and bool(store_identity.get("store_id")) and bool(profile_identity.get("profile_id"))
    return {
        "backend": {"name": backend, "declaration_source": declaration_source},
        "project_identity": project_identity,
        "hypothesis_store_identity": store_identity,
        "profile_identity": profile_identity,
        "runtime_config": runtime_report["runtime_config"],
        "formal_runtime_preflight": {"status": formal_status, "checks": runtime_report["checks"]},
        "blocking_dependencies": blocking,
        "hard_stop": {"status": "PASS" if hard_stop_passed else "FAIL", "blocking": list(hard_stop_blocking or [])},
        "readiness": {"status": "PASS" if ready else "FAIL", "code": "PROJECT_READY" if ready else "PROJECT_NOT_READY", "reason": "" if ready else "blocking dependency, runtime binding, hard-stop gate, or project identity failed"},
    }


def validate_project_ready(project_dir, *, candidate_path: str | Path | None = None, expected_backend: str | None = None) -> dict:
    """Validate receipt/runtime bytes without repairing or regenerating either."""
    project = Path(project_dir)
    # Historical fixture/projects are readable compatibility scope. New native
    # projects always have a ledger binding and therefore must satisfy v2.
    if not binding_path(project).is_file():
        return {"status": "PASS", "code": "LEGACY_UNBOUND_PROJECT", "legacy": True}
    receipt_path = project / "00_Preflight" / "preflight_receipt.json"
    if not receipt_path.is_file():
        return {"status": "FAIL", "code": "PROJECT_NOT_READY", "reason": "preflight receipt missing"}
    try:
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"status": "FAIL", "code": "PROJECT_NOT_READY", "reason": f"preflight receipt invalid: {exc}"}
    if receipt.get("schema_version") != PREFLIGHT_RECEIPT_SCHEMA or receipt.get("readiness", {}).get("code") != "PROJECT_READY" or receipt["readiness"].get("status") != "PASS":
        return {"status": "FAIL", "code": "PROJECT_NOT_READY", "reason": "receipt is not a PROJECT_READY v2 authority"}
    try:
        binding, store_path = _load_project_binding(project)
    except (LedgerError, KeyError, ValueError) as exc:
        return {"status": "FAIL", "code": "PROJECT_READY_BINDING_MISMATCH", "reason": str(exc)}
    if receipt.get("project_identity", {}).get("project_id") != binding.get("project_id") or receipt.get("hypothesis_store_identity", {}).get("store_id") != binding.get("store_id") or receipt.get("profile_identity", {}).get("profile_id") != binding.get("profile_id"):
        return {"status": "FAIL", "code": "PROJECT_READY_BINDING_MISMATCH", "reason": "project, store, or profile identity differs from receipt"}
    backend = str(receipt.get("backend", {}).get("name") or "")
    if expected_backend and backend != expected_backend:
        return {"status": "FAIL", "code": "PROJECT_READY_BACKEND_MISMATCH", "reason": f"bound backend is {backend!r}"}
    runtime = deep_research.runtime_config_path(project)
    if not runtime.is_file() or hashlib.sha256(runtime.read_bytes()).hexdigest() != receipt.get("runtime_config", {}).get("sha256"):
        return {"status": "FAIL", "code": "PROJECT_READY_RUNTIME_TAMPERED", "reason": "runtime config bytes differ from receipt"}
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    if candidate_path is not None:
        from research_loop.yamlio import _load_yaml_front
        fm = _load_yaml_front(Path(candidate_path))
        if fm.get("project_ready_receipt_path") != "00_Preflight/preflight_receipt.json" or fm.get("project_ready_receipt_sha256") != receipt_sha:
            return {"status": "FAIL", "code": "PROJECT_READY_CANDIDATE_BINDING_MISMATCH", "reason": "candidate does not pin receipt bytes"}
    return {"status": "PASS", "code": "PROJECT_READY", "receipt_relative_path": "00_Preflight/preflight_receipt.json", "receipt_sha256": receipt_sha, "backend": backend, "store_path": store_path, "project_id": binding["project_id"], "profile_id": binding.get("profile_id")}
