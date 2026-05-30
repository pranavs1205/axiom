// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title ProvenanceRegistry
/// @notice On-chain lineage registry: research paper → deployed contract → watcher.
contract ProvenanceRegistry {

    struct Record {
        bytes32 paperHash;
        string  paperTitle;
        address deployedContract;
        address watcherContract;
        address deployer;
        uint256 deployedAt;
    }

    Record[]                        public records;
    mapping(address => uint256[])   public deployerRecords;
    mapping(address => uint256)     private _contractIndex; // 1-based; 0 = not registered

    event RecordAdded(
        uint256 indexed recordId,
        bytes32 indexed paperHash,
        address indexed deployedContract,
        address deployer
    );

    function addRecord(
        bytes32 paperHash,
        string calldata paperTitle,
        address deployedContract,
        address watcherContract
    ) external returns (uint256 recordId) {
        require(deployedContract != address(0), "ProvenanceRegistry: zero address");

        recordId = records.length;
        records.push(Record({
            paperHash:        paperHash,
            paperTitle:       paperTitle,
            deployedContract: deployedContract,
            watcherContract:  watcherContract,
            deployer:         msg.sender,
            deployedAt:       block.timestamp
        }));

        deployerRecords[msg.sender].push(recordId);
        _contractIndex[deployedContract] = recordId + 1; // 1-based so 0 = unset

        emit RecordAdded(recordId, paperHash, deployedContract, msg.sender);
    }

    /// @notice Revert if contract was never registered.
    function getByContract(address contractAddr) external view returns (Record memory) {
        uint256 idx = _contractIndex[contractAddr];
        require(idx != 0, "ProvenanceRegistry: not registered");
        return records[idx - 1];
    }

    function getRecord(uint256 recordId) external view returns (Record memory) {
        require(recordId < records.length, "ProvenanceRegistry: out of range");
        return records[recordId];
    }

    function getDeployerRecords(address deployer) external view returns (uint256[] memory) {
        return deployerRecords[deployer];
    }

    function totalRecords() external view returns (uint256) {
        return records.length;
    }
}
