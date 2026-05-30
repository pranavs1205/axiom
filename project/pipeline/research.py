"""
research.py
-----------
Research Pipeline: explain, summarize, RAG Q&A.

v5 fixes — Sycophantic Drift & Answer Anchoring:
  - Chain-of-evidence prompting: LLM must quote relevant chunk text FIRST,
    then derive its answer from those quotes only. This structurally prevents
    the model from ignoring retrieved context.
  - System prompt uses hard STOP words: "DO NOT say 'To clarify'",
    "DO NOT reference prior answers", "DO NOT start with a preamble"
  - History stripped from the answer prompt entirely — history is ONLY
    used inside rewrite_query, never passed to the answer LLM
  - Chunks are numbered so the LLM can cite them by number
  - Temperature lowered to 0.0 for answer generation (deterministic grounding)
"""

from pipeline.retrieval import retrieve
from pipeline.vector_store import VectorStore
from llm.groq_client import call_llm, call_llm_with_system

MAX_CONTENT_CHARS = 5000
MAX_CONTEXT_CHARS = 7000
MAX_HISTORY_TURNS = 4
HISTORY_ANSWER_CAP = 150


def explain_section(section: dict, api_key: str) -> str:
    """Explain a section in plain language."""
    content = section["content"][:MAX_CONTENT_CHARS]
    system = "You are a research assistant that explains academic content clearly to a technical audience."
    user = (
        f"Explain the following section from a research paper in plain language.\n"
        f"Cover: what it says, why it matters, and any key concepts introduced.\n\n"
        f"SECTION TITLE: {section['title']}\n\n"
        f"SECTION CONTENT:\n{content}\n\n"
        f"Your explanation:"
    )
    return call_llm_with_system(system, user, api_key=api_key, temperature=0.3)


def summarize_section(section: dict, api_key: str) -> str:
    """Produce a concise 3-5 sentence summary of a section."""
    content = section["content"][:MAX_CONTENT_CHARS]
    system = "You are a research assistant that writes concise, accurate academic summaries."
    user = (
        f"Summarize the following section in 3-5 sentences.\n\n"
        f"SECTION TITLE: {section['title']}\n\n"
        f"SECTION CONTENT:\n{content}\n\n"
        f"Your summary:"
    )
    return call_llm_with_system(system, user, api_key=api_key, temperature=0.2)


def rewrite_query(question: str, history: list[dict], api_key: str) -> str:
    """
    Rewrite the user question into a self-contained retrieval query.

    Uses ONLY the previous user question for context — never assistant answers.

    Args:
        question: Raw user question.
        history: Full conversation history.
        api_key: Groq API key.

    Returns:
        Rewritten standalone search query.
    """
    prev_user_q = ""
    for msg in reversed(history):
        if msg["role"] == "user":
            prev_user_q = msg["content"]
            break

    context_block = ""
    if prev_user_q and prev_user_q != question:
        context_block = f"Previous question (for pronoun resolution only): {prev_user_q}\n\n"

    prompt = (
        f"Rewrite the following question as a self-contained document search query.\n\n"
        f"{context_block}"
        f"Question: {question}\n\n"
        f"Rules:\n"
        f"- Replace pronouns ('it', 'this', 'above', 'that') with specific terms\n"
        f"- Keep it 5-12 words\n"
        f"- Focus ONLY on the current question topic\n"
        f"- Output only the rewritten query, nothing else\n\n"
        f"Rewritten query:"
    )

    rewritten = call_llm(prompt, api_key=api_key, temperature=0.0)
    rewritten = rewritten.strip().strip('"\' ')

    # Drift detection: if rewrite shares no words with original, fall back
    original_words = set(question.lower().split()) - {"what", "is", "are", "the", "a", "an", "how", "why", "does", "do", "can", "please", "explain", "tell", "me", "u"}
    rewritten_words = set(rewritten.lower().split())
    if original_words and len(original_words & rewritten_words) == 0:
        print(f"  [query_rewrite] Rewrite drifted, using original question.")
        return question

    print(f"  [query_rewrite] '{question}' -> '{rewritten}'")
    return rewritten


def rag_qa(
    question: str,
    store: VectorStore,
    api_key: str,
    history: list[dict],
    top_k: int = 8,
) -> str:
    """
    Answer a question using chain-of-evidence RAG.

    Key design: LLM is forced to extract relevant quotes from chunks FIRST,
    then synthesise an answer from those quotes only. This prevents the model
    from ignoring retrieved context and relying on conversational memory.

    History is NOT passed to the answer LLM — only to the query rewriter.

    Args:
        question: Raw user question.
        store: Loaded VectorStore.
        api_key: Groq API key.
        history: Conversation history (used only for query rewriting).
        top_k: Number of chunks to retrieve.

    Returns:
        Evidence-grounded answer.
    """
    # Step 1: Rewrite query using only prior user questions
    retrieval_query = rewrite_query(question, history, api_key)

    # Step 2: Retrieve chunks
    chunks = retrieve(retrieval_query, store, top_k=top_k)
    if not chunks:
        return "No relevant content found in the paper to answer this question."

    retrieved_sections = list(dict.fromkeys(c["section"] for c in chunks))
    print(f"  [rag] Retrieved {len(chunks)} chunks from: {retrieved_sections}")

    # Step 3: Build NUMBERED context so LLM can cite by chunk number
    context_parts = []
    total_chars = 0
    for i, chunk in enumerate(chunks):
        entry = f"[CHUNK {i+1} | Section: {chunk['section']}]\n{chunk['text']}"
        if total_chars + len(entry) > MAX_CONTEXT_CHARS:
            break
        context_parts.append(entry)
        total_chars += len(entry)
    context = "\n\n".join(context_parts)

    # Step 4: Chain-of-evidence prompt
    # Forces the model to: (a) extract quotes, (b) then answer from quotes only
    # This structurally prevents sycophantic drift and answer anchoring
    system = """You are a strict evidence-based research assistant.

ABSOLUTE RULES — violation means failure:
1. NEVER start your response with "To clarify", "I can answer", "Sure", or any preamble.
2. NEVER reference previous answers or conversation history.
3. ONLY use facts that appear word-for-word in the CHUNKS below.
4. If no chunk contains the answer, output exactly: "The paper does not contain this information."
5. Always cite which CHUNK number your answer comes from."""

    user = (
        f"CHUNKS FROM PAPER:\n{context}\n\n"
        f"QUESTION: {question}\n\n"
        f"Step 1 — Copy the most relevant sentences from the chunks above that help answer the question.\n"
        f"Step 2 — Based ONLY on those sentences, write your answer.\n\n"
        f"Relevant sentences from chunks:"
    )

    return call_llm_with_system(system, user, api_key=api_key, temperature=0.0)