"""
deployer.py
-----------
Compiles and deploys Solidity contracts to Somnia using web3.py + py-solc-x.

Pipeline:
  1. Compile generated paper contract (py-solc-x)
  2. Deploy generated contract to Somnia
  3. Compile + deploy AxiomWatcher (py-solc-x — no Hardhat required)
  4. Auto-deploy ProvenanceRegistry + ComplianceLog if not in .env
  5. Register provenance on-chain
  6. Return full result dict (all keys server.py and frontend expect)
"""

import hashlib
import json
import os
import re
from pathlib import Path

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from dotenv import load_dotenv, set_key

_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(_ENV_PATH, override=True)

SOMNIA_RPC  = os.getenv("SOMNIA_RPC_URL",  "https://api.infra.testnet.somnia.network")
CHAIN_ID    = int(os.getenv("SOMNIA_CHAIN_ID", "50312"))
PRIVATE_KEY = os.getenv("SOMNIA_PRIVATE_KEY", "")

CONTRACTS_DIR = Path(__file__).parent.parent / "contracts"

EXPLORER_BASE = (
    "https://shannon-explorer.somnia.network"
    if CHAIN_ID == 50312
    else "https://explorer.somnia.network"
)


# ── Web3 ──────────────────────────────────────────────────────────────────────

def get_web3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(SOMNIA_RPC))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not w3.is_connected():
        raise ConnectionError(f"[deployer] Cannot connect to {SOMNIA_RPC}")
    return w3


def _account(w3: Web3):
    if not PRIVATE_KEY:
        raise EnvironmentError("[deployer] SOMNIA_PRIVATE_KEY not set in axiom/.env")
    return w3.eth.account.from_key(PRIVATE_KEY)


# ── Compilation ───────────────────────────────────────────────────────────────

def compile_solidity(source_code: str, contract_name: str) -> tuple[list, str]:
    """Compile self-contained Solidity. Returns (abi, bytecode_hex)."""
    import solcx

    if "0.8.20" not in [str(v) for v in solcx.get_installed_solc_versions()]:
        print("[deployer] Installing solc 0.8.20 (first time only)...")
        solcx.install_solc("0.8.20")
    solcx.set_solc_version("0.8.20")

    compiled = solcx.compile_source(
        source_code,
        output_values=["abi", "bin"],
        optimize=True,
        optimize_runs=200,
    )

    contract_key = next((k for k in compiled if contract_name in k), list(compiled.keys())[0])
    abi      = compiled[contract_key]["abi"]
    bytecode = compiled[contract_key]["bin"]
    print(f"[deployer] Compiled '{contract_name}': {len(bytecode) // 2} bytes")
    return abi, bytecode


def _compile_contract_file(filename: str) -> tuple[list, str]:
    """Compile a contract from axiom/contracts/ by filename."""
    source = (CONTRACTS_DIR / filename).read_text()
    name   = filename.replace(".sol", "")
    return compile_solidity(source, name)


# ── Deployment ────────────────────────────────────────────────────────────────

def _send_and_wait(w3: Web3, tx_dict: dict) -> dict:
    account = _account(w3)
    # web3.py v7 build_transaction() auto-fills EIP-1559 fields; strip them and
    # force a legacy (type-0) transaction which Somnia POA testnet accepts.
    for eip1559_field in ("maxFeePerGas", "maxPriorityFeePerGas", "accessList"):
        tx_dict.pop(eip1559_field, None)
    tx_dict.setdefault("chainId",  CHAIN_ID)
    # Use network gas price so we always exceed the base fee
    network_gas_price = w3.eth.gas_price
    tx_dict.setdefault("gasPrice", network_gas_price)
    tx_dict["nonce"] = w3.eth.get_transaction_count(account.address)

    signed  = account.sign_transaction(tx_dict)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"[deployer] Tx: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt["status"] != 1:
        raise RuntimeError(f"[deployer] Transaction reverted: {tx_hash.hex()}")
    return receipt


def deploy_contract(
    w3: Web3,
    abi: list,
    bytecode: str,
    constructor_args: list = None,
    value_wei: int = 0,
    gas: int = 3_000_000,
) -> str:
    """Deploy a compiled contract. Returns deployed address."""
    account  = _account(w3)
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    bal = w3.from_wei(w3.eth.get_balance(account.address), "ether")
    print(f"[deployer] Deploying from {account.address} (balance: {bal:.4f} STT)")

    deploy_tx = contract.constructor(*(constructor_args or [])).build_transaction({
        "gas": gas, "value": value_wei,
    })
    receipt = _send_and_wait(w3, deploy_tx)
    address = receipt["contractAddress"]
    print(f"[deployer] Deployed at: {address}")
    return address


# ── Infrastructure auto-deploy ────────────────────────────────────────────────

def _ensure_infra(w3: Web3) -> tuple[str, str, list, list]:
    """
    Ensure ProvenanceRegistry and ComplianceLog are deployed.
    Auto-deploys them if addresses are missing from .env and writes addresses back.
    Returns (registry_addr, complog_addr, registry_abi, complog_abi)
    """
    registry_addr = os.getenv("PROVENANCE_REGISTRY_ADDRESS", "").strip()
    complog_addr  = os.getenv("COMPLIANCE_LOG_ADDRESS", "").strip()

    registry_abi, registry_bytecode = _compile_contract_file("ProvenanceRegistry.sol")
    complog_abi,  complog_bytecode  = _compile_contract_file("ComplianceLog.sol")

    if not registry_addr:
        print("[deployer] Auto-deploying ProvenanceRegistry...")
        registry_addr = deploy_contract(w3, registry_abi, registry_bytecode)
        set_key(str(_ENV_PATH), "PROVENANCE_REGISTRY_ADDRESS", registry_addr)
        os.environ["PROVENANCE_REGISTRY_ADDRESS"] = registry_addr
        print(f"[deployer] ProvenanceRegistry: {registry_addr}")

    if not complog_addr:
        print("[deployer] Auto-deploying ComplianceLog...")
        complog_addr = deploy_contract(w3, complog_abi, complog_bytecode)
        set_key(str(_ENV_PATH), "COMPLIANCE_LOG_ADDRESS", complog_addr)
        os.environ["COMPLIANCE_LOG_ADDRESS"] = complog_addr
        print(f"[deployer] ComplianceLog: {complog_addr}")

    return registry_addr, complog_addr, registry_abi, complog_abi


# ── AxiomWatcher deployment ───────────────────────────────────────────────────

def deploy_axiom_watcher(w3: Web3, monitored_contract: str, gas_limit: int = 300_000) -> tuple[str, list]:
    """
    Compile AxiomWatcher from source (no Hardhat) and deploy it.
    Attempts Reactivity subscription; if it fails, deploys without it (graceful).
    Returns (watcher_address, watcher_abi).
    """
    abi, bytecode = _compile_contract_file("AxiomWatcher.sol")

    # Try with a small SOMI/STT value for Reactivity gas; fall back to 0 if it reverts
    for value_wei in [w3.to_wei("0.001", "ether"), 0]:
        try:
            address = deploy_contract(
                w3, abi, bytecode,
                constructor_args=[Web3.to_checksum_address(monitored_contract), gas_limit],
                value_wei=value_wei,
                gas=1_000_000,
            )
            print(f"[deployer] AxiomWatcher deployed: {address}")
            return address, abi
        except Exception as e:
            if value_wei > 0:
                print(f"[deployer] AxiomWatcher deploy with value failed ({e}), retrying without value...")
            else:
                raise


# ── Provenance registration ───────────────────────────────────────────────────

def register_provenance(
    w3: Web3,
    registry_addr: str,
    registry_abi: list,
    paper_hash: str,
    paper_title: str,
    deployed_contract: str,
    watcher_contract: str,
) -> str:
    """Write a provenance record to ProvenanceRegistry. Returns tx hash."""
    try:
        registry = w3.eth.contract(
            address=Web3.to_checksum_address(registry_addr),
            abi=registry_abi,
        )
        # Convert paper_hash to bytes32
        h = paper_hash[2:] if paper_hash.startswith("0x") else paper_hash
        hash_bytes = bytes.fromhex(h.zfill(64))

        tx = registry.functions.addRecord(
            hash_bytes,
            paper_title,
            Web3.to_checksum_address(deployed_contract),
            Web3.to_checksum_address(watcher_contract),
        ).build_transaction({"gas": 400_000})

        receipt = _send_and_wait(w3, tx)
        tx_hash = receipt["transactionHash"].hex()
        print(f"[deployer] Provenance registered — tx {tx_hash}")
        return tx_hash
    except Exception as e:
        print(f"[deployer] Provenance registration failed (non-fatal): {e}")
        return ""


# ── Demo transaction ──────────────────────────────────────────────────────────

def _default_arg(abi_type: str, w3: Web3, account_address: str):
    """Generate a sensible default value for an ABI parameter type."""
    t = abi_type.lower()
    if t == "address":
        return account_address
    if t.startswith("uint") or t.startswith("int"):
        return 1
    if t == "bool":
        return True
    if t.startswith("bytes") and not t.endswith("]"):
        size = int(t[5:]) if len(t) > 5 else 32
        return b"\x00" * size
    if "string" in t:
        return "axiom-demo"
    if t.endswith("]"):  # dynamic array
        return []
    return 0


def interact_contract(
    contract_address: str,
    abi: list,
    function_name: str = None,
    args: list = None,
) -> dict:
    """
    Call a state-changing function on a deployed contract for demo purposes.
    Auto-selects the first non-view function if function_name is None.
    Returns {tx_hash, function_name, args, explorer_url}.
    """
    w3      = get_web3()
    account = _account(w3)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(contract_address),
        abi=abi,
    )

    # Find a suitable function
    state_changing = [
        f for f in abi
        if f.get("type") == "function"
        and f.get("stateMutability") not in ("view", "pure")
        and f.get("name") != "stop"
    ]
    if not state_changing:
        raise ValueError("No state-changing functions found in ABI")

    # Pick requested function or first available
    if function_name:
        fn_abi = next((f for f in state_changing if f["name"] == function_name), None)
        if not fn_abi:
            raise ValueError(f"Function '{function_name}' not found")
    else:
        fn_abi = state_changing[0]
        function_name = fn_abi["name"]

    # Generate default args if not provided
    if args is None:
        args = [
            _default_arg(p["type"], w3, account.address)
            for p in fn_abi.get("inputs", [])
        ]

    print(f"[deployer] Calling {function_name}({args}) on {contract_address}")

    fn = contract.functions[function_name](*args)
    tx = fn.build_transaction({"gas": 500_000})
    receipt = _send_and_wait(w3, tx)
    tx_hash = receipt["transactionHash"].hex()

    return {
        "tx_hash":      tx_hash,
        "function_name": function_name,
        "args":         [str(a) for a in args],
        "explorer_url": f"{EXPLORER_BASE}/tx/{tx_hash}",
    }


# ── High-level orchestrator ────────────────────────────────────────────────────

def deploy_from_paper(solidity_code: str, contract_name: str, paper_title: str) -> dict:
    """
    Full pipeline: compile → deploy mechanism → deploy watcher → register provenance.

    Returns dict with ALL keys expected by server.py and the frontend:
      deployed_address, watcher_address, paper_hash, abi, contract_name,
      paper_title, explorer_url, watcher_url
    """
    w3 = get_web3()
    print(f"[deployer] Connected — block {w3.eth.block_number}, chain {CHAIN_ID}")

    print(f"[deployer] Compiling '{contract_name}'...")
    abi, bytecode = compile_solidity(solidity_code, contract_name)

    print(f"[deployer] Deploying '{contract_name}' to Somnia...")
    deployed_address = deploy_contract(w3, abi, bytecode)

    paper_hash = "0x" + hashlib.sha256(paper_title.encode()).hexdigest()

    print("[deployer] Deploying AxiomWatcher (Reactivity monitor)...")
    try:
        watcher_address, watcher_abi = deploy_axiom_watcher(w3, deployed_address)
    except Exception as e:
        print(f"[deployer] AxiomWatcher deployment failed (non-fatal): {e}")
        watcher_address = ""
        watcher_abi     = []

    print("[deployer] Setting up infrastructure contracts...")
    try:
        registry_addr, complog_addr, registry_abi, complog_abi = _ensure_infra(w3)
        register_provenance(
            w3, registry_addr, registry_abi,
            paper_hash, paper_title, deployed_address,
            watcher_address or deployed_address,
        )
    except Exception as e:
        print(f"[deployer] Infrastructure setup failed (non-fatal): {e}")

    return {
        "deployed_address": deployed_address,
        "watcher_address":  watcher_address,
        "paper_hash":       paper_hash,
        "abi":              abi,
        "contract_name":    contract_name,
        "paper_title":      paper_title,
        "explorer_url":     f"{EXPLORER_BASE}/address/{deployed_address}",
        "watcher_url":      f"{EXPLORER_BASE}/address/{watcher_address}" if watcher_address else "",
    }
