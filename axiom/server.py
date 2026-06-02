"""
server.py
---------
Axiom FastAPI backend.

Endpoints:
  GET  /                          — Frontend HTML
  GET  /api/status                — Health check
  POST /api/deploy                — Upload PDF → deploy to Somnia
  GET  /api/stream/{job_id}       — SSE progress stream for a deploy job
  GET  /api/compliance/{address}  — Get compliance history for a contract
  POST /api/monitor/{address}     — Manually trigger a compliance poll
"""

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

# Add the existing research pipeline to path
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from ingestion.pdf_loader      import load_pdf
from ingestion.text_extractor  import extract_text
from ingestion.section_splitter import split_into_sections
from ingestion.section_filter  import filter_sections
from pipeline.chunking         import chunk_sections
from pipeline.vector_store     import build_vector_store
from utils.helpers             import get_api_key

from core.solidity_codegen import generate_solidity
from core.deployer         import deploy_from_paper
from core.event_monitor    import ContractMonitor

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Axiom", description="Research Paper → Live Smart Contract + Compliance Monitor")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# In-memory state (reset on restart)
monitor   : ContractMonitor        = ContractMonitor()
jobs      : dict[str, dict]        = {}   # job_id → status dict
contracts : dict[str, dict]        = {}   # deployed_address → metadata


# ── Helpers ───────────────────────────────────────────────────────────────────

def _publish_to_data_streams(schema_type: str, data: dict):
    """Fire-and-forget: call ds_publish.js via Node subprocess."""
    scripts_dir = Path(__file__).parent / "scripts"
    if not (scripts_dir / "ds_publish.js").exists():
        return
    try:
        subprocess.run(
            ["node", "ds_publish.js", schema_type, json.dumps(data)],
            cwd=scripts_dir, timeout=30, capture_output=True,
        )
    except Exception as e:
        print(f"[server] Data Streams publish failed (non-fatal): {e}")


def _extract_contract_name(code: str) -> str:
    matches = re.findall(r"\bcontract\s+(\w+)", code)
    return matches[0] if matches else "GeneratedContract"


# ── Deployment pipeline (background task) ────────────────────────────────────

async def _run_deploy(job_id: str, pdf_path: str, query: str):
    job = jobs[job_id]

    async def step(msg: str):
        job["steps"].append(msg)
        print(f"[job:{job_id}] {msg}")
        await asyncio.sleep(0)   # yield so SSE flushes

    try:
        await step("Loading PDF...")
        reader = load_pdf(pdf_path)

        await step("Extracting text from paper...")
        raw_text = extract_text(reader, pdf_path=pdf_path)

        await step("Detecting sections...")
        sections = split_into_sections(raw_text)

        await step(f"Filtering relevant sections ({len(sections)} found, using AI)...")
        filtered = filter_sections(sections, groq_api_key=GROQ_API_KEY)
        if not filtered:
            raise ValueError("No relevant sections found after filtering.")

        await step(f"Building vector store from {len(filtered)} sections...")
        chunks = chunk_sections(filtered)
        store  = build_vector_store(chunks)

        await step("Generating Solidity from methodology (AI)...")
        gen = generate_solidity(query, store, GROQ_API_KEY)
        code   = gen["code"]
        events = gen["events"]
        cname  = gen["contract_name"]

        if code.startswith("// ERROR"):
            raise ValueError(code)

        await step(f"Solidity ready — contract: {cname}, events: {events}")

        paper_title = filtered[0]["title"] if filtered else "Research Paper"

        await step(f"Compiling and deploying '{cname}' to Somnia...")
        deploy = deploy_from_paper(code, cname, paper_title)

        await step(f"AxiomWatcher (Reactivity) deployed at {deploy['watcher_address'] or 'skipped'}...")
        monitor.register(deploy["deployed_address"], deploy["abi"], store, GROQ_API_KEY)

        await step("Publishing provenance to Somnia Data Streams...")
        _publish_to_data_streams("provenance", {
            "paperHash":        deploy["paper_hash"],
            "paperTitle":       paper_title,
            "deployedContract": deploy["deployed_address"],
            "explorerUrl":      deploy["explorer_url"],
        })

        contracts[deploy["deployed_address"].lower()] = {
            "abi":         deploy["abi"],
            "store":       store,
            "paper_title": paper_title,
            "watcher":     deploy["watcher_address"],
            "events":      events,
            "contract_name": cname,
        }

        job["status"] = "done"
        job["result"] = {
            "contract_address":  deploy["deployed_address"],
            "watcher_address":   deploy["watcher_address"],
            "contract_name":     cname,
            "paper_title":       paper_title,
            "explorer_url":      deploy["explorer_url"],
            "watcher_url":       deploy["watcher_url"],
            "solidity_code":     code,
            "events":            events,
        }
        await step(f"Done! Contract live at {deploy['deployed_address']}")

    except Exception as e:
        job["status"] = "error"
        job["error"]  = str(e)
        job["steps"].append(f"ERROR: {e}")
        print(f"[job:{job_id}] ERROR: {e}")
    finally:
        try:
            os.unlink(pdf_path)
        except Exception:
            pass


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def frontend():
    html = Path(__file__).parent / "frontend" / "index.html"
    if html.exists():
        return html.read_text(encoding="utf-8")
    return "<h1>Axiom</h1><p>Frontend not found — place index.html in axiom/frontend/</p>"


@app.get("/api/status")
async def status():
    return {
        "status":               "ok",
        "chain_id":             os.getenv("SOMNIA_CHAIN_ID", "50312"),
        "rpc":                  os.getenv("SOMNIA_RPC_URL", ""),
        "monitored_contracts":  len(contracts),
        "total_compliance_checks": len(monitor.get_results()),
    }


@app.post("/api/deploy")
async def deploy(
    pdf: UploadFile = File(...),
    query: str = Form(default="implement the core mechanism described in the paper methodology"),
):
    """
    Upload a research paper PDF and deploy it as a Somnia smart contract.
    Returns job_id — poll /api/stream/{job_id} for live progress.
    """
    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "File must be a PDF")
    if not GROQ_API_KEY:
        raise HTTPException(500, "GROQ_API_KEY not configured. Check your .env file.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await pdf.read())
        tmp_path = tmp.name

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "running", "steps": [], "result": None, "error": None}
    asyncio.create_task(_run_deploy(job_id, tmp_path, query))
    return {"job_id": job_id}


@app.get("/api/stream/{job_id}")
async def stream(job_id: str):
    """Server-Sent Events stream for deployment progress."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")

    async def generate() -> AsyncGenerator[str, None]:
        sent = 0
        while True:
            job   = jobs[job_id]
            steps = job["steps"]
            while sent < len(steps):
                yield f"data: {json.dumps({'type': 'step', 'message': steps[sent]})}\n\n"
                sent += 1
            if job["status"] == "done":
                yield f"data: {json.dumps({'type': 'done', 'result': job['result']})}\n\n"
                break
            elif job["status"] == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': job['error']})}\n\n"
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/compliance/{contract_address}")
async def compliance_history(contract_address: str):
    """Get all compliance records for a monitored contract."""
    records = monitor.get_results(contract_address)
    return {"contract_address": contract_address, "records": records, "total": len(records)}


@app.post("/api/monitor/{contract_address}")
async def trigger_poll(contract_address: str):
    """Manually trigger one compliance poll cycle for a contract."""
    addr = contract_address.lower()
    if addr not in contracts:
        raise HTTPException(404, "Contract not registered. Deploy it via /api/deploy first.")
    new = monitor.poll_once()
    return {"new_records": len(new), "records": new}


@app.post("/api/interact/{contract_address}")
async def interact(contract_address: str, function_name: str = None):
    """
    Send a demo transaction to a deployed contract to trigger an event.
    Auto-selects the first state-changing function if function_name is not given.
    """
    from core.deployer import interact_contract
    addr = contract_address.lower()
    if addr not in contracts:
        raise HTTPException(404, "Contract not registered. Deploy it first.")
    info = contracts[addr]
    try:
        result = interact_contract(contract_address, info["abi"], function_name)
        return result
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/stream/compliance/{contract_address}")
async def compliance_stream(contract_address: str):
    """SSE stream that pushes compliance records as they arrive."""
    addr = contract_address.lower()

    async def generate() -> AsyncGenerator[str, None]:
        sent = 0
        while True:
            records = monitor.get_results(addr)
            while sent < len(records):
                yield f"data: {json.dumps(records[sent])}\n\n"
                sent += 1
            await asyncio.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/contracts/{contract_address}/functions")
async def get_functions(contract_address: str):
    """Return the list of callable (state-changing) functions for a deployed contract."""
    addr = contract_address.lower()
    if addr not in contracts:
        raise HTTPException(404, "Contract not registered.")
    abi = contracts[addr]["abi"]
    fns = [
        {"name": f["name"], "inputs": f.get("inputs", [])}
        for f in abi
        if f.get("type") == "function"
        and f.get("stateMutability") not in ("view", "pure")
        and f.get("name") != "stop"
    ]
    return {"functions": fns}


@app.get("/api/contracts")
async def list_contracts():
    """List all deployed and monitored contracts."""
    return {
        addr: {k: v for k, v in info.items() if k not in ("abi", "store")}
        for addr, info in contracts.items()
    }


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global GROQ_API_KEY
    if not GROQ_API_KEY:
        try:
            GROQ_API_KEY = get_api_key()
        except SystemExit:
            print("[server] WARNING: GROQ_API_KEY not set — set it in axiom/.env")

    asyncio.create_task(monitor.run_forever())
    print("[server] Axiom is running at http://localhost:8000")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
