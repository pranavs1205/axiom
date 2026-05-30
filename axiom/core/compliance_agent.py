"""
compliance_agent.py
-------------------
Checks whether an on-chain event matches the paper specification via RAG + LLM.
Also writes verdicts to the ComplianceLog contract on-chain.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "project"))

from pipeline.retrieval import retrieve
from pipeline.vector_store import VectorStore
from llm.groq_client import call_llm_with_system

MAX_CONTEXT_CHARS = 5000

COMPLIANCE_SYSTEM = """You are a strict protocol compliance auditor for on-chain smart contracts.

Given an on-chain event emitted by a deployed smart contract and excerpts from
the original research paper that describes the protocol, determine whether the
event's parameters and behavior conform to the paper's specification.

RESPOND ONLY with valid JSON — no markdown, no text outside the JSON object:
{
  "verdict":       "PASS" | "ANOMALY" | "VIOLATION" | "UNKNOWN",
  "confidence":    0.0-1.0,
  "explanation":   "one clear sentence explaining the verdict",
  "cited_section": "exact paper section title or short direct quote supporting verdict",
  "details":       "optional: specific parameter values or edge-case notes"
}

VERDICT DEFINITIONS:
  PASS      — parameters and behavior exactly match the paper specification
  ANOMALY   — unusual but not definitively wrong (edge case, boundary condition)
  VIOLATION — clear, specific deviation from what the paper specifies
  UNKNOWN   — paper does not describe this behavior clearly enough to judge
"""


def check_compliance(
    event_name: str,
    event_args: dict,
    store: VectorStore,
    api_key: str,
    contract_address: str = "",
    tx_hash: str = "",
    top_k: int = 5,
) -> dict:
    """
    Check whether an on-chain event is compliant with the paper specification.
    Returns dict: {verdict, confidence, explanation, cited_section, details}
    """
    args_str = ", ".join(f"{k}={v}" for k, v in event_args.items())
    query    = f"{event_name} {' '.join(str(v) for v in event_args.keys())} specification behavior"

    chunks = retrieve(query, store, top_k=top_k)
    if not chunks:
        return {
            "verdict": "UNKNOWN", "confidence": 0.0,
            "explanation": "No relevant paper context found.",
            "cited_section": "", "details": "",
        }

    context_parts = []
    total = 0
    for chunk in chunks:
        entry = f"[Section: {chunk['section']} | Similarity: {chunk['score']:.3f}]\n{chunk['text']}"
        if total + len(entry) > MAX_CONTEXT_CHARS:
            break
        context_parts.append(entry)
        total += len(entry)

    context = "\n\n".join(context_parts)

    user_prompt = (
        f"ON-CHAIN EVENT:\n"
        f"  Contract : {contract_address or 'unknown'}\n"
        f"  Tx Hash  : {tx_hash or 'unknown'}\n"
        f"  Event    : {event_name}({args_str})\n\n"
        f"PAPER EXCERPTS (most relevant):\n{context}\n\n"
        "Does this event comply with the paper specification? Respond only with JSON."
    )

    raw = call_llm_with_system(COMPLIANCE_SYSTEM, user_prompt, api_key=api_key, temperature=0.0)

    try:
        clean  = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(clean)
        for key, default in [
            ("verdict", "UNKNOWN"), ("confidence", 0.0),
            ("explanation", ""), ("cited_section", ""), ("details", ""),
        ]:
            result.setdefault(key, default)
        return result
    except (json.JSONDecodeError, ValueError):
        return {
            "verdict": "UNKNOWN", "confidence": 0.0,
            "explanation": f"LLM parse failed: {raw[:150]}",
            "cited_section": "", "details": "",
        }


def write_compliance_to_chain(
    w3,
    record: dict,
    compliance_log_address: str,
    compliance_log_abi: list,
    private_key: str,
    chain_id: int,
) -> str:
    """Write a compliance verdict to ComplianceLog on-chain. Returns tx hash or ''."""
    try:
        log_contract = w3.eth.contract(
            address=w3.to_checksum_address(compliance_log_address),
            abi=compliance_log_abi,
        )
        account = w3.eth.account.from_key(private_key)

        verdict_map = {"PASS": 1, "ANOMALY": 2, "VIOLATION": 3}
        verdict_int = verdict_map.get(record.get("verdict", "UNKNOWN"), 0)

        # Use [2:] not lstrip("0x") to avoid stripping leading-zero digits from hash
        raw_hash = record.get("tx_hash", "")
        if raw_hash.startswith("0x"):
            raw_hash = raw_hash[2:]
        tx_hash_bytes = bytes.fromhex(raw_hash.zfill(64))

        tx = log_contract.functions.addEntry(
            w3.to_checksum_address(record["contract_address"]),
            tx_hash_bytes,
            record.get("event_name", ""),
            verdict_int,
            record.get("explanation", "")[:500],
            record.get("cited_section", "")[:300],
        ).build_transaction({"gas": 400_000})

        # Strip EIP-1559 fields and force legacy (type-0) for Somnia POA
        for f in ("maxFeePerGas", "maxPriorityFeePerGas", "accessList"):
            tx.pop(f, None)
        tx["chainId"]  = chain_id
        tx["gasPrice"] = w3.eth.gas_price
        tx["nonce"]    = w3.eth.get_transaction_count(account.address)

        signed  = account.sign_transaction(tx)
        sent    = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(sent, timeout=60)
        return receipt["transactionHash"].hex()

    except Exception as e:
        print(f"[compliance_agent] On-chain write failed (non-fatal): {e}")
        return ""
