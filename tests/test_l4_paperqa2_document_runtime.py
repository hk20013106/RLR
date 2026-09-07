import hashlib
import json
import sys

from research_loop.l05_curie.paperqa2 import PaperQA2Retriever
from research_loop.l05_curie.paperqa2_runtime import PaperQA2SubprocessBackend


def test_paperqa2_backend_accepts_frozen_xml_document_with_v2_provenance(tmp_path):
    source = tmp_path / "PMC9545966.xml"
    source.write_text(
        "<article><body><sec><title>EXPERIMENTAL PROCEDURES</title>"
        "<p>Animals were assigned to experimental groups and processed using the described protocol.</p>"
        "</sec></body></article>",
        encoding="utf-8",
    )
    expected_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

    bridge = tmp_path / "bridge.py"
    bridge.write_text(
        """
import hashlib
import json
import pathlib
import sys

request = json.load(sys.stdin)
path = pathlib.Path(request["document_path"])
print(json.dumps({
    "engine": "paperqa2",
    "runtime": {
        "schema_version": "PaperQA2Runtime/v2",
        "package": "paper-qa",
        "version": "2026.8.12",
        "upstream_repo": "https://github.com/Future-House/paper-qa",
        "upstream_tag": "v2026.08.12",
        "upstream_commit": "57e89f7223b0960d5ee5ea048c69e3c47e088572",
        "fork_repo": "https://github.com/hk20013106/paper-qa",
        "document_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "document_media_type": request["document_media_type"],
    },
    "hits": [{
        "text": "Animals were assigned to experimental groups and processed using the described protocol.",
        "locator": "PMC9545966.xml chunk 1",
        "section": "PaperQA2",
        "score": 0.9
    }]
}))
""",
        encoding="utf-8",
    )

    backend = PaperQA2SubprocessBackend(
        python_executable=sys.executable,
        bridge_script=bridge,
        paperqa_repo=tmp_path,
        pqa_home=tmp_path / "pqa-home",
    )
    paper = {
        "paper_id": "P1",
        "title": "Frozen Europe PMC source",
        "identifiers": {"pmcid": "PMC9545966"},
        "document_path": str(source),
        "document_media_type": "application/xml",
    }

    item = PaperQA2Retriever(
        backend=backend,
        backend_id="paperqa2-fork-v2026.08.12/sparse-docs-v1",
    ).retrieve(
        paper=paper,
        question="Locate the experimental procedures used in this paper.",
    )[0]

    assert item["verification_status"] == "UNVERIFIED"
    assert "role" not in item
    assert item["retrieval"]["runtime"]["schema_version"] == "PaperQA2Runtime/v2"
    assert item["retrieval"]["runtime"]["document_sha256"] == expected_sha256
    assert item["retrieval"]["runtime"]["document_media_type"] == "application/xml"
