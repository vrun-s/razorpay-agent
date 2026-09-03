"""SPIKE (P1 eval) -- THROWAWAY. Runs the evaluation harness on the dev split
at five recovery-budget levels and prints the kill-criteria verdict.

    python -m spike_p1_budget_sweep      (from backend/)

Question: does the AI arm separate from `fixed_rule` on NRR once the budget
binds? Kill criteria (proceed to clean P1 only if all hold) -- at the two
tightest budgets:
  1. AI-vs-fixed_rule bootstrap NRR gap point estimate positive,
  2. CI lower bound >= 0 at >= 1 level,
  3. AI captures a higher %% of the budget-constrained offline-optimal than
     fixed_rule does.
"""

from __future__ import annotations

from app.evaluation import DEFAULT_DATASET_SEED, generate_dataset_splits, run_evaluation

# Rs -> paise
BUDGETS = [2_000, 5_000, 10_000, 25_000, 50_000]
TIGHTEST = {2_000, 5_000}


def _pct_of_offline(arm_nrr: int, offline_nrr: int) -> float:
    return arm_nrr / offline_nrr if offline_nrr else 0.0


def main() -> None:
    dev = generate_dataset_splits(DEFAULT_DATASET_SEED).dev
    print(f"dev split: {len(dev)} cases\n")

    rows = []
    for budget_rupees in BUDGETS:
        report = run_evaluation(
            dev,
            run_seed=DEFAULT_DATASET_SEED,
            recovery_budget=budget_rupees * 100,
            n_bootstrap_resamples=10_000,
        )
        ai = report.arms["ai_treatment"].total_nrr
        fr = report.arms["fixed_rule"].total_nrr
        ni = report.arms["no_intervention"].total_nrr
        oo = report.arms["offline_optimal"].total_nrr
        boot = next(b for b in report.bootstrap_results if b.baseline_name == "fixed_rule")
        ai_pct = _pct_of_offline(ai, oo)
        fr_pct = _pct_of_offline(fr, oo)
        rows.append(
            {
                "budget": budget_rupees,
                "ai": ai, "fr": fr, "ni": ni, "oo": oo,
                "gap": boot.point_estimate, "ci_lo": boot.ci_lower, "ci_hi": boot.ci_upper,
                "ai_pct": ai_pct, "fr_pct": fr_pct,
                "ai_rec": sum(r.recovered for r in report.arms["ai_treatment"].case_results),
                "fr_rec": sum(r.recovered for r in report.arms["fixed_rule"].case_results),
                "ai_spend": sum(r.incentive_cost for r in report.arms["ai_treatment"].case_results),
                "fr_spend": sum(r.incentive_cost for r in report.arms["fixed_rule"].case_results),
            }
        )

    hdr = (
        f"{'budget':>8} | {'AI NRR':>12} {'fixed NRR':>12} {'offline NRR':>12} | "
        f"{'AI-fixed gap':>13} {'CI low':>11} {'CI high':>11} | {'AI %opt':>8} {'fix %opt':>8} | "
        f"{'AI rec':>7} {'fix rec':>7} | {'AI spend':>10} {'fix spend':>10}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['budget']:>8} | {r['ai']:>12,} {r['fr']:>12,} {r['oo']:>12,} | "
            f"{r['gap']:>13,.1f} {r['ci_lo']:>11,.1f} {r['ci_hi']:>11,.1f} | "
            f"{r['ai_pct']:>7.1%} {r['fr_pct']:>7.1%} | {r['ai_rec']:>7} {r['fr_rec']:>7} | "
            f"{r['ai_spend']:>10,} {r['fr_spend']:>10,}"
        )

    print("\n--- KILL CRITERIA (two tightest budgets: Rs 2k, Rs 5k) ---")
    tight = [r for r in rows if r["budget"] in TIGHTEST]
    c1 = all(r["gap"] > 0 for r in tight)
    c2 = any(r["ci_lo"] >= 0 for r in tight)
    c3 = all(r["ai_pct"] > r["fr_pct"] for r in tight)
    for name, ok, detail in [
        ("1. AI-vs-fixed gap point estimate positive at both", c1,
         ", ".join(f"Rs{r['budget']}: {r['gap']:,.0f}" for r in tight)),
        ("2. CI lower bound >= 0 at >= 1 level", c2,
         ", ".join(f"Rs{r['budget']}: {r['ci_lo']:,.0f}" for r in tight)),
        ("3. AI %opt > fixed %opt at both", c3,
         ", ".join(f"Rs{r['budget']}: {r['ai_pct']:.1%} vs {r['fr_pct']:.1%}" for r in tight)),
    ]:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")
    verdict = "PROCEED to Phase 2 (clean P1)" if (c1 and c2 and c3) else "STOP -- back to /grill-with-docs to rethink P1"
    print(f"\n  VERDICT: {verdict}")


if __name__ == "__main__":
    main()
