# DealEscrow artifact provenance and verification

This directory pins the ABI and compiler output for the current testnet-only DealEscrow source, including the persisted outbound-action storage layout and the `RetryFailedOutboundAction` opcode. Any change to contract code or storage changes the StateInit hash and the per-deal raw address; never reuse an address created from a previous code/storage version.

## Frozen provenance

| Field | Value |
|---|---|
| Source commit | `01963603df7fb4ad819ab4a8f4a68315cec47c5d` |
| Toolchain | Acton `1.2.1`, Tolk `1.5.0` |
| Successful exact-head contract workflow | [#43766860437](https://github.com/AzizIo/Vstore/actions/runs/43766860437) |
| Artifact ID | `14181479725` |
| Artifact archive SHA-256 | `25a4769ba2e4fee2f0ef913e2d7060524bc2143f6b060267651cab95b9fbf5be` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| Build descriptor SHA-256 | `4a782edd062c83897c7e9dc62bb2f011547bbf7d371b9f822934fdf36877f5c5` |
| Compiled code hash | `D822B8AFBB37027611A9A9DDC8E67C52F17BBBC45B4352C7F360693BD685CA54` |
| BOC base64 SHA-256 | `2e9b43b902b1d4c26d358af79d731d7445cca3d562d77cb858a532a487b1e05e` |
| Decoded BOC SHA-256 | `fd226adafbfe7a1e14164c59538843dd024e99e3cec2f458322ac94eaa8d7ba8` |
| Zlib-compressed BOC SHA-256 | `301c3aa6dfb729c5a0a640dc15eb527540e282c758c69a241632d4c04fd49947` |
| Deterministic StateInit hash | `29a40423c7e8fa1390782bce7e94e32f2a0e14ceef6cf05bd0f1641d0ba3f423` |
| Deterministic raw address | `0:29a40423c7e8fa1390782bce7e94e32f2a0e14ceef6cf05bd0f1641d0ba3f423` |
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
