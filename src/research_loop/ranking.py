"""Versioned, fail-closed shadow hypothesis ranking primitives.

This stdlib-only module deliberately has no engine or runner dependency: callers
may persist its artifacts independently from an RLR formal decision.
"""
import hashlib
import json
import random
import re
from copy import deepcopy
from pathlib import Path


SCHEMA_VERSION = "1.0"
INITIAL_ELO = 1000.0
ELO_K = 32.0
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def prompt_hash(payload):
    """Return the canonical SHA-256 digest for a stored pairwise prompt payload."""
    return _hash(payload)


def hypothesis_candidate(candidate_id, hypothesis, source_delta_hash=None,
                         source_delta=None, hypothesis_id=None):
    """Create a serializable, immutable-by-convention hypothesis snapshot."""
    if not str(candidate_id).strip() or not str(hypothesis).strip():
        raise ValueError("candidate_id and hypothesis are required")
    hypothesis_id = candidate_id if hypothesis_id is None else hypothesis_id
    if not str(hypothesis_id).strip():
        raise ValueError("hypothesis_id is required")
    return {"candidate_id": str(candidate_id), "hypothesis_id": str(hypothesis_id),
            "hypothesis": str(hypothesis),
            "source_delta_hash": source_delta_hash, "source_delta": source_delta}


class DeterministicFakeJudge:
    """Free default judge whose stable lexical verdict makes tests/network-free runs reproducible."""
    provider_name = "deterministic-fake"
    model_name = "deterministic-fake-v1"

    def compare(self, left, right):
        return {"verdict": "A" if left["candidate_id"] < right["candidate_id"] else "B",
                "reason": "deterministic lexical fixture"}


class ProviderJudge:
    """Adapt an existing AgentProvider-compatible instance to pairwise ranking."""
    def __init__(self, provider, run_dir):
        if run_dir is None:
            raise ValueError("ProviderJudge requires an audit run_dir")
        self.provider = provider
        self.run_dir = Path(run_dir)
        self._call_count = 0
        self.last_call_record = None
        self.provider_name = getattr(provider, "name", None) or getattr(provider, "type", "provider")
        self.model_name = getattr(provider, "model", None) or getattr(provider, "model_name", None) or "unspecified"

    def compare(self, left, right, payload=None):
        """Ask the configured provider for an A/B verdict using a structured schema."""
        payload = payload or pairwise_prompt_payload(left, right)
        self._call_count += 1
        child_run_dir = self.run_dir / ("pairwise_%04d" % self._call_count)
        result = self.provider.run_agent(
            "RANKING", "RankingJudge", _canonical(payload),
            output_schema={"verdict": str, "reason": str},
            run_dir=str(child_run_dir))
        self.last_call_record = {
            "provider_run_dir": str(child_run_dir),
            "provider_prompt_file": getattr(self.provider, "last_prompt_file", None),
            "provider_delta_file": getattr(self.provider, "last_delta_file", None),
        }
        if not isinstance(result, dict):
            raise ValueError("ranking provider returned non-object result")
        return result


def pairwise_prompt_payload(first, second):
    """Build the exact canonical structured prompt supplied to a provider judge."""
    def candidate(snapshot):
        return {key: snapshot.get(key) for key in
                ("candidate_id", "hypothesis_id", "hypothesis", "source_delta_hash")}
    return {
        "task": "shadow_pairwise_hypothesis_ranking",
        "instruction": "Choose the more scientifically supported hypothesis as A or B; do not use position as evidence.",
        "positions": {"A": candidate(first), "B": candidate(second)},
        "response_schema": {"verdict": "A|B", "reason": "concise explanation"},
    }


def _raw_result(result):
    if isinstance(result, str):
        result = {"verdict": result, "reason": ""}
    if not isinstance(result, dict):
        raise ValueError("judge result must be an object or verdict string")
    verdict = str(result.get("verdict", "")).strip().upper()
    aliases = {"LEFT": "A", "RIGHT": "B"}
    verdict = aliases.get(verdict, verdict)
    if verdict not in {"A", "B"}:
        raise ValueError("judge verdict must be A or B")
    return verdict, str(result.get("reason", "")).strip()


def _provider_meta(judge):
    return (getattr(judge, "provider_name", judge.__class__.__name__),
            getattr(judge, "model_name", "unspecified"))


def fair_pairwise_judge(left, right, judge=None, comparison_id=None):
    """Judge A/B then B/A; disagreement is preserved as ``UNCERTAIN``.

    The return value retains both raw position verdicts and never invents a
    winner where the two physical candidate winners differ.
    """
    judge = judge or DeterministicFakeJudge()
    orders = ((left, right), (right, left))
    raw = []
    physical_winners = []
    for first, second in orders:
        prompt = pairwise_prompt_payload(first, second)
        result = (judge.compare(first, second, prompt)
                  if isinstance(judge, ProviderJudge) else judge.compare(first, second))
        verdict, reason = _raw_result(result)
        winner = first["candidate_id"] if verdict == "A" else second["candidate_id"]
        entry = {"order": [first["candidate_id"], second["candidate_id"]],
                 "verdict": verdict, "reason": reason,
                 "prompt_payload": prompt, "prompt_hash": prompt_hash(prompt),
                 "winner_id": winner}
        if isinstance(judge, ProviderJudge):
            entry.update(judge.last_call_record)
        raw.append(entry)
        physical_winners.append(winner)
    provider, model = _provider_meta(judge)
    winner = physical_winners[0] if physical_winners[0] == physical_winners[1] else None
    return {
        "comparison_id": comparison_id,
        "candidate_ids": [left["candidate_id"], right["candidate_id"]],
        "comparison_order": [entry["order"] for entry in raw],
        "raw_verdicts": raw,
        "final_verdict": "WIN" if winner else "UNCERTAIN",
        "winner_id": winner,
        "provider": provider,
        "model": model,
        "prompt_hash": prompt_hash([entry["prompt_hash"] for entry in raw]),
    }


def new_ranking_artifact(candidates, seed, match_budget, run_id=None, provenance=None,
                         token_budget=None, cost_budget=None):
    """Create the versioned, independent shadow artifact before any matches."""
    snapshots = _normalized_snapshots(candidates)
    ids = [c["candidate_id"] for c in snapshots]
    if len(ids) != len(set(ids)):
        raise ValueError("candidate IDs must be unique")
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "provenance": dict(provenance or {}),
        "hypothesis_candidates": snapshots,
        "budget": {"matches": int(match_budget), "tokens": token_budget,
                   "cost": cost_budget},
        "scheduler": {"algorithm": "elo", "seed": int(seed),
                      "match_budget": int(match_budget), "initial_score": INITIAL_ELO,
                      "scores": {cid: INITIAL_ELO for cid in ids},
                      "match_counts": {cid: 0 for cid in ids}, "rng_state": None},
        "pairwise_judgments": [], "applied_comparison_ids": [],
        "ranking_results": [], "evidence_events": [], "advisory_comparisons": [],
        "checkpoint": {"status": "in_progress", "completed_matches": 0},
        "failures": [],
    }


def _normalized_snapshots(candidates):
    snapshots = []
    for candidate in candidates:
        snapshot = dict(candidate)
        snapshot.setdefault("hypothesis_id", snapshot.get("candidate_id"))
        snapshots.append(snapshot)
    snapshots.sort(key=lambda c: c["candidate_id"])
    return snapshots


def _validate_checkpoint(checkpoint, candidates, match_budget, seed):
    """Reject any checkpoint that cannot safely be resumed without replaying it."""
    if not isinstance(checkpoint, dict) or checkpoint.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("checkpoint schema version is unsupported")
    snapshots = _normalized_snapshots(candidates)
    if checkpoint.get("hypothesis_candidates") != snapshots:
        raise ValueError("checkpoint candidate snapshots differ from caller input")
    pairs = checkpoint.get("pairwise_judgments")
    applied = checkpoint.get("applied_comparison_ids")
    scheduler = checkpoint.get("scheduler")
    if not isinstance(pairs, list) or not isinstance(applied, list) or not isinstance(scheduler, dict):
        raise ValueError("checkpoint missing ranking state")
    if scheduler.get("seed") != int(seed):
        raise ValueError("checkpoint seed differs from requested seed")
    if any(not isinstance(cid, str) or not cid for cid in applied):
        raise ValueError("checkpoint has invalid applied comparison IDs")
    if len(applied) != len(set(applied)):
        raise ValueError("checkpoint has duplicate applied comparison IDs")
    ids = [pair.get("comparison_id") for pair in pairs if isinstance(pair, dict)]
    if len(ids) != len(pairs) or any(not cid for cid in ids) or ids != applied:
        raise ValueError("checkpoint applied comparison IDs do not match judgments")
    if len(pairs) > match_budget:
        raise ValueError("requested match budget is below completed matches")
    if checkpoint.get("checkpoint", {}).get("completed_matches") != len(pairs):
        raise ValueError("checkpoint completed match count is inconsistent")
    candidate_ids = {candidate["candidate_id"] for candidate in snapshots}
    scores, match_counts = scheduler.get("scores"), scheduler.get("match_counts")
    if (not isinstance(scores, dict) or not isinstance(match_counts, dict)
            or set(scores) != candidate_ids or set(match_counts) != candidate_ids):
        raise ValueError("checkpoint scheduler does not match candidates")
    for pair in pairs:
        _validate_judgment(pair, candidate_ids)
    replayed = _reconstruct_scheduler(snapshots, scheduler["seed"], pairs)
    if (scheduler["scores"] != replayed["scores"]
            or scheduler["match_counts"] != replayed["match_counts"]
            or _tuples(scheduler.get("rng_state")) != replayed["rng_state"]):
        raise ValueError("checkpoint scheduler state does not match stored judgments")


def _reconstruct_scheduler(snapshots, seed, judgments):
    """Replay only validated judgments to derive the one legitimate scheduler state."""
    replay = {
        "hypothesis_candidates": snapshots,
        "scheduler": {
            "scores": {candidate["candidate_id"]: INITIAL_ELO for candidate in snapshots},
            "match_counts": {candidate["candidate_id"]: 0 for candidate in snapshots},
        },
    }
    rng = random.Random(seed)
    for ordinal, pair in enumerate(judgments, 1):
        left, right = _choose_pair(replay, rng)
        expected_ids = [left["candidate_id"], right["candidate_id"]]
        expected_comparison_id = "cmp-%04d-%s-%s" % (ordinal, *expected_ids)
        if pair["candidate_ids"] != expected_ids or pair["comparison_id"] != expected_comparison_id:
            raise ValueError("checkpoint judgment does not match deterministic schedule")
        _apply_elo(replay, pair)
    return {
        "scores": replay["scheduler"]["scores"],
        "match_counts": replay["scheduler"]["match_counts"],
        "rng_state": rng.getstate() if judgments else None,
    }


def _validate_judgment(pair, candidate_ids):
    if not isinstance(pair, dict):
        raise ValueError("checkpoint judgment is not an object")
    candidate_pair = pair.get("candidate_ids")
    if (not isinstance(candidate_pair, list) or len(candidate_pair) != 2
            or len(set(candidate_pair)) != 2 or not set(candidate_pair) <= candidate_ids):
        raise ValueError("checkpoint judgment has invalid candidates")
    raw = pair.get("raw_verdicts")
    expected_orders = [candidate_pair, list(reversed(candidate_pair))]
    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError("checkpoint judgment must retain both raw verdicts")
    raw_winners = []
    for entry, order in zip(raw, expected_orders):
        if not isinstance(entry, dict):
            raise ValueError("checkpoint raw verdict is not an object")
        if entry.get("order") != order or entry.get("verdict") not in {"A", "B"}:
            raise ValueError("checkpoint judgment order or verdict is inconsistent")
        winner = order[0] if entry["verdict"] == "A" else order[1]
        if entry.get("winner_id") != winner:
            raise ValueError("checkpoint judgment raw winner is inconsistent")
        if entry.get("prompt_hash") != prompt_hash(entry.get("prompt_payload")):
            raise ValueError("checkpoint judgment prompt hash is inconsistent")
        raw_winners.append(winner)
    winner = raw_winners[0] if raw_winners[0] == raw_winners[1] else None
    if pair.get("comparison_order") != expected_orders:
        raise ValueError("checkpoint comparison order is inconsistent")
    if pair.get("final_verdict") != ("WIN" if winner else "UNCERTAIN") or pair.get("winner_id") != winner:
        raise ValueError("checkpoint final verdict is inconsistent")
    if pair.get("prompt_hash") != prompt_hash([entry["prompt_hash"] for entry in raw]):
        raise ValueError("checkpoint comparison prompt hash is inconsistent")


def _tuples(value):
    return tuple(_tuples(v) for v in value) if isinstance(value, list) else value


def _choose_pair(artifact, rng):
    candidates = artifact["hypothesis_candidates"]
    counts, scores = artifact["scheduler"]["match_counts"], artifact["scheduler"]["scores"]
    minimum = min(counts[c["candidate_id"]] for c in candidates)
    firsts = [c for c in candidates if counts[c["candidate_id"]] == minimum]
    first = firsts[rng.randrange(len(firsts))]
    others = [c for c in candidates if c["candidate_id"] != first["candidate_id"]]
    distance = min(abs(scores[first["candidate_id"]] - scores[c["candidate_id"]]) for c in others)
    seconds = [c for c in others if abs(scores[first["candidate_id"]] - scores[c["candidate_id"]]) == distance]
    return first, seconds[rng.randrange(len(seconds))]


def _apply_elo(artifact, pair):
    scores = artifact["scheduler"]["scores"]
    counts = artifact["scheduler"]["match_counts"]
    left, right = pair["candidate_ids"]
    counts[left] += 1
    counts[right] += 1
    if pair["final_verdict"] == "UNCERTAIN":
        return
    winner, loser = pair["winner_id"], right if pair["winner_id"] == left else left
    expected = 1.0 / (1.0 + 10.0 ** ((scores[loser] - scores[winner]) / 400.0))
    change = ELO_K * (1.0 - expected)
    scores[winner] = round(scores[winner] + change, 10)
    scores[loser] = round(scores[loser] - change, 10)


def _results(artifact):
    scores, counts = artifact["scheduler"]["scores"], artifact["scheduler"]["match_counts"]
    uncertainty = {cid: 0 for cid in scores}
    for pair in artifact["pairwise_judgments"]:
        if pair["final_verdict"] == "UNCERTAIN":
            for cid in pair["candidate_ids"]:
                uncertainty[cid] += 1
    ordered = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return [{"candidate_id": cid, "score": scores[cid], "rank": rank,
             "matches": counts[cid], "uncertainty": uncertainty[cid]}
            for rank, cid in enumerate(ordered, 1)]


def run_elo_ranking(candidates, judge=None, seed=0, match_budget=0,
                    checkpoint=None, run_id=None, provenance=None):
    """Run or resume fixed-budget seeded Elo, returning a complete artifact.

    A checkpoint is a prior artifact. Its saved RNG state and applied IDs make
    resume observationally equivalent to executing the same run in one pass.
    """
    if match_budget < 0:
        raise ValueError("match_budget must be non-negative")
    if checkpoint is not None:
        _validate_checkpoint(checkpoint, candidates, match_budget, seed)
        artifact = deepcopy(checkpoint)
    else:
        artifact = new_ranking_artifact(candidates, seed, match_budget, run_id, provenance)
    scheduler = artifact["scheduler"]
    if int(scheduler["seed"]) != int(seed):
        raise ValueError("checkpoint seed differs from requested seed")
    if len(artifact["hypothesis_candidates"]) < 2 and match_budget:
        raise ValueError("at least two candidates are required for matches")
    rng = random.Random()
    rng.setstate(_tuples(scheduler["rng_state"])) if scheduler["rng_state"] else rng.seed(seed)
    judge = judge or DeterministicFakeJudge()
    while len(artifact["pairwise_judgments"]) < match_budget:
        left, right = _choose_pair(artifact, rng)
        ordinal = len(artifact["pairwise_judgments"]) + 1
        comparison_id = "cmp-%04d-%s-%s" % (ordinal, left["candidate_id"], right["candidate_id"])
        if comparison_id in artifact["applied_comparison_ids"]:
            raise ValueError("duplicate comparison ID in checkpoint")
        pair = fair_pairwise_judge(left, right, judge, comparison_id)
        _apply_elo(artifact, pair)
        artifact["pairwise_judgments"].append(pair)
        artifact["applied_comparison_ids"].append(comparison_id)
        scheduler["rng_state"] = rng.getstate()
    artifact["ranking_results"] = _results(artifact)
    artifact["checkpoint"] = {"status": "complete" if len(artifact["pairwise_judgments"]) >= match_budget else "in_progress",
                              "completed_matches": len(artifact["pairwise_judgments"])}
    scheduler["match_budget"] = int(match_budget)
    artifact["budget"]["matches"] = int(match_budget)
    return artifact


def apply_evidence_event(artifact, event):
    """Validate and idempotently append an independent (non-Elo) evidence signal."""
    required = ("event_id", "hypothesis_id", "source", "direction", "strength", "quality", "payload")
    missing = [key for key in required if not event.get(key)]
    if missing:
        raise ValueError("evidence event missing: " + ", ".join(missing))
    ids = {c["hypothesis_id"] for c in artifact["hypothesis_candidates"]}
    if event["hypothesis_id"] not in ids:
        raise ValueError("evidence event references unknown hypothesis")
    payload_hash = _hash(event["payload"])
    fingerprint = _hash({key: event[key] for key in required})
    for prior in artifact["evidence_events"]:
        if prior["event_id"] == event["event_id"]:
            if prior.get("event_fingerprint") != fingerprint:
                raise ValueError("evidence event ID reused with different immutable fields")
            return False
    applied = {key: event[key] for key in required if key != "payload"}
    applied.update({"payload_hash": payload_hash, "event_fingerprint": fingerprint,
                    "applied": True})
    artifact["evidence_events"].append(applied)
    return True


def attach_advisory_comparisons(artifact, formal_records):
    """Attach formal-vs-shadow signals without changing scores or decisions.

    ``formal_direction`` is supplied by the caller as ``HIGHER`` or ``LOWER``.
    The shadow signal is only the top-half/bottom-half rank split; an uncertain
    candidate never becomes a forced agreement or disagreement.
    """
    candidates = {item["candidate_id"]: item for item in artifact["hypothesis_candidates"]}
    results = {item["candidate_id"]: item for item in artifact.get("ranking_results", [])}
    top_half = max(1, len(results) // 2)
    records = []
    seen = set()
    for formal in formal_records:
        if not isinstance(formal, dict):
            raise ValueError("formal comparison record must be an object")
        candidate_id = formal.get("candidate_id")
        hypothesis_id = formal.get("hypothesis_id")
        formal_decision = formal.get("formal_decision")
        direction = str(formal.get("formal_direction", "")).upper()
        snapshot = candidates.get(candidate_id)
        if (not snapshot or snapshot.get("hypothesis_id") != hypothesis_id
                or not formal_decision or direction not in {"HIGHER", "LOWER"}):
            raise ValueError("formal comparison record is incomplete or does not match candidate")
        if candidate_id in seen:
            raise ValueError("formal comparison records must be unique per candidate")
        seen.add(candidate_id)
        result = results.get(candidate_id)
        if result is None:
            rank = uncertainty = None
            signal, status = "UNAVAILABLE", "UNAVAILABLE"
        else:
            rank = result.get("rank")
            uncertainty = result.get("uncertainty")
            signal = "HIGHER" if rank <= top_half else "LOWER"
            if uncertainty:
                status = "UNCERTAIN"
            else:
                status = "AGREES" if direction == signal else "DISAGREES"
        records.append({
            "candidate_id": candidate_id, "hypothesis_id": hypothesis_id,
            "formal_decision": formal_decision, "formal_direction": direction,
            "shadow_rank": rank, "shadow_uncertainty": uncertainty,
            "shadow_signal": signal, "comparison_status": status,
        })
    artifact["advisory_comparisons"] = records
    return records


def write_ranking_artifact(project_dir, artifact, run_id=None):
    """Persist a run under the isolated RLR audit/ranking directory."""
    rid = _validated_run_id(run_id or artifact.get("run_id") or "ranking-run")
    target = Path(project_dir) / "08_Audit" / "ranking" / (str(rid) + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    artifact = deepcopy(artifact)
    artifact["run_id"] = rid
    with target.open("x", encoding="utf-8") as handle:
        json.dump(artifact, handle, indent=2, ensure_ascii=False, default=list)
    return str(target)


def write_checkpoint(project_dir, artifact, run_id=None):
    """Persist a separate resumable checkpoint beside the immutable run artifact."""
    rid = _validated_run_id(run_id or artifact.get("run_id") or "ranking-run")
    target = Path(project_dir) / "08_Audit" / "ranking" / (str(rid) + ".checkpoint.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(artifact, handle, indent=2, ensure_ascii=False, default=list)
    return str(target)


def _validated_run_id(run_id):
    if not isinstance(run_id, str) or not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id must be a safe filename token")
    return run_id


def load_checkpoint(path):
    """Load a previously written ranking checkpoint without side effects."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def render_markdown_report(artifact):
    """Render a compact human-auditable shadow ranking report."""
    scheduler = artifact["scheduler"]
    lines = ["# Shadow Ranking Report", "", "- Schema: " + artifact["schema_version"],
             "- Seed: " + str(scheduler["seed"]),
             "- Match budget: " + str(scheduler["match_budget"]),
             "- Completed matches: " + str(len(artifact["pairwise_judgments"])), "",
             "## Ranking", "", "| Rank | Hypothesis ID | Elo | Matches | Uncertain |",
             "| --- | --- | ---: | ---: | ---: |"]
    for row in artifact["ranking_results"]:
        lines.append("| {rank} | {candidate_id} | {score:.2f} | {matches} | {uncertainty} |".format(**row))
    uncertain = sum(p["final_verdict"] == "UNCERTAIN" for p in artifact["pairwise_judgments"])
    lines += ["", "## Reliability", "", "- Uncertain pairwise judgments: " + str(uncertain),
              "- Evidence events applied: " + str(len(artifact["evidence_events"]))]
    comparisons = artifact.get("advisory_comparisons", [])
    if comparisons:
        lines += ["", "## Formal Decision Comparison", "",
                  "| Candidate | Formal decision | Formal direction | Shadow rank | Shadow signal | Status |",
                  "| --- | --- | --- | ---: | --- | --- |"]
        for record in comparisons:
            lines.append("| {candidate_id} | {formal_decision} | {formal_direction} | {shadow_rank} | {shadow_signal} | {comparison_status} |".format(**record))
        status_counts = {status: sum(record["comparison_status"] == status for record in comparisons)
                         for status in ("AGREES", "DISAGREES", "UNCERTAIN", "UNAVAILABLE")}
        lines.append("- Advisory summary: " + ", ".join(
            "%s=%d" % (status, status_counts[status]) for status in status_counts))
    if artifact["failures"]:
        lines += ["", "## Failures", ""] + ["- " + str(item) for item in artifact["failures"]]
    return "\n".join(lines) + "\n"
