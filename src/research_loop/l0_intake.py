"""Rule-based natural-language intake for the strict L0 contract."""
import hashlib
import re
from pathlib import Path

from research_loop import l0_contract, l0_plan_intake


PARSER_MODE = "rules-v1"
NORMALIZATION_VERSION = "1.0"

_QUESTION_LABELS = ("科学问题", "研究问题", "scientific question", "research question")
_HYPOTHESIS_LABELS = ("本轮新假说", "当前假说", "新假说", "current hypothesis", "hypothesis")
_PREVIOUS_LABELS = ("上一轮假说", "上一轮 decision", "上一轮 conclusion",
                    "previous hypothesis", "previous decision", "previous conclusion")

# A bare YAML block-scalar indicator (">-", "|", "|+2", ...) is frontmatter
# syntax leaking through as a "value", never a real answer. Treat it as no
# match so the field hard-fails instead of silently carrying `>-` forward.
_BLOCK_SCALAR_RESIDUE = re.compile(r"^[|>][+-]?\d*$")


def _split_frontmatter(text):
    """Split leading closed YAML frontmatter block (--- ... ---) from body text.

    Returns (frontmatter_text, body_text).
    If there is no leading '---' or if the frontmatter block is unclosed,
    frontmatter_text is None and body_text is the original text.
    """
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 4)
    if end < 0:
        return None, text
    frontmatter_text = text[:end + 4]
    rest = text[end + 4:]
    body_text = rest.split("\n", 1)[1] if "\n" in rest else ""
    return frontmatter_text, body_text


def _strip_frontmatter(text):
    """Remove a closed leading YAML frontmatter block (--- ... ---).

    Uses the same boundary rule as yamlio._load_yaml_front: only a *closed*
    block is frontmatter. An opening "---" with no closing "---" is treated
    as ordinary body text (stripping it would silently eat real content)."""
    _, body = _split_frontmatter(text)
    return body


def _label_value(text, labels):
    wanted = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"^\s*(?:{wanted})\s*[:：]\s*(.+?)\s*$", text,
                      flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return ""
    value = match.group(1).strip()
    if _BLOCK_SCALAR_RESIDUE.match(value):
        return ""
    return value


def extract_request(text):
    """Extract only explicitly labelled fields; no prose guessing."""
    body = _strip_frontmatter(text)
    return {
        "scientific_question": _label_value(body, _QUESTION_LABELS),
        "hypothesis": _label_value(body, _HYPOTHESIS_LABELS),
        "mentions_previous_round": any(_label_value(body, (label,))
                                       for label in _PREVIOUS_LABELS),
    }


def _readable(path):
    try:
        with path.open("rb"):
            return True
    except OSError:
        return False


def scan_local_data(value):
    """Inspect one local file or a directory's visible direct files only."""
    root = Path(value).expanduser()
    if not root.exists():
        return None, [f"source_input.location: local path not found: {root}"]
    entries = []
    files = [root] if root.is_file() else sorted(
        (p for p in root.iterdir() if p.is_file() and not p.name.startswith(".")),
        key=lambda p: p.name.lower())
    for path in files:
        readable = _readable(path)
        entries.append({
            "path": str(path), "name": path.name,
            "extension": path.suffix.lower().lstrip("."),
            "readable": readable, "size_bytes": path.stat().st_size,
        })
    unreadable = [item["path"] for item in entries if not item["readable"]]
    if unreadable:
        return None, [f"source_input.files: unreadable local files: {unreadable}"]
    formats = sorted({item["extension"] for item in entries if item["extension"]})
    input_type = "files" if root.is_file() else "directory"
    source_input = l0_contract.build_source_input(
        input_type=input_type, files=[item["path"] for item in entries],
        location=str(root),
        description=(f"Local {input_type} at {root}; "
                     f"{len(entries)} visible readable file(s)"),
        fmt=", ".join(formats) or ("file" if root.is_file() else "directory"))
    return (source_input, entries), []


def _provenance(request_path, request_text, inventory):
    return {
        "request_path": str(request_path),
        "request_sha256": hashlib.sha256(request_text.encode("utf-8")).hexdigest(),
        "parser_mode": PARSER_MODE,
        "normalization_version": NORMALIZATION_VERSION,
        "llm_used": False,
        "data_inventory": inventory,
    }


def normalize_request(request_path, request_text, candidate_id, *, data=None,
                      dataset=None, memory=None, memory_hash=""):
    """Build an in-memory contract or report explicit missing/error fields."""
    frontmatter_text, body_text = _split_frontmatter(request_text)
    if frontmatter_text is not None and l0_plan_intake.detect_intake_schema(frontmatter_text):
        body_fields = {
            "scientific_question": _label_value(body_text, _QUESTION_LABELS),
            "hypothesis": _label_value(body_text, _HYPOTHESIS_LABELS),
            "mentions_previous_round": any(_label_value(body_text, (label,))
                                           for label in _PREVIOUS_LABELS),
        }
        return l0_plan_intake.normalize_frontmatter(
            frontmatter_text=frontmatter_text,
            body_text=body_text,
            body_fields=body_fields,
            request_path=request_path,
            candidate_id=candidate_id,
            data=data,
            dataset=dataset,
            memory=memory,
            memory_hash=memory_hash,
            request_text=request_text,
        )

    extracted = extract_request(request_text)
    missing, errors = [], []
    if not extracted["scientific_question"]:
        missing.append("scientific_question")
    if not extracted["hypothesis"]:
        missing.append("current_round.hypothesis")

    is_continuation = bool(memory) or extracted["mentions_previous_round"]
    if bool(data) == bool(dataset):
        missing.append("source_input.location")
        source_input, inventory = None, []
    elif data:
        scanned, scan_errors = scan_local_data(data)
        errors.extend(scan_errors)
        source_input, inventory = scanned if scanned else (None, [])
    else:
        locator = str(dataset).strip()
        if not locator or locator.lower() == "pending":
            missing.append("source_input.location")
            source_input, inventory = None, []
        else:
            source_input = l0_contract.build_source_input(
                input_type="dataset", location=locator,
                description="Remote dataset supplied by the caller",
                fmt="dataset", verification_status="unverifiable",
                reason="Remote dataset is not inspected locally")
            inventory = []

    if is_continuation and not memory:
        missing.extend(["previous_round.candidate_id", "previous_round.memory_hash",
                        "previous_round.hypothesis", "previous_round.final_decision",
                        "previous_round.conclusion", "round_id", "parent_round_id"])
    elif is_continuation:
        required_memory_fields = {
            "source_candidate_id": "previous_round.candidate_id",
            "previous_hypothesis": "previous_round.hypothesis",
            "previous_final_decision": "previous_round.final_decision",
            "previous_conclusion": "previous_round.conclusion",
            "round_id": "round_id",
            "parent_round_id": "parent_round_id",
        }
        for key, field in required_memory_fields.items():
            if not str(memory.get(key) or "").strip():
                missing.append(field)
        if not str(memory_hash or "").strip():
            missing.append("previous_round.memory_hash")
    if missing or errors:
        return {"contract": None, "missing_fields": sorted(set(missing)),
                "errors": errors, "round_type": "continuation" if is_continuation else "initial"}

    if is_continuation:
        previous_candidate_id = memory.get("source_candidate_id", "")
        parent_round_id = memory.get("parent_round_id")
        round_id = memory.get("round_id", "")
        previous_round = {
            "hypothesis": memory.get("previous_hypothesis", ""),
            "final_decision": memory.get("previous_final_decision", ""),
            "conclusion": memory.get("previous_conclusion", ""),
            "memory_hash": memory_hash,
        }
        contract = l0_contract.build_continuation_contract(
            candidate_id, round_id, parent_round_id, previous_candidate_id,
            extracted["scientific_question"], source_input, previous_round,
            extracted["hypothesis"])
    else:
        contract = l0_contract.build_initial_contract(
            candidate_id, "1", extracted["scientific_question"], source_input,
            extracted["hypothesis"])
    contract["provenance"] = _provenance(request_path, request_text, inventory)
    return {"contract": contract, "missing_fields": [], "errors": [],
            "round_type": contract["round_type"]}
