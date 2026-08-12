"""Granular deterministic L0 readiness probes.

Every result names one concrete component and its downstream consumer.  This
module does not decide scientific meaning and does not own the current-round
input contract.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import importlib.util
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from research_loop import deep_research
from research_loop.hypothesis_ledger import HypothesisLedger, LedgerError, binding_path

PREFLIGHT_RECEIPT_SCHEMA = "L0PreflightReceipt/v1"
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

    def to_dict(self) -> dict:
        return asdict(self)


def required_pubmed_tools() -> set[str]:
    return set(_PUBMED_REQUIRED_TOOLS)


def _pass(component: str, detail: str, consumer: str) -> ProbeResult:
    return ProbeResult(component, "PASS", "OK", detail, consumer)


def _fail(component: str, code: str, detail: str, consumer: str) -> ProbeResult:
    return ProbeResult(component, "FAIL", code, detail, consumer)


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


def _academic_research_probe(project_dir: Path) -> ProbeResult:
    try:
        spec, _version = deep_research.load_runtime_spec(project_dir)
        ready, reason = deep_research.runtime_ready(spec)
    except deep_research.DeepResearchError as exc:
        ready, reason = False, str(exc)
    if not ready:
        return _fail(
            "research.academic_research", "L0_RESEARCH_ARS_UNAVAILABLE", reason,
            "L1/L4/L8.5 research reasoning",
        )
    return _pass(
        "research.academic_research", "Academic Research runtime ready",
        "L1/L4/L8.5 research reasoning",
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
    consumer = "literature discovery/full-text retrieval"
    try:
        config = _pubmed_config(project_dir)
    except ValueError as exc:
        return _fail("research.pubmed_mcp", "L0_RESEARCH_PUBMED_MCP_START_FAILED",
                     str(exc), consumer)
    command = str(config.get("command") or "")
    if not command or shutil.which(command) is None:
        return _fail(
            "research.pubmed_mcp", "L0_RESEARCH_PUBMED_MCP_START_FAILED",
            f"stdio command not found on PATH: {command or '<empty>'}", consumer,
        )
    if importlib.util.find_spec("mcp") is None:
        return _fail(
            "research.pubmed_mcp", "L0_RESEARCH_PUBMED_MCP_START_FAILED",
            "official MCP Python SDK is not installed", consumer,
        )
    try:
        tools = asyncio.run(_list_pubmed_mcp_tools(config))
    except Exception as exc:  # transport/process/protocol failures share one owner
        return _fail(
            "research.pubmed_mcp", "L0_RESEARCH_PUBMED_MCP_START_FAILED",
            f"stdio MCP initialize/list_tools failed: {exc}", consumer,
        )
    missing = sorted(required_pubmed_tools() - tools)
    if missing:
        return _fail(
            "research.pubmed_mcp", "L0_RESEARCH_PUBMED_MCP_REQUIRED_TOOL_MISSING",
            f"missing required MCP tools: {', '.join(missing)}", consumer,
        )
    return _pass(
        "research.pubmed_mcp",
        "stdio MCP initialized; required search/metadata/full-text tools present",
        consumer,
    )


def _zotero_probe() -> ProbeResult:
    consumer = "selected literature/PDF management"
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
                consumer,
            )
        return _fail(
            "research.zotero", "L0_RESEARCH_ZOTERO_LIBRARY_UNREADABLE",
            f"Zotero Local API HTTP {exc.code}", consumer,
        )
    except (OSError, urllib.error.URLError) as exc:
        return _fail(
            "research.zotero", "L0_RESEARCH_ZOTERO_UNREACHABLE",
            f"Zotero Local API unavailable at 127.0.0.1:23119: {exc}", consumer,
        )
    if str(api_version) != "3":
        return _fail(
            "research.zotero", "L0_RESEARCH_ZOTERO_LIBRARY_UNREADABLE",
            f"unexpected Zotero API version: {api_version!r}", consumer,
        )
    detail = "local API v3 readable"
    if server_id:
        detail += f"; server_id={server_id}"
    return _pass("research.zotero", detail, consumer)


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
    consumer = "end-of-round human-readable projection"
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


def run_preflight_probes(project_dir) -> list[ProbeResult]:
    project = Path(project_dir)
    return [
        _python_packages_probe(),
        _filesystem_probe(project),
        _academic_research_probe(project),
        _pubmed_mcp_probe(project),
        _zotero_probe(),
        _hypothesis_ledger_probe(project),
        _evidence_store_probe(project),
        _obsidian_probe(),
    ]


def write_preflight_receipt(project_dir, results: list[ProbeResult]) -> Path:
    project = Path(project_dir)
    path = project / "00_Preflight" / "preflight_receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": PREFLIGHT_RECEIPT_SCHEMA,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "overall_status": "PASS" if all(r.status == "PASS" for r in results) else "FAIL",
        "results": [r.to_dict() for r in results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path
