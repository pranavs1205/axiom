"""
section_filter.py
-----------------
Two-stage pipeline to filter irrelevant sections from a research paper:

  Stage 1 - Rule-based: Remove sections whose titles match known
            boilerplate patterns (references, appendix, etc.)

  Stage 2 - LLM-based: Ask the LLM to verify remaining sections
            and return a strict JSON verdict.

Design note: LLM is used ONLY for reasoning (is this section relevant?),
never for transforming or regenerating the section data itself.
"""

import json
import re

from ingestion.section_splitter import Section
from llm.groq_client import call_llm


# Titles that are always irrelevant in a research context
BOILERPLATE_TITLES = {
    "references", "bibliography", "appendix", "appendices",
    "acknowledgements", "acknowledgments", "about the authors",
    "author contributions", "conflict of interest", "funding",
    "supplementary material", "supplementary materials",
}

# Max characters sent to LLM to avoid context overflow
MAX_LLM_INPUT_CHARS = 3000


def _rule_based_filter(sections: list[Section]) -> list[Section]:
    """
    Remove sections whose titles clearly match boilerplate patterns.

    Args:
        sections: Full list of parsed sections.

    Returns:
        Filtered list with boilerplate sections removed.
    """
    filtered = []
    for sec in sections:
        title_lower = sec["title"].lower().strip("0123456789. ")
        if title_lower in BOILERPLATE_TITLES:
            print(f"[section_filter] Rule-removed: '{sec['title']}'")
        else:
            filtered.append(sec)
    return filtered


def _llm_filter(sections: list[Section], groq_api_key: str) -> list[Section]:
    """
    Use the LLM to verify which sections are substantive research content.

    Sends section titles and a short preview to the LLM, which must respond
    with strict JSON: {"relevant": ["Title1", "Title2", ...]}.
    Falls back to keeping all sections if JSON parsing fails.

    Args:
        sections: Rule-filtered sections.
        groq_api_key: Groq API key for the LLM call.

    Returns:
        Final filtered list of relevant sections.
    """
    if not sections:
        return sections

    listing_parts = []
    for sec in sections:
        preview = sec["content"][:200].replace("\n", " ")
        listing_parts.append(f'- "{sec["title"]}": {preview}')

    listing = "\n".join(listing_parts)

    if len(listing) > MAX_LLM_INPUT_CHARS:
        listing = listing[:MAX_LLM_INPUT_CHARS] + "\n...[truncated]"

    prompt = f"""You are reviewing sections of a research paper.
Your task: decide which sections contain substantive research content worth reading.

Sections (title: first 200 chars of content):
{listing}

Rules:
- KEEP: any section whose content contains research methodology, technical design, algorithms,
  experimental results, analysis, token economics, protocol mechanics, math, or system description.
- KEEP: sections titled "preamble" or "body" when their content is substantive research text.
- REMOVE ONLY: pure reference lists, acknowledgements, funding statements, author bios.
- When uncertain, keep the section.

Respond ONLY with valid JSON in this exact format (no explanation, no markdown):
{{"relevant": ["section title 1", "section title 2", ...]}}
"""

    raw_response = call_llm(prompt, api_key=groq_api_key)

    try:
        clean = re.sub(r"```json|```", "", raw_response).strip()
        parsed = json.loads(clean)
        relevant_titles = set(parsed.get("relevant", []))
        if not relevant_titles:
            raise ValueError("Empty relevant list returned by LLM.")
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        print(f"[section_filter] LLM JSON parse failed ({e}). Keeping all rule-filtered sections.")
        return sections

    # Case-insensitive match so LLM response casing differences don't drop valid sections
    relevant_lower = {t.strip().lower() for t in relevant_titles}
    result = [s for s in sections if s["title"].strip().lower() in relevant_lower]
    removed = [s["title"] for s in sections if s["title"].strip().lower() not in relevant_lower]
    if removed:
        print(f"[section_filter] LLM-removed: {removed}")

    # Safety net: never return empty — the LLM may have been confused by unusual titles
    if not result:
        print("[section_filter] LLM would remove everything — keeping all rule-filtered sections.")
        return sections

    return result


def filter_sections(sections: list[Section], groq_api_key: str) -> list[Section]:
    """
    Run both filtering stages and return only relevant research sections.

    Args:
        sections: Raw parsed sections from section_splitter.
        groq_api_key: Groq API key.

    Returns:
        List of sections deemed relevant by both rule-based and LLM filtering.
    """
    print(f"[section_filter] Starting with {len(sections)} sections.")
    after_rules = _rule_based_filter(sections)
    print(f"[section_filter] After rule-based filter: {len(after_rules)} sections.")
    after_llm = _llm_filter(after_rules, groq_api_key)
    print(f"[section_filter] After LLM filter: {len(after_llm)} sections.")
    return after_llm
