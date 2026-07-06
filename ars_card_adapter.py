"""ARS-output -> compact paper/method card JSON. Token firewall: no APA prose,
abstracts, or full text ever enter a card. Cards store IDs + one-line + provenance.

Consumed by research_loop_v04.py (L1/L4 literature nodes read card IDs) and tests.
"""
import json
import hashlib
from pathlib import Path

_PAPER_KEYS = ["id", "pmid", "doi", "url", "title", "year", "journal", "one_line",
               "claims_used", "query_family_id", "retrieved_at", "hash"]
_METHOD_KEYS = ["id", "source_paper_card_id", "method_name", "measurement_type",
                "data_modality", "key_parameters", "applicability", "extracted_from",
                "full_text_fetched", "extracted_at"]


def _card_id(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts if p).encode("utf-8")).hexdigest()[:12]


def _paper_cards_dir(project_dir):
    d = Path(project_dir) / "09_Literature_Database" / "paper_cards"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _method_cards_dir(project_dir):
    d = Path(project_dir) / "09_Literature_Database" / "method_cards"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_paper_card(project_dir, card):
    """Write a compact paper card. Only whitelisted keys are persisted (firewall)."""
    cid = card.get("id") or _card_id(card.get("pmid"), card.get("doi"), card.get("title"))
    clean = {k: card.get(k) for k in _PAPER_KEYS}
    clean["id"] = cid
    clean["hash"] = _card_id("h", cid, card.get("title"))
    (_paper_cards_dir(project_dir) / f"{cid}.json").write_text(
        json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return cid


def write_method_card(project_dir, card):
    """Write a compact method card. Only whitelisted keys are persisted (firewall)."""
    cid = card.get("id") or _card_id(card.get("source_paper_card_id"), card.get("method_name"))
    clean = {k: card.get(k) for k in _METHOD_KEYS}
    clean["id"] = cid
    (_method_cards_dir(project_dir) / f"{cid}.json").write_text(
        json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return cid


def ars_output_to_cards(project_dir, ars_payload):
    """Convert an ARS agent payload {papers:[...], methods:[...]} into cards.

    APA prose, abstracts, and any non-whitelisted keys are dropped. Returns the
    written card IDs so nodes can reference them without carrying paper text."""
    paper_ids, method_ids, pmid_to_card = [], [], {}
    for p in ars_payload.get("papers", []):
        cid = write_paper_card(project_dir, {
            "pmid": p.get("pmid"), "doi": p.get("doi"), "url": p.get("url"),
            "title": p.get("title"), "year": p.get("year"), "journal": p.get("journal"),
            "one_line": p.get("relevance") or p.get("one_line", ""),
            "claims_used": p.get("claims_used", []), "query_family_id": p.get("query_family_id", ""),
        })
        paper_ids.append(cid)
        if p.get("pmid"):
            pmid_to_card[str(p["pmid"])] = cid
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
