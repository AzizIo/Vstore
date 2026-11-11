import { lazy, Suspense } from "react";

const ConfiguredWalletConnection = lazy(() => import("./TonConnectWallet"));

export function WalletConnection() {
  const manifestUrl = import.meta.env.VITE_TONCONNECT_MANIFEST_URL?.trim();
  if (!manifestUrl) {
    return (
      <p id="wallet-connect" className="wallet-config-message" role="status">
        Wallet connection is not configured.
      </p>
    );
  }

  return (
    <Suspense fallback={<p id="wallet-connect" className="wallet-config-message" role="status">Loading wallet options...</p>}>
      <ConfiguredWalletConnection manifestUrl={manifestUrl} />
    </Suspense>
  );
}
