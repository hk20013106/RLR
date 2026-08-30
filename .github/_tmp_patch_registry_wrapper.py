from pathlib import Path


def replace_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


path = Path("src/research_loop/l4_registry_projection_integrity.py")
replace_once(
    path,
    '''def _apply_registry(registry_module, project_dir, inventory, assets=None):\n    entries, receipt = registry_module.load_registry(project_dir)\n''',
    '''def _apply_registry(\n    registry_module, project_dir, inventory, assets=None, *, loaded_registry=None\n):\n    if loaded_registry is None:\n        entries, receipt = registry_module.load_registry(project_dir)\n    else:\n        entries, receipt = loaded_registry\n        entries = copy.deepcopy(list(entries))\n        receipt = copy.deepcopy(dict(receipt))\n''',
)
replace_once(
    path,
    '''    def apply_registry(project_dir, inventory, assets=None):\n        return _apply_registry(\n            registry_module, project_dir, inventory, assets=assets\n        )\n''',
    '''    def apply_registry(\n        project_dir, inventory, assets=None, *, loaded_registry=None\n    ):\n        return _apply_registry(\n            registry_module,\n            project_dir,\n            inventory,\n            assets=assets,\n            loaded_registry=loaded_registry,\n        )\n''',
)
