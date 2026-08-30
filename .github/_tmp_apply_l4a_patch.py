from pathlib import Path


def replace_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


registry = Path("src/research_loop/l4_method_registry.py")
replace_once(
    registry,
    '''def apply_registry(\n    project_dir: str | Path, inventory: list[dict]\n) -> tuple[list[dict], dict]:\n    """Add exact hints for methods already present in the cognitive inventory."""\n    entries, receipt = load_registry(project_dir)\n''',
    '''def apply_registry(\n    project_dir: str | Path, inventory: list[dict], *,\n    loaded_registry: tuple[list[dict], dict] | None = None,\n) -> tuple[list[dict], dict]:\n    """Add exact hints for methods already present in the cognitive inventory."""\n    if loaded_registry is None:\n        entries, receipt = load_registry(project_dir)\n    else:\n        entries, receipt = loaded_registry\n        entries = copy.deepcopy(list(entries))\n        receipt = copy.deepcopy(dict(receipt))\n''',
)

inventory = Path("src/research_loop/l4_inventory.py")
replace_once(
    inventory,
    "from research_loop import l4_method_registry\n",
    "from research_loop import compatibility, l4_method_registry\n",
)

marker = '''\n\ndef build_prompt(question: str, claim: str) -> str:\n    return f"""Use the installed Academic Research Skills literature-search capability.\n'''
helper = '''

def _native_known_source_catalog(
    project_dir: str | Path,
    candidate_id: str,
    profile_id: str,
    dr,
) -> tuple[dict | None, tuple[list[dict], dict] | None]:
    """Project the active frozen L0.5 sources and registry into L4A once."""
    if not str(profile_id or "").strip():
        return None, None
    try:
        profile = compatibility.get_profile(str(profile_id))
    except compatibility.CompatibilityError as exc:
        raise dr.DeepResearchError(f"L4A compatibility profile is invalid: {exc}") from exc
    if profile.delta_schema_version != "2.1":
        return None, None

    from research_loop import l05_curie, research_seed

    project = Path(project_dir)
    try:
        seed = research_seed.load_l1_research_seed(project, candidate_id)
        run_id = research_seed.active_l1_native_evidence_run_id(project, seed)
        if not run_id:
            raise dr.DeepResearchError(
                "native L4A requires an active frozen L0.5 EvidencePack before provider execution"
            )
        binding = research_seed.load_l1_native_evidence_binding(
            project, seed, run_id
        )
        pack_manifest = binding.get("evidence_pack")
        if not isinstance(pack_manifest, dict):
            raise dr.DeepResearchError(
                "native L4A active L0.5 binding has no frozen EvidencePack manifest"
            )
        frozen = l05_curie.load_frozen_evidence_pack(
            project,
            pack_manifest,
            candidate_id=str(seed["candidate_id"]),
            round_id=str(seed["round_id"]),
            seed_sha256=research_seed.seed_sha256(seed),
        )
        registry_entries, registry_receipt = l4_method_registry.load_registry(project)
    except dr.DeepResearchError:
        raise
    except (
        research_seed.ResearchSeedError,
        l05_curie.CurieContractError,
        l4_method_registry.MethodRegistryError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise dr.DeepResearchError(
            f"native L4A local-literature gate failed: {exc}"
        ) from exc

    snapshots_by_paper: dict[str, list[dict]] = {}
    for evidence in frozen.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        paper_id = str(evidence.get("paper_id") or "").strip()
        retrieval = evidence.get("retrieval")
        if not paper_id or not isinstance(retrieval, dict):
            continue
        snapshot = {
            key: copy.deepcopy(retrieval[key])
            for key in (
                "engine", "source_sha256", "snapshot_path", "pmcid", "verifier"
            )
            if retrieval.get(key) not in (None, "", [], {})
        }
        if snapshot and snapshot not in snapshots_by_paper.setdefault(paper_id, []):
            snapshots_by_paper[paper_id].append(snapshot)

    selected_papers = []
    for paper in frozen.get("selected_papers") or []:
        if not isinstance(paper, dict):
            continue
        paper_id = str(paper.get("paper_id") or "").strip()
        provenance = paper.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        compact_provenance = {
            key: copy.deepcopy(provenance[key])
            for key in (
                "provider", "raw_record_sha256", "source", "ext_id",
                "originating_query_ids", "source_records",
            )
            if provenance.get(key) not in (None, "", [], {})
        }
        metadata = paper.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        compact_metadata = {
            key: copy.deepcopy(metadata[key])
            for key in (
                "authors", "year", "journal", "publication_types",
                "is_open_access", "in_europe_pmc",
            )
            if key in metadata
        }
        selected_papers.append({
            "paper_id": paper_id,
            "title": str(paper.get("title") or "").strip(),
            "identifiers": copy.deepcopy(paper.get("identifiers") or {}),
            "metadata": compact_metadata,
            "provenance": compact_provenance,
            "source_snapshots": copy.deepcopy(snapshots_by_paper.get(paper_id, [])),
        })

    discovery_receipts = []
    for batch in frozen.get("discovery_receipts") or []:
        if not isinstance(batch, dict):
            continue
        raw_receipt = batch.get("receipt")
        raw_receipt = raw_receipt if isinstance(raw_receipt, dict) else {}
        receipt = {
            key: copy.deepcopy(raw_receipt[key])
            for key in (
                "request_sha256", "response_sha256", "response_path", "endpoint"
            )
            if raw_receipt.get(key) not in (None, "", [], {})
        }
        discovery_receipts.append({
            "provider": str(batch.get("provider") or ""),
            "query_id": str(batch.get("query_id") or ""),
            "receipt": receipt,
        })

    catalog = {
        "local_project_root": str(project.resolve()),
        "evidence_pack": {
            "pack_id": str(frozen.get("pack_id") or pack_manifest.get("pack_id") or ""),
            "content_sha256": str(
                frozen.get("content_sha256")
                or pack_manifest.get("content_sha256")
                or ""
            ),
            "artifact_path": str(pack_manifest.get("artifact_path") or ""),
            "artifact_sha256": str(pack_manifest.get("artifact_sha256") or ""),
            "source_run_id": str(run_id),
        },
        "selected_papers": selected_papers,
        "discovery_receipts": discovery_receipts,
        "method_source_registry": {
            "receipt": copy.deepcopy(registry_receipt),
            "methods": copy.deepcopy(registry_entries),
        },
    }
    return catalog, (registry_entries, registry_receipt)


def build_prompt(
    question: str, claim: str, known_sources: dict | None = None
) -> str:
    known_block = ""
    if known_sources is not None:
        known_block = f"""

Frozen known-source catalog (read-only retrieval hints; NOT method-selection authority):
{_canonical_json(known_sources)}

Local-first rules:
1. Decide the method inventory from the scientific question and selected claim first.
   A method appearing in this catalog does not authorize or require that method.
2. After a method is identified, reuse matching selected-paper identifiers and
   method-registry source_hints before doing any external lookup.
3. Do not run an external search for a DOI, PMID, PMCID, stable URL, or exact
   source already present in this catalog. Do not re-query a known identifier.
4. When metadata needs verification, use the frozen response_path or
   source_snapshots under local_project_root before any network request.
5. External metadata search is permitted only for a source/identifier gap that
   remains after local EvidencePack and method-registry matching.
"""
    return f"""Use the installed Academic Research Skills literature-search capability.
'''
text = inventory.read_text(encoding="utf-8")
if text.count(marker) != 1:
    raise SystemExit(f"{inventory}: prompt marker count {text.count(marker)}")
inventory.write_text(text.replace(marker, helper, 1), encoding="utf-8")

replace_once(
    inventory,
    '''Selected hypothesis/claim: {claim}\n\nIdentify the explicit statistical, computational, diagnostic, and alternative\n''',
    '''Selected hypothesis/claim: {claim}{known_block}\n\nIdentify the explicit statistical, computational, diagnostic, and alternative\n''',
)

replace_once(
    inventory,
    '''    profile_id: str = "",\n) -> dict:\n    canonical = _validate_inventory_payload(l4p, dr, payload)\n    try:\n        registry_inventory, registry_receipt = l4_method_registry.apply_registry(\n            project_dir, canonical["method_inventory"]\n        )\n''',
    '''    profile_id: str = "",\n    registry_snapshot: tuple[list[dict], dict] | None = None,\n) -> dict:\n    canonical = _validate_inventory_payload(l4p, dr, payload)\n    try:\n        registry_inventory, registry_receipt = l4_method_registry.apply_registry(\n            project_dir,\n            canonical["method_inventory"],\n            loaded_registry=registry_snapshot,\n        )\n''',
)

replace_once(
    inventory,
    '''    command, _ = dr.build_invocation(spec, "L4", question, claim, work)\n    command = [\n        str(inventory_schema_path) if value == str(legacy_schema_path) else value\n        for value in command\n    ]\n    prompt = build_prompt(question, claim)\n''',
    '''    known_sources, registry_snapshot = _native_known_source_catalog(\n        project_dir, candidate_id, profile_id, dr\n    )\n    command, _ = dr.build_invocation(spec, "L4", question, claim, work)\n    command = [\n        str(inventory_schema_path) if value == str(legacy_schema_path) else value\n        for value in command\n    ]\n    prompt = build_prompt(question, claim, known_sources)\n''',
)

replace_once(
    inventory,
    '''        model=spec.model,\n    )\n    if completed.returncode != 0:\n''',
    '''        model=spec.model,\n    )\n    if known_sources is not None:\n        pack = known_sources["evidence_pack"]\n        receipt["known_source_catalog"] = {\n            "catalog_sha256": _sha(_canonical_json(known_sources)),\n            "evidence_pack_id": str(pack.get("pack_id") or ""),\n            "evidence_pack_content_sha256": str(\n                pack.get("content_sha256") or ""\n            ),\n            "evidence_pack_artifact_sha256": str(\n                pack.get("artifact_sha256") or ""\n            ),\n            "selected_paper_count": len(known_sources["selected_papers"]),\n        }\n    if completed.returncode != 0:\n''',
)

replace_once(
    inventory,
    '''        round_id=round_id,\n        profile_id=profile_id,\n    )\n\n\ndef inventory_sources''',
    '''        round_id=round_id,\n        profile_id=profile_id,\n        registry_snapshot=registry_snapshot,\n    )\n\n\ndef inventory_sources''',
)

schema_test = Path("tests/test_l4_inventory_schema.py")
replace_once(
    schema_test,
    '''            dr.RuntimeSpec("codex", sys.executable, timeout=3),\n            tmp_path / "work",\n            project_id="P1",\n            round_id="1",\n            profile_id="v2.1-catalog-1",\n        )\n    finally:\n''',
    '''            dr.RuntimeSpec("codex", sys.executable, timeout=3),\n            tmp_path / "work",\n            project_id="P1",\n            round_id="1",\n            profile_id="v2.0-legacy",\n        )\n    finally:\n''',
)

local_test = Path("tests/test_l4a_local_literature_first.py")
replace_once(
    local_test,
    '''    assert manifest["runtime_receipt"]["method_source_registry"] == registry_receipt\n''',
    '''    registry_used = manifest["runtime_receipt"]["method_source_registry"]\n    assert registry_used["builtin_sha256"] == registry_receipt["builtin_sha256"]\n    assert registry_used["project_sha256"] == registry_receipt["project_sha256"]\n    assert registry_used["matches"] == [{\n        "method_id": "deseq2",\n        "canonical_method_ids": ["deseq2"],\n    }]\n''',
)
