# Kestrel evidence audit

Date: 2026-09-15. Scope: the approved network-design specification and the
four research notes in this directory. This is a source audit, not a review of
benchmark theory. Primary sources were preferred; pages were checked on
2026-09-15.

## High-impact checks

| Claim in the design/research | Finding | Evidence and disposition |
|---|---|---|
| China Spring Festival public holiday is 15–23 February 2026 | **Verified.** | The General Office of the State Council notice specifies a nine-day holiday from 15 through 23 February, with 14 and 28 February as adjusted working days. Replace the Zendrop citation with the [State Council notice](https://en.bjhd.gov.cn/workinginhaidian/supportingservices/publicholidays/202512/t20251211_4797062.shtml) (published 2025-12-11). The factory ramp-down and recovery window remains an industry assumption, not part of the official holiday notice. |
| ISO 2859-1, General II gives a sample of 200 for a 5,000-unit lot | **Plausible, but not verified by the cited primary source.** | [ISO 2859-1:2026](https://www.iso.org/standard/85464.html) (edition 3, published 2026-01) verifies that the standard defines lot-by-lot attribute sampling plans indexed by AQL. Its public page does not expose the paid tables, so it does not substantiate `5,000 → 200` or the acceptance number. The research note's worked number comes from a secondary inspection consultant. Retain it only as a secondary-sourced implementation choice, or check a licensed copy of the 2026 tables. Also revise “AQL is the maximum percent-defective in a lot”: ISO describes AQL as the worst tolerable **process average for a continuing series of lots**, and acceptance sampling has no sharp quality boundary; see ISO's public [ISO 2859-4 explanation](https://www.iso.org/obp/ui#iso:std:iso:2859:-4:ed-3:v1:en). |
| Flat 0% EU duty for Kestrel electronics | **Insufficiently specified.** | The European Commission says duty depends on tariff classification, customs value, and origin; TARIC is updated daily and is the authoritative lookup ([calculation guidance](https://taxation-customs.ec.europa.eu/customs/common-customs-tariff-cct/calculation-customs-duties_en), [TARIC](https://taxation-customs.ec.europa.eu/online-services/online-services-and-databases-customs/eu-customs-tariff-taric_en), current pages checked 2026-09-15). A 0% modelling choice may be reasonable for correctly classified headphones/loudspeakers, but “0% (EU electronics)” is overbroad: electronics do not share one tariff, and the design gives no CN/TARIC codes or origin determination. Label 0% explicitly as a simplifying choice and record assumed codes for EB-STD, EB-PRO, and SPK-1. Import VAT is also separate from TARIC and should be explicitly excluded or modelled as recoverable tax. |
| Baseline ocean on-time probability 0.65 | **Supported as an order-of-magnitude calibration, not a route-specific probability.** | Sea-Intelligence's own data release reports global schedule reliability of 65.3% in August 2025 and an average 4.80-day delay for late arrivals ([release dated 2025-09-26](https://www.sea-intelligence.com/images/press_docs/GLP-Sept2025/20250925_-_Sea-Intelligence_GLP_Press_Release_-_September_2025.pdf)); its [2024 release](https://sea-intelligence.com/press-room/307-2024-schedule-reliability-largely-within-50-55) reports 50–55% through most of 2024. The design converts a global carrier metric into a Shanghai–Rotterdam per-voyage Bernoulli event. Mark that conversion as a calibration choice, and use the reported late-arrival distribution (about five days in the cited release) rather than claiming the source supports exactly `+3 to +10 days`. |
| Five free days followed by €60/day, then €120/day demurrage | **Directionally grounded; exact tariff is a choice.** | The Port of Rotterdam confirms that free-time and demurrage/detention terms materially affect container retrieval and should be agreed with the carrier ([Port guidance](https://www.portofrotterdam.com/sites/default/files/2021-06/inland-container-shipping-guidelines.pdf), 2021). It does not publish the design's five-day allowance or tiered euro rates. Those exact values come from secondary aggregators and old carrier comparisons, so mark the entire tariff schedule as a scenario choice rather than `[freight §3]` fact. |
| Retailer chargebacks: BIGBOX 3% of order value for late/short; MARKET 2/4/6% for late/short | **Misapplied.** | Walmart's public supplier materials verify that ASN and OTIF are real compliance programs ([2024 Supply Chain Packaging Guide](https://corporate.walmart.com/content/dam/corporate/documents/suppliers/requirements/supply-chain-packaging-guide.pdf)), but do not verify the research note's current thresholds or 3% rate. More importantly, the research note says **3% of COGS for violating cases**, while the design changes this to **3% of order value** whenever an order is late or short. The Amazon 2/4/6 tiers are sourced only to a third-party blog and concern ASN accuracy, yet the design applies them to late/short delivery. Keep these as fictional customer contract terms, or implement separate ASN-accuracy and OTIF rules with the cited bases and triggers. |

## Unsupported or misleading carry-through

- “Every number there carries a URL” does not mean each number is established by
  a reliable source. Several exact probabilities and costs are derived from broad
  ranges, blogs, or analogies. Each derived value should be marked `(choice)` at
  its point of use.
- The CNY `15% chance` that a supplier recovers only to `85%` is not established
  by the cited statement that roughly one-third of workers may change employers.
  It is a calibration choice built from a different statistic.
- The `0.08` normal and `0.20` tight container-roll probabilities have no numeric
  support in the freight note. The note supports the causes and a delay of one or
  more sailings, not those probabilities.
- Blank sailings being announced 14–28 days ahead is a narrower conversion of the
  cited 2–6-week range. It is defensible as a choice, but the spec should not imply
  the source fixes that window.
- “Ships and customs run 7 days” is too categorical. Customs availability,
  terminal operations, examination, document release, and onward delivery have
  different calendars. The cited forwarder pages do not establish uninterrupted
  end-to-end customs processing at the design's rate.
- The specification calls component figures “landed component cost” although the
  calculation shown includes BOM purchase price and assembly but omits inbound
  road freight, customs brokerage, and any tax/duty treatment. Call it standard
  component/BOM cost unless those landed-cost elements are included.

## Model-semantics rulings needed

1. Section 6 says no condition reads planner state, but the port queue's
   `arrivals_excess` necessarily depends on bookings and routing actions. Treat the
   queue as operational state updated from physical arrivals, while keeping its
   strike/capacity shock exogenous; otherwise player actions cannot affect port
   congestion and the stated queue equation is not implemented faithfully.
2. COGS should normally be recognized when finished goods are sold/delivered, with
   component and conversion cost capitalized into inventory during production.
   Charging `cogs_components` and `cogs_assembly` as production completes understates
   inventory value and mismatches cost with revenue, distorting gross margin, DIO,
   write-offs, and holding cost. Cash deposits/balances can still post on their
   contractual dates independently of COGS recognition.

## Audit conclusion

The topology and event set are credible for a demonstrator, but the documents
currently overstate source fidelity. The highest-value corrections are to mark
derived calibrations as choices, preserve the cited trigger and basis of retailer
penalties, qualify the 0% duty assumption by product classification, and correct
the AQL definition. None of these requires adding benchmark theory.
