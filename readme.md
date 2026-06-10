# Axiom — Research Paper to Live Smart Contract

Axiom is a multi-agent system that turns any research paper PDF into a live, autonomously-monitored smart contract on Somnia — in minutes, not months.

---

## Architecture

Three cooperating AI agents:

| Agent | Role |
|---|---|
| **PaperReader** | Ingests PDF, detects sections, builds FAISS vector store |
| **DeployAgent** | RAG → Groq/Llama → Solidity codegen → compile → deploy to Somnia |
| **ComplianceAgent** | Monitors every on-chain event, judges compliance against paper via RAG |

On-chain components:
- **AxiomWatcher.sol** — Reactivity subscriber, triggers ComplianceAgent in the same block
- **ProvenanceRegistry.sol** — On-chain paper→contract lineage record
- **ComplianceLog.sol** — Append-only on-chain compliance verdict store

---

## Somnia-specific features used

| Feature | How Axiom uses it |
|---|---|
| **Reactivity** | AxiomWatcher subscribes to deployed contract events via precompile `0x100`. Compliance check fires in the same block — trustless, no off-chain keeper |
| **Data Streams** | Provenance and compliance verdicts published as typed schemas (`axiom_provenance_v1`, `axiom_compliance_v1`) — subscribable by any dApp |
| **100ms blocks / 1M TPS** | Compliance verdict is ready before a human notices the original transaction |

---

## Setup

### Requirements
- Python 3.11+
- Node.js 18+
- Somnia testnet wallet with STT tokens ([faucet](https://testnet.somnia.network))
- Groq API key ([console.groq.com](https://console.groq.com))

### Install

```bash
pip install -r axiom/requirements.txt
cd axiom && npm install
```

### Configure

```bash
cp axiom/.env.example axiom/.env
# Fill in: GROQ_API_KEY, SOMNIA_PRIVATE_KEY, SOMNIA_RPC_URL, SOMNIA_CHAIN_ID
```

> **SOMNIA_PRIVATE_KEY** — export from MetaMask: Account Details → Export Private Key.
> It is a 64-character hex string starting with `0x`. Do NOT paste the wallet address here.

### Run

```bash
cd axiom
python server.py
# Open http://localhost:8000
```

---

## Deployment (Render)

1. Connect this repo at [render.com](https://render.com) → New Web Service
2. **Build:** `pip install -r axiom/requirements.txt && cd axiom && npm install`
3. **Start:** `cd axiom && uvicorn server:app --host 0.0.0.0 --port $PORT`
4. Set env vars: `GROQ_API_KEY`, `SOMNIA_PRIVATE_KEY`, `SOMNIA_RPC_URL=https://api.infra.testnet.somnia.network`, `SOMNIA_CHAIN_ID=50312`
5. After first deploy: copy `PROVENANCE_REGISTRY_ADDRESS` and `COMPLIANCE_LOG_ADDRESS` from logs into env vars

---

## Project structure

```
research_paper_intelligence/
├── axiom/
│   ├── contracts/
│   │   ├── AxiomWatcher.sol        Reactivity subscriber
│   │   ├── ComplianceLog.sol       On-chain verdict store
│   │   └── ProvenanceRegistry.sol
│   ├── core/
│   │   ├── solidity_codegen.py     RAG → LLM → Solidity + post-processor + compile-fix loop
│   │   ├── deployer.py             py-solc-x compile + Somnia deploy (no Hardhat)
│   │   ├── compliance_agent.py     RAG compliance checker + on-chain verdict writer
│   │   └── event_monitor.py        Background event poller
│   ├── scripts/
│   │   └── ds_publish.js           Somnia Data Streams publisher
│   ├── frontend/index.html         Single-page UI with SSE pipeline visualization
│   └── server.py                   FastAPI backend
└── project/                        Original RAG pipeline (shared)
    ├── ingestion/                  PDF loader, text extractor, section splitter/filter
    ├── pipeline/                   Chunking, vector store, retrieval
    └── llm/                        Groq client
```

---

## Troubleshooting

All errors hit during development and their fixes.

---

### 1. `load_dotenv` not overriding system environment variables
**Error:** Stale `GROQ_API_KEY` from system env overrides `.env`  
**Fix:** Use `load_dotenv(override=True)` everywhere  
**Files:** `server.py`, `deployer.py`, `event_monitor.py`, `project/utils/helpers.py`

---

### 2. Section splitter detects only 1 section ("preamble")
**Error:** `split_into_sections()` returns the whole PDF as one section  
**Cause:** Research PDFs lack blank lines around headings after text extraction  
**Fix:** Added structural fallback using title-case detection. If preamble > 70% of content, switch to structural split. Detects ~11 sections.  
**File:** `project/ingestion/section_splitter.py`

---

### 3. LLM section filter removes all sections
**Error:** `filter_sections()` returns `[]`  
**Fix:** Safety net — if LLM output is empty, return all input sections unchanged  
**File:** `project/ingestion/section_filter.py`

---

### 4. Solidity events declared outside contract body
**Error:** `solc` — event declarations at file scope  
**Fix:** `_fix_structure()` post-processor moves top-level events inside the first contract body  
**File:** `axiom/core/solidity_codegen.py`

---

### 5. More than 3 `indexed` parameters in an event
**Error:** `solc` — `Only 3 indexed arguments allowed`  
**Fix:** `_fix_indexed_events()` strips `indexed` from rightmost params until count is 3  
**File:** `axiom/core/solidity_codegen.py`

---

### 6. Float literals in Solidity (`uint256 x = 0.8`)
**Error:** `solc` — `Type rational_const not implicitly convertible to uint256`  
**Fix:** 4-pass `_fix_float_literals()` — assignments, `x * 0.N`, `0.N * x`, bare literals. Skips pragma/import/comment lines.  
**File:** `axiom/core/solidity_codegen.py`

---

### 7. Missing data location for `string` / array parameters
**Error:** `solc` — `Data location must be specified`  
**Fix:** `_fix_missing_data_locations()` injects `calldata` (external) or `memory` (public/internal)  
**File:** `axiom/core/solidity_codegen.py`

---

### 8. LLM calls undefined function / uses Python-style array literals `[a, b]`
**Error:** `solc` — `Undeclared identifier` or invalid syntax  
**Fix:** Added Rules 11–13 to system prompt. Added compile-check-and-LLM-fix loop (up to 2 retries on failure).  
**File:** `axiom/core/solidity_codegen.py`

---

### 9. `Unknown kwargs: ['gasPrice']` — web3.py v7
**Error:** `eth_account` v0.13 rejects `gasPrice` when EIP-1559 fields are also present  
**Cause:** `build_transaction()` in web3.py v7 auto-injects `maxFeePerGas`/`maxPriorityFeePerGas`; mixing with `gasPrice` fails signing  
**Fix:** Strip `maxFeePerGas`, `maxPriorityFeePerGas`, `accessList` before signing; set `gasPrice` for legacy type-0 transactions  
**Files:** `axiom/core/deployer.py`, `axiom/core/compliance_agent.py`

---

### 10. `gas price below base fee`
**Error:** RPC rejects tx — `{'code': -32000, 'message': 'gas price below base fee'}`  
**Cause:** Hardcoded `gasPrice = 1 gwei`; Somnia testnet base fee is 6+ gwei  
**Fix:** Use `w3.eth.gas_price` to query network gas price dynamically  
**Files:** `axiom/core/deployer.py`, `axiom/core/compliance_agent.py`

---

### 11. `event_monitor` can't find ComplianceLog ABI (Hardhat artifacts missing)
**Error:** `_get_complog_abi()` returns `None` — looks for `artifacts/` directory that doesn't exist  
**Fix:** Rewritten to compile `ComplianceLog.sol` directly from source via py-solc-x  
**File:** `axiom/core/event_monitor.py`

---

### 12. `lstrip("0x")` corrupts tx hashes with leading zero digits
**Error:** `bytes.fromhex()` fails — hash bytes are wrong length  
**Cause:** `"0x00abc".lstrip("0x")` strips leading `0` digits too  
**Fix:** Use `raw_hash[2:]` instead of `lstrip("0x")`  
**File:** `axiom/core/compliance_agent.py`

---

### 13. `UnicodeDecodeError` reading `index.html` on Windows
**Error:** `'charmap' codec can't decode byte 0x8f`  
**Cause:** `Path.read_text()` uses Windows default encoding (cp1252); HTML is UTF-8  
**Fix:** `html.read_text(encoding="utf-8")`  
**File:** `axiom/server.py`

---

### 14. Private key validation — 20 bytes instead of 32
**Error:** `ValidationError: Unexpected private key length: Expected 32, but got 20 bytes`  
**Cause:** Wallet address (20 bytes) was placed in `SOMNIA_PRIVATE_KEY` instead of the private key (32 bytes)  
**Fix:** Export from MetaMask → Account Details → Export Private Key → copy the 64-char hex string

---

### 15. GitHub CLI not found in terminal after install
**Cause:** Installed to `C:\Program Files\GitHub CLI\` but not in system PATH  
**Fix:**
```powershell
[System.Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";C:\Program Files\GitHub CLI", "User")
```
Open a new terminal after running this.

---

### 16. GitHub push rejected — `Invalid username or token`
**Cause:** GitHub no longer accepts password authentication for git operations  
**Fix:** `gh auth login` (GitHub CLI) then `gh auth setup-git` before pushing

---

### 17. `Incorrect argument count. Expected '1', got '0'`
**Error:** `solc` — function or constructor called with wrong number of arguments  
**Cause:** LLM generates a call like `someFunction()` but the function definition requires 1+ parameters. Also occurs with `new SomeContract()` when the constructor requires args.  
**Fix:**
- Added Rule 14 to system prompt: every call must match its definition's argument count exactly
- Increased `_try_compile` error context from 800 → 2000 chars (includes line numbers for the LLM to pinpoint the exact call)
- Increased compile-fix retry loop from 2 → 3 attempts
- Improved `FIX_SYSTEM_PROMPT` to be more explicit about checking argument counts  
**File:** `axiom/core/solidity_codegen.py`

---

### 18. LLM user prompt truncated to ~100 chars (generic contract output)
**Error:** `[groq_client] User prompt truncated from 4637 to ~108 chars` — LLM generates a useless generic `MechanismContract` instead of anything paper-specific  
**Cause:** `MAX_PROMPT_CHARS = 4_000` in `groq_client.py`. The Solidity system prompt alone is ~3,900 chars, leaving only ~100 chars budget for the actual paper context.  
**Fix:** Raised `MAX_PROMPT_CHARS` to `24_000`. Groq's Llama 3.1-8b supports 128k context window — 24k gives plenty of room for system prompt and paper chunks combined.  
**File:** `project/llm/groq_client.py`

---

### 19. `Incorrect argument count. Expected '1', got '0'` at deploy (not compile)
**Error:** web3.py raises this at deploy time even though `_try_compile()` passed  
**Cause:** Generated contract has a constructor requiring 1+ arguments, but `deploy_from_paper()` always calls `deploy_contract()` with no constructor args  
**Fix:** Before deploying, read constructor inputs from the ABI and auto-generate defaults using `_default_arg()`. Types: `address` → wallet address, `uint` → 1, `string` → "axiom-demo", `bool` → True  
**File:** `axiom/core/deployer.py`

---

### 20. `Transaction reverted` during contract deployment (constructor `require` fails)
**Error:** `[deployer] Transaction reverted: <tx_hash>` — tx sent but constructor logic rejects default args  
**Cause:** LLM generates constructor with parameters (e.g. `constructor(uint256 threshold, ...)`) and `require()` statements; our auto-generated defaults of `1` fail those checks  
**Fix:**
- Added Rule 15 to system prompt: constructor MUST take zero parameters; all config hardcoded inside body
- Updated skeleton in prompt to show `constructor()` with no args
- Added post-deploy code check in `deploy_contract()`: verifies `get_code(address) != 0x` so reverted constructors give a clear error instead of a mysterious revert  
**Files:** `axiom/core/solidity_codegen.py`, `axiom/core/deployer.py`

---

### 21. LLM ignores Rule 15 and still generates constructor parameters
**Error:** Transaction reverts because auto-generated defaults (`1`) fail constructor `require()` checks  
**Cause:** LLM prompt rules are advisory — the model sometimes still generates `constructor(uint256 x, ...)` regardless  
**Fix (v1 — insufficient):** Added `_fix_constructor_params()` post-processor that strips params and replaces param name references with hardcoded defaults. But `require(threshold < maxScore)` → `require(1 < 1)` → still reverts.  
**File:** `axiom/core/solidity_codegen.py`

---

### 22. `_fix_constructor_params()` leaves failing `require()` in constructor body
**Error:** Transaction reverts even after param stripping — `require(1 < 1)` is always false  
**Cause:** Replacing param names with `1` doesn't fix comparisons between two params or any other business logic that can revert  
**Fix:** Replaced `_fix_constructor_params()` with `_fix_constructor()` which uses brace-depth counting to replace the ENTIRE constructor block:
- Scans line-by-line tracking `{` depth
- Finds ctor_start (line matching `constructor(`) and ctor_end (line where depth returns to 0)
- Replaces everything in that range with `constructor() { owner = msg.sender; }` (or just `constructor() {}` if no `owner` state variable)
- Eliminates all constructor `require()`, param assignments, and business logic — nothing inside can revert  
**File:** `axiom/core/solidity_codegen.py`

---

### 23. Transaction reverts with opaque tx hash — no error details
**Error:** `[deployer] Transaction reverted: 4b33126e...` — no indication of why  
**Cause:** `_send_and_wait()` only checks `receipt["status"] != 1` and raises with the hash, giving no revert reason  
**Fix:** After a failed receipt, simulate the same tx with `w3.eth.call()` at the reverted block number — the node returns the revert reason string in the exception  
**File:** `axiom/core/deployer.py`
