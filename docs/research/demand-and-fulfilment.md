# Demand Planning, Inventory, and Fulfilment: Grounding for a Consumer-Electronics Distributor Simulation

Research pass for grounding a realistic simulation of a mid-size consumer-electronics
distributor/importer. Every fact below carries its source. Numbers come from industry
benchmark aggregators, vendor documentation, and practitioner guides (WebSearch, September
2026) rather than primary academic studies in most cases — treat magnitudes as
"industry-typical ballpark," not precise ground truth, and prefer ranges over point
estimates when calibrating the simulator.

## 1. Forecasting reality

- Consumer electronics forecasters target roughly 60–70% forecast accuracy at the
  SKU/channel level, i.e., a MAPE-equivalent error of 30–40% — well below the higher accuracy
  achievable in stable/staple categories. Source: [Forecast Accuracy Statistics: 2026
  Benchmarks & Trends](https://xorosoft.com/forecast-accuracy-statistics/).
- Forecast error is not flat across horizon: each additional month of forecast horizon
  tends to add roughly 2–5 points of WAPE, so a 1-month-ahead forecast is materially more
  accurate than a 6- or 12-month-ahead one. Source: [Forecast Accuracy by Product | Supply
  Chain & Logistics Playbook](https://umbrex.com/resources/company-analysis/supply-chain-logistics/forecast-accuracy-by-product/).
- Forecast performance should be tracked by SKU × channel × horizon, not as one company-wide
  number, because predictability varies by product lifecycle stage, volume, seasonality,
  lead time, promotion intensity, and customer concentration. Source: [How Do Companies
  Measure Forecast Accuracy?](https://www.onepint.ai/insights/how-do-companies-measure-forecast-accuracy).
- MAPE is unstable at low-volume/near-zero actuals (a forecast of 27 vs. actual of 3 gives an
  800% error) and penalizes over-forecasting asymmetrically; WAPE (volume-weighted absolute
  percentage error) is the more common operational metric because it doesn't let low-volume
  SKUs distort portfolio-level accuracy. Source: [How to Calculate Forecast Accuracy Using
  MAPE, WAPE, and Bias](https://xorosoft.com/forecast-accuracy-mape-wape-bias/).
- Forecast Value Added (FVA) is the standard diagnostic for whether a forecasting process
  step (statistical model, planner override, sales input) improves accuracy versus a naive
  benchmark (e.g., "last period's actual = this period's forecast"); a positive step is
  retained, a zero-or-negative one is process waste to eliminate. Source: [What Is Forecast
  Value Added (FVA)? | IBF.org](https://ibf.org/knowledge/glossary/forecast-value-added-fva-131).
- Best-in-class forecasters (~72% accuracy) capture ~28% promotion gross-margin uplift on
  average, vs. <7% for laggards (~42% accuracy) — accuracy and promo profitability are
  strongly linked. Source: [Enhancing Demand Forecasting in Retail... Journal of Forecasting
  2026](https://onlinelibrary.wiley.com/doi/10.1002/for.70039?af=R).
- A representative promo elasticity example: a 20% price cut on a leading SKU can generate a
  ~35% unit lift in that category — a rough order of magnitude for a "single-digit-percent
  price cut → roughly proportionally larger unit uplift" relationship used in planning tools.
  Source: [Forecasting Trade Promotions vs. Forecasting Sales | Vividly](https://www.govividly.com/forecastingplaybook/understanding-forecasting/forecasting-trade-promotions-vs-forecasting-sales-for-cpg-brands).
- Promotion lead time is a configurable planning parameter (how many weeks ahead of an event
  promoted inventory must be pre-positioned to give stores/DCs time to build displays); many
  retailers still forecast without the promo calendar as a structural input and instead
  manually overlay it late, which is called out as a bias-inducing anti-pattern. Sources:
  [RELEX Solutions: promotion forecasting and replenishment](https://www.relexsolutions.com/resources/promotion-forecasting-and-replenishment/),
  [Cognira: Retail forecasting guide](https://cognira.com/guide/retail-forecasting-what-every-retailer-needs-to-know-to-plan-smarter/).
- Seasonality magnitude: Black Friday electronics sales can run >450% above October-average
  daily volume, and European Black Friday order rates peaked at 11.4 orders/second, a 205%
  jump over normal periods; November/December are consistently the two highest-volume retail
  months of the year. Sources: [25 Black Friday Statistics 2025 | Printful](https://www.printful.com/blog/black-friday-statistics),
  [Confiz: best and worst months for retail sales](https://www.confiz.com/blog/best-and-worst-months-for-retail-sales/).
- Back-to-school/back-to-college is a second major electronics seasonal peak, with
  projected 2025-class spend of ~$23.2B (college) and ~$15.2B (K-12 school) in the US alone,
  much of it electronics, laptops, and accessories. Source: [eMarketer: back to school
  season](https://contentstorage-na1.emarketer.com/069c11e63604a9ae089e9bbf0cd165c1/_What_back_to_school_season_tells_us_about_upcoming_holiday_retail_trends_eMarketer.pdf).
- Product lifecycle follows the classic 5-stage curve (introduction → growth → maturity →
  decline → termination); consumer electronics products have compressed lifecycles relative
  to other categories and are frequently designed with planned obsolescence baked in, and
  new-product forecasts at introduction are inherently low-confidence due to sparse
  historical data (planners lean on lookalike/analog product launches). Sources: [ToolsGroup:
  Product forecasting over the lifecycle](https://www.toolsgroup.com/blog/forecasting-over-the-product-lifecycle/),
  [RSP Inc: Product Lifecycle Management & Technology's Impacts](https://www.rspinc.com/blog/electronics/product-life-cycle/).
- End-of-life inventory is cleared via markdown pricing (progressive price cuts on remaining
  stock over a defined window) rather than being carried at full price indefinitely. Source:
  [The inventory planner's guide to managing product life cycle | EazyStock](https://www.eazystock.com/blog/the-inventory-planners-guide-to-managing-product-life-cycles/).

## 2. Inventory policy practice

- The standard statistical safety-stock formula is **SS = Z × σ_d × √LT**, where Z is the
  service-level z-score, σ_d is the standard deviation of daily demand, and LT is lead time
  in days (lead-time variability terms are added in more complete formulas). Source: [Safety
  Stock: Service Level Calculation Formulas | MetricGate](https://metricgate.com/blogs/safety-stock-service-level-calculation/).
- Common service-level → Z-score mappings used by planners: 90% → 1.28, 95% → 1.65,
  97.5% → 1.96, 99% → 2.33. Source: [Safety Stock Formula | Pallite Group](https://pallitegroup.com/us/news/safety-stock-formula/).
- ABC classification is the standard way service-level targets are differentiated by SKU
  importance: a common tiering is A-items ~99%, B-items ~95%, C-items ~90%, because
  safety-stock cost rises non-linearly toward the upper tail of the service-level curve —
  holding every SKU at 99% destroys working-capital efficiency. Source: [Safety Stock:
  What It Is & How to Calculate | NetSuite](https://www.netsuite.com/portal/resource/articles/inventory-management/safety-stock.shtml).
- MRP/reorder-point systems raise "action messages" (exception reports) that tell a planner
  to expedite, delay, cancel, or change the quantity of an existing order; the planner's job
  is fundamentally exception-driven review and override of these system-generated
  recommendations, not manual scheduling from scratch. Source: [MRP (Material Requirements
  Planning): Complete Guide | RMDB by User Solutions](https://usersolutions.com/blog/mrp-material-requirements-planning-guide);
  APICS/ASCM traces MRP's origin to Joe Orlicky in the 1960s, superseding pure
  reorder-point/EOQ methods. Source: [Wikipedia: Material requirements planning](https://en.wikipedia.org/wiki/Material_requirements_planning).
- Min-max planning (reorder when on-hand hits a minimum; order up to a maximum) is a simpler,
  still widely used alternative/complement to full statistical reorder-point planning,
  especially for lower-tier (B/C) SKUs. Source: [Oracle: Using Product Master Data
  Management](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/25d/fapim/item-planning-attributes.html).
- Backorder vs. lost-sales modeling choice tracks customer type: B2B/contract/high-price
  orders are typically modeled as backorders (demand is captured, fulfilled later), while
  fast-moving retail/impulse purchases are modeled as lost sales (the customer buys
  elsewhere immediately). B2B firms generally sustain higher initial fill rates and fewer
  backorders than B2C. Source: [Backorder vs. Out of Stock: How to Prevent Profit Loss](https://www.inventory-planner.com/backorder-vs-out-of-stock/).
- Walmart OTIF (On-Time In-Full) targets: prepaid suppliers must hit 90% on-time / 95%
  in-full; collect suppliers (Walmart-arranged freight) must hit 98% collect-ready / 95%
  in-full. Miss the combined threshold and Walmart charges **3% of COGS** for cases in
  violation — concretely, a supplier shipping $50,000/week that misses OTIF by 10% can lose
  ~$1,500/week (~$78,000/year). New suppliers get a 3-month grace period. Source: [Walmart
  OTIF Requirements: Avoid Fines & Penalties 2026 | Orderful](https://www.orderful.com/blog/walmart-otif).
- Amazon Vendor Central applies tiered ASN (Advance Shipment Notice) accuracy chargebacks:
  2% of product cost if ASN accuracy is >95% compliant, 4% if 70–95%, 6% if <70%; separate
  per-unit fees apply for prep/packaging non-compliance (e.g., $0.85/unit for a bagging
  violation), and vendors get 30 days with only 2 dispute attempts per chargeback. Source:
  [Amazon Vendor Central: All About Chargebacks And Deductions](https://blog.inymbus.com/amazon-vendor-central-all-about-chargebacks-and-deductions).
- Fill rate (% of demand immediately satisfiable from stock) is the standard
  customer-facing service metric distinct from cycle service level (probability of no
  stockout during a replenishment cycle); both are used but fill rate maps more directly to
  "did the order ship complete." Source: [Cycle Service Level vs Fill Rate Calculator |
  MetricGate](https://metricgate.com/docs/service-level-fill-rate/).

## 3. Customer-side mechanics

- Component/inbound lead times for consumer electronics run wide: standard components
  6–12 weeks, semiconductors in tight markets 12–26+ weeks, and general consumer-electronics
  components commonly cited at 30–90 days — this is the upstream lead time a distributor's
  own MRP has to plan against, distinct from the outbound lead time promised to retail
  customers, which can be as short as 4–6 days for in-stock reorders. Sources: [Umbrex:
  Supplier Lead Time Guide](https://umbrex.com/resources/company-analysis/supply-chain-logistics/supplier-lead-time/),
  [NetSuite: Delivery Lead Time Defined](https://www.netsuite.com/portal/resource/articles/inventory-management/delivery-lead-time.shtml).
- When supply is short, allocation methods split into (a) **fair share** — pro-rata
  allocation by historical/forecast volume share (e.g., a customer that normally takes 60%
  of volume gets 60% of a shortfall-constrained shipment) used when there's no other
  prioritization basis, and (b) **priority-based allocation** — contract customers first,
  then proportional allocation within remaining priority tiers; "fair and reasonable"
  allocation case law/practice recognizes contract-customer priority, prior-year purchase
  share, order-timing (first-come), and downstream criticality as legitimate tie-breakers.
  Source: [Inventory allocation methods: models, formulas, and best practices](https://www.cleverence.com/articles/for-business/inventory-allocation-methods-4829/),
  [Business Disruption in a Pandemic: Allocating Limited Supply | Crowell & Moring](https://www.crowell.com/en/insights/client-alerts/business-disruption-in-a-pandemic-allocating-limited-supply).
- Expedite requests are triggered by system-generated "expedite exceptions" flagging a late
  order; planners consolidate exceptions by supplier and follow up by phone/email, a
  workflow explicitly still spreadsheet-and-phone-call driven at many companies even with
  modern planning tools available. Source: [Planner Workbench: Why Planning Breaks After PO
  Release](https://sourceday.com/blog/planner-workbench/).
- Consumer electronics return rates cluster around 8–11% for most online retailers (some
  sub-segments run 15–20%), below the ~19% blended e-commerce average — attributed to more
  considered purchase behavior plus return friction (restocking fees, return shipping).
  Notably, Accenture found 68% of returned consumer electronics are "No Trouble Found"
  (the unit works fine on inspection) — a large share of "returns" are not actually defects.
  Processing cost per electronics return runs $30–$65. Sources: [Average Electronics Return
  Rate Benchmarks 2026 | Eightx](https://eightx.co/blog/average-electronics-return-rate-benchmarks),
  [Ecommerce Return Rates by Industry: 2026 Benchmarks | ShipNetwork](https://www.shipnetwork.com/post/return-rates-by-industry).

## 4. Warehouse / DC operations

- Putaway throughput industry-standard range: 50–150 units/hour depending on storage system
  and product characteristics. Source: [UPH Benchmarks for Warehouses | CognitOps](https://cognitops.com/warehouse-uph-benchmarks-by-operation-type/).
- Dock-to-stock time (receipt to available-to-pick): best-in-class under 3.5 hours per the
  2025 WERC DC Measures Report; typical well-run mid-size DCs run 2–4 hours, complex
  high-SKU-variety operations can run 24+ hours. Putaway cycle time benchmark is under 30
  minutes for a standard reserve-location move. Top-performing warehouses run 85–95% labor
  utilization on direct functions. Source: [How to Reduce Dock-to-Stock Time | CognitOps](https://cognitops.com/dock-to-stock-time-improvement-strategies/).
- Inventory holding/carrying cost is typically **20–30% of inventory value per year**
  (APQC benchmarking). An illustrative breakdown for a $500K average-inventory business:
  storage 6%, insurance 1%, obsolescence 4%, cost of capital 8%, handling 3% → 22% total —
  capital cost and obsolescence are usually the two largest and most-often-underestimated
  components. Source: [Inventory carrying cost as a percentage of inventory value | APQC](https://www.apqc.org/what-we-do/benchmarking/open-standards-benchmarking/measures/inventory-carrying-cost-percentage),
  [Portless: Inventory Holding Cost](https://www.portless.com/blogs/inventory-holding-cost).
- Cash-to-cash / cash conversion cycle (CCC = DIO + DSO − DPO) for B2B distributors
  typically runs **40–80 days**; DIO = days stock sits before selling, DSO = days between
  booking a sale and collecting cash, DPO = days taken to pay suppliers (DPO reduces the
  cycle since it's supplier-funded). Trend direction matters more than the absolute level.
  Source: [Cash Conversion Cycle: Formula and Benchmarks | CreditPulse](https://www.creditpulse.com/blog/cash-conversion-cycle-formula-and-benchmarks).

## 5. S&OP cadence

- The standard S&OP process runs on a **monthly** cadence with a five-step cycle: (1) data
  gathering/statistical baseline forecast, (2) demand review (sales/marketing/demand
  planning overlay promotions, NPI, customer commitments — consensus demand approved in
  week 1), (3) supply review (typically week 2 — supply plan balanced, mitigations defined),
  (4) financial review / pre-S&OP reconciliation (week 2–3 — financial impact of proposed
  plans quantified), (5) executive S&OP meeting where trade-offs are decided and one unified
  plan is committed. Source: [Demand Review, Supply Review, and Executive S&OP Meetings |
  Umbrex](https://umbrex.com/resources/inventory-management-playbook/demand-review-supply-review-and-executive-sop-meetings/),
  [The S&OP Process: 5 Steps, One Monthly Calendar](https://demandforecast.ai/blog/the-sop-process/).
- Below the monthly S&OP layer, a planner's actual day-to-day operates on exception
  management: reviewing system-generated exception/action-message lists, prioritizing
  near-term issues, consolidating exceptions by supplier, and following up via phone/email
  — a continuous, daily/weekly-cadence loop distinct from the monthly executive cycle.
  Source: [Learn How to Reduce Supply Chain Planning Exceptions | TraceLink](https://www.tracelink.com/resources/resource-center/improve-supply-plan-accuracy).

## Implications for a simulator

- **Forecast noise should scale with horizon and be asymmetric-friendly**: model per-SKU
  WAPE/MAPE that grows ~2–5 points per additional month of horizon, with a floor around
  30–40% error even at short horizons for electronics-like SKUs, rather than a single fixed
  noise parameter.
- **Give promotions a known lead time and let "knowing the calendar" be a genuine information
  advantage/lever** — an agent that ignores the promo calendar (like the "laggard" firms in
  the research) should structurally underperform one that treats it as a forecast input,
  matching the ~72%-vs-42%-accuracy / 28%-vs-7%-uplift split found in the literature.
- **Segment safety-stock/service-level targets by ABC class** (e.g., 99/95/90) rather than a
  uniform target — this is the single most load-bearing "planner judgment" lever to expose,
  and it directly trades off holding cost (20–30%/year) against stockout/OTIF risk.
  Model at least one of the two canonical safety-stock knobs (Z-score service level,
  lead-time variability) explicitly rather than hand-waving safety stock as a constant.
  - **OTIF-style chargebacks are a good punishing-but-not-catastrophic penalty function**:
  the Walmart 3%-of-COGS-per-violating-case and Amazon tiered 2/4/6%-of-cost ASN chargeback
  structures are concrete, already-graduated penalty curves worth mirroring instead of
  inventing an arbitrary stockout cost.
- **Model allocation-under-shortage as a policy choice** (fair-share pro-rata vs.
  priority-tier), since this is a documented real lever distributors pull, and different
  choices have different downstream customer-relationship consequences worth capturing as
  state (e.g., a "customer goodwill" or future-order-probability variable).
- **Backorder-vs-lost-sale should depend on customer type**, not be a single global rule —
  B2B/contract customers backorder, price-sensitive/impulse retail channels lose the sale;
  this is a natural way to differentiate customer segments in the simulator.
- **Give end-of-life SKUs a markdown mechanic and new SKUs a ramp/low-confidence-forecast
  period** — both are structural, not noise, and returns (8–11% for electronics, ~2/3 of
  which are "no trouble found") should probably feed inventory back into sellable stock
  rather than being destroyed, since that's realistic and changes the effective supply
  curve.
- **Warehouse capacity and receiving throughput should be a soft constraint**, not modeled
  in full physical detail: a simple units/hour cap (50–150/hr per resource) with a
  dock-to-stock delay (hours, not days, for a well-run DC) is enough to create meaningful
  congestion dynamics without over-building the warehouse layer.
- **Use CCC/DIO as a scoring dimension, not just holding cost**: distributors are judged on
  working-capital efficiency (40–80 day CCC is "normal"), so a simulator that only scores
  service level and holding cost is missing a real, commonly-tracked axis of pressure
  (tie DPO to how the simulated firm pays suppliers, which the simulator likely already
  has as a lever).
- **Layer a monthly S&OP decision cadence over the daily/weekly operational loop**: the
  research is consistent that real distributors have two clocks — daily exception-driven
  firefighting and a monthly consensus-forecast/commit cycle — and an agent or benchmark
  task that only operates at one cadence is missing a real structural feature of the
  domain.
