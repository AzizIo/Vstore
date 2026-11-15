# DealEscrow artifact provenance and verification

This directory pins the ABI and compiler output for the current testnet-only DealEscrow source, including the persisted outbound-action storage layout and the `RetryFailedOutboundAction` opcode. Any change to contract code or storage changes the StateInit hash and the per-deal raw address; never reuse an address created from a previous code/storage version.

## Frozen provenance

| Field | Value |
|---|---|
| Source commit | `48482bec7beeae2c59f24cbfd589067c9625c037` |
| Toolchain | Acton `1.2.1`, Tolk `1.5.0` |
| Strict green contract workflow | [#43759466333](https://github.com/AzizIo/Vstore/actions/runs/43759466333) |
| Artifact ID | `14179053785` |
| Artifact archive SHA-256 | `018c0c117e9c1914a9c76ca6cf428e990049cf725dd0789e08733bb02c3aae93` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| Build descriptor SHA-256 | `0c3c7dec0bbf5bb231a007e5d99e28a5c5b7285d9cbdd3324e1172cd756b2eea` |
| Compiled code hash | `2F96C25E20D744713E72CE09A5EF209414840B52B3F06EE96E00E64884608044` |
| BOC base64 SHA-256 | `8b7adda1bca4551050c968e97d8fed24f92554d3ab94e30b61a71fdd1fd720ee` |
| Decoded BOC SHA-256 | `7233b9bb48f998cfe8c6c68e0b088c50b36268a423ca7039cf60a30cb7bd96fa` |
| Deterministic StateInit hash | `5173d3e22bb3eadcc16ac2732553d3cb143250848cd4dd7866f101d82d3e6737` |
| Deterministic raw address | `0:5173d3e22bb3eadcc16ac2732553d3cb143250848cd4dd7866f101d82d3e6737` |
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

The Acton emulator suite demonstrates behavior only in the pinned toolchain/test fixtures. The first diagnostic artifact generated for the late-finality source passed compilation, ABI and StateInit cross-checks, but its one added timeout regression assertion was incorrect (it expected `nftInEscrow` to clear before oracle reconciliation); this was corrected on the branch and awaits exact-head rerun. Emulator evidence is not a live chain finality proof, independent TON/Tolk security audit, or manual TON testnet/Tonkeeper acceptance. A trusted provider must prove the exact collection membership before immutable deal terms are created. Signing and deployment remain disabled.
