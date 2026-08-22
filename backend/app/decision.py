"""Decision Engine — ticket 01 stub.

Trivial fixed-rule decision: always propose Payment Retry. Ticket 07 replaces
this with the Beta-Bernoulli estimator + bounded LLM role (ADR-0006); nothing
downstream of this function's return type should need to change when that
happens.
"""

from app.models import Intervention, RecoveryCase


def decide(case: RecoveryCase) -> Intervention:
    return Intervention.PAYMENT_RETRY
