# CONTEXT.md (reconstructed)

> The original CONTEXT.md was not provided. This file is rebuilt from what IMPLEMENTATION.md references
> (contracts §7, policy tiers, fault list §10, principles §4). Replace it with your original if you have it.

## Principles
1. Verify against observed system state, never against what the executor claims. "Success" is only printed after independent checks pass.
2. Policy is deterministic code (`core/policy.py`), not a prompt. Unknown = ask.
3. Document/web text is data, never instructions (`<untrusted_document>`).
4. Everything is in an append-only event log; every run produces an Evidence Report.
5. Generalise through SOPs and generic tools, not task-specific code.

## Policy tiers
T0 read-only (auto) · T1 reversible edit (auto) · T2 commit (auto within limits, else ask) · T3 external/irreversible/unknown (always ask) · hosts/paths outside allow-lists are blocked.

## Contracts (§7) - see `ai_operator/core/models.py`
TaskSpec, Plan/Step, Postcondition (sql|file|http|ui|llm), Action, Decision, Observation, StepResult, VerificationResult.

## Faults (§10) - see `company_env/common/web.py`
modal, rename_button, session_expiry, validation, flaky_500, slow (set via `FAULTS=a,b`).
