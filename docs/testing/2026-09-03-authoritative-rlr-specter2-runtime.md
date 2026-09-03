# Authoritative RLR / PaperQA2 / SPECTER2 runtime

This receipt records the formal runtime established on 2026-09-03. It is a
runtime/readiness record only: no real L4A-to-L4B E2E was run.

## Formal environment

There is one production environment: Micromamba `rlr`.

```text
environment name = rlr
environment path = D:\research_loop\_runtime\micromamba-root\envs\rlr
python executable = D:\research_loop\_runtime\micromamba-root\envs\rlr\python.exe
python = 3.13.15 | packaged by conda-forge
user site = disabled (PYTHONNOUSERSITE=1)
```

The checked-in owner is [`environment.yml`](../../environment.yml). Create the
environment with Python 3.13, then install the pip layer only through the same
interpreter:

```powershell
micromamba create --channel-priority strict --root-prefix D:\research_loop\_runtime\micromamba-root `
  -f environment.yml
micromamba run -n rlr python -m pip install -r requirements-specter2.txt
micromamba run -n rlr python -m pip install -e D:\research_loop\paper-qa
```

`environment.yml` owns Python, Micromamba/conda-forge lower dependencies, and
test dependencies. `requirements.txt` owns the RLR core pip requirements;
`requirements-specter2.txt` owns the verified SPECTER2 and PaperQA2 cross-stack
pins. The PaperQA2 source checkout remains pinned by its own checked-out tag
and commit (`v2026.08.12`,
`57e89f7223b0960d5ee5ea048c69e3c47e088572`). No old environment is an install
source.

## Python 3.13 decision and dependency audit

Python 3.13 was attempted first and succeeded. No hard dependency conflict
required Python 3.12, and Python 3.10 was not used for the formal runtime.

The repository RLR manifests do not declare a `requires-python` floor; the
RLR code and test suite passed on 3.13. PaperQA2 declares `requires-python >=3.11`,
so it admits 3.13. The resolver installed the pinned CPU SPECTER2 stack under
3.13, and the production forward passed. The current torch wheel/conda package,
`transformers==4.35.2`, and `adapters==0.1.0` therefore have a directly
observed 3.13 installation/runtime result here; no downgrade inference was
needed.

Observed versions in the same interpreter:

```text
torch = 2.13.0 (+cpu)
transformers = 4.35.2
adapters = 0.1.0
psutil = 7.2.2
jsonschema = 4.26.0
pytest = 9.1.1
paper-qa = 2026.8.12
fhaviary = 0.36.0
fhlmi = 0.45.0
litellm = 1.81.10
tokenizers = 0.15.2
huggingface-hub = 0.20.3
```

The `fhlmi`/`litellm`/`tokenizers` pins preserve the `transformers==4.35.2`
tokenizer contract. `huggingface-hub==0.20.3` is required by the installed
`adapters==0.1.0` API (`url_to_filename`). `pip check` passes with user-site
isolation enabled.

## Same-process and integration evidence

The formal runtime preflight is:

```powershell
$env:PYTHONPATH = "D:\research_loop\l4a-specter2-method-support-20260902\src"
$env:HF_HOME = "D:\research_loop\model_cache\huggingface"
$env:HF_HUB_CACHE = "D:\research_loop\model_cache\huggingface\hub"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:RLR_SPECTER2_DEVICE = "cpu"
micromamba run -n rlr python -m research_loop.runtime_preflight
```

It returned `status=PASS`, using the formal `rlr` executable. One process
imported `research_loop`, the runner, `paperqa.Docs`, `paperqa.Settings`, the
RLR PaperQA2 runtime bridge, and production `Specter2Ranker`. Its real
two-candidate forward returned finite cosine scores in `[-1, 1]` and recorded
adapter activation `proximity` followed by `adhoc_query`.

The model identity was unchanged:

```text
base = allenai/specter2_base@3447645e1def9117997203454fa4495937bfbd83
paper/proximity = allenai/specter2@2081559630a80fc5851d8f798a05ba81e9468089
query = allenai/specter2_adhoc_query@3f4448817028388648a74349ece07af4518ec5bd
```

The existing PaperQA2 integration bridge also passed in `rlr` against the real
fixture PDF. It exercised `Docs.aadd`, sparse retrieval, MMR, and evidence
assembly, and returned four hits with the pinned PaperQA2 commit receipt. This
was a bounded local smoke, not a large-scale literature run.

## Test evidence

```text
targeted L4A/SPECTER2/PaperQA2/L0 tests = 87 passed in 7.00s
full command = micromamba run -n rlr python -m pytest -q --no-header -p no:cacheprovider
full suite = 1202 passed in 622.39s (10:22)
full exit code = 0
timestamp failure = not reproduced in the formal Python 3.13 environment
```

The previously observed strict `_now()` timestamp failure was not changed or
masked; this fresh run did not reproduce it.

## Interpreter drift and boundaries

Active production subprocesses use `sys.executable` or the existing explicit
interpreter field; no active production path hard-codes `poc_envs\specter2`,
`paper-qa\.venv`, Miniforge base, or a second Python executable. Historical
receipts and archived plans may mention those paths, but they are not runtime
owners.

`runtime_preflight` is fail-closed: a wrong interpreter, Python version,
missing/mismatched package, import failure, or adapter-forward failure returns
exit code 3. It performs no installation, interpreter switching, or fallback.
Run it immediately before any formal L4A/SPECTER2 research execution.

```text
production scientific code modified = NO
real L4A-to-L4B E2E = NO
```
