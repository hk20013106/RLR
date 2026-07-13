from pathlib import Path
import subprocess
import sys

from research_loop.paths import _layer_template_path, _persona_template_path


ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "research_loop_v04.py"


def test_active_template_paths_are_version_neutral():
    assert "/v03_" not in _layer_template_path("L3")
    assert "/v03_" not in _persona_template_path("Oppenheimer")


def test_active_templates_contain_no_v03_runtime_instructions():
    prohibited = ("research_loop_v03.py", "v0.3 dag", "14-node", "14 node")
    for template_dir in (ROOT / "templates" / "layers", ROOT / "templates" / "personas"):
        assert template_dir.exists(), template_dir
        for path in template_dir.rglob("*.md"):
            text = path.read_text(encoding="utf-8").lower()
            assert not any(marker in text for marker in prohibited), path


def test_full_mode_injects_current_persona_and_layer_for_key_nodes(tmp_path):
    project = tmp_path / "P"
    created = subprocess.run([sys.executable, str(CLI), "new-project", str(project), "Topic"],
                             capture_output=True, text=True, encoding="utf-8")
    assert created.returncode == 0, created.stderr
    request = tmp_path / "request.md"
    data = tmp_path / "data.tsv"
    request.write_text("Scientific question: Q?\nCurrent hypothesis: H.\n", encoding="utf-8")
    data.write_text("x\n", encoding="utf-8")
    normalized = subprocess.run(
        [sys.executable, str(CLI), "normalize-l0-input", "--project", str(project),
         "--input", str(request), "--data", str(data)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert normalized.returncode == 0, normalized.stderr
    cand_id = next((project / "01_Candidates").glob("*.l0_input.yaml")).name.split(".")[0]

    expected = {
        "L0": ("Linnaeus", "Catalog Master"),
        "L3": ("Oppenheimer", "Cold Director"),
        "L7": ("Turing", "Execution Engine"),
        "L10b": ("Oppenheimer", "Cold Director"),
        "L10c": ("Linnaeus", "Catalog Master"),
    }
    for node, (persona, title) in expected.items():
        result = subprocess.run(
            [sys.executable, str(CLI), "assemble-context", str(project), cand_id,
             "--node", node, "--template-mode", "full"],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert f"=== CONTRACT: {node} | {persona} | {title}" in result.stdout
        assert "AUTHORITY:" in result.stdout
        assert "MUST NOT:" in result.stdout
        assert "[full] persona template" in result.stdout
        assert "## Functional title" in result.stdout
        assert "[full] layer template" in result.stdout
        assert "## Purpose" in result.stdout
