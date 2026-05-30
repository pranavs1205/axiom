"""
event_monitor.py
----------------
Background service that polls Somnia for events from monitored contracts,
runs AI compliance checks, and writes verdicts on-chain.

Polling interval is intentionally short (3s) since Somnia has 100ms blocks —
we want near-real-time compliance feedback for the demo.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Callable

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

SOMNIA_RPC   = os.getenv("SOMNIA_RPC_URL",  "https://api.infra.testnet.somnia.network")
CHAIN_ID     = int(os.getenv("SOMNIA_CHAIN_ID", "50312"))
PRIVATE_KEY  = os.getenv("SOMNIA_PRIVATE_KEY", "")
COMPLOG_ADDR = os.getenv("COMPLIANCE_LOG_ADDRESS", "")

POLL_INTERVAL = 3   # seconds between polls


def _make_web3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(SOMNIA_RPC))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def fetch_events(
    w3: Web3,
    contract_address: str,
    abi: list,
    from_block: int,
    to_block: int,
) -> list[dict]:
    """
    Fetch and decode all events from a contract in a block range.

    Returns list of dicts: {event, args, block, txHash, address}
    """
    contract    = w3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=abi)
    event_abis  = [item for item in abi if item.get("type") == "event"]
    results     = []

    for ev_abi in event_abis:
        name = ev_abi["name"]
        try:
            logs = contract.events[name].get_logs(fromBlock=from_block, toBlock=to_block)
            for log in logs:
                results.append({
                    "event":   name,
                    "args":    dict(log["args"]),
                    "block":   log["blockNumber"],
                    "txHash":  log["transactionHash"].hex(),
                    "address": log["address"],
                })
        except Exception as e:
            print(f"[event_monitor] {name} log fetch error: {e}")

    return results


class ContractMonitor:
    """
    Async background monitor.  Call register() for each deployed contract,
    then await run_forever() in a background task.
    """

    def __init__(self):
        self.w3          = _make_web3()
        self._monitored  : dict[str, dict] = {}   # addr → config
        self._results    : list[dict]       = []
        self._callbacks  : list[Callable]   = []
        self._running    = False
        self._complog_abi: list | None      = None

    # ── Public API ────────────────────────────────────────────────────────────

    def register(self, contract_address: str, abi: list, store, api_key: str):
        """Register a contract address for compliance monitoring."""
        addr = contract_address.lower()
        self._monitored[addr] = {
            "abi":        abi,
            "last_block": self.w3.eth.block_number,
            "store":      store,
            "api_key":    api_key,
        }
        print(f"[event_monitor] Registered {addr} from block {self._monitored[addr]['last_block']}")

    def unregister(self, contract_address: str):
        self._monitored.pop(contract_address.lower(), None)

    def on_compliance(self, callback: Callable):
        """Register a callback invoked with each new compliance record."""
        self._callbacks.append(callback)

    def get_results(self, contract_address: str = None) -> list[dict]:
        if contract_address:
            return [r for r in self._results if r["contract_address"] == contract_address.lower()]
        return list(self._results)

    # ── Polling ───────────────────────────────────────────────────────────────

    def poll_once(self) -> list[dict]:
        """Poll all monitored contracts. Returns new compliance records."""
        from core.compliance_agent import check_compliance, write_compliance_to_chain

        new_records = []

        for addr, cfg in list(self._monitored.items()):
            current_block = self.w3.eth.block_number
            from_block    = cfg["last_block"] + 1

            if from_block > current_block:
                continue

            events = fetch_events(self.w3, addr, cfg["abi"], from_block, current_block)

            for ev in events:
                print(f"[event_monitor] {ev['event']}() on {addr} @ block {ev['block']}")

                verdict = check_compliance(
                    event_name       = ev["event"],
                    event_args       = ev["args"],
                    store            = cfg["store"],
                    api_key          = cfg["api_key"],
                    contract_address = addr,
                    tx_hash          = ev["txHash"],
                )

                record = {
                    **verdict,
                    "event_name":       ev["event"],
                    "tx_hash":          ev["txHash"],
                    "block":            ev["block"],
                    "contract_address": addr,
                }

                # Write verdict to ComplianceLog contract
                if COMPLOG_ADDR and self._get_complog_abi():
                    write_compliance_to_chain(
                        self.w3, record,
                        COMPLOG_ADDR, self._get_complog_abi(),
                        PRIVATE_KEY, CHAIN_ID,
                    )

                self._results.append(record)
                new_records.append(record)

                for cb in self._callbacks:
                    try:
                        cb(record)
                    except Exception:
                        pass

                print(f"[event_monitor] Verdict: {verdict['verdict']} — {verdict['explanation']}")

            cfg["last_block"] = current_block

        return new_records

    async def run_forever(self):
        """Async background loop. Run as asyncio.create_task()."""
        self._running = True
        print(f"[event_monitor] Monitor loop started (every {POLL_INTERVAL}s)")
        while self._running:
            try:
                self.poll_once()
            except Exception as e:
                print(f"[event_monitor] Poll error: {e}")
            await asyncio.sleep(POLL_INTERVAL)

    def stop(self):
        self._running = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_complog_abi(self) -> list | None:
        if self._complog_abi is not None:
            return self._complog_abi
        try:
            import solcx
            contracts_dir = Path(__file__).parent.parent / "contracts"
            source = (contracts_dir / "ComplianceLog.sol").read_text()
            if "0.8.20" not in [str(v) for v in solcx.get_installed_solc_versions()]:
                solcx.install_solc("0.8.20")
            solcx.set_solc_version("0.8.20")
            compiled = solcx.compile_source(source, output_values=["abi"])
            key = next(k for k in compiled if "ComplianceLog" in k)
            self._complog_abi = compiled[key]["abi"]
        except Exception as e:
            print(f"[event_monitor] ComplianceLog ABI compile failed: {e}")
        return self._complog_abi
