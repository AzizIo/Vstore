# Platform policy research: TON NFT secondary resale in Telegram Mini Apps

- **Research date:** 2026-11-10
- **Scope:** Public first-party policy text only; no legal opinion and no platform approval
- **Product model assessed:** VILTARA SHOP is a third-party Telegram Mini App; users connect their own TON wallets; a seller lists an already-existing TON NFT; a different user pays the seller/platform and the NFT is transferred to the buyer (peer-to-peer secondary resale).
- **Status:** Research finding — classification unresolved; do not treat as clearance to launch payments
- **Repository issue:** [#39](https://github.com/AzizIo/Vstore/issues/39)

## 1. Executive conclusion

**Conclusion: public policies do not conclusively classify VILTARA's exact transaction. Confidence: high that the question remains unresolved; medium-high on the risk interpretation below.**

The policies establish three important facts:

1. **Apple's App Review Guidelines expressly cover NFT-related services** such as minting, listing and transferring. They also restrict calls to action leading to non-IAP purchase mechanisms in App Store apps, subject to storefront/entitlement exceptions. The text does not expressly carve out peer-to-peer resale of an existing NFT from these rules.
2. **Google Play's rules require Play Billing for in-app purchases of digital content**, and its blockchain policy covers tokenized digital assets. Google's official FAQ specifically says that if an NFT is used for an in-app purchase of digital content, Play Payments policy applies. It does not expressly settle whether a wallet-to-wallet secondary sale of an existing TON NFT through a third-party Telegram Mini App is such a purchase.
3. **Telegram's Bot Developer Terms §6.2 and official Bot Payments API guidance make Stars mandatory for covered digital goods/services transactions inside Telegram.** The Payments API FAQ explicitly says an external website or provider does not remove the Stars requirement and cryptocurrency cannot replace Stars for covered in-Telegram sales. Telegram also warns against real-time sales of valuable virtual items that cannot be reclaimed after a successful dispute/chargeback. The unresolved issue is whether this exact P2P secondary TON NFT resale is a covered transaction.

Therefore, it would be unjustified to conclude either “all TON NFT resales must definitely use Stars” or “secondary resale is exempt.” The safest current product decision is **no paid purchase flow until Telegram confirms the classification and permitted UX/payment path in writing**. **If §6.2 applies, Stars are mandatory for the in-Telegram transaction; Telegram's official Payments API FAQ says an external website/provider or cryptocurrency is not an alternative.** The remaining uncertainty is classification of this exact wallet-to-wallet secondary NFT resale, not whether external checkout can bypass Stars for a covered transaction.

This is a policy interpretation, not legal advice and not a guarantee of Apple, Google or Telegram approval.

## 2. The exact product boundary matters

The assessed flow is not NFT minting, not a game reward, not a transfer of an NFT already owned by the buyer, and not a native standalone VILTARA iOS/Android app. It is a third-party Mini App hosted by Telegram, showing a seller's existing NFT and coordinating a paid secondary sale between two users who control their own TON wallets.

That creates two separate classification questions:

- **What is being purchased?** The NFT itself / a blockchain token, or a service that facilitates a transfer between users.
- **Where is the purchase facilitated?** Inside a third-party Telegram Mini App, which is displayed by the Telegram iOS/Android client, or on an independently accessed website with no purchase CTA inside Telegram.

A user's ability to sign a TON transaction in their own wallet does not by itself change the nature of the commercial transaction. Nor does calling the transfer “P2P” prove that it is exempt from digital-goods rules.

## 3. Comparison table

| Topic | Apple App Store policy | Google Play policy | Telegram Bot Platform |
|---|---|---|---|
| NFT classification | Guideline 3.1.1 expressly discusses NFT minting, listing, transferring and viewing. | Blockchain-based content policy defines covered content as tokenized digital assets secured on a blockchain. | §6.2 covers digital goods/services and defers the relevant definition to Apple/Google. |
| Secondary resale explicitly named? | No explicit P2P-secondary-resale carve-out found in the reviewed public text. | No explicit P2P secondary-sale classification found in the reviewed public text. | No explicit TON NFT secondary resale example found in §6.2. |
| Payment rule | Digital purchases generally use IAP, subject to applicable exceptions/programs. NFT-related services may use IAP; external purchase CTAs are restricted by storefront and entitlement rules. | Play Billing applies to in-app digital goods/content unless an exception/program applies. NFT purchases used for digital content fall under this rule. | If classified as a digital-goods/services transaction pertaining to the TPA, §6.2 says Stars exclusively; third-party PSP processing is prohibited for that transaction. |
| External checkout link | Depends on storefront, entitlement/program and exact CTA; outside-US rules differ from US storefront and certain regional programs. No global permission can be assumed. | Alternative payment links/CTAs are generally restricted unless a policy program or regional exception applies. Google says a Play-managed host app facilitating covered purchases must comply across implementations, including third-party embedded app experiences/plugins. | If a sale is covered digital goods/services inside Telegram, Stars are required regardless of external websites/providers; crypto is not an alternative. Whether this particular NFT resale is covered remains unresolved. |
| No-money listing/transfer coordination | No sale removes the immediate purchase-payment question, but NFT listing/transfer UX can still fall within guideline 3.1.1 and review discretion. | No payment means the billing requirement may not be triggered, but blockchain content, financial feature and general app policies still need assessment if it is a Play-distributed app. | §6.2's sale/payment rule is less directly implicated if there is genuinely no sale/payment; other Bot Developer Terms still apply. |
| Can public text alone clear VILTARA? | No. Apple's direct App Review obligations attach to App Store-distributed apps, including Telegram's iOS host app; public text does not expressly adjudicate this exact embedded P2P NFT flow. | No. Google Play's Payments policy directly governs Play-distributed host apps such as Telegram. Its FAQ says covered purchases facilitated by a Play-managed app must comply across implementations, including third-party embedded experiences/plugins; embedding alone is not an exemption. The NFT resale classification remains unresolved. | Telegram's contractual TPA terms apply to VILTARA. If §6.2 covers the transaction, Stars are mandatory and external web/crypto payment is not a workaround; exact P2P NFT classification remains unresolved. |

## 4. Verified policy text vs interpretation vs unknowns

### 4.1 Apple

**Verified text — App Review Guidelines, §3.1.1, “In-App Purchase”**

The current guideline says apps may use IAP to sell NFT-related services “such as minting, listing, and transferring.” It permits viewing owned NFTs provided ownership does not unlock in-app functionality. For browsing NFT collections owned by others, it restricts buttons, external links or other calls to action directing customers to non-IAP purchase mechanisms outside the US storefront, subject to the guideline's applicable exceptions.

Source: https://developer.apple.com/app-store/review/guidelines/  
Section: 3.1.1, including 3.1.1(a) “Link to Other Purchase Methods”.  
Accessed: 2026-11-10.

**Interpretation**

- The explicit inclusion of listing and transferring means it is unsafe to assume an NFT marketplace is outside the scope merely because the token already exists or the transaction is secondary.
- The text says an app *may use* IAP for NFT-related services; read together with the general IAP and external-link provisions, it does not establish a universal secondary-market exemption.
- A TON Connect wallet signature is not an Apple IAP transaction. If a separately submitted iOS app sold NFT-related digital goods/services, a wallet transaction alone would not demonstrate compliance with §3.1.1.
- VILTARA itself is a web Mini App rendered within Telegram's iOS client, not a standalone VILTARA binary submitted to App Review. Apple's app review obligations directly attach to the app developer/distributor, but Telegram's Bot Developer Terms explicitly instruct TPA developers to follow Apple's and Google's definitions. Public text does not answer how Apple expects Telegram to treat a third-party Mini App's P2P NFT marketplace in every storefront.

**Unknowns**

- Does Apple classify a user-to-user sale of an existing TON NFT through a third-party Telegram Mini App as a digital-goods purchase for purposes of the Telegram host app?
- Are the relevant Mini App listing and buy CTA permitted in all storefronts, and if not, what exact storefront/entitlement restrictions apply to Telegram?
- Does Apple distinguish a wallet-to-wallet NFT asset sale from the sale of an app service that facilitates the transfer in this host-app context?

The Apple guideline page was reachable in search results, but direct page opening timed out during this research. The policy wording above was checked against the first-party search-indexed guideline text and Apple-hosted guideline content; this access limitation means the exact live page should be rechecked before launch.

### 4.2 Google Play

**Scope distinction: host app vs third-party Mini App**

Google Play's Payments policy directly governs apps distributed through Google Play, including the Telegram Android host app. VILTARA is third-party content running inside that host app, not itself the Play-distributed binary in this architecture. Google's official FAQ nevertheless says a Play-managed app facilitating a covered digital purchase must comply across implementations, including transactions initiated inside a third-party embedded app experience or plugin. Thus the embedded Mini App boundary is not an exemption if Telegram is considered to facilitate a covered purchase. This still does not determine whether this P2P secondary NFT resale is a covered digital-content purchase.

**Verified text — “Blockchain-based Content”**

Google defines blockchain-based content for the policy as tokenized digital assets secured on a blockchain. If an app sells or enables users to earn such assets, it must make the required Financial features declaration and mark in-app products as tokenized digital assets. The policy also includes transparency requirements and restrictions related to NFT gamification.

Source: https://support.google.com/googleplay/android-developer/answer/13607354?hl=en  
Section: “Blockchain-based Content”, including “Transparency Requirements for Distributing Tokenized Digital Assets”.  
Accessed: 2026-11-10.

**Verified text — “Understanding Google Play's Payments policy”**

Google says Play Billing is required for in-app purchases of digital goods and services distributed on Play, and its NFT FAQ states: “If the tokenized digital assets are used for in-app purchases of digital content” then Play Payments policy applies. It also says in-app links leading to alternate payment methods are generally prohibited unless a stated policy exception/program applies. The page describes regional programs/conditions, including the EEA and US, rather than a universal external-checkout exemption.

Source: https://support.google.com/googleplay/android-developer/answer/10281818?hl=en  
Sections: opening summary; FAQ “Can I communicate with my users about alternative ways to pay?”; FAQ “My app offers in-app purchases of tokenized digital assets, like NFTs”.  
Accessed: 2026-11-10.

**Interpretation**

- TON NFTs fall naturally within Google's broad “tokenized digital assets secured on a blockchain” definition.
- The policy's digital-content condition matters: the reviewed text does not conclusively decide whether a P2P sale of an existing NFT is a purchase of digital content in the relevant app-policy sense, or a user-to-user asset transfer facilitated by an embedded Mini App.
- Google's official Payments policy FAQ says a Play-managed app facilitating a purchase of digital goods, services, content, features or functionality must comply across implementations, explicitly including transactions initiated inside a third-party embedded app experience or plugin. If Telegram is considered to facilitate a covered purchase, embedding VILTARA is not by itself an exemption. The FAQ still does not expressly classify this exact P2P secondary TON NFT resale.
- Google's direct policy target is the app distributed through Play. In this model Telegram is the Play-distributed app; VILTARA is third-party content running within it. The exact allocation of policy responsibility and the allowed payment flow for this architecture is not expressly resolved by the public NFT FAQ.

**Unknowns**

- Does Google treat the Telegram Android client as facilitating a digital-content purchase when a third-party Mini App coordinates a wallet-to-wallet P2P resale of an existing TON NFT?
- Does the answer differ if the Mini App only lists assets and opens a separate browser, versus showing a purchase CTA and coordinating delivery inside Telegram?
- Which current regional billing/link programs, if any, can Telegram rely on for this flow, and are they applicable to third-party Mini Apps rather than the Telegram client developer's own purchases?

### 4.3 Telegram

**Verified text — Bot Platform Developer Terms, §6.2, “Digital Goods and Services”**

Telegram states that transactions for digital goods and services cannot be processed through third-party payment providers and “all transactions pertaining to digital goods and services must be executed exclusively through the exchange of Telegram Stars.” It then says Telegram must adhere to Apple's and Google's definitions of digital goods and services and directs TPA developers to those policies.

Section 6.2.1 says the TPA purveyor must ensure goods are delivered as advertised, must address disputes, must support `/paysupport`, and can refund Stars in full. It expressly discourages real-time sales of digital products/virtual items with inherent value that cannot be reclaimed, frozen, rescinded, invalidated or suspended following a successful dispute/chargeback. Section 6.2.2 says Stars in the TPA balance are owned by Telegram, not the developer. Section 6.2.4 notes rewards are processed by Fragment, may be delayed up to 21 days, and may be unavailable in some countries.

Source: https://telegram.org/tos/bot-developers  
Sections: 6.2, 6.2.1, 6.2.2, 6.2.4.  
Accessed: 2026-11-10.

**Verified text — Bot Payments API for Digital Goods and Services**

Telegram's official Payments API FAQ states that a bot or Mini App selling digital goods/services inside Telegram must use Stars regardless of other websites, apps, services or payment providers outside Telegram. It also says cryptocurrency cannot be accepted instead of Stars for covered digital goods/services inside Telegram apps. The page states that these sales must be carried out exclusively in Stars and warns that Telegram may not display a bot or Mini App to mobile users if it attempts to sell covered goods through other currencies or third-party providers.

Source: https://core.telegram.org/bots/payments-stars  
Sections: “Can I use a different currency or payment provider?”, “I run my own website to process sales…”, and “Can I accept payment in cryptocurrency instead of Telegram Stars?”  
Accessed: 2026-11-10.

**Interpretation**

- If Telegram classifies VILTARA's P2P resale as a digital-goods transaction pertaining to the TPA, Stars-only applies even if the asset transfer itself is signed by users through TON Connect. The official Payments API FAQ explicitly rules out an external website/provider or cryptocurrency as a substitute for Stars for that covered in-Telegram sale.
- The real-time sale warning is directly relevant to a valuable NFT transfer that cannot be reversed after a successful buyer dispute. Stars checkout alone does not make an irreversible delivery model acceptable.
- A seller-to-buyer transaction does not automatically escape §6.2 because the platform calls itself a “marketplace” or “P2P”. The key question is whether the transaction pertains to digital goods/services in the TPA under the store definitions.
- Conversely, public text does not explicitly name existing TON NFT secondary resale. Applying Stars conclusively without platform interpretation would exceed the evidence.

**Unknowns**

- Whether this exact P2P resale is a §6.2 digital-goods transaction.
- Whether Telegram permits a listing/coordination Mini App with no payment, and what restrictions apply to its buy CTA.
- Whether any separately operated web checkout can be linked or promoted from the Mini App for this model. No public source reviewed establishes that an external site is a permitted workaround when the underlying transaction is within §6.2.

## 5. Allowed / prohibited / conditional / unresolved

These labels refer only to the public policies reviewed, not a guarantee of approval.

### Clearly supported by the reviewed text
- A no-payment catalog/listing experience does not itself execute a purchase payment; it avoids the immediate question of which payment rail processes a sale.
- A Mini App may use Telegram's supported Mini App web-app interface; Mini App technology itself is not prohibited by the sources reviewed.
- Users may connect their own wallet for legitimate blockchain interaction, subject to all applicable app/platform policies and product permissions.

### Clearly prohibited if the relevant condition applies
- Processing a digital-goods/services transaction pertaining to the Telegram TPA through a third-party PSP, if §6.2 applies.
- Treating TON Connect as a way to bypass Telegram's Stars rule for a purchase Telegram classifies under §6.2.
- In a Play-distributed app, leading users to a prohibited alternative digital-goods payment route absent an applicable policy exception/program.
- In an App Store app, directing customers to a non-IAP purchase mechanism where §3.1.1's restriction applies and no applicable storefront/entitlement exception exists.
- Claiming that Telegram's Stars balance is VILTARA's property or that Fragment provides a seller-by-seller marketplace payout API.

### Conditional
- Apple IAP or Google Play Billing may be relevant if the purchase is classified as an in-app digital-goods/content transaction and the relevant store policy applies to the host app.
- External purchase links may be permitted only in specific storefronts/regions or under program/entitlement conditions. Eligibility belongs to the relevant app developer and cannot be presumed for VILTARA.
- A separately operated website may have a different payment-policy context if the purchase genuinely occurs independently outside the app, but linking to it or steering Mini App users to it can itself be restricted. It is not a workaround by default.

### Unresolved — blocks paid launch
- Classification of P2P resale of an already-existing TON NFT in a Telegram Mini App.
- Whether Telegram will permit Stars checkout for this asset class despite its irreversible-delivery warning, and what dispute model it expects.
- Whether Telegram permits any specific external-web checkout journey from this Mini App. For a transaction covered as digital goods/services inside Telegram, the Payments API FAQ rules out external websites/providers and crypto as substitutes for Stars; the exact transaction classification and any genuinely independent off-platform activity remain to be clarified.
- Whether the iOS and Android Telegram clients apply different UX restrictions by storefront, region, distribution channel or app version.

## 6. Consequences for product options

| Product option | Current assessment | Practical next step |
|---|---|---|
| **A. No-money listing and transfer coordination** | Lowest payment-policy risk; not a guarantee that all listing/transfer UX is approved. No checkout, commission, escrow fee or payment CTA. | Reasonable research/prototype path. Clearly state there is no payment protection and no escrow. Avoid suggesting that listing equals sale approval. Ask Telegram whether a non-monetized P2P NFT listing/transfer Mini App is allowed. |
| **B. Stars checkout in Mini App** | **NO-GO pending written confirmation.** Stars is mandatory if §6.2 classification applies, but Stars does not solve the warning about valuable irreversible virtual items or seller settlement. | Ask Telegram to classify the exact flow and confirm permitted UX, refund/dispute requirements and whether paid irreversible NFT delivery is acceptable. Do not build live checkout before the answer. |
| **C. Separately operated web checkout** | **Not an in-Telegram workaround if the transaction is covered.** Telegram's official Payments API says Stars are required for digital goods/services sold inside Telegram regardless of external websites/providers. A genuinely independent off-platform transaction is a separate question, not clearance to steer Mini App users to it. | Do not build a website link/CTA as a way around Stars. Ask Telegram whether any genuinely independent web flow is permitted and what linking/promotion restrictions apply; obtain PSP underwriting approval. Review the host app's store rules. |
| **D. TON Connect direct transfer/payment in Mini App** | **Do not use as a payment-policy workaround.** A wallet signature changes the technical rail, not necessarily the classification of the purchase. | Keep wallet connection for non-purchase operations (e.g. proving wallet control) until classification is confirmed. Separate the NFT transfer from any paid checkout in the product spec. |

A non-monetized MVP should not imply guaranteed delivery, custody, escrow, seller payout, refunds or buyer protection. If it provides only listings and user-to-user coordination, document that clearly and avoid collecting money or a marketplace fee until the classification is settled.

## 7. Exact written-confirmation questions

### First priority: Telegram (Bot Platform support / official developer contact)

Send the following question with a sequence diagram and screenshots of the proposed Mini App:

> VILTARA SHOP is a third-party Telegram Mini App. A seller lists an already-existing standard TON NFT (TEP-62) held in their own TON wallet. Another Telegram user selects “Buy”; the seller and buyer connect their own wallets; the buyer pays the agreed price and the seller transfers that NFT directly to the buyer's wallet. VILTARA does not mint the NFT and does not grant in-app functionality based on NFT ownership. Does Telegram classify this exact peer-to-peer secondary sale as a “digital goods and services” transaction under Bot Developer Terms §6.2, requiring Telegram Stars? Does the answer change if VILTARA only lists the NFT and coordinates a wallet-to-wallet transfer without collecting payment or commission? If §6.2 applies, we understand the official Bot Payments API FAQ requires Stars regardless of an external website/provider and does not permit cryptocurrency instead of Stars for the in-Telegram transaction. Is any genuinely independent off-platform transaction permitted, and may the Mini App link to or promote it? Finally, does §6.2.1's warning against real-time sales of valuable, irreversible virtual items mean this paid TON NFT transfer model is not permitted even if Stars are used? Please identify the applicable rules and any required restrictions.

Request a written answer that distinguishes iOS Telegram, Android Telegram and Telegram Desktop/Web where applicable.

### Apple (if Telegram directs the developer to Apple)

> For an App Store-distributed Telegram client that hosts a third-party Mini App, how should App Review Guideline 3.1.1 be applied when that Mini App facilitates a user-to-user secondary sale of an existing TON NFT via wallet-signed transfer? Is the sale treated as an in-app digital-goods purchase, and what purchase mechanism or CTA restrictions apply by storefront? Does the answer differ when the Mini App only lists/coordinates transfer and does not process payment? We are not submitting a standalone VILTARA native app; please address the embedded Mini App / host-app case.

### Google Play (if Telegram directs the developer to Google)

> For the Play-distributed Telegram Android client hosting a third-party Mini App, does Google Play's Payments policy apply to a P2P secondary sale of an existing TON NFT (TEP-62) where two users sign their own TON wallet transactions? Is this considered an in-app purchase of digital content under the NFT FAQ, or a peer-to-peer asset transfer? What payment/CTA restrictions apply when the Mini App itself does not receive funds but coordinates the transaction? Please address embedded third-party Mini Apps and applicable regional programs explicitly.

A generic answer that “NFTs are digital assets” is not enough; the unresolved point is the purchase classification and the host-app/Mini-App boundary. If §6.2 applies, please confirm that Stars are required and external web/crypto payment cannot be used for the in-Telegram transaction.

## 8. Research limitations

- This report relies on official public policy text available on 2026-11-10. Policies and regional programs change; re-check before release.
- Apple's official guideline page was discoverable in first-party search results, but direct opening timed out in this research session. The relevant guideline text was available in Apple's search-indexed content and Apple-hosted policy page results. Recheck the live page and storefront-specific terms before implementation.
- Public policy pages are not an individualized ruling for VILTARA's product architecture.
- No private communication with Telegram, Apple or Google was available or conducted. No written approval has been received.
- This report does not analyze jurisdiction-specific law, payment-provider underwriting, custody/escrow licensing, taxes, or consumer law; those remain separate workstreams.
- The fact that VILTARA currently runs as a web Mini App and is not itself a native app-store submission is relevant, but it does not automatically exempt the Telegram host app or the TPA from their respective rules.

## 9. First-party sources

1. **Telegram Bot Platform Developer Terms of Service**, §6.2, §6.2.1, §6.2.2, §6.2.4 — https://telegram.org/tos/bot-developers
2. **Apple App Review Guidelines**, §3.1.1 “In-App Purchase” and §3.1.1(a) “Link to Other Purchase Methods” — https://developer.apple.com/app-store/review/guidelines/
3. **Google Play: Blockchain-based Content** — https://support.google.com/googleplay/android-developer/answer/13607354?hl=en
4. **Google Play: Understanding Google Play's Payments policy**, including the NFT FAQ, alternative-payment-link FAQ and third-party embedded-experience FAQ — https://support.google.com/googleplay/android-developer/answer/10281818?hl=en
5. **Telegram Bot Payments API for Digital Goods and Services**, including the official FAQs on external websites and cryptocurrency — https://core.telegram.org/bots/payments-stars
6. **Telegram Mini Apps documentation** — https://core.telegram.org/bots/webapps

## 10. Recommendation for ADR-0002

ADR-0002 should not state as a settled fact that all existing TON NFT secondary sales in a Telegram Mini App must use Stars, nor that secondary resale is exempt and can use an external PSP. It should record:

- **Policy status:** unresolved pending written Telegram interpretation.
- **Interim release gate:** no paid purchase flow; no external-checkout link/CTA designed as a Stars workaround.
- **Fallback product:** non-monetized listing/transfer coordination only, with accurate disclosures and no claims of escrow or guaranteed delivery.
- **Stars candidate:** revisit only after Telegram confirms classification and confirms how its irreversible-asset dispute warning applies.
- **External web checkout:** revisit only after explicit platform guidance and PSP underwriting; separate hosting alone is not sufficient proof of compliance.
