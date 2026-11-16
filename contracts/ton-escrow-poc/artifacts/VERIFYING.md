# DealEscrow artifact provenance and verification

This directory pins the ABI and compiler output for the current testnet-only DealEscrow source, including the persisted outbound-action storage layout and the `RetryFailedOutboundAction` opcode. Any change to contract code or storage changes the StateInit hash and the per-deal raw address; never reuse an address created from a previous code/storage version.

## Frozen provenance

| Field | Value |
|---|---|
| Source commit | `9d80a65a974b54f115fc697158974bdcee2c6be8` |
| Toolchain | Acton `1.2.1`, Tolk `1.5.0` |
| Successful exact-head contract workflow | [#43824551943](https://github.com/AzizIo/Vstore/actions/runs/43824551943) |
| Artifact ID | `14205079269` |
| Artifact archive SHA-256 | `622174053559929887d34c0ae0b8f3318efe2a4b9c661bf1925bd4760cf48c9a` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| Build descriptor SHA-256 | `32c5ff1e392d77ade6c4a99b6010e41bcc2c1c9700e768fe190be45f98aeb5db` |
| Compiled code hash | `498A82F9B2DE206BE42108B6413D517CE63D4BCB1C20704D0BD89FCCC9509C46` |
| BOC base64 SHA-256 | `0e7bc7b35eee4ae7003fba0a0e5368df3428b7e32ad0f4fc5ddf0f3230d5daf3` |
| Decoded BOC SHA-256 | `86ed08596d0595c711aa2cf7659ee396ff443d7b01c65659b8e7543dd23c6173` |
| Zlib-compressed BOC SHA-256 | `8dce117db9f0ca883b0438c2f600b10c4caf18d7febd3db26a02d78c0191cbd7` |
| Deterministic StateInit hash | `4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75` |
| Deterministic raw address | `0:4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75` |
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


## Latest integration reproduction

The backend pin PR #247 also reran the contract workflow against its exact PR head `be6716f0f17e4cead2bd4d2ed7301d1baa5226b4`: [Contract CI #43832141975](https://github.com/AzizIo/Vstore/actions/runs/43832141975) passed and produced artifact `14208215967` (archive SHA-256 `ad4b324659333abd904226857b4ac7ed6d72661f85d4ef2456b3e7b753e1caf2`). Its generated code BOC base64 and decoded BOC hashes match the frozen manifest above. This is a second reproducible build check, not an independent security audit or live network acceptance.
