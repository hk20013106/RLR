#!/usr/bin/env python3
"""RLR v0.3 loop runner — half/auto-automated multi-round driver.

Drives research_loop_v03.py (the controller) around its DAG using a
provider-neutral orchestrator, and decides whether to open another round with a
hybrid StopPolicy (hard cap + L10b decision + optional Review gate + marginal
gain). It does NOT replace the controller and does NOT touch the core DAG/state
machine -- it only calls the controller's CLI and reads its outputs.

    python run_loop.py run PROJECT_DIR CAND_ID --config rlr_runner.yaml
    python run_loop.py run DemoProject_v03 C... --dry-run

Stop rule (the whole point — do not let the loop spin on "polish / new angle"):
the question is NOT "are there issues" but "would another round plausibly change
the conclusion". See StopPolicy.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTROLLER = HERE / "research_loop_v03.py"
sys.path.insert(0, str(HERE))

import research_loop_v03 as rl       # noqa: E402  (controller: DAG metadata + helpers)
import orchestrator as orch          # noqa: E402


DEFAULT_CONFIG = """\
max_rounds: 3
provider:
  default:
    type: manual
  nodes:
    L7:
      type: manual
      filesystem: workspace_only
review:
  enabled: true
  academy_research_skill: optional
stop_policy:
  keep_requires_review_accept: true
  marginal_gain_stop_threshold: 2
  max_l7_failures: 2
everos:
  enabled: false
  scope: project_only

# ---------------------------------------------------------------------------
# CommandProvider templates (commented placeholders -- tool-agnostic).
#
# To drive a node non-interactively, set its provider to `command` and give a
# shell `command` template. Available placeholders: {prompt_file} {output_file}
# {node} {persona} {workspace}. CONTRACT: the command MUST write the delta JSON
# to {output_file}. Raw chat CLIs usually emit prose -> wrap them so the wrapper
# extracts/writes pure JSON (the generic wrapper below is the safest path).
#
# Swap these into provider.default or provider.nodes.<Lx>. Adjust flags to match
# your actual CLI -- the commands here are SHAPES, not verified invocations.
#
# Codex CLI (placeholder flags):
#   provider:
#     default:
#       type: command
#       command: "codex exec --input {prompt_file} --output {output_file}"
#       timeout: 600
#
# Claude CLI (headless; redirection works since the runner uses shell=True):
#   provider:
#     default:
#       type: command
#       command: "claude -p < {prompt_file} > {output_file}"
#       timeout: 600
#   # NOTE: `claude -p` prints the model's text. If it isn't pure JSON, pipe it
#   # through a tiny extractor or use the generic wrapper instead.
#
# Generic wrapper (RECOMMENDED -- write ~10 lines that call any SDK and dump the
# delta JSON to {output_file}); works for Codex / Claude / AntiGravity / Hermes:
#   provider:
#     default:
#       type: command
#       command: "python my_agent.py --prompt {prompt_file} --out {output_file}
#                 --node {node} --persona {persona}"
#       timeout: 600
#
# Per-node mix example (auto cognition via command, manual sandboxed L7):
#   provider:
#     default: {type: command, command: "python my_agent.py --prompt {prompt_file} --out {output_file}"}
#     nodes:
#       L7: {type: manual, filesystem: workspace_only}
# ---------------------------------------------------------------------------
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


# --- controller plumbing ----------------------------------------------------

def _ctl(*args):
    return subprocess.run([sys.executable, str(CONTROLLER), *args],
                          capture_output=True, text=True)


def next_step(project, cand):
    r = _ctl("next-step", project, cand)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"next-step did not return JSON: "
                           f"{r.stdout!r} {r.stderr!r}")


def status_of(project, cand):
    cf = rl._candidate_file(Path(project), cand)
    if not cf.exists():
        cf = Path(project) / "99_Archive" / f"{cand}.md"
    if not cf.exists():
        return "?"
    return rl._load_yaml_front(cf).get("current_status", "?")


def load_delta(project, delta_key):
    df = rl._delta_file(Path(project), delta_key)
    if df and df.exists():
        try:
            return json.loads(df.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def assemble_context(project, cand, node):
    r = _ctl("assemble-context", project, cand, "--node", node)
    manifest = None
    for line in r.stderr.splitlines():
        if "context manifest:" in line:
            manifest = line.split("context manifest:", 1)[1].strip()
    return r.stdout, manifest


def emit_delta(project, cand, node, persona, delta, run_dir, receipt=None):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / f"{node}_{persona}_emit.json"
    tmp.write_text(json.dumps(delta, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    args = ["emit-delta", project, cand, "--node", node, "--persona", persona,
            "--file", str(tmp)]
    if receipt:
        args += ["--receipt", receipt]
    r = _ctl(*args)
    if r.returncode != 0:
        log(f"emit-delta {node} failed: {r.stdout.strip()} {r.stderr.strip()}")
    return r.returncode == 0


def advance(project, cand, step):
    ac = step.get("advance_command")
    if ac == "decision":
        _ctl("decision", project, cand, "--status", step.get("advance_status"),
             "--reason", step.get("advance_reason") or "auto")
    elif ac == "triage-idea":
        d = load_delta(project, "L3_oppenheimer") or {}
        dec = "select" if d.get("selected") else "reject"
        _ctl("triage-idea", project, cand, "--decision", dec,
             "--reason", d.get("reason") or "auto")
    elif ac == "triage-method":
        d = load_delta(project, "L6_oppenheimer") or {}
        dec = "approve" if d.get("approved_strategy") else "reject"
        _ctl("triage-method", project, cand, "--decision", dec,
             "--reason", d.get("reason") or "auto")
    elif ac == "execution-gate":
        _ctl("execution-gate", project, cand)
    elif ac == "aggregate-report":
        _ctl("aggregate-report", project, cand)


def provider_for(node, cfg, args):
    return orch.make_provider(cfg.for_node(node), override_type=args.provider)


def write_receipt(run_dir, node, persona, prov, context, step, cand, round_id,
                  workspace=None):
    rec = orch.RunReceipt(
        node=node, persona=persona,
        provider=getattr(prov, "name", getattr(prov, "type", "?")),
        timestamp=orch.now(),
        context_hash=hashlib.sha256(context.encode("utf-8")).hexdigest(),
        prompt_file=getattr(prov, "last_prompt_file", None),
        delta_file=getattr(prov, "last_delta_file", None),
        workspace=workspace,
        allowed_tools=([step.get("tools_policy")] if step.get("tools_policy")
                       else None),
        everos_scope=step.get("everos_read_scopes"),
        candidate_id=cand, round_id=round_id)
    rec.write(Path(run_dir) / f"{node}_{persona}_receipt.json")


# --- node execution ---------------------------------------------------------

def exec_cognitive(project, cand, step, cfg, args, run_dir, round_id,
                   do_advance=True):
    node, persona = step["node"], step["persona"]
    ctx, manifest = assemble_context(project, cand, node)
    prov = provider_for(node, cfg, args)
    schema = rl.DELTA_SCHEMAS.get(f"{node}_{persona.lower()}")
    delta = prov.run_agent(node, persona, ctx, output_schema=schema,
                           tools=step.get("tools_policy"), run_dir=str(run_dir))
    ok = emit_delta(project, cand, node, persona, delta, run_dir, receipt=manifest)
    write_receipt(run_dir, node, persona, prov, ctx, step, cand, round_id)
    if ok and do_advance:
        advance(project, cand, step)
    return ok


def exec_turing(project, cand, step, cfg, args, run_dir, round_id, exec_state):
    if status_of(project, cand) == "METHOD_APPROVED":
        r = _ctl("execution-gate", project, cand)
        if r.returncode != 0:
            log(f"execution-gate rejected: {r.stdout.strip()}")
            return False
    r = _ctl("prepare-turing-workspace", project, cand, "--clean")
    workspace = None
    for line in r.stdout.splitlines():
        if "Turing workspace ready:" in line:
            workspace = line.split("ready:", 1)[1].strip()
    ctx, manifest = assemble_context(project, cand, "L7")
    prov = provider_for("L7", cfg, args)
    schema = rl.DELTA_SCHEMAS.get("L7_turing")
    try:
        delta = prov.run_agent("L7", "Turing", ctx, output_schema=schema,
                               workspace=workspace,
                               tools=step.get("tools_policy") or "workspace-fs",
                               run_dir=str(run_dir))
    except Exception as e:
        exec_state["l7_failures"] += 1
        log(f"L7 provider failed ({e}); failures={exec_state['l7_failures']}")
        return False
    ok = emit_delta(project, cand, "L7", "Turing", delta, run_dir, receipt=manifest)
    write_receipt(run_dir, "L7", "Turing", prov, ctx, step, cand, round_id,
                  workspace=workspace)
    if not ok:
        exec_state["l7_failures"] += 1
        log(f"L7 emit failed; failures={exec_state['l7_failures']}")
        return False
    _ctl("decision", project, cand, "--status", "EXECUTED",
         "--reason", "Turing execution complete")
    return True


def run_round(project, cand, cfg, args, round_id, max_rounds, exec_state):
    """Drive one full DAG pass for a candidate. Returns an outcome string."""
    run_dir = Path(project) / "08_Run_Receipts" / cand / f"round_{round_id:02d}"
    max_l7 = int(cfg.stop_policy.get("max_l7_failures", 2))
    while True:
        step = next_step(project, cand)
        if step.get("terminal"):
            log(f"terminal status: {step.get('status')}")
            return "terminal"
        if step.get("is_parallel"):
            for sub in step["nodes"]:
                log(f"node {sub['node']} ({sub['persona']}) [parallel]")
                exec_cognitive(project, cand, sub, cfg, args, run_dir, round_id,
                               do_advance=False)
            continue
        node = step["node"]
        if args.stop_after_node and node == args.stop_after_node:
            log(f"--stop-after-node {node}: halting round")
            return "stopped_after_node"
        if node == "L10c":
            _ctl("aggregate-report", project, cand)
            log("L10c: aggregate-report generated FINAL_REPORT")
            return "completed"
        if node == "L7":
            log("node L7 (Turing) [execution / Path A]")
            if not exec_turing(project, cand, step, cfg, args, run_dir,
                               round_id, exec_state):
                if exec_state["l7_failures"] >= max_l7:
                    log(f"L7 failed {exec_state['l7_failures']}x — aborting round")
                    return "l7_failed"
            continue
        log(f"node {node} ({step['persona']}) advance={step.get('advance_command')}")
        exec_cognitive(project, cand, step, cfg, args, run_dir, round_id)


# --- review gate ------------------------------------------------------------

def run_review_gate(project, cand, cfg, args, run_dir):
    rep = Path(project) / "FINAL_REPORT.md"
    if not rep.exists():
        log("review gate skipped (no FINAL_REPORT.md)")
        return None
    parts = ["=== FINAL_REPORT.md ===", rep.read_text(encoding="utf-8")]
    cn = Path(project) / "FINAL_REPORT_CN.md"
    if cn.exists():
        parts += ["=== FINAL_REPORT_CN.md ===", cn.read_text(encoding="utf-8")]
    for dk in ("L8_curie", "L9a_feynman", "L9b_darwin", "L10b_oppenheimer"):
        d = load_delta(project, dk)
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


# --- stop policy ------------------------------------------------------------

class StopPolicy:
    """Hybrid stop rule. The driving question is not 'are there issues' but
    'would another round plausibly change the conclusion'."""

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

        # ---- STOP conditions (take precedence) ----
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

        # ---- CONTINUE conditions ----
        executable = self._executable(next_steps, review)
        cont = (decision == "REVISE"
                or review_verdict == "major_revision"
                or executable)
        if cont and round_id < self.max_rounds:
            return self._continue(l10b, review, parent_fm)

        # ---- conservative default: stop ----
        if status == "KEEP":
            return self._stop("KEEP (no review verdict; nothing to continue on)")
        return self._stop("no continue condition met (default stop)")


def evidence_sig(project, cand):
    l8 = load_delta(project, "L8_curie") or {}
    l9a = load_delta(project, "L9a_feynman") or {}
    basis = json.dumps({"lvl": l8.get("evidence_level"),
                        "ev": l8.get("evidence_verified"),
                        "surv": l9a.get("survives"),
                        "fals": l9a.get("falsified")},
                       sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


# --- next-round child candidate ---------------------------------------------

def create_child(project, parent_cand, decision, new_round):
    parent_fm = rl._load_yaml_front(rl._candidate_file(Path(project), parent_cand))
    src = (f"Round {new_round - 1} FINAL_REPORT.md + key deltas "
           f"(L8/L9a/L9b/L10b) of {parent_cand}")
    r = _ctl("new-candidate", project,
             "--title", decision["new_candidate_title"] or "revised candidate",
             "--question", decision["new_candidate_question"]
             or parent_fm.get("question", ""),
             "--claim", decision["new_candidate_claim"] or "revised claim",
             "--input", src)
    child = r.stdout.split()[0] if r.stdout.strip() else None
    if not child:
        raise RuntimeError(f"new-candidate failed: {r.stdout} {r.stderr}")
    cf = rl._candidate_file(Path(project), child)
    rl._replace_field(cf, "parent_candidate_id", parent_cand)
    rl._replace_field(cf, "round_id", str(new_round))
    return child


# --- dry run ----------------------------------------------------------------

def _plan_line(nid, cfg, is_l10c=False):
    ni = rl.NODE_MAP[nid]
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
    key = "L9_parallel" if start in ("L9a", "L9b") else start
    seq = rl.DAG_SEQUENCE
    i = seq.index(key) if key in seq else 0
    log(f"current status={status_of(project, cand)}  next node={start}")
    print("planned nodes this round:")
    for nid in seq[i:]:
        if nid == "L9_parallel":
            for sub in ("L9a", "L9b"):
                print(_plan_line(sub, cfg))
        elif nid == "L10c":
            print(_plan_line(nid, cfg, is_l10c=True))
        else:
            print(_plan_line(nid, cfg))
    print()
    tail = "review gate -> " if review_on else ""
    log(f"after L10c: {tail}StopPolicy(max_rounds={max_rounds}) decides stop/continue")
    log("dry-run complete (one round planned; loop is bounded by max_rounds)")
    return 0


# --- main run ---------------------------------------------------------------

def cmd_run(args):
    project, cand = args.project_dir, args.cand_id
    if not rl._candidate_file(Path(project), cand).exists() \
            and not (Path(project) / "99_Archive" / f"{cand}.md").exists():
        log(f"ERROR: no candidate {cand} in {project}")
        return 2

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
        exec_state = {"l7_failures": 0}
        outcome = run_round(project, cur, cfg, args, round_id, max_rounds,
                            exec_state)
        if outcome == "stopped_after_node":
            log("halted per --stop-after-node (no stop decision taken)")
            return 0

        run_dir = Path(project) / "08_Run_Receipts" / cur / f"round_{round_id:02d}"
        review = None
        if not args.no_review and cfg.review.get("enabled", True):
            review = run_review_gate(project, cur, cfg, args, run_dir)

        st = status_of(project, cur)
        l10b = load_delta(project, "L10b_oppenheimer")
        summaries.append({"round": round_id, "candidate": cur, "status": st,
                          "evidence_sig": evidence_sig(project, cur),
                          "review_verdict": (review or {}).get("review_verdict")})
        parent_fm = rl._load_yaml_front(rl._candidate_file(Path(project), cur))
        decision = sp.decide(status=st, l10b=l10b, review=review,
                             round_id=round_id, prev_summaries=summaries,
                             l7_failures=exec_state["l7_failures"],
                             parent_fm=parent_fm)
        (run_dir).mkdir(parents=True, exist_ok=True)
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


def build_parser():
    p = argparse.ArgumentParser(
        prog="run_loop.py",
        description="RLR v0.3 loop runner (provider-neutral; StopPolicy-bounded).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("run", help="run the loop for a candidate")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--config", help="runner config (default: PROJECT_DIR/rlr_runner.yaml)")
    sp.add_argument("--max-rounds", dest="max_rounds", type=int, default=None)
    sp.add_argument("--provider", choices=["manual", "command"], default=None,
                    help="force a provider type for all nodes")
    sp.add_argument("--dry-run", action="store_true",
                    help="print the plan; no model calls, no state changes")
    sp.add_argument("--stop-after-node", dest="stop_after_node",
                    help="halt the round after this node (e.g. L3)")
    sp.add_argument("--no-review", action="store_true",
                    help="skip the Review gate")
    sp.add_argument("--resume", action="store_true",
                    help="resume from the candidate's recorded round_id")
    sp.set_defaults(func=cmd_run)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
