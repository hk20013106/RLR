from research_loop.api import EngineAPI
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.hypothesis_ledger import HypothesisLedger


def test_next_step_surfaces_native_authority_declarations(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "hypotheses.sqlite"
    HypothesisLedger(store).bind_project(
        project, profile_id=PROFILE_V21_CATALOG_1
    )
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))

    candidate = project / "01_Candidates" / "C1.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        "---\n"
        "candidate_id: C1\n"
        "current_status: IDEA_SELECTED\n"
        "round_id: 1\n"
        "---\n",
        encoding="utf-8",
    )

    packet = EngineAPI().next_step(project, "C1")

    assert packet["node"] == "L4"
    assert packet["required_authorities"] == ["current_round_data_binding"]
    assert packet["optional_authorities"] == []
    assert packet["produces_authorities"] == []
