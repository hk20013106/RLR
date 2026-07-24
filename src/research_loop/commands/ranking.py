"""Ranking CLI command family (extracted from engine.py)."""

import json
import os
import re
import sys
import tempfile
from pathlib import Path

from research_loop import ranking
from research_loop.common import _stamp
from research_loop.delta import _delta_for_candidate
from research_loop.hypothesis_ledger import HypothesisLedger, LedgerError
from research_loop.paths import _candidate_file, _sha256
from research_loop.providers import ProviderConfig, ProviderError, make_provider


def _ledger_for(project_dir, configured_path=None, *, require_binding=True):
    """Construct the configured ledger without permitting a silent fallback."""
    store_path = configured_path or os.environ.get("RLR_HYPOTHESIS_STORE")
    if not store_path:
        raise LedgerError("hypothesis ledger requires --knowledge-store or RLR_HYPOTHESIS_STORE")
    if require_binding and not Path(store_path).is_file():
        raise LedgerError(f"configured hypothesis ledger does not exist: {store_path}")
    ledger = HypothesisLedger(store_path)
    if require_binding:
        ledger.require_activated_project(project_dir)
    return ledger


def _read_ranking_delta(project_dir, delta_key, cand_id):
    """Read one candidate-owned delta for advisory ranking input only."""
    path = _delta_for_candidate(project_dir, delta_key, cand_id)
    if path is None:
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), path
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {delta_key} for {cand_id}: {exc}") from exc


def _ranking_candidates(project_dir, candidate_ids):
    """Resolve immutable L1 hypothesis snapshots; never inspect candidate bodies."""
    snapshots = []
    for cand_id in candidate_ids:
        if not _candidate_file(project_dir, cand_id).is_file():
            raise ValueError(f"candidate not found: {cand_id}")
        delta, path = _read_ranking_delta(project_dir, "L1_einstein", cand_id)
        if not isinstance(delta, dict) or path is None:
            raise ValueError(f"candidate {cand_id} has no owned L1 Einstein delta")
        hypotheses = delta.get("hypotheses")
        if not isinstance(hypotheses, list) or not hypotheses:
            raise ValueError(f"candidate {cand_id} L1 delta has no hypotheses")
        primary = delta.get("primary_hypothesis")
        selected = next((item for item in hypotheses
                         if isinstance(item, dict) and item.get("text") == primary), None)
        selected = selected or next((item for item in hypotheses
                                     if isinstance(item, dict) and item.get("text")), None)
        if not selected:
            raise ValueError(f"candidate {cand_id} L1 delta has no usable hypothesis")
        snapshots.append(ranking.hypothesis_candidate(
            cand_id, selected["text"], source_delta_hash=_sha256(path),
            source_delta=delta, hypothesis_id=selected.get("id") or cand_id))
    return snapshots


def _ranking_formal_decisions(project_dir, stage, snapshots):
    """Return read-only formal-decision references for the shadow report."""
    decisions = []
    key = "L3_oppenheimer" if stage == "L3" else "L10b_oppenheimer"
    for snapshot in snapshots:
        cand_id, hypothesis_id = snapshot["candidate_id"], snapshot["hypothesis_id"]
        delta, path = _read_ranking_delta(project_dir, key, cand_id)
        value = "UNAVAILABLE"
        if isinstance(delta, dict):
            if stage == "L10b":
                value = str(delta.get("decision") or "UNAVAILABLE")
            else:
                selected = {str(item) for item in delta.get("selected", [])}
                rejected = {str(item) for item in delta.get("rejected", [])}
                identifiers = {cand_id, hypothesis_id}
                if identifiers & selected:
                    value = "SELECTED"
                elif identifiers & rejected:
                    value = "REJECTED"
                else:
                    value = "UNSPECIFIED"
        decisions.append({"candidate_id": cand_id, "hypothesis_id": hypothesis_id,
                          "formal_decision": value,
                          "source_delta": str(path) if path else None,
                          "source_delta_hash": _sha256(path) if path else None})
    return decisions


def _ranking_advisory_records(artifact, formal_decisions, stage):
    """Attach advisory-only formal/shadow comparisons, preserving unavailable input."""
    directions = ({"SELECTED": "HIGHER", "REJECTED": "LOWER"}
                  if stage == "L3" else
                  {"KEEP": "HIGHER", "REVISE": "HIGHER",
                   "DOWNGRADE": "LOWER", "DROP": "LOWER"})
    comparable, unavailable = [], []
    for formal in formal_decisions:
        record = dict(formal)
        direction = directions.get(str(record["formal_decision"]).upper())
        if direction:
            record["formal_direction"] = direction
            comparable.append(record)
        else:
            unavailable.append({
                "candidate_id": record["candidate_id"],
                "hypothesis_id": record["hypothesis_id"],
                "formal_decision": record["formal_decision"],
                "formal_direction": "UNAVAILABLE",
                "shadow_rank": None,
                "shadow_uncertainty": None,
                "shadow_signal": "UNAVAILABLE",
                "comparison_status": "UNAVAILABLE",
            })
    records = ranking.attach_advisory_comparisons(artifact, comparable)
    artifact["advisory_comparisons"] = records + unavailable
    return artifact["advisory_comparisons"]


def _validate_ranking_resume_provenance(checkpoint, stage, judge_mode):
    """Fail closed before provider calls when a resume changes immutable provenance."""
    provenance = checkpoint.get("provenance") if isinstance(checkpoint, dict) else None
    if not isinstance(provenance, dict):
        raise ValueError("checkpoint is missing immutable ranking provenance")
    if provenance.get("stage") != stage:
        raise ValueError("checkpoint stage differs from requested stage")
    if provenance.get("judge_mode") != judge_mode:
        raise ValueError("checkpoint judge mode differs from requested judge mode")


def _resolve_ranking_judge(args, audit_run_dir=None):
    engine_mod = sys.modules.get("research_loop.engine")
    if engine_mod and hasattr(engine_mod, "_ranking_judge"):
        engine_judge = getattr(engine_mod, "_ranking_judge")
        if engine_judge is not _ranking_judge:
            return engine_judge(args, audit_run_dir)
    return _ranking_judge(args, audit_run_dir)


def _ranking_judge(args, audit_run_dir=None):
    if args.judge == "fake":
        return ranking.DeterministicFakeJudge()
    if audit_run_dir is None:
        raise ValueError("provider ranking requires an isolated audit run directory")
    try:
        config = ProviderConfig.load(args.config)
        return ranking.ProviderJudge(make_provider(config.for_node("RANKING")), audit_run_dir)
    except (OSError, ProviderError, ValueError) as exc:
        raise ValueError(f"cannot configure ranking provider: {exc}") from exc


def _ranking_events(paths):
    events = []
    for raw_path in paths or []:
        path = Path(raw_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read evidence file {path}: {exc}") from exc
        if isinstance(payload, dict):
            payload = payload["evidence_events"] if "evidence_events" in payload else [payload]
        if not isinstance(payload, list):
            raise ValueError(f"evidence file {path} must contain an event or event list")
        if any(not isinstance(event, dict) for event in payload):
            raise ValueError(f"evidence file {path} contains a non-object event")
        events.extend(payload)
    return events


def _ranking_output_targets(project_dir, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", run_id):
        raise ValueError("run_id must be a safe filename token")
    base = Path(project_dir) / "08_Audit" / "ranking"
    targets = (base / f"{run_id}.json", base / f"{run_id}.checkpoint.json",
               base / f"{run_id}.md", base / f"{run_id}.complete.json")
    collision = next((path for path in targets if path.exists()), None)
    if collision:
        raise ValueError(f"ranking output collision: {collision}")
    return targets


def _write_ranking_complete_marker(project_dir, run_id, stage, judge_mode, paths):
    """Atomically publish a no-clobber completion marker after all outputs exist."""
    artifact_path, checkpoint_path, report_path = (Path(path) for path in paths)
    target = Path(project_dir) / "08_Audit" / "ranking" / f"{run_id}.complete.json"
    payload = {
        "schema_version": ranking.SCHEMA_VERSION,
        "run_id": run_id,
        "stage": stage,
        "judge_mode": judge_mode,
        "sha256": {
            "artifact": _sha256(artifact_path),
            "checkpoint": _sha256(checkpoint_path),
            "report": _sha256(report_path),
        },
    }
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{run_id}.complete-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
        os.unlink(temporary)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(target)


def _ranking_write_outputs(project_dir, artifact, run_id, stage, judge_mode):
    """Persist immutable run/checkpoint/report files in the isolated audit area."""
    artifact["run_id"] = run_id
    artifact_path = ranking.write_ranking_artifact(project_dir, artifact, run_id)
    checkpoint_path = ranking.write_checkpoint(project_dir, artifact, run_id)
    report_path = Path(project_dir) / "08_Audit" / "ranking" / f"{run_id}.md"
    with report_path.open("x", encoding="utf-8") as handle:
        handle.write(ranking.render_markdown_report(artifact))
    complete_marker = _write_ranking_complete_marker(
        project_dir, run_id, stage, judge_mode,
        (artifact_path, checkpoint_path, report_path))
    return artifact_path, checkpoint_path, str(report_path), complete_marker


def cmd_ranking_shadow(args):
    """Run an advisory ranking without mutating candidates, deltas, or gates."""
    project_dir = Path(args.project_dir)
    if not (project_dir / "00_Project_Index.md").is_file():
        print(f"ERROR: not a project dir (no 00_Project_Index.md): {project_dir}",
              file=sys.stderr)
        return 2
    if len(args.candidates) < 2 or len(set(args.candidates)) != len(args.candidates):
        print("ERROR: provide at least two distinct --candidate values", file=sys.stderr)
        return 2
    try:
        checkpoint = ranking.load_checkpoint(args.resume) if args.resume else None
        if checkpoint is not None and not isinstance(checkpoint, dict):
            raise ValueError("checkpoint must be a JSON object")
        if checkpoint is not None:
            _validate_ranking_resume_provenance(checkpoint, args.stage, args.judge)
        run_id = args.run_id or (
            f"{checkpoint.get('run_id')}-resume-{_stamp()}" if checkpoint else f"ranking-{_stamp()}")
        _ranking_output_targets(project_dir, run_id)
        if args.match_budget < 0:
            raise ValueError("match budget must be non-negative")
        if args.token_budget is not None and args.token_budget < 0:
            raise ValueError("token budget must be non-negative")
        if args.cost_budget is not None and args.cost_budget < 0:
            raise ValueError("cost budget must be non-negative")
        events = _ranking_events(args.evidence)
        ledger = _ledger_for(project_dir, args.knowledge_store)
        binding = ledger.require_activated_project(project_dir)
        ranking_dto = ledger.ranking_inputs(
            args.candidates, args.stage, project_id=binding["project_id"]
        )
        snapshots = [ranking.hypothesis_candidate(
            item["candidate_id"], item["statement"],
            source_delta_hash=item["source_emission"]["delta_hash"],
            source_delta=item, hypothesis_id=item["hypothesis_id"],
        ) for item in ranking_dto["candidates"]]
        provenance = {
            "mode": "shadow", "stage": args.stage, "formal_decisions":
                ranking_dto["formal_decisions"],
            "ledger_as_of_commit_seq": ranking_dto["as_of_commit_seq"],
            "judge_mode": args.judge,
            "resumed_from": str(args.resume) if args.resume else None,
        }
        provider_run_dir = (project_dir / "08_Audit" / "ranking" /
                            f"{run_id}.provider")
        judge_instance = _resolve_ranking_judge(args, provider_run_dir)
        artifact = ranking.run_elo_ranking(
            snapshots, judge=judge_instance, seed=args.seed,
            match_budget=args.match_budget, checkpoint=checkpoint, run_id=run_id,
            provenance=provenance)
        artifact["run_id"] = run_id
        artifact.setdefault("provenance", {}).update(provenance)
        artifact["budget"].update({
            "logical_matches": len(artifact["pairwise_judgments"]),
            "raw_judge_calls": len(artifact["pairwise_judgments"]) * 2,
            "tokens": args.token_budget if args.token_budget is not None else
                      (0 if args.judge == "fake" else None),
            "cost": args.cost_budget if args.cost_budget is not None else
                    (0 if args.judge == "fake" else None),
            "token_budget_policy": "declared-only/not-enforced",
            "cost_budget_policy": "declared-only/not-enforced",
        })
        _ranking_advisory_records(artifact, artifact["provenance"]["formal_decisions"],
                                  args.stage)
        for event in events:
            ranking.apply_evidence_event(artifact, event)
        paths = _ranking_write_outputs(project_dir, artifact, run_id, args.stage, args.judge)
    except (OSError, ValueError, ProviderError) as exc:
        print(f"ERROR: ranking shadow failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"run_id": run_id, "artifact": paths[0], "checkpoint": paths[1],
                      "report": paths[2], "complete_marker": paths[3],
                      "ranking_results": artifact["ranking_results"],
                      "formal_decisions": artifact["provenance"]["formal_decisions"],
                      "budget": artifact["budget"]},
                     ensure_ascii=False))
    return 0


class _SyntheticPositionBiasedJudge:
    """Free deterministic benchmark judge with deliberately measurable order bias."""
    provider_name = "synthetic-position-biased"
    model_name = "synthetic-v1"

    def __init__(self, gold_ranks, seed):
        self.gold_ranks = gold_ranks
        self.seed = int(seed)

    def compare(self, left, right):
        marker = f"{self.seed}:{left['candidate_id']}:{right['candidate_id']}"
        biased = (self.gold_ranks[left["candidate_id"]] > self.gold_ranks[right["candidate_id"]]
                  or sum(marker.encode("utf-8")) % 2 == 0)
        if biased:
            return {"verdict": "A", "reason": "synthetic first-position bias"}
        winner = ("A" if self.gold_ranks[left["candidate_id"]]
                  < self.gold_ranks[right["candidate_id"]] else "B")
        return {"verdict": winner, "reason": "synthetic gold comparison"}


def _ranking_accuracy(judgments, gold_ranks):
    valid = [pair for pair in judgments if pair.get("final_verdict") == "WIN"]
    correct = sum(gold_ranks[pair["winner_id"]] == min(
        gold_ranks[candidate_id] for candidate_id in pair["candidate_ids"])
        for pair in valid)
    return correct / len(valid) if valid else 0.0


def _naive_benchmark(gold_ranks, candidates, seed, match_budget):
    """Single-order control: same synthetic judge, intentionally no flip check."""
    judge = _SyntheticPositionBiasedJudge(gold_ranks, seed)
    wins = {candidate["candidate_id"]: 0 for candidate in candidates}
    outcomes = []
    for ordinal in range(match_budget):
        left = candidates[ordinal % len(candidates)]
        right = candidates[(ordinal + 1) % len(candidates)]
        result = judge.compare(left, right)
        winner = left["candidate_id"] if result["verdict"] == "A" else right["candidate_id"]
        wins[winner] += 1
        outcomes.append((left["candidate_id"], right["candidate_id"], winner, result["verdict"]))
    ranking_ids = sorted(wins, key=lambda candidate_id: (-wins[candidate_id], candidate_id))
    accuracy = sum(gold_ranks[winner] == min(gold_ranks[left], gold_ranks[right])
                   for left, right, winner, _ in outcomes) / len(outcomes) if outcomes else 0.0
    losing_first = [outcome for outcome in outcomes if gold_ranks[outcome[0]] > gold_ranks[outcome[1]]]
    false_first_win_rate = (sum(winner == left for left, _, winner, _ in losing_first) /
                            len(losing_first) if losing_first else 0.0)
    return {"ranking_ids": ranking_ids, "pairwise_accuracy": accuracy,
            "false_first_win_rate": false_first_win_rate, "self_consistency": 1.0,
            "uncertain_rate": 0.0, "matches": len(outcomes)}


def _average(values):
    return sum(values) / len(values) if values else 0.0


def _fair_false_first_win_rate(judgments, gold_ranks):
    losing_first = [pair for pair in judgments
                    if gold_ranks[pair["candidate_ids"][0]] > gold_ranks[pair["candidate_ids"][1]]]
    return (sum(pair["final_verdict"] == "WIN" and pair["winner_id"] == pair["candidate_ids"][0]
                for pair in losing_first) / len(losing_first) if losing_first else 0.0)


def _load_benchmark_gold(path):
    gold = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(gold, dict) or gold.get("schema_version") != ranking.SCHEMA_VERSION:
        raise ValueError("gold file requires the supported schema_version")
    candidates = gold.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise ValueError("gold file requires at least two candidates")
    for item in candidates:
        if not isinstance(item, dict):
            raise ValueError("gold candidates must be objects")
        for key in ("candidate_id", "hypothesis_id", "hypothesis", "gold_rank"):
            if key not in item or not item[key]:
                raise ValueError(f"gold candidate missing {key}")
        if not isinstance(item["gold_rank"], int) or isinstance(item["gold_rank"], bool):
            raise ValueError("gold_rank must be an integer")
    gold_ranks = {item["candidate_id"]: item["gold_rank"] for item in candidates}
    if len(gold_ranks) != len(candidates) or len(set(gold_ranks.values())) != len(candidates):
        raise ValueError("gold candidate IDs and gold ranks must be unique")
    return candidates, gold_ranks


def cmd_ranking_benchmark(args):
    """Evaluate fair flipping against a deterministic, synthetic biased control."""
    try:
        candidates, gold_ranks = _load_benchmark_gold(args.gold)
        snapshots = [ranking.hypothesis_candidate(
            item["candidate_id"], item.get("hypothesis", item["candidate_id"]),
            hypothesis_id=item.get("hypothesis_id") or item["candidate_id"])
            for item in candidates]
        seeds = [int(value.strip()) for value in args.seeds.split(",") if value.strip()]
        if not seeds:
            raise ValueError("--seeds must include at least one integer")
        fair_runs, naive_runs = [], []
        for seed in seeds:
            fair = ranking.run_elo_ranking(
                snapshots, judge=_SyntheticPositionBiasedJudge(gold_ranks, seed),
                seed=seed, match_budget=args.match_budget, run_id=f"benchmark-{seed}",
                provenance={"mode": "synthetic-benchmark"})
            fair_runs.append(fair)
            naive_runs.append(_naive_benchmark(gold_ranks, snapshots, seed, args.match_budget))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: ranking benchmark failed: {exc}", file=sys.stderr)
        return 2

    fair_orders = [[row["candidate_id"] for row in run["ranking_results"]] for run in fair_runs]
    naive_orders = [run["ranking_ids"] for run in naive_runs]
    def stability(orders):
        top_k = min(3, len(candidates))
        return _average([len(set(left[:top_k]) & set(right[:top_k])) / top_k
                         for left, right in zip(orders, orders[1:])]) if len(orders) > 1 else 1.0
    def churn(orders):
        return _average([sum(a != b for a, b in zip(left, right)) / len(left)
                         for left, right in zip(orders, orders[1:])]) if len(orders) > 1 else 0.0
    fair_uncertain = [_average([pair["final_verdict"] == "UNCERTAIN"
                                for pair in run["pairwise_judgments"]]) for run in fair_runs]
    metrics = {
        "pairwise_accuracy": {"fair": _average([_ranking_accuracy(run["pairwise_judgments"], gold_ranks)
                                                   for run in fair_runs]),
                              "naive": _average([run["pairwise_accuracy"] for run in naive_runs])},
        "position_bias": {
            "fair_false_first_win_rate": _average([
                _fair_false_first_win_rate(run["pairwise_judgments"], gold_ranks) for run in fair_runs]),
            "naive_false_first_win_rate": _average([run["false_first_win_rate"] for run in naive_runs]),
        },
        "self_consistency": {"fair": _average([1.0 - value for value in fair_uncertain]),
                             "naive": _average([run["self_consistency"] for run in naive_runs])},
        "top_k_stability": {"fair": stability(fair_orders), "naive": stability(naive_orders)},
        "ranking_churn": {"fair": churn(fair_orders), "naive": churn(naive_orders)},
        "uncertain_rate": {"fair": _average(fair_uncertain),
                           "naive": _average([run["uncertain_rate"] for run in naive_runs])},
        "budget": {"match_budget": args.match_budget,
                   "fair_logical_matches": sum(len(run["pairwise_judgments"]) for run in fair_runs),
                   "naive_logical_matches": sum(run["matches"] for run in naive_runs),
                   "fair_raw_judge_calls": sum(len(run["pairwise_judgments"]) * 2 for run in fair_runs),
                   "naive_raw_judge_calls": sum(run["matches"] for run in naive_runs),
                   "tokens": 0, "cost": 0},
    }
    result = {"schema_version": ranking.SCHEMA_VERSION, "mode": "synthetic-benchmark",
              "seeds": seeds, "metrics": metrics,
              "disclaimer": "Synthetic position-biased fixture validates the ranking framework; it is not scientific performance evidence."}
    if args.output:
        path = Path(args.output)
        if path.exists():
            print(f"ERROR: benchmark output already exists: {path}", file=sys.stderr)
            return 2
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        result["output"] = str(path)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _validate_ranking_report_artifact(artifact):
    if not isinstance(artifact, dict) or artifact.get("schema_version") != ranking.SCHEMA_VERSION:
        raise ValueError("artifact has unsupported schema_version")
    required = {"run_id": str, "scheduler": dict, "pairwise_judgments": list,
                "ranking_results": list, "evidence_events": list, "failures": list}
    for key, expected_type in required.items():
        if not isinstance(artifact.get(key), expected_type):
            raise ValueError(f"artifact missing valid {key}")
    if not all(key in artifact["scheduler"] for key in ("seed", "match_budget")):
        raise ValueError("artifact scheduler is incomplete")
    for row in artifact["ranking_results"]:
        if not isinstance(row, dict) or not all(key in row for key in
                                                ("rank", "candidate_id", "score", "matches", "uncertainty")):
            raise ValueError("artifact ranking result is malformed")


def cmd_ranking_report(args):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.run_id):
        print("ERROR: --run must be a safe run ID", file=sys.stderr)
        return 2
    path = Path(args.project_dir) / "08_Audit" / "ranking" / f"{args.run_id}.json"
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        _validate_ranking_report_artifact(artifact)
        rendered = ranking.render_markdown_report(artifact) if args.format == "markdown" else None
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: cannot read ranking artifact {path}: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(artifact, ensure_ascii=False))
    else:
        print(rendered, end="")
    return 0
