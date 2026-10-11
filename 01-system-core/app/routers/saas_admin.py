"""墨戏生花 SaaS 后台管理框架接口。"""
from __future__ import annotations

from decimal import Decimal
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_admin, verify_project_actor, verify_secondary_admin_actor
from app.database import get_db
from app.routers.admin_config import AIChatRequest
from app.services.saas_access_service import (
    create_access_key,
    create_front_user_by_admin,
    delete_access_key,
    delete_front_user_by_admin,
    list_front_users,
    login_with_front_user_account,
    login_with_access_key,
    list_access_keys,
    normalize_access_key_admin_role,
    recharge_access_key,
    register_front_user_with_invite,
    seed_default_front_users,
    set_access_key_status,
    set_advanced_generation_enabled,
    set_copy_export_enabled,
    update_front_user_by_admin,
    verify_user_session_token,
)
from app.services.saas_invite_service import (
    create_invite_codes,
    list_invite_codes,
    set_invite_code_status,
)
from app.services.saas_admin_query_service import (
    LLMProviderModelRefreshError,
    get_advanced_generation_config,
    list_credit_ledger,
    list_exceptions,
    list_generation_logs,
    list_llm_providers,
    overview_payload,
    refresh_kimi_models,
    refresh_llm_provider_models,
    save_advanced_generation_config,
    save_llm_provider,
)
from app.services.saas_subscription_service import (
    confirm_checkout_order_by_webhook,
    create_mock_checkout_order,
    create_pending_checkout_order,
    list_payment_orders,
    list_subscription_plans,
    payment_webhook_secret_from_env,
    save_subscription_plan,
)
from app.services.saas_operator_audit_service import (
    list_operator_audit_logs,
    log_operator_action,
    resolve_admin_actor,
    user_actor,
)
from app.services.rag_service import get_rag_retriever


admin_router = APIRouter(prefix="/moxi-admin", tags=["Moxi SaaS Admin"])
user_router = APIRouter(prefix="/user", tags=["Moxi User Auth"])


class AccessKeyCreateRequest(BaseModel):
    owner_name: str = Field(..., description="客户名称或备注")
    initial_credit: Decimal = Field(Decimal("0"), ge=0, description="初始额度，1额度=1元人民币")
    advanced_generation_enabled: bool = Field(False, description="是否允许使用高级生成链路")
    allow_copy_export: bool = Field(False, description="是否允许前台复制和导出创作内容")
    admin_role: str = Field("user", description="user=普通用户密钥；secondary_admin=二级管理员密钥")


class AccessKeyResponse(BaseModel):
    key_id: str
    plain_key: str | None = None
    owner_name: str
    credit_balance: float
    advanced_generation_enabled: bool
    allow_copy_export: bool = False
    admin_role: str = "user"


class AdvancedGenerationToggleRequest(BaseModel):
    enabled: bool


class CopyExportToggleRequest(BaseModel):
    enabled: bool


class AdvancedGenerationRoleConfigRequest(BaseModel):
    role: str = Field(..., max_length=40)
    provider: str = Field("", max_length=80)
    model: str = Field("", max_length=160)
    temperature: float = Field(0.7, ge=0, le=2)
    duty: str = Field("", max_length=500)


class AdvancedGenerationAdminConfigRequest(BaseModel):
    enabled: bool = True
    profile_id: str = Field("short_drama", max_length=80)
    roles: list[AdvancedGenerationRoleConfigRequest] = Field(default_factory=list)


class AccessKeyStatusRequest(BaseModel):
    status: str


class AccessKeyRechargeRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    reason: str = "后台手动充值"


class InviteCodeCreateRequest(BaseModel):
    count: int = Field(1, ge=1, le=100, description="生成数量")
    batch_name: str = Field("demo", description="批次名称")
    max_uses: int = Field(1, ge=1, le=100, description="单码最大使用次数")
    assigned_to: str = Field("", description="预分配对象")
    note: str = Field("", description="备注")


class InviteCodeStatusRequest(BaseModel):
    status: str


class InviteCodeResponse(BaseModel):
    invite_id: str
    plain_code: str | None = None
    code_prefix: str
    batch_name: str
    status: str
    max_uses: int
    used_count: int
    assigned_to: str
    note: str
    created_at: str | None = None


class AccessKeyLoginRequest(BaseModel):
    access_key: str = Field(..., description="后台生成的用户使用密钥")


class FrontUserAccountLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=160, description="用户名、邮箱或手机号")
    password: str = Field(..., min_length=1, max_length=128, description="账号密码")


class FrontUserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=80, description="前台用户名")
    password: str = Field(..., min_length=6, max_length=128, description="账号密码")
    invite_code: str = Field(..., description="内测邀请码")
    phone: str = Field("", max_length=40, description="手机号")
    email: str = Field("", max_length=160, description="邮箱")


class FrontUserAdminCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=80)
    password: str = Field(..., min_length=6, max_length=128)
    phone: str = Field("", max_length=40)
    email: str = Field("", max_length=160)
    note: str = Field("", max_length=500)
    initial_credit: Decimal = Field(Decimal("10"), ge=0)
    advanced_generation_enabled: bool = False


class FrontUserAdminUpdateRequest(BaseModel):
    username: str | None = Field(None, min_length=2, max_length=80)
    password: str | None = Field(None, min_length=6, max_length=128)
    phone: str | None = Field(None, max_length=40)
    email: str | None = Field(None, max_length=160)
    status: str | None = None
    note: str | None = Field(None, max_length=500)


class FrontUserAdminResponse(BaseModel):
    user_id: str
    username: str
    phone: str
    email: str
    status: str
    note: str
    access_key_id: str
    key_status: str
    key_prefix: str
    credit_balance: float
    advanced_generation_enabled: bool
    created_at: str | None = None
    updated_at: str | None = None
    plain_key: str | None = None
    plain_password: str | None = None


class AccessKeySessionResponse(BaseModel):
    key_id: str
    owner_name: str
    credit_balance: float
    advanced_generation_enabled: bool
    allow_copy_export: bool = False
    admin_role: str = "user"
    status: str
    session_token: str | None = None
    session_expires_at: str | None = None


class FrontUserRegisterResponse(AccessKeySessionResponse):
    front_user_id: str
    plain_key: str | None = None


class AdminOverviewResponse(BaseModel):
    billing_rule: str
    credit_unit: str
    cards: list[dict[str, str | int | float]]
    sections: list[str]
    cost_health: dict[str, float] | None = None


class ListResponse(BaseModel):
    items: list[dict]
    total: int


class LLMProviderSaveRequest(BaseModel):
    display_name: str = ""
    base_url: str = ""
    api_key: str = ""
    default_model: str = ""
    models: list[str] = Field(default_factory=list)
    is_active: bool = False
    is_default: bool = False
    input_cost_cny_per_1k: Decimal = Field(Decimal("0.002"), ge=0)
    output_cost_cny_per_1k: Decimal = Field(Decimal("0.008"), ge=0)
    billing_multiplier: Decimal = Field(Decimal("5"), gt=0)
    minimum_actual_cost_cny: Decimal = Field(Decimal("0.01"), ge=0)


class SubscriptionPlanSaveRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    price_cny: Decimal = Field(Decimal("0"), ge=0)
    credit_amount: Decimal = Field(Decimal("0"), ge=0)
    advanced_generation_enabled: bool = False
    validity_days: int = Field(30, ge=0, le=3650)
    status: str = "active"
    sort_order: int = 100


class SubscriptionPlanResponse(BaseModel):
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
    created_at: str | None = None
    updated_at: str | None = None


class SubscriptionCheckoutRequest(BaseModel):
    plan_id: str
    checkout_mode: str = Field("demo", description="demo=立即到账演示；pending=创建待支付订单等待网关回调")
    provider: str = Field("mock_gateway", max_length=80)


class PaymentWebhookRequest(BaseModel):
    order_no: str
    amount_cny: Decimal = Field(..., ge=0)
    provider_trade_no: str = ""
    signature: str


class PaymentOrderResponse(BaseModel):
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
    paid_at: str | None = None
    created_at: str | None = None
    credit_balance: float | None = None
    advanced_generation_enabled: bool | None = None


@admin_router.get("/overview", response_model=AdminOverviewResponse, summary="SaaS 后台总览框架")
async def get_admin_overview(_: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    return AdminOverviewResponse(**overview_payload(db))


@admin_router.get("/knowledge-base/status", response_model=dict, summary="查询知识库连接状态")
async def get_knowledge_base_status(_: bool = Depends(verify_admin)):
    return await get_rag_retriever().health_status()


@admin_router.get("/access-keys", response_model=ListResponse, summary="查询用户密钥列表")
async def get_access_keys(
    keyword: str = "",
    status: str = "",
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    items = [item.__dict__ for item in list_access_keys(db, keyword=keyword, status=status)]
    return ListResponse(items=items, total=len(items))


@admin_router.post("/access-keys", response_model=AccessKeyResponse, summary="生成前台用户密钥")
async def create_user_access_key(
    req: AccessKeyCreateRequest,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    admin_role = normalize_access_key_admin_role(req.admin_role)
    issued = create_access_key(
        owner_name=req.owner_name,
        initial_credit=req.initial_credit,
        advanced_generation_enabled=req.advanced_generation_enabled,
        allow_copy_export=req.allow_copy_export,
        admin_role=admin_role,
        db=db,
    )
    response = AccessKeyResponse(
        key_id=issued.key_id,
        plain_key=issued.plain_key,
        owner_name=issued.owner_name,
        credit_balance=issued.credit_balance,
        advanced_generation_enabled=issued.advanced_generation_enabled,
        allow_copy_export=issued.allow_copy_export,
        admin_role=issued.admin_role,
    )
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="access_key.create",
        target_type="access_key",
        target_id=issued.key_id,
        summary=f"生成用户密钥：{issued.owner_name}",
        metadata={
            "owner_name": issued.owner_name,
            "initial_credit": str(req.initial_credit),
            "advanced_generation_enabled": req.advanced_generation_enabled,
            "allow_copy_export": req.allow_copy_export,
            "admin_role": issued.admin_role,
        },
    )
    return response


@admin_router.post("/secondary/access-keys", response_model=AccessKeyResponse, summary="二级管理员生成普通用户密钥")
async def create_access_key_by_secondary_admin(
    req: AccessKeyCreateRequest,
    actor: ProjectAccessActor = Depends(verify_secondary_admin_actor),
    db: Session = Depends(get_db),
):
    issued = create_access_key(
        owner_name=req.owner_name,
        initial_credit=req.initial_credit,
        advanced_generation_enabled=False,
        allow_copy_export=False,
        admin_role="user",
        db=db,
    )
    response = AccessKeyResponse(
        key_id=issued.key_id,
        plain_key=issued.plain_key,
        owner_name=issued.owner_name,
        credit_balance=issued.credit_balance,
        advanced_generation_enabled=issued.advanced_generation_enabled,
        allow_copy_export=issued.allow_copy_export,
        admin_role=issued.admin_role,
    )
    log_operator_action(
        db,
        actor=user_actor(access_key_id=actor.access_key_id, owner_name=actor.owner_name),
        action="access_key.secondary_create",
        target_type="access_key",
        target_id=issued.key_id,
        summary=f"二级管理员生成用户密钥：{issued.owner_name}",
        metadata={
            "owner_name": issued.owner_name,
            "initial_credit": str(req.initial_credit),
            "created_admin_role": issued.admin_role,
        },
    )
    return response


@admin_router.put("/access-keys/{key_id}/status", response_model=AccessKeySessionResponse, summary="启用或禁用密钥")
async def update_access_key_status(
    key_id: str,
    req: AccessKeyStatusRequest,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    try:
        session = set_access_key_status(db, key_id, req.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="access_key.status",
        target_type="access_key",
        target_id=key_id,
        summary=f"更新密钥状态为 {session.status}",
        metadata={"status": session.status},
    )
    return AccessKeySessionResponse(**session.__dict__)


@admin_router.delete("/access-keys/{key_id}", response_model=AccessKeySessionResponse, summary="删除密钥")
async def delete_user_access_key(
    key_id: str,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    try:
        session = delete_access_key(db, key_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="access_key.delete",
        target_type="access_key",
        target_id=key_id,
        summary=f"删除密钥：{session.owner_name}",
        metadata={"status": session.status, "admin_role": session.admin_role},
    )
    return AccessKeySessionResponse(**session.__dict__)


@admin_router.post("/access-keys/{key_id}/recharge", response_model=AccessKeySessionResponse, summary="给密钥手动充值")
async def recharge_user_access_key(
    key_id: str,
    req: AccessKeyRechargeRequest,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    try:
        session = recharge_access_key(db, key_id, req.amount, reason=req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="access_key.recharge",
        target_type="access_key",
        target_id=key_id,
        summary=f"给密钥充值 {req.amount} 额度",
        metadata={"amount": str(req.amount), "reason": req.reason, "balance_after": str(session.credit_balance)},
    )
    return AccessKeySessionResponse(**session.__dict__)


@admin_router.get("/invite-codes", response_model=ListResponse, summary="查询邀请码列表")
async def get_invite_codes(
    status: str = "",
    batch_name: str = "",
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    items = [item.__dict__ for item in list_invite_codes(db, status=status, batch_name=batch_name)]
    return ListResponse(items=items, total=len(items))


@admin_router.post("/invite-codes", response_model=ListResponse, summary="批量生成邀请码")
async def create_admin_invite_codes(
    req: InviteCodeCreateRequest,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    issued = create_invite_codes(
        db,
        count=req.count,
        batch_name=req.batch_name,
        max_uses=req.max_uses,
        assigned_to=req.assigned_to,
        note=req.note,
    )
    items = [item.__dict__ for item in issued]
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="invite_code.create_batch",
        target_type="invite_code_batch",
        target_id=req.batch_name,
        summary=f"批量生成邀请码 {len(items)} 个",
        metadata={
            "count": len(items),
            "batch_name": req.batch_name,
            "max_uses": req.max_uses,
            "assigned_to": req.assigned_to,
            "code_prefixes": [item.get("code_prefix") for item in items],
        },
    )
    return ListResponse(items=items, total=len(items))


@admin_router.put("/invite-codes/{invite_id}/status", response_model=InviteCodeResponse, summary="启用或停用邀请码")
async def update_invite_code_status(
    invite_id: str,
    req: InviteCodeStatusRequest,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    try:
        item = set_invite_code_status(db, invite_id, req.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="invite_code.status",
        target_type="invite_code",
        target_id=invite_id,
        summary=f"更新邀请码状态为 {item.status}",
        metadata={"status": item.status, "code_prefix": item.code_prefix},
    )
    return InviteCodeResponse(**item.__dict__)


@admin_router.get("/front-users", response_model=ListResponse, summary="查询注册用户列表")
async def get_front_users(
    keyword: str = "",
    status: str = "",
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    items = [item.__dict__ for item in list_front_users(db, keyword=keyword, status=status)]
    return ListResponse(items=items, total=len(items))


@admin_router.post("/front-users", response_model=FrontUserAdminResponse, summary="后台创建注册用户")
async def create_front_user_admin(
    req: FrontUserAdminCreateRequest,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    try:
        created = create_front_user_by_admin(
            db,
            username=req.username,
            password=req.password,
            phone=req.phone,
            email=req.email,
            note=req.note,
            initial_credit=req.initial_credit,
            advanced_generation_enabled=req.advanced_generation_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="front_user.create",
        target_type="front_user",
        target_id=created.user.user_id,
        summary=f"创建注册用户：{created.user.username}",
        metadata={"username": created.user.username, "has_email": bool(req.email), "has_phone": bool(req.phone)},
    )
    return FrontUserAdminResponse(
        **created.user.__dict__,
        plain_key=created.plain_key,
        plain_password=created.plain_password,
    )


@admin_router.post("/front-users/seed-defaults", response_model=ListResponse, summary="生成默认注册用户")
async def seed_front_users_admin(
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    created = seed_default_front_users(db)
    items = [
        {
            **item.user.__dict__,
            "plain_key": item.plain_key,
            "plain_password": item.plain_password,
        }
        for item in created
    ]
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="front_user.seed_defaults",
        target_type="front_user",
        target_id="default_front_users",
        summary=f"生成默认注册用户 {len(items)} 个",
        metadata={"created_or_existing": len(items), "new_count": sum(1 for item in created if item.plain_password)},
    )
    return ListResponse(items=items, total=len(items))


@admin_router.put("/front-users/{user_id}", response_model=FrontUserAdminResponse, summary="更新注册用户")
async def update_front_user_admin(
    user_id: str,
    req: FrontUserAdminUpdateRequest,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    try:
        item = update_front_user_by_admin(db, user_id, req.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="front_user.update",
        target_type="front_user",
        target_id=user_id,
        summary=f"更新注册用户：{item.username}",
        metadata={"fields": sorted(req.model_dump(exclude_unset=True).keys()), "status": item.status},
    )
    return FrontUserAdminResponse(**item.__dict__)


@admin_router.delete("/front-users/{user_id}", response_model=FrontUserAdminResponse, summary="删除注册用户")
async def delete_front_user_admin(
    user_id: str,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    try:
        item = delete_front_user_by_admin(db, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="front_user.delete",
        target_type="front_user",
        target_id=user_id,
        summary=f"删除注册用户：{item.username}",
        metadata={"status": item.status, "access_key_id": item.access_key_id},
    )
    return FrontUserAdminResponse(**item.__dict__)


@admin_router.put(
    "/access-keys/{key_id}/advanced-generation",
    response_model=AccessKeySessionResponse,
    summary="开启或关闭某个密钥的高级生成权限",
)
async def toggle_access_key_advanced_generation(
    key_id: str,
    req: AdvancedGenerationToggleRequest,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    try:
        session = set_advanced_generation_enabled(key_id, req.enabled, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="access_key.advanced_generation",
        target_type="access_key",
        target_id=key_id,
        summary=f"{'开启' if req.enabled else '关闭'}高级生成权限",
        metadata={"enabled": req.enabled},
    )
    return AccessKeySessionResponse(**session.__dict__)


@admin_router.put(
    "/access-keys/{key_id}/copy-export",
    response_model=AccessKeySessionResponse,
    summary="开启或关闭某个密钥的复制导出权限",
)
async def toggle_access_key_copy_export(
    key_id: str,
    req: CopyExportToggleRequest,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    try:
        session = set_copy_export_enabled(key_id, req.enabled, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="access_key.copy_export",
        target_type="access_key",
        target_id=key_id,
        summary=f"{'开启' if req.enabled else '关闭'}复制导出权限",
        metadata={"enabled": req.enabled},
    )
    return AccessKeySessionResponse(**session.__dict__)


@admin_router.get("/llm-providers", response_model=ListResponse, summary="查询 LLM 接口配置")
async def get_llm_providers(_: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    items = list_llm_providers(db)
    return ListResponse(items=items, total=len(items))


@admin_router.put("/llm-providers/{provider}", summary="保存 LLM 接口配置")
async def put_llm_provider(
    provider: str,
    req: LLMProviderSaveRequest,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    saved = save_llm_provider(db, provider, req.model_dump())
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="llm_provider.save",
        target_type="llm_provider",
        target_id=provider,
        summary=f"保存 LLM 配置：{provider}",
        metadata={
            "display_name": req.display_name,
            "base_url": req.base_url,
            "default_model": req.default_model,
            "models": req.models,
            "is_active": req.is_active,
            "is_default": req.is_default,
            "has_api_key_payload": bool(req.api_key.strip()),
            "input_cost_cny_per_1k": str(req.input_cost_cny_per_1k),
            "output_cost_cny_per_1k": str(req.output_cost_cny_per_1k),
            "billing_multiplier": str(req.billing_multiplier),
        },
    )
    return saved


@admin_router.post("/llm-providers/kimi/models/refresh", summary="自动拉取 Kimi 模型列表")
async def post_refresh_kimi_models(
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    try:
        saved = await refresh_kimi_models(db)
    except LLMProviderModelRefreshError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="llm_provider.models.refresh",
        target_type="llm_provider",
        target_id="kimi",
        summary="自动拉取 Kimi 模型列表",
        metadata={
            "models": saved.get("models", []),
            "default_model": saved.get("default_model", ""),
        },
    )
    return saved


@admin_router.post("/llm-providers/{provider}/models/refresh", summary="自动拉取指定 LLM 模型列表")
async def post_refresh_llm_provider_models(
    provider: str,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    try:
        saved = await refresh_llm_provider_models(db, provider)
    except LLMProviderModelRefreshError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="llm_provider.models.refresh",
        target_type="llm_provider",
        target_id=provider,
        summary=f"自动拉取 {saved.get('display_name') or provider} 模型列表",
        metadata={
            "models": saved.get("models", []),
            "default_model": saved.get("default_model", ""),
        },
    )
    return saved


@admin_router.get("/advanced-generation/config", response_model=dict, summary="查询高级生成链路默认模型分工")
async def get_admin_advanced_generation_config(
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    return get_advanced_generation_config(db)


@admin_router.put("/advanced-generation/config", response_model=dict, summary="保存高级生成链路默认模型分工")
async def put_admin_advanced_generation_config(
    req: AdvancedGenerationAdminConfigRequest,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    saved = save_advanced_generation_config(db, req.model_dump())
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="advanced_generation.config.save",
        target_type="advanced_generation",
        target_id=saved.get("profile_id", "short_drama"),
        summary="保存高级生成链路默认模型分工",
        metadata={
            "enabled": saved.get("enabled"),
            "profile_id": saved.get("profile_id"),
            "roles": [
                {
                    "role": item.get("role"),
                    "provider": item.get("provider"),
                    "model": item.get("model"),
                    "temperature": item.get("temperature"),
                }
                for item in saved.get("roles", [])
            ],
        },
    )
    return saved


@admin_router.get("/subscription-plans", response_model=ListResponse, summary="查询套餐订阅配置")
async def get_subscription_plans(_: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    items = [item.__dict__ for item in list_subscription_plans(db, include_inactive=True)]
    return ListResponse(items=items, total=len(items))


@admin_router.post("/subscription-plans/seed-defaults", response_model=ListResponse, summary="补齐默认套餐订阅配置")
async def seed_subscription_plans_admin(
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    items = [item.__dict__ for item in list_subscription_plans(db, include_inactive=True)]
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="subscription_plan.seed_defaults",
        target_type="subscription_plan",
        target_id="default_subscription_plans",
        summary=f"补齐默认套餐配置 {len(items)} 个",
        metadata={"total": len(items), "codes": [item.get("code") for item in items]},
    )
    return ListResponse(items=items, total=len(items))


@admin_router.post("/subscription-plans", response_model=SubscriptionPlanResponse, summary="保存套餐订阅配置")
async def post_subscription_plan(
    req: SubscriptionPlanSaveRequest,
    _: bool = Depends(verify_admin),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    try:
        item = save_subscription_plan(db, req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=resolve_admin_actor(db, x_admin_token),
        action="subscription_plan.save",
        target_type="subscription_plan",
        target_id=item.plan_id,
        summary=f"保存套餐：{item.name}",
        metadata=req.model_dump(),
    )
    return SubscriptionPlanResponse(**item.__dict__)


@admin_router.get("/payment-orders", response_model=ListResponse, summary="查询支付订单")
async def get_payment_orders(_: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    items = [item.__dict__ for item in list_payment_orders(db)]
    return ListResponse(items=items, total=len(items))


@admin_router.get("/operator-audit-logs", response_model=ListResponse, summary="查询人类操作者审计日志")
async def get_operator_audit_logs(
    actor_type: str = "",
    action: str = "",
    target_type: str = "",
    status: str = "",
    limit: int = 200,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    items = [
        item.__dict__
        for item in list_operator_audit_logs(
            db,
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            status=status,
            limit=limit,
        )
    ]
    return ListResponse(items=items, total=len(items))


@admin_router.get("/credit-ledger", response_model=ListResponse, summary="查询额度流水")
async def get_credit_ledger(status: str = "", _: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    items = list_credit_ledger(db, status=status)
    return ListResponse(items=items, total=len(items))


@admin_router.get("/generation-logs", response_model=ListResponse, summary="查询生成日志")
async def get_generation_logs(_: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    items = list_generation_logs(db)
    return ListResponse(items=items, total=len(items))


@admin_router.get("/exceptions", response_model=ListResponse, summary="查询异常中心")
async def get_exceptions(_: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    items = list_exceptions(db)
    return ListResponse(items=items, total=len(items))


@user_router.post("/access-key/login", response_model=AccessKeySessionResponse, summary="前台用户密钥登录")
async def user_access_key_login(req: AccessKeyLoginRequest, db: Session = Depends(get_db)):
    try:
        session = login_with_access_key(req.access_key, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=user_actor(access_key_id=session.key_id, owner_name=session.owner_name),
        action="user.login.access_key",
        target_type="access_key",
        target_id=session.key_id,
        summary=f"用户密钥登录：{session.owner_name}",
        metadata={"login_method": "access_key"},
    )
    return AccessKeySessionResponse(**session.__dict__)


@user_router.post("/account/login", response_model=AccessKeySessionResponse, summary="前台用户账号密码登录")
async def front_user_account_login(req: FrontUserAccountLoginRequest, db: Session = Depends(get_db)):
    try:
        session = login_with_front_user_account(req.username, req.password, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=user_actor(access_key_id=session.key_id, owner_name=session.owner_name),
        action="user.login.account",
        target_type="access_key",
        target_id=session.key_id,
        summary=f"用户账号登录：{session.owner_name}",
        metadata={"login_identifier": req.username},
    )
    return AccessKeySessionResponse(**session.__dict__)


@user_router.get("/session", response_model=AccessKeySessionResponse, summary="刷新当前前台用户会话")
async def front_user_current_session(
    x_user_session: str | None = Header(None, alias="X-User-Session"),
    db: Session = Depends(get_db),
):
    if not x_user_session:
        raise HTTPException(status_code=403, detail="请先登录前台用户账号")
    try:
        session = verify_user_session_token(x_user_session, db)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return AccessKeySessionResponse(
        key_id=session.key_id,
        owner_name=session.owner_name,
        credit_balance=float(session.credit_balance),
        advanced_generation_enabled=session.advanced_generation_enabled,
        allow_copy_export=session.allow_copy_export,
        admin_role=session.admin_role,
        status=session.status,
        session_token=x_user_session,
    )


@user_router.post("/ai/chat", summary="前台用户 AI 创作聊天助手")
async def front_user_ai_chat(
    req: AIChatRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    """前台项目工作区 AI 聊天入口。

    管理员也可通过该入口在工作区调用 AI；普通用户必须带有效 X-User-Session。
    """
    from app.routers.admin_config import generate_ai_chat_response

    if not (actor.is_admin or actor.is_user):
        raise HTTPException(status_code=403, detail="请先登录管理员后台或前台用户账号")
    return await generate_ai_chat_response(req)


@user_router.post("/register", response_model=FrontUserRegisterResponse, summary="邀请码注册前台用户")
async def front_user_register(req: FrontUserRegisterRequest, db: Session = Depends(get_db)):
    try:
        registered = register_front_user_with_invite(
            db,
            username=req.username,
            password=req.password,
            invite_code=req.invite_code,
            phone=req.phone,
            email=req.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=user_actor(access_key_id=registered.key_id, owner_name=registered.owner_name),
        action="user.register",
        target_type="front_user",
        target_id=registered.front_user_id,
        summary=f"邀请码注册用户：{registered.owner_name}",
        metadata={"key_id": registered.key_id, "has_email": bool(req.email), "has_phone": bool(req.phone)},
    )
    return FrontUserRegisterResponse(**registered.__dict__)


@user_router.get("/subscription-plans", response_model=ListResponse, summary="查询前台可订阅套餐")
async def user_subscription_plans(db: Session = Depends(get_db)):
    items = [item.__dict__ for item in list_subscription_plans(db, include_inactive=False)]
    return ListResponse(items=items, total=len(items))


@user_router.get("/subscription-orders", response_model=ListResponse, summary="查询当前用户订阅订单")
async def user_subscription_orders(
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    if not actor.is_user:
        raise HTTPException(status_code=403, detail="请使用前台用户账号查看订阅订单")
    items = [item.__dict__ for item in list_payment_orders(db, access_key_id=actor.access_key_id)]
    return ListResponse(items=items, total=len(items))


@user_router.post("/subscription-orders", response_model=PaymentOrderResponse, summary="创建订阅订单")
async def user_create_subscription_order(
    req: SubscriptionCheckoutRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    if not actor.is_user:
        raise HTTPException(status_code=403, detail="请使用前台用户账号订阅套餐")
    try:
        if req.checkout_mode == "pending":
            item = create_pending_checkout_order(
                db,
                access_key_id=actor.access_key_id,
                plan_id=req.plan_id,
                provider=req.provider,
            )
        elif req.checkout_mode == "demo":
            item = create_mock_checkout_order(db, access_key_id=actor.access_key_id, plan_id=req.plan_id)
        else:
            raise ValueError("checkout_mode 只能是 demo 或 pending")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=user_actor(access_key_id=actor.access_key_id, owner_name=actor.owner_name),
        action="subscription_order.create",
        target_type="payment_order",
        target_id=item.order_id,
        summary=f"订阅套餐：{item.plan_name}",
        metadata={
            "order_no": item.order_no,
            "plan_id": item.plan_id,
            "plan_code": item.plan_code,
            "amount_cny": item.amount_cny,
            "credit_amount": item.credit_amount,
            "checkout_mode": req.checkout_mode,
            "provider": item.provider,
        },
    )
    return PaymentOrderResponse(**item.__dict__)


@user_router.post(
    "/subscription-orders/webhook/mock",
    response_model=PaymentOrderResponse,
    summary="模拟支付网关回调验签并确认订单",
)
async def user_subscription_order_mock_webhook(req: PaymentWebhookRequest, db: Session = Depends(get_db)):
    try:
        item = confirm_checkout_order_by_webhook(
            db,
            order_no=req.order_no,
            amount_cny=req.amount_cny,
            provider_trade_no=req.provider_trade_no,
            signature=req.signature,
            secret=payment_webhook_secret_from_env(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_operator_action(
        db,
        actor=user_actor(access_key_id=item.access_key_id, owner_name="payment_webhook"),
        action="subscription_order.webhook_paid",
        target_type="payment_order",
        target_id=item.order_id,
        summary=f"支付回调确认：{item.plan_name}",
        metadata={
            "order_no": item.order_no,
            "status": item.status,
            "amount_cny": item.amount_cny,
            "provider_trade_no": req.provider_trade_no,
        },
    )
    return PaymentOrderResponse(**item.__dict__)
