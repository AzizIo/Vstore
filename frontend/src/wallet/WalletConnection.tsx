import { lazy, Suspense } from "react";

import type { WalletRecord } from "./api";

const ConfiguredWalletConnection = lazy(() => import("./TonConnectWallet"));

export function WalletConnection({
  accessToken,
  onSelectedWalletChange,
}: {
  accessToken: string | null;
  onSelectedWalletChange: (wallet: WalletRecord | null) => void;
}) {
  const manifestUrl = import.meta.env.VITE_TONCONNECT_MANIFEST_URL?.trim();
  if (!accessToken) {
    return (
      <p id="wallet-connect" className="wallet-config-message" role="status">
        Open this mini app in Telegram to link a wallet.
      </p>
    );
  }
  if (!manifestUrl) {
    return (
      <p id="wallet-connect" className="wallet-config-message" role="status">
        Wallet connection is not configured.
      </p>
    );
  }

  return (
    <Suspense fallback={<p id="wallet-connect" className="wallet-config-message" role="status">Loading wallet options...</p>}>
      <ConfiguredWalletConnection
        manifestUrl={manifestUrl}
        accessToken={accessToken}
        onSelectedWalletChange={onSelectedWalletChange}
      />
    </Suspense>
  );
}
