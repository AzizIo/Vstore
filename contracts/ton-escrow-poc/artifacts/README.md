# DealEscrow generated artifact provenance

The generated artifacts for the current contract baseline are produced by the TON Escrow Contract CI workflow, not hand-authored.

- Source commit: `2913ea7d53ea7344f57d6503142c08e0b328bc7d`
- Source files: `contracts/DealEscrow.tolk`, `contracts/types.tolk`, `contracts/signatures.tolk`
- Acton: `1.2.1`
- Tolk: `1.5.0`
- Workflow run: [43634396094](https://github.com/AzizIo/Vstore/actions/runs/43634396094)
- Artifact ID: `14129775225`
- Artifact SHA-256: `80db85f1dfc91450e6e7e47990bd89bf2ff80e0ecb99d17d8f40a07f33feba58`
- ABI file in artifact: `build/abi/DealEscrow.json`
- ABI SHA-256: `05d3bc9b7aafc7fc71889cffc6d4fea2f607ea14aa48f3854c8e432747623597`
- Build descriptor: `build/DealEscrow.json`
- Build descriptor SHA-256: `f38b6c867af8ed13d95bc7fed75136961eb97c21290360197ccf9520907ffc3b`
- Compiled code hash: `E9358DAA6FFCC8FCEC979FBD631C7FC0BE336347D1DD44F3F06113E7B2A37548`

The ABI exposes the incoming DealEscrow messages and getters `get_state`, `get_progress`, `get_deal_terms`, `get_oracle_keys`, and `get_resolver_keys`. The generated TypeScript wrapper is `wrappers-ts/DealEscrow.gen.ts` inside the workflow artifact.

**Important:** the downloadable workflow artifact is retained for 90 days and expires on 2027-02-12. Verify all three SHA-256 values before consuming it. Do not enable an adapter based only on this README: the exact ABI and BOC must be vendored or fetched from an immutable artifact store at build time, and the ABI/code hash must be approved against an independent security review. No signing capability is granted by the artifact's existence.
