import copy
import inspect
import json
import sys
from types import ModuleType
from types import SimpleNamespace

import numpy as np
import pytest

from research_loop import deep_research as dr
from research_loop import l4_inventory
from research_loop import l4_pipeline as l4p
import research_loop.l4_contextual_literature as contextual
from research_loop.l4a_specter2 import (
    build_paper_text,
    rank_method_papers,
)


def _method(method_id: str, name: str) -> dict:
    return {
        "method_id": method_id,
        "name": name,
        "purpose": f"Use {name} for the selected scientific question.",
        "inventory_reason": f"{name} is required by the selected hypothesis.",
    }


def _record(
    paper_id: str,
    *,
    title: str = "English method study",
    abstract: str = "The study evaluates a reproducible analytical method.",
    query_ids: list[str] | None = None,
    language: str | None = "en",
) -> dict:
    metadata = {
        "abstract": abstract,
        "journal": "Methods Journal",
        "year": "2024",
        "authors": "Researcher",
    }
    if language is not None:
        metadata["language"] = language
    return {
        "paper_id": paper_id,
        "title": title,
        "identifiers": {
            "doi": f"10.1000/{paper_id.casefold()}",
            "pmid": "12345678",
            "pmcid": "PMC1234567",
        },
        "metadata": metadata,
        "provenance": {
            "provider": "fixture",
            "originating_query_ids": list(query_ids or ["CQ1"]),
            "source_records": [{"provider": "fixture"}],
        },
    }


def _pair_selection(*pairs: tuple[str, str]) -> dict:
    return {
        "pairs": [
            {
                "paper_id": paper_id,
                "method_id": method_id,
                "semantic_score": 0.9,
                "semantic_rank": 1,
                "selector_decision": "INCLUDE",
            }
            for paper_id, method_id in pairs
        ]
    }


def _adjudication(*rows: tuple[str, str, str]) -> dict:
    return {
        "schema_version": contextual.METHOD_SUPPORT_SCHEMA_VERSION,
        "status": "completed",
        "decisions": [
            {
                "paper_id": paper_id,
                "method_id": method_id,
                "classification": classification,
                "rationale": f"Fixture rationale for {paper_id} and {method_id}.",
            }
            for paper_id, method_id, classification in rows
        ],
        "direct_count": sum(
            classification == "DIRECT_METHOD_SUPPORT"
            for _, _, classification in rows
        ),
    }


def _inventory(*methods: dict) -> list[dict]:
    return [
        {
            **method,
            "source_asset_ids": [],
            "source_hints": [],
        }
        for method in methods
    ]


class _FakeTensor:
    def __init__(self, value):
        self.data = np.asarray(value, dtype=float)

    @property
    def ndim(self):
        return self.data.ndim

    @property
    def shape(self):
        return self.data.shape

    def __getitem__(self, index):
        return _FakeTensor(self.data[index])

    def to(self, _device):
        return self

    def detach(self):
        return self

    def cpu(self):
        return self

    def norm(self, dim=None):
        return _FakeTensor(
            np.linalg.norm(self.data, axis=dim) if dim is not None else np.linalg.norm(self.data)
        )

    def clamp_min(self, value):
        return _FakeTensor(np.maximum(self.data, value))

    def unsqueeze(self, dim):
        return _FakeTensor(np.expand_dims(self.data, axis=dim))

    def item(self):
        return self.data.item()

    def __truediv__(self, other):
        value = other.data if isinstance(other, _FakeTensor) else other
        return _FakeTensor(self.data / value)

    def __matmul__(self, other):
        value = other.data if isinstance(other, _FakeTensor) else other
        return _FakeTensor(self.data @ value)


class _FakeNoGrad:
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False


class _FakeTorch:
    class cuda:
        @staticmethod
        def is_available():
            return False

    @staticmethod
    def no_grad():
        return _FakeNoGrad()

    @staticmethod
    def cat(chunks, dim=0):
        return _FakeTensor(np.concatenate([chunk.data for chunk in chunks], axis=dim))

    @staticmethod
    def isfinite(value):
        return np.isfinite(value.data)


class _FakeTokenizer:
    sep_token = "[SEP]"

    def __init__(self):
        self.calls = []

    def __call__(self, batch, **kwargs):
        self.calls.append((list(batch), kwargs))
        values = [
            [len(text) + 1, sum(ord(char) for char in text) % 997 + 1]
            for text in batch
        ]
        return {"input_ids": _FakeTensor(values)}


class _FakeModel:
    def __init__(self):
        self.active_adapters = []
        self.load_calls = []
        self.to_devices = []
        self.eval_calls = 0

    def eval(self):
        self.eval_calls += 1
        return self

    def to(self, device):
        self.to_devices.append(device)
        return self

    def set_active_adapters(self, adapter):
        self.active_adapters.append(adapter)

    def load_adapter(self, *args, **kwargs):
        self.load_calls.append((args, kwargs))

    def __call__(self, **inputs):
        values = inputs["input_ids"].data
        hidden = np.zeros((values.shape[0], 1, 2), dtype=float)
        hidden[:, 0, :] = values
        return SimpleNamespace(last_hidden_state=_FakeTensor(hidden))


def test_english_only_eligibility_excludes_cjk_without_mutating_curie_record():
    record = _record(
        "P_CJK",
        title="心脏转录组分析方法",
        abstract="心脏表达谱研究。",
        language=None,
    )
    before = copy.deepcopy(record)

    assert contextual._english_contextual_eligibility(record) == (
        False,
        "NON_ENGLISH_CONTEXTUAL_SOURCE",
    )
    assert record == before


def test_contextual_relevance_path_no_longer_contains_token_overlap_scorer():
    source = inspect.getsource(contextual)

    assert "def _tokens" not in source
    assert "_build_selector_scorer" not in source


def test_contextual_query_validation_rejects_non_english_text():
    payload = {
        "schema_version": contextual.CONTEXTUAL_QUERY_PLAN_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1",
            "query": "心脏转录组方法",
            "purpose": "fixture",
            "status": "planned",
            "receipt": "fixture",
            "method_ids": ["M12"],
        }],
    }

    with pytest.raises(dr.DeepResearchError, match="English"):
        contextual._validate_contextual_payload(dr, dr, payload, ["M12"])


def test_specter2_paper_input_is_official_and_allows_title_only():
    assert build_paper_text("A title", "An abstract", "[SEP]") == (
        "A title[SEP]An abstract"
    )
    assert build_paper_text("A title", "", "[SEP]") == "A title"
    with pytest.raises(ValueError, match="title"):
        build_paper_text("", "abstract", "[SEP]")
    with pytest.raises(ValueError, match="separator"):
        build_paper_text("A title", "abstract", "")


def test_specter2_ranker_batches_cls_embeddings_and_uses_both_adapters():
    from research_loop.l4a_specter2 import Specter2Ranker

    tokenizer = _FakeTokenizer()
    model = _FakeModel()
    ranker = Specter2Ranker(
        tokenizer, model, _FakeTorch, device="cpu", batch_size=1
    )
    rows = ranker.rank_method_papers(
        "gene co-expression network analysis",
        [
            _record("P1", title="Weighted network analysis"),
            _record("P2", title="Comparative biology", abstract=""),
        ],
    )

    assert len(rows) == 2
    assert {row["semantic_rank"] for row in rows} == {1, 2}
    assert model.active_adapters == ["proximity", "adhoc_query"]
    assert model.eval_calls == 1
    assert all(
        call[1]["return_token_type_ids"] is False
        and call[1]["max_length"] == 512
        for call in tokenizer.calls
    )
    assert ranker.receipt()["deterministic_inference"] is True


def test_specter2_loader_uses_pinned_revisions_and_cpu_fallback(monkeypatch):
    from research_loop import l4a_specter2 as specter2

    fake_torch = ModuleType("torch")

    class _Cuda:
        @staticmethod
        def is_available():
            return False

    fake_torch.cuda = _Cuda
    fake_adapters = ModuleType("adapters")
    fake_transformers = ModuleType("transformers")
    model = _FakeModel()
    tokenizer = _FakeTokenizer()

    class AutoAdapterModel:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            model.base_load = (args, kwargs)
            return model

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            tokenizer.base_load = (args, kwargs)
            return tokenizer

    fake_adapters.AutoAdapterModel = AutoAdapterModel
    fake_transformers.AutoTokenizer = AutoTokenizer
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "adapters", fake_adapters)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    ranker = specter2.Specter2Ranker.from_pretrained(device="auto")

    assert ranker.device == "cpu"
    assert tokenizer.base_load[0] == (specter2.BASE_MODEL,)
    assert tokenizer.base_load[1]["revision"] == specter2.BASE_REVISION
    assert model.base_load[1]["revision"] == specter2.BASE_REVISION
    assert model.load_calls[0][0] == (specter2.PAPER_ADAPTER,)
    assert model.load_calls[0][1]["revision"] == specter2.PAPER_REVISION
    assert model.load_calls[1][0] == (specter2.QUERY_ADAPTER,)
    assert model.load_calls[1][1]["revision"] == specter2.QUERY_REVISION


def test_specter2_ranker_accepts_deterministic_fake_without_loading_weights():
    calls = []

    class FakeRanker:
        def rank_method_papers(self, method_query, canonical_records):
            calls.append((method_query, [item["paper_id"] for item in canonical_records]))
            return [
                {
                    "paper_id": canonical_records[0]["paper_id"],
                    "semantic_score": 0.91,
                    "semantic_rank": 1,
                }
            ]

    result = rank_method_papers(
        "co-expression network analysis",
        [_record("P1")],
        ranker=FakeRanker(),
    )

    assert result[0]["paper_id"] == "P1"
    assert result[0]["semantic_score"] == pytest.approx(0.91)
    assert calls == [("co-expression network analysis", ["P1"])]


def test_specter2_ranker_rejects_invalid_fake_identity_score_and_rank():
    record = _record("P1")

    class UnknownPaper:
        def rank_method_papers(self, _query, _records):
            return [{"paper_id": "UNKNOWN", "semantic_score": 0.2, "semantic_rank": 1}]

    with pytest.raises(ValueError, match="unknown paper_id"):
        rank_method_papers("method", [record], ranker=UnknownPaper())

    class InvalidScore:
        def rank_method_papers(self, _query, _records):
            return [{"paper_id": "P1", "semantic_score": 2.0, "semantic_rank": 1}]

    with pytest.raises(ValueError, match="outside"):
        rank_method_papers("method", [record], ranker=InvalidScore())

    class InvalidRank:
        def rank_method_papers(self, _query, _records):
            return [{"paper_id": "P1", "semantic_score": 0.2, "semantic_rank": 0}]

    with pytest.raises(ValueError, match="rank"):
        rank_method_papers("method", [record], ranker=InvalidRank())


def test_contextual_ranking_is_per_method_and_top_k_is_not_global(tmp_path):
    methods = [
        _method("M12", "Co-expression network analysis"),
        _method("M15", "Gene set enrichment analysis"),
    ]
    records = [
        _record("P1", query_ids=["CQ1"]),
        _record("P2", query_ids=["CQ1"]),
        _record("P3", query_ids=["CQ2"]),
    ]
    planner_queries = [
        {
            "query_id": "PQ1",
            "query": "co-expression network analysis cardiac transcriptomics",
            "method_ids": ["M12"],
        },
        {
            "query_id": "PQ2",
            "query": "gene set enrichment analysis cardiac transcriptomics",
            "method_ids": ["M15"],
        },
    ]
    query_plan = {
        "queries": [
            {"query_id": "CQ1"},
            {"query_id": "CQ2"},
        ]
    }

    class FakeRanker:
        def rank_method_papers(self, method_query, canonical_records):
            if method_query.casefold().startswith("co-expression"):
                scores = {"P1": 0.80, "P2": 0.70}
            else:
                scores = {"P3": 0.95}
            return [
                {
                    "paper_id": paper_id,
                    "semantic_score": scores[paper_id],
                    "semantic_rank": rank,
                }
                for rank, paper_id in enumerate(
                    sorted(scores, key=lambda item: (-scores[item], item)), 1
                )
            ]

    selection, selected_records = contextual._select_contextual_candidates(
        records,
        methods,
        planner_queries,
        query_plan,
        seed={"scientific_question": "Q", "hypothesis_seed": "H"},
        ranker=FakeRanker(),
        top_k_per_method=1,
        project_dir=tmp_path,
        candidate_id="C1",
        discovery_run_id="L4A_TEST",
    )

    by_method = {
        item["method_id"]: item for item in selection["method_selections"]
    }
    assert by_method["M12"]["selector"]["included_paper_ids"] == ["P1"]
    assert by_method["M15"]["selector"]["included_paper_ids"] == ["P3"]
    assert selection["included_paper_ids"] == ["P1", "P3"]
    assert {item["paper_id"] for item in selected_records} == {"P1", "P3"}


def test_query_provenance_does_not_bind_all_methods():
    record = _record("P1", query_ids=["CQ1"])
    controller = _inventory(
        _method("M12", "Co-expression network analysis"),
        _method("M15", "Gene set enrichment analysis"),
    )
    inventory, assets, selected_ids = contextual._bind_selected_records(
        controller,
        [record],
        _pair_selection(("P1", "M12"), ("P1", "M15")),
        _adjudication(
            ("P1", "M12", "DIRECT_METHOD_SUPPORT"),
            ("P1", "M15", "IRRELEVANT"),
        ),
        {"sources": []},
        l4_inventory,
    )
    assets = l4p._normalize_l4a_assets(assets)

    by_method = {item["method_id"]: item for item in inventory}
    assert by_method["M12"]["source_asset_ids"] == ["P1"]
    assert by_method["M15"]["source_asset_ids"] == []
    assert assets[0]["method_component_hints"] == ["M12"]
    assert selected_ids == ["P1"]


@pytest.mark.parametrize(
    "classification",
    [
        "RELATED_BUT_NOT_METHOD_SUPPORT",
        "IRRELEVANT",
        "INSUFFICIENT_METADATA",
    ],
)
def test_non_direct_classifications_are_auditable_but_never_bound(classification):
    record = _record("P1")
    controller = _inventory(_method("M12", "Gene set construction"))
    inventory, assets, _ = contextual._bind_selected_records(
        controller,
        [record],
        _pair_selection(("P1", "M12")),
        _adjudication(("P1", "M12", classification)),
        {"sources": []},
        l4_inventory,
    )

    assert inventory[0]["source_asset_ids"] == []
    assert assets[0]["method_component_hints"] == []


def test_method_support_schema_accepts_exactly_four_classifications():
    expected = {("P1", "M12")}
    for classification in contextual.METHOD_SUPPORT_CLASSIFICATIONS:
        payload = {
            "schema_version": contextual.METHOD_SUPPORT_SCHEMA_VERSION,
            "decisions": [{
                "paper_id": "P1",
                "method_id": "M12",
                "classification": classification,
                "rationale": "Short metadata-only fixture rationale.",
            }],
        }
        validated = contextual._validate_method_support_payload(
            dr, payload, expected
        )
        assert validated["decisions"][0]["classification"] == classification


def test_malformed_or_unknown_method_support_output_fails_closed():
    payload = {
        "schema_version": contextual.METHOD_SUPPORT_SCHEMA_VERSION,
        "decisions": [{
            "paper_id": "UNKNOWN",
            "method_id": "M12",
            "classification": "DIRECT_METHOD_SUPPORT",
            "rationale": "Unknown pair.",
            "doi": "10.1000/forbidden",
        }],
    }

    with pytest.raises(dr.DeepResearchError):
        contextual._validate_method_support_payload(dr, payload, {("P1", "M12")})


def test_method_support_prompt_is_metadata_only_and_rejects_topic_shortcut():
    prompt = contextual._method_support_prompt(
        {
            "methods": [_method("M12", "Gene set construction")],
            "papers": [{
                "paper_id": "P1",
                "title": "Calcium biology",
                "abstract": "Cardiac calcium handling was measured.",
                "journal": "Biology Journal",
                "year": "2024",
            }],
            "pairs": [{"paper_id": "P1", "method_id": "M12"}],
        },
        "codex",
    ).casefold()

    assert "topic relevance is not method support" in prompt
    assert "direct_method_support" in prompt
    assert "insufficient_metadata" in prompt
    assert "methods section" in prompt
    assert "do not web search" in prompt
    assert "doi" in prompt


def test_method_support_uses_existing_runtime_provider_and_schema(tmp_path, monkeypatch):
    calls = {}
    spec = dr.RuntimeSpec(
        "codex", "codex", model="configured-model", timeout=3
    )
    wire_payload = {
        "schema_version": contextual.METHOD_SUPPORT_SCHEMA_VERSION,
        "decisions": [{
            "paper_id": "P1",
            "method_id": "M12",
            "classification": "DIRECT_METHOD_SUPPORT",
            "rationale": "The title and abstract explicitly describe the method.",
        }],
    }

    def build_invocation(_spec, _node, _question, _claim, work_dir):
        return [
            "codex",
            "exec",
            "--output-schema",
            str(work_dir / "deep_research_output.schema.json"),
            "--model",
            "configured-model",
        ], "unused"

    monkeypatch.setattr(dr, "build_invocation", build_invocation)
    monkeypatch.setattr(dr, "resolve_subprocess_executable", lambda value: value)

    def subprocess_invocation(command, prompt):
        calls["command"] = list(command)
        calls["prompt"] = prompt
        return command, {}

    monkeypatch.setattr(dr, "subprocess_invocation", subprocess_invocation)
    monkeypatch.setattr(
        dr,
        "execute_provider_invocation",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(wire_payload),
            stderr="",
        ),
    )
    monkeypatch.setattr(
        dr,
        "skill_receipt",
        lambda *args, **kwargs: {"provider": "codex", "model": "configured-model"},
    )

    result = contextual._run_method_support_adjudication(
        l4p,
        dr,
        tmp_path,
        "C1",
        "Q must not enter the metadata-only prompt",
        "H must not enter the metadata-only prompt",
        spec,
        tmp_path / "work",
        "fixture",
        [_method("M12", "Gene set construction")],
        [_record("P1")],
        _pair_selection(("P1", "M12")),
        inventory_module=l4_inventory,
    )

    assert result["status"] == "completed"
    assert result["decisions"][0]["classification"] == "DIRECT_METHOD_SUPPORT"
    assert str(tmp_path / "work" / "l4a_method_support_output.schema.json") in calls["command"]
    assert "configured-model" in calls["command"]
    assert "Q must not enter" not in calls["prompt"]
    assert "H must not enter" not in calls["prompt"]


def test_zero_direct_is_legal_and_native_manifest_remains_valid(tmp_path):
    record = _record("P1")
    controller = _inventory(_method("M12", "Gene set construction"))
    inventory, assets, selected_ids = contextual._bind_selected_records(
        controller,
        [record],
        _pair_selection(("P1", "M12")),
        _adjudication(("P1", "M12", "INSUFFICIENT_METADATA")),
        {"sources": []},
        l4_inventory,
    )
    assets = l4p._normalize_l4a_assets(assets)
    manifest = {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4A",
        "run_id": "L4A_TEST",
        "project_id": "P1",
        "round_id": "1",
        "candidate_id": "C1",
        "profile_id": "v2.1-catalog-1",
        "question": "Q",
        "claim": "H",
        "question_sha256": "q",
        "claim_sha256": "h",
        "queries": [{
            "query_id": "Q1",
            "query": "gene set construction",
            "purpose": "fixture",
            "status": "completed",
            "receipt": "fixture",
        }],
        "assets": assets,
        "duplicates": [],
        "selected_asset_ids": selected_ids,
        "runtime_receipt": {
            "contextual_literature_search": {
                "method_support_adjudication": _adjudication(
                    ("P1", "M12", "INSUFFICIENT_METADATA")
                ),
            }
        },
        "inventory_schema": l4_inventory.INVENTORY_SCHEMA_VERSION,
        "method_inventory": inventory,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest["path"] = "manifest.json"
    manifest["manifest_sha256"] = l4p._sha256_json(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    ok, reason = l4p.validate_native_l4a_manifest(tmp_path, manifest)

    assert (ok, reason) == (True, "")
    assert inventory[0]["source_asset_ids"] == []


def test_curie_identity_fields_are_unchanged_by_fake_semantic_ranking():
    record = _record("P1")
    before = {
        key: copy.deepcopy(record[key])
        for key in ("paper_id", "identifiers", "provenance")
    }

    rank_method_papers(
        "gene set construction",
        [record],
        ranker=type(
            "FakeRanker",
            (),
            {
                "rank_method_papers": lambda self, _query, rows: [{
                    "paper_id": rows[0]["paper_id"],
                    "semantic_score": 0.5,
                    "semantic_rank": 1,
                }],
            },
        )(),
    )

    assert {
        key: record[key] for key in ("paper_id", "identifiers", "provenance")
    } == before


def test_runtime_spec_reads_configurable_top_k_without_changing_model_routing(tmp_path):
    preflight = tmp_path / "00_Preflight"
    preflight.mkdir()
    (preflight / "deep_research_runtime.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "backend": "codex",
            "executable": "codex",
            "model": "configured-model",
            "top_k_per_method": 3,
            "skill_version": "fixture",
        }),
        encoding="utf-8",
    )

    spec, version = dr.load_runtime_spec(tmp_path)

    assert spec.model == "configured-model"
    assert spec.top_k_per_method == 3
    assert version == "fixture"


def test_specter2_validation_and_configuration_boundaries(monkeypatch):
    from research_loop import l4a_specter2 as specter2

    with pytest.raises(TypeError, match="must be a list"):
        specter2._validate_records("not a list")
    with pytest.raises(TypeError, match="must be an object"):
        specter2._validate_records([None])
    missing_id = _record("P1")
    missing_id["paper_id"] = ""
    with pytest.raises(ValueError, match="no paper_id"):
        specter2._validate_records([missing_id])
    with pytest.raises(ValueError, match="duplicate"):
        specter2._validate_records([_record("P1"), _record("P1")])
    missing_title = _record("P1")
    missing_title["title"] = ""
    with pytest.raises(ValueError, match="no title"):
        specter2._validate_records([missing_title])

    monkeypatch.setenv("RLR_SPECTER2_BATCH_SIZE", "not-an-int")
    assert specter2._configured_batch_size() == specter2.DEFAULT_BATCH_SIZE
    assert specter2._configured_batch_size(0) == specter2.DEFAULT_BATCH_SIZE
    assert specter2._configured_batch_size(3) == 3
    assert specter2._configured_device(_FakeTorch, "auto") == "cpu"
    assert specter2._configured_device(_FakeTorch, "cuda") == "cpu"
    with pytest.raises(ValueError, match="one of auto"):
        specter2._configured_device(_FakeTorch, "tpu")


def test_specter2_ranker_handles_empty_inputs_token_type_ids_and_shape_errors():
    from research_loop import l4a_specter2 as specter2

    class TokenizerWithTokenType(_FakeTokenizer):
        def __call__(self, batch, **kwargs):
            result = super().__call__(batch, **kwargs)
            result["token_type_ids"] = _FakeTensor(
                np.zeros((len(batch), 2), dtype=float)
            )
            return result

    ranker = specter2.Specter2Ranker(
        TokenizerWithTokenType(), _FakeModel(), _FakeTorch, device="cpu", batch_size=2
    )
    assert ranker.rank_method_papers("method", [_record("P0")])
    assert ranker.rank_method_papers("method", []) == []
    with pytest.raises(ValueError, match="must be non-empty"):
        ranker.rank_method_papers("", [_record("P1")])
    with pytest.raises(ValueError, match="empty text batch"):
        ranker._encode([], "proximity")

    class BadHiddenModel(_FakeModel):
        def __call__(self, **_inputs):
            return SimpleNamespace(last_hidden_state=_FakeTensor([[1.0, 2.0]]))

    with pytest.raises(specter2.Specter2Error, match="3-dimensional"):
        specter2.Specter2Ranker(
            _FakeTokenizer(), BadHiddenModel(), _FakeTorch, device="cpu"
        ).rank_method_papers("method", [_record("P1")])

    class BadShapeTorch(_FakeTorch):
        @staticmethod
        def cat(_chunks, dim=0):
            return _FakeTensor([1.0])

    with pytest.raises(specter2.Specter2Error, match="shape"):
        specter2.Specter2Ranker(
            _FakeTokenizer(), _FakeModel(), BadShapeTorch, device="cpu"
        ).rank_method_papers("method", [_record("P1")])


def test_specter2_ranker_rejects_nonfinite_similarity_at_both_runtime_boundaries():
    from research_loop import l4a_specter2 as specter2

    class NaNModel(_FakeModel):
        def __call__(self, **inputs):
            values = inputs["input_ids"].data
            hidden = np.full((values.shape[0], 1, 2), np.nan, dtype=float)
            return SimpleNamespace(last_hidden_state=_FakeTensor(hidden))

    ranker = specter2.Specter2Ranker(
        _FakeTokenizer(), NaNModel(), _FakeTorch, device="cpu"
    )
    with pytest.raises(specter2.Specter2Error, match="non-finite"):
        ranker.rank_method_papers("method", [_record("P1")])

    class TrustingFiniteTorch(_FakeTorch):
        @staticmethod
        def isfinite(_value):
            return SimpleNamespace(all=lambda: True)

    ranker = specter2.Specter2Ranker(
        _FakeTokenizer(), NaNModel(), TrustingFiniteTorch, device="cpu"
    )
    with pytest.raises(specter2.Specter2Error, match="non-finite"):
        ranker.rank_method_papers("method", [_record("P1")])


@pytest.mark.parametrize(
    "raw, expected_type, message",
    [
        ("not a list", TypeError, "result must be a list"),
        ([None], TypeError, "result item must be an object"),
        ([{"paper_id": "P1", "semantic_score": "bad"}], ValueError, "not numeric"),
        ([{"paper_id": "P1", "semantic_score": float("nan")}], ValueError, "not finite"),
        (
            [
                {"paper_id": "P1", "semantic_score": 0.2, "semantic_rank": 1},
                {"paper_id": "P1", "semantic_score": 0.1, "semantic_rank": 2},
            ],
            ValueError,
            "duplicate",
        ),
        (
            [
                {"paper_id": "P1", "semantic_score": 0.2, "semantic_rank": 1},
                {"paper_id": "P2", "semantic_score": 0.1, "semantic_rank": 3},
            ],
            ValueError,
            "contiguous",
        ),
    ],
)
def test_public_specter2_ranker_rejects_malformed_result(raw, expected_type, message):
    class FakeRanker:
        def rank_method_papers(self, _query, _records):
            return raw

    with pytest.raises(expected_type, match=message):
        rank_method_papers("method", [_record("P1"), _record("P2")], ranker=FakeRanker())


def test_public_specter2_ranker_requires_rank_method_and_receipt_is_preserved():
    from research_loop import l4a_specter2 as specter2

    with pytest.raises(TypeError, match="must expose"):
        rank_method_papers("method", [_record("P1")], ranker=object())

    class ReceiptRanker:
        def receipt(self):
            return {"implementation": "fixture", "device": "cpu"}

    assert specter2.ranker_receipt(ReceiptRanker()) == {
        "implementation": "fixture",
        "device": "cpu",
    }

    class NonMappingReceiptRanker:
        def receipt(self):
            return ["not", "a", "receipt"]

    assert specter2.ranker_receipt(NonMappingReceiptRanker())["injected"] is True


def test_specter2_loader_rethrows_its_own_runtime_error(monkeypatch):
    from research_loop import l4a_specter2 as specter2

    fake_torch = ModuleType("torch")

    class _Cuda:
        @staticmethod
        def is_available():
            return False

    fake_torch.cuda = _Cuda
    fake_adapters = ModuleType("adapters")
    fake_transformers = ModuleType("transformers")
    model = _FakeModel()
    tokenizer = _FakeTokenizer()

    class AutoAdapterModel:
        @staticmethod
        def from_pretrained(*_args, **_kwargs):
            return model

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(*_args, **_kwargs):
            return tokenizer

    fake_adapters.AutoAdapterModel = AutoAdapterModel
    fake_transformers.AutoTokenizer = AutoTokenizer
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "adapters", fake_adapters)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setattr(
        specter2,
        "_configured_device",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            specter2.Specter2Error("sentinel runtime error")
        ),
    )

    with pytest.raises(specter2.Specter2Error, match="sentinel runtime error"):
        specter2.Specter2Ranker.from_pretrained()


def test_specter2_ranker_is_process_scoped_and_lazy(monkeypatch):
    from research_loop import l4a_specter2 as specter2

    calls = []

    class CachedRanker:
        pass

    def fake_loader(cls):
        calls.append(cls)
        return CachedRanker()

    monkeypatch.setattr(
        specter2.Specter2Ranker,
        "from_pretrained",
        classmethod(fake_loader),
    )
    specter2._cached_specter2_ranker.cache_clear()
    try:
        first = specter2.get_specter2_ranker()
        second = specter2.get_specter2_ranker()
    finally:
        specter2._cached_specter2_ranker.cache_clear()

    assert first is second
    assert len(calls) == 1
