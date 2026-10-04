"""Pinned native proof and one-step live acceptance through RLR's public host protocol."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import uuid


_HOST_CHILD_ENV_ALLOWLIST = (
    "APPDATA",
    "COMSPEC",
    "CONDA_DEFAULT_ENV",
    "CONDA_PREFIX",
    "DEEPSEEK_API_KEY",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "OBSIDIAN_VAULT",
    "PATH",
    "PATHEXT",
    "PROGRAMDATA",
    "PYTHONNOUSERSITE",
    "PYTHONPATH",
    "PYTHONUTF8",
    "RLR_HOST_BACKEND",
    "RLR_HYPOTHESIS_STORE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
    "HF_HUB_DISABLE_TELEMETRY",
    "HF_HUB_OFFLINE",
    "LITELLM_LOCAL_MODEL_COST_MAP",
    "TRANSFORMERS_OFFLINE",
)


def _last_json_object(raw: bytes) -> dict:
    for line in reversed(raw.decode("utf-8", errors="replace").splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("status"), str):
            return value
    raise ValueError("host-next did not return a JSON action")


def _safe_error_bytes(raw: bytes, credential: str | None = None) -> bytes:
    credential = credential or os.environ.get("DEEPSEEK_API_KEY")
    if credential:
        raw = raw.replace(credential.encode("utf-8"), b"[REDACTED]")
    return raw


def _read_deepseek_credential(credential_file: str | Path) -> str:
    """Read only the authorized DEEPSEEK_API_KEY entry from a dotenv file."""
    path = Path(credential_file).resolve(strict=True)
    with path.open("rb") as stream:
        for raw_line in stream:
            line = raw_line.lstrip()
            if line.startswith(b"\xef\xbb\xbf"):
                line = line[3:]
            if not line.startswith(b"DEEPSEEK_API_KEY"):
                continue
            assignment = line[len(b"DEEPSEEK_API_KEY"):].lstrip(b" \t")
            if not assignment.startswith(b"="):
                continue
            credential = assignment[1:].strip()
            if len(credential) >= 2 and credential[0] == credential[-1] and credential[0] in b"\"'":
                credential = credential[1:-1]
            if not credential or b"\n" in credential or b"\r" in credential:
                raise ValueError("authorized DEEPSEEK_API_KEY entry is empty or invalid")
            return credential.decode("utf-8", errors="strict")
    raise ValueError("authorized DEEPSEEK_API_KEY entry is missing")


def _host_child_environment(credential: str) -> dict[str, str]:
    """Build the allowlisted host/worker environment and force offline model loading."""
    if not isinstance(credential, str) or not credential.strip():
        raise ValueError("live host process requires the authorized credential file")
    environment = {
        name: value
        for name in _HOST_CHILD_ENV_ALLOWLIST
        if name != "DEEPSEEK_API_KEY"
        if (value := os.environ.get(name)) is not None
    }
    environment["DEEPSEEK_API_KEY"] = credential
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    return environment


def run_credential_probe(binding_file: str | Path, credential_file: str | Path) -> str:
    """Probe credential visibility in the project's bound PaperQA2 interpreter."""
    from research_loop.l05_curie.paperqa2_runtime import validate_corpus_worker_config

    binding = json.loads(Path(binding_file).read_text(encoding="utf-8"))
    config = binding["paperqa2"]
    validate_corpus_worker_config(config)
    credential = _read_deepseek_credential(credential_file)
    probe = (
        "import os, sys; "
        "available = bool(os.environ.get('DEEPSEEK_API_KEY')); "
        "offline = (os.environ.get('HF_HUB_OFFLINE') == '1' and "
        "os.environ.get('TRANSFORMERS_OFFLINE') == '1'); "
        "print('PAPERQA2_DEEPSEEK_CREDENTIAL=' + ('AVAILABLE' if available else 'MISSING')); "
        "sys.exit(0 if offline else 23)"
    )
    process = subprocess.run(
        [config["python_executable"], "-c", probe],
        cwd=config["paperqa_repo"],
        env=_host_child_environment(credential),
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise ValueError("PaperQA2 credential probe did not receive required offline flags")
    output = process.stdout.decode("utf-8", errors="strict").strip()
    if output not in {
        "PAPERQA2_DEEPSEEK_CREDENTIAL=AVAILABLE",
        "PAPERQA2_DEEPSEEK_CREDENTIAL=MISSING",
    }:
        raise ValueError("PaperQA2 credential probe returned an unexpected status")
    return output


def _format_error_streams(stdout: bytes, stderr: bytes) -> bytes:
    return b"=== stdout ===\n" + (stdout or b"") + b"\n=== stderr ===\n" + (stderr or b"")


def _acceptance_blocker(project: Path, candidate_id: str, raw_error: bytes,
                        credential: str | None = None,
                        command_name: str = "host-next") -> dict:
    root = project / "08_Audit" / "l05_acquisition" / candidate_id / "task11_driver"
    root.mkdir(parents=True, exist_ok=True)
    safe_error = _safe_error_bytes(raw_error, credential)
    error_path = root / f"{command_name}-{uuid.uuid4().hex}.stderr.log"
    error_path.write_bytes(safe_error)
    return {
        "status": "BLOCKED",
        "real_e2e": "BLOCKED",
        "worker": {"status": "BLOCKED", "raw_error_path": str(error_path)},
        "coverage": {"status": "NOT ATTEMPTED"},
        "l1": {"status": "NOT ATTEMPTED"},
        "raw_error_path": str(error_path),
        "raw_error_sha256": hashlib.sha256(safe_error).hexdigest(),
        "host_provider_calls": 0,
    }


def _project_root_from_binding(binding_file: str | Path) -> Path:
    path = Path(binding_file).resolve(strict=True)
    project = path.parent.parent.resolve(strict=True)
    if path.name != "deep_research_runtime.json" or path.parent.name != "00_Preflight":
        raise ValueError("live-corpus requires the project's 00_Preflight runtime binding")
    if not (project / "01_Candidates").is_dir():
        raise ValueError("runtime binding does not resolve to an RLR project")
    return project


def _candidate_id_from_project(project: Path) -> str:
    inputs = sorted((project / "01_Candidates").glob("*.l0_input.yaml"))
    if len(inputs) != 1:
        raise ValueError("live-corpus binding must resolve to exactly one existing candidate input")
    candidate_id = inputs[0].name.removesuffix(".l0_input.yaml")
    if not (inputs[0].parent / f"{candidate_id}.md").is_file():
        raise ValueError("candidate input has no matching current RLR candidate")
    return candidate_id


def run_live_step(binding_file: str | Path, candidate_id: str,
                  credential_file: str | Path | None = None) -> dict:
    """Ask the existing host-next owner for one step; never invoke host cognition."""
    from research_loop.l05_curie.paperqa2_runtime import validate_corpus_worker_config

    project = _project_root_from_binding(binding_file)
    candidate_input = project / "01_Candidates" / f"{candidate_id}.l0_input.yaml"
    candidate_record = project / "01_Candidates" / f"{candidate_id}.md"
    if not candidate_input.is_file() or not candidate_record.is_file():
        raise ValueError("live-corpus candidate is not bound to an existing project input")
    if credential_file is None:
        raise ValueError("live-corpus requires the authorized credential file")
    binding = json.loads(Path(binding_file).read_text(encoding="utf-8"))
    validate_corpus_worker_config(binding["paperqa2"])
    credential = _read_deepseek_credential(credential_file)

    repo_root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        str(repo_root / "src" / "run_loop.py"),
        "host-next",
        str(project),
        candidate_id,
        "--resume",
    ]
    process = subprocess.run(
        command,
        cwd=repo_root,
        env=_host_child_environment(credential),
        capture_output=True,
        check=False,
    )
    try:
        action = _last_json_object(process.stdout)
    except ValueError:
        action = None
    if process.returncode != 0 or action is None or action.get("status") == "blocked":
        raw_error = _format_error_streams(process.stdout, process.stderr)
        return _acceptance_blocker(project, candidate_id, raw_error, credential)

    if action["status"] == "needs_host":
        return {
            "status": "NEEDS_HOST",
            "real_e2e": "PENDING",
            "action": action,
            "worker": {"status": "PENDING"},
            "coverage": {"status": "PENDING" if _is_coverage_request(action) else "NOT ATTEMPTED"},
            "l1": {"status": "NOT ATTEMPTED"},
            "host_provider_calls": 0,
        }
    if action["status"] in {"continued", "terminal"}:
        return {
            "status": action["status"].upper(),
            "real_e2e": "PENDING",
            "action": action,
            "worker": {"status": "PENDING"},
            "coverage": {"status": "PENDING" if _is_coverage_request(action) else "NOT ATTEMPTED"},
            "l1": {"status": "NOT ATTEMPTED"},
            "host_provider_calls": 0,
        }
    return _acceptance_blocker(
        project,
        candidate_id,
        _format_error_streams(process.stdout, process.stderr),
        credential,
    )


def run_live_submit(binding_file: str | Path, candidate_id: str, request_id: str,
                    response_file: str | Path, credential_file: str | Path) -> dict:
    """Submit only a current-host response through the public host-submit command."""
    from research_loop.l05_curie.paperqa2_runtime import validate_corpus_worker_config

    project = _project_root_from_binding(binding_file)
    candidate_input = project / "01_Candidates" / f"{candidate_id}.l0_input.yaml"
    candidate_record = project / "01_Candidates" / f"{candidate_id}.md"
    if not candidate_input.is_file() or not candidate_record.is_file():
        raise ValueError("host-submit candidate is not bound to an existing project input")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("host-submit request id must not be empty")
    response = Path(response_file).resolve(strict=True)
    binding = json.loads(Path(binding_file).read_text(encoding="utf-8"))
    validate_corpus_worker_config(binding["paperqa2"])
    credential = _read_deepseek_credential(credential_file)

    repo_root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        str(repo_root / "src" / "run_loop.py"),
        "host-submit",
        str(project),
        candidate_id,
        request_id,
        str(response),
        "--config",
        str(project / "rlr_runner.yaml"),
        "--resume",
    ]
    process = subprocess.run(
        command,
        cwd=repo_root,
        env=_host_child_environment(credential),
        capture_output=True,
        check=False,
    )
    try:
        submitted = _last_json_object(process.stdout)
    except ValueError:
        submitted = None
    continuation = (submitted or {}).get("continuation") or {}
    if (process.returncode != 0 or submitted is None
            or submitted.get("status") == "blocked"
            or continuation.get("status") == "blocked"):
        raw_error = _format_error_streams(process.stdout, process.stderr)
        return _acceptance_blocker(
            project, candidate_id, raw_error, credential, command_name="host-submit",
        )
    if continuation.get("status") == "needs_host":
        return {
            "status": "NEEDS_HOST",
            "real_e2e": "PENDING",
            "action": continuation,
            "worker": {"status": "PENDING"},
            "coverage": {"status": "PENDING" if _is_coverage_request(continuation) else "NOT ATTEMPTED"},
            "l1": {"status": "NOT ATTEMPTED"},
            "host_provider_calls": 0,
        }
    return {
        "status": "HOST_SUBMITTED",
        "real_e2e": "PENDING",
        "action": submitted,
        "worker": {"status": "PENDING"},
        "coverage": {"status": "PENDING" if _is_coverage_request(continuation) else "NOT ATTEMPTED"},
        "l1": {"status": "NOT ATTEMPTED"},
        "host_provider_calls": 0,
    }


def _is_coverage_request(action: dict) -> bool:
    request_path = action.get("request_path")
    if not request_path:
        return False
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    stage = (request.get("identity") or {}).get("stage")
    return isinstance(stage, str) and stage.startswith("coverage:")


def _live_candidate_id(binding_file: str | Path) -> str:
    return _candidate_id_from_project(_project_root_from_binding(binding_file))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=["native-identity", "native-diagnostics", "credential-probe", "live-corpus", "live-host-submit"], required=True)
    parser.add_argument("--binding-file", required=True)
    parser.add_argument("--credential-file")
    parser.add_argument("--request-id")
    parser.add_argument("--response-file")
    args = parser.parse_args(argv)
    if args.case == "credential-probe":
        try:
            result = run_credential_probe(args.binding_file, args.credential_file)
        except (OSError, ValueError, KeyError, TypeError):
            result = "PAPERQA2_DEEPSEEK_CREDENTIAL=MISSING"
        print(result)
        return 0 if result.endswith("=AVAILABLE") else 3
    if args.case == "live-corpus":
        try:
            if not args.credential_file:
                raise ValueError("live-corpus requires the authorized credential file")
            result = run_live_step(
                args.binding_file, _live_candidate_id(args.binding_file), args.credential_file,
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({
                "status": "BLOCKED",
                "real_e2e": "BLOCKED",
                "reason": str(exc),
                "worker": {"status": "BLOCKED"},
                "coverage": {"status": "NOT ATTEMPTED"},
                "l1": {"status": "NOT ATTEMPTED"},
                "host_provider_calls": 0,
            }, ensure_ascii=False, sort_keys=True))
            return 3
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 3 if result["status"] == "BLOCKED" else 0
    if args.case == "live-host-submit":
        try:
            if not args.credential_file or not args.request_id or not args.response_file:
                raise ValueError("live-host-submit requires credential file, request id, and response file")
            result = run_live_submit(
                args.binding_file,
                _live_candidate_id(args.binding_file),
                args.request_id,
                args.response_file,
                args.credential_file,
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({
                "status": "BLOCKED",
                "real_e2e": "BLOCKED",
                "reason": str(exc),
                "worker": {"status": "BLOCKED"},
                "coverage": {"status": "NOT ATTEMPTED"},
                "l1": {"status": "NOT ATTEMPTED"},
                "host_provider_calls": 0,
            }, ensure_ascii=False, sort_keys=True))
            return 3
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 3 if result["status"] == "BLOCKED" else 0
    binding = json.loads(Path(args.binding_file).read_text(encoding="utf-8"))["paperqa2"]
    if Path(binding["python_executable"]).resolve() != Path(sys.executable).resolve():
        raise ValueError("offline proof must run with the existing bound interpreter")
    bridge_path = Path(binding["bridge_script"])
    spec = importlib.util.spec_from_file_location("corpus_bridge_acceptance", bridge_path)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    import paperqa
    from paperqa import Docs, Settings
    from paperqa.types import Doc, Text
    from lmi import LLMResult
    from paperqa.core import LLMContextError
    assert paperqa.__version__ == "2026.8.12"
    repo = Path(binding["paperqa_repo"]).resolve()
    assert bridge._git(repo, "rev-parse", "HEAD") == "57e89f7223b0960d5ee5ea048c69e3c47e088572"
    assert bridge._git(repo, "describe", "--tags", "--exact-match", "HEAD") == "v2026.08.12"
    assert not bridge._git(repo, "status", "--porcelain")
    Path(paperqa.__file__).resolve().relative_to(repo)

    class Summary:
        """Only provider I/O is controlled; native summary parsing/retry stays real."""
        def __init__(self, outputs): self.outputs = iter(outputs); self.calls = 0
        async def call_single(self, **kwargs):
            self.calls += 1
            value = next(self.outputs)
            if isinstance(value, Exception): raise value
            return LLMResult(model="offline-controlled", text=value, date="2026-10-01")

    async def run_case(outputs):
        settings = Settings(embedding="sparse", summary_llm="offline-controlled",
                            answer={"evidence_k": 60, "evidence_skip_summary": False,
                                    "evidence_text_only_fallback": False},
                            parsing={"use_doc_details": False, "multimodal": False, "defer_embedding": True})
        docs = Docs()
        doc = Doc(dockey="CANONICAL_P1", docname="CANONICAL_P1", citation="Frozen citation")
        text = Text(doc=doc, name="unparseable arbitrary name", text="Entire original paragraph.",
                    source_locator="sec:1/p:1", section="Methods")
        assert len({text, text.model_copy(deep=True)}) == 1
        assert await docs.aadd_texts([text], doc, settings=settings)
        summary = Summary(outputs)
        diagnostics = bridge._CorpusDiagnostics(LLMContextError)
        logger = logging.getLogger("paperqa.core")
        logger.addHandler(diagnostics)
        try:
            session = await docs.aget_evidence("Complete frozen question", settings=settings,
                                              summary_llm_model=summary)
        finally:
            logger.removeHandler(diagnostics); diagnostics.close()
        assert not diagnostics.capture_failed
        return session, diagnostics.terminal_context_error_count, summary.calls

    if args.case == "native-identity":
        session, errors, calls = asyncio.run(run_case(['{"summary":"audit-only generated summary","relevance_score":5}']))
        assert errors == 0 and calls == 1 and len(session.contexts) == 1
        context = session.contexts[0]
        assert context.text.doc.dockey == context.text.doc.docname == "CANONICAL_P1"
        assert context.text.source_locator == "sec:1/p:1" and context.text.section == "Methods"
        assert context.text.text == "Entire original paragraph."
        assert context.context != context.text.text and len({context, context.model_copy(deep=True)}) == 1
        print(json.dumps({"case": args.case, "status": "PASS", "native_contexts": len(session.contexts),
                          "provider_calls": calls, "terminal_context_error_count": errors,
                          "version": paperqa.__version__}))
        return 0

    import litellm
    cases = {
        "score_zero": (["{\"summary\":\"irrelevant\",\"relevance_score\":0}"], (0, 0, 1)),
        "failed_twice": (["{invalid", "{invalid"], (0, 1, 2)),
        "recovered_retry": (["{invalid", '{"summary":"recovered","relevance_score":5}'], (1, 0, 2)),
        "non_retryable": ([litellm.Timeout(message="controlled offline timeout", model="offline-controlled", llm_provider="openai")], (0, 1, 1)),
    }
    facts = {}
    for name, (outputs, expected) in cases.items():
        session, errors, calls = asyncio.run(run_case(outputs))
        actual = (len(session.contexts), errors, calls)
        assert actual == expected, (name, actual, expected)
        facts[name] = {"contexts": actual[0], "terminal_context_error_count": errors, "provider_calls": calls}
    print(json.dumps({"case": args.case, "status": "PASS", "native_cases": facts,
                      "version": paperqa.__version__}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
