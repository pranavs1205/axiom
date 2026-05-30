require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();

const PRIVATE_KEY = process.env.SOMNIA_PRIVATE_KEY || "0x" + "0".repeat(64);
const RPC_URL     = process.env.SOMNIA_RPC_URL     || "https://api.infra.testnet.somnia.network";
const CHAIN_ID    = parseInt(process.env.SOMNIA_CHAIN_ID || "50312");

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.20",
    settings: {
      optimizer: { enabled: true, runs: 200 },
    },
  },
  networks: {
    somnia: {
      url:      RPC_URL,
      chainId:  CHAIN_ID,
      accounts: [PRIVATE_KEY],
    },
  },
  paths: {
    artifacts: "./artifacts",
    sources:   "./contracts",
  },
};
