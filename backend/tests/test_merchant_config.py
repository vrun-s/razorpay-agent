"""Ticket 19/ADR-0014: MerchantConfig unifies recovery_budget across the
Policy Engine and Streaming Allocator, and adds incentive_pct."""

from app.allocator import get_allocator
from app.merchant_config import DEFAULT_MERCHANT_CONFIG, MerchantConfig
from app.policy import DEFAULT_POLICY_CONFIG


def test_default_incentive_pct_is_5_percent():
    assert DEFAULT_MERCHANT_CONFIG.incentive_pct == 5.0


def test_policy_configs_recovery_budget_derives_from_merchant_config():
    assert DEFAULT_POLICY_CONFIG.recovery_budget == DEFAULT_MERCHANT_CONFIG.recovery_budget


def test_default_allocators_ledger_derives_from_the_same_merchant_config():
    assert get_allocator().ledger.recovery_budget == DEFAULT_MERCHANT_CONFIG.recovery_budget


def test_merchant_config_is_immutable():
    config = MerchantConfig(recovery_budget=1000, incentive_pct=3.0)
    try:
        config.incentive_pct = 4.0  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised
