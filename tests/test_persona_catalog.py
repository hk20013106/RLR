import shutil

import pytest

from research_loop import persona_catalog
from research_loop.compatibility import PROFILE_V21_CATALOG_1, get_profile
from research_loop.persona_catalog import PersonaCatalogError


def _copy_catalog(tmp_path):
    root = tmp_path / "root"
    target = root / "templates" / "personas" / "catalog-v1"
    target.parent.mkdir(parents=True)
    shutil.copytree(
        persona_catalog._ROOT / "templates" / "personas" / "catalog-v1",
        target,
    )
    return root, target


def test_catalog_contains_ten_stable_personas():
    entries = persona_catalog._read_catalog()
    assert len(entries) == 10
    resolved = persona_catalog.resolve_persona_template(
        get_profile(PROFILE_V21_CATALOG_1), "Tukey"
    )
    assert resolved.markdown_body.startswith("# Tukey")
    assert resolved.catalog_sha256


def test_catalog_rejects_unknown_template_version(tmp_path, monkeypatch):
    root, target = _copy_catalog(tmp_path)
    file = target / "06_Tukey.md"
    file.write_text(
        file.read_text(encoding="utf-8").replace(
            'template_version: "1.0"', 'template_version: "9.0"'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(persona_catalog, "_ROOT", root)
    with pytest.raises(PersonaCatalogError, match="template version"):
        persona_catalog._read_catalog()


def test_catalog_rejects_unknown_frontmatter_field(tmp_path, monkeypatch):
    root, target = _copy_catalog(tmp_path)
    file = target / "06_Tukey.md"
    file.write_text(
        file.read_text(encoding="utf-8").replace(
            "template_version:", "tools_policy: all\ntemplate_version:"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(persona_catalog, "_ROOT", root)
    with pytest.raises(PersonaCatalogError, match="missing or unknown"):
        persona_catalog._read_catalog()
