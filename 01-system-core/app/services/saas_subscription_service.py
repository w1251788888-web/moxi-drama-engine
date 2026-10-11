"""SaaS 套餐订阅与 Demo 支付服务。"""
from __future__ import annotations

import secrets
import hmac
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models.saas_admin import CreditLedger, PaymentOrder, SubscriptionPlan, UserAccessKey


PAYMENT_WEBHOOK_SECRET_ENV = "MOXI_PAYMENT_WEBHOOK_SECRET"


DEFAULT_SUBSCRIPTION_PLANS = [
    {
        "code": "starter",
        "name": "体验套餐",
        "description": "适合试跑短剧主链路，包含基础生成额度。",
        "price_cny": Decimal("19.90"),
        "credit_amount": Decimal("30.00"),
        "advanced_generation_enabled": False,
        "validity_days": 30,
        "sort_order": 10,
    },
    {
        "code": "creator",
        "name": "创作套餐",
        "description": "适合连续创作，开通高级生成链路并发放更多额度。",
        "price_cny": Decimal("99.00"),
        "credit_amount": Decimal("180.00"),
        "advanced_generation_enabled": True,
        "validity_days": 30,
        "sort_order": 20,
    },
    {
        "code": "studio",
        "name": "工作室套餐",
        "description": "适合小团队集中生产，额度更多，有效期更长。",
        "price_cny": Decimal("299.00"),
        "credit_amount": Decimal("680.00"),
        "advanced_generation_enabled": True,
        "validity_days": 90,
        "sort_order": 30,
    },
]


@dataclass(frozen=True)
class SubscriptionPlanItem:
    plan_id: str
    code: str
    name: str
    description: str
    price_cny: float
    credit_amount: float
    advanced_generation_enabled: bool
    validity_days: int
    status: str
    sort_order: int
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True)
class PaymentOrderItem:
    order_id: str
    order_no: str
    access_key_id: str
    front_user_id: str
    plan_id: str
    plan_code: str
    plan_name: str
    amount_cny: float
    credit_amount: float
    provider: str
    status: str
    human_reason: str
    paid_at: str | None
    created_at: str | None
    credit_balance: float | None = None
    advanced_generation_enabled: bool | None = None


def _money(value: Decimal | int | float | str | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money_float(value: Decimal | int | float | str | None) -> float:
    return float(_money(value))


def payment_webhook_secret_from_env() -> str:
    return os.getenv(PAYMENT_WEBHOOK_SECRET_ENV, "").strip()


def build_payment_webhook_signature(
    secret: str,
    *,
    order_no: str,
    amount_cny: Decimal | int | float | str,
    provider_trade_no: str = "",
) -> str:
    payload = f"{str(order_no or '').strip()}|{_money(amount_cny)}|{str(provider_trade_no or '').strip()}"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _normalize_code(code: str) -> str:
    normalized = str(code or "").strip().lower()
    if not normalized:
        raise ValueError("套餐 code 不能为空")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    if any(ch not in allowed for ch in normalized):
        raise ValueError("套餐 code 只能包含小写字母、数字、- 和 _")
    return normalized


def _plan_item(row: SubscriptionPlan) -> SubscriptionPlanItem:
    return SubscriptionPlanItem(
        plan_id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        price_cny=_money_float(row.price_cny),
        credit_amount=_money_float(row.credit_amount),
        advanced_generation_enabled=bool(row.advanced_generation_enabled),
        validity_days=int(row.validity_days or 0),
        status=row.status,
        sort_order=int(row.sort_order or 100),
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def _order_item(
    row: PaymentOrder,
    *,
    credit_balance: Decimal | int | float | str | None = None,
    advanced_generation_enabled: bool | None = None,
) -> PaymentOrderItem:
    return PaymentOrderItem(
        order_id=row.id,
        order_no=row.order_no,
        access_key_id=row.access_key_id,
        front_user_id=row.front_user_id,
        plan_id=row.plan_id,
        plan_code=row.plan_code,
        plan_name=row.plan_name,
        amount_cny=_money_float(row.amount_cny),
        credit_amount=_money_float(row.credit_amount),
        provider=row.provider,
        status=row.status,
        human_reason=row.human_reason,
        paid_at=row.paid_at.isoformat() if row.paid_at else None,
        created_at=row.created_at.isoformat() if row.created_at else None,
        credit_balance=_money_float(credit_balance) if credit_balance is not None else None,
        advanced_generation_enabled=advanced_generation_enabled,
    )


def ensure_default_subscription_plans(db: Session) -> None:
    changed = False
    for item in DEFAULT_SUBSCRIPTION_PLANS:
        exists = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == item["code"]).first()
        if exists:
            continue
        db.add(SubscriptionPlan(
            code=str(item["code"]),
            name=str(item["name"]),
            description=str(item["description"]),
            price_cny=_money(item["price_cny"]),
            credit_amount=_money(item["credit_amount"]),
            advanced_generation_enabled=bool(item["advanced_generation_enabled"]),
            validity_days=int(item["validity_days"]),
            status="active",
            sort_order=int(item["sort_order"]),
        ))
        changed = True
    if changed:
        db.commit()


def list_subscription_plans(db: Session, *, include_inactive: bool = False) -> list[SubscriptionPlanItem]:
    ensure_default_subscription_plans(db)
    query = db.query(SubscriptionPlan)
    if not include_inactive:
        query = query.filter(SubscriptionPlan.status == "active")
    rows = query.order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.created_at.asc()).all()
    return [_plan_item(row) for row in rows]


def save_subscription_plan(db: Session, payload: dict) -> SubscriptionPlanItem:
    code = _normalize_code(str(payload.get("code") or ""))
    row = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == code).first()
    if row is None:
        row = SubscriptionPlan(code=code)
        db.add(row)

    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("套餐名称不能为空")
    price = _money(payload.get("price_cny"))
    credit = _money(payload.get("credit_amount"))
    if price < 0 or credit < 0:
        raise ValueError("套餐价格和额度不能小于 0")

    status = str(payload.get("status") or row.status or "active").strip()
    if status not in {"active", "disabled", "draft"}:
        raise ValueError("套餐状态只能是 active、disabled 或 draft")

    row.name = name
    row.description = str(payload.get("description") or "").strip()
    row.price_cny = price
    row.credit_amount = credit
    row.advanced_generation_enabled = bool(payload.get("advanced_generation_enabled"))
    row.validity_days = max(0, int(payload.get("validity_days") or 0))
    row.status = status
    row.sort_order = int(payload.get("sort_order") or 100)
    row.updated_at = datetime.now()
    db.commit()
    db.refresh(row)
    return _plan_item(row)


def list_payment_orders(db: Session, *, access_key_id: str = "") -> list[PaymentOrderItem]:
    query = db.query(PaymentOrder).order_by(PaymentOrder.created_at.desc())
    normalized_key = str(access_key_id or "").strip()
    if normalized_key:
        query = query.filter(PaymentOrder.access_key_id == normalized_key)
    return [_order_item(row) for row in query.limit(300).all()]


def create_pending_checkout_order(
    db: Session,
    *,
    access_key_id: str,
    plan_id: str,
    provider: str = "mock_gateway",
) -> PaymentOrderItem:
    ensure_default_subscription_plans(db)
    key_row = db.query(UserAccessKey).filter(UserAccessKey.id == str(access_key_id or "").strip()).first()
    if key_row is None or key_row.status != "active":
        raise ValueError("当前账号不可用，请重新登录")

    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == str(plan_id or "").strip()).first()
    if plan is None or plan.status != "active":
        raise ValueError("套餐不存在或已下架")

    now = datetime.now()
    order = PaymentOrder(
        order_no=f"MOXI-PAY-{now.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}",
        access_key_id=key_row.id,
        front_user_id=key_row.front_user_id or "",
        plan_id=plan.id,
        plan_code=plan.code,
        plan_name=plan.name,
        amount_cny=_money(plan.price_cny),
        credit_amount=_money(plan.credit_amount),
        provider=str(provider or "mock_gateway").strip()[:80],
        status="pending",
        human_reason=f"等待支付：{plan.name}",
        paid_at=None,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return _order_item(order)


def confirm_checkout_order_by_webhook(
    db: Session,
    *,
    order_no: str,
    amount_cny: Decimal | int | float | str,
    provider_trade_no: str = "",
    signature: str,
    secret: str,
) -> PaymentOrderItem:
    normalized_secret = str(secret or "").strip()
    if not normalized_secret:
        raise ValueError(f"支付回调密钥未配置：请设置 {PAYMENT_WEBHOOK_SECRET_ENV}")

    normalized_order_no = str(order_no or "").strip()
    order = db.query(PaymentOrder).filter(PaymentOrder.order_no == normalized_order_no).first()
    if order is None:
        raise ValueError("支付订单不存在")

    if _money(order.amount_cny) != _money(amount_cny):
        raise ValueError("支付金额与订单不一致")

    expected_signature = build_payment_webhook_signature(
        normalized_secret,
        order_no=order.order_no,
        amount_cny=order.amount_cny,
        provider_trade_no=provider_trade_no,
    )
    if not hmac.compare_digest(expected_signature, str(signature or "").strip()):
        raise ValueError("支付回调签名校验失败")

    key_row = db.query(UserAccessKey).filter(UserAccessKey.id == order.access_key_id).first()
    if key_row is None or key_row.status != "active":
        raise ValueError("订单关联账号不可用")

    if order.status == "paid":
        return _order_item(
            order,
            credit_balance=key_row.credit_balance,
            advanced_generation_enabled=bool(key_row.advanced_generation_enabled),
        )
    if order.status != "pending":
        raise ValueError(f"当前订单状态不允许确认支付：{order.status}")

    now = datetime.now()
    provider_trade_no_text = str(provider_trade_no or "").strip()
    paid_reason = (
        f"支付回调确认：{order.plan_name}"
        if not provider_trade_no_text
        else f"支付回调确认：{order.plan_name} / {provider_trade_no_text}"
    )
    updated_count = (
        db.query(PaymentOrder)
        .filter(PaymentOrder.id == order.id, PaymentOrder.status == "pending")
        .update(
            {"status": "paid", "paid_at": now, "human_reason": paid_reason},
            synchronize_session=False,
        )
    )
    if updated_count != 1:
        db.rollback()
        db.refresh(order)
        if order.status == "paid":
            return _order_item(
                order,
                credit_balance=key_row.credit_balance,
                advanced_generation_enabled=bool(key_row.advanced_generation_enabled),
            )
        raise ValueError(f"当前订单状态不允许确认支付：{order.status}")

    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == order.plan_id).first()
    credit = _money(order.credit_amount)
    balance = _money(key_row.credit_balance) + credit
    key_row.credit_balance = balance
    if plan is not None and bool(plan.advanced_generation_enabled):
        key_row.advanced_generation_enabled = True
    validity_days = int(plan.validity_days or 0) if plan is not None else 0
    if validity_days > 0:
        base_expires_at = key_row.expires_at if key_row.expires_at and key_row.expires_at > now else now
        key_row.expires_at = base_expires_at + timedelta(days=validity_days)

    db.add(CreditLedger(
        access_key_id=key_row.id,
        event_type="recharge",
        amount=credit,
        balance_after=balance,
        actual_cost_cny=Decimal("0.00"),
        billing_multiplier=Decimal("1.00"),
        provider="subscription",
        model=order.plan_code,
        generation_type="subscription",
        status="success",
        human_reason=f"套餐订阅到账：{order.plan_name}",
    ))
    db.commit()
    db.refresh(key_row)
    db.refresh(order)
    return _order_item(
        order,
        credit_balance=key_row.credit_balance,
        advanced_generation_enabled=bool(key_row.advanced_generation_enabled),
    )


def create_mock_checkout_order(db: Session, *, access_key_id: str, plan_id: str) -> PaymentOrderItem:
    ensure_default_subscription_plans(db)
    key_row = db.query(UserAccessKey).filter(UserAccessKey.id == str(access_key_id or "").strip()).first()
    if key_row is None or key_row.status != "active":
        raise ValueError("当前账号不可用，请重新登录")

    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == str(plan_id or "").strip()).first()
    if plan is None or plan.status != "active":
        raise ValueError("套餐不存在或已下架")

    now = datetime.now()
    credit = _money(plan.credit_amount)
    balance = _money(key_row.credit_balance) + credit
    key_row.credit_balance = balance
    if bool(plan.advanced_generation_enabled):
        key_row.advanced_generation_enabled = True
    if int(plan.validity_days or 0) > 0:
        base_expires_at = key_row.expires_at if key_row.expires_at and key_row.expires_at > now else now
        key_row.expires_at = base_expires_at + timedelta(days=int(plan.validity_days or 0))

    order = PaymentOrder(
        order_no=f"MOXI-PAY-{now.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}",
        access_key_id=key_row.id,
        front_user_id=key_row.front_user_id or "",
        plan_id=plan.id,
        plan_code=plan.code,
        plan_name=plan.name,
        amount_cny=_money(plan.price_cny),
        credit_amount=credit,
        provider="mock",
        status="paid",
        human_reason=f"Demo 模拟支付：{plan.name}",
        paid_at=now,
    )
    db.add(order)
    db.add(CreditLedger(
        access_key_id=key_row.id,
        event_type="recharge",
        amount=credit,
        balance_after=balance,
        actual_cost_cny=Decimal("0.00"),
        billing_multiplier=Decimal("1.00"),
        provider="subscription",
        model=plan.code,
        generation_type="subscription",
        status="success",
        human_reason=f"套餐订阅到账：{plan.name}",
    ))
    db.commit()
    db.refresh(key_row)
    db.refresh(order)
    return _order_item(
        order,
        credit_balance=key_row.credit_balance,
        advanced_generation_enabled=bool(key_row.advanced_generation_enabled),
    )
