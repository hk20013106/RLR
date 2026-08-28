#!/usr/bin/env python3
"""RLR v0.9.2 loop runner — the canonical active runtime entry point.

`python run_loop.py run PROJECT CAND` is the one documented way to drive the
loop. It drives the v0.9.2 engine (research_loop_v04.py) whose `assemble-context`
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

HERE = Path(__file__).resolve().parent
CONTROLLER = HERE / "research_loop_v04.py"
sys.path.insert(0, str(HERE))

import research_loop_v04 as rl       # noqa: E402
import orchestrator as orch          # noqa: E402
from research_loop.api import EngineAPI  # noqa: E402
from research_loop.compatibility import PROFILE_V20, get_profile
from research_loop.code_state import capture_code_state
from research_loop import deep_research
from research_loop.loopx_policy import LoopXRetryPolicy
from research_loop.deep_research import SUPPORTED_BACKENDS
from research_loop.delta import artifact_for_node
from research_loop.hypothesis_contracts import SCHEMA_REGISTRY
from research_loop.l0_state import L0StateError, restore_previous_round
from research_loop import research_seed
from research_loop.topology import topology_for_profile

ENGINE = EngineAPI()


DEFAULT_CONFIG = """\
mode: main_agent
max_rounds: 3

main_agent:
  enabled: true
  description: "The current Claude Code/Codex/AntiGravity/Hermes session acts as the orchestrator. No per-node copy-paste."

provider:
  default:
    type: none

headless:
  enabled: false
  command: ""

deep_research:
  backend: ""
  executable: ""
  skill_path: ""
  plugin_dir: ""
  skill_version: unknown
  timeout: 900

manual:
  enabled: false
  debug_only: true

review:
  enabled: true
  academy_research_skill: optional

stop_policy:
  keep_requires_review_accept: true
  marginal_gain_stop_threshold: 2
  max_l7_failures: 2
  max_node_failures: 2

everos:
  enabled: false
  scope: project_only

# Automatic provider templates are documented in RUNNER.md. Manual mode is
# debug-only; the canonical runner never silently falls back to it.
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
    return orch.make_provider(cfg.for_node(node), override_type=args.provider)


def _context_token_budget(cfg):
    value = (getattr(cfg, "data", {}) or {}).get("context_token_budget", 8000)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("context_token_budget must be a non-negative integer")
    return value


def _provider_output_schema(project, node, step):
    """Resolve the provider submission schema from the bound project profile."""
    native_binding = (Path(project) / "00_Preflight" /
                      "hypothesis_store_binding.json").exists()
    if not native_binding:
        persona = step.get("persona", "").lower()
        return rl.DELTA_SCHEMAS.get(f"{node}_{persona}")
    schema_version = str(step.get("schema_version") or "")
    schemas = SCHEMA_REGISTRY.get(schema_version)
    if schemas is None or node not in schemas:
        raise RuntimeError(
            f"provider schema is unavailable for bound schema {schema_version!r} "
            f"and node {node!r}"
        )
    return schemas[node]


def preflight_providers(cfg, args):
    if cfg.mode == "main_agent":
        log("mode: main_agent (host session orchestrates; no python provider needed)")
        return True
    if args.provider == "manual":
        log("provider: MANUAL (debug mode, explicitly requested via --provider manual)")
        return True
    specs = [("provider.default", cfg.default)]
    specs += [(f"provider.nodes.{n}", s) for n, s in cfg.nodes.items()]
    for label, spec in specs:
        t = args.provider or (spec or {}).get("type")
        if t == "manual":
            log(f"ERROR: {label}.type = 'manual', but manual is DEBUG-ONLY.")
            log("       Configure an automatic provider (type: host | command),")
            log("       e.g. set $RLR_HOST_AGENT_CMD, or run with --provider manual "
                "to force debug mode.")
            return False
        try:
            orch.make_provider(spec, override_type=args.provider)
        except orch.ProviderError as e:
            log(f"ERROR: {label} is not runnable automatically:")
            for ln in str(e).splitlines():
                log(f"       {ln}")
            return False
    log(f"provider: AUTOMATIC ({args.provider or cfg.default.get('type')})")
    return True


def write_receipt(run_dir, node, persona, prov, context, step, cand, round_id,
                  *, manifest=None, provider_delta_file=None, workspace=None,
                  config_path=None, raw_provider_delta_file=None,
                  transformation_receipt_file=None):
    manifest_data = {}
    if manifest:
        manifest_data = json.loads(Path(manifest).read_text(encoding="utf-8"))
    prompt_file = getattr(prov, "last_prompt_file", None)
    delta_file = getattr(prov, "last_delta_file", None)
    provider_delta_file = Path(provider_delta_file) if provider_delta_file else None
    raw_provider_delta_file = Path(
        raw_provider_delta_file or provider_delta_file
    ) if (raw_provider_delta_file or provider_delta_file) else None
    transformation_receipt_file = Path(transformation_receipt_file) if transformation_receipt_file else None
    rendered_context_hash = manifest_data.get("rendered_context_sha256")
    if manifest:
        rendered_path = Path(str(manifest_data.get("rendered_context_path") or ""))
        if not rendered_path.is_file():
            raise ValueError("context manifest rendered context is missing")
        rendered_bytes = rendered_path.read_bytes()
        if hashlib.sha256(rendered_bytes).hexdigest() != rendered_context_hash:
            raise ValueError("context manifest rendered context hash is invalid")
        if context.encode("utf-8") != rendered_bytes:
            raise ValueError("context bytes do not match manifest rendered context bytes")
    code_state = capture_code_state(HERE, config_path) if config_path else None
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
    )
    path = Path(run_dir) / f"{node}_{persona}_receipt.json"
    rec.write(path)
    return str(path)


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
    except Exception as e:
        auto_pitfall(project, cand, node, "provider_failure",
                     f"{persona} provider raised: {e}", provider=pname,
                     evidence=str(run_dir))
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
    except Exception as e:
        exec_state["l7_failures"] += 1
        log(f"L7 provider failed ({e}); failures={exec_state['l7_failures']}")
        auto_pitfall(project, cand, "L7", "execution_failure",
                     f"Turing execution provider failed: {e}", provider=pname,
                     evidence=workspace or str(run_dir))
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
    return command


def exec_l05(project, cand, step, cfg, args, run_dir, round_id):
    """Run the native Curie acquisition boundary before dispatching L1.

    L0.5 is a first-class research phase, not a delta-producing persona.  Its
    command owns discovery, verification, and EvidencePack freeze; the runner
    owns the final ResearchSeed -> native binding handoff so the next-step
    router can authorize L1 from the exact frozen pack.
    """
    try:
        command = _l05_command(project, cand, cfg)
    except ValueError as exc:
        detail = f"invalid L0.5 Curie configuration: {exc}"
        log(detail)
        auto_pitfall(project, cand, "L0.5", "evidence_acquisition_failure",
                     detail, provider="curie-europe-pmc", evidence=str(run_dir))
        return False
    result = _ctl(*command)
    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip()
                  or "L0.5 Curie acquisition failed")
        log(f"L0.5 Curie acquisition failed closed: {detail}")
        auto_pitfall(project, cand, "L0.5", "evidence_acquisition_failure",
                     detail, provider="curie-europe-pmc", evidence=str(run_dir))
        return False
    try:
        acquisition = json.loads(result.stdout)
        if acquisition.get("status") != "FROZEN":
            raise ValueError(
                f"acquisition status is {acquisition.get('status')!r}, expected 'FROZEN'"
            )
        acquisition_run_id = str(acquisition.get("run_id") or "").strip()
        evidence_pack = acquisition.get("evidence_pack")
        if not acquisition_run_id or not isinstance(evidence_pack, dict):
            raise ValueError("FROZEN acquisition result lacks run_id or evidence_pack")
        seed = research_seed.load_l1_research_seed(project, cand)
        research_seed.write_l1_native_evidence_binding(
            project, seed, evidence_pack, acquisition_run_id
        )
        research_seed.activate_l1_native_evidence_binding(
            project, seed, acquisition_run_id
        )
        active_run_id = research_seed.active_l1_native_evidence_run_id(project, seed)
        if str(active_run_id or "") != acquisition_run_id:
            raise ValueError(
                "native L1 activation did not select the acquired run "
                f"{acquisition_run_id!r}"
            )
    except (ValueError, json.JSONDecodeError, research_seed.ResearchSeedError) as exc:
        detail = f"L0.5 Curie result/binding invalid: {exc}"
        log(detail)
        auto_pitfall(project, cand, "L0.5", "evidence_acquisition_failure",
                     detail, provider="curie-europe-pmc", evidence=str(run_dir))
        return False
    log(f"L0.5 Curie: frozen EvidencePack bound and activated for {acquisition_run_id}")
    return True


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
    prompt = _ctl("pre-research", project, cand, "--node", node).stdout
    hl = getattr(cfg, "headless", {}) or {}
    cmd = (hl.get("command") if isinstance(hl, dict) else None) \
        or os.environ.get("RLR_HEADLESS_CMD") or os.environ.get("RLR_HOST_AGENT_CMD")
    if not cmd:
        log(f"pre-research {node}: no headless command -- the orchestrator must run "
            f"`pre-research {project} {cand} --node {node}` (main-agent mode)")
        return True
    try:
        timeout = hl.get("timeout") if isinstance(hl, dict) else None
        md = orch.run_text_command(cmd, prompt, run_dir, f"prefetch_{node}", timeout)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(md, encoding="utf-8")
        log(f"pre-research {node}: produced {target}")
    except Exception as e:
        log(f"pre-research {node}: failed ({e}); continuing without it")
    return True


def _bump_node_failure(exec_state, node, max_node_failures):
    counts = exec_state.setdefault("node_failures", {})
    counts[node] = counts.get(node, 0) + 1
    return counts[node] >= max_node_failures


def run_round(project, cand, cfg, args, round_id, max_rounds, exec_state):
    """Drive one full DAG pass for a candidate. Returns an outcome string."""
    run_dir = Path(project) / "08_Run_Receipts" / cand / f"round_{round_id:02d}"
    max_l7 = int(cfg.stop_policy.get("max_l7_failures", 2))
    max_node = int(cfg.stop_policy.get("max_node_failures", 2))
    retry_threshold = int(cfg.stop_policy.get("loopx_retry_threshold", 2))
    exec_state.setdefault("loopx_policy", LoopXRetryPolicy(retry_threshold))
    while True:
        step = next_step(project, cand)
        if step.get("terminal"):
            log(f"terminal status: {step.get('status')}")
            return "terminal"
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
        if args.stop_after_node and node == args.stop_after_node:
            log(f"--stop-after-node {node}: halting round")
            return "stopped_after_node"
        if node == "L0.5":
            log("node L0.5 (Curie) [research acquisition / FREEZE]")
            if not exec_l05(project, cand, step, cfg, args, run_dir, round_id):
                return "node_failed:L0.5"
            continue
        recovered = _recover_committed_advance(project, cand, step)
        if recovered is not None:
            if not recovered:
                return f"node_failed:{node}"
            continue
        if not ensure_pre_research(project, cand, node, cfg, args, run_dir):
            return f"node_failed:{node}"
        if node == "L10c":
            report = _ctl("aggregate-report", project, cand)
            if report.returncode != 0:
                detail = (report.stderr.strip() or report.stdout.strip()
                          or "aggregate-report failed")
                log(f"L10c finalization failed: {detail}")
                return "node_failed:L10c"
            log("L10c: report + required Obsidian projection + round manifest complete")
            return "completed"
        if node == "L7":
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
    spec = cfg.review.get("provider") or cfg.default
    try:
        prov = orch.make_provider(spec, override_type=args.provider)
        out = prov.run_agent("REVIEW", "Reviewer", context,
                             output_schema=REVIEW_SCHEMA, run_dir=str(run_dir))
        log(f"review verdict: {out.get('review_verdict')}")
        return out
    except Exception as e:
        log(f"review gate skipped ({e})")
        return None


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


def cmd_run(args):
    project, cand = args.project_dir, args.cand_id
    if getattr(args, "knowledge_store", None):
        os.environ["RLR_HYPOTHESIS_STORE"] = str(
            Path(args.knowledge_store).resolve()
        )
    if not rl._candidate_file(Path(project), cand).exists() \
            and not (Path(project) / "99_Archive" / f"{cand}.md").exists():
        log(f"ERROR: no candidate {cand} in {project}")
        return 2

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
    max_rounds = args.max_rounds or cfg.max_rounds or 3

    if args.dry_run:
        return dry_run_plan(project, cand, cfg, max_rounds,
                            review_on=(not args.no_review
                                       and cfg.review.get("enabled", True)))

    # Restore is deterministic state validation, not provider work. It must run
    # before provider readiness or main-agent handoff so a broken continuation
    # cannot consume model quota or receive an orchestration prompt.
    try:
        binding = restore_previous_round(project, cand)
    except L0StateError as exc:
        log(f"L0 STATE RESTORE FAILED -- {exc.code}: {exc.detail}")
        return 3
    if binding.get("binding_status") == "PASS":
        log(f"L0 state restore PASS: {len(binding.get('verified_artifacts', []))} "
            "prior artifacts verified")

    if not preflight_providers(cfg, args):
        log("aborting: no automatic provider configured (see RUNNER.md).")
        return 2

    if cfg.mode == "main_agent" and args.provider in (None, "main_agent"):
        log("main-agent handoff: host session must execute the protocol below; "
            "no python provider will be called")
        return cmd_print_main_agent_prompt(args)

    sp = StopPolicy(
        max_rounds=max_rounds,
        marginal_gain_stop_threshold=int(
            cfg.stop_policy.get("marginal_gain_stop_threshold", 2)),
        keep_requires_review_accept=bool(
            cfg.stop_policy.get("keep_requires_review_accept", True)),
        max_l7_failures=int(cfg.stop_policy.get("max_l7_failures", 2)))

    summaries = []
    cur = cand
    round_id = int(rl._load_yaml_front(
        rl._candidate_file(Path(project), cur)).get("round_id", 1) or 1) \
        if args.resume else 1

    while round_id <= max_rounds:
        log(f"================ ROUND {round_id} | candidate {cur} ================")
        exec_state = {"l7_failures": 0, "node_failures": {}}
        outcome = run_round(project, cur, cfg, args, round_id, max_rounds,
                            exec_state)
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

        st = status_of(project, cur)
        l10b = load_delta(project, cur, "L10b_oppenheimer")
        summaries.append({"round": round_id, "candidate": cur, "status": st,
                          "evidence_sig": evidence_sig(project, cur),
                          "review_verdict": (review or {}).get("review_verdict")})
        parent_fm = rl._load_yaml_front(rl._candidate_file(Path(project), cur))
        decision = sp.decide(status=st, l10b=l10b, review=review,
                             round_id=round_id, prev_summaries=summaries,
                             l7_failures=exec_state["l7_failures"],
                             parent_fm=parent_fm)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "stop_decision.json").write_text(
            json.dumps(decision, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"STOP DECISION: stop={decision['stop']} — {decision['reason']}")
        if decision["stop"]:
            break
        cur = create_child(project, cur, decision, round_id + 1)
        log(f"opening next round on child candidate: {cur}")
        round_id += 1

    log("loop finished")
    return 0


MAIN_AGENT_PROMPT_TEMPLATE = """You are now the RLR v0.9.2 main-agent orchestrator.

Project: {project}
Candidate: {cand_id}

Instructions:
1. Run:  python research_loop_v04.py next-step {project} {cand_id}
2. Read the JSON output to get the current DAG node, persona, and context_files.
3. DEEP RESEARCH (mandatory): before L1, L4, or L8.5, run the configured
   Academic Research runtime; it invokes `$academic-research-suite` for Codex
   or the installed ARS plugin for Claude and persists located paper evidence:
     python research_loop_v04.py deep-research-run {project} {cand_id} --node NODE
   L1 requires Results/Discussion/Conclusion evidence; L4 requires Methods plus
   a review-search receipt; L8.5 requires paper-based result verification. Do
   not hand-write a pre-research note. L7 remains the separate code-search step.
4. Run:  python research_loop_v04.py assemble-context {project} {cand_id} --node NODE
5. The assemble-context output is your ONLY input for this node (it now includes the
   pre-research summary when present). Do NOT read other delta files.
6. Act as the specified persona. Generate a strict JSON delta matching the schema.
7. Write the delta to a temp file, then run:
   python research_loop_v04.py emit-delta {project} {cand_id} --node NODE --persona PERSONA --file TEMP_DELTA.json
8. If emit-delta says VALIDATION: PASS, run the advance_command.
9. Repeat from step 1 until next-step returns L10c (aggregate-report).
10. After L10c, evaluate StopPolicy: if KEEP + review accept, stop. If REVISE with
    executable next_steps, create child candidate.
11. Maximum rounds: {max_rounds}.

Key rules:
- Do NOT read DAG-disallowed delta files. Only use assemble-context output.
- Deep Research runs BEFORE L1/L4/L8.5 and is embedded via assemble-context; it does NOT
  change the 15-node DAG topology.
- The provider receipt must bind the exact raw file passed to `emit-delta`; do not
  reserialize or copy a provider delta before emission.
- L4 Fisher references the local E/G/A handles shown in context. The `emit-delta`
  commit boundary performs the deterministic handle binding and records the raw-to-
  canonical provenance edge; do not create a runner-side bound copy.
- L7 Turing: use prepare-turing-workspace, run scripts only in that workspace.
- {l9_rule}
- If emit-delta fails validation, fix the JSON and retry. Do NOT skip.
- You are the orchestrator. Do not ask the user to copy-paste between nodes.
"""

def cmd_print_main_agent_prompt(args):
    project, cand = args.project_dir, args.cand_id
    cfg_path = args.config or str(Path(project) / "rlr_runner.yaml")
    max_rounds = 3
    if Path(cfg_path).exists():
        cfg = orch.ProviderConfig.load(cfg_path)
        max_rounds = cfg.max_rounds or 3
    try:
        profile_id = next_step(project, cand).get("profile_id", PROFILE_V20)
    except Exception:
        profile_id = PROFILE_V20
    l9_rule = (
        "Historical v2.0 L9a/L9b are parallel and mutually invisible."
        if profile_id == PROFILE_V20 else
        "L9: emit and finalize L9a, then assemble and emit L9b, then permit L10a."
    )
    prompt = MAIN_AGENT_PROMPT_TEMPLATE.format(
        project=project, cand_id=cand, max_rounds=max_rounds,
        l9_rule=l9_rule)
    prompt, meta = rl._caveman_lite(
        prompt, required_literals=[project, cand, "main-agent", "Do NOT"])
    print(prompt)
    log("caveman-lite: " + json.dumps(meta, sort_keys=True))
    return 0

def build_parser():
    p = argparse.ArgumentParser(
        prog="run_loop.py",
        description="RLR v0.9.2 loop runner — canonical runtime entry point "
                    "(main-agent / headless / manual).")
    sub = p.add_subparsers(dest="cmd", required=True)

    ma = sub.add_parser("print-main-agent-prompt",
                        help="print the main-agent orchestration protocol")
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
    sp.add_argument("--provider", choices=["main_agent", "host", "command", "manual"],
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
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
