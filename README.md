# AI_Project (AI Operator)

An agent that plans, acts across company systems (web portals, files, SQL), verifies the real end state, and escalates to a human when it should.
Built from IMPLEMENTATION.md. Package name is `ai_operator` (a package called `operator` would shadow Python's stdlib `operator` module and break `python -m`).

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && playwright install chromium
export ANTHROPIC_API_KEY=...
make data                                   # receipts, template, invoices
python -m ai_operator.run "Reimburse Priya's Mumbai trip" --files company_env/data/receipts/mumbai --start-portals
python -m ai_operator.run "Reimburse Priya's Mumbai trip" --files company_env/data/receipts/mumbai --start-portals --faults modal
python -m ai_operator.ui.server             # console at http://localhost:8000 (starts portals too)
pytest                                      # unit tests, no API key needed
pytest -m e2e                               # live LLM + browser
python -m evals.run_evals --runs 5          # eval table -> evals/results.json
```
Other tasks: `"Onboard Arjun Nair, joining Engineering on 2026-11-02, reporting to Anita Desai. His personal email is arjun.nair@example.test"`
and `"Reconcile the March vendor invoices against the ledger" --files company_env/data/invoices_march.xlsx` (Task 3 uses only SOP-FIN-003, no task code).

## Free mode (no API key): local model with Ollama
```bash
brew install ollama && ollama serve &      # or install the app from ollama.com
ollama pull qwen2.5:14b                    # ~9 GB; use qwen2.5:7b on small machines
export OPERATOR_PROVIDER=ollama OPERATOR_MODEL=qwen2.5:14b
python -m ai_operator.run "Reimburse Priya's Mumbai trip" --files company_env/data/receipts/mumbai --start-portals
```
Local models are much weaker at multi-step tool use than Claude: expect retries, escalations, and NOT VERIFIED outcomes. The verifier and policy gate still protect you from false successes.

## Architecture
intake → plan (SOP-grounded, postconditions per step) → execute (tool-use loop, every action through the policy gate) → verify step → replan / ask human → independent final verification → Evidence Report (`runs/<id>/report.html`).

## Deviations from the spec (deliberate)
- Tool names are sent to the API as `browser__click` (the API rejects dots) and mapped back.
- `browser.login(system)` keeps credentials out of the model's context.
- Commit detection is structural (`type=submit`, Enter key) as well as label-based, so the `rename_button` fault cannot dodge the gate.
- Non-commit clicks are T1-allow (the spec skeleton would have asked on every click).
- File paths are allow-listed in policy; `email.send` is simulated (writes an outbox file).

## Limitations
- The auto-approve limit reads `claim_total_inr` from working memory, which the model sets; the independent verifier re-reads the receipts, but the gate itself trusts that value.
- Cost table is approximate. Vision fallback is read-only. SQLite/mock portals only.
- Eval numbers are not included: run `make evals` and paste your table here.
