/**
 * deploy_infra.js
 * ---------------
 * One-time Hardhat deploy script for the infrastructure contracts:
 *   - ProvenanceRegistry  (paper→contract registry)
 *   - ComplianceLog       (on-chain compliance verdicts)
 *
 * Run: npx hardhat run scripts/deploy_infra.js --network somnia
 *
 * Copy the output addresses into your .env file:
 *   PROVENANCE_REGISTRY_ADDRESS=0x...
 *   COMPLIANCE_LOG_ADDRESS=0x...
 */

const hre = require("hardhat");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log(`Deploying infrastructure contracts from: ${deployer.address}`);
  console.log(`Balance: ${hre.ethers.formatEther(await hre.ethers.provider.getBalance(deployer.address))} SOMI/STT\n`);

  // Deploy ProvenanceRegistry
  const Registry = await hre.ethers.getContractFactory("ProvenanceRegistry");
  const registry = await Registry.deploy();
  await registry.waitForDeployment();
  const registryAddr = await registry.getAddress();
  console.log(`ProvenanceRegistry deployed: ${registryAddr}`);

  // Deploy ComplianceLog
  const CompLog = await hre.ethers.getContractFactory("ComplianceLog");
  const compLog = await CompLog.deploy();
  await compLog.waitForDeployment();
  const compLogAddr = await compLog.getAddress();
  console.log(`ComplianceLog deployed:      ${compLogAddr}`);

  console.log("\n── Add these to your .env file ──────────────────────────────");
  console.log(`PROVENANCE_REGISTRY_ADDRESS=${registryAddr}`);
  console.log(`COMPLIANCE_LOG_ADDRESS=${compLogAddr}`);
  console.log("─────────────────────────────────────────────────────────────");
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
