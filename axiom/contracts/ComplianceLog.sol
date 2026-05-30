// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title ComplianceLog
/// @notice Append-only on-chain log of AI compliance verdicts.
///         Only the contract owner (Axiom backend wallet) can write entries.
contract ComplianceLog {

    enum Verdict { UNKNOWN, PASS, ANOMALY, VIOLATION }

    struct Entry {
        address contractAddress;
        bytes32 txHash;
        string  eventName;
        Verdict verdict;
        string  explanation;
        string  citedSection;
        uint256 checkedAt;
    }

    address public owner;

    Entry[]                         public entries;
    mapping(address => uint256[])   public contractEntries;

    event ComplianceRecorded(
        uint256 indexed entryId,
        address indexed contractAddress,
        Verdict indexed verdict,
        bytes32 txHash
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "ComplianceLog: not owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    /// @notice Record a compliance verdict. Restricted to owner.
    function addEntry(
        address contractAddress,
        bytes32 txHash,
        string calldata eventName,
        uint8   verdictInt,
        string calldata explanation,
        string calldata citedSection
    ) external onlyOwner returns (uint256 entryId) {
        require(verdictInt <= 3, "ComplianceLog: invalid verdict");

        entryId = entries.length;
        entries.push(Entry({
            contractAddress: contractAddress,
            txHash:          txHash,
            eventName:       eventName,
            verdict:         Verdict(verdictInt),
            explanation:     explanation,
            citedSection:    citedSection,
            checkedAt:       block.timestamp
        }));

        contractEntries[contractAddress].push(entryId);
        emit ComplianceRecorded(entryId, contractAddress, Verdict(verdictInt), txHash);
    }

    function getEntry(uint256 entryId) external view returns (Entry memory) {
        require(entryId < entries.length, "ComplianceLog: out of range");
        return entries[entryId];
    }

    function getContractEntries(address contractAddress) external view returns (uint256[] memory) {
        return contractEntries[contractAddress];
    }

    function totalEntries() external view returns (uint256) {
        return entries.length;
    }
}
