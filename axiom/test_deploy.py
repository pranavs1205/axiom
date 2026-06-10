"""
test_deploy.py
--------------
Standalone deploy smoke-test. Skips PDF / RAG / LLM entirely.

Tests:
  1. Compile + deploy a minimal known-good contract (no constructor args, no require)
  2. Print deployed address and explorer link
  3. Optionally test _fix_constructor() on a contract with parameterised constructor

Run from axiom/ directory:
    python test_deploy.py
"""

import sys
import os
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=True)

from core.deployer import compile_solidity, deploy_contract, get_web3, EXPLORER_BASE
from core.solidity_codegen import _fix_constructor, _fix_structure

# ── Minimal known-good contract ────────────────────────────────────────────────
SIMPLE_CONTRACT = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract AxiomSmokeTest {

    event Pinged(address indexed sender, uint256 count);

    address public owner;
    uint256 public pingCount;

    constructor() {
        owner = msg.sender;
        pingCount = 0;
    }

    function ping() external {
        pingCount += 1;
        emit Pinged(msg.sender, pingCount);
    }

    function getCount() external view returns (uint256) {
        return pingCount;
    }
}
"""

# ── Contract with parameterised constructor (tests _fix_constructor) ───────────
PARAM_CONSTRUCTOR_CONTRACT = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract ParamCtorTest {

    event Stored(address indexed who, uint256 value);

    address public owner;
    uint256 public threshold;
    uint256 public maxScore;

    constructor(uint256 _threshold, uint256 _maxScore) {
        require(_threshold > 0 && _threshold < _maxScore, "bad params");
        owner = msg.sender;
        threshold = _threshold;
        maxScore = _maxScore;
    }

    function store(uint256 val) external {
        require(val >= threshold, "below threshold");
        emit Stored(msg.sender, val);
    }
}
"""


def test_fix_constructor():
    print("\n== Test: _fix_constructor() on parameterised constructor ==")
    fixed = _fix_structure(PARAM_CONSTRUCTOR_CONTRACT)
    if "constructor()" in fixed and "_threshold" not in fixed and "require" not in fixed.split("constructor()")[1].split("}")[0]:
        print("[PASS] constructor stripped and body replaced")
    else:
        # Show what it produced for inspection
        print("[INFO] Fixed output:")
        print(fixed)
    return fixed


def test_deploy_simple():
    print("\n== Test: deploy minimal AxiomSmokeTest ==")
    w3 = get_web3()
    print(f"[test] Connected - block {w3.eth.block_number}")

    print("[test] Compiling AxiomSmokeTest...")
    abi, bytecode = compile_solidity(SIMPLE_CONTRACT, "AxiomSmokeTest")
    print(f"[test] Compiled - {len(bytecode) // 2} bytes")

    print("[test] Deploying...")
    address = deploy_contract(w3, abi, bytecode)
    print(f"[test] SUCCESS - deployed at: {address}")
    print(f"[test] Explorer: {EXPLORER_BASE}/address/{address}")
    return address


def test_deploy_fixed_param_ctor():
    print("\n== Test: deploy after _fix_constructor() ==")
    fixed_code = _fix_structure(PARAM_CONSTRUCTOR_CONTRACT)

    w3 = get_web3()
    print("[test] Compiling fixed ParamCtorTest...")
    abi, bytecode = compile_solidity(fixed_code, "ParamCtorTest")
    print(f"[test] Compiled - {len(bytecode) // 2} bytes")

    print("[test] Deploying fixed contract (no constructor args needed)...")
    address = deploy_contract(w3, abi, bytecode)
    print(f"[test] SUCCESS - deployed at: {address}")
    print(f"[test] Explorer: {EXPLORER_BASE}/address/{address}")
    return address


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test",
        choices=["simple", "fixctor", "all"],
        default="simple",
        help="simple = deploy known-good contract | fixctor = deploy after _fix_constructor | all = both",
    )
    args = parser.parse_args()

    # Always run the local (free) fix test
    test_fix_constructor()

    if args.test in ("simple", "all"):
        test_deploy_simple()

    if args.test in ("fixctor", "all"):
        test_deploy_fixed_param_ctor()
