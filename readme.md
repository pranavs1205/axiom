Axiom

Axiom is a multi-agent system that turns any research paper into a live, autonomously-monitored smart contract on Somnia — in minutes, not months.

The system runs three cooperating AI agents. The PaperReader Agent ingests a PDF, extracts the methodology using semantic section detection, and builds a vector store over the paper's content. The Deploy Agent retrieves the most relevant methodology chunks via RAG, uses Groq's Llama model to synthesize deployable Solidity code grounded exclusively in the paper — with multi-pass self-correction to fix compilation errors — then compiles and deploys the contract to Somnia. The Compliance Agent then takes over permanently: it monitors every event the deployed contract emits and judges whether the on-chain behavior matches what the paper specified, producing structured verdicts (PASS / ANOMALY / VIOLATION) with exact paper section citations.

What makes this specifically a Somnia agent story is how the Compliance Agent is triggered. Rather than polling or running on a trusted server, Axiom registers a Reactivity subscription on the deployed contract — Somnia's native precompile at address 0x100. When the contract emits an event, Somnia's validators inject a synthetic transaction calling the AxiomWatcher contract in the same block. This is the on-chain agent pattern: autonomous, trustless, in-block response without any off-chain keeper. At 100ms blocks, the compliance verdict is ready before a human could even notice the original transaction.

Every verdict the Compliance Agent produces is published to Somnia Data Streams as a typed, subscribable schema. This creates a verifiable, permanent audit trail — any dApp, investor, or regulator can subscribe to a contract's compliance feed without trusting Axiom's word. The provenance chain (paper hash → deployed contract → compliance history) is fully on-chain and open.

Somnia's 1M TPS and sub-100ms finality aren't just performance features here — they're what make real-time agent-driven compliance possible at all. On any other chain, the Compliance Agent would be batched, delayed, or require centralized infrastructure. On Somnia, it's trustless and instant.
