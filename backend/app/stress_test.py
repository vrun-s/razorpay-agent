"""Ticket 16: misspecification stress test (ADR-0007's robustness check).

Reruns ticket 15's paired evaluation (app/evaluation.py's `run_evaluation`),
unchanged, against three scenarios where one of the frozen generator's
parameters (app/simulator/personas.py's `PERSONA_MIX`, app/simulator/
response_curves.py's `BASE_RESPONSE_CURVES`/`FATIGUE_DECAY_RATE`) is
deliberately perturbed by ~20%. Each perturbation is applied in the
direction that makes the AI-vs-baseline claim *harder* to sustain, not an
arbitrary or favorable one -- the point of a stress test is to check the
claim against its least favorable case, not its best one:

- Persona mix: every persona's weight scaled by roughly ±20% -- the two
  higher-converting personas (LOYAL, BARGAIN_HUNTER) down, the two
  lower-converting ones (NEW, UNRELIABLE_PAYER) up, renormalized to 1.0.
- Response-curve elasticities: every base recovery probability scaled
  down 20% -- every case is harder to recover than assumed.
- Fatigue decay rate: decays 20% faster -- retries are worth less than
  the baseline models, compressing any arm's multi-attempt advantage.

**No estimator retuning** (ticket 16's own explicit criterion): every
scenario reruns `run_evaluation` exactly as ticket 15 built it -- same AI
arm, same Policy Engine, same Streaming Allocator, same fixed-rule
discount, same bootstrap procedure, same Beta(2,2) cold start reset fresh
per run (there's no separately-fitted estimator artifact to vary between
scenarios; "the exact same trained/fitted estimator configuration" is the
same online-learning procedure, applied fresh each time).

**Perturbation mechanics.** Persona mix and response curves are consumed
only at population-generation time (`generate_population`), so perturbing
them needs no changes to `run_evaluation` itself -- a perturbed population
is generated once per scenario and fed into the unmodified harness.
Fatigue decay rate is different: it's read fresh, every call, directly out
of `app.simulator.response_curves`'s own module globals by
`decayed_probability` (not cached or bound at another module's import
time), deep inside `run_evaluation`'s call graph
(`SimulatorGateway.resolve()`). Threading an explicit override parameter
through every intermediate function between `run_evaluation` and that call
would mean re-touching already-committed, already-tested ticket 14/15
code for one stress-test scenario. Temporarily reassigning that module
attribute for the scenario's duration (restored in a `finally`, matching
`app/estimator.py`'s `reset_estimator()` precedent for "a batch script
deliberately mutating shared state, documented, single-process, ADR-0008")
achieves the same effect without touching that code at all.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

import app.simulator.response_curves as response_curves_module
from app.evaluation import EvaluationReport, run_evaluation
from app.models import WorkflowType
from app.policy import DEFAULT_POLICY_CONFIG, PolicyConfig
from app.simulator.generator import SimulatedCase, generate_population
from app.simulator.personas import PERSONA_MIX, Persona
from app.simulator.response_curves import BASE_RESPONSE_CURVES

PERTURBATION_MAGNITUDE = 0.20

# Pessimistic direction per persona, ranked by average response probability
# across BASE_RESPONSE_CURVES's three interventions (LOYAL .50, BARGAIN_HUNTER
# .32, NEW .27, UNRELIABLE_PAYER .14): the two higher-converting personas lose
# share, the two lower-converting ones gain it.
_PESSIMISTIC_PERSONA_DIRECTION: dict[Persona, float] = {
    Persona.LOYAL: 1 - PERTURBATION_MAGNITUDE,
    Persona.BARGAIN_HUNTER: 1 - PERTURBATION_MAGNITUDE,
    Persona.NEW: 1 + PERTURBATION_MAGNITUDE,
    Persona.UNRELIABLE_PAYER: 1 + PERTURBATION_MAGNITUDE,
}


def _perturbed_persona_mix() -> dict[Persona, float]:
    """Every persona's weight scaled by roughly ±20% -- the two
    higher-converting personas scaled down, the two lower-converting ones
    scaled up, then renormalized to sum to 1.0. Renormalization nudges each
    persona's *exact* post-perturbation share a couple points off a clean
    20% (the ticket says "roughly ±20%"), but every persona moves -- unlike
    a single pairwise transfer, where only one persona's share would."""
    scaled = {persona: PERSONA_MIX[persona] * _PESSIMISTIC_PERSONA_DIRECTION[persona] for persona in PERSONA_MIX}
    total = sum(scaled.values())
    return {persona: weight / total for persona, weight in scaled.items()}


def _perturbed_response_curves() -> dict[Persona, dict]:
    """Every (persona, intervention) base probability scaled down 20%."""
    return {
        persona: {intervention: probability * (1 - PERTURBATION_MAGNITUDE) for intervention, probability in curve.items()}
        for persona, curve in BASE_RESPONSE_CURVES.items()
    }


@contextlib.contextmanager
def _perturbed_fatigue_decay_rate():
    """Temporarily scales `FATIGUE_DECAY_RATE` down 20% (faster decay),
    restoring the original value even if the scenario run raises."""
    original = response_curves_module.FATIGUE_DECAY_RATE
    response_curves_module.FATIGUE_DECAY_RATE = original * (1 - PERTURBATION_MAGNITUDE)
    try:
        yield
    finally:
        response_curves_module.FATIGUE_DECAY_RATE = original


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    report: EvaluationReport
    survived: bool  # AI-vs-baseline lift stayed significant against both baselines


def _lift_survives(report: EvaluationReport) -> bool:
    """A scenario "survives" if the AI-vs-baseline lift stays significant
    (95% CI lower bound above 0 -- excludes a zero-or-negative gap) against
    *both* baselines, not just the weaker no-intervention one. ADR-0007
    refers to "the AI-vs-baseline lift" in the singular even though ticket
    15 reports two separate CIs (never blended into one number); requiring
    both to hold is the more conservative reading, and the one that
    actually supports "the AI system beats the simplest alternatives too,"
    not just doing nothing.
    """
    return all(result.ci_lower > 0 for result in report.bootstrap_results)


def run_stress_test(
    cases: list[SimulatedCase],
    *,
    run_seed: int,
    workflow_type: WorkflowType = WorkflowType.FAILED_PAYMENT,
    policy: PolicyConfig = DEFAULT_POLICY_CONFIG,
    n_bootstrap_resamples: int = 10_000,
) -> StressTestReport:
    """Runs the baseline (unperturbed) evaluation plus all three perturbed
    scenarios and reports whether the lift survives in at least 2 of 3 --
    every scenario's full report is included regardless of outcome (a
    failed stress test is documented, not hidden, per ticket 16's own
    acceptance criterion)."""

    def _run(evaluation_cases: list[SimulatedCase]) -> EvaluationReport:
        return run_evaluation(
            evaluation_cases,
            run_seed=run_seed,
            workflow_type=workflow_type,
            policy=policy,
            n_bootstrap_resamples=n_bootstrap_resamples,
        )

    baseline_report = _run(cases)

    persona_mix_cases = generate_population(run_seed, len(cases), persona_mix=_perturbed_persona_mix())
    persona_mix_report = _run(persona_mix_cases)

    response_curve_cases = generate_population(run_seed, len(cases), response_curves=_perturbed_response_curves())
    response_curve_report = _run(response_curve_cases)

    with _perturbed_fatigue_decay_rate():
        fatigue_decay_report = _run(cases)

    scenarios = [
        ScenarioResult(name="persona_mix", report=persona_mix_report, survived=_lift_survives(persona_mix_report)),
        ScenarioResult(
            name="response_curve_elasticities", report=response_curve_report, survived=_lift_survives(response_curve_report)
        ),
        ScenarioResult(name="fatigue_decay_rate", report=fatigue_decay_report, survived=_lift_survives(fatigue_decay_report)),
    ]

    return StressTestReport(baseline=baseline_report, scenarios=scenarios)


@dataclass(frozen=True)
class StressTestReport:
    baseline: EvaluationReport
    scenarios: list[ScenarioResult]

    @property
    def survived_count(self) -> int:
        return sum(scenario.survived for scenario in self.scenarios)

    @property
    def passed(self) -> bool:
        """ADR-0007: "the AI-vs-baseline lift must survive under at least 2 of the 3 perturbations"."""
        return self.survived_count >= 2
