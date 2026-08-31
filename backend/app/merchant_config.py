"""Ticket 19 / ADR-0014: the merchant-configured knobs that used to be two
independently-set copies -- `PolicyConfig.recovery_budget` (the Policy
Engine's ceiling) and `BudgetLedger.recovery_budget` (the Streaming
Allocator's ledger), flagged as a disclosed gap in app/allocator.py -- now
collapse to one object both derive from. Also the new home for
`incentive_pct`, the flat rate (ADR-0014) that turns a chosen `PAYMENT_RETRY`/
`RESUME_CHARGE` proposal into a real, budget-consuming Incentive.

A leaf module (no dependencies on policy/allocator/lifecycle) so every one of
them can import it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MerchantConfig:
    recovery_budget: int  # paise, same convention as Payment.amount
    incentive_pct: float = 5.0  # ADR-0014: numerically matches FIXED_RULE_DISCOUNT_PCT, kept as an independent constant


DEFAULT_MERCHANT_CONFIG = MerchantConfig(recovery_budget=1_000_000)  # INR 10,000 in paise, matching the prior DEFAULT_POLICY_CONFIG default
