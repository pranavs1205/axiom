"""
solidity_codegen.py
-------------------
Generates deployable Solidity smart contract code from research paper methodology.
"""

import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../project"))

from pipeline.retrieval import retrieve_methodology
from pipeline.vector_store import VectorStore
from llm.groq_client import call_llm_with_system

MAX_CONTEXT_CHARS = 6000

SOLIDITY_SYSTEM_PROMPT = """You are an expert Solidity smart contract engineer.
Your task: implement the mechanism described in the research paper context as a valid Solidity contract.

HARD RULES:
1. Output ONLY Solidity source code. No markdown. No code fences. No explanations.
2. First line must be: // SPDX-License-Identifier: MIT
3. Second line must be: pragma solidity ^0.8.20;
4. Everything (events, state variables, constructor, functions) MUST be INSIDE the contract body.
5. NO imports — do NOT use @openzeppelin, @uniswap, or any external package.
6. Emit a named event for every significant state change.
7. NatSpec @notice/@param on public functions citing the paper section.
8. EVENTS: maximum 3 `indexed` parameters per event. Do NOT add indexed to more than 3 params.
9. NO floating point: Solidity has no float type. Represent decimals as scaled integers.
   Use uint256 with a SCALE constant. Example: 0.8 precision → uint256 constant SCALE = 1000; value = 800
   NEVER write: uint256 x = 0.8;  ALWAYS write: uint256 x = 800; // out of SCALE (1000)
10. REFERENCE TYPE PARAMETERS: string, bytes, and array params in functions MUST have a data location.
    Use `calldata` for external functions (cheaper). Use `memory` for public/internal functions.
    NEVER write: function foo(string _s)   ALWAYS write: function foo(string calldata _s)
    NEVER write: function bar(uint[] _arr) ALWAYS write: function bar(uint[] calldata _arr)
11. NO undefined functions: Every function you call must be fully implemented in the same contract.
    NEVER call a function you haven't written. If you need a helper, write it completely.
12. NO Python/JS-style inline array literals: Solidity does not support [a, b] as an expression.
    If you need to pass multiple values, use separate parameters or a storage/memory array.
    NEVER write: foo([a, b])   ALWAYS write: foo(a, b) or declare uint256[] memory arr; arr[0]=a; arr[1]=b; foo(arr)
13. Keep the contract SIMPLE and DEPLOYABLE. Avoid complex algorithms with loops over large arrays.
    If the paper describes complex math, approximate it with simple mappings and integer arithmetic.
    A working simple contract is better than a broken complex one.
14. ARGUMENT COUNT: Every function call MUST pass exactly the right number of arguments.
    Before writing any call, count the parameters in the function definition and match them exactly.
    NEVER write: someFunction() if someFunction(uint256 x) requires 1 argument.
    NEVER omit required constructor arguments when deploying contracts with `new`.

THE EXACT OUTPUT STRUCTURE (copy this skeleton):

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract <ContractName> {

    // ── Events ──────────────────────────────────────────────────────────────
    event <EventName1>(address indexed sender, uint256 indexed id, uint256 value);
    event <EventName2>(address indexed user, uint256 amount);

    // ── State Variables ─────────────────────────────────────────────────────
    address public owner;
    uint256 public someParam;

    // ── Constructor ─────────────────────────────────────────────────────────
    constructor(uint256 _someParam) {
        owner = msg.sender;
        someParam = _someParam;
    }

    // ── Core Functions ──────────────────────────────────────────────────────
    /// @notice <describe what this does per the paper>
    function coreAction(uint256 input) external returns (uint256) {
        // implement mechanism
        emit <EventName1>(msg.sender, 1, input);
        return input;
    }

    // ── View Functions ───────────────────────────────────────────────────────
    function getState() external view returns (uint256) {
        return someParam;
    }

    // === EMITTED EVENTS ===
    // <EventName1>(sender, id, value)
    // <EventName2>(user, amount)
}

REMINDER: events MUST be inside the contract {{ }} braces, not at file level.
"""


def _fix_structure(code: str) -> str:
    """
    Post-process LLM output to fix common structural mistakes.

    1. Strip markdown fences.
    2. Move any top-level event declarations inside the first contract body.
    3. Ensure SPDX + pragma are present.
    """
    # Strip markdown fences
    if "```solidity" in code:
        code = code.split("```solidity")[1].split("```")[0].strip()
    elif "```" in code:
        code = code.split("```")[1].split("```")[0].strip()

    lines = code.splitlines()

    # Separate top-level event declarations from the rest
    top_level_events: list[str] = []
    kept_lines: list[str] = []
    inside_contract = False

    for line in lines:
        stripped = line.strip()
        # Detect contract opening
        if re.match(r"^\s*contract\s+\w+", line):
            inside_contract = True
        if not inside_contract and re.match(r"^\s*event\s+\w+", line):
            # Collect event declared outside any contract
            top_level_events.append("    " + stripped)
        else:
            kept_lines.append(line)

    if top_level_events:
        print(f"[solidity_codegen] Moved {len(top_level_events)} top-level event(s) inside contract")
        # Insert moved events right after the first `contract X {` opening brace line
        final: list[str] = []
        inserted = False
        for line in kept_lines:
            final.append(line)
            if not inserted and re.match(r"^\s*contract\s+\w+.*\{", line):
                final.append("")
                final.append("    // ── Events (moved from file scope) ──")
                final.extend(top_level_events)
                inserted = True
        code = "\n".join(final)
    else:
        code = "\n".join(kept_lines)

    # Ensure SPDX line is present
    if "SPDX-License-Identifier" not in code:
        code = "// SPDX-License-Identifier: MIT\n" + code

    # Ensure pragma is present
    if "pragma solidity" not in code:
        spdx_end = code.find("\n") + 1
        code = code[:spdx_end] + "pragma solidity ^0.8.20;\n" + code[spdx_end:]

    code = _fix_indexed_events(code)
    code = _fix_float_literals(code)
    code = _fix_missing_data_locations(code)
    return code


def _fix_indexed_events(code: str) -> str:
    """Solidity only allows max 3 indexed params per event. Strip extras."""
    lines = code.splitlines()
    result = []
    for line in lines:
        if re.match(r"\s*event\s+\w+", line) and line.count("indexed") > 3:
            # Remove `indexed ` from the rightmost params until count reaches 3
            while line.count("indexed") > 3:
                pos = line.rfind(" indexed ")
                if pos == -1:
                    break
                line = line[:pos] + line[pos + 8:]  # drop ' indexed'
            print("[solidity_codegen] Fixed: too many indexed params in event")
        result.append(line)
    return "\n".join(result)


def _fix_float_literals(code: str) -> str:
    """
    Convert ALL float literals to scaled integer arithmetic.

    Two passes:
    1. Declarations:   uint256 x = 0.8;          → uint256 x = 800; // scaled by 1000
    2. Expressions:    value * 0.4                → value * 400 / 1000
                       0.4 * value                → 400 * value / 1000
    Any remaining bare float literal is replaced with its integer * 1000 form
    (rare edge cases like ternaries or return values).
    """
    def _scale(fval: str) -> int:
        return int(round(float(fval) * 1000))

    # Pass 1 — assignments: `uint256 x = 0.8;`
    def fix_decl(m: re.Match) -> str:
        s = _scale(m.group(3))
        print(f"[solidity_codegen] Fixed float decl: {m.group(3)} -> {s}")
        return f"{m.group(1)} {m.group(2)} = {s}; // scaled by 1000"

    code = re.sub(r"\b(u?int\d*)\s+(\w+)\s*=\s*(\d*\.\d+)\s*;", fix_decl, code)

    # Pass 2 — expressions: `identifier * 0.4`  →  `identifier * 400 / 1000`
    def fix_mul_right(m: re.Match) -> str:
        s = _scale(m.group(2))
        print(f"[solidity_codegen] Fixed float expr (*right): {m.group(2)} -> {s}/1000")
        return f"{m.group(1)} * {s} / 1000"

    code = re.sub(r"(\b\w+)\s*\*\s*(\d*\.\d+)", fix_mul_right, code)

    # Pass 3 — expressions: `0.4 * identifier`  →  `400 * identifier / 1000`
    def fix_mul_left(m: re.Match) -> str:
        s = _scale(m.group(1))
        print(f"[solidity_codegen] Fixed float expr (*left): {m.group(1)} -> {s}/1000")
        return f"{s} * {m.group(2)} / 1000"

    code = re.sub(r"(\d*\.\d+)\s*\*\s*(\b\w+)", fix_mul_left, code)

    # Pass 4 — any remaining bare float literal (e.g. in return / comparisons)
    # Process line by line to skip pragma / import / comment lines where
    # decimal dots are version numbers or valid syntax, not float values.
    SKIP_LINE = re.compile(r"^\s*(pragma|import|//|/\*|\*)")
    BARE_FLOAT = re.compile(r"\b\d*\.\d+\b")

    def fix_bare(m: re.Match) -> str:
        fval = m.group(0)
        s = _scale(fval)
        print(f"[solidity_codegen] Fixed bare float: {fval} -> {s}")
        return str(s)

    lines = code.splitlines()
    for i, line in enumerate(lines):
        if not SKIP_LINE.match(line):
            lines[i] = BARE_FLOAT.sub(fix_bare, line)
    code = "\n".join(lines)

    return code


# Reference types that require a data location keyword in function signatures.
# Matches: string | bytes (not bytes1-32) | any T[] array type
# Does NOT match value types: address, uint256, int256, bool, bytesN
_REF_TYPES = re.compile(
    r"\b(string|bytes(?!\d)|\w+(?:\[\])+)"
)
_DATA_LOC = re.compile(r"\b(memory|calldata|storage)\b")


def _fix_missing_data_locations(code: str) -> str:
    """
    Add missing `calldata` / `memory` data locations to reference-type parameters
    in function signatures.

    Strategy: scan each function signature line for reference-type params that
    lack a location keyword between the type and the param name.
    - external functions → calldata
    - public / internal / private → memory
    """
    lines = code.splitlines()
    result = []

    for line in lines:
        # Only process function signature lines that contain ref types without a location
        if re.search(r"\bfunction\b", line) and _REF_TYPES.search(line):
            # Choose location based on function visibility
            loc = "calldata" if re.search(r"\bexternal\b", line) else "memory"

            def inject_location(m: re.Match) -> str:
                matched = m.group(0)
                # Check if a data location keyword already immediately follows
                end = m.end()
                rest = line[end:]
                if _DATA_LOC.match(rest.lstrip()):
                    return matched  # already has location
                return f"{matched} {loc}"

            new_line = _REF_TYPES.sub(inject_location, line)
            if new_line != line:
                print(f"[solidity_codegen] Fixed missing data location ({loc}) in: {line.strip()[:60]}")
            result.append(new_line)
        else:
            result.append(line)

    return "\n".join(result)


FIX_SYSTEM_PROMPT = """You are an expert Solidity 0.8.20 compiler and debugger.
The code below fails to compile. Study the EXACT error message and fix it.
Output ONLY the complete corrected Solidity source. No markdown, no explanations.

Core rules to never break:
- No imports or external packages
- No float literals (use scaled integers)
- Max 3 indexed params per event
- All string/bytes/array params need calldata or memory
- Every function call must pass exactly the right number of arguments
- Never call an undefined function"""


def _try_compile(code: str, contract_name: str) -> str | None:
    """Try to compile code with solcx. Returns focused error string or None on success."""
    try:
        import solcx
        if "0.8.20" not in [str(v) for v in solcx.get_installed_solc_versions()]:
            solcx.install_solc("0.8.20")
        solcx.set_solc_version("0.8.20")
        solcx.compile_source(code, output_values=["abi", "bin"], optimize=True, optimize_runs=200)
        return None  # success
    except Exception as e:
        err = str(e)
        # Extract just the stderr section which has the actual solc errors with line numbers
        if "stderr:" in err:
            err = err[err.index("stderr:"):].strip()
        return err[:2000]  # give LLM enough context including line numbers


def _fix_with_llm(code: str, error: str, api_key: str) -> str:
    """Ask the LLM to fix a specific Solidity compilation error."""
    user_prompt = (
        f"COMPILATION ERROR (includes line numbers):\n{error}\n\n"
        f"FULL CONTRACT CODE:\n{code}\n\n"
        "Find the exact lines causing the error and fix them. "
        "Output ONLY the complete corrected Solidity source code."
    )
    raw = call_llm_with_system(FIX_SYSTEM_PROMPT, user_prompt, api_key=api_key, temperature=0.0)
    return _fix_structure(raw)


def generate_solidity(query: str, store: VectorStore, api_key: str, top_k: int = 6) -> dict:
    """
    Generate Solidity smart contract code from paper methodology chunks.

    Returns dict: {code, contract_name, events, context_chunks}
    """
    chunks = retrieve_methodology(query, store, top_k=top_k)
    if not chunks:
        return {
            "code": "// ERROR: No methodology context found.",
            "contract_name": "Unknown",
            "events": [],
            "context_chunks": [],
        }

    context_parts = []
    total = 0
    for chunk in chunks:
        entry = f"[Section: {chunk['section']}]\n{chunk['text']}"
        if total + len(entry) > MAX_CONTEXT_CHARS:
            break
        context_parts.append(entry)
        total += len(entry)

    context = "\n\n---\n\n".join(context_parts)

    user_prompt = (
        f"Implement in Solidity: {query}\n\n"
        f"METHODOLOGY FROM PAPER:\n{context}\n\n"
        "Output ONLY Solidity code following the exact skeleton above. "
        "All events and all code must be inside the contract {{ }} body."
    )

    print(f"[solidity_codegen] Generating from {len(context_parts)} chunks...")
    raw = call_llm_with_system(SOLIDITY_SYSTEM_PROMPT, user_prompt, api_key=api_key, temperature=0.1)
    code = _fix_structure(raw)

    # Compile-check-and-fix loop (up to 3 LLM fix attempts)
    for attempt in range(4):
        contract_name_tmp = _extract_contract_name(code)
        err = _try_compile(code, contract_name_tmp)
        if err is None:
            print(f"[solidity_codegen] Compile check passed (attempt {attempt})")
            break
        if attempt < 3:
            print(f"[solidity_codegen] Compile error (attempt {attempt}), asking LLM to fix...")
            print(f"[solidity_codegen] Error snippet: {err[:300]}")
            code = _fix_with_llm(code, err, api_key)
        else:
            print(f"[solidity_codegen] Compile still failing after 3 fix attempts — passing to deployer")

    contract_name = _extract_contract_name(code)
    events = re.findall(r"\bevent\s+(\w+)\s*\(", code)

    print(f"[solidity_codegen] Contract: {contract_name} | Events: {events}")
    return {
        "code": code,
        "contract_name": contract_name,
        "events": events,
        "context_chunks": context_parts,
    }


def _extract_contract_name(code: str) -> str:
    matches = re.findall(r"\bcontract\s+(\w+)", code)
    return matches[0] if matches else "GeneratedContract"
