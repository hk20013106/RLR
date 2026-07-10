"""Pre-research artifact text utilities + literature-gate constants (Phase 3a leaf).

No intra-repo imports -> pure leaf.
"""
import re
import json
from pathlib import Path


LIT_RUNTIME_DIGEST_TOKEN_BUDGET = 1000

_LIT_PRE_RESEARCH_TYPES = {"deep_research", "literature_review"}

_DOI_PMID_URL_RE = re.compile(
    r"(10\.\d{4,9}/\S+|PMID:?\s*\d+|https?://\S+)", re.IGNORECASE)

def _runtime_digest_budget_error(estimated_tokens, budget):
    return (
        f"Runtime digest estimated at {estimated_tokens} tokens exceeds "
        f"configured budget {budget}; compress `## Runtime digest` with a "
        "provenance-preserving compressor such as caveman or host-agent "
        "compression; preserve Query log, Tool receipt, Source count, and all "
        "DOI/PMID/URL identifiers.")

def _extract_section(text, heading):
    # Extract a markdown section by heading. Returns section text or empty str.
    pattern = f"\n## {heading}"
    idx = text.find(f"## {heading}")
    if idx == -1:
        return ""
    start = idx + len(f"## {heading}")
    # Find next ## heading after this section
    rest = text[start:]
    next_h2 = rest.find("\n## ")
    if next_h2 == -1:
        return rest.strip()
    return rest[:next_h2].strip()

def _estimate_tokens(text):
    # Rough token estimate: 1 token ~= 4 characters.
    return max(1, len(text) // 4)


def _validate_pre_research_content(text, pr_cfg):
    """Validate content of a pre-research artifact. Returns (ok, reason)."""
    if "NOT YET RUN" in text:
        return False, "artifact is the NOT YET RUN placeholder"
    if not text.strip():
        return False, "artifact is empty"
    if pr_cfg.get("type") in _LIT_PRE_RESEARCH_TYPES:
        digest = _extract_section(text, "Runtime digest")
        if not digest:
            return False, "missing required `## Runtime digest` section"
        if not _DOI_PMID_URL_RE.search(digest):
            return False, "Runtime digest carries no DOI/PMID/URL identifier"
        estimated_tokens = _estimate_tokens(digest)
        if estimated_tokens > LIT_RUNTIME_DIGEST_TOKEN_BUDGET:
            return False, _runtime_digest_budget_error(
                estimated_tokens, LIT_RUNTIME_DIGEST_TOKEN_BUDGET)
        # V0.6 (PR2): reviewable provenance is mandatory for literature nodes.
        prov = _parse_pre_research_provenance(text)
        if not prov["query_log"]:
            return False, ("missing or empty `## Query log` -- record the actual "
                           "queries issued (including 0-result ones)")
        if not prov["tool_receipt"]:
            return False, ("missing or empty `## Tool receipt` -- record each "
                           "tool call (name, timestamp, return summary)")
        if not prov["source_count_declared"]:
            return False, ("missing `## Source count` section -- it must be "
                           "stated explicitly (not inferred)")
        if prov["source_count"] < 1:
            return False, "`## Source count` is < 1 (no sources retrieved)"
    return True, ""

def _parse_section_bullets(text, heading):
    """Return the '- '/'* ' bullet items under a `## <heading>` section."""
    bullets = []
    for raw in _extract_section(text, heading).splitlines():
        line = raw.strip()
        if line.startswith(("- ", "* ")):
            item = line[2:].strip()
            if item:
                bullets.append(item)
    return bullets

def _parse_pre_research_provenance(text):
    """Extract V0.6 provenance from a pre-research artifact. Never raises.

    Returns {query_log, tool_receipt, source_count, source_count_declared}.
    Missing sections yield empty/0; if `## Source count` is absent the count
    falls back to distinct DOI/PMID/URL identifiers in the Runtime digest."""
    declared = _extract_section(text, "Source count")
    m = re.search(r"-?\d+", declared)
    if m:
        source_count = max(0, int(m.group()))
        source_count_declared = True
    else:
        digest = _extract_section(text, "Runtime digest")
        source_count = len(set(_DOI_PMID_URL_RE.findall(digest)))
        source_count_declared = False
    return {
        "query_log": _parse_section_bullets(text, "Query log"),
        "tool_receipt": _parse_section_bullets(text, "Tool receipt"),
        "source_count": source_count,
        "source_count_declared": source_count_declared,
    }

_QF_STOP = {"the", "a", "an", "of", "in", "and", "or", "vs", "for", "to", "on", "is", "do"}

def _query_family_key(q):
    """Normalize a query string to a family key: lowercased, de-punctuated,
    stop-words removed, sorted unique tokens."""
    toks = [t for t in re.sub(r"[^a-z0-9 ]", " ", q.lower()).split()
            if t and t not in _QF_STOP]
    return " ".join(sorted(set(toks)))

def _load_query_family_cache(project_dir):
    p = Path(project_dir) / "09_Literature_Database" / "query_families.json"
    if p.exists():
        try:
            return set(json.loads(p.read_text(encoding="utf-8")).get("families", []))
        except Exception:
            return set()
    return set()

def _merge_query_family_cache(project_dir, families):
    p = Path(project_dir) / "09_Literature_Database" / "query_families.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_query_family_cache(project_dir)
    existing |= {f for f in families if f}
    p.write_text(json.dumps({"families": sorted(existing)}, indent=2), encoding="utf-8")
