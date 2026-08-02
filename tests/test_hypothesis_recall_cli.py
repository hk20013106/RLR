import json
import os
from pathlib import Path

from research_loop.cli import main
from tests.test_hypothesis_pool import _seed_rejected_hypothesis


def test_hypothesis_recall_cli_writes_artifact(tmp_path, capsys):
    project, _ledger, rejected_id = _seed_rejected_hypothesis(tmp_path)

    rc = main([
        "hypothesis-recall",
        str(project),
        "C2",
        "--round-id",
        "2",
        "--query",
        "extracellular matrix expression",
        "--limit",
        "10",
        "--knowledge-store",
        os.environ["RLR_HYPOTHESIS_STORE"],
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["artifact_path"]).is_file()
    assert payload["artifact"]["results"][0]["hypothesis_id"] == rejected_id


def test_hypothesis_pool_list_cli_includes_rejected_hypothesis(tmp_path, capsys):
    project, _ledger, rejected_id = _seed_rejected_hypothesis(tmp_path)

    rc = main([
        "hypothesis-pool-list",
        str(project),
        "--eligibility",
        "ELIGIBLE_WITH_BASIS",
        "--limit",
        "10",
        "--knowledge-store",
        os.environ["RLR_HYPOTHESIS_STORE"],
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(item["hypothesis_id"] == rejected_id for item in payload["records"])
