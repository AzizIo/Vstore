# DealEscrow artifact provenance and verification

This directory pins the ABI and compiler output for the current testnet-only DealEscrow source, including the persisted outbound-action storage layout and the `RetryFailedOutboundAction` opcode. Any change to contract code or storage changes the StateInit hash and the per-deal raw address; never reuse an address created from a previous code/storage version.

## Frozen provenance

| Field | Value |
|---|---|
| Source commit | `61755265e85f5f136d22f2414b350d65b55c9549` |
| Toolchain | Acton `1.2.1`, Tolk `1.5.0` |
| Strict green contract workflow | [#43732705509](https://github.com/AzizIo/Vstore/actions/runs/43732705509) |
| Artifact ID | `14168644387` |
| Artifact archive SHA-256 | `d39f01b327ba575c8d5558e1ef6eb3417fde97458de45b8727fff0f5c7157f7d` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| Build descriptor SHA-256 | `f78fd9d9a22798f687ebd494c55d8301ceeb6146bb94123fea3a4b6d3f2f389d` |
| Compiled code hash | `A196078E27BF11C8602B40DF96B5AAA3CD29D16639E099185430358324023386` |
| BOC base64 SHA-256 | `be49a828d93309f349bb977d552c2e9c9b67e87fb0df1b4bd6b3694d241b92e2` |
| Decoded BOC SHA-256 | `98dacf0dbaac5017fa9e6a4499b27a4bc430ebdf1460394f32a778bd8ee8a22b` |
| Deterministic StateInit hash | `024ec492b97607ed98a2c3f93a36533053d5a8cb4bb4c31c951c820e8aefdaf9` |
| Deterministic raw address | `0:024ec492b97607ed98a2c3f93a36533053d5a8cb4bb4c31c951c820e8aefdaf9` |
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
