# DecisionInput gains an optional qualitative_signal field for the LLM escalation flag

[[0009-architecture-freeze-core-interfaces]] fixed `DecisionInput` at `case`, `customer_history`, `failure_reason` -- no field carries the qualitative customer-response text ticket 08's third LLM role needs ("flags a case as escalation-worthy based on qualitative signal... independent of any numeric policy threshold"). `DecisionOutput.escalate` was already part of the frozen envelope from the start, so the output side needed no change; the input side had nowhere to put what drives it. Per ADR-0009's own escape valve ("if a later ticket finds this ADR's shape genuinely doesn't work, that's a new ADR superseding the relevant part of this one"), this ADR supersedes that one field of ADR-0009's Decision Engine section with the shape actually implemented.

**Decision**: `DecisionInput` gains one optional field:

```python
@dataclass(frozen=True)
class DecisionInput:
    case: RecoveryCase
    customer_history: CustomerHistory
    failure_reason: str | None = None
    qualitative_signal: str | None = None  # new
```

`decide()` calls `llm_client.flag_escalation(signal_text=...)` only when `qualitative_signal` is set; otherwise `escalate` is `False` without an LLM call. Every other field, and `DecisionOutput`, are unchanged.

**Consequences**: No real channel produces `qualitative_signal` yet -- no support/chat webhook exists in the pipeline -- so every caller today (`app/lifecycle.py`'s `run_decision_cycle`) passes `None`; wiring a real source (e.g. a customer-reply webhook feeding the escalation queue) is future work, most likely ticket 09's. Unlike ADR-0010's revision (a genuine contradiction in the Policy Engine sketch), this one is purely additive -- existing callers and tests are unaffected by the new field's default. Third shape ADR-0009 gets revised this way, by the same design: the freeze protects against silent signature drift, not against a documented, deliberate addition once real implementation surfaces a gap the freeze couldn't have anticipated.
