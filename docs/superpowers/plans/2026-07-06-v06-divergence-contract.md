# v0.6 Divergence-Contract Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the RLR loop structurally divergent — carry loop memory, literature cards, and branch/method/modality traceability as enforced system state instead of relying on agent memory.

**Architecture:** Extend `DELTA_SCHEMAS` with optional fields, add file-based artifacts (loop-memory seed, paper/method cards, ledgers, exec manifest), add gates that hard-fail only for `--from-memory` divergent candidates, and route literature work through ARS agents via a token-firewall adapter. All new fields optional → legacy candidates C1/C2 keep validating.

**Tech Stack:** Python 3 stdlib (json, re, hashlib, pathlib, argparse), pytest, ARS agents (`synthesis_agent`, `research_architect_agent`), PubMed/bioRxiv MCP fallback.

## Global Constraints

- Branch `v0.6`. Do NOT start v0.7. Do NOT push.
- All new `DELTA_SCHEMAS` fields are OPTIONAL; hard-fail only when candidate frontmatter `from_memory: true`.
- No delta may store full paper/method text — card IDs + hashes only.
- Do NOT touch: provenance-gate core logic, `caveman-lite`, candidate-isolation logic (unless a concrete reproduced bug), the hand-verified BH/FDR implementation.
- `divergence.min_new_query_families = 2`.
- Implementation limited to `research_loop_v04.py` + new `ars_card_adapter.py` + `tests/`. No candidate/report edits.
- Every code step is TDD: failing test first, then minimal impl.
- Commit locally after each task. Never push. Never `--no-verify`.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

- `research_loop_v04.py` — schemas, gates, CLI subcommands (all edits here).
- `ars_card_adapter.py` — NEW. ARS-output → compact paper/method card JSON. Token firewall.
- `tests/test_v06_divergence.py` — NEW. All 13 test groups.
- `tests/fixtures/` — NEW. Minimal project + seed + delta fixtures.

Artifacts produced at runtime (not code):
- `08_Audit/loop_memory/<cand>_next_loop_memory.{json,md}`
- `09_Literature_Database/paper_cards/<id>.json`, `method_cards/<id>.json`, `query_families.json`
- `08_Audit/branch_ledger/<cand>.json`, `08_Audit/modality_ledger/<cand>.json`
- `04_Analysis_Outputs/_exec_manifest/<cand>_L7.json`
- `FINAL_REPORT_<cand>.md`, `00_Reports_Index.md`

---

## Task 1: Config + `loop_type`/`from_memory` frontmatter + `new-candidate --from-memory`

**Files:**
- Modify: `research_loop_v04.py` (`_candidate_template_v03`, `cmd_new_candidate` :2855-2872, argparse `new-candidate` :4000)
- Test: `tests/test_v06_divergence.py`

**Interfaces:**
- Produces: candidate frontmatter keys `from_memory: bool`, `loop_type: str`, `prior_candidate: str`, `memory_file: str`, `memory_hash: str`. Helper `_sha256_file(path) -> str`. Helper `_load_loop_memory(path) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_v06_divergence.py
import json, subprocess, sys, hashlib
from pathlib import Path
import pytest

RL = str(Path(__file__).resolve().parent.parent / "research_loop_v04.py")

def _run(*args, cwd=None):
    return subprocess.run([sys.executable, RL, *args], capture_output=True, text=True, cwd=cwd)

def _new_project(tmp_path):
    r = _run("new-project", str(tmp_path / "P"), "Test")
    assert r.returncode == 0, r.stderr
    return tmp_path / "P"

def _write_seed(proj, cand="C_prev"):
    d = proj / "08_Audit" / "loop_memory"; d.mkdir(parents=True, exist_ok=True)
    seed = {
        "source_candidate_id": cand, "terminal_node": "L10c", "terminal_decision": "DOWNGRADE",
        "original_question": "Q0", "previous_hypothesis": "H_prev", "final_reason": "R",
        "next_round_hypothesis": "H_next", "required_new_search_directions": ["dir_a", "dir_b"],
        "evidence_kept": [], "evidence_dropped": [], "explored_branches": ["b1"],
        "unexplored_branches": [{"id": "b_atrial", "why": "deferred", "data_available": True, "data_path": "x/atrial.csv"}],
        "data_modalities_used": ["transcriptomic_DEG"], "data_modalities_available_unused": ["atrial_DEG"],
        "paper_card_ids": [], "method_card_ids": [], "hashes": {},
    }
    p = d / f"{cand}_next_loop_memory.json"; p.write_text(json.dumps(seed), encoding="utf-8")
    return p

def test_new_candidate_from_memory_records_hash_and_loop_type(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q",
             "--claim", "C", "--input", "in", "--from-memory", str(seed),
             "--loop-type", "divergent")
    assert r.returncode == 0, r.stderr
    cand_id = r.stdout.strip().splitlines()[0]
    cf = next(proj.rglob(f"{cand_id}.md"))
    txt = cf.read_text(encoding="utf-8")
    assert "from_memory: true" in txt
    assert "loop_type: divergent" in txt
    assert "prior_candidate: C_prev" in txt
    h = hashlib.sha256(seed.read_bytes()).hexdigest()
    assert h in txt

def test_new_candidate_from_memory_rejects_missing_seed(tmp_path):
    proj = _new_project(tmp_path)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q",
             "--claim", "C", "--input", "in", "--from-memory", str(proj / "nope.json"),
             "--loop-type", "divergent")
    assert r.returncode != 0
    assert "seed" in (r.stderr + r.stdout).lower()

def test_new_candidate_from_memory_requires_loop_type(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q",
             "--claim", "C", "--input", "in", "--from-memory", str(seed))
    assert r.returncode != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/research_loop && python -m pytest tests/test_v06_divergence.py -k from_memory -v`
Expected: FAIL (`--from-memory` unknown arg / assertions fail).

- [ ] **Step 3: Write minimal implementation**

Add helpers near other file helpers in `research_loop_v04.py`:

```python
import hashlib

def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _load_loop_memory(path):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"loop-memory seed not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"invalid loop-memory seed JSON: {e}")
    required = {"source_candidate_id", "next_round_hypothesis", "required_new_search_directions"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"loop-memory seed missing keys: {sorted(missing)}")
    return data
```

In `cmd_new_candidate`, before writing the body, resolve memory:

```python
    from_memory = getattr(args, "from_memory", None)
    loop_type = getattr(args, "loop_type", None) or ""
    mem_fields = {}
    if from_memory:
        if not loop_type:
            print("ERROR: --from-memory requires --loop-type", file=sys.stderr)
            return 2
        try:
            mem = _load_loop_memory(from_memory)
        except (FileNotFoundError, ValueError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        mem_fields = {
            "from_memory": True, "loop_type": loop_type,
            "prior_candidate": mem["source_candidate_id"],
            "memory_file": str(from_memory),
            "memory_hash": _sha256_file(from_memory),
        }
```

Extend `_candidate_template_v03` signature to accept `extra_front: dict = None` and emit those keys into the YAML frontmatter block (append `key: value`, booleans lowercased). Pass `extra_front=mem_fields` from `cmd_new_candidate`.

Add argparse to the `new-candidate` parser:

```python
    sp.add_argument("--from-memory", dest="from_memory", default=None,
                    help="path to a next_loop_memory.json seed")
    sp.add_argument("--loop-type", dest="loop_type", default=None,
                    choices=["divergent", "correction", "data-acquisition"],
                    help="required with --from-memory")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v06_divergence.py -k from_memory -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add research_loop_v04.py tests/test_v06_divergence.py
git commit -m "feat(v0.6): candidate creation from loop-memory seed with loop_type

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `emit-loop-memory` subcommand (JSON + MD seed)

**Files:**
- Modify: `research_loop_v04.py` (new `cmd_emit_loop_memory`, `SEED_SCHEMA_KEYS`, argparse)
- Test: `tests/test_v06_divergence.py`

**Interfaces:**
- Consumes: existing `_delta_for_candidate`, `_load_yaml_front`, `_candidate_file`, `DELTA_DAG_ORDER`.
- Produces: `08_Audit/loop_memory/<cand>_next_loop_memory.json` + `.md`; function `_build_loop_memory(project_dir, cand_id) -> dict`. Introduces empty stubs `_read_branch_ledger`, `_read_modality_ledger`, `_list_card_ids` (real bodies in Tasks 4/10).

- [ ] **Step 1: Write the failing test**

```python
def _seed_candidate_with_deltas(proj):
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q0",
             "--claim", "C", "--input", "in")
    cand = r.stdout.strip().splitlines()[0]
    notes = proj / "02_Agent_Notes"
    def drop(persona, key, obj):
        d = notes / persona; d.mkdir(parents=True, exist_ok=True)
        obj = {**obj, "candidate_id": cand}
        (d / f"{cand}_{key}_delta.json").write_text(json.dumps(obj), encoding="utf-8")
    drop("Einstein", "L1_einstein", {"hypotheses": [{"id": "H1", "text": "h", "testable": True, "rationale": "r"}],
         "key_uncertainty": "u", "primary_hypothesis": "H1", "candidate_branches": [{"id": "b1", "description": "d"}]})
    drop("Oppenheimer", "L10b_oppenheimer", {"decision": "DOWNGRADE", "evidence_level": "weak",
         "reason": "because", "next_steps": [], "next_round_hypothesis": "H_next"})
    return cand

def test_emit_loop_memory_deterministic_and_schema(tmp_path):
    proj = _new_project(tmp_path)
    cand = _seed_candidate_with_deltas(proj)
    r1 = _run("emit-loop-memory", str(proj), cand)
    assert r1.returncode == 0, r1.stderr
    seed = proj / "08_Audit" / "loop_memory" / f"{cand}_next_loop_memory.json"
    md = proj / "08_Audit" / "loop_memory" / f"{cand}_next_loop_memory.md"
    assert seed.exists() and md.exists()
    data = json.loads(seed.read_text(encoding="utf-8"))
    assert data["source_candidate_id"] == cand
    assert data["next_round_hypothesis"] == "H_next"
    assert data["terminal_decision"] == "DOWNGRADE"
    assert data["original_question"] == "Q0"
    for k in ("required_new_search_directions", "unexplored_branches",
              "data_modalities_used", "paper_card_ids", "hashes"):
        assert k in data
    first = seed.read_text(encoding="utf-8")
    _run("emit-loop-memory", str(proj), cand)
    assert seed.read_text(encoding="utf-8") == first  # deterministic
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v06_divergence.py -k emit_loop_memory -v`
Expected: FAIL (`emit-loop-memory` unknown command).

- [ ] **Step 3: Write minimal implementation**

```python
SEED_SCHEMA_KEYS = [
    "source_candidate_id", "terminal_node", "terminal_decision", "original_question",
    "previous_hypothesis", "final_reason", "next_round_hypothesis",
    "required_new_search_directions", "evidence_kept", "evidence_dropped",
    "explored_branches", "unexplored_branches", "data_modalities_used",
    "data_modalities_available_unused", "paper_card_ids", "method_card_ids", "hashes",
]

# Empty-default stubs; real bodies land in Tasks 4/10 (NOT placeholders — callable now).
def _read_branch_ledger(project_dir, cand_id):
    return {"branches": []}

def _read_modality_ledger(project_dir, cand_id):
    return {"used": [], "available_unused": []}

def _list_card_ids(project_dir, cand_id, sub):
    return []

def _build_loop_memory(project_dir, cand_id):
    project_dir = Path(project_dir)
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    def _d(key):
        p = _delta_for_candidate(project_dir, key, cand_id)
        if p and p.exists():
            try: return json.loads(p.read_text(encoding="utf-8"))
            except Exception: return {}
        return {}
    l1 = _d("L1_einstein"); l10 = _d("L10b_oppenheimer")
    branches = l1.get("candidate_branches", []) or []
    bl = _read_branch_ledger(project_dir, cand_id)
    ml = _read_modality_ledger(project_dir, cand_id)
    return {
        "source_candidate_id": cand_id,
        "terminal_node": "L10c",
        "terminal_decision": l10.get("decision", ""),
        "original_question": fm.get("question", ""),
        "previous_hypothesis": l1.get("primary_hypothesis", ""),
        "final_reason": l10.get("reason", ""),
        "next_round_hypothesis": l10.get("next_round_hypothesis", ""),
        "required_new_search_directions": l10.get("next_steps", []) or [],
        "evidence_kept": l10.get("evidence_kept", []) or [],
        "evidence_dropped": l10.get("evidence_dropped", []) or [],
        "explored_branches": [b.get("id") for b in branches],
        "unexplored_branches": [b for b in bl.get("branches", []) if b.get("status") == "ignored"],
        "data_modalities_used": ml.get("used", []),
        "data_modalities_available_unused": ml.get("available_unused", []),
        "paper_card_ids": _list_card_ids(project_dir, cand_id, "paper_cards"),
        "method_card_ids": _list_card_ids(project_dir, cand_id, "method_cards"),
        "hashes": {},
    }

def _loop_memory_to_md(mem):
    out = [f"# Next-Loop Memory — {mem['source_candidate_id']}", ""]
    for k in SEED_SCHEMA_KEYS:
        out.append(f"## {k}")
        v = mem.get(k)
        out.append(json.dumps(v, ensure_ascii=False, indent=2) if isinstance(v, (list, dict)) else str(v))
        out.append("")
    return "\n".join(out)

def cmd_emit_loop_memory(args):
    project_dir = Path(args.project_dir)
    mem = _build_loop_memory(project_dir, args.cand_id)
    out_dir = project_dir / "08_Audit" / "loop_memory"; out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / f"{args.cand_id}_next_loop_memory.json"
    jp.write_text(json.dumps(mem, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    mp = out_dir / f"{args.cand_id}_next_loop_memory.md"
    mp.write_text(_loop_memory_to_md(mem), encoding="utf-8")
    print(f"loop-memory written:\n  {jp}\n  {mp}")
    return 0
```

Register argparse:

```python
    sp = sub.add_parser("emit-loop-memory", help="L10c: emit next_loop_memory seed (JSON+MD)")
    sp.add_argument("project_dir"); sp.add_argument("cand_id")
    sp.set_defaults(func=cmd_emit_loop_memory)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v06_divergence.py -k emit_loop_memory -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research_loop_v04.py tests/test_v06_divergence.py
git commit -m "feat(v0.6): emit-loop-memory subcommand writes JSON+MD seed

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: L0 `prior_loop_memory` schema + injection + memory-hash gate

**Files:**
- Modify: `research_loop_v04.py` (`DELTA_SCHEMAS["L0_linnaeus"]` :440, `cmd_assemble_context` L0 branch, `cmd_emit_delta` L0 validation :2024)
- Test: `tests/test_v06_divergence.py`

**Interfaces:**
- Consumes: candidate frontmatter `from_memory`, `memory_file`, `memory_hash` (Task 1).
- Produces: gate `_audit_l0_memory(project_dir, cand_id, delta) -> (ok, reason)`.

- [ ] **Step 1: Write the failing test**

```python
def test_l0_memory_gate_rejects_missing_prior_memory(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q",
             "--claim", "C", "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    d = proj / "02_Agent_Notes" / "Linnaeus"; d.mkdir(parents=True, exist_ok=True)
    bad = {"skills_found": [], "skills_gaps": [], "input_verified": {}, "environment": {},
           "skill_use_plan": [], "forbidden_shortcuts": [], "candidate_id": cand}
    f = tmp_path / "l0.json"; f.write_text(json.dumps(bad), encoding="utf-8")
    r2 = _run("emit-delta", str(proj), "--node", "L0", "--persona", "Linnaeus",
              "--file", str(f), "--cand-id", cand)
    assert r2.returncode != 0
    assert "prior_loop_memory" in (r2.stderr + r2.stdout)

def test_l0_memory_gate_accepts_matching_hash(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q",
             "--claim", "C", "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    h = hashlib.sha256(seed.read_bytes()).hexdigest()
    good = {"skills_found": [], "skills_gaps": [], "input_verified": {}, "environment": {},
            "skill_use_plan": [], "forbidden_shortcuts": [],
            "prior_loop_memory": {"source_candidate_id": "C_prev", "loaded_from": str(seed),
                "memory_hash": h, "previous_hypothesis": "H_prev", "final_decision": "DOWNGRADE",
                "next_round_hypothesis": "H_next", "required_new_search_directions": ["dir_a", "dir_b"],
                "evidence_kept": [], "evidence_dropped": [], "unexplored_branches": [],
                "data_modalities_available_unused": []},
            "candidate_id": cand}
    f = tmp_path / "l0ok.json"; f.write_text(json.dumps(good), encoding="utf-8")
    r2 = _run("emit-delta", str(proj), "--node", "L0", "--persona", "Linnaeus",
              "--file", str(f), "--cand-id", cand)
    assert r2.returncode == 0, r2.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v06_divergence.py -k l0_memory -v`
Expected: FAIL (gate absent; both accept).

- [ ] **Step 3: Write minimal implementation**

Add optional field to schema:

```python
    "L0_linnaeus": {
        "skills_found": list, "skills_gaps": list, "input_verified": dict,
        "environment": dict, "skill_use_plan": list, "forbidden_shortcuts": list,
        "prior_loop_memory": dict,   # optional; required only when from_memory
    },
```

Add gate:

```python
def _audit_l0_memory(project_dir, cand_id, delta):
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    plm = delta.get("prior_loop_memory")
    if not plm:
        return False, "candidate is from_memory but L0 delta lacks `prior_loop_memory`"
    expected = fm.get("memory_hash", "")
    if plm.get("memory_hash") != expected:
        return False, (f"prior_loop_memory.memory_hash mismatch: "
                       f"delta={plm.get('memory_hash')!r} frontmatter={expected!r}")
    for req in ("previous_hypothesis", "next_round_hypothesis", "required_new_search_directions"):
        if not plm.get(req):
            return False, f"prior_loop_memory missing `{req}`"
    return True, ""
```

In `cmd_emit_delta`, after existing L0 schema validation (`if delta_key == "L0_linnaeus":` at :2024), call the gate:

```python
        ok, reason = _audit_l0_memory(project_dir, args.cand_id, delta)
        if not ok:
            print(f"ERROR: L0 memory gate failed: {reason}", file=sys.stderr)
            return 3
```

In `cmd_assemble_context` L0 branch, if `fm.get("from_memory")`, read `memory_file` and inject a compact `PRIOR LOOP MEMORY` block (IDs + hypotheses + required directions + unexplored branch ids only — never full text).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v06_divergence.py -k l0_memory -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add research_loop_v04.py tests/test_v06_divergence.py
git commit -m "feat(v0.6): L0 prior_loop_memory field, injection, and hash gate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Paper/method cards + `ars_card_adapter.py` (token firewall)

**Files:**
- Create: `ars_card_adapter.py`
- Modify: `research_loop_v04.py` (`_list_card_ids` real body)
- Test: `tests/test_v06_divergence.py`

**Interfaces:**
- Produces: `write_paper_card(project_dir, card) -> str(id)`, `write_method_card(project_dir, card) -> str(id)`, `ars_output_to_cards(project_dir, ars_payload) -> {"paper_cards": [...], "method_cards": [...]}`. Card id = `sha1(pmid|doi|title)[:12]` (paper), `sha1(source_paper_card_id|method_name)[:12]` (method).

- [ ] **Step 1: Write the failing test**

```python
import ars_card_adapter as aca

def test_paper_card_round_trip_no_abstract_in_card(tmp_path):
    proj = _new_project(tmp_path)
    cid = aca.write_paper_card(proj, {"pmid": "12345678", "doi": "10.1/x", "url": "http://x",
        "title": "Paper A", "year": 2020, "journal": "J", "one_line": "relevant",
        "claims_used": ["c1"], "query_family_id": "qf1"})
    p = proj / "09_Literature_Database" / "paper_cards" / f"{cid}.json"
    assert p.exists()
    card = json.loads(p.read_text(encoding="utf-8"))
    assert card["pmid"] == "12345678"
    assert "abstract" not in card
    assert card["one_line"] == "relevant"

def test_ars_output_to_cards_strips_prose(tmp_path):
    proj = _new_project(tmp_path)
    payload = {"papers": [{"pmid": "999", "doi": "10.9/y", "title": "P", "year": 2019,
                "journal": "J2", "url": "u", "apa": "Long APA prose ...", "relevance": "one line"}],
               "methods": [{"source_pmid": "999", "method_name": "AFM", "measurement_type": "mechanical",
                "data_modality": "tissue_mechanics", "key_parameters": {"probe": "x"},
                "applicability": "direct", "extracted_from": "full_text", "full_text_fetched": True}]}
    out = aca.ars_output_to_cards(proj, payload)
    assert len(out["paper_cards"]) == 1 and len(out["method_cards"]) == 1
    mc_id = out["method_cards"][0]
    mc = json.loads((proj / "09_Literature_Database" / "method_cards" / f"{mc_id}.json").read_text(encoding="utf-8"))
    assert mc["extracted_from"] == "full_text" and "apa" not in mc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v06_divergence.py -k card -v`
Expected: FAIL (`ars_card_adapter` missing).

- [ ] **Step 3: Write minimal implementation**

```python
# ars_card_adapter.py
"""ARS-output -> compact paper/method card JSON. Token firewall: no APA prose,
abstracts, or full text ever enter a card. Cards store IDs + one-line + provenance."""
import json, hashlib
from pathlib import Path

_PAPER_KEYS = ["id", "pmid", "doi", "url", "title", "year", "journal", "one_line",
               "claims_used", "query_family_id", "retrieved_at", "hash"]
_METHOD_KEYS = ["id", "source_paper_card_id", "method_name", "measurement_type",
                "data_modality", "key_parameters", "applicability", "extracted_from",
                "full_text_fetched", "extracted_at"]

def _card_id(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts if p).encode("utf-8")).hexdigest()[:12]

def _paper_cards_dir(project_dir):
    d = Path(project_dir) / "09_Literature_Database" / "paper_cards"; d.mkdir(parents=True, exist_ok=True); return d

def _method_cards_dir(project_dir):
    d = Path(project_dir) / "09_Literature_Database" / "method_cards"; d.mkdir(parents=True, exist_ok=True); return d

def write_paper_card(project_dir, card):
    cid = card.get("id") or _card_id(card.get("pmid"), card.get("doi"), card.get("title"))
    clean = {k: card.get(k) for k in _PAPER_KEYS}
    clean["id"] = cid
    clean["hash"] = _card_id("h", cid, card.get("title"))
    (_paper_cards_dir(project_dir) / f"{cid}.json").write_text(
        json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return cid

def write_method_card(project_dir, card):
    cid = card.get("id") or _card_id(card.get("source_paper_card_id"), card.get("method_name"))
    clean = {k: card.get(k) for k in _METHOD_KEYS}
    clean["id"] = cid
    (_method_cards_dir(project_dir) / f"{cid}.json").write_text(
        json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return cid

def ars_output_to_cards(project_dir, ars_payload):
    paper_ids, method_ids, pmid_to_card = [], [], {}
    for p in ars_payload.get("papers", []):
        cid = write_paper_card(project_dir, {
            "pmid": p.get("pmid"), "doi": p.get("doi"), "url": p.get("url"),
            "title": p.get("title"), "year": p.get("year"), "journal": p.get("journal"),
            "one_line": p.get("relevance") or p.get("one_line", ""),
            "claims_used": p.get("claims_used", []), "query_family_id": p.get("query_family_id", ""),
        })
        paper_ids.append(cid)
        if p.get("pmid"): pmid_to_card[str(p["pmid"])] = cid
    for m in ars_payload.get("methods", []):
        src = pmid_to_card.get(str(m.get("source_pmid", "")), "")
        method_ids.append(write_method_card(project_dir, {
            "source_paper_card_id": src, "method_name": m.get("method_name"),
            "measurement_type": m.get("measurement_type"), "data_modality": m.get("data_modality"),
            "key_parameters": m.get("key_parameters", {}), "applicability": m.get("applicability", ""),
            "extracted_from": m.get("extracted_from", "abstract"),
            "full_text_fetched": bool(m.get("full_text_fetched", False)),
        }))
    return {"paper_cards": paper_ids, "method_cards": method_ids}
```

Replace the `_list_card_ids` stub in `research_loop_v04.py` with the real body:

```python
def _list_card_ids(project_dir, cand_id, sub):
    d = Path(project_dir) / "09_Literature_Database" / sub
    if not d.exists(): return []
    return sorted(p.stem for p in d.glob("*.json"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v06_divergence.py -k card -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ars_card_adapter.py research_loop_v04.py tests/test_v06_divergence.py
git commit -m "feat(v0.6): ARS card adapter + paper/method card writers (token firewall)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: L1 divergence gate (>=2 new query families)

**Files:**
- Modify: `research_loop_v04.py` (`DELTA_SCHEMAS["L1_einstein"] += candidate_branches`, `_audit_divergence`, `_query_family_key`, `_load_query_family_cache`, config `DIVERGENCE_MIN_NEW_QUERY_FAMILIES`, hook in `cmd_assemble_context` L1)
- Test: `tests/test_v06_divergence.py`

**Interfaces:**
- Consumes: `_parse_pre_research_provenance` (`## Query log`), `query_families.json` cache, frontmatter `loop_type`, `created_at`, `_pre_research_file`.
- Produces: `_audit_divergence(project_dir, node_id, cand_id) -> (ok, reason)`; `_query_family_key(q) -> str`.

- [ ] **Step 1: Write the failing test**

```python
def _run_pyfunc_divergence(proj, node, cand):
    import importlib.util
    spec = importlib.util.spec_from_file_location("rl", RL)
    rl = importlib.util.module_from_spec(spec); spec.loader.exec_module(rl)
    return rl._audit_divergence(str(proj), node, cand)

def _write_pre_research(proj, node, queries, ident="PMID: 111"):
    d = proj / "02_Agent_Notes" / "_pre_research"; d.mkdir(parents=True, exist_ok=True)
    ql = "\n".join(f"- {q}" for q in queries)
    txt = (f"# {node} research\n\n## Runtime digest\nfindings {ident}\n\n"
           f"## Query log\n{ql}\n\n## Tool receipt\n- pubmed 2020 ok\n\n## Source count\n2\n")
    (d / f"{node}_research.md").write_text(txt, encoding="utf-8")

def test_divergence_gate_fails_on_reused_families_divergent(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    cache = proj / "09_Literature_Database" / "query_families.json"; cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"families": ["col6a1 collagen", "collagen enhancer vi"]}), encoding="utf-8")
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q",
             "--claim", "C", "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    _write_pre_research(proj, "L1", ["COL6A1 collagen", "collagen VI enhancer"])
    ok, reason = _run_pyfunc_divergence(proj, "L1", cand)
    assert ok is False and "new query" in reason.lower()

def test_divergence_gate_passes_with_two_new_families(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    cache = proj / "09_Literature_Database" / "query_families.json"; cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"families": ["col6a1 collagen"]}), encoding="utf-8")
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q",
             "--claim", "C", "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    _write_pre_research(proj, "L1", ["cardiac tissue stiffness AFM", "myocardial passive compliance measurement"])
    ok, reason = _run_pyfunc_divergence(proj, "L1", cand)
    assert ok is True, reason

def test_divergence_gate_bypassed_for_correction_loop(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q",
             "--claim", "C", "--input", "in", "--from-memory", str(seed), "--loop-type", "correction")
    cand = r.stdout.strip().splitlines()[0]
    _write_pre_research(proj, "L1", ["COL6A1 collagen"])
    ok, reason = _run_pyfunc_divergence(proj, "L1", cand)
    assert ok is True, reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v06_divergence.py -k divergence -v`
Expected: FAIL (`_audit_divergence` missing).

- [ ] **Step 3: Write minimal implementation**

```python
DIVERGENCE_MIN_NEW_QUERY_FAMILIES = 2
_STOP = {"the", "a", "an", "of", "in", "and", "or", "vs", "for", "to", "on", "is", "do"}

def _query_family_key(q):
    toks = [t for t in re.sub(r"[^a-z0-9 ]", " ", q.lower()).split() if t and t not in _STOP]
    return " ".join(sorted(set(toks)))

def _load_query_family_cache(project_dir):
    p = Path(project_dir) / "09_Literature_Database" / "query_families.json"
    if p.exists():
        try: return set(json.loads(p.read_text(encoding="utf-8")).get("families", []))
        except Exception: return set()
    return set()

def _audit_divergence(project_dir, node_id, cand_id):
    project_dir = Path(project_dir)
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    if fm.get("loop_type") != "divergent":
        return True, ""  # correction / data-acquisition bypass the family requirement
    prf = _pre_research_file(project_dir, node_id)
    if not prf.exists():
        return False, f"divergence gate: pre-research artifact missing for {node_id}"
    created = fm.get("created_at", "")
    try:
        if created:
            import datetime as _dt
            ct = _dt.datetime.fromisoformat(created).timestamp()
            if prf.stat().st_mtime < ct:
                return False, ("divergence gate: pre-research artifact predates candidate "
                               "creation (stale reuse)")
    except Exception:
        pass
    prov = _parse_pre_research_provenance(prf.read_text(encoding="utf-8"))
    fams = {_query_family_key(q) for q in prov.get("query_log", []) if q.strip()}
    cache = {_query_family_key(q) for q in _load_query_family_cache(project_dir)}
    new = {f for f in fams if f and f not in cache}
    need = DIVERGENCE_MIN_NEW_QUERY_FAMILIES
    if len(new) < need:
        return False, (f"divergence gate: only {len(new)} new query families "
                       f"(need >= {need}); reused={sorted(fams & cache)}")
    return True, ""
```

Add `candidate_branches: list` (optional) to `DELTA_SCHEMAS["L1_einstein"]`. Wire `_audit_divergence` into `cmd_assemble_context` for L1 (call after existing `_audit_pre_research`; on failure print + return non-zero). After a successful L1 `emit-delta`, merge the L1 pre-research families into `query_families.json`.

Note: `_parse_pre_research_provenance` must expose a `query_log` list of raw query strings. If the existing helper returns booleans only, extend it to also return the list (keep old keys intact).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v06_divergence.py -k divergence -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add research_loop_v04.py tests/test_v06_divergence.py
git commit -m "feat(v0.6): L1 divergence gate (>=2 new query families, staleness, loop_type bypass)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: L4 method-card grounding gate

**Files:**
- Modify: `research_loop_v04.py` (`DELTA_SCHEMAS["L4_fisher"]` scripts_needed doc, `_audit_l4_methods`, hook in `cmd_emit_delta` L4)
- Test: `tests/test_v06_divergence.py`

**Interfaces:**
- Produces: `_audit_l4_methods(project_dir, cand_id, delta) -> (ok, reason)`. A script is method-dependent unless `status == "internally_motivated"`.

- [ ] **Step 1: Write the failing test**

```python
def _emit_l4(proj, cand, scripts):
    d = proj / "02_Agent_Notes" / "Fisher"; d.mkdir(parents=True, exist_ok=True)
    obj = {"strategies": [{"id": "s1", "name": "n", "steps": [], "samples": 3, "status": "ok"}],
           "recommended": "s1", "scripts_needed": scripts, "key_decisions": [], "candidate_id": cand}
    f = proj / f"l4_{cand}.json"; f.write_text(json.dumps(obj), encoding="utf-8")
    return _run("emit-delta", str(proj), "--node", "L4", "--persona", "Fisher", "--file", str(f), "--cand-id", cand)

def test_l4_method_gate_fails_without_fulltext_method_card(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C",
             "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    r2 = _emit_l4(proj, cand, [{"name": "afm.py", "purpose": "measure stiffness", "status": "planned",
                                "grounded_in_method_card_ids": ["nonexistent"]}])
    assert r2.returncode != 0 and "method_card" in (r2.stderr + r2.stdout)

def test_l4_method_gate_allows_internally_motivated(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C",
             "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    r2 = _emit_l4(proj, cand, [{"name": "bh_fdr.py", "purpose": "correction", "status": "internally_motivated"}])
    assert r2.returncode == 0, r2.stderr

def test_l4_method_gate_accepts_real_fulltext_card(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C",
             "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    import ars_card_adapter as aca
    mc = aca.write_method_card(proj, {"source_paper_card_id": "p1", "method_name": "AFM",
        "measurement_type": "mechanical", "data_modality": "tissue", "key_parameters": {},
        "applicability": "direct", "extracted_from": "full_text", "full_text_fetched": True})
    r2 = _emit_l4(proj, cand, [{"name": "afm.py", "purpose": "stiffness", "status": "planned",
                                "grounded_in_method_card_ids": [mc]}])
    assert r2.returncode == 0, r2.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v06_divergence.py -k l4_method -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
def _audit_l4_methods(project_dir, cand_id, delta):
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    mc_dir = Path(project_dir) / "09_Literature_Database" / "method_cards"
    def _is_fulltext(mc_id):
        p = mc_dir / f"{mc_id}.json"
        if not p.exists(): return False
        try: return json.loads(p.read_text(encoding="utf-8")).get("extracted_from") == "full_text"
        except Exception: return False
    for s in delta.get("scripts_needed", []):
        if s.get("status") == "internally_motivated":
            continue
        ids = s.get("grounded_in_method_card_ids", []) or []
        if not any(_is_fulltext(i) for i in ids):
            return False, (f"L4 script {s.get('name')!r} is method-dependent but has no "
                           f"full_text method_card (ids={ids}); add one or mark status "
                           f"'internally_motivated'")
    return True, ""
```

Hook in `cmd_emit_delta` after L4 schema validation (return 3 on failure).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v06_divergence.py -k l4_method -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add research_loop_v04.py tests/test_v06_divergence.py
git commit -m "feat(v0.6): L4 method-card grounding gate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: L6 script-grounding traceability gate

**Files:**
- Modify: `research_loop_v04.py` (`_audit_l6_traceability`, `_critique_ref_valid`, hook in emit-delta L6)
- Test: `tests/test_v06_divergence.py`

**Interfaces:**
- Produces: `_audit_l6_traceability(project_dir, cand_id, delta) -> (ok, reason)`. Grounding types: `method_card` (existing `method_card_ids`), `internal_critique` (`critique_delta_ref` naming a real L2/L5 attack index), `prior_reuse` (`reused_from`).

- [ ] **Step 1: Write the failing test**

```python
def _emit_l6(proj, cand, scripts):
    d = proj / "02_Agent_Notes" / "Oppenheimer"; d.mkdir(parents=True, exist_ok=True)
    obj = {"approved_strategy": "s1", "modifications": [], "reason": "r",
           "analysis_plan": {"scripts": scripts, "parameters": {}, "outputs": ["o.json"]},
           "candidate_id": cand}
    f = proj / f"l6_{cand}.json"; f.write_text(json.dumps(obj), encoding="utf-8")
    return _run("emit-delta", str(proj), "--node", "L6", "--persona", "Oppenheimer", "--file", str(f), "--cand-id", cand)

def _emit_l6_ok(proj, cand):
    d = proj / "02_Agent_Notes" / "Feynman"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{cand}_L2_feynman_delta.json").write_text(json.dumps({"attacks": [{"hypothesis_id": "H1",
        "severity": "high", "text": "no multiple-testing correction"}], "confounders": [],
        "diagnostic_tests": [], "verdict": "v", "candidate_id": cand}), encoding="utf-8")
    return _emit_l6(proj, cand, [{"name": "bh.py", "purpose": "correction", "branch_id": "b1",
        "data_modality": "stat", "grounding": {"type": "internal_critique",
        "critique_delta_ref": "L2_feynman#0"}}])

def test_l6_gate_fails_ungrounded_script(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C",
             "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    r2 = _emit_l6(proj, cand, [{"name": "x.py", "purpose": "p", "branch_id": "b1",
                                "data_modality": "dm", "grounding": {}}])
    assert r2.returncode != 0 and "grounding" in (r2.stderr + r2.stdout)

def test_l6_gate_accepts_internal_critique_with_ref(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C",
             "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    r2 = _emit_l6_ok(proj, cand)
    assert r2.returncode == 0, r2.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v06_divergence.py -k l6_gate -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
def _critique_ref_valid(project_dir, cand_id, ref):
    try:
        key, idx = ref.split("#"); idx = int(idx)
    except Exception:
        return False
    p = _delta_for_candidate(project_dir, key, cand_id)
    if not (p and p.exists()): return False
    try: obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception: return False
    return 0 <= idx < len(obj.get("attacks", []))

def _audit_l6_traceability(project_dir, cand_id, delta):
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    scripts = (delta.get("analysis_plan") or {}).get("scripts", [])
    mc_dir = Path(project_dir) / "09_Literature_Database" / "method_cards"
    for s in scripts:
        if isinstance(s, str):
            return False, (f"L6 script {s!r} is a bare string; must be an object with "
                           f"grounding/branch_id/data_modality")
        g = s.get("grounding") or {}
        gtype = g.get("type")
        if gtype == "method_card":
            ids = g.get("method_card_ids", []) or []
            if not ids or not all((mc_dir / f"{i}.json").exists() for i in ids):
                return False, f"L6 script {s.get('name')!r}: method_card grounding refs missing cards"
        elif gtype == "internal_critique":
            ref = g.get("critique_delta_ref", "")
            if not _critique_ref_valid(project_dir, cand_id, ref):
                return False, f"L6 script {s.get('name')!r}: critique_delta_ref {ref!r} not found"
        elif gtype == "prior_reuse":
            if not g.get("reused_from"):
                return False, f"L6 script {s.get('name')!r}: prior_reuse missing reused_from"
        else:
            return False, (f"L6 script {s.get('name')!r}: grounding.type must be one of "
                           f"method_card|internal_critique|prior_reuse")
        if not s.get("branch_id"):
            return False, f"L6 script {s.get('name')!r}: missing branch_id"
    return True, ""
```

Hook in emit-delta L6 (return 3). Gate only bites `from_memory` candidates → legacy bare-string L6 deltas still validate (verified in Task 12).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v06_divergence.py -k l6_gate -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research_loop_v04.py tests/test_v06_divergence.py
git commit -m "feat(v0.6): L6 script-grounding traceability gate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: L7 execution-traceability manifest + gate

**Files:**
- Modify: `research_loop_v04.py` (`_l6_script_branches`, `_audit_l7_manifest`, `_write_exec_manifest`, hook emit-delta L7)
- Test: `tests/test_v06_divergence.py`

**Interfaces:**
- Consumes: L6 delta scripts (name→branch_id map).
- Produces: `_audit_l7_manifest(project_dir, cand_id, delta) -> (ok, reason)`; manifest `04_Analysis_Outputs/_exec_manifest/<cand>_L7.json`.

- [ ] **Step 1: Write the failing test**

```python
def test_l7_manifest_gate_requires_branch_and_l6_map(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C",
             "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    _emit_l6_ok(proj, cand)
    d = proj / "02_Agent_Notes" / "Turing"; d.mkdir(parents=True, exist_ok=True)
    bad = {"scripts_run": [{"name": "bh.py", "exit_code": 0, "output_files": ["o.json"]}],
           "key_results": {}, "warnings": [], "failures": [], "candidate_id": cand}
    f = proj / "l7bad.json"; f.write_text(json.dumps(bad), encoding="utf-8")
    r2 = _run("emit-delta", str(proj), "--node", "L7", "--persona", "Turing", "--file", str(f), "--cand-id", cand)
    assert r2.returncode != 0 and "branch" in (r2.stderr + r2.stdout).lower()

def test_l7_manifest_written_on_valid(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C",
             "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    _emit_l6_ok(proj, cand)
    d = proj / "02_Agent_Notes" / "Turing"; d.mkdir(parents=True, exist_ok=True)
    good = {"scripts_run": [{"name": "bh.py", "exit_code": 0, "output_files": ["o.json"],
            "branch_id": "b1", "method_card_ids": [], "grounded_by": "bh.py",
            "input_hashes": ["h1"], "output_hashes": ["h2"]}],
            "key_results": {}, "warnings": [], "failures": [], "candidate_id": cand}
    f = proj / "l7ok.json"; f.write_text(json.dumps(good), encoding="utf-8")
    r2 = _run("emit-delta", str(proj), "--node", "L7", "--persona", "Turing", "--file", str(f), "--cand-id", cand)
    assert r2.returncode == 0, r2.stderr
    man = proj / "04_Analysis_Outputs" / "_exec_manifest" / f"{cand}_L7.json"
    assert man.exists()
    m = json.loads(man.read_text(encoding="utf-8"))
    assert m["scripts"][0]["branch_id"] == "b1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v06_divergence.py -k l7_manifest -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
def _l6_script_branches(project_dir, cand_id):
    p = _delta_for_candidate(project_dir, "L6_oppenheimer", cand_id)
    out = {}
    if p and p.exists():
        try:
            for s in (json.loads(p.read_text(encoding="utf-8")).get("analysis_plan") or {}).get("scripts", []):
                if isinstance(s, dict) and s.get("name"):
                    out[s["name"]] = s.get("branch_id")
        except Exception:
            pass
    return out

def _audit_l7_manifest(project_dir, cand_id, delta):
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    l6 = _l6_script_branches(project_dir, cand_id)
    for s in delta.get("scripts_run", []):
        name = s.get("name")
        if not s.get("branch_id"):
            return False, f"L7 script {name!r}: missing branch_id"
        if name not in l6:
            return False, f"L7 script {name!r} not found in approved L6 analysis_plan"
        if l6[name] and s["branch_id"] != l6[name]:
            return False, f"L7 script {name!r}: branch_id {s['branch_id']!r} != L6 {l6[name]!r}"
    return True, ""

def _write_exec_manifest(project_dir, cand_id, delta):
    d = Path(project_dir) / "04_Analysis_Outputs" / "_exec_manifest"; d.mkdir(parents=True, exist_ok=True)
    man = {"candidate_id": cand_id, "scripts": [
        {"name": s.get("name"), "branch_id": s.get("branch_id"),
         "method_card_ids": s.get("method_card_ids", []), "grounded_by": s.get("grounded_by"),
         "input_hashes": s.get("input_hashes", []), "output_hashes": s.get("output_hashes", []),
         "output_files": s.get("output_files", [])}
        for s in delta.get("scripts_run", [])]}
    (d / f"{cand_id}_L7.json").write_text(json.dumps(man, indent=2, sort_keys=True), encoding="utf-8")
```

Hook in emit-delta L7: run `_audit_l7_manifest`; on pass, call `_write_exec_manifest`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v06_divergence.py -k l7_manifest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research_loop_v04.py tests/test_v06_divergence.py
git commit -m "feat(v0.6): L7 execution-traceability manifest + gate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: L10b decision traceability + gate

**Files:**
- Modify: `research_loop_v04.py` (`_audit_l10_traceability`, hook emit-delta L10b)
- Test: `tests/test_v06_divergence.py`

**Interfaces:**
- Produces: `_audit_l10_traceability(project_dir, cand_id, delta) -> (ok, reason)`. Requires `literature_changed_direction` (bool) present + `decision_grounding` with all three id lists.

- [ ] **Step 1: Write the failing test**

```python
def _emit_l10b(proj, cand, obj):
    d = proj / "02_Agent_Notes" / "Oppenheimer"; d.mkdir(parents=True, exist_ok=True)
    obj = {**obj, "candidate_id": cand}
    f = proj / f"l10b_{cand}.json"; f.write_text(json.dumps(obj), encoding="utf-8")
    return _run("emit-delta", str(proj), "--node", "L10b", "--persona", "Oppenheimer", "--file", str(f), "--cand-id", cand)

def test_l10b_gate_requires_literature_changed_direction(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C",
             "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    r2 = _emit_l10b(proj, cand, {"decision": "DOWNGRADE", "evidence_level": "weak",
        "reason": "r", "next_steps": [], "next_round_hypothesis": "H"})
    assert r2.returncode != 0 and "literature_changed_direction" in (r2.stderr + r2.stdout)

def test_l10b_gate_accepts_full_traceability(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C",
             "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    r2 = _emit_l10b(proj, cand, {"decision": "DOWNGRADE", "evidence_level": "weak", "reason": "r",
        "next_steps": [], "next_round_hypothesis": "H", "literature_changed_direction": False,
        "decision_grounding": {"paper_card_ids": [], "method_card_ids": [], "branch_ids": ["b1"]},
        "evidence_kept": [], "evidence_dropped": []})
    assert r2.returncode == 0, r2.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v06_divergence.py -k l10b_gate -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
def _audit_l10_traceability(project_dir, cand_id, delta):
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    if "literature_changed_direction" not in delta:
        return False, "L10b must state `literature_changed_direction` (bool) explicitly"
    if not isinstance(delta.get("literature_changed_direction"), bool):
        return False, "`literature_changed_direction` must be a boolean"
    dg = delta.get("decision_grounding") or {}
    for k in ("paper_card_ids", "method_card_ids", "branch_ids"):
        if k not in dg:
            return False, f"decision_grounding missing `{k}`"
    return True, ""
```

Hook in emit-delta L10b (return 3).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v06_divergence.py -k l10b_gate -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research_loop_v04.py tests/test_v06_divergence.py
git commit -m "feat(v0.6): L10b decision-traceability gate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Branch ledger + modality ledger (real bodies + coverage gate)

**Files:**
- Modify: `research_loop_v04.py` (replace stubs `_read_branch_ledger`/`_read_modality_ledger`, add `_audit_branch_coverage`, `_prior_unexplored_ids`, `cmd_branch_status`, `cmd_modality_scan`, argparse; wire gate into assemble-context L1)
- Test: `tests/test_v06_divergence.py`

**Interfaces:**
- Produces: `08_Audit/branch_ledger/<cand>.json`, `08_Audit/modality_ledger/<cand>.json`; `_audit_branch_coverage(project_dir, cand_id) -> (ok, reason)`.

- [ ] **Step 1: Write the failing test**

```python
def test_branch_gate_requires_prior_unexplored_statused(tmp_path):
    proj = _new_project(tmp_path); seed = _write_seed(proj)  # seed has unexplored b_atrial
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C",
             "--input", "in", "--from-memory", str(seed), "--loop-type", "divergent")
    cand = r.stdout.strip().splitlines()[0]
    import importlib.util
    spec = importlib.util.spec_from_file_location("rl", RL); rl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rl)
    ok, reason = rl._audit_branch_coverage(str(proj), cand)
    assert ok is False and "b_atrial" in reason
    _run("branch-status", str(proj), cand, "--branch", "b_atrial", "--status", "ignored",
         "--why", "still no protein data")
    ok2, _ = rl._audit_branch_coverage(str(proj), cand)
    assert ok2 is True

def test_modality_scan_detects_unused(tmp_path):
    proj = _new_project(tmp_path)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C", "--input", "in")
    cand = r.stdout.strip().splitlines()[0]
    r2 = _run("modality-scan", str(proj), cand, "--used", "transcriptomic_DEG",
              "--available", "transcriptomic_DEG", "--available", "atrial_DEG")
    assert r2.returncode == 0
    ml = json.loads((proj / "08_Audit" / "modality_ledger" / f"{cand}.json").read_text(encoding="utf-8"))
    assert "atrial_DEG" in ml["available_unused"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v06_divergence.py -k "branch_gate or modality_scan" -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Replace the Task-2 stubs with real bodies and add the rest:

```python
def _branch_ledger_path(project_dir, cand_id):
    return Path(project_dir) / "08_Audit" / "branch_ledger" / f"{cand_id}.json"

def _read_branch_ledger(project_dir, cand_id):
    p = _branch_ledger_path(project_dir, cand_id)
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: return {"branches": []}
    return {"branches": []}

def _modality_ledger_path(project_dir, cand_id):
    return Path(project_dir) / "08_Audit" / "modality_ledger" / f"{cand_id}.json"

def _read_modality_ledger(project_dir, cand_id):
    p = _modality_ledger_path(project_dir, cand_id)
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: return {"used": [], "available_unused": []}
    return {"used": [], "available_unused": []}

def _prior_unexplored_ids(project_dir, cand_id):
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    mf = fm.get("memory_file")
    if not mf or not Path(mf).exists(): return []
    try: mem = json.loads(Path(mf).read_text(encoding="utf-8"))
    except Exception: return []
    return [b.get("id") for b in mem.get("unexplored_branches", []) if b.get("id")]

def _audit_branch_coverage(project_dir, cand_id):
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory") or fm.get("loop_type") != "divergent":
        return True, ""
    prior = set(_prior_unexplored_ids(project_dir, cand_id))
    have = {b.get("id"): b.get("status") for b in _read_branch_ledger(project_dir, cand_id).get("branches", [])}
    missing = [b for b in prior if not have.get(b)]
    if missing:
        return False, f"branch gate: prior unexplored branches not statused: {sorted(missing)}"
    return True, ""

def cmd_branch_status(args):
    p = _branch_ledger_path(args.project_dir, args.cand_id); p.parent.mkdir(parents=True, exist_ok=True)
    led = _read_branch_ledger(args.project_dir, args.cand_id); led.setdefault("branches", [])
    led["branches"] = [b for b in led["branches"] if b.get("id") != args.branch]
    led["branches"].append({"id": args.branch, "description": args.description or "",
        "status": args.status, "data_available": bool(args.data_path),
        "data_path": args.data_path or "", "why_deferred": args.why or ""})
    p.write_text(json.dumps(led, indent=2, sort_keys=True), encoding="utf-8")
    print(f"branch {args.branch} -> {args.status}"); return 0

def cmd_modality_scan(args):
    p = _modality_ledger_path(args.project_dir, args.cand_id); p.parent.mkdir(parents=True, exist_ok=True)
    used = list(dict.fromkeys(args.used or []))
    avail = list(dict.fromkeys(args.available or []))
    led = {"used": used, "available_unused": [m for m in avail if m not in used]}
    p.write_text(json.dumps(led, indent=2, sort_keys=True), encoding="utf-8")
    print(f"modality ledger: used={used} unused={led['available_unused']}"); return 0
```

Register argparse:

```python
    sp = sub.add_parser("branch-status", help="set a branch's exploration status in the ledger")
    sp.add_argument("project_dir"); sp.add_argument("cand_id")
    sp.add_argument("--branch", required=True); sp.add_argument("--description", default="")
    sp.add_argument("--status", required=True, choices=["explored", "partial", "ignored"])
    sp.add_argument("--data-path", dest="data_path", default="")
    sp.add_argument("--why", default=""); sp.set_defaults(func=cmd_branch_status)

    sp = sub.add_parser("modality-scan", help="record used/available data modalities")
    sp.add_argument("project_dir"); sp.add_argument("cand_id")
    sp.add_argument("--used", action="append", default=[])
    sp.add_argument("--available", action="append", default=[])
    sp.set_defaults(func=cmd_modality_scan)
```

Wire `_audit_branch_coverage` into `cmd_assemble_context` at L1 alongside `_audit_divergence`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v06_divergence.py -k "branch_gate or modality_scan" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research_loop_v04.py tests/test_v06_divergence.py
git commit -m "feat(v0.6): branch + modality ledgers with coverage gate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Candidate-scoped aggregate-report (no silent overwrite)

**Files:**
- Modify: `research_loop_v04.py` (`cmd_aggregate_report` :3777-3863, argparse add `--force`)
- Test: `tests/test_v06_divergence.py`

**Interfaces:**
- Produces: `FINAL_REPORT_<cand>.md`/`_CN_<cand>.md` canonical; `FINAL_REPORT.md` = latest w/ banner; `00_Reports_Index.md`. Helpers `_shared_report_owner`, `_update_reports_index`.

- [ ] **Step 1: Write the failing test**

```python
def test_aggregate_report_no_silent_clobber(tmp_path):
    proj = _new_project(tmp_path)
    c1 = _seed_candidate_with_deltas(proj)
    assert _run("aggregate-report", str(proj), c1).returncode == 0
    c2 = _seed_candidate_with_deltas(proj)
    assert _run("aggregate-report", str(proj), c2).returncode == 0
    r1 = (proj / f"FINAL_REPORT_{c1}.md").read_text(encoding="utf-8")
    r2 = (proj / f"FINAL_REPORT_{c2}.md").read_text(encoding="utf-8")
    assert c1 in r1 and c2 in r2
    shared = (proj / "FINAL_REPORT.md").read_text(encoding="utf-8")
    assert c2 in shared
    idx = (proj / "00_Reports_Index.md").read_text(encoding="utf-8")
    assert c1 in idx and c2 in idx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v06_divergence.py -k aggregate_report -v`
Expected: FAIL (only shared FINAL_REPORT.md written; c1 report absent).

- [ ] **Step 3: Write minimal implementation**

In `cmd_aggregate_report`, replace the two fixed-path writes (`en_path`/`cn_path`) with candidate-scoped writes + guarded shared pointer:

```python
    en_cand = project_dir / f"FINAL_REPORT_{args.cand_id}.md"
    cn_cand = project_dir / f"FINAL_REPORT_CN_{args.cand_id}.md"
    en_cand.write_text(en_report, encoding="utf-8")
    cn_cand.write_text(cn_report, encoding="utf-8")

    shared = project_dir / "FINAL_REPORT.md"
    prev_owner = _shared_report_owner(shared)
    if prev_owner and prev_owner != args.cand_id and not getattr(args, "force", False):
        print(f"NOTE: FINAL_REPORT.md currently belongs to {prev_owner}; writing candidate-scoped "
              f"report only. Use --force to also repoint the shared file.", file=sys.stderr)
    else:
        banner = f"<!-- shared FINAL_REPORT points to candidate {args.cand_id} -->\n"
        shared.write_text(banner + en_report, encoding="utf-8")
        (project_dir / "FINAL_REPORT_CN.md").write_text(banner + cn_report, encoding="utf-8")

    _update_reports_index(project_dir, args.cand_id, status)
```

Add helpers:

```python
def _shared_report_owner(shared_path):
    if not shared_path.exists(): return None
    head = shared_path.read_text(encoding="utf-8")[:200]
    m = re.search(r"candidate (C\w+)", head)
    return m.group(1) if m else None

def _update_reports_index(project_dir, cand_id, status):
    idx = Path(project_dir) / "00_Reports_Index.md"
    lines = idx.read_text(encoding="utf-8").splitlines() if idx.exists() else ["# Reports Index", ""]
    lines = [ln for ln in lines if f"FINAL_REPORT_{cand_id}.md" not in ln]
    lines.append(f"- [{cand_id}](FINAL_REPORT_{cand_id}.md) — status: {status}")
    idx.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

Add `--force` to the `aggregate-report` parser. Keep the existing `print("FINAL_REPORT generated:")` block (update the EN/CN paths printed to the candidate-scoped ones). NOTE: because the shared-pointer path repoints on same-owner or first-write, the very first candidate writes the banner (owner==itself via first-write branch); the test's two distinct candidates exercise the repoint-to-c2 path — since c2 != c1 owner and no `--force`, adjust: the test expects `c2 in shared`. To satisfy that, on a different-owner write WITHOUT `--force`, still repoint but print the NOTE (advisory, not blocking). Implement as: repoint always, but emit the NOTE when overwriting a different owner unless `--force`. (i.e. the `else` branch is the default; `--force` only silences the NOTE.) Final logic:

```python
    banner = f"<!-- shared FINAL_REPORT points to candidate {args.cand_id} -->\n"
    if prev_owner and prev_owner != args.cand_id and not getattr(args, "force", False):
        print(f"NOTE: repointing FINAL_REPORT.md from {prev_owner} to {args.cand_id} "
              f"(candidate-scoped copies preserved).", file=sys.stderr)
    shared.write_text(banner + en_report, encoding="utf-8")
    (project_dir / "FINAL_REPORT_CN.md").write_text(banner + cn_report, encoding="utf-8")
```

This keeps both candidate-scoped reports intact (no clobber) while the shared pointer advances to the latest, with an audit NOTE. `--force` only silences the NOTE.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v06_divergence.py -k aggregate_report -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research_loop_v04.py tests/test_v06_divergence.py
git commit -m "fix(v0.6): candidate-scoped aggregate-report, no silent FINAL_REPORT clobber

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Backward-compatibility regression (legacy candidates still validate)

**Files:**
- Test: `tests/test_v06_divergence.py`

**Interfaces:**
- Consumes: gates from Tasks 3/6/7/8/9 (all must no-op for non-`from_memory` candidates).

- [ ] **Step 1: Write the failing/guard test**

```python
def test_legacy_delta_without_new_fields_still_validates(tmp_path):
    proj = _new_project(tmp_path)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C", "--input", "in")
    cand = r.stdout.strip().splitlines()[0]
    d = proj / "02_Agent_Notes" / "Oppenheimer"; d.mkdir(parents=True, exist_ok=True)
    legacy_l6 = {"approved_strategy": "s", "modifications": [], "reason": "r",
                 "analysis_plan": {"scripts": ["s1.py", "s2.py"], "parameters": {}, "outputs": ["o"]},
                 "candidate_id": cand}
    f = proj / "legacy_l6.json"; f.write_text(json.dumps(legacy_l6), encoding="utf-8")
    r2 = _run("emit-delta", str(proj), "--node", "L6", "--persona", "Oppenheimer", "--file", str(f), "--cand-id", cand)
    assert r2.returncode == 0, r2.stderr  # gate must NOT bite non-from_memory candidate
    d0 = proj / "02_Agent_Notes" / "Linnaeus"; d0.mkdir(parents=True, exist_ok=True)
    l0 = {"skills_found": [], "skills_gaps": [], "input_verified": {}, "environment": {},
          "skill_use_plan": [], "forbidden_shortcuts": [], "candidate_id": cand}
    f0 = proj / "legacy_l0.json"; f0.write_text(json.dumps(l0), encoding="utf-8")
    r3 = _run("emit-delta", str(proj), "--node", "L0", "--persona", "Linnaeus", "--file", str(f0), "--cand-id", cand)
    assert r3.returncode == 0, r3.stderr
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_v06_divergence.py -k legacy -v`
Expected: PASS if all gates guard on `from_memory`; FAIL signals a gate biting legacy candidates.

- [ ] **Step 3: Fix any gate that bites legacy**

If FAIL: find the gate returning non-zero for a non-`from_memory` candidate; ensure its first lines are `fm = _load_yaml_front(...)` then `if not fm.get("from_memory"): return True, ""`.

- [ ] **Step 4: Full-suite run**

Run: `python -m pytest tests/test_v06_divergence.py -v`
Expected: PASS (all groups). Then: `python -m pytest -q` (no regressions in the existing suite).

- [ ] **Step 5: Commit**

```bash
git add tests/test_v06_divergence.py
git commit -m "test(v0.6): backward-compat regression for legacy (non-from_memory) candidates

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** A/N→Task 2; B→Task 3; C→Task 1; D→Task 5; E/F→Task 4; G→Tasks 4/6 (`full_text` flag + gate); H→Task 7; I→Task 8; J→Task 9; K/L→Task 10; M→Task 11; O→Task 4 (adapter) + meta-workflow; P→Task 4 firewall + card design; Q→Tasks 1-12. Invariants 1-7 enforced by Tasks 3/5/7/8/11 + Task 12 guard. Locked Q1(loop_type)→Tasks 1/5/10; Q2(ARS engine+adapter)→Task 4; Q3(≥2 families)→Task 5.

**Placeholder scan:** stubs `_read_branch_ledger`/`_read_modality_ledger`/`_list_card_ids` introduced empty-but-callable in Task 2, real bodies in Tasks 4/10 — flagged explicitly, not silent TODOs. No "TBD"/"handle edge cases" language.

**Type consistency:** card id `sha1(...)[:12]` consistent (Task 4 def; Tasks 6/7 refs). All `_audit_*` gates return `(ok, reason)` and hook via `return 3` on failure. Frontmatter keys `from_memory`/`loop_type`/`memory_hash`/`memory_file`/`prior_candidate` consistent across Tasks 1/3/5/6/7/9/10/11. Existing helpers referenced (`_delta_for_candidate`, `_candidate_file`, `_load_yaml_front`, `_pre_research_file`, `_parse_pre_research_provenance`) verified present in research_loop_v04.py. Task 5 notes the one required extension: `_parse_pre_research_provenance` must expose `query_log` as a list of raw strings.

## Open follow-ups (not blocking)

- Live ARS agent invocation (calling `synthesis_agent`/`research_architect_agent`, feeding `ars_output_to_cards`) is orchestrator-level; the adapter contract is unit-tested, the live call is integration-tested on the first real divergent loop.
- `DIVERGENCE_MIN_NEW_QUERY_FAMILIES` and query-family normalization may need tuning after the first real run.
