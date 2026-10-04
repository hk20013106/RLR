"""Real CLI integration for the native L0 host commit and next host action."""

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

from native_v2_helpers import bootstrap_project_ready
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.runtime_preflight import formal_runtime_command
from research_loop.yamlio import _load_yaml_front


def test_public_host_submit_routes_coverage_to_l05owner(tmp_path, monkeypatch, capsys):
    import run_loop
    from research_loop.l05_curie import europepmc_runtime as owner
    from test_l05_curie_corpus_integration import drive
    original_continue = owner.continue_acquisition
    original_submit = owner.submit_acquisition_host_response
    continued, receipts, stages = [], [], []
    def continuation(*args, **kwargs):
        result = original_continue(*args, **kwargs); continued.append(result); return result
    def submit(*args, **kwargs):
        receipt = original_submit(*args, **kwargs); receipts.append(receipt); return receipt
    monkeypatch.setattr(owner, "continue_acquisition", continuation)
    monkeypatch.setattr(owner, "submit_acquisition_host_response", submit)
    def public_submit(project, seed, step, response):
        # Isolated first-mile fixture already has an activated ledger. Exercise
        # the real CLI command and all acquisition persistence/cognition owners.
        monkeypatch.setattr(run_loop, "_host_command_configuration", lambda _args: (project, "C001", None))
        request = step["request"]; stages.append(request["identity"]["stage"])
        before = len(receipts)
        args = SimpleNamespace(request_id=step["request_id"], response_path=str(response))
        assert run_loop.cmd_host_submit(args) == 0
        result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert result["status"] == "committed" and len(receipts) == before + 1
        assert result["response_receipt"]["request_sha256"] == request["request_sha256"]
        assert result["response_receipt"]["cursor"] == request["identity"]["cursor"]
        return continued[-1]
    project, seed, result, calls = drive(tmp_path, monkeypatch, rounds=1, submitter=public_submit)
    assert stages[0] == "planner" and stages[-1] == "coverage:1"
    assert result["kind"] == "FROZEN" and calls["worker"] == [30]


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "research_loop_v04.py"
HOST_CLI = ROOT / "run_loop.py"


def _run_cli(entrypoint, *args, env):
    launcher = formal_runtime_command() if entrypoint == HOST_CLI else [sys.executable]
    return subprocess.run(
        [*launcher, str(entrypoint), *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        env=env,
        timeout=120,
    )


def _last_json_line(result):
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_agent_native_cli_commits_l0_and_schedules_l05(tmp_path):
    """Real host CLI commits L0 and authoritative next-step selects L0.5."""
    project = tmp_path / "agent-native-cli"
    store = tmp_path / "hypotheses.sqlite"
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "RLR_HYPOTHESIS_STORE": str(store),
        "RLR_HOST_BACKEND": "codex",
        "RLR_AUTO_HYPOTHESIS_RECALL": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }

    created = _run_cli(
        CONTROLLER,
        "new-project", project, "Agent-native CLI integration",
        "--profile", PROFILE_V21_CATALOG_1,
        env=env,
    )
    assert created.returncode == 0, created.stderr or created.stdout

    env = bootstrap_project_ready(
        project,
        CONTROLLER,
        cwd=str(ROOT),
        extra_env={key: value for key, value in env.items() if key != "PATH"},
        profile_id=PROFILE_V21_CATALOG_1,
    )
    candidate_result = _run_cli(
        CONTROLLER,
        "new-candidate", project,
        "--title", "Offline host cycle",
        "--question", "Can the host cycle advance from L0 to L0.5?",
        "--claim", "A valid fixture response commits L0 and schedules L0.5.",
        "--input", "Synthetic fixture input for the host cycle.",
        env=env,
    )
    assert candidate_result.returncode == 0, candidate_result.stderr or candidate_result.stdout
    candidate_id = candidate_result.stdout.strip().splitlines()[0]
    candidate_path = project / "01_Candidates" / f"{candidate_id}.md"
    assert _load_yaml_front(candidate_path)["current_status"] == "NEW"

    first = _run_cli(
        HOST_CLI, "host-next", project, candidate_id,
        "--knowledge-store", store,
        env=env,
    )
    assert first.returncode == 0, first.stderr or first.stdout
    first_action = _last_json_line(first)
    assert first_action["status"] == "needs_host"
    first_request = json.loads(Path(first_action["request_path"]).read_text(encoding="utf-8"))
    assert first_request["identity"]["node"] == "L0"
    assert first_request["identity"]["candidate_id"] == candidate_id
    assert first_request["output_contract"]["schema_version"] == "2.1"

    response_path = project / "legal-l0-host-response.json"
    response_path.write_text(
        json.dumps({"schema_version": "2.1", "candidate_id": candidate_id}) + "\n",
        encoding="utf-8",
    )
    submitted = _run_cli(
        HOST_CLI, "host-submit", project, candidate_id,
        first_action["request_id"], response_path,
        "--knowledge-store", store,
        env=env,
    )
    assert submitted.returncode == 0, submitted.stderr or submitted.stdout
    submit_result = _last_json_line(submitted)
    assert submit_result["status"] == "committed"
    assert submit_result["phase"] == "committed"
    assert _load_yaml_front(candidate_path)["current_status"] == "IDEA_PROPOSED"

    authoritative_next = _run_cli(
        CONTROLLER, "next-step", project, candidate_id,
        env=env,
    )
    assert authoritative_next.returncode == 0, authoritative_next.stderr or authoritative_next.stdout
    next_step = json.loads(authoritative_next.stdout)
    assert next_step["node"] == "L0.5"
