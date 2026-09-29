"""Real CLI integration for the native L0 host commit and next host action."""

import json
import os
import subprocess
import sys
from pathlib import Path

from native_v2_helpers import bootstrap_project_ready
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.runtime_preflight import formal_runtime_command
from research_loop.yamlio import _load_yaml_front


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
