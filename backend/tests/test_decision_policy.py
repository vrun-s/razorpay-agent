from app.decision import decide
from app.models import Intervention, RecoveryCase, WorkflowType


def test_decide_always_proposes_payment_retry():
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)

    assert decide(case) is Intervention.PAYMENT_RETRY
