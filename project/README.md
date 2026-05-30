# Research Paper Intelligence System

A production-style Python system for ingesting, understanding, and implementing research papers.

## Features

- **Ingestion Pipeline**: PDF loading → text extraction → section splitting → two-stage filtering (rule-based + LLM)
- **Research Pipeline**: Section explanation, summarization, and RAG-based Q&A
- **Code Generation Pipeline**: Methodology-grounded Python code generation with explicit assumptions

## Project Structure

```
project/
├── ingestion/
│   ├── pdf_loader.py        # PDF file loading and validation
│   ├── text_extractor.py    # Raw text extraction from PDF pages
│   ├── section_splitter.py  # Heuristic-based section detection
│   └── section_filter.py    # Two-stage section filtering (rules + LLM)
├── pipeline/
│   ├── chunking.py          # Sliding window chunking (800 chars, 100 overlap)
│   ├── vector_store.py      # FAISS index build/save/load
│   ├── retrieval.py         # Semantic retrieval + methodology-specific retrieval
│   ├── codegen.py           # Code generation pipeline
│   └── research.py          # Explain / summarize / RAG Q&A
├── llm/
│   └── groq_client.py       # Groq LLM wrapper (single + system-user prompts)
├── utils/
│   └── helpers.py           # CLI helpers, validation, display utilities
├── main.py                  # CLI entry point
├── requirements.txt
└── .env.example
```

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your Groq API key
export GROQ_API_KEY=your_key_here
# or copy .env.example to .env and fill it in, then: source .env
```

## Usage

### Research Mode
Explains sections, summarizes sections, and answers questions about the paper.

```bash
python main.py path/to/paper.pdf --mode research
```

### Code Generation Mode
Retrieves methodology sections and generates Python implementation code.

```bash
python main.py path/to/paper.pdf --mode codegen
```

## Design Decisions

| Decision | Rationale |
|---|---|
| Two-stage section filtering | Rules are fast and reliable for obvious boilerplate; LLM handles ambiguous cases |
| LLM returns strict JSON for filtering | Enables safe programmatic parsing; falls back gracefully on failure |
| Sliding window chunking | PDF-extracted text lacks clean sentence boundaries; fixed-size windows are more robust |
| FAISS IndexFlatL2 | Exact search; suitable for paper-scale corpora (hundreds of chunks) |
| Over-fetch in methodology retrieval | Ensures enough methodology chunks even if they rank lower than general chunks |
| LLM used for reasoning only | LLM never regenerates or transforms the raw data — prevents hallucination |
| Context truncation before LLM calls | Prevents silent overflow errors that cause degraded output |

## Getting a Groq API Key

1. Sign up at [console.groq.com](https://console.groq.com)
2. Create an API key under API Keys
3. Export it: `export GROQ_API_KEY=gsk_...`
