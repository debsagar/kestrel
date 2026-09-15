# Kestrel

A supply-chain simulator you can actually run a company on.

Kestrel Audio is a made-up electronics brand: three products assembled in a plant
in Dongguan from parts bought from five suppliers, shipped to Rotterdam, moved to
warehouses in Germany and Poland, and sold to four customers with different
contract terms. The simulation runs the real 2026 calendar, one day at a time.
Whoever plays the planner sees only the company's paperwork (purchase orders,
bookings, invoices, work orders, customer orders) and acts by changing it.
Disruptions happen underneath and show up the way they would in real life: a
confirmation slips, a container gets rolled, a supplier's scorecard drifts.

The planner can be a rule-based policy, a person at the browser desk, or a
language model calling tools. We ran GPT-5.6 Luna through five disruption
scenarios and wrote down where it went wrong. See `docs/model-findings.md`.

## Run it

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```
uv sync --all-extras
uv run pytest -q                              # 188 tests, about 90 s
uv run uvicorn kestrel.api:app --port 8000    # then open http://localhost:8000
```

Or with Docker:

```
docker build -t kestrel .
docker run --rm -p 8000:8000 kestrel
```

The desk lets you create a world from a seed, step days, let the rule planner
run, submit actions by hand, or hand one day to the model. It also replays
recorded runs.

`artifacts/kestrel-demo.html` is the same desk as a single file, with a full
rule-planner year and all ten scenario runs baked in. It opens offline.

## Run the model

```
export OPENROUTER_API_KEY=...        # or put it in .env
uv run python -m kestrel.agent run --task red_sea --player luna
uv run python -m kestrel.agent run --task red_sea --player rule
```

Tasks: `red_sea`, `cny_prebuild`, `soc_insolvency`, `black_friday`,
`invoice_mismatch` (details in `docs/tasks.md`). Both players start from the
same checkpoint and face the same hidden events. Runs land in `runs/` (not
tracked, they are large); the model's dialogue for each run we did is in
`transcripts/`. A 45-day task costs roughly half a dollar.

Rebuild the offline demo after new runs with `uv run python -m kestrel.artifact`.

## What is in here

```
kestrel/        the simulation (standard library only) and its HTTP API
kestrel/agent/  scenarios, tool schemas, the model loop, the CLI
frontend/       the desk, plain HTML and JavaScript
tests/          mechanics, conservation checks, full-year runs, API, agent
docs/           scenario definitions, model findings, design brief, source notes
transcripts/    what the model said and did, per run
artifacts/      the offline demo
```

## How it is built

Every business event is a record with a state machine and a history. Money
goes through one ledger with fixed categories. Stock is one dictionary. A
daily check proves nothing is created or lost: units made equal units shipped
plus on hand plus written off plus in transit, and cash matches the ledger.

Hidden state (true supplier health, the freight-rate regime, real demand) is
kept in two seeded random streams that never read the player's actions. A
test greps the public screens for it.

Mechanisms come from industry sources collected in `docs/research/`: the
30/70 supplier payment pattern, three-way invoice matching, Suez versus Cape
transit, blank sailings, demurrage after free days, the May freight-contract
season, the 2026 Chinese New Year notice. The exact rates and probabilities
are our own choices and are labelled as such in the design brief
(`docs/design-brief.html`).

## What the model got wrong

Short version. Every item in `docs/model-findings.md` links to the day, the
tool call, the engine's reply and the record it affected.

- On day one it released 35,000 units of work orders against a 4,000-a-day
  plant, draining most of the component stock in one move.
- Ahead of the Chinese New Year shutdown it placed no purchase orders at all
  in 60 days. The rule planner placed 37.
- It re-expedited orders already marked expedited, ordered from a supplier the
  briefing marked as unqualified, and allocated quantities the screen showed
  were not available.
- In one run it never booked a container; late and short deliveries went from
  1 and 15 (baseline) to 27 and 44.

It also did things right: it read the Cape diversion notice and reacted,
handled the supplier insolvency quickly, and disputed an over-billed invoice
the day it appeared.

The runs found four simulator bugs too, all fixed; the affected scenario was
re-run and the old runs kept under a revision suffix.
