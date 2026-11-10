> **Historical baseline note (2026-11-10):** This proposal intentionally describes the repository at commit `8ab3501`, before the fresh ownership re-check in PR #34 was merged. Current `main` has since merged #34, #50 (catalog visibility), #52 (listing expiry), and #53 (seller profile). Treat repository implementation claims here as a historical snapshot, not current-state documentation. This is an independent proposal, not an owner-approved design.

# Proposal: VILTARA Safe Deal — split rails, provider-held settlement, and NFT-first escrow

- **Author / agent:** GPT-6 (independent architecture research)
- **Date:** 2026-11-10
- **Repository baseline:** main at `8ab35010de99b74812aa9426ebfbef57d9caa60b`
- **Preferred model:** E — a conditional hybrid: separate Telegram and external-web payment rails, a regulated PSP for fiat settlement, and an independently audited TON NFT escrow contract. No production approval is implied.
- **Confidence:** medium on protocol and documented platform facts; low on legal classification, PSP underwriting, and whether the exact NFT resale model is accepted by Telegram.

> This is an independent proposal for discussion only. It does not amend ADR-0001, supersede any existing design, or authorize implementation. The maintainer must choose the model after legal, platform, provider, and security review. No production payment, custody, payout, or NFT-transfer code should be started from this document alone.

## Executive recommendation

**Recommendation:** do not launch paid NFT transactions from the Telegram Mini App yet. Keep the current listing and order-reservation workflow as a non-payment flow until Telegram confirms how this particular peer-to-peer TON NFT resale product is classified, and until the seller-settlement and irreversible-delivery model is approved.

For a future real transaction, investigate a two-rail architecture:

1. **Telegram rail:** the Mini App remains the discovery, wallet-verification, order-coordination, and support interface. If Telegram confirms the sale is a digital good within section 6.2, any payment initiated inside the TPA must use Stars. Stars are not seller-specific escrow funds, and Telegram explicitly discourages real-time sales of valuable virtual items that cannot be reclaimed after a dispute or chargeback. A Stars invoice by itself is therefore not a safe-deal solution.
2. **External web rail:** investigate a standalone web checkout with a regulated marketplace PSP. Adyen for Platforms is the most technically promising candidate found in the reviewed public documentation because it provides seller onboarding, balance accounts, split instructions, settlement controls, and on-demand payouts. Its public documentation does **not** establish that Adyen accepts VILTARA's NFT resale, escrow, or delayed-release model. Written underwriting and a negotiated contract are mandatory. Do not link from the Mini App to an external checkout as a workaround for Telegram's digital-goods rules; the TPA/store policy treatment must first be confirmed.
3. **Asset rail:** for a testnet proof of concept, investigate a TEP-62 escrow contract that receives the exact NFT before payment capture, holds it while the buyer inspects the on-chain item identity, and releases it only after a server-verified payment and buyer acceptance. A separate chain watcher should confirm post-transfer ownership before the PSP payout is requested. The contract and watcher are not approved for mainnet. TON's asynchronous message model and the absence of a standard TEP-62 safe-transfer rollback mean that the two legs are not an atomic exchange.

This proposal deliberately avoids describing a provider balance account, database ledger, or smart contract as legally segregated escrow without an explicit legal and provider basis. A database ledger is accounting evidence; it does not itself hold money or grant a licence.

**Current production recommendation: NO-GO for live paid NFT trades.** A non-payment marketplace, test-provider integration, and isolated testnet contract research may proceed as separate, gated workstreams.

## What exists in the repository today

Inspected on 2026-11-10 against the main SHA above:

- FastAPI modular monolith, PostgreSQL/SQLAlchemy async, Alembic, Redis, React/TypeScript Mini App, aiogram bot, TON Connect wallet proof, and a read-only TON Center API v3 NFT verifier.
- Listings can be created as drafts and safely published after a fresh TEP-62 ownership verification. The seller-management service performs the external provider check outside a database transaction, then locks and re-reads the listing, wallet, and asset before publication.
- Orders are created from ACTIVE listings. Order creation snapshots the listing price/currency, reserves the listing, writes an order event, and enqueues Telegram notifications. The current DB state constraint permits only pending_payment, cancelled, and expired. The cancellation/expiry path releases the listing.
- Order creation currently checks the persisted NFT asset owner and verification fields. **PR #34, which adds a fresh ownership check before reservation, was open and not merged at the time of this research.** Do not treat that protection as already present on the inspected main.
- The PaymentAdapter in backend/app/orders/payment.py is only a Protocol with create_intent and verify_notification. It is not wired to a provider. It has no refund or reconciliation contract.
- There is no real payment collection, provider webhook endpoint, payment-intent persistence, payment ledger, seller balance, payout, refund, dispute, escrow contract, chain-transfer worker, or NFT transfer implementation.
- The TON Center v3 integration is an indexed-data adapter. It is appropriate for discovery and operational monitoring, but a successful API response is not by itself a cryptographic proof of chain state.
- Wallet proof is non-custodial: the server validates a TON Connect proof and records the wallet association. The server does not receive the user's seed phrase or private key.

The code baseline therefore provides a good reservation and event-history starting point, but it does not yet provide the money state machine or the asset-delivery state machine needed for a safe deal.

## Options compared

### Model A — Telegram Stars plus operator-managed seller settlement

**Money flow**

Buyer pays an XTR invoice. A successful_payment update identifies the charge. Stars are reflected in the TPA balance controlled through the Telegram account that owns the bot/Mini App. If the operator later obtains a reward through the supported Telegram/Fragment route, that is a separate reward process; it is not a direct payment from Telegram to the NFT seller.

Any seller payout would therefore be a separate obligation of the VILTARA legal entity/operator, funded from an approved payout source. A seller sub-balance stored in PostgreSQL would be an internal payable record, not a segregated pool of Stars or money.

**NFT flow**

Seller sends the item directly to the buyer's verified wallet, or deposits it into a separate escrow contract. A post-transfer chain observation confirms the new owner. If delivery fails, the operator may refund Stars, but the NFT may already have become irreversibly controlled by the buyer if transfer had succeeded.

**Refunds and disputes**

Before delivery, the operator can attempt a full Stars refund using refundStarPayment and must handle /paysupport. The refund is funded from the TPA Stars balance. After an irreversible NFT transfer, a refund does not automatically recover the NFT. The operator would need the buyer to return it, or compensate from its own funds. Telegram is not the dispute arbitrator.

**Assessment**

This is the only documented in-TPA payment method for digital goods if the exact transaction is within Telegram section 6.2. It does not create seller escrow, seller payout rails, or atomic asset delivery. It is not sufficient to advertise a guaranteed safe deal.

### Model B — TON NFT escrow contract plus TON payment

**Money flow**

Outside the Telegram in-app purchase flow, buyer sends TON to an audited escrow contract. The contract holds TON until its release conditions are met. The contract can return funds on a defined failure path if the funds have not already been released.

**NFT flow**

Seller deposits the exact item to the escrow contract using a TEP-62 transfer. The contract validates the item and order binding. After payment and the required delivery/acceptance evidence, the contract sends the NFT to the buyer and releases TON to the seller.

**Refunds and disputes**

The contract can encode deadlines and deterministic refund paths, but TON messages are asynchronous. The NFT-item transfer and the TON payout are separate messages/transactions. If one side succeeds and the other fails, there is no general cross-contract rollback. TEP-62 does not provide a mandatory safe-transfer method that automatically reverts ownership when receiver-side execution fails. A chain watcher or authorized attesters may be needed for post-transfer confirmation, introducing trust in that evidence path.

**Assessment**

This is the most NFT-native candidate for a non-Telegram checkout, but it is technically and legally high-risk. It is not a compliant workaround for Telegram Stars. Production requires a reviewed legal classification, formal contract specification, independent audit, operational key controls, and a plan for asymmetric failures.

### Model C — External regulated PSP / marketplace payments

**Money flow**

Buyer pays through a standalone web checkout. A marketplace PSP processes the transaction. The seller is onboarded and identified as a PSP account holder, where the provider supports that model. Payment splits book seller proceeds and platform commission to provider balance accounts. Seller payout occurs only when funds are settled and the provider's contract permits the requested delay or on-demand release.

**NFT flow**

The seller first deposits the exact NFT into an escrow contract. The provider captures the payment only after the deposit is independently confirmed. The contract holds the NFT for buyer inspection and releases it on buyer acceptance. A chain watcher verifies that the buyer wallet is the current owner before the marketplace requests seller payout.

**Refunds and disputes**

The PSP handles card/payment refunds and chargebacks according to the provider contract and scheme rules. The NFT contract handles asset return only while it still holds the item. Once the NFT is in the buyer's self-hosted wallet, it cannot be unilaterally clawed back by the marketplace. A post-delivery refund may require a buyer-signed return transaction or a funded compensation reserve.

**Provider screening performed**

- **Adyen for Platforms:** public docs describe user balance accounts, account-holder onboarding and KYC, split payment instructions, settlement delay, payout to verified bank accounts, custom/on-demand payout, and platform internal fund transfers. This makes it a technical discovery candidate, not a confirmed NFT provider. The reviewed public pages do not establish acceptance of TON NFT secondary-market transactions or escrow-like payout holds. Written pre-approval for the exact business model is required.
- **Stripe:** its restricted-business page lists first-party NFT minting/sales including marketplaces and SaaS, and separately restricts payment facilitation/aggregation that receives proceeds for third-party sellers. VILTARA should not assume Stripe Connect is available. Only a written exception/approval for the exact secondary-market model could change this assessment.
- **MANGOPAY:** its published policy labels payment escrow/payment facilitation and cryptoassets/NFTs as restricted activities. It is not a plug-and-play choice; written underwriting would be required before considering it.

**Assessment**

A regulated PSP could reduce the platform's direct handling of fiat and provide seller onboarding, balance reporting, refunds, chargeback signals, and payout controls. It does not automatically make the flow legal escrow. Provider acceptance, the platform's actual control over payout timing, account contracting, and ZAG/PSD2 classification require legal review.

### Model D — Direct non-custodial P2P exchange

**Money flow**

Buyer pays seller directly, for example with a wallet transaction. VILTARA does not receive or control funds. There is no platform-controlled per-order money balance and no automatic seller payout.

**NFT flow**

Seller transfers directly to the buyer. The platform verifies wallets and observes the chain, but it cannot force either party to complete the other leg.

**Refunds and disputes**

There is no native reversal. A refund or return requires the recipient's cooperation and a new transaction. The platform can mediate or restrict accounts, but cannot guarantee the money or NFT is recovered.

**Assessment**

This is a viable non-custodial coordination marketplace only if the UI says plainly that the platform does not hold funds, guarantee delivery, or provide escrow. It is not a safe deal and should not be branded as one.

### Model E — Conditional hybrid proposed here

This combines a separate Telegram discovery/coordination surface, a PSP-managed external fiat settlement path where permitted, and a TON NFT escrow contract for a future reviewed asset flow. The Telegram path does not link to or disguise an external checkout until the store/platform interpretation is approved. The external web path is an independent product surface with its own contracts, disclosures, jurisdiction restrictions, and checkout rules.

This hybrid has the most promising separation of responsibilities, but it inherits the unresolved legal and provider gates of Models B and C. It is a candidate for further investigation, not a production approval.

## Preferred technical sequence — external PSP + NFT-first escrow candidate

The sequence below is a concrete testable architecture hypothesis. Every live step remains conditional on PSP underwriting and legal/platform sign-off.

### Money-flow diagram

    Buyer
      |
      | card / PSP-supported method on standalone web checkout
      v
    Regulated marketplace PSP / acquirer
      |
      | payment captured; provider reference + settlement data
      v
    Provider-controlled seller/platform balance accounts
      |
      | payout withheld by provider configuration / contract
      | until delivery evidence and the agreed review window
      v
    Seller verified bank account
     
    Provider split instructions:
      - seller gross proceeds
      - VILTARA commission
      - PSP processing fees
      - agreed rolling reserve / chargeback reserve

VILTARA's database records an auditable ledger of the provider's obligations and movements. It does not represent that the database itself holds the money.

**Important legal boundary:** the Adyen documentation describes funds assigned to the users' balance accounts and payout to verified bank accounts. It also describes platform-controlled custom/on-demand payouts. For Germany, BaFin's ZAG guidance specifically discusses online-marketplace escrow services that receive purchase money into pooled accounts and forward it after delivery confirmation as a potential Finanztransfergeschäft. BaFin further describes a licensed payment institution handling the flow for the parties where each party has its own contract with that institution and the platform has no influence over the flow. Therefore a VILTARA-controlled payout release is not automatically within a technical-service exemption. Legal counsel must determine whether the proposed platform role requires authorisation or a different structure.

### NFT-flow diagram

    Seller TON wallet
      |
      | seller signs TEP-62 transfer with new_owner = escrow contract
      v
    Order-bound TON NFT escrow contract
      |
      | validate allowlisted item, network, order nonce and deposit event
      | contract holds the NFT while payment is pending / buyer inspects
      v
    Buyer verifies item identity, collection, network and destination wallet
      |
      | buyer signs acceptance / release instruction
      v
    Escrow contract sends TEP-62 transfer to buyer wallet
      |
      | independent chain observer verifies exact item owner = buyer wallet
      v
    Provider payout release is requested for seller

The escrow contract must not accept arbitrary NFT items merely because a sender claims a listing ID. It must bind each deposit to a configured network, canonical item address, collection policy, order nonce, seller, buyer destination, expiry, and contract version. A chain watcher independently checks the actual item owner after deposit and release. TON Center v3 can be used as one indexed source, but for valuable trades the acceptance policy should require stronger evidence such as a verified lite-server proof or corroboration from independently operated providers, rather than trusting a single indexed HTTP result.

**Why deposit before capture:** it prevents the seller from receiving payment while still having unilateral control over whether to deliver the NFT. If the seller does not deposit before the order's asset-lock deadline, no payment is captured and the reservation is released. The seller bears the risk that the NFT is locked in escrow during the buyer acceptance interval; that interval must be bounded in the contract and seller terms.

**Why hold the asset until buyer acceptance:** the buyer can inspect the exact on-chain item and collection while the asset remains inside escrow. If the buyer rejects it within the agreed inspection period, the contract's dispute path can return the NFT to the seller and the PSP can refund the payment. If the buyer accepts, the contract releases the NFT and the chain watcher verifies delivery. Legal consumer rights may still require remedies beyond this contractual inspection flow.

**No claim of atomicity:** the contract cannot atomically coordinate a card PSP and the TON chain. TON contract messages are asynchronous. Payment capture, NFT deposit, buyer acceptance, NFT release, chain confirmation, refund, and payout are a saga with explicit intermediate states, timeouts, idempotency, and manual recovery.

## Order, payment, asset and settlement state machine

Keep the current order reservation statuses semantically intact. Introduce distinct payment, escrow, delivery, dispute and payout records rather than using one overloaded status field as the source of truth.

Suggested high-level lifecycle:

    ACTIVE listing
      -> RESERVED
      -> ASSET_DEPOSIT_PENDING
      -> ASSET_HELD
      -> PAYMENT_PENDING
      -> PAYMENT_CAPTURED
      -> AWAITING_BUYER_ACCEPTANCE
      -> NFT_RELEASE_PENDING
      -> NFT_DELIVERED_CONFIRMED
      -> PAYOUT_PENDING
      -> COMPLETED

Recovery / exception branches:

    PAYMENT_FAILED
    CANCELLED
    EXPIRED
    REFUND_PENDING
    REFUNDED
    DISPUTED
    DELIVERY_FAILED
    CHARGEBACK
    MANUAL_REVIEW

Suggested trusted transition guards:

| Transition | Trusted source | Required evidence |
|---|---|---|
| ACTIVE → RESERVED | Order service | Authenticated buyer, server snapshot, idempotency key, listing and seller guards |
| RESERVED → ASSET_DEPOSIT_PENDING | Order service | Buyer and seller addresses verified, order-specific contract nonce issued |
| ASSET_DEPOSIT_PENDING → ASSET_HELD | Chain watcher | Exact NFT item and network, contract deposit notification, independent owner observation |
| ASSET_HELD → PAYMENT_PENDING | Order service / PSP adapter | Asset deposit recorded, invoice amount/currency/merchant fixed from server order snapshot |
| PAYMENT_PENDING → PAYMENT_CAPTURED | PSP webhook + reconciliation | Signature/authentication valid, exact merchant/account, order reference, currency, amount, unique provider event and charge IDs |
| PAYMENT_CAPTURED → AWAITING_BUYER_ACCEPTANCE | Order service | Captured payment is persisted and reconciled; no client-paid flag |
| AWAITING_BUYER_ACCEPTANCE → NFT_RELEASE_PENDING | Buyer wallet signature + order service | Acceptance references exact order nonce, item, buyer destination and policy version |
| NFT_RELEASE_PENDING → NFT_DELIVERED_CONFIRMED | Chain watcher | Verified chain transaction/trace and exact current item owner equals buyer's verified wallet |
| NFT_DELIVERED_CONFIRMED → PAYOUT_PENDING | Settlement service | Delivery observation accepted, dispute/review window satisfied, no active hold |
| PAYOUT_PENDING → COMPLETED | PSP webhook + reconciliation | Provider confirms payout booked/completed; unique transfer reference |
| Any eligible pre-release state → REFUND_PENDING | Dispute/admin policy | Approved refund outcome; asset return path still viable |
| REFUND_PENDING → REFUNDED | PSP + chain watcher | Provider confirms refund and escrow contract confirms NFT returned to seller |
| Any eligible state → DISPUTED | Buyer/seller/admin policy | Evidence attached, allowed dispute window, automatic payout/release frozen where possible |

No browser request may set paid, delivered, refunded, disputed, completed, commission, seller payout, or escrow ownership. The PSP webhook, chain observer, and authorised dispute process are separate trust boundaries. An admin action may decide a dispute but must not forge a PSP payment or chain-delivery event.

## Protection of buyer and seller

### Buyer protection

- Seller must place the exact NFT in an order-bound escrow contract before the PSP captures payment.
- Buyer sees the network, item address, collection address, item metadata and destination wallet before accepting delivery.
- Buyer can inspect the asset while it is held in escrow; the inspection/acceptance timer is explicit and bounded.
- No payout is requested until the NFT is delivered to the buyer's verified wallet and independently observed on-chain.
- If seller fails to deposit, payment is not captured.
- If the item is not deposited, is rejected before release, or cannot be released, the dispute path can refund the buyer and return the NFT to the seller.
- The app must disclose that indexed ownership data may lag and that final confirmation can take time.

### Seller protection

- The exact NFT is reserved in a contract with order ID and expiry; it cannot be sold through a second VILTARA order while held.
- Buyer payment is captured only after asset deposit has been confirmed.
- Buyer acceptance must be explicit and attributable to a verified wallet signature; an inspection deadline prevents indefinite limbo.
- Payout timing, platform fee, PSP fees, reserve/holdback, chargeback liability and evidence requirements are disclosed before listing.
- If the buyer does not accept or open a dispute by the deadline, a published contract/runbook policy decides whether the item is returned or a human review is triggered. Do not make silent discretionary releases.
- Seller payout goes only to a PSP-verified payout instrument; changing payout details requires fresh PSP verification and cooling-off controls.

### Protection limits that must be disclosed

- A TON NFT transfer to a buyer-controlled wallet is not generally reversible by the marketplace.
- Card chargebacks can be raised after on-chain delivery; a provider may debit a seller/platform balance or reserve after the NFT has left escrow.
- A platform cannot promise both an unconditional card refund and recovery of an NFT that has already been transferred irreversibly.
- A database reserve is not guaranteed funds unless it is backed by actual provider-held or otherwise legally controlled assets.
- No contract removes the risk of contract bugs, compromised upgrade/admin keys, malicious oracles, provider insolvency, provider account freeze, or legal enforcement.
- If VILTARA cannot fund post-delivery compensation or obtain a contractual PSP solution for chargebacks, it must not promise full buyer protection after final NFT delivery.

## Refunds and disputes

### Refund matrix

| Scenario | Funds action | NFT action | Order outcome |
|---|---|---|---|
| Seller never deposits NFT | No capture; if accidentally captured, request full PSP refund | Nothing entered escrow | Cancelled / payment failed |
| Provider declines or expires payment before capture | No seller payout; release any payment authorisation per provider rules | Return NFT from escrow to seller | Cancelled / expired |
| Duplicate or replayed payment webhook | No duplicate capture or ledger entry | No second transfer | Existing payment record remains authoritative |
| Payment captured; buyer rejects item before NFT release | Full PSP refund, subject to provider completion | Return NFT from escrow to seller | Refunded after both legs confirm |
| Chain observer unavailable | Do not pay seller; do not infer failure or success | Keep NFT locked; retry from independent sources | Manual review / delivery pending |
| NFT release fails and item remains in escrow | Refund buyer after approved failure handling | Return NFT to seller | Refunded after chain confirmation |
| NFT reaches buyer; buyer reports wrong item | Freeze payout if not already released; compare item address, collection, signed order and trace | Buyer-signed return or dispute resolution; cannot unilaterally reclaim | Disputed |
| Buyer claims non-receipt but chain proves item owner is buyer | Preserve evidence; apply published dispute process | No involuntary transfer from buyer wallet | Dispute decision |
| Card chargeback after NFT delivery | PSP may debit seller/platform/reserve; provide evidence package | NFT generally remains with buyer unless buyer voluntarily returns | Chargeback / recovery case |
| PSP account or payout route frozen | Stop new captures; reconcile and follow provider support process | Keep undealt-with assets in escrow where contract allows | Manual review |
| Escrow contract / signer / watcher outage | No optimistic payout; pause new transactions | Do not release asset until safe recovery | Manual review |

### Dispute decision process

- Publish a finite initial complaint window and a separate statutory-rights escalation process. A contractual window cannot waive mandatory consumer rights.
- Evidence packet: exact order and listing snapshot, NFT item and collection addresses, chain/network, deposit transaction, release transaction, current owner observation, buyer/seller wallet proof timestamps, PSP payment/charge/refund references, messages, policy acceptance and timestamps.
- Disputes should be reviewed by a trained operator separate from the person who can execute escrow admin or PSP payout actions.
- For high-value items, require a second reviewer or threshold approval before a manual contract decision.
- Record every decision and evidence hash in an append-only audit trail; notify both parties; support an appeal path.
- If the NFT is already in the buyer's wallet, the dispute policy must say whether the buyer is required to sign a return transfer before a voluntary refund, or whether the platform will compensate from a funded reserve. Do not pretend the contract can seize it.

## Commission and seller payout

**Recommendation:** calculate fees against the actual captured settlement amount, not the listing price alone. The order snapshot records the agreed gross price, currency and fee schedule version. The settlement ledger records:

- gross buyer payment;
- PSP fee and any currency conversion;
- marketplace commission and applicable VAT/tax;
- seller gross entitlement;
- any reserve/holdback amount and its release date;
- refund/partial refund/chargeback amounts;
- payout amount and provider transfer reference;
- FX rate, source and timestamp, if applicable.

Store amounts as fixed-precision decimals in the provider's settlement currency. Do not mutate old ledger entries; post reversing/compensating entries. Each payment, refund, chargeback and payout must have a unique provider identifier and idempotency key.

**Payout sequence:** the PSP receives and settles the payment into its regulated platform structure; seller is KYC/onboarded and linked to a verified bank account; split instructions assign the agreed seller and platform amounts; the seller's payout is triggered only after the delivery/inspection policy allows it and after the PSP's settlement delay. A risk reserve may be held only if the provider contract and applicable law permit it. Define the reserve percentage, maximum duration, replenishment and negative-balance allocation in the seller agreement.

**Do not assume Adyen supports this exact delayed-release design.** Its public documentation supports balance accounts, split instructions, settlement delays, custom/on-demand payout and internal transfers. It also says platform balance accounts can go negative after refunds/chargebacks and describes a liable compensation account. Whether the exact NFT marketplace business, delayed payout period, reserve and buyer dispute process are underwritten must be agreed with Adyen. No Adyen integration should be implemented before this is in writing.

## Telegram, TON, PSP and legal constraints

### Telegram

**Verified fact:** Telegram's Bot Platform Developer Terms state that digital-goods and digital-services transactions in a TPA must use Stars rather than third-party payment providers. The Terms place responsibility for delivery and disputes on the TPA operator, require /paysupport, allow full Stars refunds, and explicitly discourage real-time sale of valuable virtual goods that cannot be reclaimed/frozen/rescinded after a successful dispute or chargeback. The TPA's Stars balance is not the developer's property; Stars are owned by Telegram and are available for Ads/rewards under Telegram's terms. The current reward value shown is USD 0.013 per Star; Stars may take up to 21 days to become available for rewards; Fragment may be unavailable to some users or countries. These values and terms can change.

**Open question / blocker:** the official wording is about digital goods and services. This research does not establish a definitive Telegram interpretation of peer-to-peer resale of a pre-existing TON NFT. The platform/store classification must be confirmed in writing for VILTARA's specific product before checkout is enabled. Until then, assume the more restrictive interpretation for the in-TPA flow.

**Consequence:** do not link from a Telegram Mini App to an external checkout as a way to avoid Stars. A separate website may be evaluated as an independent distribution/commerce surface, but whether TPA-to-web linking, promotion, or deep links are permitted for this product must be reviewed against Telegram and app-store rules.

### TON

- TEP-62 uses separate NFT item and collection contracts. A transfer message names the new owner and is sent by the current owner. The standard explicitly notes that there is no mandatory safe-transfer method that reverses ownership if receiver-side execution fails.
- TON is asynchronous: messages to different contracts are separate transactions and may be processed at different times. A payment leg and NFT leg must therefore be modelled as a saga, not assumed atomic.
- TON Connect lets the user connect a wallet and sign/send a transaction; the application must never request the seed phrase or private key.
- TON Center API v3 is an indexed data layer reading node storage and storing decoded data in PostgreSQL. It is useful for monitoring and lookup, but do not treat a successful HTTP result as a cryptographic proof of state.
- Separate TON NFT and Telegram Gifts integrations. Telegram Business Gift methods and rights do not confer arbitrary transfer rights over standard TON NFTs.

### Payment providers

- Stripe's published restricted-business policy lists first-party NFT minting/sales, including marketplaces and SaaS, and payment facilitation/aggregation for proceeds belonging to third-party sellers. Treat Stripe as unavailable unless written approval for the exact resale model is obtained.
- MANGOPAY categorises payment escrow/payment facilitation and cryptoassets/NFTs as restricted. Obtain explicit written underwriting rather than assuming the marketplace is eligible.
- Adyen for Platforms documents account-holder onboarding, seller balance accounts, split payments, settlement delays, payouts to verified bank accounts and internal transfers. It is a candidate for a sales conversation, not a confirmed provider for NFTs or legal escrow.
- No provider's public API documentation is a substitute for a signed agreement that names NFT secondary-market trading, escrow/conditional payout, reserve/holdback, chargeback allocation, refund responsibilities, jurisdictions and seller types.

### Legal / regulatory

This proposal uses EU/EEA and Germany as a **research lens only**, not as an assertion that VILTARA is incorporated or will launch there. The repository does not yet declare its legal entity, merchant of record, seller countries, buyer countries, or target-market restrictions. Those must be established before a legal opinion can be scoped.

1. **Germany — ZAG / payment services.** BaFin's ZAG guidance expressly discusses marketplace escrow services where an operator receives buyer funds into pooled accounts and forwards them to the seller after the buyer confirms proper delivery. It says such a setup can constitute Finanztransfergeschäft. The same guidance discusses a possible structure using a licensed payment institution where buyer and seller each have their own contract with the institution and the marketplace has no influence over the flow; if the marketplace controls the money movement, it may go beyond the role of a technical service provider. This is a material blocker for a VILTARA-controlled pooled account or discretionary payout model. A German payments lawyer must analyse the actual contracts, account structure, control rights and flow before launch.
2. **PSD2 / payment institution.** Payment services listed in PSD2 Annex I include payment execution and money remittance. The exact classification and any exclusion/agent model is fact-specific; do not infer that using an API or outsourcing custody removes the platform's own regulatory risk.
3. **MiCA / NFTs.** MiCA excludes crypto-assets that are unique and non-fungible, but says issuance in a large series or collection is an indicator of fungibility, a unique ID alone is insufficient, and classification uses substance over form. It also defines regulated crypto-asset services such as custody and operation of a trading platform. The exclusion is not a universal “all NFTs are out of scope” rule. Review each asset/collection model, fractionalization, rights and actual use. If in scope, custody/trading/transfer activities may trigger CASP authorisation and operational requirements, including segregation and custody controls.
4. **Transfer of Funds Regulation / Travel Rule.** If an in-scope crypto-asset service provider participates in the transfer, Regulation (EU) 2023/1113 can require originator/beneficiary information and, for transfers over EUR 1,000 to or from self-hosted addresses, measures to assess wallet ownership/control. This is a CASP-specific analysis, not a claim that every direct P2P TON transfer automatically triggers the same obligations.
5. **AML package.** Regulation (EU) 2024/1624 (AMLR) applies from 10 July 2027, subject to the regulation's own transitional rules. Confirm which entity is an obliged entity under current and future national/EU laws. KYC performed by a PSP does not automatically discharge every marketplace, sanctions or suspicious-activity obligation the operator might have.
6. **Consumer rights.** Where a seller is a trader and a buyer is a consumer, distance-contract rights can apply. The Consumer Rights Directive generally provides a 14-day withdrawal period, subject to exceptions. The digital-content exception requires prior express consent to begin performance during the withdrawal period, acknowledgement that the right is lost, and required confirmation. Whether a particular NFT resale is digital content, a digital asset or another type of supply, whether the seller is a trader, and whether the exception applies are legal questions. Do not use a checkbox to waive mandatory rights without counsel's approval.
7. **Tax / reporting / company law.** Determine VAT treatment of marketplace services and commissions, seller status, invoicing, DAC7/DAC8 or other platform reporting applicability, accounting recognition of Stars and PSP balance entitlements, consumer disclosures, sanctions screening, GDPR roles/retention, and insolvency treatment of provider balances/reserves. Do not encode a tax or reporting threshold until the target-country advice is obtained.
8. **App stores.** Apple guidelines address NFT-related services and external purchase links by storefront/entitlement; Google Play requires transparency and a financial-features declaration for apps that sell or enable users to earn tokenized digital assets, and places country-specific regulatory expectations on crypto services. Telegram's own terms refer to Apple/Google definitions of digital goods. Review the current store distribution path and country storefronts before launch.

This section is not a legal opinion. It identifies questions counsel must resolve, not a final interpretation of ZAG, PSD2, MiCA, TFR, consumer or tax law.

## Evaluation matrix

Scores are 1 (weak) to 5 (strong). Scores measure the model's design characteristics **assuming the necessary provider/platform permissions exist**. Any BLOCKER overrides the average score.

| Criterion | A: Stars + operator payout | B: TON contract escrow | C: external PSP | D: direct P2P | E: conditional hybrid |
|---|---:|---:|---:|---:|---:|
| Telegram in-app policy fit | 4* | 1 | 1 | 1 | 2* |
| Buyer protection before delivery | 1 | 4 | 3 | 1 | 4 |
| Remedy after irreversible delivery | 1 | 2 | 2 | 1 | 2 |
| Seller payment certainty | 2 | 4 | 4 | 3 | 4 |
| Custody / regulatory simplicity | 1 | 1 | 3 | 5 | 2 |
| Resistance to double-sale/fraud | 2 | 4 | 3 | 2 | 4 |
| TON technical feasibility | 4 | 2 | 4 | 4 | 2 |
| Operational burden | 2 | 1 | 3 | 3 | 1 |
| Refund / chargeback compatibility | 2 | 2 | 3 | 1 | 3 |
| Country availability | 2 | 2 | 3 | 3 | 2 |
| Safe pilot feasibility | 3 | 2 | 3 | 4 | 2 |

* A Stars invoice is the documented payment rail only if the item is classified as an in-TPA digital good. It does not solve seller escrow or the irreversible-item warning. Model E must not use an external checkout link from inside the TPA until platform/store review permits it.

### Score interpretation

- **A:** easy to prototype, but does not create seller funds or credible post-delivery buyer protection. Operator-funded settlement introduces a direct legal/accounting obligation.
- **B:** provides the strongest pre-delivery asset lock and deterministic on-chain rules, but is hard to secure and does not remove TON's asynchronous delivery problem or legal custody questions. It is not suitable as an in-TPA TON checkout.
- **C:** a regulated PSP can perform settlement, seller KYC, split accounting, refunds and bank payout. It does not guarantee NFT delivery or make the marketplace's use of balances legally escrow. Provider acceptance is currently unknown.
- **D:** lowest platform custody burden, but no enforcement, no refund, no asset/payment atomicity and no safe-deal guarantee.
- **E:** combines the useful pieces of B and C, but also combines their operational, regulatory and integration complexity. It remains conditional on Telegram classification, PSP approval and legal analysis.

**No model currently has a BLOCKER-free production path on the evidence reviewed.**

## Threat model and failure controls

| Threat / failure | Required control | Residual risk |
|---|---|---|
| Stale seller ownership | Fresh TEP-62 ownership check before reservation, before deposit, and at contract deposit; revalidate wallet binding | Indexer lag or false provider data; PR #34 remains unmerged on inspected main |
| Fake item / collection | Allowlisted network and item address, collection-index resolution, metadata separated from proof | A legitimate item may still have misleading off-chain metadata |
| Double sale | Current DB reservation uniqueness plus contract order nonce and one active deposit per item | Race between external chain actions and DB; reconcile both |
| Fake payment webhook | Verify provider signature/secret, merchant account, amount/currency, order reference, timestamp, and unique charge/event ID | Provider credentials or account compromise |
| Duplicate/out-of-order webhook | Durable webhook inbox, idempotent event handling, unique provider references, reconciliation polling | Provider can deliver late/duplicate events; never process by arrival order alone |
| Payment succeeds but webhook is lost | Scheduled provider lookup/reconciliation by idempotent intent/reference | Provider API outage delays state convergence |
| Wrong NFT is transferred | Exact item/collection/network binding and contract-held inspection stage | Token metadata/collection reputation remains a separate risk |
| TON Center outage/lag | Keep order pending; retry; corroborate with independent sources/proofs | No payout on unavailable or inconclusive evidence |
| TEP-62 transfer bounce/failure | Contract state machine, bounce handling, bounded retries and explicit recovery state | Not every receiver failure can be rolled back by a standard NFT item |
| Buyer refuses acceptance | Bounded inspection window, dispute mechanism, objective contract timeout | Badly chosen timeout may unfairly favour one party |
| Buyer chargeback after NFT delivery | PSP reserve, seller contract, dispute evidence, risk limits and funded compensation policy | NFT may remain with buyer while fiat is debited |
| PSP freezes platform/seller account | No new captures, daily reconciliation, support escalation, reserve and seller communication | Funds can remain inaccessible for an extended period |
| Admin or signer compromise | Threshold multisig, hardware keys, role separation, time-lock, monitoring and bounded per-order authority | Governance key compromise remains systemic |
| Worker crash | Durable outbox/inbox, leases, retries, dead-letter/manual-review, periodic reconciliation | Operational incident and delayed settlement |
| Insider alters ledger | Immutable journal/append-only event records, provider statements and independent reconciliation | A database alone is not tamper-proof |
| Buyer/seller identity laundering | PSP onboarding, sanctions controls and jurisdiction eligibility, plus wallet-risk process if legally required | PSP KYC does not remove all platform duties |

## Data model and API changes — conceptual only

No schema change is approved here. If the maintainer accepts a model, a future implementation could add:

- **Payment records:** payment_intents, payment_transactions, provider_webhook_inbox, refunds, chargebacks, payout_transfers, provider_account_refs.
- **Ledger:** ledger_accounts and immutable double-entry ledger_entries for buyer capture, provider clearing, seller payable, platform fee, PSP fee, reserve, refund and chargeback. No mutable User.balance field.
- **Asset custody:** escrow_contracts, escrow_orders, asset_deposits, asset_release_attempts, chain_observations, wallet attestations and per-network contract configuration.
- **Disputes:** disputes, evidence references, deadlines, decisions, reviewer identities, appeals, and immutable audit records.
- **Order history:** preserve current order_events but extend actor identities only by a reviewed migration; payment and chain facts should also have their own immutable external-event records.
- **Outbox:** durable commands for PSP refunds, escrow release/return, payout request and notification; retry with leases and idempotency keys.

Possible API families, if later approved:

- Server-only payment intent creation from an existing order snapshot.
- Provider webhook endpoint with raw-body verification, durable inbox insertion, and asynchronous processing.
- Authenticated buyer acceptance / dispute submission referencing an order nonce.
- Seller status and payout read endpoints; no client-side trigger that marks payment or delivery complete.
- Admin dispute decision endpoint with strong RBAC, second-person approval for high-value orders, and audit trail.
- Read-only reconciliation/admin endpoints for PSP statements and chain evidence.

All external network calls must occur outside database row-lock transactions. The pattern already used in listing publication is a useful baseline: snapshot, release transaction, call external provider, start a new transaction, lock and compare the same identifiers/state, then commit the local transition. Contract commands and provider API calls should be generated through a durable outbox so a database commit cannot be lost between state change and external side effect.

## Fee and payout example

The following is illustrative only and is not a proposed price schedule:

- Buyer gross charge: 100.00 settlement-currency units.
- Platform commission: 5.00.
- PSP processing fee: 2.00.
- Seller gross entitlement: 95.00 before tax/withholding, subject to the seller agreement.
- Temporary reserve: 5.00 withheld from seller entitlement if the provider and law permit it.
- Seller immediately eligible payout: 90.00, less applicable tax/withholding and any other disclosed charges.
- Reserve release: 5.00 after the agreed chargeback risk window or after a dispute outcome.

All numbers must be configured from a signed fee schedule and actual provider settlement data. Do not promise the illustrative reserve duration or payout date before provider approval.

## Test plan and rollout gates

### Phase 0 — legal and provider discovery (no payment code)

- Confirm the operating legal entity, its country, target buyer and seller countries, professional-vs-private seller policy, merchant of record, governing law and dispute forum.
- Obtain written Telegram guidance on the classification of P2P TON NFT resale, in-TPA checkout, and any permitted external web journey.
- Obtain a written PSP decision for secondary NFT marketplace transactions, seller onboarding, settlement delay, payout holds, refunds, chargebacks, reserve, country coverage and whether the proposed platform controls any regulated funds flow.
- Obtain ZAG/PSD2 and MiCA/TFR/AMLR analysis for the actual legal agreements and money/asset flow, plus consumer and tax advice.
- Confirm app-store listing, NFT sale buttons and any outbound purchase links per storefront.
- Define customer support, complaint SLA, seller terms, refund policy, AML/sanctions policy, reserve capital and incident response owner.

### Phase 1 — non-financial architecture prototype

- Fake PSP adapter and fake chain observer only.
- Exercise state transitions with deterministic fixture events; no real credentials, live Stars, live fiat, live TON mainnet contract or production payment state.
- Build a payment/chain failure matrix and verify reconciliation after worker crashes.
- Test webhook replay, delayed event, duplicate event and out-of-order event behavior.

### Phase 2 — isolated TON testnet proof of concept

- Separate disposable escrow contract; no mainnet keys or real-value assets.
- Independent contract review before testing valuable assets.
- Test deposit, collection verification, incorrect item, bounce, low gas, timeout, repeated messages, replay, buyer rejection, refund, release, signer rotation and recovery.
- Verify chain traces and owner changes using independent data sources.
- Do not connect a live fiat PSP or enable seller payout.

### Phase 3 — PSP sandbox and seller onboarding test

Only after provider written acceptance:
- Sandbox/test account, seller KYC, test cards, split accounting, refund, chargeback event and on-demand payout simulations.
- Durable webhook inbox, outbox, idempotent worker and reconciliation job.
- No real-value NFT sale; no platform-held pooled funds.

### Phase 4 — controlled production pilot (only after all gates)

- External legal opinion and provider contract signed.
- Independent smart-contract audit and operational key review completed.
- Country allowlist, seller screening, transaction/value caps, reserve capital and manual dispute rota ready.
- User-facing terms state exactly what is and is not guaranteed.
- Daily PSP and chain reconciliation, alerting, incident drill, support SLA and shutdown/runbook tested.
- Pilot only in countries and for asset types explicitly approved by Telegram, app stores, PSP and counsel.

## Estimated operational burden

| Model | Operations required |
|---|---|
| A — Stars | Telegram payment-support team, Star balance/refund reconciliation, seller payout operations, cash-flow and compensation reserve |
| B — TON escrow | Contract engineering, key management/multisig, chain watcher, TON fees, security monitoring, manual arbitration and recovery |
| C — PSP | PSP onboarding/KYC coordination, settlement/reconciliation, chargeback evidence, payout support, provider relationship and compliance programme |
| D — direct P2P | Abuse/fraud moderation, wallet verification, user disputes and careful no-escrow communications |
| E — hybrid | All of B and C, plus two distribution/payment-policy surfaces, cross-system reconciliation, seller support and legal/store compliance |

Model E is the most complex. It should not be selected solely because it provides the strongest theoretical asset lock.

## Risks and unresolved questions

1. Is the exact peer-to-peer sale of an existing TON NFT by a user to another user a digital good sale under Telegram's terms, Apple/Google store rules, or a different classification?
2. Will Telegram permit an external-web commerce surface associated with the TPA, and what TPA links, CTAs, messages or deep links are allowed?
3. Which legal entity operates VILTARA and in which country? Is the intended seller population consumer, professional, or mixed?
4. Does the platform operate an arrangement which is a payment service or Finanztransfergeschäft if it can trigger or delay seller payout, even where the licensed PSP technically holds the balance?
5. Will a PSP underwrite TON NFT resale and the proposed deposit/inspection/dispute/payout sequence? Will it permit payout holds for the required period?
6. If a provider balance is credited to a seller account but payout is delayed, who legally owns/controls the claim and how is it treated on provider insolvency?
7. What chargeback reserve is sufficient, who funds it, and what happens if a buyer obtains a card refund while retaining an NFT?
8. Does each VILTARA NFT collection qualify for MiCA's unique/non-fungible exclusion, or do large series/utility/financial features bring some collections back into scope?
9. Would VILTARA or a contract operator perform a CASP custody, trading-platform, exchange, or transfer service if the relevant NFT is in scope?
10. Which consumer withdrawal and conformity remedies apply to professional sellers and consumers after an irreversible on-chain transfer?
11. Who can make a final dispute decision, what is the maximum decision deadline, and what independent appeal exists?
12. Does the escrow contract hold assets solely under user instructions, or does the operator exercise control that changes the regulatory analysis?
13. What level of chain finality/proof is enough for a high-value item? Which independent observer(s) and signer quorum are trusted?
14. What is the recovery plan if the PSP terminates, the bot owner account is limited, Fragment is unavailable, the operator entity is insolvent, or the escrow admin key is lost?
15. How should Telegram Gifts be handled? They must remain outside this TON NFT design until their specific Telegram Business permissions and transfer path are separately validated.

## Final recommendation and decision status

**Independent recommendation for review:** Model E is the most promising long-term research direction only if it is split into distinct, policy-compliant surfaces: no paid checkout in the Telegram Mini App until Telegram/store classification is confirmed; a separately approved external PSP route; and a testnet-first TON NFT escrow contract with pre-deposit, inspection, acceptance, independent chain confirmation, and delayed PSP payout.

**Do not approve the following from this proposal alone:**
- live Stars transactions for TON NFT resale;
- external checkout links from the Mini App;
- Stripe, MANGOPAY, or Adyen as an assumed available provider;
- a VILTARA pooled bank account or database-based escrow;
- mainnet NFT escrow or automatic NFT delivery;
- a promise of full post-delivery chargeback protection;
- a claim that the platform is a guarantor, custodian, or licensed escrow provider.

The most useful next action is a coordinated written pre-clearance round: (1) Telegram's NFT resale/store-policy classification, (2) Adyen or another PSP's NFT secondary-market underwriting and payout-hold acceptance, and (3) counsel's ZAG/PSD2/MiCA/TFR/consumer/tax analysis for the actual legal entity and target countries. The maintainer should compare this proposal with other agents' proposals and decide which gates and model, if any, are worth taking into a new ADR.

**Maintainer decision: NOT DECIDED.** ADR-0001 remains unchanged and authoritative until the maintainer approves a new decision record.

## Sources — official documents checked 2026-11-10

### Repository sources

- VILTARA main baseline: https://github.com/AzizIo/Vstore/tree/8ab35010de99b74812aa9426ebfbef57d9caa60b
- Active discussion: https://github.com/AzizIo/Vstore/blob/main/docs/discussions/0001-safe-deal-payment-and-escrow.md
- Current proposed ADR (not modified): https://github.com/AzizIo/Vstore/blob/main/docs/adr/0001-compliant-payments-and-escrow.md
- Existing technical design (not modified): https://github.com/AzizIo/Vstore/blob/main/docs/PAYMENTS_ESCROW_DESIGN.md
- TON/Gifts integration audit: https://github.com/AzizIo/Vstore/blob/main/docs/ASSET_INTEGRATION_AUDIT.md
- Current order service: https://github.com/AzizIo/Vstore/blob/main/backend/app/orders/service.py
- Payment adapter protocol only: https://github.com/AzizIo/Vstore/blob/main/backend/app/orders/payment.py
- Order DB model/status constraints: https://github.com/AzizIo/Vstore/blob/main/backend/app/db/models.py
- Seller listing lock/revalidation pattern: https://github.com/AzizIo/Vstore/blob/main/backend/app/listings/service.py
- Open fresh-ownership reservation PR at research time: https://github.com/AzizIo/Vstore/pull/34

### Telegram

- Bot Payments API for digital goods / Stars, invoice and successful_payment flow, 10-second pre-checkout response, charge reference and refunds: https://core.telegram.org/bots/payments-stars
- Telegram Bot API refundStarPayment: https://core.telegram.org/bots/api#refundstarpayment
- Telegram webhook secret_token: https://core.telegram.org/bots/api#setwebhook
- Bot Platform Developer Terms, sections 6.2, 6.2.1 and 6.2.2 (Stars-only digital goods, dispute responsibility, irreversibility warning, TPA balance ownership): https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services
- Telegram Mini Apps: https://core.telegram.org/bots/webapps

### TON

- TEP-62 NFT standard, transfer message and unresolved safe-transfer question: https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md
- TON Connect overview: https://docs.ton.org/applications/ton-connect/overview
- TON messages/transactions overview: https://docs.ton.org/foundations/messages/overview
- TON Center API v3 overview (indexed data layer): https://docs.ton.org/ecosystem/api/toncenter/v3/overview

### PSPs

- Adyen for Platforms payment flow, seller balance accounts, splits and settlement delay: https://docs.adyen.com/platforms/quickstart-guide/payments/
- Adyen platform payouts, settlement delay and verified bank payout: https://docs.adyen.com/platforms/quickstart-guide/payouts
- Adyen custom/on-demand payouts: https://docs.adyen.com/platforms/custom-payouts/on-demand-payouts
- Adyen split transactions: https://docs.adyen.com/platforms/online-payments/split-transactions
- Adyen split chargebacks: https://docs.adyen.com/platforms/online-payments/split-transactions/split-chargebacks
- Adyen internal balance transfers: https://docs.adyen.com/platforms/internal-fund-transfers/
- Adyen onboarding and KYC: https://docs.adyen.com/platforms/quickstart-guide/onboarding-and-kyc
- Adyen liable balance accounts and compensation account: https://docs.adyen.com/platforms/manage-liable-accounts/
- Stripe restricted businesses (last updated 2026-09-22): https://stripe.com/legal/restricted-businesses
- MANGOPAY prohibited/restricted businesses (page states last updated 2026-06-24): https://mangopay.com/prohibited-businesses

### EU / Germany / app stores

- BaFin ZAG guidance, including internet-marketplace escrow and use of a licensed payment institution: https://bafin.de/SharedDocs/Veroeffentlichungen/DE/Merkblatt/mb_111222_zag.html
- PSD2, Directive (EU) 2015/2366, Annex I payment services: https://eur-lex.europa.eu/eli/dir/2015/2366/oj/eng
- MiCA, Regulation (EU) 2023/1114, Recitals 10–11, Article 2 and custody/trading-platform provisions: https://eur-lex.europa.eu/eli/reg/2023/1114/oj/eng
- Transfer of Funds Regulation, Regulation (EU) 2023/1113, Article 14 and self-hosted address rules: https://eur-lex.europa.eu/eli/reg/2023/1113/oj/eng
- Anti-Money Laundering Regulation, Regulation (EU) 2024/1624, application date in Article 90: https://eur-lex.europa.eu/eli/reg/2024/1624/oj/eng
- Consumer Rights Directive 2011/83/EU, Articles 9 and 16(m): https://eur-lex.europa.eu/eli/dir/2011/83/oj/eng
- Apple App Store Review Guidelines, section 3.1.1: https://developer.apple.com/app-store/review/guidelines/
- Google Play Blockchain-based Content policy: https://support.google.com/googleplay/android-developer/answer/13607354?hl=en

---

*Research note: official provider/platform/legal pages are time-sensitive. Re-check all sources, fee terms, supported countries, definitions, and contract terms at the time of any future implementation. This proposal is a technical and regulatory issue map, not legal advice or a provider approval.*
