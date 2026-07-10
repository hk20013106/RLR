"""Pre-research artifact text utilities + literature-gate constants (Phase 3a leaf).

No intra-repo imports -> pure leaf.
"""
import re


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
