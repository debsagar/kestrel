# Real multi-echelon consumer-electronics supply network: operations grounding

Purpose: ground a realistic simulation of component suppliers → contract/own
factory → regional DCs → retail stores/customers. Every fact below carries a
source URL; numbers are as reported by the cited source, not re-derived.

## 1. Factory / assembly planning

- Master production schedule (MPS) plans individual end-items per time
  bucket against forecast demand, working hours, capacity, and parts supply;
  it is the input that MRP explodes into component requirements.
  ["Master Production Scheduling," SAP Help Portal](https://help.sap.com/docs/SAP_ERP/666b7ae6edfe4c05a90ac0150637f964/1a25bf53d25ab64ce10000000a174cb4.html)
- Available-to-Promise (ATP) checks on-hand plus planned supply and can
  return **zero units** available for an assembled product even when
  underlying components/capacity could still support a later date — this is
  exactly the gap that Capable-to-Promise (CTP) closes.
  ["Capable-to-Promise (CTP) in PP/DS," SAP Documentation](https://help.sap.com/doc/saphelp_scm700_ehp02/7.0.2/en-US/4c/56297de7c33a0de10000000a42189c/content.htm?no_cache=true)
- CTP simulates using available components and capacity on underutilized
  lines to produce a delivery-date promise when a straight ATP check fails —
  i.e., a feasibility re-check against real capacity, not just inventory.
  ["Capable-to-Promise (CTP) in PP/DS," SAP Documentation](https://help.sap.com/doc/saphelp_scm700_ehp02/7.0.2/en-US/4c/56297de7c33a0de10000000a42189c/content.htm?no_cache=true)
- SMT (surface-mount) line changeover: industry "ideal"/SMED target is
  **10–15 minutes**; typical high-mix EMS baseline runs **60–120 minutes**
  per changeover before optimization; unoptimized changeovers can consume
  **25–40% of available production time** on a line running 20+ board types
  per day.
  ["A Roadmap to Faster SMT Changeovers," I-Connect007](https://iconnect007.com/article/150773/a-roadmap-to-faster-smt-changeovers/150770/smt)
- Some EMS lines run **20–40 minutes per changeover with 6–14 changeovers/day**
  depending on job size and components-per-board.
  ["A Roadmap to Faster SMT Changeovers," I-Connect007](https://iconnect007.com/article/150773/a-roadmap-to-faster-smt-changeovers/150770/smt)
- Build-to-order consumer-electronics lead time benchmark (Dell, historical):
  orders shipped to customers within **5 days** of order placement, with the
  fastest configured units built and shipped in **6–8 hours**; this was
  enabled by supplier-owned hubs minutes from the plant, order downloads
  every **2 hours**, and suppliers given **15 minutes to confirm** part
  availability and **75 minutes to deliver** to the line.
  ["Case study: Dell — Distribution and supply chain innovation," MaRS Startup Toolkit](https://learn.marsdd.com/article/case-study-dell-distribution-and-supply-chain-innovation/)
- Before shifting to build-to-order, Dell carried **70 days of inventory on
  hand** (1993) and every unsold PC lost **1% of value per week** — the
  economic pressure that forced the lead-time compression above.
  ["Timeless Lessons From Dell's Build-to-Order Strategy in The 2000s," Supply Chain Nuggets](https://supplychainnuggets.com/timeless-lessons-from-dells-build-to-order-strategy-in-the-2000s/)
- Component shortage / allocation: when demand exceeds a component supplier's
  output, the supplier stops promising normal quantities and instead
  rations available stock across customers on a **"fair-share" basis tied to
  each customer's recent purchasing history** — not first-come-first-served.
  ["Electronic Component Allocation Explained," GlobX](https://globx.eu/blog/supply-chain-insight/electronic-component-allocation)
- 2021 semiconductor shortage: semiconductor demand grew **>30%** between
  August 2020 and August 2021, driving multi-quarter allocation across
  automotive and consumer electronics simultaneously (line-down risk shared
  across industries competing for the same fabs).
  ["Semiconductor Chip Shortage 2021: Causes and Effects," EE Times / Grinnell](https://cs.grinnell.edu/lunar-note/semiconductor-chip-shortage-2021-causes-and-effects-1767646793)
- Unplanned line-down cost is highly asymmetric by plant type: **~$260,000/hr**
  average across manufacturing generally, **~$2.3M/hr** for an automotive
  assembly plant, and **into the millions/hr** for a leading-edge
  semiconductor fab — useful as a relative-cost prior for a "line stoppage"
  penalty in a simulator (electronics final assembly sits well below fabs,
  above generic manufacturing).
  ["The Real Cost of Unplanned Downtime in Manufacturing," Reliamag](https://reliamag.com/articles/cost-unplanned-downtime-manufacturing/)
**Implications for a simulator:** model ATP as a hard on-hand/planned-supply
check that can be pessimistic (returns "unavailable" even when true capacity
exists), and CTP as a second-pass feasibility solve using current capacity —
these should be two distinct decision points, not one. Changeover time
should be a stochastic tax on switch-SKU actions (order-of-magnitude: tens of
minutes to ~2 hours), penalizing frequent small-batch production schedules.
Component allocation under shortage should be exogenous and non-negotiable
(fair-share by trailing purchase volume), not a lever the agent controls —
it's the environment rationing the agent, mirroring real allocation letters.
Line-down cost should scale with which echelon is starved (fab > final
assembly > generic warehousing) if the simulator ever prices stockout at the
production stage rather than only at the retail stage.

## 2. Distribution (DRP, transfers, allocation)

- DRP (Distribution Requirements Planning) is the ASCM/APICS-defined
  time-phased order-point method: it determines the need to replenish
  branch-warehouse inventory, then explodes those branch-level planned
  orders via MRP-style logic into gross requirements on the supplying
  source (echoing MRP's logic but applied to a distribution, not a bill-of-
  materials, tree).
  ["What Is Distribution Requirements Planning (DRP)?," NetSuite](https://www.netsuite.com/portal/resource/articles/erp/distribution-requirement-planning-drp.shtml)
- DRP networks are explicitly modeled as **tree structures**: a central
  facility supplies regional facilities, which supply further downstream
  facilities, with any number of layers — directly matching a
  supplier→factory→regional-DC→store topology.
  ["What Is Distribution Requirements Planning (DRP)?," NetSuite](https://www.netsuite.com/portal/resource/articles/erp/distribution-requirement-planning-drp.shtml)
- DRP mechanics center on the **Projected Available Balance (PAB)** computed
  period-by-period on a DRP grid — the standard planning artifact taught in
  ASCM/APICS CPIM curricula.
  ["PDL 05: Distribution Requirements Planning (DRP)," ASCM Monterrey](https://www.mty.ascm.org/pdl-05-distribution-requirements-planning-drp)
- Pallet-level inter-region truck transport within Europe: **domestic
  groupage ≈ €80–150/pallet**, **cross-border neighboring-country groupage ≈
  €150–300/pallet**, and **long corridors (e.g., Poland→Spain) ≈ €300–600+
  per pallet**.
  ["How Much Does It Cost to Ship a Pallet in Europe? (2026 Rates)," Transroad](https://www.trans-road.com/en/blog/freight-cost-per-pallet-europe)
- Full-truckload road cost in Europe (2025): **€1.10–1.90/km**; LTL (part-
  load, cost normalized per cargo share): **€0.35–0.90/km**.
  ["Road Transport Price Per Km in Europe 2025," Trans-road](https://www.trans-road.com/en/freight-rates/cost-per-km-europe)
- The LTL vs. dedicated-truck break-even is **~17–22 pallets** depending on
  corridor — below that, pay-per-pallet groupage is cheaper; above it, book
  a full truck.
  ["Cost to Ship a Pallet from Europe: 2026 Pricing Guide," EuroSaleOnline](https://eurosaleonline.com/countries/how-much-does-it-cost-to-ship-a-pallet-from-europe)
- Rail/intermodal freight typically costs **20–40% less than truck** for
  long-distance moves but trades off transit-time flexibility and requires
  extra handling — the classic cost/speed lever between regional DCs.
  ["How Much Does It Cost to Ship a Pallet in Europe? (2026 Rates)," Transroad](https://www.trans-road.com/en/blog/freight-cost-per-pallet-europe)
- Short-sea/maritime intra-Europe: **≈€150–500/pallet** for road/rail vs.
  **€350–900/pallet** by sea to overseas hubs vs. **€1,200–4,000+/pallet**
  by air — establishing the air-freight expedite premium (roughly 5–10x
  surface cost) that motivates an "air lever" in an expedite model.
  ["Cost to Ship a Pallet from Europe: 2026 Pricing Guide," EuroSaleOnline](https://eurosaleonline.com/countries/how-much-does-it-cost-to-ship-a-pallet-from-europe)
- Rotterdam→Germany rail: cargo crosses the German border within **3 hours**
  and reaches many European destinations within **24 hours**.
  ["Rail transport," Port of Rotterdam](https://www.portofrotterdam.com/en/logistics/connections/intermodal-transportation/rail-transport)
- Rotterdam→Poland via dedicated rail shuttle: **48–72 hours** transit
  (rail-road combined).
  ["Rail vs Sea Transit Time: China to Poland/Germany in Real Numbers," Topway Shipping](https://www.topwayshipping.com/rail-vs-sea-transit-time-china-to-poland-germany-in-real-numbers/)
- Cross-docking facilities achieve **5–10x higher throughput per square
  foot** than storage-based warehouses and typically need **2–3x more dock
  doors** per unit floor area to handle simultaneous inbound/outbound flow;
  target dock-to-dock cycle is **30–45 minutes per truck** with sortation
  accuracy **>99.5%**.
  ["Cross-docking Implementation Guide," Racklify](https://racklify.com/encyclopedia/cross-docking-implementation-guide-facility-layout-processes-and-technology/)
**Implications for a simulator:** treat inter-DC replenishment as a DRP tree
with time-phased PAB, not independent (s,S) policies per node — the parent
DC's outbound plan should net against the aggregate of children's planned
orders. Give the simulator at least three transport-cost/speed tiers between
DCs (rail ≈ cheap/slow, truck ≈ mid, air ≈ 5–10x cost/fast), with a
pallet-count break-even threshold between LTL and dedicated-truck booking —
this is a natural place for a batching/economies-of-scale mechanic. Model a
central DC's inter-regional transfer lead time on the order of ~1 day
(Germany-like proximity) vs. ~2–3 days (Poland-like periphery) to create a
non-uniform regional-service asymmetry.

## 3. Bullwhip effect

- Bullwhip ratio = order variability ÷ demand variability. Thresholds
  reported: **<1.2 efficient**, **1.2–1.5 moderate inefficiency**, **>1.5
  high / significant ordering-policy problems**, **>2.5 critical**, typically
  requiring fundamental redesign.
  ["Bullwhip Effect in Supply Chains," MetricGate](https://metricgate.com/blogs/bullwhip-effect-supply-chain-variance/)
- Real case study (UK dairy product, grocery retailer): **production order
  variance was 7.68x** demand variance — a concrete, large real-world
  amplification figure, well above the "critical" threshold.
  ["Bullwhip Effect in Supply Chains," MetricGate](https://metricgate.com/blogs/bullwhip-effect-supply-chain-variance/)
- Four canonical causes: **demand-signal processing** (naive forecast
  updating on noisy downstream orders), **order batching**, **shortage
  gaming** (rationing induces over-ordering), and **price fluctuations**
  (forward-buying around promotions).
  ["The bullwhip effect: Progress, trends and directions," ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0377221715006554)
- VMI (vendor-managed inventory) remedy, measured cases: bullwhip
  coefficient reduced from **1.109→0.535** (biscuit manufacturing), from
  **1.224→0.496** (fresh-water manufacturing), and via CPFR from
  **1.285→0.729** (HDPE plastics) — all roughly **50–60% reductions** in the
  bullwhip coefficient.
  ["Vendor Managed Inventory and bullwhip reduction in a two-level supply chain," Cardiff ORCA](https://orca.cardiff.ac.uk/id/eprint/38772/1/Vendor%20managed%20inventory%20and%20bullwhip%20reduction%20in%20a%20two%20level%20supply%20chain%20Pre-print.pdf)
- Firms adopting VMI report **20–30% reductions in inventory holding costs**
  alongside improved in-stock availability, i.e., VMI is not solely a
  variance-reduction lever but also a working-capital lever.
  ["Vendor Managed Inventory and bullwhip reduction in a two-level supply chain," Cardiff ORCA](https://orca.cardiff.ac.uk/id/eprint/38772/1/Vendor%20managed%20inventory%20and%20bullwhip%20reduction%20in%20a%20two%20level%20supply%20chain%20Pre-print.pdf)

**Implications for a simulator:** a >1.5 order/demand variance ratio should
be treated as the "something is badly miscalibrated" regime and a >7x ratio
(the real dairy case) as an existence proof that extreme amplification is
plausible under batching/promotion-driven demand, not a modeling artifact to
suppress. If the simulator ever adds an information-sharing lever (shared
demand signal / VMI-like visibility upstream), a 50–60% cut in the
downstream order-variance ratio is the right order of magnitude to target
for calibration, and it should come paired with an inventory-holding-cost
drop (20–30%), not just a variance drop.

## 4. Network design

- Poland and the Netherlands are described as **Europe's two central
  wholesale-electronics corridors**: most Asian-origin electronics enter via
  Rotterdam (sea) and Amsterdam Schiphol (air), are warehoused/repackaged in
  the Netherlands, then move to Poland for refurbishment, B2B distribution,
  and onward export to Eastern Europe/CIS — i.e., a two-tier
  gateway-DC → secondary-DC pattern.
  ["Poland and Netherlands: Europe's Wholesale Electronics Corridors," Aikon](https://aikon.app/blog/poland-netherlands-europe-wholesale-electronics)
- Rotterdam→Germany rail: **<3 hours to cross the border, <24 hours** to
  many European destinations (repeated from §2, load-bearing for network
  design as well as replenishment timing).
  ["Rail transport," Port of Rotterdam](https://www.portofrotterdam.com/en/logistics/connections/intermodal-transportation/rail-transport)
- Fast-fashion benchmark for a fully vertically-integrated network (Zara/
  Inditex): central hub ("The Cube," Arteixo, Spain) is **464,500 m² (5M
  sq ft)**, with **11 owned factories within a 16 km radius** linked to the
  DC by underground monorail; finished goods reach European stores in
  **24–48 hours** and Asia/Americas stores in **48–72 hours**; design-to-
  shelf cycle is **~2 weeks** vs. **4–8 weeks industry-typical** for
  non-vertically-integrated apparel chains.
  ["Super Responsive Supply Chain: The Case of Spanish Fast Fashion Retailer Inditex-Zara"](https://www.iberglobal.com/files/2018/zara_case_supply_chain.pdf)
- Zara's cross-docking at the central hub is explicitly credited with
  compressing the engineer-to-order (ETO) lead time — matching the DRP/
  cross-dock throughput mechanic in §2.
  ["ZARA Logistics System & Transportation Strategy Case Study," Aithor](https://aithor.com/essay-examples/zara-logistics-system-transportation-strategy-case-study)
- Public sourcing did not surface a single authoritative, brand-disclosed
  count of European DC locations for Apple, Samsung, or Xiaomi (their
  network maps are not published at that granularity); Apple's own
  disclosures describe supplier geographic concentration (Europe as a
  moderate manufacturing/assembly participant) rather than DC counts.
  ["Apple's Supply Chain: Economic and Geopolitical...," AEI](https://aei.org/wp-content/uploads/2025/06/RPT_Miller_Apple-Supply-Chain_June-2025.pdf)

**Implications for a simulator:** a two-tier European network (one or two
gateway DCs near a major port, feeding several secondary/regional DCs with a
day-scale transit lag to core markets and a multi-day lag to peripheral
markets) is a defensible, sourced topology even though brand-specific DC
counts for Apple/Samsung/Xiaomi are not public. The Zara case is a useful
upper-bound reference for what full vertical integration buys (2-week
design-to-shelf, 24–72h hub-to-store) — the simulator's non-integrated
"buy from contract factory" mode should sit well below that speed.

## 5. Retail / customer echelon

- On-shelf availability (OSA) benchmark: strong performers sit at
  **95–98%**; below 95% is flagged as needing investigation.
  ["On-Shelf Availability in Retail," Pazo](https://www.gopazo.com/blog/on-shelf-availability)
- European retail out-of-stock rate averages **8.3%** (roughly 1 in 12
  SKUs unavailable when a shopper looks); NIQ reported a narrower **~4%**
  shelf out-of-stock rate specifically across France, Spain, and the UK.
  ["On-Shelf Availability in Retail," Pazo](https://www.gopazo.com/blog/on-shelf-availability)
- Stockouts are estimated to cost the **global retail industry ~8% of
  sales**, rising to **~10% during promotions**, and an estimated
  **$1 trillion/year** in lost sales industry-wide.
  ["Stockout Statistics Every Retailer Should Know," Xorosoft](https://xorosoft.com/stockout-statistics/)
- Consumer response to a stockout: **~70% switch brand or store** in some
  combination; more granularly, **31% buy a different brand** and **26%
  leave the store entirely** without purchasing — the behavioral basis for
  a lost-sale (not just delayed-sale) assumption on stockouts.
  ["Stockout Statistics Every Retailer Should Know," Xorosoft](https://xorosoft.com/stockout-statistics/)
- Consumer-electronics return rate: **~8–15%** of orders (one estimate:
  **~11% average**), materially lower than apparel (~20%+), but per-unit
  reverse-logistics cost is high: **$30–65/item** in electronics reverse
  logistics, with only **~50% of returned units** resold or refurbished
  industry-wide.
  ["Ecommerce Return Rates in 2026," Richpanel](https://www.richpanel.com/learn/ecommerce-return-rates)
- Electronics-specific return fraud rate: **~13%** of consumer-electronics
  returns are fraudulent, above the ~9% all-category average.
  ["Ecommerce Return Rates in 2026," Richpanel](https://www.richpanel.com/learn/ecommerce-return-rates)

**Implications for a simulator:** treat 95–98% OSA as the "good" service-
level target and use it to calibrate a reward/penalty scale where a
stockout below 95% coverage starts genuinely costing simulated revenue (on
the order of a high-single-digit percentage of sales, not a small
rounding-error penalty). If the simulator ever models customer switching
under stockout, ~70% substitution/attrition (not simple backorder-and-wait)
is the empirically grounded default. If returns flow is modeled, electronics
returns should be low-frequency (~10%) but high friction-cost per unit
($30–65), and only about half of returned stock should re-enter usable
inventory — the rest is effectively write-off, which matters for anyone
tracking a closed-loop inventory balance.
