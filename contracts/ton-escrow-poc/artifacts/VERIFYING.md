# DealEscrow artifact provenance and verification

This directory pins the ABI and compiler output for the current testnet-only DealEscrow source, including the persisted outbound-action storage layout and the `RetryFailedOutboundAction` opcode. Any change to contract code or storage changes the StateInit hash and the per-deal raw address; never reuse an address created from a previous code/storage version.

## Frozen provenance

| Field | Value |
|---|---|
| Source commit | `979ec32f07224726532fdf48b941eda8314f32b0` |
| Toolchain | Acton `1.2.1`, Tolk `1.5.0` |
| Successful exact-head contract workflow | [#43760602962](https://github.com/AzizIo/Vstore/actions/runs/43760602962) |
| Artifact ID | `14180230821` |
| Artifact archive SHA-256 | `557b694b6980d1560917d7c6f1331a185c084c39c3617cea6977d3fc3dcdb9af` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| Build descriptor SHA-256 | `71499599b33d728d8f0ca0b5b26a49d6f557ffb2a9c5bfd20d2163bc738ea779` |
| Compiled code hash | `1BCCBF586878F8032F4E860707B0102EC554B4E1C0CFD7DEA362E1DD391D6666` |
| BOC base64 SHA-256 | `2ba55420e6b09c94986d51b045db92959df11f66b339cd77df4e919d30a0e50b` |
| Decoded BOC SHA-256 | `b4a46ef78089119fb10272e1edbd152f8b5e9c337b59d759ad5e1c661dd4fbb5` |
| Zlib-compressed BOC SHA-256 | `57eec30799e23fe30b3d54c4407949ae99c1af8ebe921e2ce053d1d4f17c80f3` |
| Deterministic StateInit hash | `ffd464daa07d4fd3b99e2469520eb77624f3265de9784d103df3babc15c5199f` |
| Deterministic raw address | `ffd464daa07d4fd3b99e2469520eb77624f3265de9784d103df3babc15c5199f` |
| Initial data cell hash | `ffd464daa07d4fd3b99e2469520eb77624f3265de9784d103df3babc15c5199f` |

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
