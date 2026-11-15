# DealEscrow artifact provenance and verification

This directory pins the ABI and compiler output for the current testnet-only DealEscrow source, including the persisted outbound-action storage layout and the `RetryFailedOutboundAction` opcode. Any change to contract code or storage changes the StateInit hash and the per-deal raw address; never reuse an address created from a previous code/storage version.

## Frozen provenance

| Field | Value |
|---|---|
| Source commit | `2160aa6780efff2e44e5f8ae99b2d21cb8764740` |
| Toolchain | Acton `1.2.1`, Tolk `1.5.0` |
| Successful exact-head contract workflow | [#43767931853](https://github.com/AzizIo/Vstore/actions/runs/43767931853) |
| Artifact ID | `14183122192` |
| Artifact archive SHA-256 | `b5c7d011004098ccbeaef48aeaec230231c6531a5554d17937972d7f3ec9edf0` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| Build descriptor SHA-256 | `d53460a4c957ed011897fe43435d21fbfd570080b2e9bee34e244bd361959bf0` |
| Compiled code hash | `9011F274BC3D7E32B76A17F13FCBA17AC49429BB4EECBC4AB97FA202BDAC2940` |
| BOC base64 SHA-256 | `f8da91f71e363585823060fcfb75d9fe579e449f3e74551bbba6b142a7e98149` |
| Decoded BOC SHA-256 | `f9ae570bf2808556a1be9dee8e804d95f6c9f427ecfcfd3edb06b029490c8607` |
| Zlib-compressed BOC SHA-256 | `58a888105143cf27c02e5beae8d724fca92fb7b89f00c77fbfc54ad5828cf365` |
| Deterministic StateInit hash | `674227296eff6ac5ee02c8e2eaa12857ac339d10a9ed7f4f7ea0591e7b4adfca` |
| Deterministic raw address | `0:674227296eff6ac5ee02c8e2eaa12857ac339d10a9ed7f4f7ea0591e7b4adfca` |
| Initial data cell hash | `faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b` |

The source-controlled files are `frozen/DealEscrow.abi.json` and `frozen/manifest.json`. The backend pins the compressed compiler BOC as `backend/app/escrow/abi_artifacts/DealEscrow.code.boc.zlib.b64`; CI rebuilds it and verifies the code hash and BOC digests.

## Local verification

From `contracts/ton-escrow-poc`:

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/verify_frozen_files.py
acton build
python3 scripts/verify_build_matches_manifest.py
acton wrapper --all
acton wrapper DealEscrow --ts --output wrappers-ts/DealEscrow.gen.ts
npm install --no-save --no-package-lock @ton/core@0.63.1 tsx@4.19.2
npx tsx scripts/verify_state_init_vector.ts
npx tsx scripts/verify_message_vectors.ts
acton fmt --check
acton check
acton test --coverage --no-studio-reporting
```

## Important limitations

The Acton emulator suite demonstrates behavior only in the pinned toolchain/test fixtures. The successful exact-head contract workflow rebuilt and verified the code/BOC, generated and cross-checked StateInit and message vectors, passed Tolk formatting/static checks, and completed the emulator suite including late NFT delivery/payout and late NFT return/buyer-refund after timeout. This proves the modeled testnet contract behavior in the pinned toolchain; it is not an independent audit or live network acceptance. Emulator evidence is not a live chain finality proof, independent TON/Tolk security audit, or manual TON testnet/Tonkeeper acceptance. A trusted provider must prove the exact collection membership before immutable deal terms are created. Signing and deployment remain disabled.
