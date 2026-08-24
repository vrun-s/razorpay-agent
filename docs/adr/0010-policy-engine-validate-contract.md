# Policy Engine's `validate()` takes a structured proposal, not a bare Intervention

[[0009-architecture-freeze-core-interfaces]] sketched the Policy Engine's intended contract ahead of ticket 05 as `validate(case: RecoveryCase, intervention: Intervention, policy: PolicyConfig) -> PolicyResult`, with a `PolicyResult.fallback_intervention` field for "what actually executes on rejection." Implementing ticket 05's four real constraints (`max_discount`, `max_payment_retries`, `max_interventions_per_customer`, `recovery_budget`) against that exact shape turned out not to work: a bare `Intervention` enum value carries no discount percentage or incentive cost to check `max_discount`/`recovery_budget` against, and ticket 05's own acceptance criteria explicitly rules out `fallback_intervention` — "a proposal violating any single constraint is rejected outright (not downgraded/auto-corrected to a compliant value)." Per ADR-0009's own escape valve ("if a later ticket finds this ADR's shape genuinely doesn't work, that's a new ADR superseding the relevant part of this one"), this ADR supersedes ADR-0009's Policy Engine section with the shape actually implemented.

**Decision**: `validate(case: RecoveryCase, proposal: ProposedIntervention, policy: PolicyConfig, *, budget_spent_so_far: int = 0) -> PolicyResult`, where:

```python
@dataclass(frozen=True)
class ProposedIntervention:
    intervention: Intervention
    discount_pct: float = 0.0
    incentive_amount: int = 0  # cost of this specific intervention, in paise

@dataclass(frozen=True)
class PolicyConfig:
    max_discount_pct: float
    max_payment_retries: int
    max_interventions_per_customer: int
    recovery_budget: int  # paise

@dataclass(frozen=True)
class PolicyResult:
    approved: bool
    intervention: Intervention               # echoed back unchanged, never substituted
    violated_constraint: str | None = None    # e.g. "max_payment_retries"; None iff approved
    proposed_value: float | int | None = None # the specific value that violated the constraint
    reason: str | None = None                 # human-readable, for the audit trail
```

`fallback_intervention` is dropped: the Policy Engine only answers yes/no on the proposal it was given — it never chooses what runs instead of a rejected one. That choice belongs to the case lifecycle (ticket 06 onward: e.g. fall back to `NO_ACTION`, stop, or escalate), which can see state (Case History, other cases) the Policy Engine doesn't need. `max_payment_retries` and `max_interventions_per_customer` are counted from `case.history`'s `EXECUTION` entries (now tagged with `"intervention": <value>` at write time, in `app/intake.py`) — `max_interventions_per_customer` currently scopes to this one case's own executions, since no cross-case customer identity exists yet in the schema; a case is the closest available proxy for "this customer" until that's built. `recovery_budget` takes `budget_spent_so_far` as an explicit parameter rather than deriving it internally, since cumulative spend tracking is the Streaming Allocator's job (ticket 10), not built yet — the Policy Engine just checks `budget_spent_so_far + proposal.incentive_amount` against the ceiling.

**Consequences**: `app/intake.py` wraps the Decision Engine's still-stub `decide() -> Intervention` output in a `ProposedIntervention` with `discount_pct=0.0, incentive_amount=0`, so today's tracer-bullet flow stays trivially compliant (as before ticket 05) until ticket 07 gives the Decision Engine real economic terms to propose. This is the second locked shape ADR-0009 gets to revise this way, by design — the freeze protects against silent signature drift, not against a documented, deliberate correction once real implementation surfaces a gap the freeze couldn't have anticipated.

`PolicyConfig`/`PolicyResult`/`validate()` as given here are **additively extended by [[0012-policy-engine-escalation-threshold]]** (ticket 09: an `escalation_value_threshold` field and an orthogonal `escalate` output, plus a `case_value` parameter) — this shape stays current, ADR-0012 just adds to it.
