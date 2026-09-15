Project state lives in PROJECT-LOG.jsonl (append-only event log). Replay it
at session start via the project-log skill; append events as you work.

Kestrel is a standalone supply-chain simulator (package `kestrel`, stdlib
Python, `uv`). README.md has the commands; docs/model-findings.md has the live
model evaluation. The approved spec, plans and per-task review ledger are kept
outside this repo (author's machine, supply-chain-pomdp/.superpowers/sdd/).
Never commit without being asked. Never print the OpenRouter key.
