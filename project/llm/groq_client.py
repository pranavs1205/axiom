"""
groq_client.py
--------------
Thin wrapper around the Groq SDK for all LLM calls.

Uses the groq SDK directly (not langchain_groq) for reliability.
Retries up to 3 times on transient errors. Auth errors fail immediately.
"""

import time
from groq import Groq

DEFAULT_MODEL    = "llama-3.1-8b-instant"
MAX_PROMPT_CHARS = 24_000  # Groq llama-3.1-8b supports 128k context; 24k gives plenty of room
MAX_RETRIES      = 3


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    for sep in (". ", ".\n", "? ", "! "):
        pos = truncated.rfind(sep)
        if pos > max_chars * 0.6:
            return truncated[: pos + 1] + "\n\n[...content truncated for length...]"
    return truncated + "\n\n[...content truncated for length...]"


def call_llm(prompt: str, api_key: str, model: str = DEFAULT_MODEL, temperature: float = 0.2) -> str:
    """Send a single-turn prompt. Retries on transient errors."""
    if len(prompt) > MAX_PROMPT_CHARS:
        print(f"[groq_client] Prompt truncated from {len(prompt)} to ~{MAX_PROMPT_CHARS} chars.")
        prompt = _truncate_at_sentence(prompt, MAX_PROMPT_CHARS)

    messages = [{"role": "user", "content": prompt}]
    return _call(messages, api_key, model, temperature)


def call_llm_with_system(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
) -> str:
    """Send a system + user prompt. Trims user prompt if combined exceeds limit."""
    combined = len(system_prompt) + len(user_prompt)
    if combined > MAX_PROMPT_CHARS:
        budget = MAX_PROMPT_CHARS - len(system_prompt)
        print(f"[groq_client] User prompt truncated from {len(user_prompt)} to ~{budget} chars.")
        user_prompt = _truncate_at_sentence(user_prompt, budget)

    messages = [
        {"role": "system",  "content": system_prompt},
        {"role": "user",    "content": user_prompt},
    ]
    return _call(messages, api_key, model, temperature)


def _call(messages: list, api_key: str, model: str, temperature: float) -> str:
    client     = Groq(api_key=api_key)
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            last_error = e
            err = str(e).lower()
            if "401" in err or "authentication" in err or "invalid api key" in err:
                raise RuntimeError(f"[groq_client] Authentication failed: {e}") from e
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt
                print(f"[groq_client] Attempt {attempt + 1} failed, retrying in {wait}s: {e}")
                time.sleep(wait)

    raise RuntimeError(f"[groq_client] LLM call failed after {MAX_RETRIES} attempts: {last_error}") from last_error
