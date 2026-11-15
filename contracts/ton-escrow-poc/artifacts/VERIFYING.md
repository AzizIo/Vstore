# DealEscrow artifact provenance and verification

This directory pins the ABI and compiler output for the current testnet-only DealEscrow source, including the persisted outbound-action storage layout and the `RetryFailedOutboundAction` opcode. Any change to contract code or storage changes the StateInit hash and the per-deal raw address; never reuse an address created from a previous code/storage version.

## Frozen provenance

| Field | Value |
|---|---|
| Source commit | `42b94ea121d7a04e71a7dc9f4268be0744c8e778` |
| Toolchain | Acton `1.2.1`, Tolk `1.5.0` |
| Strict green contract workflow | [#43738313655](https://github.com/AzizIo/Vstore/actions/runs/43732705509) |
| Artifact ID | `14169431583` |
| Artifact archive SHA-256 | `1a08426a6d6fbdbe5608358962e058d070def036408a7fd420c8d25c9d6dda4a` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| Build descriptor SHA-256 | `0c3c7dec0bbf5bb231a007e5d99e28a5c5b7285d9cbdd3324e1172cd756b2eea` |
| Compiled code hash | `61348A9F67A31753622AB3E9E204AF67FBC1ED8736B05510DD9DF93E0F49366B` |
| BOC base64 SHA-256 | `ab0fdad1ca51d84b5df77f64a34eedac0e41f0c328aeffd5984e0dde0b381a40` |
| Decoded BOC SHA-256 | `33f6f2e25bf541720eaab59e39aea98a53e2a622a1a569b91d318932dc092153` |
| Deterministic StateInit hash | `e97848a3d9e691bd0b78c7a6085d836821e459b347b15ecd0d10c645427768c6` |
| Deterministic raw address | `0:e97848a3d9e691bd0b78c7a6085d836821e459b347b15ecd0d10c645427768c6` |
| Initial data cell hash | `faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b` |

The source-controlled files are `frozen/DealEscrow.abi.json` and `frozen/manifest.json`. The compiled BOC itself is not manually checked in as a text file; CI rebuilds it and verifies the exact compiler code hash and BOC digests.

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

The green Acton emulator suite demonstrates behavior only in the pinned toolchain/test fixtures. It is not a live chain finality proof, independent TON/Tolk security audit, or manual TON testnet/Tonkeeper acceptance. The collection/item membership assertion must be checked by the future trusted provider before creating immutable deal terms. Signing and deployment remain disabled.
