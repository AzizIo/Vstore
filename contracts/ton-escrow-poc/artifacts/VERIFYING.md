# Frozen DealEscrow artifact verification

This verifies the exact PR #193 contract artifact that is currently recorded in Issue #197. It does not validate contract correctness, StateInit derivation, security, provider finality or live testnet behavior.

## Frozen provenance

| Field | Pinned value |
|---|---|
| Source commit | `2913ea7d53ea7344f57d6503142c08e0b328bc7d` |
| Acton | `1.2.1` |
| Tolk | `1.5.0` |
| Workflow run | [43634396094](https://github.com/AzizIo/Vstore/actions/runs/43634396094) |
| Artifact ID | `14129775225` |
| Archive SHA-256 | `80db85f1dfc91450e6e7e47990bd89bf2ff80e0ecb99d17d8f40a07f33feba58` |
| ABI SHA-256 | `05d3bc9b7aafc7fc71889cffc6d4fea2f607ea14aa48f3854c8e432747623597` |
| Build descriptor SHA-256 | `f38b6c867af8ed13d95bc7fed75136961eb97c21290360197ccf9520907ffc3b` |
| Compiled code hash | `E9358DAA6FFCC8FCEC979FBD631C7FC0BE336347D1DD44F3F06113E7B2A37548` |

The generated Actions artifact has a finite retention period. Do not treat it as a permanent dependency or silently replace it with a rebuild.

## Verify a downloaded archive

Download artifact `14129775225` from workflow run `43634396094`, then run:

```bash
python3 scripts/verify_artifact.py /path/to/ton-escrow-acton-artifacts.zip
```

The verifier checks the archive digest before opening it, rejects unsafe/duplicate ZIP paths and corrupt members, checks the exact ABI/build descriptor digests, and confirms the ABI identity plus compiled code hash.

## Tests

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

The same tests run in the TON Escrow Contract CI workflow.

## Important limitations

- The archive remains an expiring GitHub Actions artifact; this change does not vendor the ABI, wrapper or BoC into a durable release.
- The verifier pins integrity and provenance, not compiler reproducibility or semantic correctness.
- It does not derive a contract address or verify StateInit data.
- It does not enable backend payload construction, signing, deployment or mainnet behavior.
- Independent TON/Tolk review and live testnet acceptance remain mandatory.
