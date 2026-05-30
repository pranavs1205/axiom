"""
section_splitter.py
-------------------
Splits cleaned paper text into named sections.

Strategy: two-pass heading detection.
  Pass 1 (keyword) — must match a known research keyword (with/without number prefix).
  Pass 2 (structural) — used as a fallback ONLY when pass 1 finds ≤ 1 section.
    A line is a candidate heading if it is short, title-cased / ALL-CAPS,
    ends without a sentence-terminating period, and is surrounded by blank lines.
"""

import re
from typing import TypedDict


class Section(TypedDict):
    title: str
    content: str


NUMBER_PREFIX_RE = re.compile(
    r"^(\d+(\.\d+)*\.?|[IVXivx]+\.|[A-Z]\.?)\s+"
)

HEADING_KEYWORDS = {
    # Standard academic sections
    "abstract", "introduction", "background", "motivation",
    "related work", "related works", "literature review",
    "methodology", "method", "methods", "proposed method",
    "approach", "our approach", "model", "models",
    "experiment", "experiments", "experimental setup", "experimental results",
    "evaluation", "results", "result", "discussion", "discussions",
    "conclusion", "conclusions", "summary", "future work", "future directions",
    "limitations", "limitation", "references", "bibliography",
    "appendix", "appendices", "acknowledgements", "acknowledgments",
    "dataset", "datasets", "data", "data collection",
    "implementation", "implementation details", "system design",
    "analysis", "ablation", "ablation study",
    "architecture", "framework", "overview", "system overview",
    "problem formulation", "problem statement", "preliminaries",
    "contributions", "contribution", "notation",
    "training", "inference", "deployment", "baseline", "baselines",
    # Math / optimization
    "quantum", "optimization", "formulation", "objective",
    "constraints", "penalty", "qubo", "cqm", "hamiltonian",
    # Blockchain / DeFi / crypto
    "protocol", "protocol design", "protocol overview",
    "token", "tokenomics", "token economics", "token design",
    "smart contract", "smart contracts",
    "mechanism", "mechanism design", "incentive", "incentives",
    "governance", "dao", "consensus", "staking", "liquidity",
    "amm", "automated market maker", "swap", "pool", "vault",
    "fee", "fees", "rewards", "reward",
    "security", "security analysis", "threat model",
    "game theory", "game theoretic", "nash equilibrium",
    "cryptography", "zero knowledge", "zk", "proof",
    "scalability", "throughput", "latency",
    "decentralization", "trust", "assumptions",
    "system", "design", "specification",
    "use case", "use cases", "applications",
    "economic", "economics", "market",
    "properties", "correctness", "safety", "liveness",
    # General
    "problem", "solution", "challenges", "open problems",
    "scope", "roadmap", "timeline",
}


def _is_keyword_heading(line: str) -> bool:
    """Strict check: line must match a known keyword (with optional number prefix)."""
    if not line:
        return False
    if line.startswith(".") or "," in line or len(line) > 80:
        return False
    if re.match(r"^[\d\s]+$", line):
        return False
    if len(line.split()) > 8:
        return False

    keyword_part = NUMBER_PREFIX_RE.sub("", line).strip().rstrip(":").lower()

    if keyword_part in HEADING_KEYWORDS:
        return True
    if line.isupper() and 1 <= len(line.split()) <= 5 and keyword_part in HEADING_KEYWORDS:
        return True
    return False


_SMALL_WORDS = {"a", "an", "the", "and", "or", "but", "for", "nor", "so",
                "yet", "at", "by", "in", "of", "on", "to", "up", "as",
                "is", "it", "its", "be", "are", "was", "were", "via"}


def _is_title_case(line: str) -> bool:
    """
    Returns True if the line looks title-cased.
    At least half the non-small words must start with an uppercase letter.
    """
    words = line.split()
    if not words:
        return False
    significant = [w for w in words if w.lower() not in _SMALL_WORDS and w.isalpha()]
    if not significant:
        return False
    capitalized = sum(1 for w in significant if w[0].isupper())
    return capitalized / len(significant) >= 0.6


def _is_structural_heading(line: str) -> bool:
    """
    Looser check used only in the structural fallback pass.
    Uses title-case detection instead of blank-line context (PDF extraction
    often strips blank lines from around headings).

    A line is a heading candidate if:
      - 1–8 words, ≤ 70 chars
      - Doesn't end with sentence-terminating punctuation (. ? !)
      - Doesn't start with lowercase
      - Not pure numbers / code
      - Is title-cased (most content words start with uppercase)
    """
    if not line:
        return False
    if line.startswith(("#", "//", "-", "*", "|", ">")):
        return False
    if line.startswith(".") or "," in line:
        return False
    if re.match(r"^[\d\s\.\-\(\)]+$", line):
        return False
    if len(line) > 70:
        return False

    words = line.split()
    if not (1 <= len(words) <= 8):
        return False

    if line[-1] in ".?!;":
        return False

    if line[0].islower():
        return False

    # Must look like a title (not a random capitalised sentence fragment)
    return _is_title_case(line)


def _run_split(lines: list[str], heading_fn) -> list[Section]:
    """Generic split loop given a heading detection function."""
    sections: list[Section] = []
    current_title = "preamble"
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if heading_fn(stripped):
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    sections.append(Section(title=current_title, content=content))
            current_title = stripped
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append(Section(title=current_title, content=content))

    return sections


def _structural_split(lines: list[str]) -> list[Section]:
    """Fallback split using title-case heading detection."""
    return _run_split(lines, _is_structural_heading)


def split_into_sections(text: str, debug: bool = False) -> list[Section]:
    """
    Split paper text into sections.

    First tries keyword-based detection. Falls back to structural detection
    if only 1 section (preamble) is found.
    """
    lines = text.splitlines()

    sections = _run_split(lines, _is_keyword_heading)

    # Also use structural fallback when preamble holds most of the document
    total_chars = sum(len(s["content"]) for s in sections)
    preamble_chars = sum(len(s["content"]) for s in sections if s["title"] == "preamble")
    preamble_dominant = total_chars > 0 and preamble_chars / total_chars > 0.70

    if len(sections) <= 1 or preamble_dominant:
        structural = _structural_split(lines)
        if len(structural) > len(sections):
            sections = structural
            print(f"[section_splitter] Switched to structural pass: {len(structural)} sections")

    titles = [s["title"] for s in sections]
    print(f"[section_splitter] Detected {len(sections)} sections: {titles[:10]}")
    return sections
