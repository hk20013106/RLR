# SPECTER2 official-source audit

**Audit date:** 2026-09-02
**Scope:** Bounded primary-source verification for the RLR SPECTER2 integration. No production code or benchmark/evidence directory was changed; no git metadata, branch, index, or tracked file was changed. This requested note is the only new untracked file.

## Findings

| Item | Official finding |
| --- | --- |
| Base checkpoint | Use `allenai/specter2_base` as the base model with the adapters. The Hugging Face card describes the model as `bert-base-uncased + adapters` and says it is finetuned from `allenai/scibert`. |
| Proximity/retrieval adapter | The post-rename Hugging Face adapter repository is `allenai/specter2`; its card identifies it as the adapter for `allenai/specter2_base` and as the retrieval-specific adapter for paper queries and candidate papers. |
| Adhoc query adapter | Use `allenai/specter2_adhoc_query` for short raw-text search queries. Candidate papers are encoded with the proximity adapter. |
| Paper input construction | Construct each paper string as `title + tokenizer.sep_token + (abstract or '')`. The query-card example keeps a short textual query as raw text, e.g. `"Bidirectional transformers"`. |
| Tokenization/inference | The official examples use `padding=True`, `truncation=True`, `return_tensors="pt"`, `return_token_type_ids=False`, and `max_length=512`, through `AutoAdapterModel`. |
| Embedding | Use the first-token/CLS representation: `output.last_hidden_state[:, 0, :]`. |
| Hardware constraint | The README explicitly marks the multiple-task batch-processing path as requiring a GPU. It does not state that the basic single-adapter example requires a GPU; the official examples cap tokenized inputs at 512 tokens. |

## Naming caveat

The AllenAI README records the rename `allenai/specter2` (old base) -> `allenai/specter2_base` and `allenai/specter2_proximity` (old proximity adapter) -> `allenai/specter2`. Its simple current-style example therefore loads `allenai/specter2_base` and the `allenai/specter2` adapter. However, the same README later still lists `allenai/specter2_proximity` in the Hugging Face table and multi-task example, and uses `allenai/specter2` as the multi-task `base_checkpoint`. Treat those entries as an internal documentation inconsistency/legacy naming path. Keep remote repository IDs distinct from the local `load_as` label (`proximity`, `specter2`, or another label shown in the examples).

## Official sources

- [AllenAI SPECTER2 README](https://github.com/allenai/SPECTER2/blob/main/README.md)
- [Hugging Face: `allenai/specter2_base`](https://huggingface.co/allenai/specter2_base)
- [Hugging Face: `allenai/specter2` proximity adapter](https://huggingface.co/allenai/specter2)
- [Hugging Face: `allenai/specter2_adhoc_query` adapter](https://huggingface.co/allenai/specter2_adhoc_query)
