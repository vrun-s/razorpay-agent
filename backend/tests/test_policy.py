"""Ticket 05: Policy Engine constraint enforcement."""

from app.models import CaseHistoryEntry, CaseHistoryEntryType, Intervention, RecoveryCase, WorkflowType
from app.policy import PolicyConfig, ProposedIntervention, validate

_POLICY = PolicyConfig(
    max_discount_pct=10.0,
    max_payment_retries=2,
    max_interventions_per_customer=3,
    recovery_budget=1000,
)


def _new_case() -> RecoveryCase:
    return RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)


def _case_with_prior_executions(session, interventions: list[Intervention]) -> RecoveryCase:
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)
    session.add(case)
    for intervention in interventions:
        session.add(
            CaseHistoryEntry(
                case_id=case.id,
                entry_type=CaseHistoryEntryType.EXECUTION,
                summary="prior execution",
                data={"intervention": intervention.value},
            )
        )
    session.commit()
    session.refresh(case)
    return case


def test_compliant_proposal_passes_through_unmodified():
    case = _new_case()
    proposal = ProposedIntervention(intervention=Intervention.PAYMENT_RETRY, discount_pct=5.0, incentive_amount=100)

    result = validate(case, proposal, _POLICY)

    assert result.approved is True
    assert result.intervention is Intervention.PAYMENT_RETRY
    assert result.violated_constraint is None
    assert result.reason is None


def test_max_discount_pct_blocks_a_proposal_over_the_limit():
    case = _new_case()
    proposal = ProposedIntervention(intervention=Intervention.PAYMENT_RETRY, discount_pct=15.0)

    result = validate(case, proposal, _POLICY)

    assert result.approved is False
    assert result.violated_constraint == "max_discount_pct"
    assert result.proposed_value == 15.0


def test_max_payment_retries_blocks_a_proposal_over_the_limit(session):
    # Policy allows 2 retries; this case already has 2 executed -> a 3rd is over the limit.
    case = _case_with_prior_executions(session, [Intervention.PAYMENT_RETRY, Intervention.PAYMENT_RETRY])
    proposal = ProposedIntervention(intervention=Intervention.PAYMENT_RETRY)

    result = validate(case, proposal, _POLICY)

    assert result.approved is False
    assert result.violated_constraint == "max_payment_retries"
    assert result.proposed_value == 3


def test_max_interventions_per_customer_blocks_a_proposal_over_the_limit(session):
    # Policy allows 3 interventions total; this case already has 3 executed (mixed types).
    case = _case_with_prior_executions(
        session, [Intervention.PAYMENT_RETRY, Intervention.PAYMENT_RETRY, Intervention.RESUME_CHARGE]
    )
    proposal = ProposedIntervention(intervention=Intervention.RESUME_CHARGE)

    result = validate(case, proposal, _POLICY)

    assert result.approved is False
    assert result.violated_constraint == "max_interventions_per_customer"
    assert result.proposed_value == 4


def test_recovery_budget_blocks_a_proposal_over_the_limit():
    case = _new_case()
    proposal = ProposedIntervention(intervention=Intervention.PAYMENT_RETRY, incentive_amount=200)

    result = validate(case, proposal, _POLICY, budget_spent_so_far=900)

    assert result.approved is False
    assert result.violated_constraint == "recovery_budget"
    assert result.proposed_value == 1100


def test_a_rejected_proposal_is_not_downgraded_to_a_compliant_value():
    case = _new_case()
    proposal = ProposedIntervention(intervention=Intervention.PAYMENT_RETRY, discount_pct=99.0)

    result = validate(case, proposal, _POLICY)

    assert result.approved is False
    # The rejected intervention/value are echoed back unchanged, never substituted.
    assert result.intervention is Intervention.PAYMENT_RETRY
    assert result.proposed_value == 99.0


def test_case_value_at_or_above_escalation_threshold_is_flagged_for_escalation():
    policy = PolicyConfig(
        max_discount_pct=10.0, max_payment_retries=2, max_interventions_per_customer=3,
        recovery_budget=1000, escalation_value_threshold=50_000,
    )
    case = _new_case()
    proposal = ProposedIntervention(intervention=Intervention.PAYMENT_RETRY)

    result = validate(case, proposal, policy, case_value=50_000)

    assert result.escalate is True
    # Escalation is orthogonal to approval -- a compliant proposal still executes.
    assert result.approved is True


def test_case_value_below_escalation_threshold_is_not_flagged():
    policy = PolicyConfig(
        max_discount_pct=10.0, max_payment_retries=2, max_interventions_per_customer=3,
        recovery_budget=1000, escalation_value_threshold=50_000,
    )
    case = _new_case()
    proposal = ProposedIntervention(intervention=Intervention.PAYMENT_RETRY)

    result = validate(case, proposal, policy, case_value=49_999)

    assert result.escalate is False


def test_no_escalation_threshold_configured_never_flags_escalation():
    case = _new_case()
    proposal = ProposedIntervention(intervention=Intervention.PAYMENT_RETRY)

    result = validate(case, proposal, _POLICY, case_value=10_000_000)

    assert result.escalate is False


def test_escalation_flag_survives_a_rejected_proposal():
    # A proposal can be both over-threshold (escalate) and independently
    # rejected on another constraint -- the two are orthogonal signals.
    policy = PolicyConfig(
        max_discount_pct=10.0, max_payment_retries=2, max_interventions_per_customer=3,
        recovery_budget=1000, escalation_value_threshold=50_000,
    )
    case = _new_case()
    proposal = ProposedIntervention(intervention=Intervention.PAYMENT_RETRY, discount_pct=99.0)

    result = validate(case, proposal, policy, case_value=50_000)

    assert result.approved is False
    assert result.escalate is True
