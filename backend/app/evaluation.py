"""Ticket 15: the evaluation harness -- implements ADR-0013's contract
(metric formula, baseline-arm definitions, pairing mechanics, bootstrap
procedure) directly. Ticket 15's own issue says to build against that
document rather than re-deriving any of it here, so this module's design
choices are annotated with the ADR-0013 clause they implement.

**The four arms** (ADR-0013):
- `no_intervention`: every case always gets NO_ACTION -- a single,
  fatigue-free draw (the customer's organic, no-nudge resolution behaviour;
  there is nothing to retry).
- `fixed_rule`: every case always gets its workflow's cost-bearing
  intervention at a flat 5% discount, retried across cycles like a real
  case, through the *same* Policy Engine and Streaming Allocator (fresh
  per-arm instances, never the live process-wide singletons) as the AI
  arm -- only the proposed intervention differs.
- `ai_treatment`: the real system, unmodified -- app/simulator_driver.py's
  `run_simulated_case`, which drives app/intake.py + app/lifecycle.py
  exactly as a live webhook would.
- `offline_optimal`: a retrospective computation with full foresight
  (CONTEXT.md: Offline-Optimal Allocation) -- not a decision the agent
  made, so it doesn't touch the Policy Engine/Allocator at all. Tries
  every valid intervention for up to the same retry budget the online
  arms get, and keeps whichever recovers: an offline arm that could try
  strictly *fewer* things than an online one wouldn't be a fair upper
  bound on what the online arms achieved.

**Estimator isolation.** `mark_recovered`/`resolve_case_manually`
(app/lifecycle.py) update the process-wide `Estimator` singleton for
`EventSource.SIMULATED`-sourced outcomes (ADR-0006) whenever a case
resolves; `decide()` (app/decision.py) only *reads* it. Updating is
appropriate for the `ai_treatment` arm (that online learning *is* the thing
being evaluated), catastrophic for every other arm (it would leak a
baseline-arm's synthetic outcomes into the same posterior the AI arm reads,
breaking ADR-0007's independence guarantee). Baseline and offline-optimal
arms therefore never call `run_decision_cycle`/`mark_recovered` at all: they
call `app.policy.validate()` and a fresh `StreamingAllocator` directly,
against plain, never-persisted `RecoveryCase` objects (never added to a
session -- these aren't real decisions the system made). Only the
`ai_treatment` arm touches the estimator, and `reset_estimator()` runs at
the start of every evaluation run so a rerun (or the dev/validation/held-out sequence within
one run) starts cold every time -- required for the determinism acceptance
criterion, since a warm-started rerun would not reproduce the same numbers.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.allocator import AllocationCandidate, BudgetLedger, StreamingAllocator
from app.decision import VALID_INTERVENTIONS
from app.estimator import reset_estimator
from app.merchant_config import DEFAULT_MERCHANT_CONFIG
from app.models import (
    CaseHistoryEntry,
    CaseHistoryEntryType,
    EventSource,
    Intervention,
    RecoveryCase,
    WorkflowType,
)
from app.policy import DEFAULT_POLICY_CONFIG, PolicyConfig, ProposedIntervention, validate
from app.simulator.generator import SimulatedCase, generate_population
from app.simulator_driver import DEFAULT_CASE_AMOUNT, ResolvedDecision, run_simulated_case
from app.simulator_gateway import SimulatorGateway

# -- Dataset splits (ADR-0013: "300 dev / 150 validation / 200 held-out") --

DEFAULT_DATASET_SEED = 20260826  # "generated once under a fixed top-level seed"
DEV_SIZE = 300
VALIDATION_SIZE = 150
HELD_OUT_SIZE = 200


@dataclass(frozen=True)
class DatasetSplits:
    dev: list[SimulatedCase]
    validation: list[SimulatedCase]
    held_out: list[SimulatedCase]


def generate_dataset_splits(
    seed: int = DEFAULT_DATASET_SEED,
    *,
    dev_size: int = DEV_SIZE,
    validation_size: int = VALIDATION_SIZE,
    held_out_size: int = HELD_OUT_SIZE,
) -> DatasetSplits:
    """One population generated under a fixed top-level seed, partitioned by
    a fixed sequential rule (cases 1..dev_size dev, next validation_size
    validation, next held_out_size held-out) -- reproducible from the seed
    alone, never a separately-seeded generation per split."""
    population = generate_population(seed, dev_size + validation_size + held_out_size)
    return DatasetSplits(
        dev=population[:dev_size],
        validation=population[dev_size : dev_size + validation_size],
        held_out=population[dev_size + validation_size : dev_size + validation_size + held_out_size],
    )


def _case_seed(run_seed: int, case_index: int) -> int:
    """Deterministic per-case seed derived from `(run_seed, case_index)`.

    ADR-0013's pairing mechanism: "each case gets a deterministic per-case
    seed... for a given case, each arm's chosen intervention is fed to the
    same seeded draw." Every arm below constructs its own fresh
    `SimulatorGateway`/rng from this same seed when it processes a given
    case, so the first (and, for multi-cycle arms, every subsequent) draw
    lines up attempt-for-attempt across arms -- what makes a per-case
    subtraction ("paired") isolate the effect of the chosen intervention
    rather than independent random noise. A fixed formula, not Python's
    salted `hash()`, keeps this stable across processes/interpreter versions.
    """
    return (run_seed * 1_000_003 + case_index) % (2**31)


def _workflow_intervention(workflow_type: WorkflowType) -> Intervention:
    """The workflow's cost-bearing intervention (CONTEXT.md: Payment Retry / Resume Charge)."""
    return Intervention.PAYMENT_RETRY if workflow_type == WorkflowType.FAILED_PAYMENT else Intervention.RESUME_CHARGE


# -- Per-case / per-arm results -------------------------------------------


@dataclass(frozen=True)
class CaseResult:
    case_index: int
    intervention: Intervention | None
    recovered: bool
    gross_recovered: int
    incentive_cost: int

    @property
    def nrr(self) -> int:
        """ADR-0013: `NRR(case) = gross_recovered(case) - incentive_cost(case)`."""
        return self.gross_recovered - self.incentive_cost


@dataclass(frozen=True)
class ArmResult:
    name: str
    case_results: list[CaseResult]
    resolved_decisions: list[ResolvedDecision] = field(default_factory=list)

    @property
    def total_nrr(self) -> int:
        """ADR-0013: "A batch's NRR is the sum (not average) of its cases' NRR"."""
        return sum(result.nrr for result in self.case_results)


# -- Shared arm constants -----------------------------------------------------

FIXED_RULE_DISCOUNT_PCT = 5.0
_MAX_ARM_CYCLES = 10  # mirrors app/simulator_driver.py's own safety bound
_NEUTRAL_QUALITY_SCORE = 0.5  # matches the estimator's own Beta(2,2) cold-start mean

# ADR-0016: the eval harness's estimator collapses to a single non-trivial
# cell (failure_reason and customer_segment_proxy are both constant across
# every simulated case), so there is no cross-case quality signal to ration a
# reserve on. A calibrated p-hat that converges below the allocator's
# min-quality gate would strand the reserved third for the AI arm while
# fixed_rule (fed a neutral 0.5) spends through -- an artefact of the
# single-cell harness, not a real allocation decision. Run every arm
# first-come-first-served instead. The live/demo path keeps
# app/allocator.py's _DEFAULT_RESERVE_RATIO = 1/3 untouched.
_EVAL_RESERVE_RATIO = 0.0


# -- No-intervention arm ---------------------------------------------------


def run_no_intervention_arm(
    cases: list[SimulatedCase],
    *,
    workflow_type: WorkflowType,
    case_value: int,
    run_seed: int,
    policy: PolicyConfig = DEFAULT_POLICY_CONFIG,
) -> ArmResult:
    """ADR-0013: "every case is always proposed NO_ACTION... `NRR(case)`
    collapses to `gross_recovered(case)` from the customer's organic
    (no-nudge) resolution behaviour, with zero incentive cost." A single,
    fatigue-free draw per case -- there is nothing to retry when nothing was
    ever proposed to begin with.

    Still routed through a fresh `StreamingAllocator`, same as every other
    arm ("each run as a full arm through the same Policy Engine and
    Streaming Allocator... as the AI treatment"): numerically inert today
    (a zero-cost proposal is always funded), kept for structural parity with
    `run_fixed_rule_arm` rather than silently skipping the one arm whose
    cost happens to be zero.
    """
    results = []
    for simulated in cases:
        case = RecoveryCase(workflow_type=workflow_type, source=EventSource.SIMULATED)
        policy_result = validate(case, ProposedIntervention(intervention=Intervention.NO_ACTION), policy, case_value=case_value)
        allocator = StreamingAllocator(BudgetLedger(recovery_budget=policy.recovery_budget, reserve_ratio=_EVAL_RESERVE_RATIO))
        allocation = allocator.decide(
            AllocationCandidate(case_id=case.id, point_estimate=_NEUTRAL_QUALITY_SCORE, uncertainty=0.0, incentive_amount=0)
        )
        gateway = SimulatorGateway(simulated.hidden, rng=random.Random(_case_seed(run_seed, simulated.case_index)))
        recovered = policy_result.approved and allocation.funded and gateway.resolve(Intervention.NO_ACTION)
        gross = case_value if recovered else 0
        results.append(
            CaseResult(
                case_index=simulated.case_index,
                intervention=Intervention.NO_ACTION,
                recovered=recovered,
                gross_recovered=gross,
                incentive_cost=0,
            )
        )
    return ArmResult(name="no_intervention", case_results=results)


# -- Fixed-rule arm ----------------------------------------------------------


def run_fixed_rule_arm(
    cases: list[SimulatedCase],
    *,
    workflow_type: WorkflowType,
    case_value: int,
    run_seed: int,
    policy: PolicyConfig = DEFAULT_POLICY_CONFIG,
) -> ArmResult:
    """ADR-0013: "every case is always proposed its workflow's cost-bearing
    intervention... at a flat 5% discount -- no Decision Engine estimate
    involved, just the hardcoded rate," run "through the same Policy Engine
    and Streaming Allocator... as the AI treatment -- only the proposed
    intervention differs." A fresh `StreamingAllocator` per case (never the
    live process-wide singleton) keeps this arm's spend isolated from every
    other arm's.

    No Decision Engine estimate exists for this arm by definition, so the
    Streaming Allocator's reserve-quality gate (app/allocator.py) is fed a
    neutral point_estimate/uncertainty (0.5/0.0) -- the same "no
    information" value the estimator's own cold start uses, with zero
    claimed confidence since this is a fixed rule, not a probabilistic
    estimate.
    """
    intervention = _workflow_intervention(workflow_type)
    incentive_amount = round(case_value * FIXED_RULE_DISCOUNT_PCT / 100)
    results = []
    for simulated in cases:
        case = RecoveryCase(workflow_type=workflow_type, source=EventSource.SIMULATED)
        gateway = SimulatorGateway(simulated.hidden, rng=random.Random(_case_seed(run_seed, simulated.case_index)))
        allocator = StreamingAllocator(BudgetLedger(recovery_budget=policy.recovery_budget, reserve_ratio=_EVAL_RESERVE_RATIO))

        recovered = False
        total_cost = 0
        for _cycle in range(_MAX_ARM_CYCLES):
            proposal = ProposedIntervention(
                intervention=intervention, discount_pct=FIXED_RULE_DISCOUNT_PCT, incentive_amount=incentive_amount
            )
            policy_result = validate(
                case, proposal, policy, budget_spent_so_far=allocator.ledger.spent, case_value=case_value
            )
            if not policy_result.approved:
                break

            allocation = allocator.decide(
                AllocationCandidate(
                    case_id=case.id,
                    point_estimate=_NEUTRAL_QUALITY_SCORE,
                    uncertainty=0.0,
                    incentive_amount=incentive_amount,
                )
            )
            if not allocation.funded:
                break

            outcome = gateway.resolve(intervention, incentive_amount=incentive_amount)
            total_cost += incentive_amount
            case.history.append(
                CaseHistoryEntry(
                    case_id=case.id,
                    entry_type=CaseHistoryEntryType.EXECUTION,
                    summary=f"fixed-rule {intervention.value} executed",
                    data={"intervention": intervention.value},
                )
            )
            if outcome:
                recovered = True
                break

        gross = case_value if recovered else 0
        results.append(
            CaseResult(
                case_index=simulated.case_index,
                intervention=intervention,
                recovered=recovered,
                gross_recovered=gross,
                incentive_cost=total_cost,
            )
        )
    return ArmResult(name="fixed_rule", case_results=results)


# -- Offline-optimal arm -----------------------------------------------------


def _recovers_within_attempt_budget(
    simulated: SimulatedCase, intervention: Intervention, seed: int, max_attempts: int
) -> bool:
    """Whether committing to `intervention` and retrying it (with fatigue
    decay, like any other repeated attempt on this case) up to `max_attempts`
    times would recover this case -- one candidate's fully-exhausted branch
    of the retrospective search below. A fresh `SimulatorGateway` per
    candidate so different candidates' attempt sequences don't consume each
    other's draws; each starts from the *same* per-case seed as every other
    arm's first attempt at this intervention (ADR-0013 pairing)."""
    gateway = SimulatorGateway(simulated.hidden, rng=random.Random(seed))
    return any(gateway.resolve(intervention) for _ in range(max_attempts))


def run_offline_optimal_arm(
    cases: list[SimulatedCase],
    *,
    workflow_type: WorkflowType,
    case_value: int,
    run_seed: int,
    max_attempts: int = _MAX_ARM_CYCLES,
) -> ArmResult:
    """CONTEXT.md: "a retrospective, batch-computed allocation over a case
    set already fully observed... never presented as a decision the agent
    itself made." For each case, evaluates every intervention valid for the
    workflow with full foresight and keeps whichever recovers.

    Every candidate gets a full, guaranteed `max_attempts` real draws,
    unconstrained by the Policy Engine's sequence-bound constraints
    (max_payment_retries etc.) that cap `fixed_rule`/`ai_treatment`'s actual
    attempt counts below that same ceiling, and uncomplicated by
    `ai_treatment`'s own uncertainty-driven cycles that don't land on the
    winning intervention at all. That's deliberate, not an oversight: an
    offline arm bound by the same practical guardrails a deployed policy
    needs wouldn't be an upper bound on what's *achievable* with foresight,
    just a replay of one arm's realized path -- CONTEXT.md's "best possible
    outcome" framing is exactly the ceiling this is meant to represent, not
    a strategy any online arm could literally execute. Every candidate's
    attempts replay the same per-case seed's draw sequence the other arms
    would see if they'd chosen that same intervention (ADR-0013 pairing).

    This arm's own candidates still cost 0, deliberately, unlike
    `fixed_rule`/`ai_treatment` since ticket 19/ADR-0014: it has no Policy
    Engine or Streaming Allocator in the loop at all (see this function's
    first paragraph), so there is no budget to spend against -- it degenerates
    to "recover for free whenever any candidate can, within the attempt
    budget" with no budget tradeoff to solve. A future ticket that wants this
    arm to also account for Incentive cost would need it to become a genuine
    budget-constrained knapsack over cases instead -- out of this ticket's
    scope, same as the rest of this arm's "no practical guardrails" design.
    """
    candidates = VALID_INTERVENTIONS[workflow_type]
    results = []
    for simulated in cases:
        seed = _case_seed(run_seed, simulated.case_index)
        recovering = [
            candidate
            for candidate in candidates
            if _recovers_within_attempt_budget(simulated, candidate, seed, max_attempts)
        ]
        recovered = bool(recovering)
        chosen = recovering[0] if recovering else None
        gross = case_value if recovered else 0
        results.append(
            CaseResult(
                case_index=simulated.case_index,
                intervention=chosen,
                recovered=recovered,
                gross_recovered=gross,
                incentive_cost=0,
            )
        )
    return ArmResult(name="offline_optimal", case_results=results)


# -- AI treatment arm ---------------------------------------------------------


def _ephemeral_engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


def run_ai_treatment_arm(
    cases: list[SimulatedCase], *, workflow_type: WorkflowType, case_value: int, run_seed: int
) -> ArmResult:
    """The real system, unmodified: `app/simulator_driver.py`'s
    `run_simulated_case`, driving `app/intake.py` + `app/lifecycle.py`
    exactly as a live webhook would (ticket 14). Runs against a throwaway
    in-memory database -- this is a batch evaluation run, not something
    sharing state with a live deployment.

    Resets the shared `Estimator` singleton to cold-start first (see this
    module's docstring): this is the one arm whose online learning is the
    thing being evaluated, so it's also the one arm allowed to touch it.

    Ticket 19/ADR-0014: `run_decision_cycle` now computes a real
    `incentive_amount` for a cost-bearing proposal, so this arm needs its own
    fresh `StreamingAllocator` too -- otherwise every case in the run would
    fall through to `run_decision_cycle`'s default, the process-wide
    singleton (app/allocator.py's `get_allocator()`), and one arm's spend
    would leak into live traffic's ledger or a later evaluation run's. Built
    against the canonical `DEFAULT_MERCHANT_CONFIG` (never a tuned demo
    value, per ADR-0014's evaluation-integrity boundary) and shared across
    every case in this call, mirroring the sibling baseline arms' "fresh
    per-arm allocator instance."
    """
    reset_estimator()
    engine = _ephemeral_engine()
    SQLModel.metadata.create_all(engine)
    allocator = StreamingAllocator(
        BudgetLedger(recovery_budget=DEFAULT_MERCHANT_CONFIG.recovery_budget, reserve_ratio=_EVAL_RESERVE_RATIO)
    )

    results = []
    resolved_decisions: list[ResolvedDecision] = []
    with Session(engine) as session:
        for simulated in cases:
            outcome = run_simulated_case(
                session,
                simulated,
                workflow_type=workflow_type,
                rng=random.Random(_case_seed(run_seed, simulated.case_index)),
                allocator=allocator,
            )
            resolved_decisions.extend(outcome.resolved_decisions)
            incentive_cost = _total_incentive_cost(outcome.case)
            gross = case_value if outcome.recovered else 0
            chosen = _last_decided_intervention(outcome.case)
            results.append(
                CaseResult(
                    case_index=simulated.case_index,
                    intervention=chosen,
                    recovered=outcome.recovered,
                    gross_recovered=gross,
                    incentive_cost=incentive_cost,
                )
            )
    return ArmResult(name="ai_treatment", case_results=results, resolved_decisions=resolved_decisions)


def _total_incentive_cost(case: RecoveryCase) -> int:
    """Sum of `incentive_amount` actually incurred across every EXECUTION
    entry on this case (ADR-0013: "the sum of incentive amounts actually
    incurred across every intervention executed on that case") -- a case can
    be executed on more than once across reassessment cycles, same as
    `fixed_rule`'s own `total_cost` accumulation."""
    return sum(
        int(entry.data.get("incentive_amount", 0))
        for entry in case.history
        if entry.entry_type == CaseHistoryEntryType.EXECUTION
    )


def _last_decided_intervention(case: RecoveryCase) -> Intervention | None:
    decisions = [entry for entry in case.history if entry.entry_type == CaseHistoryEntryType.DECISION]
    if not decisions:
        return None
    return Intervention(decisions[-1].data["intervention"])


# -- Bootstrap CI on the paired gap (ADR-0013) -------------------------------


@dataclass(frozen=True)
class BootstrapResult:
    baseline_name: str
    point_estimate: float  # mean of the actual per-case gaps
    ci_lower: float  # 2.5th percentile of the resampled means
    ci_upper: float  # 97.5th percentile of the resampled means


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (numpy's default 'linear' method),
    implemented directly -- this repo has no numpy/scipy dependency
    (app/estimator.py's own precedent: "no scipy dependency")."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = (pct / 100) * (len(sorted_values) - 1)
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = index - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def bootstrap_gap_ci(
    ai_arm: ArmResult, baseline_arm: ArmResult, *, n_resamples: int = 10_000, rng: random.Random
) -> BootstrapResult:
    """ADR-0013's exact procedure: "compute the per-case paired gap
    `gap(case) = NRR_AI(case) - NRR_baseline(case)`... resample these
    per-case gaps with replacement 10,000 times, take the mean gap per
    resample, and report the point estimate (mean of the actual gaps)
    alongside the 95% percentile interval (2.5th-97.5th percentile of the
    resampled means)." `rng` is caller-supplied so a rerun with the same
    seed reproduces the same CI, not just the same point estimate.
    """
    ai_by_case = {result.case_index: result.nrr for result in ai_arm.case_results}
    baseline_by_case = {result.case_index: result.nrr for result in baseline_arm.case_results}
    case_indices = sorted(ai_by_case.keys() & baseline_by_case.keys())
    gaps = [ai_by_case[i] - baseline_by_case[i] for i in case_indices]

    point_estimate = sum(gaps) / len(gaps)
    resampled_means = []
    for _ in range(n_resamples):
        sample = [gaps[rng.randrange(len(gaps))] for _ in range(len(gaps))]
        resampled_means.append(sum(sample) / len(sample))
    resampled_means.sort()

    return BootstrapResult(
        baseline_name=baseline_arm.name,
        point_estimate=point_estimate,
        ci_lower=_percentile(resampled_means, 2.5),
        ci_upper=_percentile(resampled_means, 97.5),
    )


# -- Calibration curve --------------------------------------------------------


@dataclass(frozen=True)
class CalibrationBucket:
    bucket_low: float
    bucket_high: float
    mean_predicted: float
    observed_rate: float
    count: int


def calibration_curve(resolved_decisions: list[ResolvedDecision], *, n_buckets: int = 10) -> list[CalibrationBucket]:
    """Predicted vs. actual recovery probability for the estimator (ticket
    15's own acceptance criterion). Fixed-width bins (not quantile-based
    deciles): the estimator's point estimates come from a small number of
    discrete per-cell posteriors, not a continuous spread, so quantile
    splitting could produce degenerate bins; fixed width handles that
    sparsity gracefully. Empty bins are omitted."""
    width = 1.0 / n_buckets
    buckets: list[CalibrationBucket] = []
    for i in range(n_buckets):
        low, high = i * width, (i + 1) * width
        in_bucket = [
            d for d in resolved_decisions if low <= d.point_estimate < high or (high == 1.0 and d.point_estimate == 1.0)
        ]
        if not in_bucket:
            continue
        buckets.append(
            CalibrationBucket(
                bucket_low=low,
                bucket_high=high,
                mean_predicted=sum(d.point_estimate for d in in_bucket) / len(in_bucket),
                observed_rate=sum(d.recovered for d in in_bucket) / len(in_bucket),
                count=len(in_bucket),
            )
        )
    return buckets


# -- Top-level evaluation run -------------------------------------------------


@dataclass(frozen=True)
class EvaluationReport:
    run_seed: int
    workflow_type: WorkflowType
    arms: dict[str, ArmResult]
    bootstrap_results: list[BootstrapResult]
    calibration: list[CalibrationBucket]

    def incremental_recovery(self, baseline_name: str) -> float:
        """CONTEXT.md's Incremental Recovery, in NRR terms: the AI arm's
        bootstrap point-estimate gap over the named baseline."""
        return next(r.point_estimate for r in self.bootstrap_results if r.baseline_name == baseline_name)

    def pct_of_offline_optimal_captured(self) -> float:
        """ADR-0013: "% of offline-optimal NRR captured" by the AI arm."""
        offline_nrr = self.arms["offline_optimal"].total_nrr
        if offline_nrr == 0:
            return 0.0
        return self.arms["ai_treatment"].total_nrr / offline_nrr


def run_evaluation(
    cases: list[SimulatedCase],
    *,
    run_seed: int,
    workflow_type: WorkflowType = WorkflowType.FAILED_PAYMENT,
    case_value: int = DEFAULT_CASE_AMOUNT,
    policy: PolicyConfig = DEFAULT_POLICY_CONFIG,
    n_bootstrap_resamples: int = 10_000,
) -> EvaluationReport:
    """Runs all four arms over the same case stream (ADR-0013's paired
    counterfactual replay) and reports NRR, Incremental Recovery (via
    bootstrap CI), and a calibration curve. `held_out` per ADR-0013 is meant
    to be touched exactly once, for the final reported headline comparison
    -- this function has no code path that feeds its results back into the
    estimator's parameters or any policy/config threshold, regardless of
    which split is passed in; enforcing "touch it once" is the caller's
    discipline (dev/validation/held-out are picked and passed here, not
    looped over internally).

    Defaults to `FAILED_PAYMENT`: `HALTED_SUBSCRIPTION`'s `case_value`
    always resolves to 0 (a disclosed gap since ticket 12 -- the Subscription
    entity carries no `amount` field), which would make every case's
    `gross_recovered` structurally 0 regardless of outcome and the whole
    comparison meaningless for that workflow until that gap closes. The
    parameter is still exposed (not hardcoded) for when it does.
    """
    no_intervention = run_no_intervention_arm(cases, workflow_type=workflow_type, case_value=case_value, run_seed=run_seed)
    fixed_rule = run_fixed_rule_arm(
        cases, workflow_type=workflow_type, case_value=case_value, run_seed=run_seed, policy=policy
    )
    offline_optimal = run_offline_optimal_arm(
        cases, workflow_type=workflow_type, case_value=case_value, run_seed=run_seed
    )
    ai_treatment = run_ai_treatment_arm(cases, workflow_type=workflow_type, case_value=case_value, run_seed=run_seed)

    bootstrap_rng = random.Random(_case_seed(run_seed, -1))  # -1: never a valid case_index, so no collision
    bootstrap_results = [
        bootstrap_gap_ci(ai_treatment, baseline, n_resamples=n_bootstrap_resamples, rng=bootstrap_rng)
        for baseline in (no_intervention, fixed_rule)
    ]

    return EvaluationReport(
        run_seed=run_seed,
        workflow_type=workflow_type,
        arms={arm.name: arm for arm in (no_intervention, fixed_rule, offline_optimal, ai_treatment)},
        bootstrap_results=bootstrap_results,
        calibration=calibration_curve(ai_treatment.resolved_decisions),
    )


# -- JSON artifact for the dashboard (ticket 18) ---------------------------

# The evaluation harness is expensive (four arms over 650 cases + 10k
# bootstrap resamples) and deterministic, so ticket 18's dashboard reads a
# cached artifact written by `python -m app.evaluation` rather than
# recomputing it in an HTTP handler. Anchored to the backend dir the same
# way app/config.py anchors the .env path.
DEFAULT_REPORT_PATH = Path(__file__).resolve().parent.parent / "evaluation_report.json"


def report_to_dict(report: EvaluationReport) -> dict[str, Any]:
    """A JSON-serializable projection of an `EvaluationReport` -- exactly the
    numbers test2108.md §13 items 5-6 want on screen (NRR vs. both baselines
    with an interval and % of offline-optimal, plus the calibration curve)."""
    return {
        "run_seed": report.run_seed,
        "workflow_type": report.workflow_type.value,
        "arms": {
            name: {
                "total_nrr": arm.total_nrr,
                "case_count": len(arm.case_results),
                "recovered_count": sum(1 for r in arm.case_results if r.recovered),
            }
            for name, arm in report.arms.items()
        },
        "baselines": [
            {
                "baseline_name": b.baseline_name,
                "incremental_nrr": b.point_estimate,
                "ci_lower": b.ci_lower,
                "ci_upper": b.ci_upper,
            }
            for b in report.bootstrap_results
        ],
        "pct_of_offline_optimal": report.pct_of_offline_optimal_captured(),
        "calibration": [
            {
                "bucket_low": c.bucket_low,
                "bucket_high": c.bucket_high,
                "mean_predicted": c.mean_predicted,
                "observed_rate": c.observed_rate,
                "count": c.count,
            }
            for c in report.calibration
        ],
    }


def _split_cases(split: str, seed: int) -> list[SimulatedCase]:
    splits = generate_dataset_splits(seed)
    return {"dev": splits.dev, "validation": splits.validation, "held_out": splits.held_out}[split]


# Default to `dev` for the dashboard artifact: it is a demo/inspection view
# refreshed freely, and ADR-0013 reserves `held_out` for the single final
# headline run. Pass `--split held_out` explicitly for that one.
DASHBOARD_SPLIT = "dev"


def write_report(
    *,
    split: str = DASHBOARD_SPLIT,
    dataset_seed: int = DEFAULT_DATASET_SEED,
    run_seed: int = DEFAULT_DATASET_SEED,
    out_path: Path = DEFAULT_REPORT_PATH,
    n_bootstrap_resamples: int = 10_000,
) -> Path:
    """Runs the harness once on `split` and writes the JSON artifact the
    dashboard serves. Returns the path written."""
    report = run_evaluation(
        _split_cases(split, dataset_seed),
        run_seed=run_seed,
        n_bootstrap_resamples=n_bootstrap_resamples,
    )
    payload = report_to_dict(report) | {"split": split}
    out_path.write_text(json.dumps(payload, indent=2))
    return out_path


def _main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the evaluation harness and write its JSON report (ticket 18).")
    parser.add_argument("--split", choices=("dev", "validation", "held_out"), default=DASHBOARD_SPLIT)
    parser.add_argument("--dataset-seed", type=int, default=DEFAULT_DATASET_SEED)
    parser.add_argument("--run-seed", type=int, default=DEFAULT_DATASET_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--bootstrap-resamples", type=int, default=10_000)
    args = parser.parse_args(argv)

    path = write_report(
        split=args.split,
        dataset_seed=args.dataset_seed,
        run_seed=args.run_seed,
        out_path=args.out,
        n_bootstrap_resamples=args.bootstrap_resamples,
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    _main()
