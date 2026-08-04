import hashlib

from research_loop import l4_runtime_compat as compat


def test_receipt_canonicalization_is_cross_platform(tmp_path):
    relative = "09_Literature_Database/evidence_packs/retrieval_receipts/R1/A1.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    canonical = b'{\n  "status": "resolved"\n}\n'
    path.write_bytes(canonical.replace(b"\n", b"\r\n"))
    artifact = {
        "full_text_retrieval": [{
            "path": relative,
            "sha256": hashlib.sha256(canonical).hexdigest(),
        }]
    }

    compat._canonicalize_receipts(tmp_path, artifact)

    assert path.read_bytes() == canonical


def test_runtime_routes_only_native_v21_l4_to_staged_pipeline(tmp_path):
    calls = []

    class FakeDeepResearch:
        _l4_evidence_bundle_original_run = staticmethod(
            lambda *args, **kwargs: calls.append("legacy") or {"path": "legacy"}
        )
        run_and_persist = staticmethod(
            lambda *args, **kwargs: calls.append("staged") or {"path": "staged"}
        )

    class FakeBundle:
        run_l4b_evidence = staticmethod(
            lambda *args, **kwargs: {"full_text_retrieval": []}
        )

    compat.install(FakeDeepResearch, FakeBundle)
    common = (
        tmp_path, "C1", "L4", "question", "claim", object(), tmp_path / "work"
    )

    assert FakeDeepResearch.run_and_persist(*common, profile_id="v2.0")["path"] == "legacy"
    assert FakeDeepResearch.run_and_persist(
        *common, profile_id="v2.1-catalog-1"
    )["path"] == "staged"
    assert calls == ["legacy", "staged"]
