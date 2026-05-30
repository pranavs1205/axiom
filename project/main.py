"""
main.py
-------
CLI entry point for the Research Paper Intelligence System.

v5 changes:
  - History reset: type 'clear' to wipe conversation history
  - Answers stored in history are truncated to 150 chars (prevents bleeding)
  - 'clear' command feedback shown to user
"""

import argparse
import sys

from ingestion.pdf_loader import load_pdf
from ingestion.text_extractor import extract_text
from ingestion.section_splitter import split_into_sections
from ingestion.section_filter import filter_sections
from pipeline.chunking import chunk_sections
from pipeline.vector_store import build_vector_store
from pipeline.research import explain_section, summarize_section, rag_qa, HISTORY_ANSWER_CAP
from pipeline.codegen import generate_code
from utils.helpers import get_api_key, print_separator, truncate_display, validate_pdf_path


def _pick_section(filtered_sections: list, action: str) -> int:
    """Prompt the user to pick a valid section index with retry on bad input."""
    max_idx = len(filtered_sections) - 1
    while True:
        try:
            raw = input(f"\nEnter section NUMBER [0-{max_idx}] to {action} (or -1 to skip): ").strip()
            idx = int(raw)
            if idx == -1:
                return -1
            if 0 <= idx <= max_idx:
                return idx
            print(f"  Invalid: enter a number between 0 and {max_idx}, or -1 to skip.")
        except ValueError:
            print("  Please enter a NUMBER (e.g. 0, 1, 2...), not text.")
        except KeyboardInterrupt:
            return -1


def run_ingestion_pipeline(pdf_path: str, api_key: str):
    """Run the full ingestion pipeline: PDF -> filtered chunks -> vector store."""
    print_separator("INGESTION PIPELINE")
    reader   = load_pdf(pdf_path)
    raw_text = extract_text(reader, pdf_path=pdf_path)
    sections = split_into_sections(raw_text, debug=True)
    filtered = filter_sections(sections, groq_api_key=api_key)

    if not filtered:
        print("[main] ERROR: No relevant sections found after filtering. Exiting.")
        sys.exit(1)

    chunks = chunk_sections(filtered)
    store  = build_vector_store(chunks)
    return filtered, store


def run_research_mode(filtered_sections: list, store, api_key: str) -> None:
    """Interactive research pipeline with multi-turn Q&A and history management."""
    print_separator("RESEARCH PIPELINE")

    print("Available sections (use the NUMBER on the left):")
    for i, sec in enumerate(filtered_sections):
        preview = sec["content"][:80].replace("\n", " ")
        print(f"  [{i}] {sec['title']}  —  {preview}...")

    # Section Explanation
    print_separator("Section Explanation")
    idx = _pick_section(filtered_sections, "EXPLAIN")
    if idx >= 0:
        print(f"\nExplaining: {filtered_sections[idx]['title']}...\n")
        print(truncate_display(explain_section(filtered_sections[idx], api_key), 1500))

    # Section Summarization
    print_separator("Section Summarization")
    idx = _pick_section(filtered_sections, "SUMMARIZE")
    if idx >= 0:
        print(f"\nSummarizing: {filtered_sections[idx]['title']}...\n")
        print(summarize_section(filtered_sections[idx], api_key))

    # Multi-turn RAG Q&A
    print_separator("RAG Q&A — Ask questions about the paper")
    print("Commands: type \'quit\' to exit | type \'clear\' to reset conversation history\n")

    history: list[dict] = []

    while True:
        try:
            question = input("Your question: ").strip()

            if not question:
                continue

            if question.lower() == "quit":
                break

            # Allow user to manually clear history if answers start drifting
            if question.lower() == "clear":
                history = []
                print("  [history cleared] Conversation history has been reset.\n")
                continue

            print("\nSearching paper...\n")
            answer = rag_qa(question, store, api_key, history=history)
            print(f"Answer:\n{answer}\n")

            # Store user question in full, but cap answer length to prevent
            # prompt bleeding where long wrong answers pollute future queries
            history.append({"role": "user",     "content": question})
            history.append({"role": "assistant", "content": answer[:HISTORY_ANSWER_CAP]})

        except KeyboardInterrupt:
            break


def run_codegen_mode(store, api_key: str) -> None:
    """Interactive code generation pipeline from paper methodology."""
    print_separator("CODE GENERATION PIPELINE")
    print("Describe what you want to implement from the paper methodology.")
    print("Type \'quit\' to exit.\n")

    while True:
        try:
            query = input("What to implement: ").strip()
            if not query or query.lower() == "quit":
                break
            print("\nGenerating code...\n")
            code = generate_code(query, store, api_key)
            print_separator("Generated Code")
            print(code)
            print_separator()
        except KeyboardInterrupt:
            break


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Research Paper Intelligence System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py paper.pdf --mode research
  python main.py paper.pdf --mode codegen
        """
    )
    parser.add_argument("pdf", help="Path to the research paper PDF.")
    parser.add_argument(
        "--mode",
        choices=["research", "codegen"],
        default="research",
        help="Pipeline mode: \'research\' or \'codegen\'.",
    )
    args = parser.parse_args()

    pdf_path = validate_pdf_path(args.pdf)
    api_key = get_api_key()


    print_separator(f"Research Paper Intelligence System — Mode: {args.mode.upper()}")
    filtered_sections, store = run_ingestion_pipeline(pdf_path, api_key)

    if args.mode == "research":
        run_research_mode(filtered_sections, store, api_key)
    elif args.mode == "codegen":
        run_codegen_mode(store, api_key)

    print_separator("Done")


if __name__ == "__main__":
    main()