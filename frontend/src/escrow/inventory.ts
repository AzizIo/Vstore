import { fetchMyInventory, type InventoryAsset } from "../api/assets";
import { fetchMyWallets, type WalletRecord } from "../wallet/api";

export interface EscrowOwnedNft {
  asset: InventoryAsset;
  wallet: WalletRecord;
}

export interface EscrowTestnetInventory {
  wallets: WalletRecord[];
  nfts: EscrowOwnedNft[];
}

const PAGE_SIZE = 24;
const MAX_PAGES_PER_WALLET = 40;

/**
 * Reuses the existing server-verified wallet and NFT inventory endpoints.
 * A connected TonConnect account is deliberately not used as an ownership signal.
 */
export async function fetchEscrowTestnetInventory(
  accessToken: string,
  signal?: AbortSignal,
): Promise<EscrowTestnetInventory> {
  const records = await fetchMyWallets(accessToken, signal);
  const wallets = records
    .filter((wallet) => wallet.is_verified && wallet.network === "testnet")
    .sort((left, right) => Number(right.is_primary) - Number(left.is_primary));

  const nfts: EscrowOwnedNft[] = [];
  const seenItems = new Set<string>();

  for (const wallet of wallets) {
    let offset = 0;
    let pageCount = 0;
    let hasMore = true;

    while (hasMore && pageCount < MAX_PAGES_PER_WALLET) {
      if (signal?.aborted) throw new DOMException("The request was aborted.", "AbortError");
      const page = await fetchMyInventory(
        accessToken,
        { walletId: wallet.id, limit: PAGE_SIZE, offset },
        signal,
      );

      if (page.wallet_id !== wallet.id) {
        throw new Error("Инвентарь вернул данные другого testnet-кошелька.");
      }

      for (const asset of page.items) {
        const key = asset.item_address.trim().toLowerCase();
        if (
          asset.asset_type !== "ton_nft" ||
          asset.verification_status !== "verified" ||
          !asset.eligible_for_listing ||
          !key ||
          seenItems.has(key)
        ) continue;

        seenItems.add(key);
        nfts.push({ asset, wallet });
      }

      if (!page.has_more) {
        hasMore = false;
      } else if (page.next_offset <= offset) {
        throw new Error("Инвентарь вернул некорректный курсор. Повторите загрузку.");
      } else {
        offset = page.next_offset;
        pageCount += 1;
      }
    }

    if (hasMore) {
      throw new Error("Инвентарь слишком велик для безопасной загрузки за один запрос. Уточните кошелёк и повторите.");
    }
  }

  return { wallets, nfts };
}
