# How a Real Electronics Importer's Procurement Desk Operates

Research notes to ground a realistic supply-chain simulation. Every fact below
carries its source URL. Researched 2026-09-15.

## 1. Purchase order lifecycle

- Core procure-to-pay (P2P) steps: PO creation (items, quantities, pricing, timing) ->
  vendor acknowledgement (vendor accepts PO, prepares shipment, issues delivery note) ->
  goods receipt (items unloaded and checked against PO and delivery note) -> invoice ->
  payment. Source: "P2P Cycle in SAP | Complete Procure to Pay Process Explained",
  https://www.erpvits.com/blog/p2p-cycle-in-sap-complete-procure-to-pay-process/
- Suppliers can optionally send an Order Confirmation or an Advance Shipping Notice
  (ASN) via a supplier network before goods arrive, giving the buyer visibility ahead
  of physical receipt. Source: "Define the Purchase Order Lifecycle" (SAP Learning),
  https://learning.sap.com/courses/managing-purchase-orders-in-sap-ariba-buying-and-invoicing/define-the-purchase-order-lifecycle
- 3-way match cross-references the invoice against the PO and the goods receipt (GR)
  before payment is authorized; any deviation beyond a configured tolerance triggers
  an automatic invoice block, i.e. payment does not happen on invoice alone. Source:
  "How 3-Way Matching in SAP Works: A Quick Guide", https://ramp.com/blog/sap-3-way-match
- Receiving-dock goods receipt updates inventory records and is the point where
  quantity/condition discrepancies against the PO are first detected. Source: "Goods
  Receipt: Definition, Process & 3-Way Matching", https://ramp.com/blog/accounts-payable/goods-receipt

### Payment terms with Asian electronics suppliers

- The dominant first-order structure is **30% deposit (T/T) before production starts,
  70% balance (T/T) before shipment** (or against a copy of the bill of lading).
  Source: "30% Deposit 70% Before Shipment or Against B/L: What Does it Mean?",
  https://www.advantasourcing.com/blog/30-deposit-70-before-shipment
- Rationale for 30/70: Chinese factories typically run on thin margins (often
  5-15%), and for electronics, raw materials/components can be 40-60% of total
  production cost, so the deposit funds material procurement. Source: "30/70 Payment
  Terms Explained", https://www.ihomechinabuy.com/30-70-payment-terms-explained/
- As trust builds, terms can loosen to **0% deposit / 100% after shipment, net
  end-of-month**, and can tighten again if a supplier needs to pre-order specialized
  components 3+ months ahead. Source: "T/T Payment: How to Pay Chinese Suppliers With
  It", https://qualityinspection.org/pay-chinese-suppliers-tt-payment/
- For large-value transactions (commonly cited around >$1M) buyers may use a
  Documentary or Usance (deferred-payment) LC instead of T/T, paying 30-90 days
  after shipment (aligning with Net 30/Net 60 terms); LC is common in Asia trade,
  but over 70% of first LC document presentations contain discrepancies that
  delay payment release. Source: "Letter of Credit (LC) in International Trade",
  https://incodocs.com/blog/letter-credit-lc/

### MOQs and price breaks

- MOQ is the smallest quantity a supplier will sell on one order line; a buyer
  cannot split below it even at the same unit price. Source: "MOQ Meaning: Minimum
  Order Quantity Explained", https://blog.findchips.com/the-meaning-of-moq-understanding-the-critical-role-of-minimum-order-quantity-in-electronic-component-sourcing/
- In wholesale electronics, MOQs range from ~10 units for niche accessories up to
  50,000+ units for mass-market handsets; MOQs of 10,000+ are common across
  electronics generally. Source: "What Is an MOQ? Understanding Minimum Order
  Quantities in Electronics", https://www.kynix.com/Blog/minimum_order_quantity_electronics.html
- Price breaks are step-function marginal-unit-price reductions as order quantity
  rises; lower-quantity buyers pay a higher per-unit price so the supplier still
  clears its target margin. Source: same as above (kynix.com).
- For component-level MOQs specifically, the driver is SMT line setup-time
  amortization (machine programming and changeover cost spread across the batch),
  not arbitrary supplier policy. Source: same as above (kynix.com).

### Lead-time quoting vs actual

- During tight-supply periods, quoted lead times for advanced SoCs/FPGAs have run
  26-52 weeks while actual receipts extended to 40-78 weeks — a real, and
  sometimes doubling, gap between quote and delivery. Source: "Semiconductor Lead
  Times 2026: Quoted vs Actual", https://cosolvic.com/blog/semiconductor-lead-time-reality-2026-quoted-vs-actual/
- Factory-quoted dates can move multiple times before a buyer secures a firm
  allocation; a quoted date is explicitly "not stock." Source: same as above
  (cosolvic.com).
- Under allocation, manufacturers prioritize highest-volume/automotive-grade
  customers (e.g., locked capacity at Infineon, NXP, Renesas, STMicroelectronics),
  leaving industrial/consumer buyers with longer quotes and less certainty even at
  a higher price. Source: same as above (cosolvic.com).

## 2. Incoterms for China -> Europe electronics

- **FOB (Free on Board)** is the most widely used Incoterm for China-origin
  shipments: the seller handles China-side export logistics (customs clearance,
  loading, terminal handling) while the buyer controls and pays for the main
  ocean/air freight, insurance, and import customs; risk transfers once goods pass
  the ship's rail. Source: "All 11 Incoterms explained with real sourcing examples",
  https://www.cosmosourcing.com/blog/incoterms-defined-fob-exw
- **EXW (Ex Works)**: seller only makes goods available at its own premises; buyer
  bears full cost/risk from pickup through export clearance, freight, insurance,
  duties and final delivery. Described as the most buyer-unfriendly term for
  buyers new to sourcing from China (they must self-manage Chinese export
  clearance). Source: "Incoterms Explained: FOB, CIF, EXW and DDP for China
  Shipments", https://chinamakershub.com/journal/incoterms-explained-fob-cif-exw-china
- **DDP (Delivered Duty Paid)**: seller/forwarder carries essentially all costs and
  risks — freight, insurance, and customs clearance/duties — until goods reach the
  buyer. Source: Flexport Help Center, "What Are Incoterms?",
  https://www.flexport.com/help/40-incoterms-guide/
- Only CIF and CIP explicitly assign insurance to the seller by definition; under
  FOB/EXW/DDP it is a negotiated add-on, not a term-defined obligation. Source:
  same as above (flexport.com).

## 3. Supplier risk management

- OTIF (On-Time In-Full) is described as the "gold standard" delivery metric —
  percent of orders delivered both on time and complete; both conditions must be
  met to count. Top-performing companies achieve 95-98% OTIF via integrated
  supply-chain operations and real-time visibility. Source: "On-Time In-Full
  (OTIF): Meaning, Benchmarks, Best Practices", https://redstagfulfillment.com/on-time-and-in-full-otif/
- OTIF is a metric inside the SCOR (Supply Chain Operations Reference) framework,
  now stewarded by ASCM (Association for Supply Chain Management, formed from the
  APICS/Supply-Chain Council merger); SCOR Digital Standard defines 300+ metrics
  at scor.ascm.org. Source: ASCM SCOR Quick Reference Guide,
  https://www.ascm.org/globalassets/documents--files/corporate-transformation/scor-ds-digital-guide_final.pdf
- Supplier scorecards typically combine: delivery (OTIF, lead-time reliability,
  short-ship frequency), quality (PPM defect rate), cost (price stability, TCO),
  responsiveness (issue resolution time), and compliance/ESG (certifications, audit
  findings). Source: "Supplier Performance Scorecard: Automating OTIF & PPM
  Metrics", https://leanlinking.com/guides/srm-software-buyers-guide-supplier-performance-scorecard/
- Recommended monitoring cadence: Tier-1 (high spend/criticality) suppliers
  monitored monthly, Tier-2 quarterly; annual-only review is appropriate only for
  low-spend, easily-replaceable long-tail suppliers; high-risk suppliers get
  quarterly financials or continuous credit-rating alerts rather than waiting for
  the annual cycle. Source: "Supplier Financial Risk Assessment: Key Steps &
  Analysis", https://www.kodiakhub.com/blog/supplier-financial-risk-assessment
- Segmentation approach: combine OTIF with spend volume, criticality, and
  availability of alternative suppliers to prioritize corrective action and set
  differentiated management strategies — the analytic basis for when dual-sourcing
  is worth the premium. Source: "Supplier Scorecards: How to Benchmark Supplier
  Reliability, Quality & ESG", https://www.certaintysoftware.com/supplier-scorecard/
- Supplier onboarding/qualification timeline: end-to-end, from deciding to use a
  new direct-materials supplier to being able to issue a PO, typically runs
  **2-6 months**; simpler cases can qualify in as little as 2 weeks depending on
  risk profile and document readiness. Structured self-service onboarding portals
  can cut supplier activation to under 48 hours versus multi-week email-based
  cycles for the administrative (non-qualification) part of onboarding. Source:
  "Supplier Qualification: Definition, Process, Steps and Guidelines",
  https://www.qcadvisor.com/blog/supplier-qualification/ and "Supplier Onboarding:
  5 Steps to Compliance & Qualification", https://leanlinking.com/guides/supplier-onboarding-process/
- Financial-health assessment draws on financial ratios (e.g., DSCR, current
  ratio, DPO trend), payment behavior data, third-party credit signals (e.g.,
  Dun & Bradstreet business credit scores), and early-warning distress indicators.
  Source: "SMB Solutions: Evaluate Supplier Risk", Dun & Bradstreet,
  https://www.dnb.com/en-us/smb/business-risk/evaluate-vendors.html

## 4. Incoming quality (AQL sampling)

- ISO 2859-1 defines sampling-by-attributes plans indexed by Acceptance Quality
  Limit (AQL); AQL is the maximum percent-defective in a lot still considered
  acceptable. Source: ISO, "ISO 2859-1:2026 — Sampling procedures for inspection by
  attributes", https://www.iso.org/standard/85464.html
- Seven inspection levels: General I (fewer samples; used when a supplier has
  passed most previous inspections), General II (**default**, most widely used),
  General III (used after a supplier had recent quality problems — larger sample),
  and Special S-1 through S-4 (small sample sizes, used when higher sampling risk
  is acceptable, e.g. destructive or costly tests). Source: "How The AQL
  Inspection Levels In ISO 2859-1 Affect Sampling Size",
  https://qualityinspection.org/inspection-level/
- Worked sample sizes from the same source: on a 5,000-unit lot, General I = 80
  pcs, General II = 200 pcs, General III = 315 pcs, S-1..S-4 = 5-32 pcs; on a
  40,000-unit lot, General I = 200 pcs, General II = 500 pcs, General III = 800
  pcs, S-1..S-4 = 8-80 pcs. Source: same as above (qualityinspection.org).
- Common AQL threshold values used in practice: stricter (0-0.65%) for critical
  defects, moderate (1.0-2.5%) for major defects, looser (2.5-4.0%) for minor
  defects; 1.0%, 1.5%, 2.5%, 4.0% are the most commonly quoted AQL percentages.
  Source: "Acceptance Quality Limit (AQL) Guide: Standards and Best Practices",
  https://quality.eleapsoftware.com/glossary/acceptance-quality-limit-aql-guide-standards-and-best-practices/
- Typical achieved defect rates: consumer/"entertainment" electronics commonly
  target under 1,000 DPPM (99.9% good), versus ~20 PPM in automotive; well-run
  turnkey PCB assembly commonly reports under 500 DPPM. Source: "PPM (Parts Per
  Million): Formula, Benchmarks & MES Data", https://www.symestic.com/en-us/what-is/parts-per-million
- On rejection/quality escape: RMA (Return Material Authorization) is the formal
  process for a customer to return defective product to the manufacturer/EMS;
  disposition options are sort (100% inspection to cull defectives), rework, scrap,
  or return-to-supplier; if the No-Fault-Found rate on returns exceeds ~3% for a
  single recurring issue, the EMS provider and OEM jointly investigate root cause
  and corrective action. Source: "Electronics return materials authorization (RMA)
  and product repair strategy", https://ventureoutsource.com/contract-manufacturing/electronics-return-materials-authorization-rma-and-product-repair-strategy/
- Warranty/chargeback cost buckets include parts, labor, logistics, admin
  overhead, and supplier chargeback recoveries — the buyer can claw back some
  defect cost rather than absorbing it all. Source: same RMA source (ventureoutsource.com).

## 5. Chinese New Year (CNY) and Golden Week effects

- CNY 2026 official public holiday: **February 15-23, 2026** (7-9 days is the
  typical statutory range). Source: "Chinese New Year Shutdown 2026: Navigating
  Supply Chain Disruptions", https://www.zendrop.com/blog/chinese-new-year-shutdown/
- Real production disruption is much longer than the statutory holiday: factories
  begin scaling down **3-4 weeks before** the holiday and take **2-4 weeks after**
  to return to full capacity, giving a combined disruption window of roughly
  **6-8 weeks**. Source: "When Factories Close For The Chinese New Year & Shipping",
  https://ship4wd.com/import-guides/when-factories-close-for-the-chinese-new-year
- Shipping-side effect runs on a similar but shifted clock: pre-holiday congestion
  starts ~3 weeks before the holiday as shippers rush to clear orders (freight
  rates and surcharges rise, space gets tight), and post-holiday backlog clearing
  extends ~3 weeks after; overall the shipping effect is felt for roughly **2
  months** (mid-January to mid-March in a February CNY year). Source: same as
  above (ship4wd.com).
- During the 2025 CNY window, transit times from China to the U.S. West Coast
  extended from ~35 days to nearly 40 days as backlogs cleared. Source: "2025
  Chinese New Year Shipping Delays: Essential Guide", https://www.freightamigo.com/en/blog/logistics-news/chinese-new-year-shipping-delays/
- Structural fragility: China dominates PCB and electronic-component manufacturing
  and many buyers are effectively single-sourced with no quick alternative during
  the shutdown, so shortages/delays concentrate here rather than spreading evenly.
  Source: same as above (freightamigo.com).
- Post-holiday labor risk: roughly one-third of factory workers may not return to
  their prior employer after CNY, slowing ramp-up beyond the pure calendar effect.
  Source: "2026 Manufacturing: Tariff Uncertainty & CNY Disruptions",
  https://blog.epectec.com/2026-manufacturing-tariff-uncertainty-and-chinese-new-year-disruptions
- A second, smaller annual disruption is **Golden Week** (China's National Day,
  Oct 1-7, 2026): electronics/semiconductor/auto-parts factories and ports run
  reduced staff, and pressure from late September through mid-October adds
  roughly **2-4 weeks** of extra transit/backlog around the 7-day holiday.
  Source: "China Golden Week 2026: Shipping Effects & Tips",
  https://www.icontainers.com/blog/china-golden-week-shipping-2026/

## Implications for a simulator

- Model payment as a two-part cash outflow tied to production milestones, not a
  single order-time cost: ~30% at order placement (funds supplier's material
  purchase) and ~70% at ship-confirmation (T/T against B/L), with an alternate LC
  path for large orders that delays payment 30-90 days post-shipment but adds
  document-discrepancy delay risk.
- Represent quoted lead time and realized lead time as two separate random
  variables, not one: the gap is bounded by contract/allocation status (routine
  parts stay close to quote; allocated/scarce parts can realize 1.5-2x the quoted
  weeks), and the quote itself should be allowed to revise upward while an order is
  open ("a quoted date is not stock").
- Enforce MOQ as a hard per-SKU order-size floor with a step-function (not
  continuous) unit-price curve — ordering below MOQ should not be representable,
  and per-unit price should drop in discrete bands as order quantity crosses
  thresholds.
- Give every supplier a small number of observable health signals (OTIF history,
  a scorecard-style composite, and an optional slow-moving financial-risk signal)
  that update on a realistic cadence (e.g., monthly/quarterly, not every step), and
  let dual-sourcing be a deliberate cost/latency trade the agent can choose, not a
  free background hedge.
- Give new suppliers a multi-week-to-multi-month onboarding/qualification delay
  before they can receive a first PO — a new sourcing lever should not be usable
  instantly.
- Model incoming inspection as AQL sampling (not 100% inspection): sample size
  scales with lot size and inspection level, acceptance is a c=0 (or similar)
  threshold on sampled defectives, and a failed lot triggers a real
  consequence — sort/rework/return-to-supplier with an associated cost and
  time delay — rather than silently degrading downstream quality.
- Build in a recurring, date-anchored capacity shock for Chinese New Year
  (multi-week ramp-down/up, chance a supplier's capacity doesn't fully recover
  post-holiday) plus a smaller Golden Week shock in October — both distinct from
  ordinary stochastic lead-time noise since they are calendar-predictable and
  should be learnable/plannable by a good policy.
- Track Incoterm choice (FOB vs EXW vs DDP) as a structural decision that shifts
  which cost/risk line items sit on the buyer's books (freight, insurance,
  customs) rather than folding it into a single opaque landed-cost number —
  this is what lets a simulator distinguish "supplier price" from "total cost
  of ownership."
