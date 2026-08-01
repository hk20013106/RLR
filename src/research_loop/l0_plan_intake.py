"""Structured-frontmatter preplan compatibility adapter for L0 intake (v0.9)."""
import hashlib
import os
import re
import unicodedata
from pathlib import Path
import yaml
from yaml.constructor import ConstructorError

from research_loop import l0_contract
from research_loop.l0_contract import _is_placeholder


class DuplicateKeyError(ValueError):
    """Raised when a duplicate YAML mapping key is encountered."""
    pass


class StrictPlanLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys at any mapping depth."""
    pass


def _construct_mapping(loader, node, deep=False):
    if not isinstance(node, yaml.MappingNode):
        raise ConstructorError(None, None, f"expected a mapping node, but found {node.id}", node.start_mark)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            line = key_node.start_mark.line + 1
            raise DuplicateKeyError(f"duplicate YAML key '{key}' at line {line}")
        value = loader.construct_object(value_node, deep=deep)
        mapping[key] = value
    return mapping


StrictPlanLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _normalize_conflict_text(s: str) -> str:
    """Normalize text for body/frontmatter conflict comparison.

    Performs Unicode NFC normalization, collapses consecutive whitespace, and
    removes spaces introduced by line folding between CJK characters/punctuation.
    Does NOT modify English word spaces or frontmatter values stored in contract.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"\s+", " ", s).strip()
    cjk_char = r"[\u2e80-\u2eff\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]"
    pattern = rf"({cjk_char})\s+({cjk_char})"
    while re.search(pattern, s):
        s = re.sub(pattern, r"\1\2", s)
    return s


def detect_intake_schema(frontmatter_text: str) -> bool:
    """Return True if closed frontmatter text declares an intake_schema."""
    if not frontmatter_text:
        return False
    return bool(re.search(r"^\s*intake_schema\s*:", frontmatter_text, re.MULTILINE))


def parse_frontmatter_strict(frontmatter_text: str):
    """Parse frontmatter YAML with duplicate key rejection.

    Returns (parsed_mapping_or_none, list_of_error_strings).
    Never raises exceptions past this boundary.
    """
    if not frontmatter_text or not frontmatter_text.strip():
        return None, ["frontmatter is empty"]

    yaml_text = frontmatter_text.rstrip()
    if yaml_text.endswith("\n---"):
        yaml_text = yaml_text[:-4]
    elif yaml_text.endswith("---"):
        yaml_text = yaml_text[:-3]

    try:
        parsed = yaml.load(yaml_text, Loader=StrictPlanLoader)
    except DuplicateKeyError as err:
        return None, [str(err)]
    except yaml.YAMLError as err:
        if hasattr(err, "problem_mark") and err.problem_mark is not None:
            line = err.problem_mark.line + 1
            problem = getattr(err, "problem", str(err))
            return None, [f"YAML syntax error at line {line}: {problem}"]
        return None, [f"YAML syntax error: {err}"]
    except Exception as err:
        return None, [f"YAML parsing error: {err}"]

    if not isinstance(parsed, dict):
        return None, ["frontmatter must be a YAML mapping/dictionary"]

    return parsed, []


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Stream-hash a file using chunked reads."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_path(path_str: str):
    """Resolve and normalize a file path for case-insensitive duplicate comparison on NT."""
    resolved = Path(path_str).expanduser().resolve()
    posix = resolved.as_posix()
    if os.name == "nt":
        posix = posix.casefold()
    return resolved, posix


def _derive_format(paths):
    """Derive sorted unique lowercase file extensions joined by comma."""
    exts = set()
    for p in paths:
        ext = Path(p).suffix.lower().lstrip(".")
        if ext:
            exts.add(ext)
    if not exts:
        return "unspecified"
    return ", ".join(sorted(exts))


def normalize_frontmatter(
    frontmatter_text,
    body_text,
    body_fields,
    request_path,
    candidate_id,
    *,
    data=None,
    dataset=None,
    memory=None,
    memory_hash="",
    request_text="",
):
    """Normalize a structured-frontmatter preplan into an L0 input contract.

    Task 2.5: Build existing schema-1.0 contract.
    Note: l0_plan_intake.py MUST NOT import l0_intake.py.
    """
    parsed, parse_errors = parse_frontmatter_strict(frontmatter_text)
    if parse_errors:
        return {
            "contract": None,
            "missing_fields": [],
            "errors": parse_errors,
            "round_type": "initial",
        }

    schema = parsed.get("intake_schema")
    if schema != "research-loop-plan/1.0":
        return {
            "contract": None,
            "missing_fields": [],
            "errors": [f"unsupported intake_schema '{schema}'; supported value is 'research-loop-plan/1.0'"],
            "round_type": "initial",
        }

    round_type = parsed.get("round_type", "initial")
    if round_type != "initial":
        return {
            "contract": None,
            "missing_fields": [],
            "errors": ["structured continuation rounds are not supported in v0.9"],
            "round_type": str(round_type),
        }

    missing_fields = []
    errors = []

    # 1. round_id
    round_id_val = parsed.get("round_id")
    if round_id_val is None or isinstance(round_id_val, (dict, list)) or _is_placeholder(round_id_val):
        missing_fields.append("round_id")

    # 2. scientific_question
    sq_val = parsed.get("scientific_question")
    if sq_val is None or not isinstance(sq_val, str) or _is_placeholder(sq_val):
        missing_fields.append("scientific_question")

    # 3. current_round.hypothesis
    current_round = parsed.get("current_round")
    if not isinstance(current_round, dict):
        missing_fields.append("current_round.hypothesis")
    else:
        hypo_val = current_round.get("hypothesis")
        if hypo_val is None or not isinstance(hypo_val, str) or _is_placeholder(hypo_val):
            missing_fields.append("current_round.hypothesis")

    # 4. source_input.file_manifest
    source_input = parsed.get("source_input")
    manifest = None
    if not isinstance(source_input, dict):
        missing_fields.append("source_input.file_manifest")
    else:
        manifest = source_input.get("file_manifest")
        if not isinstance(manifest, list) or len(manifest) == 0:
            missing_fields.append("source_input.file_manifest")

    # 5. research_plan
    research_plan = parsed.get("research_plan")
    if not isinstance(research_plan, dict) or len(research_plan) == 0:
        missing_fields.append("research_plan")

    # 6. Body/frontmatter conflict checks
    if isinstance(sq_val, str) and not _is_placeholder(sq_val):
        body_sq = (body_fields or {}).get("scientific_question", "").strip()
        if body_sq and _normalize_conflict_text(body_sq) != _normalize_conflict_text(sq_val):
            errors.append(f"scientific_question: body label ('{body_sq}') conflicts with frontmatter ('{sq_val.strip()}')")

    if isinstance(current_round, dict):
        hypo_val = current_round.get("hypothesis")
        if isinstance(hypo_val, str) and not _is_placeholder(hypo_val):
            body_hypo = (body_fields or {}).get("hypothesis", "").strip()
            if body_hypo and _normalize_conflict_text(body_hypo) != _normalize_conflict_text(hypo_val):
                errors.append(f"current_round.hypothesis: body label ('{body_hypo}') conflicts with frontmatter ('{hypo_val.strip()}')")

    if missing_fields or errors:
        return {
            "contract": None,
            "missing_fields": sorted(set(missing_fields)),
            "errors": errors,
            "round_type": "initial",
        }

    # Task 2.4: Verification of manifest entries
    resolved_data_root = None
    if data:
        resolved_data_root = Path(data).expanduser().resolve()
        if not resolved_data_root.exists():
            errors.append(f"source_input.location: local path not found: {resolved_data_root}")
        elif not resolved_data_root.is_dir():
            errors.append(f"source_input.location: --data root is not a directory: {resolved_data_root}")

    seen_normalized_paths = {}

    for i, entry in enumerate(manifest):
        if not isinstance(entry, dict):
            errors.append(f"source_input.file_manifest[{i}] must be a mapping")
            continue

        role = entry.get("role")
        if role is None or not isinstance(role, str) or not role.strip() or _is_placeholder(role):
            missing_fields.append(f"source_input.file_manifest[{i}].role")

        path_str = entry.get("path")
        has_valid_path_field = True
        if path_str is None or not isinstance(path_str, str) or not path_str.strip() or _is_placeholder(path_str):
            missing_fields.append(f"source_input.file_manifest[{i}].path")
            has_valid_path_field = False

        bytes_val = entry.get("bytes")
        has_valid_bytes_field = True
        if bytes_val is None:
            missing_fields.append(f"source_input.file_manifest[{i}].bytes")
            has_valid_bytes_field = False
        elif isinstance(bytes_val, bool) or not isinstance(bytes_val, int) or bytes_val < 0:
            errors.append(f"source_input.file_manifest[{i}].bytes must be a non-negative integer")
            has_valid_bytes_field = False

        sha_val = entry.get("sha256")
        has_valid_sha_field = True
        if sha_val is None:
            missing_fields.append(f"source_input.file_manifest[{i}].sha256")
            has_valid_sha_field = False
        elif not isinstance(sha_val, str) or not re.match(r"^[0-9a-f]{64}$", sha_val):
            errors.append(f"source_input.file_manifest[{i}].sha256 must be a 64-character lowercase hex string")
            has_valid_sha_field = False

        resolved_path = None
        if has_valid_path_field:
            try:
                resolved_path, norm_path = _normalize_path(path_str)
                if norm_path in seen_normalized_paths:
                    prev_index = seen_normalized_paths[norm_path]
                    errors.append(f"source_input.file_manifest[{i}].path duplicates source_input.file_manifest[{prev_index}].path after normalization")
                else:
                    seen_normalized_paths[norm_path] = i
            except Exception as err:
                errors.append(f"source_input.file_manifest[{i}].path invalid: {err}")
                has_valid_path_field = False

        if has_valid_path_field and resolved_data_root and resolved_data_root.exists() and resolved_data_root.is_dir():
            try:
                resolved_path.relative_to(resolved_data_root)
            except ValueError:
                errors.append(f"source_input.file_manifest[{i}].path resolves outside --data root")

        if has_valid_path_field:
            try:
                if not resolved_path.exists():
                    errors.append(f"source_input.file_manifest[{i}].path: file not found")
                elif not resolved_path.is_file():
                    errors.append(f"source_input.file_manifest[{i}].path: path is not a regular file")
                else:
                    if has_valid_bytes_field:
                        actual_size = resolved_path.stat().st_size
                        if actual_size != bytes_val:
                            errors.append(f"source_input.file_manifest[{i}].bytes mismatch: declared={bytes_val} actual={actual_size}")
                    if has_valid_sha_field:
                        actual_hash = _sha256_file(resolved_path)
                        if actual_hash != sha_val:
                            errors.append(f"source_input.file_manifest[{i}].sha256 mismatch: declared={sha_val} actual={actual_hash}")
            except OSError as err:
                errors.append(f"source_input.file_manifest[{i}].path: filesystem error accessing file: {err}")

    if missing_fields or errors:
        return {
            "contract": None,
            "missing_fields": sorted(set(missing_fields)),
            "errors": errors,
            "round_type": "initial",
        }

    # Task 2.5: Build canonical schema-1.0 contract
    verified_files = [entry["path"].strip() for entry in manifest]
    fmt = _derive_format(verified_files)
    location_str = resolved_data_root.as_posix() if resolved_data_root else None
    desc = f"{len(manifest)} verified file(s) from structured preplan round {str(round_id_val)}"

    source_input_contract = l0_contract.build_source_input(
        input_type="files",
        files=verified_files,
        location=location_str,
        description=desc,
        fmt=fmt,
    )

    clean_manifest = []
    for entry in manifest:
        clean_manifest.append({
            "role": entry["role"].strip(),
            "path": entry["path"].strip(),
            "bytes": entry["bytes"],
            "sha256": entry["sha256"].strip(),
        })
    source_input_contract["file_manifest"] = clean_manifest

    contract = l0_contract.build_initial_contract(
        cand_id=candidate_id,
        round_id=str(round_id_val),
        scientific_question=sq_val.strip(),
        source_input=source_input_contract,
        new_hypothesis=current_round["hypothesis"].strip(),
    )

    data_inventory = []
    for entry in clean_manifest:
        p = Path(entry["path"])
        data_inventory.append({
            "path": entry["path"],
            "name": p.name,
            "extension": p.suffix.lower().lstrip("."),
            "readable": True,
            "size_bytes": entry["bytes"],
        })

    req_file_path = Path(request_path)
    if req_file_path.exists() and req_file_path.is_file():
        source_bytes = req_file_path.read_bytes()
    else:
        req_text_str = request_text if request_text else (frontmatter_text + (body_text or ""))
        source_bytes = req_text_str.encode("utf-8")

    snapshot_sha256 = hashlib.sha256(source_bytes).hexdigest()
    snapshot_relpath = f"01_Candidates/_research_plans/{candidate_id}.md"

    contract["provenance"] = {
        "request_path": str(request_path),
        "request_sha256": hashlib.sha256(request_text.encode("utf-8") if request_text else source_bytes).hexdigest(),
        "parser_mode": "plan-v1",
        "normalization_version": "1.0",
        "llm_used": False,
        "data_inventory": data_inventory,
        "manifest_verified": True,
        "research_plan_snapshot_path": snapshot_relpath,
        "research_plan_snapshot_sha256": snapshot_sha256,
    }

    return {
        "contract": contract,
        "missing_fields": [],
        "errors": [],
        "round_type": "initial",
    }
