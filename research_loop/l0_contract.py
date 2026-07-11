"""L0 structured input contract — the single authoritative definition.

One module owns: the schema, the enums, the ONE validator, the renderer, and
the builders. Every enforcement point (assemble-context L0, emit-delta L0, the
provider prompt writer) reads THIS module — there is no second copy of the input
and no per-node re-definition of the field set.

Design (see .claude/plan/l0-input-contract.md §10):
  * The contract BODY lives in its own artifact `01_Candidates/<cid>.l0_input.yaml`.
    The candidate frontmatter (a flat scalar-only parser) holds only pointers:
    input_contract_path, input_contract_hash, schema_version, round_type,
    round_id, parent_round_id, previous_candidate_id.
  * `validate_l0_input_contract` is the one validator. It hard-fails (returns a
    non-empty error list) on every case in the plan's §5/§10.4 matrix, and every
    message names the offending field, the decided round_type, the artifact file
    read, and the correct format.

Leaf module: imports stdlib + PyYAML + research_loop.paths/topology (both leaves)
-> no engine import, no cycle.
"""
import hashlib
from pathlib import Path

import yaml

from research_loop.paths import _candidate_file
from research_loop.topology import DECISION_TRANSITIONS


L0_CONTRACT_SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = ("1.0",)
ROUND_TYPES = ("initial", "continuation")
SOURCE_INPUT_TYPES = ("files", "directory", "dataset", "inline", "other")
# Remote/non-local datasets cannot be filesystem-checked; they must instead
# carry an explicit verification status + reason. There is NO verified:false
# escape for local file/directory inputs (those hard-fail when missing).
DATASET_VERIFICATION_STATUS = ("verified", "unverifiable", "pending")

# Reuse the repo's terminal decision enum (do NOT invent one). The L10b final
# decision is exactly the set of terminal transitions out of UNDER_REVIEW.
PREVIOUS_DECISION_ENUM = tuple(sorted(DECISION_TRANSITIONS["UNDER_REVIEW"]))

# Values that are structurally "present" but semantically empty -> hard fail.
_PLACEHOLDERS = {
    "", "tbd", "todo", "n/a", "na", "none", "null", "...", "?",
    "已有数据", "existing data", "existing", "data", "placeholder",
}


def _is_placeholder(v):
    return str(v if v is not None else "").strip().lower() in _PLACEHOLDERS


def _l0_input_file(project_dir, cand_id):
    """Sidecar artifact path, adjacent to the candidate .md.

    (The plan suggested `candidates/<cid>/l0_input.yaml`; the real repo stores
    candidates as `01_Candidates/<cid>.md`, so the sidecar sits beside it as
    `01_Candidates/<cid>.l0_input.yaml`.)"""
    return _candidate_file(project_dir, cand_id).with_suffix(".l0_input.yaml")


def _sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


# --- load / write -----------------------------------------------------------

def load_contract(project_dir, cand_id):
    """Return (contract_dict|None, artifact_path, raw_bytes|None).

    None contract means the artifact is absent or unparseable (the caller/gate
    turns that into a hard fail — there is no legacy soft-floor)."""
    p = _l0_input_file(project_dir, cand_id)
    if not p.exists():
        return None, p, None
    raw = p.read_bytes()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except Exception:
        return None, p, raw
    if not isinstance(data, dict):
        return None, p, raw
    return data, p, raw


def write_contract(project_dir, cand_id, contract):
    """Serialize the contract to its sidecar artifact; return (path, sha256)."""
    p = _l0_input_file(project_dir, cand_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(contract, allow_unicode=True, sort_keys=True)
    b = text.encode("utf-8")
    p.write_bytes(b)
    return p, _sha256_bytes(b)


# --- builders (used by new-candidate) ---------------------------------------

def build_source_input(input_type=None, files=None, location=None,
                       description="", fmt="", verification_status=None,
                       reason=None):
    si = {
        "input_type": input_type or "inline",
        "files": list(files or []),
        "location": location,
        "description": description or "",
        "format": fmt or "",
    }
    # dataset-only fields (no verified:false escape for local files)
    if verification_status is not None:
        si["verification_status"] = verification_status
    if reason is not None:
        si["reason"] = reason
    return si


def build_initial_contract(cand_id, round_id, scientific_question, source_input,
                           new_hypothesis):
    return {
        "schema_version": L0_CONTRACT_SCHEMA_VERSION,
        "round_type": "initial",
        "round_id": str(round_id),
        "previous_candidate_id": None,
        "candidate_id": str(cand_id),
        "scientific_question": scientific_question or "",
        "source_input": source_input,
        "previous_round": None,
        "current_round": {"hypothesis": new_hypothesis or ""},
    }


def build_continuation_contract(cand_id, round_id, parent_round_id,
                                previous_candidate_id, scientific_question,
                                source_input, previous_round, new_hypothesis):
    return {
        "schema_version": L0_CONTRACT_SCHEMA_VERSION,
        "round_type": "continuation",
        "round_id": str(round_id),
        "parent_round_id": (str(parent_round_id)
                            if parent_round_id is not None else None),
        "previous_candidate_id": (str(previous_candidate_id)
                                  if previous_candidate_id else None),
        "candidate_id": str(cand_id),
        "scientific_question": scientific_question or "",
        "source_input": source_input,
        "previous_round": {
            "candidate_id": str(previous_candidate_id or ""),
            "hypothesis": (previous_round or {}).get("hypothesis", ""),
            "final_decision": (previous_round or {}).get("final_decision", ""),
            "conclusion": (previous_round or {}).get("conclusion", ""),
            "memory_hash": (previous_round or {}).get("memory_hash", ""),
        },
        "current_round": {"hypothesis": new_hypothesis or ""},
    }


# --- the ONE validator ------------------------------------------------------

def validate_l0_input_contract(contract, fm, project_dir, cand_id,
                               artifact_path=None, raw_bytes=None):
    """Single authoritative validator. Returns a list of precise error strings
    (empty list == valid). Never raises for validation issues.

    `contract` is the parsed l0_input.yaml dict (or None if missing/malformed).
    `fm` is the candidate frontmatter (flat pointers). Both are cross-checked."""
    ap = artifact_path or _l0_input_file(project_dir, cand_id)
    ap = ap.as_posix() if hasattr(ap, "as_posix") else str(ap)
    fmt_hint = ("expected l0_input.yaml with keys schema_version, round_type, "
                "round_id, scientific_question, source_input{input_type,"
                "files|location,description,format}, current_round.hypothesis")

    if contract is None:
        return [f"[L0] input contract artifact missing or unparseable "
                f"({ap}); {fmt_hint}"]

    e = []

    def err(msg):
        e.append(f"[artifact={ap}] {msg}")

    # 0. schema version
    sv = str(contract.get("schema_version") or "")
    if sv not in SUPPORTED_SCHEMA_VERSIONS:
        err(f"unsupported schema_version {contract.get('schema_version')!r}; "
            f"supported: {list(SUPPORTED_SCHEMA_VERSIONS)}")

    # 1. round_type (explicit, never inferred)
    rt = contract.get("round_type")
    if rt not in ROUND_TYPES:
        err(f"round_type missing/illegal {rt!r}; must be one of {list(ROUND_TYPES)}")
        rt = None  # can't do round-specific checks without a valid round_type

    rlabel = rt or "unknown"

    # 2. frontmatter <-> artifact pointer consistency (hash + ids)
    if raw_bytes is not None and fm.get("input_contract_hash"):
        actual = _sha256_bytes(raw_bytes)
        if str(fm.get("input_contract_hash")) != actual:
            err(f"[round={rlabel}] input_contract_hash mismatch: frontmatter="
                f"{fm.get('input_contract_hash')!r} recomputed={actual!r} "
                f"(artifact tampered or out of sync)")
    for key in ("round_type", "round_id", "previous_candidate_id"):
        if key in fm and fm.get(key) not in (None, "", "None"):
            if str(fm.get(key)) != str(contract.get(key)):
                err(f"[round={rlabel}] {key} mismatch: frontmatter="
                    f"{fm.get(key)!r} != artifact={contract.get(key)!r}")
    if contract.get("candidate_id") and str(contract["candidate_id"]) != str(cand_id):
        err(f"[round={rlabel}] contract candidate_id {contract['candidate_id']!r} "
            f"!= candidate {cand_id!r}")

    # 3. scientific_question (required, non-empty, not placeholder, fixed type)
    sq = contract.get("scientific_question")
    if not isinstance(sq, str) or _is_placeholder(sq):
        err(f"[round={rlabel}] scientific_question missing/placeholder/wrong-type "
            f"({sq!r}); give one non-empty testable question as a string")

    # 4. source_input (required structured mapping)
    si = contract.get("source_input")
    if not isinstance(si, dict):
        err(f"[round={rlabel}] source_input must be a mapping "
            f"{{input_type,files|location,description,format}}, got {type(si).__name__}")
    else:
        it = si.get("input_type")
        if it not in SOURCE_INPUT_TYPES:
            err(f"[round={rlabel}] source_input.input_type illegal {it!r}; "
                f"one of {list(SOURCE_INPUT_TYPES)}")
        if _is_placeholder(si.get("description")):
            err(f"[round={rlabel}] source_input.description missing/placeholder; "
                f"describe the raw data (not vague text like '已有数据')")
        if not str(si.get("format") or "").strip():
            err(f"[round={rlabel}] source_input.format required "
                f"(e.g. 'csv', 'fastq', 'h5ad')")
        def _missing(paths):
            return [f for f in paths
                    if not (Path(project_dir) / str(f)).exists()
                    and not Path(str(f)).exists()]

        if it in ("files", "directory"):
            files = list(si.get("files") or [])
            if not files and si.get("location"):
                files = [si["location"]]
            if not files:
                err(f"[round={rlabel}] source_input.files|location required for "
                    f"input_type={it!r}")
            else:
                missing = _missing(files)
                # NO bypass: a local file/directory input whose paths do not
                # exist is a HARD FAIL. There is no verified:false escape.
                # Data that cannot be verified locally MUST be declared as
                # input_type=dataset (location + verification_status + reason).
                if missing:
                    err(f"[round={rlabel}] source_input files/directory not found "
                        f"on disk: {missing}; a local file/directory input must "
                        f"exist. For data that cannot be verified locally, use "
                        f"input_type=dataset with a stable location + "
                        f"verification_status + reason (not missing local files).")
        elif it == "dataset":
            # Remote / non-local dataset: cannot be filesystem-checked, so it
            # must carry a stable locator/ID and an explicit verification status
            # (+ reason unless already verified).
            if _is_placeholder(si.get("location")):
                err(f"[round={rlabel}] source_input.location required for "
                    f"input_type=dataset: give a stable locator/ID "
                    f"(accession, URI, DOI, dataset name)")
            vs = si.get("verification_status")
            if vs not in DATASET_VERIFICATION_STATUS:
                err(f"[round={rlabel}] source_input.verification_status illegal "
                    f"{vs!r}; one of {list(DATASET_VERIFICATION_STATUS)}")
            if vs != "verified" and _is_placeholder(si.get("reason")):
                err(f"[round={rlabel}] source_input.reason required when "
                    f"verification_status != 'verified' (explain why the dataset "
                    f"cannot be verified locally)")
            # a dataset may ALSO list local files; if it does, they must exist.
            dmiss = _missing(list(si.get("files") or []))
            if dmiss:
                err(f"[round={rlabel}] source_input.files listed but not found: "
                    f"{dmiss}")
        else:  # inline / other -- not file-backed, but any listed files must
               # exist (prevents smuggling missing files under a non-file type).
            imiss = _missing(list(si.get("files") or []))
            if imiss:
                err(f"[round={rlabel}] source_input declares files that do not "
                    f"exist under input_type={it!r}: {imiss}; use input_type="
                    f"files with existing paths, or dataset for remote data")

    # 5. current_round.hypothesis (the new hypothesis; required non-empty)
    cur = contract.get("current_round")
    if not isinstance(cur, dict) or _is_placeholder(cur.get("hypothesis")):
        err(f"[round={rlabel}] current_round.hypothesis (new_hypothesis) "
            f"missing/placeholder; state this round's hypothesis")

    # 6. round-type-specific state consistency
    if rt == "initial":
        if fm.get("from_memory") or contract.get("previous_round") not in (None, {}):
            err("[round=initial] conflicts with prior state: initial round must "
                "not carry from_memory or a previous_round block")
        if contract.get("previous_candidate_id"):
            err("[round=initial] previous_candidate_id must be null on an initial round")
    elif rt == "continuation":
        pr = contract.get("previous_round")
        if not isinstance(pr, dict) or not pr:
            err("[round=continuation] previous_round is required and must contain "
                "hypothesis, final_decision, conclusion")
        else:
            for field, label in (("hypothesis", "previous_hypothesis"),
                                 ("final_decision", "previous_final_decision"),
                                 ("conclusion", "previous_conclusion")):
                if _is_placeholder(pr.get(field)):
                    err(f"[round=continuation] previous_round.{field} ({label}) "
                        f"missing/placeholder; read it from the prior round's "
                        f"loop-memory seed ({fm.get('memory_file', '<seed>')})")
            fd = pr.get("final_decision")
            if fd and not _is_placeholder(fd) and fd not in PREVIOUS_DECISION_ENUM:
                err(f"[round=continuation] previous_round.final_decision {fd!r} "
                    f"illegal; one of {list(PREVIOUS_DECISION_ENUM)}")
            # continuation must link to a real prior artifact
            if not fm.get("from_memory"):
                err("[round=continuation] candidate lacks from_memory/seed linkage; "
                    "a continuation must be created via --from-memory")
            seed = fm.get("memory_file")
            if seed and not Path(seed).exists():
                err(f"[round=continuation] prior loop-memory artifact not found: "
                    f"{seed}")
            # id / hash linkage between rounds
            pcid = contract.get("previous_candidate_id") or pr.get("candidate_id")
            if _is_placeholder(pcid):
                err("[round=continuation] previous_candidate_id missing; must name "
                    "the source candidate")
            mh = pr.get("memory_hash")
            if mh and fm.get("memory_hash") and str(mh) != str(fm.get("memory_hash")):
                err(f"[round=continuation] previous_round.memory_hash {mh!r} != "
                    f"frontmatter memory_hash {fm.get('memory_hash')!r}")

    return e


# --- renderer (physical injection into L0 context) --------------------------

def render_contract_block(contract):
    """Deterministic text block injected into the L0 rendered context (and thus
    the provider prompt). This is the physical carrier the sentinel tests probe."""
    if not isinstance(contract, dict):
        return "=== L0 INPUT CONTRACT ===\n(invalid contract)\n"
    si = contract.get("source_input") or {}
    lines = [
        "=== L0 INPUT CONTRACT ===",
        f"schema_version: {contract.get('schema_version', '')}",
        f"round_type: {contract.get('round_type', '')}",
        f"round_id: {contract.get('round_id', '')}",
        f"scientific_question: {contract.get('scientific_question', '')}",
        "source_input:",
        f"  input_type: {si.get('input_type', '')}",
        f"  files: {si.get('files', [])}",
        f"  location: {si.get('location', '')}",
        f"  description: {si.get('description', '')}",
        f"  format: {si.get('format', '')}",
    ]
    if "verification_status" in si:
        lines.append(f"  verification_status: {si.get('verification_status')}")
    if "reason" in si:
        lines.append(f"  reason: {si.get('reason')}")
    pr = contract.get("previous_round")
    if isinstance(pr, dict) and pr:
        lines += [
            "previous_round:",
            f"  candidate_id: {pr.get('candidate_id', '')}",
            f"  hypothesis: {pr.get('hypothesis', '')}",
            f"  final_decision: {pr.get('final_decision', '')}",
            f"  conclusion: {pr.get('conclusion', '')}",
        ]
    else:
        lines.append("previous_round: null")
    cur = contract.get("current_round") or {}
    lines += [
        "current_round:",
        f"  hypothesis: {cur.get('hypothesis', '')}",
    ]
    return "\n".join(lines) + "\n"
