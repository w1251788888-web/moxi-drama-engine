"""SaaS 管理后台框架表：用户密钥、额度流水、功能开关与模型配置。"""
from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, Numeric, String, Text

from app.database import Base


class FrontUser(Base):
    """前台注册用户框架；当前密钥登录为主，账号注册先预留。"""

    __tablename__ = "front_user"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(120), unique=True, index=True, default="")
    phone = Column(String(40), index=True, default="")
    email = Column(String(160), index=True, default="")
    password_hash = Column(String(255), default="")
    status = Column(String(30), default="reserved")
    invite_code_id = Column(String(36), index=True, default="")
    access_key_id = Column(String(36), index=True, default="")
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class UserAccessKey(Base):
    """后台生成给前台用户使用的登录密钥。"""

    __tablename__ = "user_access_key"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    key_prefix = Column(String(24), nullable=False, index=True)
    plain_key = Column(String(120), default="")
    owner_name = Column(String(120), default="")
    contact = Column(String(160), default="")
    note = Column(Text, default="")
    status = Column(String(30), default="active")
    front_user_id = Column(String(36), index=True, default="")
    credit_balance = Column(Numeric(12, 2), default=0)
    advanced_generation_enabled = Column(Boolean, default=False)
    allow_copy_export = Column(Boolean, default=False)
    admin_role = Column(String(40), default="user")
    tenant_db_path = Column(String(500), default="")
    tenant_storage_status = Column(String(30), default="pending")
    tenant_storage_updated_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class SubscriptionPlan(Base):
    """套餐订阅配置：Demo 阶段使用本地模拟支付，后续可接正式支付渠道。"""

    __tablename__ = "subscription_plan"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String(80), unique=True, nullable=False, index=True)
    name = Column(String(120), default="")
    description = Column(Text, default="")
    price_cny = Column(Numeric(12, 2), default=0)
    credit_amount = Column(Numeric(12, 2), default=0)
    advanced_generation_enabled = Column(Boolean, default=False)
    validity_days = Column(Integer, default=30)
    status = Column(String(30), default="active")
    sort_order = Column(Integer, default=100)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class PaymentOrder(Base):
    """支付订单与后台对账流水；Demo 阶段订单会立即标记为 paid。"""

    __tablename__ = "payment_order"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_no = Column(String(64), unique=True, nullable=False, index=True)
    access_key_id = Column(String(36), index=True, nullable=False)
    front_user_id = Column(String(36), index=True, default="")
    plan_id = Column(String(36), index=True, nullable=False)
    plan_code = Column(String(80), default="")
    plan_name = Column(String(120), default="")
    amount_cny = Column(Numeric(12, 2), default=0)
    credit_amount = Column(Numeric(12, 2), default=0)
    provider = Column(String(50), default="mock")
    status = Column(String(30), default="paid")
    human_reason = Column(String(500), default="")
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class OperatorAuditLog(Base):
    """人类操作者审计日志：后台管理员与前台用户关键动作统一留痕。"""

    __tablename__ = "operator_audit_log"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_type = Column(String(30), nullable=False, index=True)
    actor_id = Column(String(120), default="", index=True)
    actor_label = Column(String(160), default="")
    action = Column(String(80), nullable=False, index=True)
    target_type = Column(String(80), default="", index=True)
    target_id = Column(String(120), default="", index=True)
    status = Column(String(30), default="success", index=True)
    summary = Column(String(500), default="")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_operator_audit_actor_created", "actor_type", "actor_id", "created_at"),
        Index("ix_operator_audit_action_created", "action", "created_at"),
        Index("ix_operator_audit_target_created", "target_type", "target_id", "created_at"),
        Index("ix_operator_audit_status_created", "status", "created_at"),
    )


class FrontUserSession(Base):
    """前台用户服务端会话；密钥只用于登录，后续请求使用 session token。"""

    __tablename__ = "front_user_session"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_token_hash = Column(String(64), unique=True, nullable=False, index=True)
    access_key_id = Column(String(36), index=True, nullable=False)
    owner_name = Column(String(120), default="")
    status = Column(String(30), default="active")
    expires_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class InviteCode(Base):
    """邀请码池：先供内测发放，后续可绑定正式注册用户。"""

    __tablename__ = "invite_code"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code_hash = Column(String(64), unique=True, nullable=False, index=True)
    code_prefix = Column(String(24), nullable=False, index=True)
    batch_name = Column(String(120), default="")
    status = Column(String(30), default="active")
    max_uses = Column(Integer, default=1)
    used_count = Column(Integer, default=0)
    assigned_to = Column(String(160), default="")
    note = Column(Text, default="")
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class CreditLedger(Base):
    """额度流水账本：充值、扣费、补偿都走这里。"""

    __tablename__ = "credit_ledger"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    access_key_id = Column(String(36), index=True, nullable=False)
    event_type = Column(String(30), default="charge")
    amount = Column(Numeric(12, 2), nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=False)
    actual_cost_cny = Column(Numeric(12, 4), default=0)
    billing_multiplier = Column(Numeric(8, 2), default=5)
    provider = Column(String(80), default="")
    model = Column(String(120), default="")
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    generation_type = Column(String(80), default="")
    status = Column(String(30), default="success")
    human_reason = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.now)


class LLMProviderSetting(Base):
    """后台 LLM 接口配置框架；真实 key 后续应加密保存。"""

    __tablename__ = "llm_provider_setting"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider = Column(String(80), unique=True, nullable=False, index=True)
    display_name = Column(String(120), default="")
    base_url = Column(String(500), default="")
    api_key_encrypted = Column(Text, default="")
    default_model = Column(String(120), default="")
    models_json = Column(Text, default="[]")
    is_active = Column(Boolean, default=False)
    is_default = Column(Boolean, default=False)
    input_cost_cny_per_1k = Column(Numeric(12, 6), default=0.002)
    output_cost_cny_per_1k = Column(Numeric(12, 6), default=0.008)
    billing_multiplier = Column(Numeric(8, 2), default=5)
    minimum_actual_cost_cny = Column(Numeric(12, 4), default=0.01)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AdminFeatureFlag(Base):
    """后台控制功能开关，先支持高级生成总开关。"""

    __tablename__ = "admin_feature_flag"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key = Column(String(120), unique=True, nullable=False, index=True)
    label = Column(String(160), default="")
    enabled = Column(Boolean, default=False)
    note = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
