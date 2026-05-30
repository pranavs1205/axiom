// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// ── Somnia Reactivity interfaces (inlined — no npm required) ──────────────────

interface ISomniaReactivity {
    struct EventFilter {
        address[] contracts;
        bytes32[] topics;
    }
    struct SubscriptionOptions {
        uint64 gasLimit;
        uint64 maxFeePerGas;
        uint64 priorityFeePerGas;
        bool   persistent;
    }
    function subscribe(
        address handler,
        EventFilter calldata filter,
        SubscriptionOptions calldata options
    ) external payable returns (uint64 subscriptionId);
    function unsubscribe(uint64 subscriptionId) external;
}

abstract contract SomniaReactivityHandler {
    address constant REACTIVITY_PRECOMPILE = 0x0000000000000000000000000000000000000100;
    uint64 public subscriptionId;

    /// @dev Called by Somnia validators in the same block when a subscribed event fires.
    function handleEvent(
        uint64 subId,
        address emitter,
        bytes32[] calldata eventTopics,
        bytes calldata data
    ) external {
        require(msg.sender == REACTIVITY_PRECOMPILE, "AxiomWatcher: caller not Reactivity");
        require(subId == subscriptionId, "AxiomWatcher: unknown subscription");
        _onEvent(emitter, eventTopics, data);
    }

    function _onEvent(
        address emitter,
        bytes32[] calldata eventTopics,
        bytes calldata data
    ) internal virtual;
}

// ── AxiomWatcher ──────────────────────────────────────────────────────────────

/// @title AxiomWatcher
/// @notice Somnia Reactivity handler. Subscribes to ALL events from a monitored
///         contract. When any event fires, re-emits ComplianceCheckRequested so
///         the off-chain ComplianceAgent can run the RAG compliance check.
contract AxiomWatcher is SomniaReactivityHandler {

    event ComplianceCheckRequested(
        address indexed contractAddress,
        address indexed emitter,
        bytes32 indexed topic0,
        bytes   eventData,
        uint256 blockNumber
    );
    event WatcherRegistered(address indexed monitoredContract, uint64 subscriptionId);
    event WatcherStopped(address indexed owner, uint64 subscriptionId);

    address public immutable monitoredContract;
    address public owner;
    bool    public active;

    constructor(address _monitoredContract, uint64 gasLimit) payable {
        require(_monitoredContract != address(0), "AxiomWatcher: zero address");
        owner             = msg.sender;
        monitoredContract = _monitoredContract;
        active            = true;

        // Subscribe to ALL events from the monitored contract (empty topics = wildcard)
        address[] memory contracts = new address[](1);
        contracts[0] = _monitoredContract;

        ISomniaReactivity.EventFilter memory filter = ISomniaReactivity.EventFilter({
            contracts: contracts,
            topics:    new bytes32[](0)
        });
        ISomniaReactivity.SubscriptionOptions memory options = ISomniaReactivity.SubscriptionOptions({
            gasLimit:          gasLimit,
            maxFeePerGas:      0,
            priorityFeePerGas: 1,
            persistent:        true
        });

        subscriptionId = ISomniaReactivity(REACTIVITY_PRECOMPILE).subscribe{value: msg.value}(
            address(this), filter, options
        );
        emit WatcherRegistered(_monitoredContract, subscriptionId);
    }

    function _onEvent(
        address emitter,
        bytes32[] calldata eventTopics,
        bytes calldata data
    ) internal override {
        if (!active) return;
        bytes32 topic0 = eventTopics.length > 0 ? eventTopics[0] : bytes32(0);
        emit ComplianceCheckRequested(monitoredContract, emitter, topic0, data, block.number);
    }

    function stop() external {
        require(msg.sender == owner, "AxiomWatcher: not owner");
        active = false;
        uint64 sid = subscriptionId;
        if (sid != 0) {
            subscriptionId = 0;
            ISomniaReactivity(REACTIVITY_PRECOMPILE).unsubscribe(sid);
        }
        emit WatcherStopped(owner, sid);
    }

    receive() external payable {}
}
