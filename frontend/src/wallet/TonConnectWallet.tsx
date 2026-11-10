import { useState } from "react";
import {
  CHAIN,
  TonConnectUIProvider,
  useTonConnectUI,
  useTonWallet,
} from "@tonconnect/ui-react";

export default function TonConnectWallet({ manifestUrl }: { manifestUrl: string }) {
  return (
    <TonConnectUIProvider manifestUrl={manifestUrl}>
      <WalletControls />
    </TonConnectUIProvider>
  );
}

function WalletControls() {
  const wallet = useTonWallet();
  const [tonConnectUI] = useTonConnectUI();
  const [error, setError] = useState("");

  async function disconnectWallet() {
    setError("");
    try {
      await tonConnectUI.disconnect();
    } catch {
      setError("Could not disconnect the wallet. Please try again.");
    }
  }

  if (!wallet) {
    return (
      <div className="wallet-control">
        <button className="wallet-button" type="button" onClick={() => tonConnectUI.openModal()}>
          Connect wallet
        </button>
        {error && <span className="wallet-error" role="alert">{error}</span>}
      </div>
    );
  }

  const address = wallet.account.address;
  const shortAddress = `${address.slice(0, 6)}…${address.slice(-4)}`;
  const network = wallet.account.chain === CHAIN.MAINNET
    ? "Mainnet"
    : wallet.account.chain === CHAIN.TESTNET
      ? "Testnet"
      : "TON network";

  return (
    <div className="wallet-control">
      <span className="wallet-account" role="status">
        <span className="wallet-address">{shortAddress}</span>
        <span className="wallet-network">{network}</span>
        <span className="wallet-disclaimer">Connection does not verify NFT ownership</span>
      </span>
      <button className="wallet-button wallet-disconnect" type="button" onClick={disconnectWallet}>
        Disconnect
      </button>
      {error && <span className="wallet-error" role="alert">{error}</span>}
    </div>
  );
}