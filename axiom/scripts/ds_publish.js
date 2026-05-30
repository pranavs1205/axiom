/**
 * ds_publish.js
 * -------------
 * Publishes provenance and compliance records to Somnia Data Streams.
 * Called from the Python backend via subprocess.
 *
 * Usage:
 *   node ds_publish.js setup
 *   node ds_publish.js provenance  '{"paperHash":"0x...","paperTitle":"...","deployedContract":"0x...","explorerUrl":"..."}'
 *   node ds_publish.js compliance  '{"contractAddress":"0x...","txHash":"0x...","eventName":"Swap","verdict":"PASS","explanation":"...","citedSection":"..."}'
 */

require("dotenv").config({ path: require("path").join(__dirname, "../.env") });

const { SDK }                 = require("@somnia-chain/streams");
const { createPublicClient,
        createWalletClient,
        http }                = require("viem");
const { privateKeyToAccount } = require("viem/accounts");

// ── Chain definitions ─────────────────────────────────────────────────────────
const CHAIN_ID  = parseInt(process.env.SOMNIA_CHAIN_ID || "50312");
const RPC_URL   = process.env.SOMNIA_RPC_URL || "https://api.infra.testnet.somnia.network";
const PRIV_KEY  = process.env.SOMNIA_PRIVATE_KEY;

const somniaTestnet = {
  id: 50312,
  name: "Somnia Testnet",
  network: "somnia-testnet",
  nativeCurrency: { name: "Somnia Test Token", symbol: "STT", decimals: 18 },
  rpcUrls: { default: { http: [RPC_URL] } },
  blockExplorers: { default: { name: "Explorer", url: "https://testnet.somnia.network" } },
};

const somniaMainnet = {
  id: 5031,
  name: "Somnia",
  network: "somnia",
  nativeCurrency: { name: "SOMI", symbol: "SOMI", decimals: 18 },
  rpcUrls: { default: { http: ["https://api.infra.mainnet.somnia.network"] } },
  blockExplorers: { default: { name: "Explorer", url: "https://explorer.somnia.network" } },
};

const chain = CHAIN_ID === 5031 ? somniaMainnet : somniaTestnet;

// ── Schema definitions ────────────────────────────────────────────────────────
const SCHEMAS = {
  provenance: {
    name:   "axiom_provenance_v1",
    schema: "bytes32 paperHash, string paperTitle, address deployedContract, address deployer, uint256 deployedAt, string explorerUrl",
  },
  compliance: {
    name:   "axiom_compliance_v1",
    schema: "address contractAddress, bytes32 txHash, string eventName, string verdict, string explanation, string citedSection, uint256 checkedAt",
  },
};

// ── SDK factory ───────────────────────────────────────────────────────────────
function buildSDK() {
  if (!PRIV_KEY) throw new Error("SOMNIA_PRIVATE_KEY not set in .env");
  const account      = privateKeyToAccount(PRIV_KEY);
  const publicClient = createPublicClient({ chain, transport: http(RPC_URL) });
  const walletClient = createWalletClient({ chain, account, transport: http(RPC_URL) });
  return new SDK({ public: publicClient, wallet: walletClient });
}

// ── Commands ──────────────────────────────────────────────────────────────────
async function setup(sdk) {
  process.stderr.write("[ds_publish] Registering Data Streams schemas...\n");
  await sdk.registerDataSchemas([{ name: SCHEMAS.provenance.name, schema: SCHEMAS.provenance.schema }]);
  await sdk.registerDataSchemas([{ name: SCHEMAS.compliance.name, schema: SCHEMAS.compliance.schema }]);
  process.stderr.write("[ds_publish] Schemas registered.\n");
  console.log(JSON.stringify({ success: true, action: "setup" }));
}

async function publishProvenance(sdk, data) {
  const schemaId = await sdk.computeSchemaId(SCHEMAS.provenance);
  const account  = buildSDK(); // just to get address
  await sdk.setAndEmitEvents(
    [{
      schemaId,
      key: data.deployedContract,
      value: {
        paperHash:        data.paperHash || "0x" + "0".repeat(64),
        paperTitle:       data.paperTitle || "",
        deployedContract: data.deployedContract,
        deployer:         data.deployer || "0x0000000000000000000000000000000000000000",
        deployedAt:       BigInt(Math.floor(Date.now() / 1000)),
        explorerUrl:      data.explorerUrl || "",
      },
    }],
    []
  );
  console.log(JSON.stringify({ success: true, type: "provenance", contract: data.deployedContract }));
}

async function publishCompliance(sdk, data) {
  const schemaId = await sdk.computeSchemaId(SCHEMAS.compliance);
  const key      = `${data.contractAddress}_${data.txHash || Date.now()}`;
  await sdk.setAndEmitEvents(
    [{
      schemaId,
      key,
      value: {
        contractAddress: data.contractAddress,
        txHash:          data.txHash || "0x" + "0".repeat(64),
        eventName:       data.eventName || "",
        verdict:         data.verdict || "UNKNOWN",
        explanation:     (data.explanation || "").slice(0, 500),
        citedSection:    (data.citedSection || "").slice(0, 300),
        checkedAt:       BigInt(Math.floor(Date.now() / 1000)),
      },
    }],
    []
  );
  console.log(JSON.stringify({ success: true, type: "compliance", verdict: data.verdict }));
}

// ── Entry point ───────────────────────────────────────────────────────────────
async function main() {
  const [,, schemaType, rawJson] = process.argv;
  if (!schemaType) {
    process.stderr.write("Usage: node ds_publish.js <setup|provenance|compliance> [json]\n");
    process.exit(1);
  }

  const sdk  = buildSDK();
  const data = rawJson ? JSON.parse(rawJson) : {};

  if      (schemaType === "setup")      await setup(sdk);
  else if (schemaType === "provenance") await publishProvenance(sdk, data);
  else if (schemaType === "compliance") await publishCompliance(sdk, data);
  else {
    process.stderr.write(`Unknown type: ${schemaType}\n`);
    process.exit(1);
  }
}

main().catch(err => {
  process.stderr.write(`[ds_publish] Error: ${err.message}\n`);
  process.exit(1);
});
