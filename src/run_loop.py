#!/usr/bin/env python3
"""RLR loop runner — the canonical active runtime entry point.

`python run_loop.py run PROJECT CAND` is the one documented way to drive the
loop. It drives the engine (research_loop_v04.py) whose `assemble-context`
enforces the V0.7 Deep Research gate: L1/L4/L8.5 fail closed (rc=3) without a
successful ARS receipt and a valid evidence pack; `assemble_context()` here
re-raises that as a hard stop.

Drives research_loop_v04.py (the controller) around its DAG using a
provider-neutral orchestrator, and decides whether to open another round with a
hybrid StopPolicy (hard cap + L10b decision + optional Review gate + marginal
gain). It does NOT replace the controller and does NOT touch the core DAG/state
machine -- it only calls the controller's CLI and reads its outputs.

    python run_loop.py run PROJECT_DIR CAND_ID --config rlr_runner.yaml
    python run_loop.py run ../demos/other_examples/DemoProject_v03 C... --dry-run

Stop rule (the whole point — do not let the loop spin on "polish / new angle"):
the question is NOT "are there issues" but "would another round plausibly change
the conclusion". See StopPolicy.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

HERE = Path(__file__).resolve().parent
CONTROLLER = HERE / "research_loop_v04.py"
sys.path.insert(0, str(HERE))

import research_loop_v04 as rl       # noqa: E402
import orchestrator as orch          # noqa: E402
from research_loop.api import (  # noqa: E402
    EngineAPI,
    load_rendered_context_artifact,
)
from research_loop.context import DEFAULT_CONTEXT_TOKEN_BUDGET
from research_loop.compatibility import PROFILE_V20, PROFILE_V21_CATALOG_1, get_profile
from research_loop.code_state import capture_code_state
from research_loop.persona_catalog import (
    PersonaCatalogError,
    resolve_persona_template,
)
from research_loop import (
    deep_research, l0_preflight, runtime_preflight,
)
from research_loop.l05_curie import europepmc_runtime
from research_loop.loopx_policy import LoopXRetryPolicy
from research_loop.providers.base import (
    ProviderOutputContractError,
    provider_attempt_path,
)
from research_loop.deep_research import SUPPORTED_BACKENDS
from research_loop.delta import artifact_for_node
from research_loop.hypothesis_contracts import provider_schema_for_profile
from research_loop.l0_state import L0StateError, restore_previous_round
from research_loop import research_seed
from research_loop.l05_curie.europepmc_runtime import (
    CurieAcquisitionError, validate_europepmc_acquisition_result,
)
from research_loop.topology import topology_for_profile

ENGINE = EngineAPI()
ExecutionMode = Literal["headless", "agent_native"]


DEFAULT_CONFIG = """\
max_rounds: 3

provider:
  default:
    type: headless
    command: ""

deep_research:
  backend: ""
  executable: ""
  skill_path: ""
  plugin_dir: ""
  skill_version: unknown
  timeout: 900

review:
  enabled: true
  academy_research_skill: optional

stop_policy:
  keep_requires_review_accept: true
  marginal_gain_stop_threshold: 2
  max_l7_failures: 2
  max_node_failures: 2

# Configure provider.default.command or RLR_HEADLESS_CMD for automatic runs.
# Manual mode is debug-only and is never a silent fallback.
"""

REVIEW_SCHEMA = {
    "review_verdict": "accept | weak_accept | major_revision | reject",
    "evidence_score": int,
    "method_validity_score": int,
    "novelty_score": int,
    "falsification_risk_score": int,
    "marginal_gain_score": int,
    "required_revisions": list,
    "executable_next_actions": list,
    "reason": str,
}

_POLISH_KW = ("literature", "文献", "rephrase", "reword", "wording", "说法",
              "figure", "figures", "图", "plot", "polish", "格式", "format",
              "typo", "再查", "再画", "措辞")


def log(msg):
    print(f"[run_loop] {msg}")


def _formal_runtime_preflight():
    """Require the pinned production environment before a formal run starts."""
    try:
        report = runtime_preflight.require_ready()
    except runtime_preflight.RuntimePreflightError as exc:
        log(f"FORMAL RUNTIME PREFLIGHT FAILED -- {exc}")
        return False
    log(
        "FORMAL RUNTIME PREFLIGHT PASS -- "
        f"environment={report.get('environment')}; "
        f"executable={report.get('sys_executable')}"
    )
    return True


def _ctl(*args):
    return ENGINE.run_cli(*args)


def auto_pitfall(project, cand, node, category, symptom, provider="unknown",
                 evidence=""):
    try:
        r = _ctl("record-pitfall", project, cand, "--node", node,
                 "--category", category, "--symptom", symptom[:500],
                 "--severity", "warn", "--status", "draft",
                 "--provider", provider or "unknown",
                 *(["--evidence", evidence] if evidence else []))
        if r.returncode == 0:
            log(f"auto-recorded draft pitfall ({category} @ {node})")
        else:
            log(f"auto-pitfall failed (non-fatal): {r.stderr.strip()}")
    except Exception as e:
        log(f"auto-pitfall error (non-fatal): {e}")


def record_loopx_failure(failure_state, node, failure_class, failure_code, *, run_dir=None):
    """Record a classified failure and persist the Loop X retry decision."""
    policy = failure_state.setdefault("loopx_policy", LoopXRetryPolicy())
    event = policy.record(node, failure_class, failure_code)
    failure_state["last_loopx_failure"] = event
    if run_dir:
        path = Path(run_dir) / "loopx_failures.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def _record_runtime_failure(failure_state, node, failure_class, failure_code, run_dir):
    if failure_state is not None:
        return record_loopx_failure(
            failure_state, node, failure_class, failure_code, run_dir=run_dir
        )
    return None


def next_step(project, cand):
    return ENGINE.next_step(project, cand)


def status_of(project, cand):
    cf = rl._candidate_file(Path(project), cand)
    if not cf.exists():
        cf = Path(project) / "99_Archive" / f"{cand}.md"
    if not cf.exists():
        return "?"
    return rl._load_yaml_front(cf).get("current_status", "?")


def load_delta(project, cand, delta_key):
    df = rl._delta_for_candidate(Path(project), delta_key, cand)
    if df and df.exists():
        try:
            return json.loads(df.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def _recover_committed_advance(project, cand, step):
    """Resume a committed native delta whose state transition was interrupted."""
    if step.get("schema_version") != "2.1":
        return None
    try:
        profile = get_profile(step["profile_id"])
        delta_key = artifact_for_node(profile, step["node"]).storage_key
    except (KeyError, ValueError):
        return None
    delta = load_delta(project, cand, delta_key)
    if not delta or delta.get("schema_version") != "2.1":
        return None
    log(f"{step['node']}: committed v2.1 delta found; recovering advance only")
    try:
        advance(project, cand, step)
    except RuntimeError as exc:
        auto_pitfall(project, cand, step["node"], "advance_failure", str(exc),
                     provider="controller", evidence=str(project))
        log(f"{step['node']} recovery advance failed closed: {exc}")
        return False
    return True


def assemble_context(project, cand, node, authorization_id=None, evidence_run_id=None,
                     context_token_budget=None):
    return ENGINE.assemble_context(project, cand, node, authorization_id,
                                   evidence_run_id,
                                   context_token_budget=context_token_budget)


def _write_provider_delta(run_dir, node, persona, delta):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / f"{node}_{persona}_emit.json"
    tmp.write_text(json.dumps(delta, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    return tmp


def canonical_provider_emission(prov, run_dir, node, persona, delta):
    """Return the provider's original canonical file when it owns one.

    Command, headless, and manual providers already persist their JSON output.
    Re-serializing their parsed return value would create a competing identity.
    A provider without a persisted output delegates canonical production to the
    runner, which writes exactly one artifact.
    """
    raw_path = getattr(prov, "last_delta_file", None)
    if raw_path:
        path = Path(raw_path)
        if not path.is_file():
            raise ValueError(f"provider canonical delta is missing: {path}")
        try:
            persisted = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"provider canonical delta is unreadable: {path}") from exc
        if persisted != delta:
            raise ValueError(
                "provider returned data that differs from its persisted canonical delta"
            )
        return path, None
    return _write_provider_delta(run_dir, node, persona, delta), None


def emit_delta(project, cand, node, persona, delta, run_dir, receipt=None,
               provider_receipt=None):
    tmp = delta if isinstance(delta, Path) else _write_provider_delta(
        run_dir, node, persona, delta
    )
    r = ENGINE.emit_delta(
        project, cand, node, persona, tmp,
        context_manifest=receipt, provider_receipt=provider_receipt,
    )
    if r.returncode != 0:
        log(f"emit-delta {node} failed: {r.stdout.strip()} {r.stderr.strip()}")
    return r.returncode == 0


def _run_advance_command(*argv):
    """Run a state transition and fail closed when the controller rejects it."""
    result = _ctl(*argv)
    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip() or
                  f"controller exited with {result.returncode}")
        raise RuntimeError(f"{argv[0]} failed: {detail}")
    return result


def advance(project, cand, step):
    ac = step.get("advance_command")
    if step.get("node") == "L10b":
        _run_advance_command("finalize-candidate", project, cand)
    elif ac == "decision":
        _run_advance_command(
            "decision", project, cand, "--status", step.get("advance_status"),
            "--reason", step.get("advance_reason") or "auto")
    elif ac == "triage-idea":
        d = load_delta(project, cand, "L3_oppenheimer") or {}
        if d.get("schema_version") in ("2.0", "2.1"):
            _run_advance_command("triage-idea", project, cand)
        else:
            dec = "select" if d.get("selected") else "reject"
            _run_advance_command("triage-idea", project, cand,
                                 "--decision", dec,
                                 "--reason", d.get("reason") or "auto")
    elif ac == "triage-method":
        d = load_delta(project, cand, "L6_oppenheimer") or {}
        if d.get("schema_version") in ("2.0", "2.1"):
            _run_advance_command("triage-method", project, cand)
        else:
            dec = "approve" if d.get("approved_strategy") else "reject"
            _run_advance_command("triage-method", project, cand,
                                 "--decision", dec,
                                 "--reason", d.get("reason") or "auto")
    elif ac == "execution-gate":
        _run_advance_command("execution-gate", project, cand)
    elif ac == "aggregate-report":
        _run_advance_command("aggregate-report", project, cand)


def provider_for(node, cfg, args):
    return orch.make_provider(
        cfg.for_node(node), override_type=getattr(args, "provider", None)
    )


def _context_token_budget(cfg):
    value = (getattr(cfg, "data", {}) or {}).get(
        "context_token_budget", DEFAULT_CONTEXT_TOKEN_BUDGET
    )
    if value is None:
        value = DEFAULT_CONTEXT_TOKEN_BUDGET
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("context_token_budget must be a non-negative integer")
    return value


def agent_native_capabilities(profile_id: str) -> dict[str, bool]:
    """Report whether every cognition seam reachable in a profile is host-backed."""
    try:
        profile = get_profile(str(profile_id))
        _, node_map, _ = topology_for_profile(profile.profile_id)
    except (KeyError, TypeError, ValueError):
        return {}
    host_prepare = callable(globals().get("prepare_host_step"))
    host_submit = callable(globals().get("submit_host_step"))
    deep_receipt = callable(getattr(deep_research, "_host_literature_payload", None))
    literature_prepare = callable(globals().get("_prepare_host_literature"))
    literature_submit = callable(globals().get("_submit_host_literature"))
    deep_persist = callable(getattr(deep_research, "persist_run", None))
    deep_audit = callable(getattr(deep_research, "audit_evidence_pack", None))
    return {
        "L1_native_binding": bool(
            "L1" in node_map
            and callable(globals().get("_native_l1_binding_ready"))
            and callable(globals().get("_ensure_native_l1_recall"))
        ),
        "L4_literature": bool(
            "L4" in node_map and host_prepare and host_submit and deep_receipt
        ),
        "L8.5_literature": bool(
            "L8.5" in node_map and host_prepare and host_submit
            and literature_prepare and literature_submit and deep_receipt
            and deep_persist and deep_audit
        ),
        "pre_research_text": bool(host_prepare and host_submit),
        "L7_text_preparation": bool(
            "L7" in node_map and host_prepare and host_submit
        ),
        "L7_delta": bool("L7" in node_map and host_prepare and host_submit),
        "REVIEW": bool(host_prepare and host_submit and callable(_validate_review_response)),
    }


def _provider_output_schema(project, node, step):
    """Resolve the provider submission schema from the bound project profile."""
    native_binding = (Path(project) / "00_Preflight" /
                      "hypothesis_store_binding.json").exists()
    if not native_binding:
        persona = step.get("persona", "").lower()
        return rl.DELTA_SCHEMAS.get(f"{node}_{persona}")
    schema_version = str(step.get("schema_version") or "")
    profile_id = str(step.get("profile_id") or "")
    schema = provider_schema_for_profile(profile_id, node, schema_version)
    if schema is None:
        raise RuntimeError(
            f"provider schema is unavailable for bound schema {schema_version!r} "
            f"profile {profile_id!r} and node {node!r}"
        )
    return schema


def preflight_providers(cfg, args):
    override = getattr(args, "provider", None)
    if override == "manual":
        log("provider: MANUAL (debug mode, explicitly requested via --provider manual)")
        return True
    specs = [("provider.default", cfg.default)]
    specs += [(f"provider.nodes.{n}", s) for n, s in cfg.nodes.items()]
    for label, spec in specs:
        t = override or (spec or {}).get("type")
        if t == "manual":
            log(f"ERROR: {label}.type = 'manual', but manual is DEBUG-ONLY.")
            log("       Configure an automatic provider (type: host | command),")
            log("       e.g. set $RLR_HOST_AGENT_CMD, or run with --provider manual "
                "to force debug mode.")
            return False
        try:
            orch.make_provider(spec, override_type=override)
        except orch.ProviderError as e:
            log(f"ERROR: {label} is not runnable automatically:")
            for ln in str(e).splitlines():
                log(f"       {ln}")
            return False
    log(f"provider: AUTOMATIC ({override or cfg.default.get('type')})")
    return True


def write_receipt(run_dir, node, persona, prov, context, step, cand, round_id,
                  *, manifest=None, provider_delta_file=None, workspace=None,
                  config_path=None, raw_provider_delta_file=None,
                  transformation_receipt_file=None, execution_status=None):
    manifest_data = {}
    rendered_bytes = None
    if manifest:
        (manifest_data, rendered_path, rendered_bytes,
         _rendered_text) = load_rendered_context_artifact(manifest)
    prompt_file = getattr(prov, "last_prompt_file", None)
    delta_file = getattr(prov, "last_delta_file", None)
    provider_delta_file = Path(provider_delta_file) if provider_delta_file else None
    raw_provider_delta_file = Path(
        raw_provider_delta_file or provider_delta_file
    ) if (raw_provider_delta_file or provider_delta_file) else None
    transformation_receipt_file = Path(transformation_receipt_file) if transformation_receipt_file else None
    rendered_context_hash = manifest_data.get("rendered_context_sha256")
    if manifest:
        if context.encode("utf-8") != rendered_bytes:
            raise ValueError("context bytes do not match manifest rendered context bytes")
    code_state = capture_code_state(HERE, config_path) if config_path else None
    execution_status = execution_status or getattr(
        prov, "last_execution_status", None
    )
    rec = orch.RunReceipt(
        node=node, persona=persona,
        provider=getattr(prov, "name", getattr(prov, "type", "?")),
        timestamp=orch.now(),
        context_hash=(rendered_context_hash
                      or hashlib.sha256(context.encode("utf-8")).hexdigest()),
        prompt_file=prompt_file,
        prompt_hash=(hashlib.sha256(Path(prompt_file).read_bytes()).hexdigest()
                     if prompt_file and Path(prompt_file).is_file() else None),
        delta_file=delta_file,
        delta_hash=(hashlib.sha256(Path(delta_file).read_bytes()).hexdigest()
                    if delta_file and Path(delta_file).is_file() else None),
        workspace=workspace,
        allowed_tools=([step.get("tools_policy")] if step.get("tools_policy")
                       else None),
        everos_scope=step.get("everos_read_scopes"),
        fresh_session=getattr(prov, "last_fresh_session", None),
        project_id=manifest_data.get("project_id"),
        candidate_id=cand, round_id=str(round_id),
        profile_id=step.get("profile_id", "v2.0-legacy"),
        context_manifest_path=str(manifest or ""),
        context_manifest_hash=(hashlib.sha256(Path(manifest).read_bytes()).hexdigest()
                               if manifest else None),
        rendered_context_path=manifest_data.get("rendered_context_path"),
        rendered_context_hash=rendered_context_hash,
        provider_delta_path=str(provider_delta_file or ""),
        provider_delta_hash=(hashlib.sha256(provider_delta_file.read_bytes()).hexdigest()
                             if provider_delta_file else None),
        raw_provider_delta_path=str(raw_provider_delta_file or ""),
        raw_provider_delta_hash=(hashlib.sha256(raw_provider_delta_file.read_bytes()).hexdigest()
                                 if raw_provider_delta_file else None),
        transformation_receipt_path=str(transformation_receipt_file or ""),
        transformation_receipt_hash=(
            hashlib.sha256(transformation_receipt_file.read_bytes()).hexdigest()
            if transformation_receipt_file else None
        ),
        git_head=(code_state or {}).get("git_head"),
        git_dirty=(code_state or {}).get("git_dirty"),
        working_tree_diff_sha256=(code_state or {}).get("working_tree_diff_sha256"),
        config_sha256=(code_state or {}).get("config_sha256"),
        code_state_id=(code_state or {}).get("code_state_id"),
        schema_version="RunReceipt/v2" if code_state else "RunReceipt/v1",
        exit_code=getattr(prov, "last_exit_code", None),
        timed_out=getattr(prov, "last_timed_out", None),
        terminal_state=getattr(prov, "last_terminal_state", None),
        execution_status=execution_status,
    )
    attempt_number = getattr(prov, "last_attempt_number", None) or 1
    path = provider_attempt_path(
        run_dir, node, persona, "receipt", ".json", attempt_number
    )
    if path.exists():
        raise ValueError(
            f"provider attempt receipt already exists and is immutable: {path}"
        )
    rec.write(path)
    return str(path)


def _write_provider_failure_receipt(run_dir, node, persona, prov, context,
                                    step, cand, round_id, manifest=None,
                                    workspace=None, config_path=None):
    """Persist a failed provider invocation without inventing canonical output.

    If the process produced raw bytes before an output-contract failure, retain
    that exact artifact path/hash while keeping canonical provider_delta absent.
    """
    if not getattr(prov, "last_prompt_file", None):
        return None
    raw_output = getattr(prov, "last_delta_file", None)
    raw_output = (
        Path(raw_output)
        if raw_output and Path(raw_output).is_file()
        else None
    )
    try:
        return write_receipt(
            run_dir, node, persona, prov, context, step, cand, round_id,
            manifest=manifest, workspace=workspace, config_path=config_path,
            raw_provider_delta_file=raw_output,
            execution_status="failed",
        )
    except (OSError, ValueError) as exc:
        log(f"{node} provider failure receipt could not be persisted: {exc}")
        return None


def _shadow_run_id(node, cand, round_id, candidates, seed, match_budget):
    identity = json.dumps({"stage": node, "candidate": cand, "round": round_id,
                           "candidates": sorted(candidates), "seed": seed,
                           "match_budget": match_budget}, sort_keys=True)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"shadow-{node.lower()}-r{round_id}-{digest}"


def _write_shadow_failure_audit(project, run_id, node, cand, error, command,
                                seed, match_budget, outcome="failed"):
    try:
        audit_dir = Path(project) / "08_Audit" / "ranking"
        audit_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "shadow-ranking-failure-v1",
            "run_id": run_id,
            "stage": node,
            "candidate_id": cand,
            "outcome": outcome,
            "error": str(error),
            "provenance": {
                "shadow_mode": "fail-soft",
                "command": command,
                "seed": seed,
                "match_budget": match_budget,
            },
        }
        serialized = json.dumps(payload, indent=2, ensure_ascii=False)
        for attempt in range(1, 1000):
            suffix = "" if attempt == 1 else f".{attempt}"
            target = audit_dir / f"{run_id}.{outcome}{suffix}.json"
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                        mode="w", encoding="utf-8", dir=audit_dir,
                        prefix=f".{target.name}.", suffix=".tmp", delete=False) as handle:
                    temp_path = Path(handle.name)
                    handle.write(serialized)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.link(temp_path, target)
                temp_path.unlink()
                return
            except FileExistsError:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
                continue
            except Exception:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
                raise
        raise RuntimeError("unable to allocate a shadow ranking audit filename")
    except Exception as exc:
        log(f"shadow ranking failure audit skipped: {exc}")


def _shadow_artifact_status(project, run_id, stage, candidates, seed, match_budget):
    base = Path(project) / "08_Audit" / "ranking"
    paths = {
        "artifact": base / f"{run_id}.json",
        "checkpoint": base / f"{run_id}.checkpoint.json",
        "report": base / f"{run_id}.md",
        "marker": base / f"{run_id}.complete.json",
    }
    present = {name: path.exists() for name, path in paths.items()}
    if not any(present.values()):
        return "absent", paths, "no prior ranking outputs"
    if not present["marker"]:
        return "partial", paths, "ranking outputs exist without a completion marker"
    if not all(present.values()):
        missing = [name for name, exists in present.items() if not exists]
        return "partial", paths, f"missing outputs: {', '.join(missing)}"
    try:
        marker = json.loads(paths["marker"].read_text(encoding="utf-8"))
        if not isinstance(marker, dict):
            raise ValueError("completion marker is not a JSON object")
        if marker.get("run_id") != run_id:
            raise ValueError(f"completion marker run_id does not match {run_id}")
        if marker.get("stage") != stage:
            raise ValueError(f"completion marker stage does not match {stage}")
        optional_values = {
            "candidate_ids": sorted(candidates), "candidates": sorted(candidates),
            "candidate_set": sorted(candidates),
            "seed": seed, "match_budget": match_budget,
        }
        for key, expected in optional_values.items():
            if key in marker and marker[key] != expected:
                raise ValueError(f"completion marker {key} does not match this run")
        if isinstance(marker.get("budget"), dict) and "matches" in marker["budget"] \
                and marker["budget"]["matches"] != match_budget:
            raise ValueError("completion marker budget does not match this run")
        hashes = marker.get("sha256")
        if not isinstance(hashes, dict):
            raise ValueError("completion marker has no sha256 mapping")
        for name in ("artifact", "checkpoint", "report"):
            actual = hashlib.sha256(paths[name].read_bytes()).hexdigest()
            if hashes.get(name) != actual:
                raise ValueError(f"completion marker hash mismatch for {name}")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return "partial", paths, f"invalid outputs: {exc}"
    return "complete", paths, "validated completion marker and output hashes"


def run_shadow_ranking(project, cand, node, args, round_id):
    if not getattr(args, "shadow_ranking", False) or node not in ("L3", "L10b"):
        return
    candidates = []
    for candidate_id in [cand, *(getattr(args, "shadow_candidate", None) or [])]:
        if candidate_id and candidate_id not in candidates:
            candidates.append(candidate_id)
    seed = getattr(args, "shadow_seed", 0)
    match_budget = getattr(args, "shadow_match_budget", 10)
    requested_timeout = getattr(args, "shadow_timeout", 60)
    try:
        timeout = min(max(int(requested_timeout), 1), 600)
    except (TypeError, ValueError):
        timeout = 60
    run_id = _shadow_run_id(node, cand, round_id, candidates, seed, match_budget)
    if len(candidates) < 2:
        error = "shadow ranking requires at least two distinct candidates"
        log(f"shadow ranking skipped (non-fatal): {error}")
        _write_shadow_failure_audit(project, run_id, node, cand, error, None,
                                    seed, match_budget, outcome="skipped")
        return
    artifact_status, artifact_paths, artifact_reason = _shadow_artifact_status(
        project, run_id, node, candidates, seed, match_budget)
    if artifact_status == "complete":
        log(f"shadow ranking already complete: {run_id}")
        return
    if artifact_status == "partial":
        path_text = ", ".join(f"{name}={path}" for name, path in artifact_paths.items())
        error = (f"partial shadow ranking outputs for {run_id}: {artifact_reason}; "
                 f"paths={{{path_text}}}")
        log(f"shadow ranking skipped (non-fatal): {error}")
        _write_shadow_failure_audit(project, run_id, node, cand, error, None,
                                    seed, match_budget, outcome="partial")
        return
    command = [sys.executable, str(CONTROLLER), "ranking-shadow", str(project),
               "--stage", node]
    for candidate_id in candidates:
        command.extend(["--candidate", candidate_id])
    command.extend(["--seed", str(seed), "--match-budget", str(match_budget),
                    "--run-id", run_id])
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            post_status, post_paths, post_reason = _shadow_artifact_status(
                project, run_id, node, candidates, seed, match_budget)
            if post_status == "complete":
                log(f"shadow ranking complete: {run_id}")
                return
            path_text = ", ".join(f"{name}={path}" for name, path in post_paths.items())
            error = (f"ranking-shadow exited successfully without a valid completion marker "
                     f"for {run_id}: status={post_status}; reason={post_reason}; "
                     f"paths={{{path_text}}}")
            log(f"shadow ranking partial (non-fatal): {error}")
            _write_shadow_failure_audit(project, run_id, node, cand, error, command,
                                        seed, match_budget, outcome="partial")
            return
        error = result.stderr.strip() or result.stdout.strip() or \
            f"ranking-shadow exited {result.returncode}"
    except subprocess.TimeoutExpired:
        error = f"ranking-shadow timed out after {timeout}s"
    except Exception as exc:
        error = f"ranking-shadow launch failed: {exc}"
    log(f"shadow ranking failed (non-fatal): {error}")
    _write_shadow_failure_audit(project, run_id, node, cand, error, command,
                                seed, match_budget)


def exec_cognitive(project, cand, step, cfg, args, run_dir, round_id,
                   do_advance=True, authorization_id=None, failure_state=None):
    node, persona = step["node"], step["persona"]
    evidence_run_id = getattr(args, "evidence_run_ids", {}).get(node)
    ctx, manifest = assemble_context(project, cand, node, authorization_id,
                                     evidence_run_id, _context_token_budget(cfg))
    if node == "L0":
        ok_c, c_reason = rl._audit_l0_contract(Path(project), cand)
        if not ok_c:
            raise RuntimeError(f"L0 input-contract gate (pre-dispatch): {c_reason}")
    prov = provider_for(node, cfg, args)
    pname = getattr(prov, "name", getattr(prov, "type", "unknown"))
    schema = _provider_output_schema(project, node, step)
    try:
        delta = prov.run_agent(node, persona, ctx, output_schema=schema,
                               tools=step.get("tools_policy"),
                               run_dir=str(run_dir))
    except ProviderOutputContractError as exc:
        failure_receipt = _write_provider_failure_receipt(
            run_dir, node, persona, prov, ctx, step, cand, round_id,
            manifest=manifest, config_path=getattr(cfg, "source_path", None),
        )
        auto_pitfall(project, cand, node, "provider_contract_failure",
                     str(exc), provider=pname,
                     evidence=str(failure_receipt or run_dir))
        _record_runtime_failure(
            failure_state, node, "CONTRACT", "provider_artifact_contract", run_dir
        )
        return False
    except Exception as e:
        failure_receipt = _write_provider_failure_receipt(
            run_dir, node, persona, prov, ctx, step, cand, round_id,
            manifest=manifest, config_path=getattr(cfg, "source_path", None),
        )
        auto_pitfall(project, cand, node, "provider_failure",
                     f"{persona} provider raised: {e}", provider=pname,
                     evidence=str(failure_receipt or run_dir))
        _record_runtime_failure(
            failure_state, node, "EXTERNAL", "provider_invocation_error", run_dir
        )
        return False
    try:
        raw_emitted, _ = canonical_provider_emission(
            prov, run_dir, node, persona, delta
        )
        provider_receipt = write_receipt(
            run_dir, node, persona, prov, ctx, step, cand, round_id,
            manifest=manifest, provider_delta_file=raw_emitted,
            config_path=getattr(cfg, "source_path", None),
        )
    except (ValueError, deep_research.DeepResearchError) as exc:
        auto_pitfall(project, cand, node, "provider_contract_failure", str(exc),
                     provider=pname, evidence=str(run_dir))
        _record_runtime_failure(
            failure_state, node, "CONTRACT", "provider_artifact_contract", run_dir
        )
        return False
    ok = emit_delta(project, cand, node, persona, raw_emitted, run_dir,
                    receipt=manifest, provider_receipt=provider_receipt)
    if not ok:
        auto_pitfall(project, cand, node, "emit_delta_failure",
                     f"{persona} delta rejected by emit-delta (schema/validation)",
                     provider=pname, evidence=str(run_dir))
        _record_runtime_failure(
            failure_state, node, "CONTRACT", "emit_delta_rejected", run_dir
        )
    if ok and do_advance:
        run_shadow_ranking(project, cand, node, args, round_id)
        try:
            advance(project, cand, step)
        except RuntimeError as exc:
            auto_pitfall(project, cand, node, "advance_failure", str(exc),
                         provider="controller", evidence=str(run_dir))
            _record_runtime_failure(
                failure_state, node, "IMPLEMENTATION", "state_transition_rejected", run_dir
            )
            log(f"{node} advance failed closed: {exc}")
            return False
    return ok


def exec_turing(project, cand, step, cfg, args, run_dir, round_id, exec_state):
    if status_of(project, cand) == "METHOD_APPROVED":
        r = _ctl("execution-gate", project, cand)
        if r.returncode != 0:
            log(f"execution-gate rejected: {r.stdout.strip()}")
            _record_runtime_failure(
                exec_state, "L7", "CONTRACT", "execution_gate_rejected", run_dir
            )
            return False
    r = _ctl("prepare-turing-workspace", project, cand, "--clean")
    if r.returncode != 0:
        exec_state["l7_failures"] += 1
        log(f"prepare-turing-workspace rejected: "
            f"{r.stderr.strip() or r.stdout.strip()}")
        auto_pitfall(project, cand, "L7", "execution_failure",
                     "Turing workspace preparation failed",
                     provider="controller", evidence=str(run_dir))
        _record_runtime_failure(
            exec_state, "L7", "IMPLEMENTATION", "workspace_preparation_failed", run_dir
        )
        return False
    workspace = None
    for line in r.stdout.splitlines():
        if "Turing workspace ready:" in line:
            workspace = line.split("ready:", 1)[1].strip()
    ctx, manifest = assemble_context(
        project, cand, "L7", context_token_budget=_context_token_budget(cfg)
    )
    prov = provider_for("L7", cfg, args)
    pname = getattr(prov, "name", getattr(prov, "type", "unknown"))
    schema = _provider_output_schema(project, "L7", step)
    try:
        delta = prov.run_agent("L7", "Turing", ctx, output_schema=schema,
                               workspace=workspace,
                               tools=step.get("tools_policy") or "workspace-fs",
                               run_dir=str(run_dir))
    except ProviderOutputContractError as exc:
        failure_receipt = _write_provider_failure_receipt(
            run_dir, "L7", "Turing", prov, ctx, step, cand, round_id,
            manifest=manifest, workspace=workspace,
            config_path=getattr(cfg, "source_path", None),
        )
        auto_pitfall(project, cand, "L7", "provider_contract_failure",
                     str(exc), provider=pname,
                     evidence=str(failure_receipt or workspace or run_dir))
        _record_runtime_failure(
            exec_state, "L7", "CONTRACT", "provider_artifact_contract", run_dir
        )
        return False
    except Exception as e:
        exec_state["l7_failures"] += 1
        failure_receipt = _write_provider_failure_receipt(
            run_dir, "L7", "Turing", prov, ctx, step, cand, round_id,
            manifest=manifest, workspace=workspace,
            config_path=getattr(cfg, "source_path", None),
        )
        log(f"L7 provider failed ({e}); failures={exec_state['l7_failures']}")
        auto_pitfall(project, cand, "L7", "execution_failure",
                     f"Turing execution provider failed: {e}", provider=pname,
                     evidence=str(failure_receipt or workspace or run_dir))
        _record_runtime_failure(
            exec_state, "L7", "EXTERNAL", "provider_invocation_error", run_dir
        )
        return False
    try:
        emitted, _ = canonical_provider_emission(prov, run_dir, "L7", "Turing", delta)
        provider_receipt = write_receipt(
            run_dir, "L7", "Turing", prov, ctx, step, cand, round_id,
            manifest=manifest, provider_delta_file=emitted, workspace=workspace,
            config_path=getattr(cfg, "source_path", None),
        )
    except ValueError as exc:
        auto_pitfall(project, cand, "L7", "provider_contract_failure", str(exc),
                     provider=pname, evidence=workspace or str(run_dir))
        _record_runtime_failure(
            exec_state, "L7", "CONTRACT", "provider_artifact_contract", run_dir
        )
        return False
    ok = emit_delta(project, cand, "L7", "Turing", emitted, run_dir,
                    receipt=manifest, provider_receipt=provider_receipt)
    if not ok:
        exec_state["l7_failures"] += 1
        log(f"L7 emit failed; failures={exec_state['l7_failures']}")
        auto_pitfall(project, cand, "L7", "emit_delta_failure",
                     "Turing L7 delta rejected by emit-delta (schema/validation)",
                     provider=pname, evidence=workspace or str(run_dir))
        _record_runtime_failure(
            exec_state, "L7", "CONTRACT", "emit_delta_rejected", run_dir
        )
        return False
    try:
        _run_advance_command(
            "decision", project, cand, "--status", "EXECUTED",
            "--reason", "Turing execution complete",
        )
    except RuntimeError as exc:
        auto_pitfall(project, cand, "L7", "advance_failure", str(exc),
                     provider="controller", evidence=workspace or str(run_dir))
        _record_runtime_failure(
            exec_state, "L7", "IMPLEMENTATION", "state_transition_rejected", run_dir
        )
        return False
    return True


def _l05_command(project, cand, cfg):
    """Build the bounded, reproducible command for the native L0.5 adapter."""
    data = getattr(cfg, "data", {}) or {}
    settings = data.get("l05_acquisition", {}) if isinstance(data, dict) else {}
    if not isinstance(settings, dict):
        raise ValueError("l05_acquisition configuration must be a mapping")

    try:
        selected = orch.make_provider(cfg.for_node("L0.5"))
    except (AttributeError, orch.ProviderError) as exc:
        raise ValueError(f"L0.5 semantic assessor provider is invalid: {exc}") from exc
    assessor_command = getattr(selected, "command", None)
    assessor_timeout = getattr(selected, "timeout", None)
    if not isinstance(assessor_command, str) or not assessor_command.strip():
        raise ValueError("L0.5 semantic assessor requires a headless command")
    if assessor_timeout is None:
        assessor_timeout = 300
    if (not isinstance(assessor_timeout, int) or isinstance(assessor_timeout, bool)
            or assessor_timeout <= 0):
        raise ValueError("L0.5 semantic assessor timeout must be a positive integer")

    command = ["l05-acquire-europepmc", str(project), str(cand)]
    queries = settings.get("queries", settings.get("explicit_queries"))
    if queries is not None:
        if (not isinstance(queries, list) or not queries or
                not all(isinstance(query, str) and query.strip() for query in queries)):
            raise ValueError("l05_acquisition.queries must be a non-empty list of strings")
        for query in queries:
            command.extend(["--query", query.strip()])

    bounds = {
        "max_papers": (1, 1000),
        "page_size": (1, 1000),
        "timeout": (1, None),
    }
    for key, (minimum, maximum) in bounds.items():
        if key not in settings:
            continue
        value = settings[key]
        if (not isinstance(value, int) or isinstance(value, bool) or value < minimum or
                (maximum is not None and value > maximum)):
            limit = f"-{maximum}" if maximum is not None else ""
            raise ValueError(
                f"l05_acquisition.{key} must be an integer in [{minimum}{limit}]"
            )
        command.extend([f"--{key.replace('_', '-')}", str(value)])
    command.extend([
        "--semantic-assessor-command", assessor_command,
        "--semantic-assessor-timeout", str(assessor_timeout),
    ])
    return command


def exec_l05(project, cand, step, cfg, args, run_dir, round_id):
    """Return a typed first-acquisition outcome to the DAG runner."""
    try:
        command = _l05_command(project, cand, cfg)
    except ValueError as exc:
        return {"terminal_status": "ERROR", "error_category": "CONTRACT_ERROR",
                "detail": f"invalid L0.5 Curie configuration: {exc}"}
    result = _ctl(*command)
    if result.returncode != 0:
        try:
            failure = json.loads(result.stdout)
        except (ValueError, TypeError):
            failure = {}
        category = failure.get("error_category", "ERROR") if isinstance(failure, dict) else "ERROR"
        detail = (failure.get("detail") if isinstance(failure, dict) else None) or (
            result.stderr.strip() or result.stdout.strip() or "L0.5 Curie acquisition failed"
        )
        log(f"L0.5 Curie {category}: {detail}")
        auto_pitfall(project, cand, "L0.5", "evidence_acquisition_failure",
                     detail, provider="curie-europe-pmc", evidence=str(run_dir))
        return {"terminal_status": "ERROR", "error_category": category, "detail": detail}
    try:
        acquisition = json.loads(result.stdout)
        acquisition = validate_europepmc_acquisition_result(project, cand, acquisition)
    except (ValueError, OSError, CurieAcquisitionError,
            research_seed.ResearchSeedError) as exc:
        detail = f"L0.5 Curie result invalid: {exc}"
        log(detail)
        auto_pitfall(project, cand, "L0.5", "evidence_acquisition_failure",
                     detail, provider="curie-europe-pmc", evidence=str(run_dir))
        category = exc.category if isinstance(exc, CurieAcquisitionError) else "CONTRACT_ERROR"
        return {"terminal_status": "ERROR", "error_category": category,
                "detail": detail}
    if acquisition["status"] == "INSUFFICIENT_STOP":
        log(f"L0.5 Curie insufficient: {acquisition['terminal_reason']}")
        return {
            "terminal_status": "L0_5_INSUFFICIENT_STOP",
            "completed": False, "full_dag_completed": False,
            "terminal_reason": acquisition["terminal_reason"],
            "acquisition_run_id": acquisition["run_id"],
            "acquisition_manifest_path": acquisition["acquisition_manifest_path"],
            "acquisition_manifest_sha256": acquisition["acquisition_manifest_sha256"],
        }
    if acquisition["status"] != "FROZEN":
        return {"terminal_status": "ERROR", "error_category": "CONTRACT_ERROR",
                "detail": f"unexpected L0.5 status: {acquisition['status']}"}
    acquisition_run_id = acquisition["run_id"]
    evidence_pack = acquisition["evidence_pack"]
    try:
        seed = research_seed.load_l1_research_seed(project, cand)
        research_seed.write_l1_native_evidence_binding(
            project, seed, evidence_pack, acquisition_run_id
        )
        research_seed.activate_l1_native_evidence_binding(
            project, seed, acquisition_run_id
        )
        active_run_id = research_seed.active_l1_native_evidence_run_id(project, seed)
        if str(active_run_id or "") != acquisition_run_id:
            raise ValueError("native L1 activation did not select the acquired run")
    except (ValueError, research_seed.ResearchSeedError) as exc:
        detail = f"L0.5 Curie binding invalid: {exc}"
        log(detail)
        auto_pitfall(project, cand, "L0.5", "evidence_acquisition_failure",
                     detail, provider="curie-europe-pmc", evidence=str(run_dir))
        return {"terminal_status": "ERROR", "error_category": "BINDING_ERROR",
                "detail": detail}
    log(f"L0.5 Curie: frozen EvidencePack bound and activated for {acquisition_run_id}")
    return {"terminal_status": "FROZEN", "acquisition_run_id": acquisition_run_id}


def _deep_research_config(cfg):
    data = getattr(cfg, "data", {}) or {}
    value = data.get("deep_research", {}) if isinstance(data, dict) else {}
    return value if isinstance(value, dict) else {}


def _native_l1_binding_root(project, cand):
    return (Path(project) / "08_Audit" / "research_seed_bindings" /
            "native" / str(cand))


def _native_l1_binding_ready(project, cand):
    """Validate the active native binding without falling back to legacy DR."""
    try:
        seed = research_seed.load_l1_research_seed(project, cand)
        run_id = research_seed.active_l1_native_evidence_run_id(project, seed)
        if not run_id:
            return False
        binding = research_seed.load_l1_native_evidence_binding(
            project, seed, run_id
        )
        return str(binding.get("acquisition_run_id") or "") == str(run_id)
    except (research_seed.ResearchSeedError, OSError, ValueError):
        return False


def _bound_profile_id(project):
    """Read the immutable profile binding without inferring from runtime data."""
    try:
        binding = json.loads(rl.binding_path(project).read_text(encoding="utf-8"))
        return str(binding.get("profile_id") or "").strip()
    except (OSError, TypeError, json.JSONDecodeError):
        return ""


def _ensure_native_l1_recall(project, cand):
    """Create the fixed-cursor recall artifact required by native L1 once."""
    project = Path(project)
    try:
        seed = research_seed.load_l1_research_seed(project, cand)
    except research_seed.ResearchSeedError as exc:
        log(f"ERROR: native L1 recall seed is invalid: {exc}")
        return False
    target = (project / "08_Audit" / "hypothesis_recall" /
              f"{cand}_round_{seed['round_id']}.json")
    if target.is_file():
        return True
    store = os.environ.get("RLR_HYPOTHESIS_STORE", "").strip()
    if not store:
        log("ERROR: native L1 recall requires RLR_HYPOTHESIS_STORE")
        return False
    query = " ".join((
        str(seed["scientific_question"]),
        str(seed["hypothesis_seed"]),
    )).strip()
    result = _ctl(
        "hypothesis-recall", str(project), str(cand),
        "--round-id", str(seed["round_id"]), "--query", query,
        "--knowledge-store", store,
    )
    if result.returncode != 0 or not target.is_file():
        detail = (result.stderr.strip() or result.stdout.strip() or
                  "recall artifact was not created")
        log(f"ERROR: native L1 recall failed closed: {detail}")
        return False
    log(f"native L1 recall: fixed-cursor artifact created at {target}")
    return True


def ensure_pre_research(project, cand, node, cfg, args, run_dir):
    native_catalog = _bound_profile_id(project) == PROFILE_V21_CATALOG_1
    if native_catalog and node == "L1":
        if not _native_l1_binding_root(project, cand).is_dir():
            log("ERROR: native L1 requires an active frozen L0.5 EvidencePack")
            return False
        if not _native_l1_binding_ready(project, cand):
            log("ERROR: native L1 binding exists but is not valid/active")
            return False
        if not _ensure_native_l1_recall(project, cand):
            return False
        log("native L1 binding already active; independent literature search is not applicable")
        return True
    if getattr(args, "mode", None) == "agent_native" and node in {
        "L4", "L8.5", *rl.PRE_RESEARCH_MAP.keys()
    }:
        log(
            f"ERROR: agent-native {node} pre-research requires the current action "
            "and cursor; use prepare_host_step instead of ensure_pre_research"
        )
        return False
    if native_catalog and node in {"L4", "L8.5"}:
        existing = _ctl("audit-literature-evidence", project, cand, "--node", node)
        if existing.returncode == 0:
            try:
                run_id = str(json.loads(existing.stdout).get("run_id") or "")
            except (TypeError, json.JSONDecodeError):
                run_id = ""
            if run_id:
                args.evidence_run_ids = getattr(args, "evidence_run_ids", {})
                args.evidence_run_ids[node] = run_id
                log(f"native {node}: valid canonical literature run already present: {run_id}")
                return True
        dr_cfg = _deep_research_config(cfg)
        backend = str(dr_cfg.get("backend", "")).strip()
        if backend and backend not in SUPPORTED_BACKENDS:
            log(f"ERROR: native {node} runner override deep_research.backend={backend!r} must be one of {SUPPORTED_BACKENDS}")
            return False
        command = ["deep-research-run", project, cand, "--node", node]
        if backend:
            command.extend(["--backend", backend])
        for option, key in (("--executable", "executable"), ("--model", "model"), ("--timeout", "timeout")):
            value = dr_cfg.get(key)
            if value not in (None, ""):
                command.extend([option, str(value)])
        result = _ctl(*command)
        if result.returncode != 0:
            log(f"ERROR: native {node} canonical literature run failed closed: {(result.stderr or result.stdout).strip()}")
            return False
        try:
            run_id = str(json.loads(result.stdout)["run_id"])
        except (KeyError, TypeError, json.JSONDecodeError):
            log(f"ERROR: native {node} command did not return a run_id")
            return False
        args.evidence_run_ids = getattr(args, "evidence_run_ids", {})
        args.evidence_run_ids[node] = run_id
        log(f"native {node}: persisted canonical literature run {run_id}")
        return True
    if node not in rl.PRE_RESEARCH_MAP:
        return True
    if node == "L1" and _native_l1_binding_root(project, cand).is_dir():
        if not _native_l1_binding_ready(project, cand):
            log("ERROR: native L1 binding exists but is not valid/active")
            return False
        if not _ensure_native_l1_recall(project, cand):
            return False
        log("native L1 binding already active; legacy Deep Research is not applicable")
        return True
    target = (Path(project) / "02_Agent_Notes" / "_pre_research"
              / f"{node}_research.md")
    if node in ("L1", "L4", "L8.5"):
        existing = _ctl("audit-literature-evidence", project, cand, "--node", node)
        if target.exists() and existing.returncode == 0:
            log(f"Deep Research {node}: valid evidence pack already present")
            return True
        dr_cfg = _deep_research_config(cfg)
        backend = str(dr_cfg.get("backend", "")).strip()
        if backend and backend not in SUPPORTED_BACKENDS:
            log(f"ERROR: Deep Research {node} runner override "
                f"deep_research.backend={backend!r} must be one of {SUPPORTED_BACKENDS}")
            return False
        command = ["deep-research-run", project, cand, "--node", node]
        if backend:
            command.extend(["--backend", backend])
        for option, key in (("--executable", "executable"), ("--plugin-dir", "plugin_dir"),
                            ("--skill-path", "skill_path"), ("--skill-version", "skill_version"),
                            ("--model", "model"), ("--timeout", "timeout")):
            value = dr_cfg.get(key)
            if value not in (None, ""):
                command.extend([option, str(value)])
        result = _ctl(*command)
        if result.returncode != 0:
            log(f"ERROR: Deep Research {node} failed closed: "
                f"{(result.stderr or result.stdout).strip()}")
            return False
        try:
            artifact = json.loads(result.stdout)
            args.evidence_run_ids = getattr(args, "evidence_run_ids", {})
            args.evidence_run_ids[node] = artifact["run_id"]
        except (KeyError, json.JSONDecodeError):
            log(f"ERROR: Deep Research {node} did not return a run_id")
            return False
        log(f"Deep Research {node}: persisted verified evidence pack {artifact['run_id']}")
        return True
    if target.exists():
        log(f"pre-research {node}: already present")
        return True
    research = _ctl("pre-research", project, cand, "--node", node)
    if research.returncode != 0:
        detail = (research.stderr or research.stdout or "pre-research prompt failed").strip()
        log(f"ERROR: pre-research {node} prompt failed closed: {detail}")
        return False
    try:
        provider = provider_for(node, cfg, args)
        md = provider.run_text(
            research.stdout, run_dir, f"prefetch_{node}"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(md, encoding="utf-8")
        log(f"pre-research {node}: produced {target}")
    except Exception as e:
        log(f"ERROR: pre-research {node} failed closed: {e}")
        return False
    return True


def _bump_node_failure(exec_state, node, max_node_failures):
    counts = exec_state.setdefault("node_failures", {})
    counts[node] = counts.get(node, 0) + 1
    return counts[node] >= max_node_failures


def _step_action_kind(step):
    if step.get("terminal"):
        return "terminal"
    if step.get("is_parallel"):
        return "cognitive"
    node = step.get("node")
    if node == "L0.5":
        return "l05"
    if node == "L7":
        return "l7"
    if node == "L10c":
        return "report"
    if node == "REVIEW":
        return "review"
    return "cognitive"


def current_action(project, cand, cfg, args, round_id, exec_state) -> dict:
    """Return the shared RLR action for the current authoritative next-step."""
    mode = getattr(args, "mode", "headless")
    if mode not in ("headless", "agent_native"):
        raise ValueError(f"unsupported execution mode: {mode!r}")

    step = next_step(project, cand)
    profile_id = step.get("profile_id") or _bound_profile_id(project) or PROFILE_V20
    expected_cursor = exec_state.get("cursor")
    cursor = None
    if (profile_id == PROFILE_V21_CATALOG_1 and
            (expected_cursor is not None or _bound_profile_id(project) == profile_id)):
        ledger = rl._ledger_for(
            project, getattr(args, "knowledge_store", None), readonly=True
        )
        cursor = ledger.snapshot_candidate(project, cand, str(round_id))
        if expected_cursor is not None and expected_cursor != cursor:
            raise RuntimeError(
                f"stale cursor for {cand} round {round_id}: expected caller cursor "
                "does not match the current authoritative ledger snapshot"
            )

    nodes = step.get("nodes") or []
    action_identity = {
        "profile_id": profile_id,
        "round_id": str(round_id),
        "cursor": cursor,
        "nodes": [item.get("node") for item in nodes] if nodes
        else [step.get("node")],
    }
    kind = _step_action_kind(step)
    if (mode == "agent_native" and exec_state.get("host_review_pending")
            and step.get("terminal")):
        step = {
            "node": "REVIEW", "persona": "Reviewer",
            "profile_id": profile_id, "schema_version": "2.1",
        }
        action_identity["nodes"] = ["REVIEW"]
        kind = "review"
    needs_pre_research = (
        kind != "terminal" and not nodes and step.get("node") in rl.PRE_RESEARCH_MAP
    )
    if (needs_pre_research and
            exec_state.get("prepared_action_identity") != action_identity):
        kind = "pre_research"

    return {
        "kind": kind,
        "step": step,
        "profile_id": profile_id,
        "cursor": cursor,
        "identity": action_identity,
    }


def _host_step_json_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _host_step_marker_path(project, cand, round_id, request_id):
    return (
        Path(project) / "08_Run_Receipts" / str(cand)
        / f"round_{int(round_id):02d}" / f"host_commit_{request_id}.json"
    )


def _read_host_step_marker(path):
    try:
        marker = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"host step commit marker is invalid: {exc}") from exc
    if not isinstance(marker, dict):
        raise RuntimeError("host step commit marker must contain an object")
    return marker


def _write_host_step_marker(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_host_step_json_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _validate_host_step_request(project, cand, round_id, action, request):
    """Bind a persisted ordinary-node request to current RLR context owners."""
    identity = request.get("identity") or {}
    inputs = request.get("inputs") or {}
    step = action["step"]
    manifest_arg = inputs.get("context_manifest_path")
    rendered_arg = inputs.get("rendered_context_path")
    if not manifest_arg or not rendered_arg:
        raise RuntimeError("host request lacks context manifest or rendered context")
    manifest_path = Path(str(manifest_arg)).resolve(strict=True)
    rendered_path = Path(str(rendered_arg)).resolve(strict=True)
    try:
        manifest_path.relative_to(Path(project).resolve(strict=True))
        rendered_path.relative_to(Path(project).resolve(strict=True))
    except ValueError as exc:
        raise RuntimeError("host request context artifact path escapes the project") from exc
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"host request context manifest is invalid: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "ContextManifest/v2":
        raise RuntimeError("host request requires ContextManifest/v2")
    rendered_hash = hashlib.sha256(rendered_path.read_bytes()).hexdigest()
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    expected = {
        "project_id": manifest.get("project_id"),
        "candidate_id": str(cand),
        "round_id": str(round_id),
        "node": step.get("node"),
        "persona": step.get("persona"),
        "profile_id": action.get("profile_id"),
    }
    for field, value in expected.items():
        if identity.get(field) != value or manifest.get(field) != value:
            raise RuntimeError(f"host request {field} does not match current RLR action")
    if manifest.get("rendered_context_path") != str(rendered_path):
        raise RuntimeError("host request rendered-context path differs from manifest")
    if manifest.get("rendered_context_sha256") != rendered_hash:
        raise RuntimeError("host request rendered-context hash differs from manifest bytes")
    if manifest_hash != inputs.get("context_manifest_sha256"):
        raise RuntimeError("host request context-manifest hash differs from manifest bytes")
    if rendered_hash != inputs.get("rendered_context_sha256"):
        raise RuntimeError("host request rendered-context hash differs from request")
    if inputs.get("context_hash") != rendered_hash:
        raise RuntimeError("host request context hash differs from rendered context")
    config_path = Path(str(inputs.get("runner_config_path") or "")).resolve(strict=True)
    if hashlib.sha256(config_path.read_bytes()).hexdigest() != inputs.get(
        "runner_config_sha256"
    ):
        raise RuntimeError("host request runner config changed since preparation")
    if identity.get("cursor") != action.get("cursor"):
        raise RuntimeError("host request cursor is stale against current next-step")
    if not isinstance(identity.get("cursor"), dict):
        raise RuntimeError("agent-native host request requires an authoritative ledger cursor")
    persona_hashes = {
        "persona_catalog_sha256": "catalog_sha256",
        "persona_catalog_entry_sha256": "entry_sha256",
        "persona_template_sha256": "template_sha256",
        "persona_body_sha256": "body_sha256",
    }
    try:
        resolved = resolve_persona_template(
            get_profile(str(action.get("profile_id"))), str(step.get("persona"))
        )
    except (KeyError, ValueError, PersonaCatalogError) as exc:
        raise RuntimeError(f"host request persona binding is invalid: {exc}") from exc
    for manifest_field, resolution_field in persona_hashes.items():
        expected_hash = getattr(resolved, resolution_field)
        if (
            manifest.get(manifest_field) != expected_hash
            or inputs.get(manifest_field) != expected_hash
        ):
            raise RuntimeError(
                f"host request {manifest_field} differs from current persona template"
            )
    tools_policy = request.get("tools_policy")
    if (
        not tools_policy
        or tools_policy != manifest.get("tools_policy")
        or (step.get("tools_policy") and step.get("tools_policy") != tools_policy)
    ):
        raise RuntimeError("host request tool policy differs from current context")
    for field, value in {
        "context_manifest_path": str(manifest_path),
        "context_manifest_sha256": manifest_hash,
        "rendered_context_path": str(rendered_path),
        "rendered_context_sha256": rendered_hash,
    }.items():
        if inputs.get(field) != value:
            raise RuntimeError(f"host request {field} does not match context artifacts")
    return manifest, manifest_path, rendered_path, rendered_hash


def _prepare_host_literature(project, cand, cfg, args, round_id, exec_state, action):
    """Prepare a host literature response from the existing pre-research prompt."""
    step = action["step"]
    node = str(step.get("node") or "")
    if node not in {"L4", "L8.5"}:
        return None
    audit = _ctl("audit-literature-evidence", project, cand, "--node", node)
    target = (Path(project) / "02_Agent_Notes" / "_pre_research"
              / f"{node}_research.md")
    if audit.returncode == 0 and target.is_file():
        try:
            run_id = str(json.loads(audit.stdout).get("run_id") or "")
        except (TypeError, json.JSONDecodeError):
            run_id = ""
        if run_id:
            args.evidence_run_ids = getattr(args, "evidence_run_ids", {})
            args.evidence_run_ids[node] = run_id
            exec_state["prepared_action_identity"] = action["identity"]
            return {"kind": "deterministic", "action": action, "evidence_run_id": run_id}

    prompt_result = _ctl("pre-research", project, cand, "--node", node)
    if prompt_result.returncode != 0 or not str(prompt_result.stdout or "").strip():
        return {
            "kind": "blocked", "step": step,
            "reason": "existing pre-research prompt owner did not provide a host task",
        }
    prompt = str(prompt_result.stdout)
    prompt_bytes = prompt.encode("utf-8")
    store = getattr(args, "knowledge_store", None)
    ledger = rl._ledger_for(project, store, readonly=True)
    binding = ledger.require_binding(project)
    if not isinstance(action.get("cursor"), dict):
        return {"kind": "blocked", "step": step,
                "reason": "host literature request requires authoritative v2.1 cursor"}
    profile_id = str(action["profile_id"])
    attempt = int(exec_state.get("host_attempts", {}).get(f"{node}:literature", 1))
    request = ENGINE.prepare_host_request(
        project,
        kind="literature",
        identity={
            "project_id": str(binding["project_id"]),
            "candidate_id": str(cand), "round_id": str(round_id),
            "node": node, "persona": "Curie", "profile_id": profile_id,
            "stage": "literature_review", "attempt": attempt,
            "cursor": action["cursor"],
        },
        inputs={
            "literature_prompt": prompt,
            "literature_prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "authorized_by": "RLR pre-research prompt owner",
        },
        tools_policy="literature-only",
        output_contract={
            "type": "object", "schema_version": deep_research.SCHEMA_VERSION,
            "schema": deep_research._runtime_schema(node),
        },
    )
    return {"kind": "needs_host", "step": step, "request": request,
            "request_id": request["request_id"], "request_path": request["request_path"]}


def _prepare_host_pre_research_text(project, cand, args, round_id, exec_state, action):
    """Prepare a host response for existing non-literature pre-research text."""
    step = action["step"]
    node = str(step.get("node") or "")
    if node not in rl.PRE_RESEARCH_MAP or node in {"L1", "L4", "L8.5"}:
        return None
    target = (Path(project) / "02_Agent_Notes" / "_pre_research"
              / f"{node}_research.md")
    if target.is_file():
        request = _pending_pre_research_text_request(
            project, cand, args, round_id, exec_state, action
        )
        if request is not None:
            marker_path = _host_step_marker_path(
                project, cand, round_id, request["request_id"]
            )
            marker = _read_host_step_marker(marker_path)
            if marker and marker.get("phase") == "committed":
                loader = getattr(ENGINE, "load_host_response_receipt", None)
                if not callable(loader):
                    raise RuntimeError("committed text response receipt loader is unavailable")
                receipt = loader(
                    project, request["request_id"],
                    expected_cursor=(request.get("identity") or {}).get("cursor"),
                )
                if receipt is None:
                    raise RuntimeError("committed text response receipt is missing")
                _validate_committed_pre_research_text(
                    project, cand, request, marker, receipt
                )
        exec_state["prepared_action_identity"] = action["identity"]
        return {"kind": "deterministic", "action": action, "target": str(target)}
    prompt_result = _ctl("pre-research", project, cand, "--node", node)
    if prompt_result.returncode != 0 or not str(prompt_result.stdout or "").strip():
        return {"kind": "blocked", "step": step,
                "reason": "existing pre-research prompt owner did not provide a host task"}
    prompt = str(prompt_result.stdout)
    store = getattr(args, "knowledge_store", None)
    binding = rl._ledger_for(project, store, readonly=True).require_binding(project)
    if not isinstance(action.get("cursor"), dict):
        return {"kind": "blocked", "step": step,
                "reason": "host text request requires authoritative v2.1 cursor"}
    profile_id = str(action["profile_id"])
    request = ENGINE.prepare_host_request(
        project,
        kind="pre_research_text",
        identity={
            "project_id": str(binding["project_id"]),
            "candidate_id": str(cand), "round_id": str(round_id),
            "node": node, "persona": str(step.get("persona") or "Researcher"),
            "profile_id": profile_id, "stage": "pre_research_text",
            "attempt": int(exec_state.get("host_attempts", {}).get(
                f"{node}:pre_research_text", 1)),
            "cursor": action["cursor"],
        },
        inputs={
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "target_path": str(target.resolve()),
        },
        tools_policy="no-fs",
        output_contract={"type": "object", "required": ["text"],
                         "properties": {"text": {"type": "string"}}},
    )
    return {"kind": "needs_host", "step": step, "request": request,
            "request_id": request["request_id"], "request_path": request["request_path"]}


def _validate_committed_pre_research_text(project, cand, request, marker, receipt):
    """Verify the existing committed text marker still names the exact target bytes."""
    identity = request.get("identity") or {}
    inputs = request.get("inputs") or {}
    node = str(identity.get("node") or "")
    root = Path(project).resolve(strict=True)
    expected = (root / "02_Agent_Notes" / "_pre_research"
                / f"{node}_research.md").resolve(strict=False)
    target = Path(str(inputs.get("target_path") or "")).resolve(strict=False)
    marker_target = Path(str(marker.get("target") or "")).resolve(strict=False)
    if (request.get("kind") != "pre_research_text"
            or str(identity.get("candidate_id")) != str(cand)
            or node not in rl.PRE_RESEARCH_MAP
            or target != expected or marker_target != expected
            or str(marker.get("request_id") or "") != str(request.get("request_id") or "")
            or marker.get("phase") != "committed"):
        raise RuntimeError("committed pre-research text target binding is invalid")
    target_bytes = expected.read_bytes()
    target_hash = hashlib.sha256(target_bytes).hexdigest()
    if (not marker.get("text_sha256")
            or target_hash != marker.get("text_sha256")
            or marker.get("raw_response_sha256")
            != receipt.get("raw_response_sha256")):
        raise RuntimeError("committed pre-research text target bytes differ from receipt")
    return expected


def _review_context_snapshot(project, cand, profile_id):
    report_path = Path(project) / "FINAL_REPORT.md"
    if not report_path.is_file():
        raise RuntimeError("REVIEW requires FINAL_REPORT.md")
    profile = get_profile(str(profile_id))
    l8_key = artifact_for_node(profile, "L8").storage_key
    parts = ["=== FINAL_REPORT.md ===", report_path.read_text(encoding="utf-8")]
    source_hashes = {
        str(report_path.resolve()): hashlib.sha256(report_path.read_bytes()).hexdigest()
    }
    cn_path = Path(project) / "FINAL_REPORT_CN.md"
    if cn_path.is_file():
        parts += ["=== FINAL_REPORT_CN.md ===", cn_path.read_text(encoding="utf-8")]
        source_hashes[str(cn_path.resolve())] = hashlib.sha256(cn_path.read_bytes()).hexdigest()
    for delta_key in (l8_key, "L9a_feynman", "L9b_darwin", "L10b_oppenheimer"):
        delta = load_delta(project, cand, delta_key)
        if delta is not None:
            parts += [f"=== {delta_key} ===", json.dumps(
                delta, indent=2, ensure_ascii=False
            )]
    context = "\n\n".join(parts)
    return context, hashlib.sha256(context.encode("utf-8")).hexdigest(), source_hashes


def _validate_review_response(value):
    """Validate reviewer output against the existing REVIEW_SCHEMA contract."""
    if not isinstance(value, dict) or set(value) != set(REVIEW_SCHEMA):
        raise ValueError("REVIEW response does not match required schema fields")
    if value.get("review_verdict") not in {
        "accept", "weak_accept", "major_revision", "reject"
    }:
        raise ValueError("REVIEW response has an invalid review_verdict")
    for field, expected in REVIEW_SCHEMA.items():
        if field == "review_verdict":
            continue
        actual = value.get(field)
        if expected is int:
            if not isinstance(actual, int) or isinstance(actual, bool):
                raise ValueError(f"REVIEW response field {field} must be an integer")
        elif not isinstance(actual, expected):
            raise ValueError(f"REVIEW response field {field} has the wrong schema type")
    if not value["reason"].strip():
        raise ValueError("REVIEW response reason must not be empty")
    return value


def _submit_host_literature(project, cand, request, action, response_receipt,
                            session_identity):
    """Persist host literature through the existing Deep Research owner."""
    identity = request.get("identity") or {}
    inputs = request.get("inputs") or {}
    node = str(identity.get("node") or "")
    if (node not in {"L4", "L8.5"} or action.get("kind") != "pre_research"
            or str(action["step"].get("node")) != node):
        raise RuntimeError("host literature response no longer names L4/L8.5 pre-research")
    if (identity.get("cursor") != action.get("cursor")
            or str(identity.get("candidate_id")) != str(cand)
            or str(identity.get("profile_id")) != str(action.get("profile_id"))
            or identity.get("stage") != "literature_review"):
        raise RuntimeError("host literature request identity or cursor is stale")
    prompt_bytes = str(inputs.get("literature_prompt") or "").encode("utf-8")
    if (not prompt_bytes or hashlib.sha256(prompt_bytes).hexdigest()
            != inputs.get("literature_prompt_sha256")):
        raise RuntimeError("host literature prompt differs from its immutable request")
    request_path = Path(request["request_path"]).resolve(strict=True)
    response_path = Path(response_receipt["raw_response_path"]).resolve(strict=True)
    project_root = Path(project).resolve(strict=True)
    for path, label in ((request_path, "request"), (response_path, "response")):
        try:
            path.relative_to(project_root)
        except ValueError as exc:
            raise RuntimeError(f"host literature {label} path escapes project") from exc
    request_hash = hashlib.sha256(request_path.read_bytes()).hexdigest()
    response_hash = hashlib.sha256(response_path.read_bytes()).hexdigest()
    if (request_hash != request.get("request_sha256")
            or response_hash != response_receipt.get("raw_response_sha256")):
        raise RuntimeError("host literature request/response bytes changed")
    try:
        payload = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"host literature response is not valid JSON: {exc}") from exc
    host_receipt = {
        "schema_version": deep_research.HOST_RECEIPT_SCHEMA,
        "source": "host_session", "request_id": request["request_id"],
        "host_request_path": str(request_path),
        "host_request_sha256": request_hash,
        "raw_response_path": str(response_path),
        "raw_response_sha256": response_hash,
        "host_session_id": session_identity.get("session_id"),
        "host_session_id_source": session_identity.get("source", "unavailable"),
    }
    artifact = deep_research.persist_run(
        project, cand, node, payload, host_receipt,
        project_id=str(identity["project_id"]),
        round_id=str(identity["round_id"]),
        profile_id=str(identity["profile_id"]), research_persona="Curie",
    )
    valid, reason = deep_research.audit_evidence_pack(
        project, cand, node, run_id=artifact["run_id"]
    )
    if not valid:
        raise RuntimeError(f"host literature evidence pack failed existing audit: {reason}")
    target = (Path(project) / "02_Agent_Notes" / "_pre_research"
              / f"{node}_research.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(deep_research.render_pre_research_markdown(artifact),
                      encoding="utf-8")
    audited = _ctl("audit-literature-evidence", project, cand, "--node", node)
    if audited.returncode != 0:
        raise RuntimeError("RLR literature audit rejected the host evidence pack")
    try:
        audited_run_id = str(json.loads(audited.stdout).get("run_id") or "")
    except (TypeError, json.JSONDecodeError):
        audited_run_id = ""
    if audited_run_id != artifact["run_id"]:
        raise RuntimeError("RLR literature audit selected a different evidence run")
    return artifact


def _validate_l7_workspace_request(project, cand, request):
    """Revalidate the exact execution workspace manifest before L7 emission."""
    inputs = request.get("inputs") or {}
    root = Path(project).resolve(strict=True)
    workspace = Path(str(inputs.get("workspace_path") or "")).resolve(strict=True)
    manifest_path = Path(
        str(inputs.get("workspace_manifest_path") or "")
    ).resolve(strict=True)
    try:
        workspace.relative_to(root)
        manifest_path.relative_to(workspace)
    except ValueError as exc:
        raise RuntimeError("L7 host workspace manifest escapes its controlled workspace") from exc
    raw = manifest_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != inputs.get("workspace_manifest_sha256"):
        raise RuntimeError("L7 host workspace manifest changed after request preparation")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"L7 host workspace manifest is invalid: {exc}") from exc
    if manifest != inputs.get("workspace_manifest"):
        raise RuntimeError("L7 host workspace manifest differs from immutable request")
    if (manifest.get("candidate_id") != str(cand)
            or manifest.get("node") != "L7" or manifest.get("missing")):
        raise RuntimeError("L7 host workspace manifest is incomplete or misbound")
    for item in manifest.get("staged_files") or []:
        staged_path = Path(str(item.get("workspace_path") or item.get("path") or ""))
        if not staged_path.is_absolute():
            staged_path = workspace / staged_path
        staged_path = staged_path.resolve(strict=True)
        try:
            staged_path.relative_to(workspace)
        except ValueError as exc:
            raise RuntimeError("L7 host staged file escapes its workspace") from exc
        if hashlib.sha256(staged_path.read_bytes()).hexdigest() != item.get("sha256"):
            raise RuntimeError("L7 host staged script/output changed after authorization")
    return workspace, manifest_path, digest


def _submit_host_pre_research_text(project, cand, request, action,
                                   response_receipt):
    identity = request.get("identity") or {}
    inputs = request.get("inputs") or {}
    node = str(identity.get("node") or "")
    if (action.get("kind") != "pre_research"
            or str(action["step"].get("node")) != node
            or node not in rl.PRE_RESEARCH_MAP
            or node in {"L1", "L4", "L8.5"}):
        raise RuntimeError("host text response no longer names a text pre-research step")
    if (identity.get("cursor") != action.get("cursor")
            or str(identity.get("candidate_id")) != str(cand)
            or str(identity.get("profile_id")) != str(action.get("profile_id"))
            or identity.get("stage") != "pre_research_text"):
        raise RuntimeError("host text request identity or cursor is stale")
    prompt = str(inputs.get("prompt") or "")
    if (not prompt or hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            != inputs.get("prompt_sha256")):
        raise RuntimeError("host text prompt differs from immutable request")
    try:
        payload = json.loads(Path(response_receipt["raw_response_path"])
                             .read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"host pre-research response is invalid JSON: {exc}") from exc
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("host pre-research response requires non-empty text")
    root = Path(project).resolve(strict=True)
    target = Path(str(inputs.get("target_path") or "")).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("host pre-research output path escapes project") from exc
    if target != (root / "02_Agent_Notes" / "_pre_research"
                  / f"{node}_research.md").resolve(strict=False):
        raise RuntimeError("host pre-research output target differs from node owner")
    target.parent.mkdir(parents=True, exist_ok=True)
    text_bytes = text.encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
    return {"target": str(target), "text_sha256": hashlib.sha256(
        text_bytes).hexdigest()}


def prepare_host_step(project, cand, cfg, args, round_id, exec_state) -> dict:
    """Prepare exactly one current ordinary cognitive step for the host session."""
    args.mode = "agent_native"
    action = current_action(project, cand, cfg, args, round_id, exec_state)
    step = action["step"]
    if action["kind"] == "terminal":
        return {"kind": "terminal", "step": step}
    host_l7_workspace = None
    if action["kind"] == "l05":
        return {
            "kind": "blocked",
            "step": step,
            "reason": f"{step.get('node')} host handoff is not implemented in this phase",
        }
    if action["kind"] == "review":
        profile_id = str(action["profile_id"])
        try:
            review_context, review_context_hash, source_hashes = (
                _review_context_snapshot(project, cand, profile_id)
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return {"kind": "blocked", "step": step, "reason": str(exc)}
        binding = rl._ledger_for(
            project, getattr(args, "knowledge_store", None), readonly=True
        ).require_binding(project)
        if not isinstance(action.get("cursor"), dict):
            return {"kind": "blocked", "step": step,
                    "reason": "REVIEW host request requires authoritative v2.1 cursor"}
        review_properties = {}
        for field, value_type in REVIEW_SCHEMA.items():
            if field == "review_verdict":
                review_properties[field] = {
                    "type": "string",
                    "enum": ["accept", "weak_accept", "major_revision", "reject"],
                }
            else:
                review_properties[field] = {
                    "type": "integer" if value_type is int else "array"
                    if value_type is list else "string"
                }
        request = ENGINE.prepare_host_request(
            project,
            kind="review",
            identity={
                "project_id": str(binding["project_id"]),
                "candidate_id": str(cand), "round_id": str(round_id),
                "node": "REVIEW", "persona": "Reviewer", "profile_id": profile_id,
                "stage": "review", "attempt": int(
                    exec_state.get("host_attempts", {}).get("REVIEW", 1)
                ), "cursor": action["cursor"],
            },
            inputs={
                "review_context": review_context,
                "review_context_sha256": review_context_hash,
                "source_hashes": source_hashes,
            },
            tools_policy="review-read-only",
            output_contract={
                "type": "object",
                "schema": {
                    "type": "object", "required": list(REVIEW_SCHEMA),
                    "properties": review_properties,
                },
            },
        )
        return {"kind": "needs_host", "step": step, "request": request,
                "request_id": request["request_id"],
                "request_path": request["request_path"]}
    if action["kind"] == "l7":
        if status_of(project, cand) == "METHOD_APPROVED":
            gate = _ctl("execution-gate", project, cand)
            if gate.returncode != 0:
                return {"kind": "blocked", "step": step,
                        "reason": f"execution-gate rejected: {gate.stdout.strip()}"}
        prepared = _ctl("prepare-turing-workspace", project, cand, "--clean")
        if prepared.returncode != 0:
            return {"kind": "blocked", "step": step,
                    "reason": "controlled Turing workspace preparation failed"}
        workspace = next((line.split("ready:", 1)[1].strip()
                          for line in prepared.stdout.splitlines()
                          if "Turing workspace ready:" in line), "")
        if not workspace:
            return {"kind": "blocked", "step": step,
                    "reason": "Turing workspace owner returned no workspace path"}
        workspace_path = Path(workspace).resolve(strict=True)
        try:
            workspace_path.relative_to(Path(project).resolve(strict=True))
        except ValueError:
            return {"kind": "blocked", "step": step,
                    "reason": "controlled Turing workspace escapes the project"}
        workspace_manifest_path = workspace_path / "WORKSPACE_MANIFEST.json"
        workspace_manifest_bytes = workspace_manifest_path.read_bytes()
        workspace_manifest = json.loads(workspace_manifest_bytes.decode("utf-8"))
        if (workspace_manifest.get("candidate_id") != str(cand)
                or workspace_manifest.get("node") != "L7"
                or workspace_manifest.get("missing")):
            return {"kind": "blocked", "step": step,
                    "reason": "Turing workspace manifest is invalid or incomplete"}
        exec_state.setdefault("host_l7_workspaces", {})[str(cand)] = {
            "path": str(workspace_path),
            "manifest_path": str(workspace_manifest_path.resolve()),
            "manifest_sha256": hashlib.sha256(workspace_manifest_bytes).hexdigest(),
        }
        host_l7_workspace = {
            "path": str(workspace_path),
            "manifest_path": str(workspace_manifest_path.resolve()),
            "manifest_sha256": hashlib.sha256(workspace_manifest_bytes).hexdigest(),
            "manifest": workspace_manifest,
        }
    if step.get("is_parallel") or step.get("nodes"):
        return {
            "kind": "blocked",
            "step": step,
            "reason": "parallel host handoff requires a node-specific authorization",
        }
    if action["kind"] == "report":
        result = execute_deterministic_action(
            action, project, cand, cfg, args,
            Path(project) / "08_Run_Receipts" / cand / f"round_{int(round_id):02d}",
            round_id, exec_state,
        )
        return {"kind": "deterministic", "action": action, "result": result}
    if action["kind"] == "pre_research":
        recovered = _recover_committed_advance(project, cand, step)
        if recovered:
            return {"kind": "deterministic", "action": action, "advanced": True}
        if (str(step.get("node") or "") == "L1"
                and action.get("profile_id") == PROFILE_V21_CATALOG_1):
            ok = ensure_pre_research(
                project, cand, "L1", cfg, args,
                Path(project) / "08_Run_Receipts" / cand
                / f"round_{int(round_id):02d}",
            )
            return {
                "kind": "deterministic" if ok else "blocked",
                "action": action,
                "result": {"kind": "pre_research", "ok": bool(ok)},
                **({} if ok else {
                    "step": step,
                    "reason": "native L1 binding/recall owner failed closed",
                }),
            }
        literature = _prepare_host_literature(
            project, cand, cfg, args, round_id, exec_state, action
        )
        if literature is not None:
            return literature
        try:
            text_handoff = _prepare_host_pre_research_text(
                project, cand, args, round_id, exec_state, action
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return {"kind": "blocked", "step": step, "reason": str(exc)}
        if text_handoff is not None:
            return text_handoff
        return {
            "kind": "blocked",
            "step": step,
            "reason": "agent-native pre-research handoff is not implemented in this phase",
        }

    recovered = _recover_committed_advance(project, cand, step)
    if recovered is True:
        return {"kind": "deterministic", "action": action, "advanced": True}
    if recovered is False:
        return {"kind": "blocked", "step": step, "reason": "committed delta advance failed"}

    node, persona = str(step["node"]), str(step["persona"])
    evidence_run_id = getattr(args, "evidence_run_ids", {}).get(node)
    context, manifest_path = assemble_context(
        project, cand, node,
        getattr(args, "authorization_ids", {}).get(node),
        evidence_run_id,
        _context_token_budget(cfg),
    )
    config_value = getattr(cfg, "source_path", None) or getattr(args, "config", None)
    if not config_value:
        return {
            "kind": "blocked",
            "step": step,
            "reason": "agent-native host receipt requires the exact runner config path",
        }
    config_path = Path(config_value).resolve(strict=True)
    config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest, rendered_path, rendered_bytes, _rendered_text = load_rendered_context_artifact(
        manifest_path
    )
    rendered_path = rendered_path.resolve(strict=True)
    rendered_hash = hashlib.sha256(rendered_bytes).hexdigest()
    if context.encode("utf-8") != rendered_bytes:
        raise RuntimeError("assembled host context differs from persisted context bytes")
    if manifest.get("node") != node or manifest.get("persona") != persona:
        raise RuntimeError("context manifest identity differs from current host step")
    tools_policy = step.get("tools_policy") or manifest.get("tools_policy")
    if not tools_policy or tools_policy != manifest.get("tools_policy"):
        raise RuntimeError("current host step has no matching context tool policy")
    if not isinstance(action.get("cursor"), dict):
        return {
            "kind": "blocked",
            "step": step,
            "reason": "agent-native host request requires an authoritative v2.1 ledger cursor",
        }
    identity = {
        "project_id": str(manifest["project_id"]),
        "candidate_id": str(cand),
        "round_id": str(round_id),
        "node": node,
        "persona": persona,
        "profile_id": str(action["profile_id"]),
        "stage": "cognitive",
        "attempt": int(exec_state.get("host_attempts", {}).get(node, 1)),
        "cursor": action["cursor"],
    }
    inputs = {
        "context_manifest_path": str(manifest_path.resolve()),
        "context_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "rendered_context_path": str(rendered_path.resolve()),
        "rendered_context_sha256": rendered_hash,
        "context_hash": rendered_hash,
        "allowed_inputs": list(manifest.get("allowed_inputs") or []),
        "persona_catalog_sha256": manifest.get("persona_catalog_sha256"),
        "persona_catalog_entry_sha256": manifest.get("persona_catalog_entry_sha256"),
        "persona_template_sha256": manifest.get("persona_template_sha256"),
        "persona_body_sha256": manifest.get("persona_body_sha256"),
        "runner_config_path": str(config_path),
        "runner_config_sha256": config_hash,
    }
    if host_l7_workspace is not None:
        inputs.update({
            "workspace_path": host_l7_workspace["path"],
            "workspace_manifest_path": host_l7_workspace["manifest_path"],
            "workspace_manifest_sha256": host_l7_workspace["manifest_sha256"],
            "workspace_manifest": host_l7_workspace["manifest"],
        })
    # L0's strict contract is re-read immediately before creating the durable
    # host request so changes during context preparation fail closed.
    if node == "L0":
        ok, reason = rl._audit_l0_contract(Path(project), cand)
        if not ok:
            return {"kind": "blocked", "step": step,
                    "reason": f"L0 input-contract gate before host request: {reason}"}
    request = ENGINE.prepare_host_request(
        project,
        kind="cognitive",
        identity=identity,
        inputs=inputs,
        tools_policy=tools_policy,
        output_contract={
            "type": "object",
            "schema_version": step.get("schema_version"),
            "schema": _provider_output_schema(project, node, step),
        },
    )
    return {
        "kind": "needs_host",
        "step": step,
        "request": request,
        "request_id": request["request_id"],
        "request_path": request["request_path"],
        "context_manifest_path": str(manifest_path),
        "rendered_context_path": str(rendered_path),
    }


def submit_host_step(project, cand, request_id, response_path, *,
                     session_identity=None):
    """Validate one host response, emit it, record v3-host provenance, and advance."""
    session_identity = dict(session_identity or {})
    session_source = session_identity.get("source", "unavailable")
    session_id = session_identity.get("session_id")
    if session_source not in {"verified", "declared", "unavailable"}:
        raise ValueError("host session identity source must be verified, declared, or unavailable")
    if session_source == "verified":
        raise ValueError(
            "verified host session identity requires a trusted verifier; "
            "this boundary accepts declared or unavailable"
        )
    if session_source in {"verified", "declared"} and not str(session_id or "").strip():
        raise ValueError("verified or declared host session identity requires session_id")
    if session_source == "unavailable" and session_id not in (None, ""):
        raise ValueError("unavailable host session identity cannot claim session_id")

    with ENGINE.host_step_commit_lock(project, request_id):
        request = ENGINE.load_host_request(project, request_id)
        if request.get("request_id") != request_id:
            raise RuntimeError("host request ID does not match requested submission")
        identity = request.get("identity") or {}
        expected_cursor = identity.get("cursor")
        if not isinstance(expected_cursor, dict):
            raise RuntimeError("host request has no authoritative ledger cursor")
        marker_path = _host_step_marker_path(
            project, cand, identity["round_id"], request_id
        )
        marker = _read_host_step_marker(marker_path)
        if marker is not None and marker.get("phase") == "committed":
            response_receipt = ENGINE.submit_host_response(
                project, request_id, response_path, expected_cursor=expected_cursor
            )
            if (
                marker.get("request_id") != request_id
                or marker.get("raw_response_sha256")
                != response_receipt.get("raw_response_sha256")
            ):
                raise RuntimeError(
                    "host request was already committed with different response bytes"
                )
            if request.get("kind") == "pre_research_text":
                _validate_committed_pre_research_text(
                    project, cand, request, marker, response_receipt
                )
            return {"kind": "committed", "duplicate": True, **marker}

        action = current_action(
            project, cand, SimpleNamespace(stop_policy={}),
            SimpleNamespace(mode="agent_native", knowledge_store=None),
            str(identity["round_id"]), {
                "cursor": expected_cursor,
                "host_review_pending": request.get("kind") == "review",
            },
        )
        if (request.get("kind") == "cognitive" and marker
                and marker.get("phase") == "delta_committed"):
            response_receipt = ENGINE.submit_host_response(
                project, request_id, response_path, expected_cursor=expected_cursor
            )
            response_hash = response_receipt.get("raw_response_sha256")
            if (marker.get("request_id") != request_id
                    or marker.get("raw_response_sha256") != response_hash):
                raise RuntimeError(
                    "host request was already committed with different response bytes"
                )
            response_bytes_path = Path(
                response_receipt.get("raw_response_path") or ""
            ).resolve(strict=True)
            canonical_delta_path = Path(
                marker.get("canonical_delta_path") or ""
            ).resolve(strict=True)
            raw_hash = hashlib.sha256(response_bytes_path.read_bytes()).hexdigest()
            if (response_bytes_path != canonical_delta_path
                    or raw_hash != response_hash
                    or raw_hash != marker.get("canonical_delta_sha256")):
                raise RuntimeError(
                    "persisted host response or canonical delta differs from commit marker"
                )
            host_receipt_path = Path(
                marker.get("host_receipt_path") or ""
            ).resolve(strict=True)
            host_receipt = orch.RunReceipt.read(host_receipt_path)
            if (host_receipt.schema_version != "RunReceipt/v3-host"
                    or Path(str(host_receipt.host_request_path)).resolve(strict=True)
                    != Path(str(request["request_path"])).resolve(strict=True)
                    or host_receipt.host_request_hash != request.get("request_sha256")
                    or Path(str(host_receipt.raw_response_path)).resolve(strict=True)
                    != response_bytes_path
                    or host_receipt.raw_response_hash != response_hash
                    or Path(str(host_receipt.canonical_delta_path)).resolve(strict=True)
                    != canonical_delta_path
                    or host_receipt.canonical_delta_hash != raw_hash):
                raise RuntimeError("persisted host RunReceipt differs from commit marker")

            current_step = action.get("step") or {}
            still_current = (
                str(current_step.get("node")) == str(identity.get("node"))
                and str(current_step.get("persona")) == str(identity.get("persona"))
            )
            if still_current:
                advance(project, cand, current_step)
            marker["phase"] = "committed"
            _write_host_step_marker(marker_path, marker)
            return {"kind": "committed", "duplicate": True, **marker}

        step = action["step"]
        if request.get("kind") == "review":
            if (action.get("kind") != "review"
                    or str(cand) != str(identity.get("candidate_id"))
                    or str(action.get("profile_id")) != str(identity.get("profile_id"))
                    or action.get("cursor") != expected_cursor
                    or str(step.get("node")) != "REVIEW"):
                raise RuntimeError("host REVIEW response is stale or names another stage")
            current_context, current_context_hash, current_sources = (
                _review_context_snapshot(project, cand, identity["profile_id"])
            )
            request_inputs = request.get("inputs") or {}
            if (request_inputs.get("review_context") != current_context
                    or request_inputs.get("review_context_sha256") != current_context_hash
                    or request_inputs.get("source_hashes") != current_sources):
                raise RuntimeError("host REVIEW request context or source hashes changed")
            response_receipt = ENGINE.submit_host_response(
                project, request_id, response_path, expected_cursor=expected_cursor
            )
            raw_response_path = Path(response_receipt["raw_response_path"]).resolve(strict=True)
            raw_bytes = raw_response_path.read_bytes()
            raw_hash = hashlib.sha256(raw_bytes).hexdigest()
            if raw_hash != response_receipt.get("raw_response_sha256"):
                raise RuntimeError("host REVIEW response receipt differs from exact bytes")
            try:
                review = json.loads(raw_bytes.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"host REVIEW response is invalid JSON: {exc}") from exc
            review = _validate_review_response(review)
            marker = {
                "schema_version": "HostStepCommit/v1", "phase": "committed",
                "request_id": request_id, "raw_response_sha256": raw_hash,
                "review": review,
                "host_receipt": {
                    "schema_version": "HostResponseReceipt/v1",
                    "request_id": request_id,
                    "request_path": request["request_path"],
                    "request_sha256": hashlib.sha256(
                        Path(request["request_path"]).read_bytes()
                    ).hexdigest(),
                    "raw_response_path": str(raw_response_path),
                    "raw_response_sha256": raw_hash,
                },
            }
            _write_host_step_marker(marker_path, marker)
            return {"kind": "committed", "duplicate": False, **marker,
                    "response_receipt": response_receipt}
        if request.get("kind") == "pre_research_text":
            response_receipt = ENGINE.submit_host_response(
                project, request_id, response_path, expected_cursor=expected_cursor
            )
            text_result = _submit_host_pre_research_text(
                project, cand, request, action, response_receipt
            )
            marker = {
                "schema_version": "HostStepCommit/v1",
                "phase": "committed", "request_id": request_id,
                "raw_response_sha256": response_receipt["raw_response_sha256"],
                **text_result,
            }
            _write_host_step_marker(marker_path, marker)
            return {"kind": "committed", "duplicate": False, **marker}
        if request.get("kind") == "literature":
            if action.get("kind") != "pre_research":
                raise RuntimeError("host literature response is stale outside pre-research")
            response_receipt = ENGINE.submit_host_response(
                project, request_id, response_path, expected_cursor=expected_cursor
            )
            artifact = _submit_host_literature(
                project, cand, request, action, response_receipt, session_identity
            )
            marker = {
                "schema_version": "HostStepCommit/v1",
                "phase": "committed",
                "request_id": request_id,
                "raw_response_sha256": response_receipt["raw_response_sha256"],
                "evidence_run_id": artifact["run_id"],
                "host_receipt_schema": deep_research.HOST_RECEIPT_SCHEMA,
            }
            _write_host_step_marker(marker_path, marker)
            return {"kind": "committed", "duplicate": False, **marker}
        if action["kind"] == "terminal":
            if marker and marker.get("phase") == "delta_committed":
                response_receipt = ENGINE.submit_host_response(
                    project, request_id, response_path,
                    expected_cursor=expected_cursor,
                )
                if (
                    marker.get("request_id") != request_id
                    or marker.get("raw_response_sha256")
                    != response_receipt.get("raw_response_sha256")
                ):
                    raise RuntimeError(
                        "host request was already committed with different response bytes"
                    )
                marker["phase"] = "committed"
                _write_host_step_marker(marker_path, marker)
                return {"kind": "committed", "duplicate": True, **marker}
            raise RuntimeError("host response is stale because RLR is already terminal")
        if action.get("kind") != "cognitive" or step.get("is_parallel"):
            raise RuntimeError("host request no longer names an ordinary cognitive step")
        if (
            str(cand) != str(identity.get("candidate_id"))
            or str(action.get("profile_id")) != str(identity.get("profile_id"))
            or str(step.get("node")) != str(identity.get("node"))
            or str(step.get("persona")) != str(identity.get("persona"))
            or action.get("cursor") != expected_cursor
        ):
            raise RuntimeError("host response request node, persona, profile, or cursor is stale")
        manifest, manifest_path, rendered_path, rendered_hash = _validate_host_step_request(
            project, cand, identity["round_id"], action, request
        )
        workspace = None
        workspace_manifest_hash = None
        if str(identity.get("node")) == "L7":
            workspace, _workspace_manifest_path, workspace_manifest_hash = (
                _validate_l7_workspace_request(project, cand, request)
            )

        response_receipt = ENGINE.submit_host_response(
            project, request_id, response_path, expected_cursor=expected_cursor
        )
        response_hash = response_receipt["raw_response_sha256"]
        raw_response_path = Path(response_receipt["raw_response_path"]).resolve(strict=True)
        raw_response_hash = hashlib.sha256(raw_response_path.read_bytes()).hexdigest()
        if response_hash != raw_response_hash:
            raise RuntimeError("host response receipt does not match exact response bytes")
        if marker is not None and (
            marker.get("request_id") != request_id
            or marker.get("raw_response_sha256") != response_hash
        ):
            raise RuntimeError("host request was already committed with different response bytes")
        if marker and marker.get("phase") == "delta_committed":
            if action["kind"] == "terminal":
                marker["phase"] = "committed"
                _write_host_step_marker(marker_path, marker)
                return {"kind": "committed", "duplicate": True, **marker}
            advance(project, cand, step)
            marker["phase"] = "committed"
            _write_host_step_marker(marker_path, marker)
            return {"kind": "committed", "duplicate": True, **marker}

        request_path = Path(request["request_path"]).resolve(strict=True)
        request_hash = hashlib.sha256(request_path.read_bytes()).hexdigest()
        run_dir = (
            Path(project) / "08_Run_Receipts" / str(cand)
            / f"round_{int(identity['round_id']):02d}"
        )
        inputs = request.get("inputs") or {}
        config_path = inputs.get("runner_config_path")
        if not config_path:
            raise RuntimeError("host request lacks its exact runner config path")
        code_state = capture_code_state(HERE, config_path)
        receipt = orch.RunReceipt(
            node=str(identity["node"]),
            persona=str(identity["persona"]),
            provider="host_session",
            timestamp=orch.now(),
            context_hash=rendered_hash,
            prompt_file=None,
            prompt_hash=None,
            provider_delta_path=str(raw_response_path),
            provider_delta_hash=raw_response_hash,
            allowed_tools=[request["tools_policy"]],
            everos_scope=step.get("everos_read_scopes"),
            fresh_session=None,
            project_id=str(identity["project_id"]),
            candidate_id=str(cand),
            round_id=str(identity["round_id"]),
            profile_id=str(identity["profile_id"]),
            context_manifest_path=str(manifest_path),
            context_manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            rendered_context_path=str(rendered_path),
            rendered_context_hash=rendered_hash,
            git_head=code_state["git_head"],
            git_dirty=code_state["git_dirty"],
            working_tree_diff_sha256=code_state["working_tree_diff_sha256"],
            config_sha256=code_state["config_sha256"],
            code_state_id=code_state["code_state_id"],
            host_request_path=str(request_path),
            host_request_hash=request_hash,
            raw_response_path=str(raw_response_path),
            raw_response_hash=raw_response_hash,
            canonical_delta_path=str(raw_response_path),
            canonical_delta_hash=raw_response_hash,
            host_session_id=session_id,
            host_session_id_source=session_source,
            schema_version="RunReceipt/v3-host",
            workspace=str(workspace) if workspace is not None else None,
            exit_code=None,
            timed_out=None,
            terminal_state=None,
            execution_status=None,
        )
        attempt = int(identity.get("attempt", 1))
        receipt_path = provider_attempt_path(
            run_dir, step["node"], step["persona"], "receipt", ".json", attempt
        )
        receipt.write(receipt_path)
        if not emit_delta(
            project, cand, step["node"], step["persona"], raw_response_path,
            run_dir, receipt=manifest_path, provider_receipt=receipt_path,
        ):
            raise RuntimeError(f"emit-delta rejected host response for {step['node']}")
        marker = {
            "schema_version": "HostStepCommit/v1",
            "phase": "delta_committed",
            "request_id": request_id,
            "raw_response_sha256": raw_response_hash,
            "host_receipt_path": str(receipt_path),
            "canonical_delta_path": str(raw_response_path),
            "canonical_delta_sha256": raw_response_hash,
        }
        if workspace is not None:
            marker["workspace_manifest_sha256"] = workspace_manifest_hash
        _write_host_step_marker(marker_path, marker)
        advance(project, cand, step)
        marker["phase"] = "committed"
        _write_host_step_marker(marker_path, marker)
        return {"kind": "committed", "duplicate": False, **marker}


def _host_protocol_action(prepared):
    """Translate one existing owner result into the host CLI protocol shape."""
    kind = prepared.get("kind")
    if kind == "needs_host":
        request = prepared.get("request") or {}
        request_id = prepared.get("request_id") or request.get("request_id")
        request_path = prepared.get("request_path") or request.get("request_path")
        if not request_id or not request_path:
            return {"status": "blocked", "reason": "host owner returned an incomplete request"}
        try:
            request_bytes = Path(request_path).read_bytes()
        except OSError as exc:
            return {"status": "blocked", "reason": f"host request bytes are unavailable: {exc}"}
        request_hash = hashlib.sha256(request_bytes).hexdigest()
        expected_hash = request.get("request_sha256")
        if not expected_hash or expected_hash != request_hash:
            return {"status": "blocked", "reason": "host request bytes do not match its persisted hash"}
        return {
            "status": "needs_host",
            "request_id": str(request_id),
            "request_path": str(request_path),
            "request_sha256": request_hash,
        }
    if kind == "terminal":
        return {"status": "terminal", "step": prepared.get("step")}
    terminal_status = prepared.get("terminal_status") or prepared.get("status")
    if terminal_status == "L0_5_INSUFFICIENT_STOP":
        return {"status": "terminal", "result": prepared}
    if terminal_status in {"FROZEN", "NO_ADMISSIBLE_REPLAN"}:
        return {"status": "continued", "result": prepared}
    if terminal_status == "INSUFFICIENT_STOP":
        return {"status": "terminal", "result": prepared}
    if kind == "blocked":
        return {"status": "blocked", "reason": str(prepared.get("reason") or "host step is blocked")}
    if kind in {"deterministic", "continued"}:
        return {"status": "continued", "result": prepared.get("result")}
    return {"status": "blocked", "reason": f"unsupported host owner result: {kind!r}"}


def _resume_recorded_host_response(project, cand, prepared):
    """Commit a verified response receipt through the original stage owner."""
    if prepared.get("kind") != "needs_host":
        return None
    request = prepared.get("request") or {}
    if request.get("kind") not in {
        "cognitive", "review", "pre_research_text", "literature"
    }:
        return None
    request_id = prepared.get("request_id") or request.get("request_id")
    identity = request.get("identity") or {}
    cursor = identity.get("cursor")
    loader = getattr(ENGINE, "load_host_response_receipt", None)
    if not request_id or not isinstance(cursor, dict) or not callable(loader):
        return {"status": "blocked", "reason": "persisted host response loader is unavailable"}
    try:
        receipt = loader(project, request_id, expected_cursor=cursor)
        if receipt is None:
            return None
        response_path = receipt.get("raw_response_path")
        if not response_path:
            raise ValueError("persisted response receipt has no raw response path")
        outcome = host_protocol_submit(project, cand, request_id, response_path)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return {"status": "blocked", "reason": f"persisted host response is invalid: {exc}"}
    if outcome.get("status") != "committed":
        return {"status": "blocked", "reason": "persisted host response did not commit"}
    return {"status": "committed", "receipt": receipt, "outcome": outcome}


def _continue_after_host_response(project, cand, cfg, args, round_id,
                                  exec_state, action):
    if action.get("kind") == "pre_research":
        exec_state["prepared_action_identity"] = action.get("identity")
    next_action = current_action(project, cand, cfg, args, round_id, exec_state)
    if (next_action.get("kind") == action.get("kind")
            and next_action.get("identity") == action.get("identity")):
        return {"status": "blocked",
                "reason": "host response committed but shared next-step did not advance"}
    return host_protocol_next(project, cand, cfg, args, round_id, exec_state)


def _pending_pre_research_text_request(project, cand, args, round_id,
                                      exec_state, action):
    step = action.get("step") or {}
    node = str(step.get("node") or "")
    if node not in rl.PRE_RESEARCH_MAP or node in {"L1", "L4", "L8.5"}:
        return None
    if not isinstance(action.get("cursor"), dict):
        raise RuntimeError("host text recovery requires an authoritative ledger cursor")
    binding = rl._ledger_for(
        project, getattr(args, "knowledge_store", None), readonly=True
    ).require_binding(project)
    identity = {
        "project_id": str(binding["project_id"]),
        "candidate_id": str(cand), "round_id": str(round_id),
        "node": node, "persona": str(step.get("persona") or "Researcher"),
        "profile_id": str(action["profile_id"]),
        "stage": "pre_research_text",
        "attempt": int(exec_state.get("host_attempts", {}).get(
            f"{node}:pre_research_text", 1)),
        "cursor": action["cursor"],
    }
    return ENGINE.load_host_request_for_identity(project, identity)


def host_protocol_next(project, cand, cfg, args, round_id, exec_state):
    """Return one action from the existing RLR/owner state machines."""
    args.mode = "agent_native"
    run_dir = Path(project) / "08_Run_Receipts" / str(cand) / f"round_{int(round_id):02d}"
    stop_path = run_dir / "stop_decision.json"

    def round_result(decision):
        if decision.get("stop"):
            return {"status": "terminal", "stop_decision": decision}
        child = decision.get("next_candidate_id")
        if not child:
            return {"status": "blocked",
                    "reason": "round continuation has no persisted child candidate"}
        return {"status": "continued", "next_candidate_id": child,
                "stop_decision": decision}

    if stop_path.is_file():
        try:
            persisted = json.loads(stop_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {"status": "blocked", "reason": f"persisted stop decision is invalid: {exc}"}
        if isinstance(persisted, dict) and (
            persisted.get("stop") is True or persisted.get("next_candidate_id")
        ):
            return round_result(persisted)
        if (isinstance(persisted, dict)
                and persisted.get("terminal_status") == "L0_5_INSUFFICIENT_STOP"):
            try:
                relative = Path(str(persisted.get("acquisition_manifest_path") or ""))
                if relative.is_absolute():
                    raise ValueError("acquisition manifest path must be project-relative")
                project_path = Path(project).resolve()
                manifest_path = (project_path / relative).resolve(strict=True)
                manifest_path.relative_to(project_path)
                manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
                if not isinstance(manifest, dict):
                    raise ValueError("acquisition manifest must be an object")
                manifest_digest = str(persisted.get("acquisition_manifest_sha256") or "")
                result = europepmc_runtime._result_from_manifest(
                    manifest, relative.as_posix(), manifest_digest
                )
                validated = validate_europepmc_acquisition_result(
                    project_path, str(cand), result
                )
                if (validated.get("status") != "INSUFFICIENT_STOP"
                        or validated.get("run_id") != persisted.get("acquisition_run_id")
                        or validated.get("terminal_reason") != persisted.get("terminal_reason")
                        or validated.get("acquisition_manifest_path") != relative.as_posix()
                        or validated.get("acquisition_manifest_sha256") != manifest_digest):
                    raise ValueError("persisted L0.5 stop differs from validated acquisition manifest")
                expected_record = _l05_insufficient_stop_record({
                    "terminal_status": "L0_5_INSUFFICIENT_STOP",
                    "completed": False,
                    "full_dag_completed": False,
                    "terminal_reason": validated["terminal_reason"],
                    "acquisition_run_id": validated["run_id"],
                    "acquisition_manifest_path": validated["acquisition_manifest_path"],
                    "acquisition_manifest_sha256": validated[
                        "acquisition_manifest_sha256"
                    ],
                })
                if persisted != expected_record:
                    raise ValueError("persisted L0.5 stop record fields are not canonical")
            except (OSError, UnicodeError, ValueError, KeyError, TypeError,
                    RuntimeError, CurieAcquisitionError) as exc:
                return {"status": "blocked",
                        "reason": f"persisted L0.5 acquisition manifest is invalid: {exc}"}
            return {"status": "terminal", "result": persisted}

    action = current_action(project, cand, cfg, args, round_id, exec_state)
    terminal_round = action.get("kind") == "terminal"
    review_enabled = (
        not getattr(args, "no_review", False)
        and bool((getattr(cfg, "review", {}) or {}).get("enabled", True))
    )
    has_report = (Path(project) / "FINAL_REPORT.md").is_file()
    if terminal_round and review_enabled and has_report:
        exec_state["host_review_pending"] = True
        action = current_action(project, cand, cfg, args, round_id, exec_state)
        if action.get("kind") != "review":
            return {"status": "blocked",
                    "reason": "shared controller could not prepare the round-end REVIEW action"}

    if action.get("kind") == "review":
        prepared = prepare_host_step(project, cand, cfg, args, round_id, exec_state)
        if prepared.get("kind") == "blocked":
            return _host_protocol_action(prepared)
        if prepared.get("kind") != "needs_host":
            return {"status": "blocked", "reason": "REVIEW owner did not return a host request"}
        request = prepared.get("request") or {}
        request_id = prepared.get("request_id") or request.get("request_id")
        marker_path = _host_step_marker_path(project, cand, round_id, request_id)
        marker = _read_host_step_marker(marker_path)
        if not marker or marker.get("phase") != "committed":
            resumed = _resume_recorded_host_response(project, cand, prepared)
            if resumed and resumed.get("status") == "blocked":
                return resumed
            if resumed is None:
                return _host_protocol_action(prepared)
            marker = _read_host_step_marker(marker_path)
            if not marker or marker.get("phase") != "committed":
                return {"status": "blocked",
                        "reason": "persisted REVIEW response did not produce a commit marker"}
        identity = request.get("identity") or {}
        if (identity.get("stage") != "review"
                or identity.get("candidate_id") != str(cand)
                or identity.get("round_id") != str(round_id)
                or identity.get("cursor") != action.get("cursor")):
            return {"status": "blocked", "reason": "persisted REVIEW request identity is stale"}
        context, context_hash, sources = _review_context_snapshot(
            project, cand, action["profile_id"]
        )
        inputs = request.get("inputs") or {}
        if (inputs.get("review_context") != context
                or inputs.get("review_context_sha256") != context_hash
                or inputs.get("source_hashes") != sources):
            return {"status": "blocked", "reason": "persisted REVIEW context or source hashes changed"}
        receipt_data = marker.get("host_receipt") or {}
        if (receipt_data.get("schema_version") != "HostResponseReceipt/v1"
                or receipt_data.get("request_id") != request_id):
            return {"status": "blocked", "reason": "persisted REVIEW response receipt is invalid"}
        raw_path = Path(str(receipt_data.get("raw_response_path") or "")).resolve(strict=True)
        request_path = Path(str(request.get("request_path") or "")).resolve(strict=True)
        raw_bytes = raw_path.read_bytes()
        request_hash = hashlib.sha256(request_path.read_bytes()).hexdigest()
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        if (request_hash != receipt_data.get("request_sha256")
                or raw_hash != receipt_data.get("raw_response_sha256")
                or raw_hash != marker.get("raw_response_sha256")):
            return {"status": "blocked", "reason": "persisted REVIEW bytes differ from receipt"}
        try:
            response_receipt = ENGINE.submit_host_response(
                project, request_id, raw_path, expected_cursor=action["cursor"]
            )
            if response_receipt.get("raw_response_sha256") != raw_hash:
                raise RuntimeError("host response receipt hash changed")
            review = _validate_review_response(json.loads(raw_bytes.decode("utf-8")))
        except (ValueError, RuntimeError, UnicodeError, json.JSONDecodeError) as exc:
            return {"status": "blocked", "reason": f"persisted REVIEW response is invalid: {exc}"}
        decision = _finalize_round(
            project, cand, cfg, round_id, review,
            l7_failures=int(exec_state.get("l7_failures", 0)),
            reuse_persisted=True,
        )
        return round_result(decision)

    if terminal_round:
        decision = _finalize_round(
            project, cand, cfg, round_id, None,
            l7_failures=int(exec_state.get("l7_failures", 0)),
            reuse_persisted=True,
        )
        return round_result(decision)
    if action.get("kind") == "l05":
        prepared = europepmc_runtime.prepare_acquisition_host_step(
            project, cand
        )
        if prepared.get("kind") == "deterministic":
            prepared = europepmc_runtime.continue_acquisition(project, cand)
        outcome = _host_protocol_action(prepared)
        terminal = outcome.get("result") or {}
        if (outcome.get("status") == "terminal"
                and terminal.get("terminal_status") == "L0_5_INSUFFICIENT_STOP"):
            try:
                stop_record, _stop_path = _persist_l05_insufficient_stop(
                    project, cand, round_id, terminal
                )
            except (OSError, RuntimeError, UnicodeError) as exc:
                return {"status": "blocked", "reason": str(exc)}
            return {"status": "terminal", "result": stop_record}
        return outcome
    if action.get("kind") == "pre_research":
        try:
            pending_text_request = _pending_pre_research_text_request(
                project, cand, args, round_id, exec_state, action
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return {"status": "blocked",
                    "reason": f"persisted pre-research text request is invalid: {exc}"}
        if pending_text_request is not None:
            pending = {
                "kind": "needs_host", "step": action["step"],
                "request": pending_text_request,
                "request_id": pending_text_request["request_id"],
                "request_path": pending_text_request["request_path"],
            }
            resumed = _resume_recorded_host_response(project, cand, pending)
            if resumed and resumed.get("status") == "blocked":
                return resumed
            if resumed is not None:
                return _continue_after_host_response(
                    project, cand, cfg, args, round_id, exec_state, action
                )
    if action.get("kind") == "l7":
        load_pending = getattr(ENGINE, "load_host_request_for_identity", None)
        if not callable(load_pending):
            return {"status": "blocked",
                    "reason": "host request slot recovery is unavailable for L7"}
        try:
            binding = rl._ledger_for(
                project, getattr(args, "knowledge_store", None), readonly=True
            ).require_binding(project)
            identity = {
                "project_id": str(binding["project_id"]),
                "candidate_id": str(cand), "round_id": str(round_id),
                "node": "L7", "persona": "Turing",
                "profile_id": str(action["profile_id"]),
                "stage": "cognitive", "attempt": int(
                    exec_state.get("host_attempts", {}).get("L7", 1)
                ), "cursor": action.get("cursor"),
            }
            pending_request = load_pending(project, identity)
            if pending_request is not None:
                _validate_host_step_request(
                    project, cand, round_id, action, pending_request
                )
                _validate_l7_workspace_request(project, cand, pending_request)
                pending = {
                    "kind": "needs_host", "step": action["step"],
                    "request": pending_request,
                    "request_id": pending_request["request_id"],
                    "request_path": pending_request["request_path"],
                }
                resumed = _resume_recorded_host_response(project, cand, pending)
                if resumed and resumed.get("status") == "blocked":
                    return resumed
                if resumed is not None:
                    return _continue_after_host_response(
                        project, cand, cfg, args, round_id, exec_state, action
                    )
                return _host_protocol_action(pending)
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            return {"status": "blocked",
                    "reason": f"persisted L7 host request is invalid: {exc}"}
    prepared = prepare_host_step(project, cand, cfg, args, round_id, exec_state)
    if prepared.get("kind") == "needs_host":
        resumed = _resume_recorded_host_response(project, cand, prepared)
        if resumed and resumed.get("status") == "blocked":
            return resumed
        if resumed is not None:
            return _continue_after_host_response(
                project, cand, cfg, args, round_id, exec_state, action
            )
    if action.get("kind") == "pre_research" and prepared.get("kind") == "deterministic":
        # The completed pre-research artifact is the durable completion signal.
        # Reconstruct the in-memory prepared marker after a process restart and
        # return the next action in this same call, so a fresh CLI invocation
        # cannot loop on the already-completed pre-research owner.
        exec_state["prepared_action_identity"] = action["identity"]
        next_action = current_action(project, cand, cfg, args, round_id, exec_state)
        if next_action.get("kind") == "pre_research":
            return {"status": "blocked",
                    "reason": "pre-research completion did not advance the shared next-step owner"}
        prepared = prepare_host_step(project, cand, cfg, args, round_id, exec_state)
    return _host_protocol_action(prepared)


def host_protocol_submit(project, cand, request_id, response_path, *,
                         session_identity=None):
    """Submit through the owning handoff boundary, then return its exact outcome."""
    request = ENGINE.load_host_request(project, request_id)
    identity = request.get("identity") or {}
    stage = str(identity.get("stage") or "")
    if stage == "planner" or stage == "semantic" or stage.startswith("semantic:"):
        receipt = europepmc_runtime.submit_acquisition_host_response(
            project, cand, request_id, response_path
        )
        continued = europepmc_runtime.continue_acquisition(project, cand)
        result = _host_protocol_action(continued)
        return {"status": "committed", "response_receipt": receipt,
                "continuation": result}
    if session_identity is None:
        committed = submit_host_step(project, cand, request_id, response_path)
    else:
        committed = submit_host_step(
            project, cand, request_id, response_path,
            session_identity=session_identity,
        )
    return {"status": "committed", **committed}


def _host_command_configuration(args):
    project = Path(args.project_dir).resolve()
    cand = str(args.cand_id)
    if getattr(args, "knowledge_store", None):
        os.environ["RLR_HYPOTHESIS_STORE"] = str(Path(args.knowledge_store).resolve())
    if (not rl._candidate_file(project, cand).exists()
            and not (project / "99_Archive" / f"{cand}.md").exists()):
        raise ValueError(f"no candidate {cand} in {project}")
    if not (project / "99_Archive" / f"{cand}.md").exists():
        ready = l0_preflight.validate_project_ready(
            str(project), candidate_path=rl._candidate_file(project, cand)
        )
        if ready.get("status") != "PASS":
            raise ValueError(
                f"PROJECT_NOT_READY {ready.get('code')}: {ready.get('reason')}"
            )
    if not _formal_runtime_preflight():
        raise ValueError("formal runtime preflight failed")
    dep = _ctl("check-deps", str(project))
    if dep.returncode != 0:
        raise ValueError("L0 dependency gate failed: " +
                         str(dep.stderr or dep.stdout).strip())
    config_path = Path(args.config or project / "rlr_runner.yaml")
    if not config_path.exists():
        config_path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    cfg = orch.ProviderConfig.load(str(config_path))
    if cfg.mode == "main_agent":
        raise ValueError("configuration uses retired mode: main_agent")
    if cfg.mode not in (None, ""):
        log(f"WARNING: top-level mode={cfg.mode!r} is deprecated and inert")
    profile_id = _bound_profile_id(project) or PROFILE_V20
    try:
        from research_loop import pre_e2e_closure
        closure = pre_e2e_closure.audit_static_closure(profile_id)
    except Exception as exc:
        raise ValueError(f"static closure audit failed: {exc}") from exc
    if not closure.get("e2e_start_allowed", False):
        raise ValueError("static closure gate is open: " +
                         json.dumps(closure.get("unresolved_required_paths") or [],
                                    ensure_ascii=False, sort_keys=True))
    capabilities = agent_native_capabilities(profile_id)
    missing = sorted(name for name, implemented in capabilities.items()
                     if implemented is not True)
    if not capabilities or missing:
        raise ValueError("agent-native capability gate failed: " +
                         (", ".join(missing) if missing else "empty capability map"))
    return project, cand, cfg


def _host_command_round_id(project, cand, resume):
    candidate_path = rl._candidate_file(Path(project), cand)
    frontmatter = rl._load_yaml_front(candidate_path) if candidate_path.exists() else {}
    return str(frontmatter.get("round_id", 1) or 1) if resume else "1"


def cmd_host_next(args):
    try:
        project, cand, cfg = _host_command_configuration(args)
        round_id = _host_command_round_id(project, cand, args.resume)
        restore_previous_round(str(project), cand)
        args.mode = "agent_native"
        exec_state = {}
        action = host_protocol_next(
            str(project), cand, cfg, args, round_id, exec_state
        )
        print(json.dumps(action, ensure_ascii=False, sort_keys=True))
        return 3 if action.get("status") == "blocked" else 0
    except (ValueError, RuntimeError, OSError, L0StateError) as exc:
        log(f"HOST NEXT BLOCKED: {exc}")
        return 3


def cmd_host_submit(args):
    try:
        project, cand, _cfg = _host_command_configuration(args)
        submitted = host_protocol_submit(
            str(project), cand, args.request_id, args.response_path
        )
        print(json.dumps(submitted, ensure_ascii=False, sort_keys=True))
        continuation = submitted.get("continuation") or {}
        if continuation.get("status") == "blocked":
            return 3
        return 0
    except (ValueError, RuntimeError, OSError, L0StateError) as exc:
        log(f"HOST SUBMIT BLOCKED: {exc}")
        return 3


def execute_deterministic_action(action, project, cand, cfg, args, run_dir,
                                 round_id, exec_state) -> dict:
    """Execute existing deterministic runner/controller owners for an action."""
    kind = action["kind"]
    step = action["step"]
    if kind == "pre_research":
        ok = ensure_pre_research(
            project, cand, step["node"], cfg, args, run_dir
        )
        return {"kind": kind, "ok": bool(ok)}
    if kind == "report":
        result = _ctl("aggregate-report", project, cand)
        return {"kind": kind, "ok": result.returncode == 0, "result": result}
    raise ValueError(f"action {kind!r} is not a deterministic runner action")


def run_round(project, cand, cfg, args, round_id, max_rounds, exec_state,
              *, mode: ExecutionMode = "headless"):
    """Drive one full DAG pass for a candidate. Returns an outcome string."""
    if mode not in ("headless", "agent_native"):
        raise ValueError(f"unsupported execution mode: {mode!r}")
    args.mode = mode
    run_dir = Path(project) / "08_Run_Receipts" / cand / f"round_{round_id:02d}"
    max_l7 = int(cfg.stop_policy.get("max_l7_failures", 2))
    max_node = int(cfg.stop_policy.get("max_node_failures", 2))
    retry_threshold = int(cfg.stop_policy.get("loopx_retry_threshold", 2))
    exec_state.setdefault("loopx_policy", LoopXRetryPolicy(retry_threshold))
    while True:
        action = current_action(project, cand, cfg, args, round_id, exec_state)
        step = action["step"]
        if action["kind"] == "terminal":
            log(f"terminal status: {step.get('status')}")
            return "terminal"
        if mode == "agent_native":
            return "agent_native_handoff_required"
        if action["kind"] == "pre_research":
            node = step["node"]
            recovered = _recover_committed_advance(project, cand, step)
            if recovered is not None:
                if not recovered:
                    return f"node_failed:{node}"
                continue
            prepared = execute_deterministic_action(
                action, project, cand, cfg, args, run_dir, round_id, exec_state
            )
            if not prepared["ok"]:
                return f"node_failed:{node}"
            exec_state["prepared_action_identity"] = action["identity"]
            continue
        if step.get("is_parallel"):
            authorization_ids = {}
            if (Path(project) / "00_Preflight" /
                    "hypothesis_store_binding.json").exists():
                authorized = _ctl(
                    "hypothesis-authorize-context", project, cand,
                    "--node", "L9a", "--node", "L9b",
                    "--round-id", str(round_id),
                )
                if authorized.returncode != 0:
                    raise RuntimeError(
                        "cannot create fixed pre-parallel hypothesis snapshots: "
                        f"{authorized.stderr or authorized.stdout}"
                    )
                authorization_ids = {
                    item["node"]: item["authorization_id"]
                    for item in json.loads(authorized.stdout)
                }
            for sub in step["nodes"]:
                log(f"node {sub['node']} ({sub['persona']}) [parallel]")
                exec_state.pop("last_loopx_failure", None)
                ok = exec_cognitive(project, cand, sub, cfg, args, run_dir,
                                    round_id, do_advance=False,
                                    authorization_id=authorization_ids.get(sub["node"]),
                                    failure_state=exec_state)
                event = exec_state.get("last_loopx_failure")
                if not ok and event and event["recommended_action"] != "RETRY_SAME_NODE":
                    log(f"Loop X {sub['node']}: {event['recommended_action']} "
                        f"for {event['failure_fingerprint']}")
                    return f"node_failed:{sub['node']}"
                if not ok and _bump_node_failure(exec_state, sub["node"], max_node):
                    log(f"node {sub['node']} failed emit "
                        f"{exec_state['node_failures'][sub['node']]}x -- "
                        f"aborting round (no further retries)")
                    return f"node_failed:{sub['node']}"
            continue
        node = step["node"]
        if action["kind"] == "l05":
            log("node L0.5 (Curie) [research acquisition / FREEZE]")
            l05_outcome = exec_l05(project, cand, step, cfg, args, run_dir, round_id)
            if l05_outcome["terminal_status"] == "L0_5_INSUFFICIENT_STOP":
                return l05_outcome
            if l05_outcome["terminal_status"] != "FROZEN":
                return l05_outcome
            continue
        recovered = _recover_committed_advance(project, cand, step)
        if recovered is not None:
            if not recovered:
                return f"node_failed:{node}"
            continue
        if action["kind"] == "report":
            report = execute_deterministic_action(
                action, project, cand, cfg, args, run_dir, round_id, exec_state
            )
            if not report["ok"]:
                result = report["result"]
                detail = (result.stderr.strip() or result.stdout.strip()
                          or "aggregate-report failed")
                log(f"L10c finalization failed: {detail}")
                return "node_failed:L10c"
            log("L10c: report + required Obsidian projection + round manifest complete")
            return "completed"
        if action["kind"] == "l7":
            log("node L7 (Turing) [execution / Path A]")
            exec_state.pop("last_loopx_failure", None)
            if not exec_turing(project, cand, step, cfg, args, run_dir,
                               round_id, exec_state):
                event = exec_state.get("last_loopx_failure")
                if event and event["recommended_action"] != "RETRY_SAME_NODE":
                    log(f"Loop X L7: {event['recommended_action']} "
                        f"for {event['failure_fingerprint']}")
                    return "node_failed:L7"
                if exec_state["l7_failures"] >= max_l7:
                    log(f"L7 failed {exec_state['l7_failures']}x — aborting round")
                    return "l7_failed"
            continue
        log(f"node {node} ({step['persona']}) advance={step.get('advance_command')}")
        exec_state.pop("last_loopx_failure", None)
        ok = exec_cognitive(project, cand, step, cfg, args, run_dir, round_id,
                            failure_state=exec_state)
        event = exec_state.get("last_loopx_failure")
        if not ok and event and event["recommended_action"] != "RETRY_SAME_NODE":
            log(f"Loop X {node}: {event['recommended_action']} "
                f"for {event['failure_fingerprint']}")
            return f"node_failed:{node}"
        if not ok and _bump_node_failure(exec_state, node, max_node):
            log(f"node {node} failed emit {exec_state['node_failures'][node]}x -- "
                f"aborting round (no further retries)")
            return f"node_failed:{node}"
        if ok and args.stop_after_node and node == args.stop_after_node:
            log(f"--stop-after-node {node}: halting round")
            return "stopped_after_node"


def run_review_gate(project, cand, cfg, args, run_dir):
    rep = Path(project) / "FINAL_REPORT.md"
    if not rep.exists():
        log("review gate skipped (no FINAL_REPORT.md)")
        return None
    parts = ["=== FINAL_REPORT.md ===", rep.read_text(encoding="utf-8")]
    cn = Path(project) / "FINAL_REPORT_CN.md"
    if cn.exists():
        parts += ["=== FINAL_REPORT_CN.md ===", cn.read_text(encoding="utf-8")]
    profile_id = next_step(project, cand).get("profile_id")
    if not profile_id:
        raise RuntimeError("review gate cannot resolve the bound project profile")
    l8_key = artifact_for_node(get_profile(profile_id), "L8").storage_key
    for dk in (l8_key, "L9a_feynman", "L9b_darwin", "L10b_oppenheimer"):
        d = load_delta(project, cand, dk)
        if d is not None:
            parts += [f"=== {dk} ===", json.dumps(d, indent=2, ensure_ascii=False)]
    context = "\n\n".join(parts)
    try:
        prov = provider_for("REVIEW", cfg, args)
        out = prov.run_agent("REVIEW", "Reviewer", context,
                             output_schema=REVIEW_SCHEMA, run_dir=str(run_dir))
    except Exception as e:
        log(f"review gate skipped ({e})")
        return None
    out = _validate_review_response(out)
    log(f"review verdict: {out.get('review_verdict')}")
    return out


class StopPolicy:
    """Hybrid stop rule: continue only if another round can change conclusion."""

    def __init__(self, max_rounds=3, marginal_gain_stop_threshold=2,
                 keep_requires_review_accept=True, max_l7_failures=2):
        self.max_rounds = max_rounds
        self.mg_threshold = marginal_gain_stop_threshold
        self.keep_requires_review_accept = keep_requires_review_accept
        self.max_l7_failures = max_l7_failures

    @staticmethod
    def _marginal_gain(l10b, review):
        for src in (review, l10b):
            v = (src or {}).get("marginal_gain_score")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return v
        return None

    @staticmethod
    def _executable(next_steps, review):
        if review and review.get("executable_next_actions"):
            return bool(review["executable_next_actions"])
        if not next_steps:
            return False
        def trivial(s):
            s = str(s).lower()
            return any(k in s for k in _POLISH_KW)
        return any(not trivial(s) for s in next_steps)

    @staticmethod
    def _no_new_evidence_two_rounds(prev_summaries):
        sigs = [s.get("evidence_sig") for s in prev_summaries
                if s.get("evidence_sig")]
        return len(sigs) >= 2 and sigs[-1] == sigs[-2]

    def _stop(self, reason):
        return {"stop": True, "reason": reason, "next_round_required": False,
                "new_candidate_title": None, "new_candidate_question": None,
                "new_candidate_claim": None}

    def _continue(self, l10b, review, parent_fm):
        next_steps = (l10b or {}).get("next_steps") or []
        focus = ((review or {}).get("executable_next_actions")
                 or next_steps or ["address reviewer revisions"])
        focus_txt = "; ".join(str(x) for x in focus[:3])
        pfm = parent_fm or {}
        title = (pfm.get("title", "candidate")) + " (revised round)"
        return {"stop": False,
                "reason": "REVISE with executable next actions likely to move "
                          "evidence/falsification scores",
                "next_round_required": True,
                "new_candidate_title": title,
                "new_candidate_question": pfm.get("question", ""),
                "new_candidate_claim": f"Revised focus: {focus_txt}"}

    def decide(self, *, status, l10b, review, round_id, prev_summaries,
               l7_failures, parent_fm=None):
        l10b = l10b or {}
        decision = str(l10b.get("decision", "")).upper()
        review_verdict = (review or {}).get("review_verdict")
        next_steps = l10b.get("next_steps") or []
        if status in ("DROP", "DOWNGRADE", "ARCHIVED"):
            return self._stop(f"terminal status {status}")
        if l7_failures >= self.max_l7_failures:
            return self._stop(f"L7 execution failed {l7_failures}x")
        if review_verdict == "reject":
            return self._stop("review verdict = reject (human should re-scope)")
        if status == "KEEP" and review_verdict in ("accept", "weak_accept"):
            return self._stop(f"KEEP and review={review_verdict}")
        if status == "KEEP" and not self.keep_requires_review_accept:
            return self._stop("KEEP (review not required by policy)")
        if round_id >= self.max_rounds:
            return self._stop(f"max_rounds ({self.max_rounds}) reached")
        mg = self._marginal_gain(l10b, review)
        if mg is not None and mg <= self.mg_threshold:
            return self._stop(f"marginal_gain_score {mg} <= {self.mg_threshold} "
                              "(another round unlikely to change the conclusion)")
        if decision == "REVISE" and not self._executable(next_steps, review):
            return self._stop("REVISE but next_steps are empty / non-executable "
                              "(polish-only, not conclusion-changing)")
        if self._no_new_evidence_two_rounds(prev_summaries):
            return self._stop("two consecutive rounds added no new key evidence")
        executable = self._executable(next_steps, review)
        if decision == "REVISE" and executable and round_id < self.max_rounds:
            return self._continue(l10b, review, parent_fm)
        if status == "KEEP":
            return self._stop("KEEP (no review verdict; nothing to continue on)")
        return self._stop("no continue condition met (default stop)")


def _stop_policy_for_config(cfg, max_rounds=None):
    data = getattr(cfg, "data", None) or {}
    return StopPolicy(
        max_rounds=int(max_rounds or getattr(cfg, "max_rounds", None)
                       or data.get("max_rounds", 0) or 3),
        marginal_gain_stop_threshold=int(
            cfg.stop_policy.get("marginal_gain_stop_threshold", 2)),
        keep_requires_review_accept=bool(
            cfg.stop_policy.get("keep_requires_review_accept", True)),
        max_l7_failures=int(cfg.stop_policy.get("max_l7_failures", 2)),
    )


def _l05_insufficient_stop_record(outcome):
    stop_record = {
        **outcome,
        "node": "L0.5",
        "downstream": "NOT_ATTEMPTED",
        "L1": "NOT_ATTEMPTED",
        "REVIEW": "NOT_ATTEMPTED",
        "L10b": "NOT_ATTEMPTED",
        "not_attempted_nodes": {
            node: "NOT_ATTEMPTED" for node in (
                "L1", "L2", "L3", "L4", "L5", "L6", "L7",
                "L8", "L8.5", "L9a", "L9b", "L10a", "L10b", "L10c",
                "REVIEW",
            )
        },
    }
    return stop_record


def _persist_l05_insufficient_stop(project, cand, round_id, outcome):
    """Persist the shared downstream-NOT_ATTEMPTED terminal record for L0.5."""
    run_dir = (Path(project) / "08_Run_Receipts" / str(cand)
               / f"round_{int(round_id):02d}")
    run_dir.mkdir(parents=True, exist_ok=True)
    stop_record = _l05_insufficient_stop_record(outcome)
    stop_path = run_dir / "stop_decision.json"
    raw_stop = json.dumps(stop_record, indent=2, ensure_ascii=False)
    if stop_path.exists() and stop_path.read_text(encoding="utf-8") != raw_stop:
        raise RuntimeError("L0.5 stop record conflicts with existing run decision")
    if not stop_path.exists():
        fd, temporary = tempfile.mkstemp(
            prefix=f".{stop_path.name}.", dir=str(run_dir)
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw_stop.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, stop_path)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
    return stop_record, stop_path


def _round_summary_history(project, cand, round_id):
    summaries = []
    project_path = Path(project)
    current_candidate = str(cand)
    try:
        current_frontmatter = rl._load_yaml_front(
            rl._candidate_file(project_path, current_candidate)
        )
    except (OSError, ValueError):
        current_frontmatter = {}

    # Continuation candidates record their direct parent. Walk that explicit
    # lineage, retaining each ancestor's own round_id, then read summaries in
    # chronological order. Round numbers alone cannot identify which candidate
    # owned a prior round after a continuation.
    ancestors = []
    visited = {current_candidate}
    previous_candidate = str(
        current_frontmatter.get("previous_candidate_id") or ""
    ).strip()
    while previous_candidate and previous_candidate not in visited:
        visited.add(previous_candidate)
        try:
            frontmatter = rl._load_yaml_front(
                rl._candidate_file(project_path, previous_candidate)
            )
        except (OSError, ValueError):
            break
        try:
            ancestor_round = int(frontmatter.get("round_id"))
        except (TypeError, ValueError):
            break
        if ancestor_round < int(round_id):
            ancestors.append((previous_candidate, ancestor_round))
        previous_candidate = str(
            frontmatter.get("previous_candidate_id") or ""
        ).strip()

    for ancestor_candidate, ancestor_round in reversed(ancestors):
        path = (project_path / "08_Run_Receipts" / ancestor_candidate
                / f"round_{ancestor_round:02d}" / "stop_decision.json")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"prior stop decision is invalid: {path}: {exc}") from exc
        summary = record.get("round_summary") if isinstance(record, dict) else None
        if isinstance(summary, dict):
            summaries.append(summary)
    return summaries


def _finalize_round(project, cand, cfg, round_id, review, *,
                    prev_summaries=(), l7_failures=0, reuse_persisted=False,
                    max_rounds=None):
    """Use the shared StopPolicy and terminal artifact owner for one round."""
    run_dir = Path(project) / "08_Run_Receipts" / str(cand) / f"round_{int(round_id):02d}"
    stop_path = run_dir / "stop_decision.json"
    if reuse_persisted and stop_path.is_file():
        try:
            existing = json.loads(stop_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"persisted stop decision is invalid: {exc}") from exc
        if isinstance(existing, dict) and (
            existing.get("stop") is True or existing.get("next_candidate_id")
        ):
            return existing

    status = status_of(project, cand)
    l10b = load_delta(project, cand, "L10b_oppenheimer")
    summary = {
        "round": int(round_id), "candidate": str(cand), "status": status,
        "evidence_sig": evidence_sig(project, cand),
        "review_verdict": (review or {}).get("review_verdict"),
    }
    summaries = list(prev_summaries)
    if reuse_persisted and not summaries:
        summaries = _round_summary_history(project, cand, round_id)
    summaries.append(summary)
    parent_fm = rl._load_yaml_front(rl._candidate_file(Path(project), cand))
    decision = _stop_policy_for_config(cfg, max_rounds).decide(
        status=status, l10b=l10b, review=review, round_id=int(round_id),
        prev_summaries=summaries, l7_failures=int(l7_failures),
        parent_fm=parent_fm,
    )
    record = {**decision, "round_summary": summary}
    run_dir.mkdir(parents=True, exist_ok=True)
    if not decision["stop"]:
        child = create_child(project, cand, decision, int(round_id) + 1)
        record["next_candidate_id"] = child
    fd, temp_name = tempfile.mkstemp(prefix=f".{stop_path.name}.", dir=str(run_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(record, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, stop_path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return record


def evidence_sig(project, cand):
    profile_id = next_step(project, cand).get("profile_id")
    if not profile_id:
        raise RuntimeError("evidence signature cannot resolve project profile")
    l8_key = artifact_for_node(get_profile(profile_id), "L8").storage_key
    l8 = load_delta(project, cand, l8_key) or {}
    l9a = load_delta(project, cand, "L9a_feynman") or {}
    basis = json.dumps({"lvl": l8.get("evidence_level"),
                        "ev": l8.get("evidence_verified"),
                        "surv": l9a.get("survives"),
                        "fals": l9a.get("falsified")},
                       sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def create_child(project, parent_cand, decision, new_round):
    parent_fm = rl._load_yaml_front(rl._candidate_file(Path(project), parent_cand))
    l10b = load_delta(project, parent_cand, "L10b_oppenheimer") or {}
    proposal = l10b.get("next_round_proposal") or {}
    if str(l10b.get("decision", "")).upper() != "REVISE":
        raise RuntimeError("only a committed L10b REVISE decision may create a child")
    loop_type = proposal.get("loop_type")
    successor = proposal.get("hypothesis_id")
    if not loop_type or not successor:
        raise RuntimeError("L10b REVISE lacks loop_type or successor hypothesis_id")
    emitted = _ctl("emit-loop-memory", project, parent_cand)
    if emitted.returncode != 0:
        raise RuntimeError(f"emit-loop-memory failed: {emitted.stdout} {emitted.stderr}")
    memory_path = (Path(project) / "08_Audit" / "loop_memory" /
                   f"{parent_cand}_next_loop_memory.json")
    try:
        memory = json.loads(memory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot reload emitted loop-memory: {exc}") from exc
    if (memory.get("schema_version") != "2.0"
            or memory.get("loop_type") != loop_type
            or memory.get("next_round_hypothesis_id") != successor):
        raise RuntimeError("emitted loop-memory does not match the L10b continuation proposal")
    src = (f"Round {new_round - 1} FINAL_REPORT.md + key deltas "
           f"(L8/L9a/L9b/L10b) of {parent_cand}")
    r = _ctl("new-candidate", project,
             "--title", decision["new_candidate_title"] or "revised candidate",
             "--question", decision["new_candidate_question"]
             or parent_fm.get("question", ""),
             "--claim", decision["new_candidate_claim"] or "revised claim",
             "--input", src, "--from-memory", str(memory_path),
             "--loop-type", loop_type, "--inherit-previous-source")
    child = r.stdout.split()[0] if r.stdout.strip() else None
    if not child:
        raise RuntimeError(f"new-candidate failed: {r.stdout} {r.stderr}")
    return child


def _plan_line(nid, cfg, node_map, is_l10c=False):
    ni = node_map[nid]
    if is_l10c:
        return (f"  {nid:5} {ni['persona']:11} provider=-          "
                f"advance=aggregate-report (controller -- no agent call)")
    spec = cfg.for_node(nid)
    return (f"  {nid:5} {ni['persona']:11} provider={spec.get('type','manual'):8} "
            f"tools={ni.get('tools_policy'):11} advance={ni.get('advance_command')}"
            f"  inputs={ni['context_inputs']}")


def dry_run_plan(project, cand, cfg, max_rounds, review_on):
    log("DRY RUN -- no external model calls, no state changes")
    log(f"project={project} candidate={cand} max_rounds={max_rounds} "
        f"review={'on' if review_on else 'off'}")
    step = next_step(project, cand)
    if step.get("terminal"):
        log(f"candidate is terminal ({step.get('status')}); nothing to plan")
        return 0
    start = step["nodes"][0]["node"] if step.get("is_parallel") else step["node"]
    profile_id = step.get("profile_id", PROFILE_V20)
    _, node_map, seq = topology_for_profile(profile_id)
    i = seq.index(start) if start in seq else 0
    log(f"current status={status_of(project, cand)}  next node={start}")
    print("planned nodes this round:")
    for nid in seq[i:]:
        if nid == "L9_parallel":
            for sub in ("L9a", "L9b"):
                print(_plan_line(sub, cfg, node_map))
        elif nid == "L10c":
            print(_plan_line(nid, cfg, node_map, is_l10c=True))
        else:
            print(_plan_line(nid, cfg, node_map))
    print()
    tail = "review gate -> " if review_on else ""
    log(f"after L10c: {tail}StopPolicy(max_rounds={max_rounds}) decides stop/continue")
    try:
        orch.make_provider(cfg.default, override_type=None)
        log(f"default provider '{cfg.default.get('type')}' resolves OK (automatic)")
    except orch.ProviderError as e:
        log(f"NOTE: default provider not runnable yet -- {str(e).splitlines()[0]}")
    log("dry-run complete (one round planned; loop is bounded by max_rounds)")
    return 0


def cmd_run(args, *, mode: ExecutionMode = "headless"):
    if mode not in ("headless", "agent_native"):
        raise ValueError(f"unsupported execution mode: {mode!r}")
    project, cand = args.project_dir, args.cand_id
    if getattr(args, "knowledge_store", None):
        os.environ["RLR_HYPOTHESIS_STORE"] = str(
            Path(args.knowledge_store).resolve()
        )
    if not rl._candidate_file(Path(project), cand).exists() \
            and not (Path(project) / "99_Archive" / f"{cand}.md").exists():
        log(f"ERROR: no candidate {cand} in {project}")
        return 2
    if not getattr(args, "dry_run", False):
        ready = l0_preflight.validate_project_ready(
            project, candidate_path=rl._candidate_file(Path(project), cand)
        )
        if ready.get("status") != "PASS":
            log(f"PROJECT_NOT_READY -- {ready.get('code')}: {ready.get('reason')}")
            return 3

    if not getattr(args, "dry_run", False) and not _formal_runtime_preflight():
        return 3

    dep = _ctl("check-deps", project)
    if dep.returncode != 0:
        log("L0 DEPENDENCY GATE FAILED -- halting (not skipping):")
        for ln in (dep.stderr or dep.stdout).strip().splitlines():
            log(f"  {ln}")
        return 3

    cfg_path = args.config or str(Path(project) / "rlr_runner.yaml")
    if not Path(cfg_path).exists():
        Path(cfg_path).write_text(DEFAULT_CONFIG, encoding="utf-8")
        log(f"wrote default config: {cfg_path}")
    cfg = orch.ProviderConfig.load(cfg_path)
    override = getattr(args, "provider", None)
    if cfg.mode == "main_agent" or override == "main_agent":
        source = "configuration mode" if cfg.mode == "main_agent" else "CLI provider"
        log(f"ERROR: {source} uses retired mode: main_agent.")
        log("       Remove `mode: main_agent` and configure execution under `provider:`.")
        return 2
    if cfg.mode not in (None, ""):
        log(
            f"WARNING: top-level mode={cfg.mode!r} is deprecated and inert; "
            "provider.default/provider.nodes select execution"
        )
    max_rounds = args.max_rounds or cfg.max_rounds or 3

    if args.dry_run:
        return dry_run_plan(project, cand, cfg, max_rounds,
                            review_on=(not args.no_review
                                       and cfg.review.get("enabled", True)))

    # Restore is deterministic state validation, not provider work. It must run
    # before provider readiness so a broken continuation cannot consume model
    # quota or receive a node prompt.
    try:
        binding = restore_previous_round(project, cand)
    except L0StateError as exc:
        log(f"L0 STATE RESTORE FAILED -- {exc.code}: {exc.detail}")
        return 3
    if binding.get("binding_status") == "PASS":
        log(f"L0 state restore PASS: {len(binding.get('verified_artifacts', []))} "
            "prior artifacts verified")

    try:
        if rl.binding_path(project).exists():
            profile_id = rl._ledger_for(
                project, getattr(args, "knowledge_store", None), readonly=True
            ).project_profile(project)
        else:
            profile_id = PROFILE_V20
        from research_loop import pre_e2e_closure
        closure = pre_e2e_closure.audit_static_closure(profile_id)
    except Exception as exc:
        log(f"STATIC CLOSURE AUDIT FAILED -- halting before provider startup: {exc}")
        return 3
    if not closure.get("e2e_start_allowed", False):
        log("STATIC CLOSURE OPEN -- halting before provider startup:")
        for item in closure.get("unresolved_required_paths") or []:
            log(f"  {json.dumps(item, ensure_ascii=False, sort_keys=True)}")
        return 3

    if mode == "agent_native":
        capabilities = agent_native_capabilities(profile_id)
        missing = sorted(
            name for name, implemented in capabilities.items() if implemented is not True
        )
        if not capabilities or missing:
            log(
                "AGENT-NATIVE CAPABILITY GATE FAILED -- halting before first round: "
                + (", ".join(missing) if missing else "capability map is empty")
            )
            return 3

    if mode == "headless" and not preflight_providers(cfg, args):
        log("aborting: no runnable provider configured under provider.default/provider.nodes.")
        return 2

    summaries = []
    cur = cand
    round_id = int(rl._load_yaml_front(
        rl._candidate_file(Path(project), cur)).get("round_id", 1) or 1) \
        if args.resume else 1

    while round_id <= max_rounds:
        log(f"================ ROUND {round_id} | candidate {cur} ================")
        exec_state = {"l7_failures": 0, "node_failures": {}}
        outcome = run_round(project, cur, cfg, args, round_id, max_rounds,
                            exec_state, mode=mode)
        if outcome == "agent_native_handoff_required":
            log("agent-native step requires the host handoff path; refusing headless fallback")
            return 2
        if isinstance(outcome, dict):
            if outcome.get("terminal_status") == "L0_5_INSUFFICIENT_STOP":
                try:
                    _stop_record, _stop_path = _persist_l05_insufficient_stop(
                        project, cur, round_id, outcome
                    )
                except (OSError, RuntimeError, UnicodeError):
                    log("L0.5 stop record conflicts with existing run decision")
                    return 4
                log("L0.5 insufficient stop recorded; full DAG incomplete")
                return 0
            log(f"ABORTING RUN: L0.5 {outcome.get('error_category', 'CONTRACT_ERROR')}: "
                f"{outcome.get('detail', 'invalid outcome')}")
            return 4
        if outcome == "stopped_after_node":
            log("halted per --stop-after-node (no stop decision taken)")
            return 0
        if isinstance(outcome, str) and outcome.startswith("node_failed:"):
            log(f"ABORTING RUN: {outcome} -- node execution/finalization failed; "
                "not treated as success")
            return 4

        run_dir = Path(project) / "08_Run_Receipts" / cur / f"round_{round_id:02d}"
        review = None
        if not args.no_review and cfg.review.get("enabled", True):
            review = run_review_gate(project, cur, cfg, args, run_dir)

        decision = _finalize_round(
            project, cur, cfg, round_id, review,
            prev_summaries=summaries,
            l7_failures=exec_state["l7_failures"],
            max_rounds=max_rounds,
        )
        summaries.append(decision["round_summary"])
        log(f"STOP DECISION: stop={decision['stop']} — {decision['reason']}")
        if decision["stop"]:
            break
        cur = decision["next_candidate_id"]
        log(f"opening next round on child candidate: {cur}")
        round_id += 1

    log("loop finished")
    return 0


def cmd_print_main_agent_prompt(args):
    print(
        "The print-main-agent-prompt command is retired. "
        "Use `run_loop.py run PROJECT_DIR CAND_ID` with execution configured "
        "under `provider:`.",
        file=sys.stderr,
    )
    return 2

def build_parser():
    p = argparse.ArgumentParser(
        prog="run_loop.py",
        description="RLR loop runner — sole production orchestration entry point.")
    sub = p.add_subparsers(dest="cmd", required=True)

    ma = sub.add_parser("print-main-agent-prompt",
                        help="retired compatibility command (always exits non-zero)")
    ma.add_argument("project_dir")
    ma.add_argument("cand_id")
    ma.add_argument("--config")
    ma.set_defaults(func=cmd_print_main_agent_prompt)

    sp = sub.add_parser("run", help="run the loop for a candidate")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--config", help="runner config (default: PROJECT_DIR/rlr_runner.yaml)")
    sp.add_argument("--knowledge-store",
                    help="shared hypothesis SQLite store (or use RLR_HYPOTHESIS_STORE)")
    sp.add_argument("--max-rounds", dest="max_rounds", type=int, default=None)
    sp.add_argument(
                    "--provider",
                    choices=["main_agent", "headless", "host", "auto", "command", "manual"],
                    default=None,
                    help="force a provider type for all nodes (manual is debug-only)")
    sp.add_argument("--dry-run", action="store_true",
                    help="print the plan; no model calls, no state changes")
    sp.add_argument("--stop-after-node", dest="stop_after_node",
                    help="halt the round after this node (e.g. L3)")
    sp.add_argument("--no-review", action="store_true",
                    help="skip the Review gate")
    sp.add_argument("--resume", action="store_true",
                    help="resume from the candidate's recorded round_id")
    sp.add_argument("--shadow-ranking", action="store_true",
                    help="after L3/L10b, run advisory ranking without changing gates")
    sp.add_argument("--shadow-candidate", action="append", default=[],
                    help="peer candidate ID for advisory ranking (repeatable)")
    sp.add_argument("--shadow-seed", type=int, default=0,
                    help="deterministic seed passed to advisory ranking")
    sp.add_argument("--shadow-match-budget", type=int, default=10,
                    help="match budget passed to advisory ranking")
    sp.add_argument("--shadow-timeout", type=int, default=60,
                    help="per-run advisory ranking timeout in seconds (1-600)")
    sp.set_defaults(func=cmd_run)

    hn = sub.add_parser(
        "host-next", help="return one agent-native host action without invoking a model"
    )
    hn.add_argument("project_dir")
    hn.add_argument("cand_id")
    hn.add_argument("--config", help="runner config (default: PROJECT_DIR/rlr_runner.yaml)")
    hn.add_argument("--knowledge-store",
                    help="shared hypothesis SQLite store (or use RLR_HYPOTHESIS_STORE)")
    hn.add_argument("--resume", action="store_true",
                    help="restore and continue from the candidate's recorded round")
    hn.set_defaults(func=cmd_host_next)

    hs = sub.add_parser(
        "host-submit", help="submit one host response to the existing RLR owner"
    )
    hs.add_argument("project_dir")
    hs.add_argument("cand_id")
    hs.add_argument("request_id", metavar="REQUEST_ID")
    hs.add_argument("response_path", metavar="RESPONSE_PATH")
    hs.add_argument("--config", help="runner config (default: PROJECT_DIR/rlr_runner.yaml)")
    hs.add_argument("--knowledge-store",
                    help="shared hypothesis SQLite store (or use RLR_HYPOTHESIS_STORE)")
    hs.add_argument("--resume", action="store_true",
                    help="restore and continue from the candidate's recorded round")
    hs.set_defaults(func=cmd_host_submit)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
