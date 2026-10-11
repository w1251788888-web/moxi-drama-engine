"""SaaS 额度计费服务：按真实 AI 成本折算用户额度。"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


DEFAULT_BILLING_MULTIPLIER = Decimal("5")
DEFAULT_INPUT_COST_CNY_PER_1K = Decimal("0.002")
DEFAULT_OUTPUT_COST_CNY_PER_1K = Decimal("0.008")
MINIMUM_ACTUAL_COST_CNY = Decimal("0.01")


@dataclass(frozen=True)
class BillableCredit:
    actual_cost_cny: Decimal
    multiplier: Decimal
    credit_amount: Decimal


def _money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_billable_credit(
    actual_cost_cny: Decimal | int | float | str,
    *,
    multiplier: Decimal | int | float | str = DEFAULT_BILLING_MULTIPLIER,
) -> BillableCredit:
    """把真实 AI 成本换算成用户扣费额度。

    当前规则：1 额度 = 1 元人民币，用户扣费 = 真实 AI 成本 * 5。
    """
    actual = _money(actual_cost_cny)
    rate = Decimal(str(multiplier))
    credit = _money(actual * rate)
    return BillableCredit(
        actual_cost_cny=actual,
        multiplier=rate,
        credit_amount=credit,
    )


def estimate_generation_actual_cost_cny(
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    input_cost_per_1k: Decimal | int | float | str = DEFAULT_INPUT_COST_CNY_PER_1K,
    output_cost_per_1k: Decimal | int | float | str = DEFAULT_OUTPUT_COST_CNY_PER_1K,
    minimum_actual_cost_cny: Decimal | int | float | str = MINIMUM_ACTUAL_COST_CNY,
) -> Decimal:
    """按 token 估算一次生成的真实成本。

    现阶段不同供应商价格未完全接入后台配置，先使用保守默认单价，
    并设置最小真实成本，避免 0 token mock/降级场景绕过额度流水。
    """
    input_tokens = max(0, int(prompt_tokens or 0))
    output_tokens = max(0, int(completion_tokens or 0))
    input_rate = Decimal(str(input_cost_per_1k))
    output_rate = Decimal(str(output_cost_per_1k))
    minimum = Decimal(str(minimum_actual_cost_cny))
    actual = (
        Decimal(input_tokens) / Decimal("1000") * input_rate
        + Decimal(output_tokens) / Decimal("1000") * output_rate
    )
    if actual < minimum:
        actual = minimum
    return _money(actual)
