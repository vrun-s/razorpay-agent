from app.decision import decide
from app.models import Intervention, RecoveryCase, WorkflowType
from app.policy import evaluate


def test_decide_always_proposes_payment_retry():
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)

    assert decide(case) is Intervention.PAYMENT_RETRY


def test_policy_passes_through_the_proposed_intervention_unmodified():
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)

    result = evaluate(case, Intervention.PAYMENT_RETRY)

    assert result.approved is True
    assert result.intervention is Intervention.PAYMENT_RETRY
    assert result.reason is None
