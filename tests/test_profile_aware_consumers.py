import json
from types import SimpleNamespace

from research_loop.commands.ledger import _emit_delta_v2
from research_loop.commands.research import _l8_storage_key
from research_loop.context import cmd_assemble_context
from research_loop.compatibility import (
    PROFILE_V20,
    PROFILE_V21,
    PROFILE_V21_CATALOG_1,
    get_profile,
)
from research_loop.delta import artifact_for_node
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.topology import topology_for_profile
from sync_to_obsidian import _display_artifact
from native_v2_helpers import seed_revise_continuation


def test_l8_consumers_follow_bound_profile_without_fallback(tmp_path):
    for profile_id, expected in (
        (PROFILE_V21, "L8_curie"),
        (PROFILE_V21_CATALOG_1, "L8_tukey"),
    ):
        project = tmp_path / profile_id
        project.mkdir()
        ledger = HypothesisLedger(tmp_path / f"{profile_id}.sqlite")
        ledger.bind_project(project, profile_id=profile_id)
        assert _l8_storage_key(project) == expected
        persona, storage_key, title = _display_artifact(
            get_profile(profile_id), "L8_curie"
        )
        assert (persona, storage_key) == ("Tukey", expected)
        assert "(Tukey)" in title


def test_native_profiles_are_serial_and_legacy_profile_is_parallel():
    _, legacy, legacy_sequence = topology_for_profile(PROFILE_V20)
    assert "L9_parallel" in legacy_sequence
    assert "L9a" not in legacy["L9b"]["context_inputs"]
    for profile_id in (PROFILE_V21, PROFILE_V21_CATALOG_1):
        _, nodes, sequence = topology_for_profile(profile_id)
        assert sequence.index("L9a") < sequence.index("L9b")
        assert "L9a" in nodes["L9b"]["context_inputs"]
        assert nodes["L9b"]["is_parallel"] is False


def test_public_emit_rejects_v20_project(tmp_path, monkeypatch, capsys):
    project = tmp_path / "legacy"
    project.mkdir()
    store = tmp_path / "legacy.sqlite"
    ledger = HypothesisLedger(store)
    ledger.bind_project(project, profile_id=PROFILE_V20)
    candidate = project / "01_Candidates" / "C1.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        "---\ncandidate_id: C1\nround_id: 1\n---\n", encoding="utf-8"
    )
    source = tmp_path / "delta.json"
    source.write_text(json.dumps({"schema_version": "2.0"}), encoding="utf-8")
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    args = SimpleNamespace(
        project_dir=str(project), cand_id="C1", node="L1",
        persona="Einstein", file=str(source), knowledge_store=str(store),
        context_manifest=None, receipt=None, provider_receipt=None,
    )
    assert _emit_delta_v2(args, {"schema_version": "2.0"}) == 1
    assert "read-only" in capsys.readouterr().err


def test_catalog_profile_l8_descriptor_uses_tukey_storage():
    descriptor = artifact_for_node(get_profile(PROFILE_V21_CATALOG_1), "L8")
    assert descriptor.display_persona == "Tukey"
    assert descriptor.storage_key == "L8_tukey"


def test_l9b_context_contains_finalized_l9a_snapshot(
    tmp_path, monkeypatch, capsys
):
    project = tmp_path / "serial"
    project.mkdir()
    store = tmp_path / "serial.sqlite"
    ledger = HypothesisLedger(store)
    ledger.bind_project(project, profile_id=PROFILE_V21_CATALOG_1)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    seed_revise_continuation(
        project, "C1", write_memory=False, loop_type="divergent"
    )
    args = SimpleNamespace(
        project_dir=str(project), cand_id="C1", node="L9b",
        authorization_id=None, knowledge_store=str(store),
        template_mode="contract", pre_research_mode="digest",
        pre_research_token_budget=None, context_token_budget=8000,
        evidence_run_id=None,
    )
    assert cmd_assemble_context(args) == 0
    manifest_path = sorted(
        (project / "08_Audit").glob("context_manifest_L9b_*.json")
    )[-1]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    authorization = ledger.load_authorized_context(
        project, manifest["hypothesis_authorization"]["authorization_id"]
    )
    assert any(event["node"] == "L9a" for event in authorization["events"])
    assert "L9a" in manifest["allowed_inputs"]
    capsys.readouterr()
