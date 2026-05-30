"""
helpers.py
----------
Shared utility functions used across the project.
"""

import os
import sys


def get_api_key(env_var: str = "GROQ_API_KEY") -> str:
    """
    Retrieve the Groq API key from environment variables or a .env file.

    Raises:
        SystemExit: If the environment variable is not set.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass

    key = os.environ.get(env_var, "").strip()
    if not key:
        print(f"[helpers] ERROR: Environment variable '{env_var}' is not set.")
        print(f"  Windows: set {env_var}=your_key_here")
        print(f"  Or add it to a .env file: {env_var}=your_key_here")
        sys.exit(1)
    return key


def print_separator(title: str = "", width: int = 60) -> None:
    """Print a visual separator line for CLI output readability."""
    if title:
        print(f"\n{'=' * width}")
        print(f"  {title}")
        print(f"{'=' * width}\n")
    else:
        print("=" * width)


def truncate_display(text: str, max_chars: int = 500) -> str:
    """Truncate text for display, appending an ellipsis if cut."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated for display]"


def validate_pdf_path(path: str) -> str:
    """
    Validate that a path points to a readable PDF file.

    Raises:
        SystemExit: If the path is invalid or not a PDF.
    """
    if not os.path.exists(path):
        print(f"[helpers] ERROR: File not found: {path}")
        sys.exit(1)
    if not path.lower().endswith(".pdf"):
        print(f"[helpers] ERROR: Expected a .pdf file, got: {path}")
        sys.exit(1)
    return path
