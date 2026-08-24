# Policy Engine gains an escalation-value threshold, orthogonal to approval

Ticket 09 needs a second path to `CaseStatus.ESCALATED` beyond ticket 08's LLM qualitative flag: spec user story 25, "As a Merchant, I want to define escalation thresholds, so that cases above a certain value or risk are routed to a human rather than resolved autonomously." [[0010-policy-engine-validate-contract]] fixed `PolicyConfig`/`PolicyResult`/`validate()` without this — no field carried a case's monetary value in, and no output field carried an escalation signal out. Per that ADR's own escape valve, this is a documented additive change, not a redesign: existing callers/tests are unaffected by the new optional field and parameter.

**Decision**:

```python
@dataclass(frozen=True)
class PolicyConfig:
    ...
    escalation_value_threshold: int | None = None  # paise; None disables it

@dataclass(frozen=True)
class PolicyResult:
    ...
    escalate: bool = False  # orthogonal to `approved`

def validate(case, proposal, policy=DEFAULT_POLICY_CONFIG, *, budget_spent_so_far=0, case_value=0) -> PolicyResult
```

`case_value` is the payment amount at risk (paise, same convention as `recovery_budget`), threaded in explicitly by the caller (`app/lifecycle.py`'s `run_decision_cycle`, from the payment payload) rather than derived internally -- the same pattern ADR-0010 already established for `budget_spent_so_far`. `escalate` is computed once per call and carried through every return path (`_reject` and the final approved `PolicyResult` alike), because a case can be both over-threshold and independently non-compliant, or compliant and still escalation-worthy -- the two signals don't gate each other. `DEFAULT_POLICY_CONFIG` leaves the threshold unset (`None`): it's merchant-configurable per story 25, not a universal default, and an unset threshold must never turn an existing compliant proposal into a surprise escalation.

**Consequences**: `app/lifecycle.py`'s `run_decision_cycle` checks `decision_output.escalate or policy_result.escalate` after logging the `POLICY_CHECK` entry, and short-circuits into `CaseStatus.ESCALATED` before the sequence-bound-stop check or any execution -- an escalated case never auto-executes the proposal that triggered it (spec story 25: "routed to a human rather than resolved autonomously"). This is the third additive revision to a frozen shape, by the same design as ADR-0011: the freeze protects against silent signature drift, not against a documented addition once real implementation needs it.
