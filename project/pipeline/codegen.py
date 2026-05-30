"""
codegen.py
----------
Code Generation Pipeline.

Uses only methodology-retrieved chunks as context. The prompt is carefully
engineered to:
  - Prevent hallucination (use only provided context)
  - Enforce modular Python output
  - Explicitly state assumptions where info is missing
"""

from pipeline.retrieval import retrieve_methodology
from pipeline.vector_store import VectorStore
from llm.groq_client import call_llm_with_system

# Max context characters sent to the LLM to avoid overflow
MAX_CONTEXT_CHARS = 6000

SYSTEM_PROMPT = """You are an expert Python engineer tasked with implementing research paper methodology in code.

STRICT RULES:
1. Use ONLY the provided methodology context. Do NOT invent details not present in the context.
2. Where the paper is ambiguous or missing implementation details, add a clearly labeled comment:
   # ASSUMPTION: <describe your assumption and why>
3. Write modular Python: one function per logical operation, with type hints and docstrings.
4. Include all necessary imports at the top.
5. Do NOT produce pseudocode. All code must be syntactically valid Python.
6. Add a main() function demonstrating usage with placeholder data.
"""


def generate_code(query: str, store: VectorStore, api_key: str, top_k: int = 5) -> str:
    """
    Generate Python code implementing the methodology described in the paper.

    Retrieves methodology-relevant chunks, assembles them as context,
    then prompts the LLM to write clean, modular Python.

    Args:
        query: Description of what to implement (e.g., "implement the training loop").
        store: Loaded VectorStore.
        api_key: Groq API key.
        top_k: Number of methodology chunks to use as context.

    Returns:
        Generated Python code as a string.
    """
    chunks = retrieve_methodology(query, store, top_k=top_k)

    if not chunks:
        return "# ERROR: No methodology context found. Cannot generate code without source material."

    # Assemble context from retrieved chunks
    context_parts = []
    total_chars = 0
    for chunk in chunks:
        section_header = f"[Section: {chunk['section']}]"
        entry = f"{section_header}\n{chunk['text']}"
        if total_chars + len(entry) > MAX_CONTEXT_CHARS:
            print("[codegen] Context budget reached; truncating chunk list.")
            break
        context_parts.append(entry)
        total_chars += len(entry)

    context = "\n\n---\n\n".join(context_parts)

    user_prompt = f"""Based ONLY on the following methodology context from a research paper,
implement the following in Python: {query}

METHODOLOGY CONTEXT:
{context}

Generate clean, modular, well-documented Python code. State all assumptions explicitly.
"""

    print(f"[codegen] Generating code from {len(context_parts)} methodology chunks...")
    return call_llm_with_system(SYSTEM_PROMPT, user_prompt, api_key=api_key, temperature=0.2)
