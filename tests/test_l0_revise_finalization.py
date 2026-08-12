import json
from pathlib import Path
from types import SimpleNamespace

from research_loop.commands.lifecycle import cmd_next_step


def test_revise_candidate_routes_to_l10c_before_round_is_terminal(tmp_path, capsys):
    project = tmp_path / "P"
    project.mkdir()
    candidates = project / "01_Candidates"
    candidates.mkdir()
    (candidates / "C1.md").write_text(
        "---\n"
        "candidate_id: C1\n"
        "round_id: '1'\n"
        "current_status: REVISE\n"
        "---\n",
        encoding="utf-8",
    )

    rc = cmd_next_step(
        SimpleNamespace(project_dir=str(project), cand_id="C1", knowledge_store=None)
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload.get("terminal") is not True
    assert payload["node"] == "L10c"
    assert payload["advance_command"] == "aggregate-report"
