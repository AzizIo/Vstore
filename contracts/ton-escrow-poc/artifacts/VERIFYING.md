# DealEscrow artifact provenance and verification

This directory pins the exact DealEscrow ABI and the hashes of the compiled code artifact produced by the reviewed PR #193 source.

## Frozen provenance

| Field | Value |
|---|---|
| Source commit | `2913ea7d53ea7344f57d6503142c08e0b328bc7d` |
| Acton | `1.2.1` |
| Tolk | `1.5.0` |
| Workflow run | [43634396094](https://github.com/AzizIo/Vstore/actions/runs/43634396094) |
| Artifact ID | `14129775225` |
| Original archive SHA-256 | `80db85f1dfc91450e6e7e47990bd89bf2ff80e0ecb99d17d8f40a07f33feba58` |
| Original ABI SHA-256 | `05d3bc9b7aafc7fc71889cffc6d4fea2f607ea14aa48f3854c8e432747623597` |
| Original build descriptor SHA-256 | `f38b6c867af8ed13d95bc7fed75136961eb97c21290360197ccf9520907ffc3b` |
| Compiled code hash | `E9358DAA6FFCC8FCEC979FBD631C7FC0BE336347D1DD44F3F06113E7B2A37548` |
| Original BOC base64 SHA-256 | `1dd9695f38ebc6d158866159ef796bbe8e7d4ec7558a5a2093a4b74951454e57` |
| Original decoded BOC SHA-256 | `aaaa3822a52e28410589cbd11e7e81252ea8d52b07ece73a9b5dda1c07d8a167` |

## What is stored

- `frozen/DealEscrow.abi.json` — generated ABI snapshot, canonical digest pinned in `frozen/manifest.json`.
- `frozen/manifest.json` — immutable provenance and expected compiled code/BOC digests.

The compiled BOC itself is deliberately **not** checked in as a hand-copied text file. CI rebuilds it from the pinned Acton/Tolk source and compares both the compiler code hash and exact BOC digests against the frozen manifest. This avoids accepting a damaged or mistyped binary snapshot.

## Local verification

From `contracts/ton-escrow-poc`:

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/verify_frozen_files.py
acton build
python3 scripts/verify_build_matches_manifest.py
```

## Limitations

These checks pin ABI provenance and detect compiler-output drift. They do not prove semantic contract safety, StateInit/address derivation correctness, backend adapter correctness, provider finality, or live testnet acceptance. Independent TON/Tolk review remains mandatory. Signing and deployment remain disabled.
