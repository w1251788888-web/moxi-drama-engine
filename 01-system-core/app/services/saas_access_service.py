"""前台用户密钥服务：生成密钥、登录、充值和高级生成功能授权。"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import inspect, or_, text
from sqlalchemy.orm import Session

from app.models.saas_admin import CreditLedger, FrontUser, FrontUserSession, UserAccessKey
from app.services.saas_billing_service import (
    DEFAULT_BILLING_MULTIPLIER,
    DEFAULT_INPUT_COST_CNY_PER_1K,
    DEFAULT_OUTPUT_COST_CNY_PER_1K,
    MINIMUM_ACTUAL_COST_CNY,
    calculate_billable_credit,
    estimate_generation_actual_cost_cny,
)
from app.services.saas_invite_service import consume_invite_code
from app.services.tenant_database_service import (
    delete_access_key_tenant_database,
    ensure_access_key_tenant_database,
)


USER_SESSION_TTL_DAYS = 30
MINIMUM_GENERATION_CREDIT = Decimal("0.05")
DEFAULT_REGISTER_CREDIT = Decimal("10")
ACCESS_KEY_ADMIN_ROLES = {"user", "secondary_admin"}


@dataclass(frozen=True)
class IssuedAccessKey:
    key_id: str
    plain_key: str
    owner_name: str
    credit_balance: Decimal
    advanced_generation_enabled: bool
    allow_copy_export: bool = False
    admin_role: str = "user"


@dataclass(frozen=True)
class AccessKeySession:
    key_id: str
    owner_name: str
    credit_balance: Decimal
    advanced_generation_enabled: bool
    allow_copy_export: bool
    admin_role: str
    status: str
    session_token: str | None = None
    session_expires_at: str | None = None


@dataclass(frozen=True)
class RegisteredFrontUser:
    front_user_id: str
    key_id: str
    plain_key: str
    owner_name: str
    credit_balance: Decimal
    advanced_generation_enabled: bool
    allow_copy_export: bool
    admin_role: str
    status: str
    session_token: str | None
    session_expires_at: str | None


@dataclass(frozen=True)
class VerifiedUserSession:
    key_id: str
    owner_name: str
    credit_balance: Decimal
    advanced_generation_enabled: bool
    allow_copy_export: bool
    admin_role: str
    status: str


@dataclass(frozen=True)
class AccessKeyAdminItem:
    key_id: str
    key_prefix: str
    plain_key: str
    owner_name: str
    contact: str
    status: str
    credit_balance: Decimal
    advanced_generation_enabled: bool
    allow_copy_export: bool
    admin_role: str
    last_used_at: str | None
    created_at: str | None


@dataclass(frozen=True)
class FrontUserAdminItem:
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
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True)
class FrontUserAdminCreateResult:
    user: FrontUserAdminItem
    plain_key: str | None = None
    plain_password: str | None = None


@dataclass
class _AccessKeyRecord:
    key_id: str
    key_hash: str
    plain_key: str
    owner_name: str
    credit_balance: Decimal
    advanced_generation_enabled: bool
    allow_copy_export: bool = False
    admin_role: str = "user"
    status: str = "active"
    created_at: datetime = datetime.now()
    last_used_at: datetime | None = None


_ACCESS_KEYS: dict[str, _AccessKeyRecord] = {}

DEFAULT_FRONT_USER_SEEDS = [
    {"username": "moxi_writer_a", "phone": "", "email": "writer-a@example.local", "credit": Decimal("99"), "advanced": True},
    {"username": "moxi_creator_b", "phone": "", "email": "creator-b@example.local", "credit": Decimal("30"), "advanced": False},
    {"username": "moxi_reviewer_c", "phone": "", "email": "reviewer-c@example.local", "credit": Decimal("199"), "advanced": True},
]


def _credit(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_access_key_admin_role(value: str | None) -> str:
    role = str(value or "user").strip()
    return role if role in ACCESS_KEY_ADMIN_ROLES else "user"


def ensure_access_key_admin_role_column(db: Session) -> None:
    """SQLite 项目库没有迁移系统，运行时补齐用户密钥权限列。"""
    try:
        rows = db.connection().exec_driver_sql("PRAGMA table_info(user_access_key)").fetchall()
        existing = {str(row[1]) for row in rows}
        changed = False
        if rows and "admin_role" not in existing:
            db.connection().exec_driver_sql(
                "ALTER TABLE user_access_key ADD COLUMN admin_role VARCHAR(40) DEFAULT 'user'"
            )
            changed = True
        if rows and "plain_key" not in existing:
            db.connection().exec_driver_sql(
                "ALTER TABLE user_access_key ADD COLUMN plain_key VARCHAR(120) DEFAULT ''"
            )
            changed = True
        if rows and "allow_copy_export" not in existing:
            db.connection().exec_driver_sql(
                "ALTER TABLE user_access_key ADD COLUMN allow_copy_export INTEGER DEFAULT 0"
            )
            changed = True
        if rows and "tenant_db_path" not in existing:
            db.connection().exec_driver_sql(
                "ALTER TABLE user_access_key ADD COLUMN tenant_db_path VARCHAR(500) DEFAULT ''"
            )
            changed = True
        if rows and "tenant_storage_status" not in existing:
            db.connection().exec_driver_sql(
                "ALTER TABLE user_access_key ADD COLUMN tenant_storage_status VARCHAR(30) DEFAULT 'pending'"
            )
            changed = True
        if rows and "tenant_storage_updated_at" not in existing:
            db.connection().exec_driver_sql(
                "ALTER TABLE user_access_key ADD COLUMN tenant_storage_updated_at DATETIME"
            )
            changed = True
        if changed:
            db.commit()
    except Exception:
        db.rollback()


def hash_access_key(plain_key: str) -> str:
    return hashlib.sha256(str(plain_key or "").strip().encode("utf-8")).hexdigest()


def hash_front_user_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"


def verify_front_user_password(password: str, stored_hash: str) -> bool:
    parts = str(stored_hash or "").split("$")
    if len(parts) != 3 or parts[0] != "sha256":
        return False
    _, salt, digest = parts
    expected = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return hmac.compare_digest(expected, digest)


def generate_seed_password() -> str:
    return f"Moxi-{secrets.token_urlsafe(8)}1!"


def hash_session_token(session_token: str) -> str:
    return hashlib.sha256(str(session_token or "").strip().encode("utf-8")).hexdigest()


def generate_plain_access_key() -> str:
    parts = [secrets.token_hex(2).upper() for _ in range(3)]
    return "MOXI-" + "-".join(parts)


def generate_user_session_token() -> str:
    return "MXS-" + secrets.token_urlsafe(32)


def create_access_key(
    *,
    owner_name: str,
    initial_credit: Decimal | int | float | str = Decimal("0"),
    advanced_generation_enabled: bool = False,
    allow_copy_export: bool = False,
    contact: str = "",
    front_user_id: str = "",
    admin_role: str = "user",
    db: Session | None = None,
) -> IssuedAccessKey:
    normalized_admin_role = normalize_access_key_admin_role(admin_role)
    plain_key = generate_plain_access_key()
    key_hash = hash_access_key(plain_key)
    key_id = secrets.token_hex(16)
    record = _AccessKeyRecord(
        key_id=key_id,
        key_hash=key_hash,
        plain_key=plain_key,
        owner_name=str(owner_name or "").strip() or "未命名用户",
        credit_balance=_credit(initial_credit),
        advanced_generation_enabled=bool(advanced_generation_enabled),
        allow_copy_export=bool(allow_copy_export),
        admin_role=normalized_admin_role,
    )
    _ACCESS_KEYS[key_id] = record

    if db is not None:
        ensure_access_key_admin_role_column(db)
        row = UserAccessKey(
            id=record.key_id,
            key_hash=record.key_hash,
            key_prefix=record.plain_key[:14],
            plain_key=record.plain_key,
            owner_name=record.owner_name,
            contact=str(contact or "").strip(),
            front_user_id=str(front_user_id or "").strip(),
            credit_balance=record.credit_balance,
            advanced_generation_enabled=record.advanced_generation_enabled,
            allow_copy_export=record.allow_copy_export,
            admin_role=record.admin_role,
        )
        db.add(row)
        ensure_access_key_tenant_database(db, row)
        if record.credit_balance > 0:
            db.add(CreditLedger(
                access_key_id=record.key_id,
                event_type="recharge",
                amount=record.credit_balance,
                balance_after=record.credit_balance,
                human_reason="创建密钥时发放初始额度",
            ))
        db.commit()

    return IssuedAccessKey(
        key_id=record.key_id,
        plain_key=record.plain_key,
        owner_name=record.owner_name,
        credit_balance=record.credit_balance,
        advanced_generation_enabled=record.advanced_generation_enabled,
        allow_copy_export=record.allow_copy_export,
        admin_role=record.admin_role,
    )


def register_front_user_with_invite(
    db: Session,
    *,
    username: str,
    password: str,
    invite_code: str,
    phone: str = "",
    email: str = "",
    initial_credit: Decimal | int | float | str = DEFAULT_REGISTER_CREDIT,
) -> RegisteredFrontUser:
    normalized_username = str(username or "").strip()
    normalized_phone = str(phone or "").strip()
    normalized_email = str(email or "").strip().lower()
    raw_password = str(password or "")

    if len(normalized_username) < 2:
        raise ValueError("用户名至少需要 2 个字符")
    if len(raw_password) < 6:
        raise ValueError("密码至少需要 6 位")
    if not str(invite_code or "").strip():
        raise ValueError("请输入邀请码")
    if db.query(FrontUser).filter(FrontUser.username == normalized_username).first():
        raise ValueError("用户名已存在")
    if normalized_phone and db.query(FrontUser).filter(FrontUser.phone == normalized_phone).first():
        raise ValueError("手机号已被注册")
    if normalized_email and db.query(FrontUser).filter(FrontUser.email == normalized_email).first():
        raise ValueError("邮箱已被注册")

    assigned_to = normalized_email or normalized_phone or normalized_username
    invite_row = consume_invite_code(
        db,
        invite_code,
        assigned_to=assigned_to,
        commit=False,
    )
    front_user = FrontUser(
        username=normalized_username,
        phone=normalized_phone,
        email=normalized_email,
        password_hash=hash_front_user_password(raw_password),
        status="active",
        invite_code_id=invite_row.id,
        note=f"邀请码注册：{invite_row.code_prefix}",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(front_user)
    db.flush()

    issued = create_access_key(
        owner_name=normalized_username,
        initial_credit=initial_credit,
        advanced_generation_enabled=False,
        contact=normalized_email or normalized_phone,
        front_user_id=front_user.id,
        db=db,
    )
    front_user.access_key_id = issued.key_id
    db.commit()

    session = login_with_access_key(issued.plain_key, db=db)
    return RegisteredFrontUser(
        front_user_id=front_user.id,
        key_id=issued.key_id,
        plain_key=issued.plain_key,
        owner_name=session.owner_name,
        credit_balance=session.credit_balance,
        advanced_generation_enabled=session.advanced_generation_enabled,
        allow_copy_export=session.allow_copy_export,
        admin_role=session.admin_role,
        status=session.status,
        session_token=session.session_token,
        session_expires_at=session.session_expires_at,
    )


def _normalize_front_user_payload(payload: dict, *, partial: bool = False) -> dict:
    normalized = {
        "username": str(payload.get("username") or "").strip(),
        "password": str(payload.get("password") or ""),
        "phone": str(payload.get("phone") or "").strip(),
        "email": str(payload.get("email") or "").strip().lower(),
        "status": str(payload.get("status") or "").strip(),
        "note": str(payload.get("note") or "").strip(),
    }
    if not partial or "username" in payload:
        if len(normalized["username"]) < 2:
            raise ValueError("用户名至少需要 2 个字符")
    if normalized["password"] and len(normalized["password"]) < 6:
        raise ValueError("密码至少需要 6 位")
    if normalized["status"] and normalized["status"] not in {"active", "disabled"}:
        raise ValueError("用户状态只能是 active 或 disabled")
    return normalized


def _ensure_front_user_unique(
    db: Session,
    *,
    username: str = "",
    phone: str = "",
    email: str = "",
    exclude_user_id: str = "",
) -> None:
    if username:
        query = db.query(FrontUser).filter(FrontUser.username == username)
        if exclude_user_id:
            query = query.filter(FrontUser.id != exclude_user_id)
        if query.first():
            raise ValueError("用户名已存在")
    if phone:
        query = db.query(FrontUser).filter(FrontUser.phone == phone)
        if exclude_user_id:
            query = query.filter(FrontUser.id != exclude_user_id)
        if query.first():
            raise ValueError("手机号已被注册")
    if email:
        query = db.query(FrontUser).filter(FrontUser.email == email)
        if exclude_user_id:
            query = query.filter(FrontUser.id != exclude_user_id)
        if query.first():
            raise ValueError("邮箱已被注册")


def _front_user_item(row: FrontUser, key_row: UserAccessKey | None = None) -> FrontUserAdminItem:
    return FrontUserAdminItem(
        user_id=row.id,
        username=row.username,
        phone=row.phone,
        email=row.email,
        status=row.status,
        note=row.note,
        access_key_id=row.access_key_id or (key_row.id if key_row else ""),
        key_status=key_row.status if key_row else "",
        key_prefix=key_row.key_prefix if key_row else "",
        credit_balance=float(_credit(key_row.credit_balance)) if key_row else 0.0,
        advanced_generation_enabled=bool(key_row.advanced_generation_enabled) if key_row else False,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def _linked_access_key(db: Session, row: FrontUser) -> UserAccessKey | None:
    ensure_access_key_admin_role_column(db)
    if row.access_key_id:
        key_row = db.query(UserAccessKey).filter(UserAccessKey.id == row.access_key_id).first()
        if key_row is not None:
            return key_row
    return db.query(UserAccessKey).filter(UserAccessKey.front_user_id == row.id).first()


def list_front_users(db: Session, *, keyword: str = "", status: str = "") -> list[FrontUserAdminItem]:
    query = db.query(FrontUser).order_by(FrontUser.created_at.desc())
    normalized_keyword = str(keyword or "").strip()
    if normalized_keyword:
        like = f"%{normalized_keyword}%"
        query = query.filter(
            (FrontUser.username.like(like))
            | (FrontUser.phone.like(like))
            | (FrontUser.email.like(like))
            | (FrontUser.note.like(like))
        )
    normalized_status = str(status or "").strip()
    if normalized_status:
        query = query.filter(FrontUser.status == normalized_status)
    else:
        query = query.filter(FrontUser.status != "deleted")
    rows = query.limit(300).all()
    return [_front_user_item(row, _linked_access_key(db, row)) for row in rows]


def create_front_user_by_admin(
    db: Session,
    *,
    username: str,
    password: str,
    phone: str = "",
    email: str = "",
    note: str = "",
    initial_credit: Decimal | int | float | str = DEFAULT_REGISTER_CREDIT,
    advanced_generation_enabled: bool = False,
) -> FrontUserAdminCreateResult:
    payload = _normalize_front_user_payload(
        {"username": username, "password": password, "phone": phone, "email": email, "note": note}
    )
    if not payload["password"]:
        raise ValueError("请设置初始密码")
    _ensure_front_user_unique(db, username=payload["username"], phone=payload["phone"], email=payload["email"])

    now = datetime.now()
    front_user = FrontUser(
        username=payload["username"],
        phone=payload["phone"],
        email=payload["email"],
        password_hash=hash_front_user_password(payload["password"]),
        status="active",
        note=payload["note"] or "后台创建用户",
        created_at=now,
        updated_at=now,
    )
    db.add(front_user)
    db.flush()

    issued = create_access_key(
        owner_name=front_user.username,
        initial_credit=initial_credit,
        advanced_generation_enabled=advanced_generation_enabled,
        contact=front_user.email or front_user.phone,
        front_user_id=front_user.id,
        db=db,
    )
    front_user.access_key_id = issued.key_id
    db.commit()
    db.refresh(front_user)
    key_row = _linked_access_key(db, front_user)
    return FrontUserAdminCreateResult(
        user=_front_user_item(front_user, key_row),
        plain_key=issued.plain_key,
        plain_password=payload["password"],
    )


def update_front_user_by_admin(db: Session, user_id: str, payload: dict) -> FrontUserAdminItem:
    row = db.query(FrontUser).filter(FrontUser.id == str(user_id or "").strip()).first()
    if row is None or row.status == "deleted":
        raise ValueError("注册用户不存在")
    normalized = _normalize_front_user_payload(payload, partial=True)

    next_username = normalized["username"] if "username" in payload else row.username
    next_phone = normalized["phone"] if "phone" in payload else row.phone
    next_email = normalized["email"] if "email" in payload else row.email
    _ensure_front_user_unique(
        db,
        username=next_username,
        phone=next_phone,
        email=next_email,
        exclude_user_id=row.id,
    )

    if "username" in payload:
        row.username = next_username
    if "phone" in payload:
        row.phone = next_phone
    if "email" in payload:
        row.email = next_email
    if "note" in payload:
        row.note = normalized["note"]
    if normalized["password"]:
        row.password_hash = hash_front_user_password(normalized["password"])
    if normalized["status"]:
        row.status = normalized["status"]
    row.updated_at = datetime.now()

    key_row = _linked_access_key(db, row)
    if key_row is not None:
        key_row.owner_name = row.username
        key_row.contact = row.email or row.phone
        if normalized["status"] == "disabled":
            key_row.status = "disabled"
            _disable_front_user_sessions(db, key_row.id)
        elif normalized["status"] == "active":
            key_row.status = "active"

    db.commit()
    db.refresh(row)
    key_row = _linked_access_key(db, row)
    return _front_user_item(row, key_row)


def _disable_front_user_sessions(db: Session, access_key_id: str) -> None:
    db.query(FrontUserSession).filter(FrontUserSession.access_key_id == access_key_id).update(
        {"status": "disabled", "updated_at": datetime.now()},
        synchronize_session=False,
    )


def delete_front_user_by_admin(db: Session, user_id: str) -> FrontUserAdminItem:
    row = db.query(FrontUser).filter(FrontUser.id == str(user_id or "").strip()).first()
    if row is None or row.status == "deleted":
        raise ValueError("注册用户不存在")
    key_row = _linked_access_key(db, row)
    row.status = "deleted"
    row.updated_at = datetime.now()
    if key_row is not None:
        key_row.status = "disabled"
        _disable_front_user_sessions(db, key_row.id)
    db.commit()
    db.refresh(row)
    key_row = _linked_access_key(db, row)
    return _front_user_item(row, key_row)


def seed_default_front_users(db: Session) -> list[FrontUserAdminCreateResult]:
    results: list[FrontUserAdminCreateResult] = []
    for item in DEFAULT_FRONT_USER_SEEDS:
        username = str(item["username"])
        existing = db.query(FrontUser).filter(FrontUser.username == username, FrontUser.status != "deleted").first()
        if existing is not None:
            results.append(FrontUserAdminCreateResult(user=_front_user_item(existing, _linked_access_key(db, existing))))
            continue
        plain_password = generate_seed_password()
        created = create_front_user_by_admin(
            db,
            username=username,
            password=plain_password,
            phone=str(item["phone"]),
            email=str(item["email"]),
            note="后台默认种子用户",
            initial_credit=item["credit"],
            advanced_generation_enabled=bool(item["advanced"]),
        )
        results.append(created)
    return results


def _find_by_plain_key(plain_key: str) -> _AccessKeyRecord | None:
    key_hash = hash_access_key(plain_key)
    for record in _ACCESS_KEYS.values():
        if record.key_hash == key_hash:
            return record
    return None


def _record_from_db_row(row: UserAccessKey) -> _AccessKeyRecord:
    return _AccessKeyRecord(
        key_id=row.id,
        key_hash=row.key_hash,
        plain_key=str(getattr(row, "plain_key", "") or ""),
        owner_name=row.owner_name,
        credit_balance=_credit(row.credit_balance),
        advanced_generation_enabled=bool(row.advanced_generation_enabled),
        allow_copy_export=bool(getattr(row, "allow_copy_export", False)),
        admin_role=normalize_access_key_admin_role(getattr(row, "admin_role", "user")),
        status=row.status,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
    )


def _is_access_key_expired(row: UserAccessKey, *, now: datetime | None = None) -> bool:
    return bool(row.expires_at and row.expires_at < (now or datetime.now()))


def _session_from_record(
    record: _AccessKeyRecord,
    *,
    session_token: str | None = None,
    session_expires_at: datetime | None = None,
) -> AccessKeySession:
    return AccessKeySession(
        key_id=record.key_id,
        owner_name=record.owner_name,
        credit_balance=record.credit_balance,
        advanced_generation_enabled=record.advanced_generation_enabled,
        allow_copy_export=record.allow_copy_export,
        admin_role=record.admin_role,
        status=record.status,
        session_token=session_token,
        session_expires_at=session_expires_at.isoformat() if session_expires_at else None,
    )


def _create_front_user_session(db: Session, row: UserAccessKey) -> tuple[str, datetime]:
    token = generate_user_session_token()
    expires_at = datetime.now() + timedelta(days=USER_SESSION_TTL_DAYS)
    db.add(FrontUserSession(
        session_token_hash=hash_session_token(token),
        access_key_id=row.id,
        owner_name=row.owner_name,
        expires_at=expires_at,
        last_seen_at=datetime.now(),
    ))
    return token, expires_at


def login_with_access_key(plain_key: str, db: Session | None = None) -> AccessKeySession:
    if db is not None:
        ensure_access_key_admin_role_column(db)
        key_hash = hash_access_key(plain_key)
        row = db.query(UserAccessKey).filter(UserAccessKey.key_hash == key_hash).first()
        if row is None or row.status != "active" or _is_access_key_expired(row):
            raise ValueError("密钥无效或已停用")
        ensure_access_key_tenant_database(db, row)
        row.last_used_at = datetime.now()
        session_token, expires_at = _create_front_user_session(db, row)
        db.commit()
        return _session_from_record(
            _record_from_db_row(row),
            session_token=session_token,
            session_expires_at=expires_at,
        )

    record = _find_by_plain_key(plain_key)
    if record is None or record.status != "active":
        raise ValueError("密钥无效或已停用")
    record.last_used_at = datetime.now()
    return _session_from_record(record)


def login_with_front_user_account(username: str, password: str, db: Session) -> AccessKeySession:
    ensure_access_key_admin_role_column(db)
    identifier = str(username or "").strip()
    normalized_email = identifier.lower()
    raw_password = str(password or "")
    if not identifier or not raw_password:
        raise ValueError("请输入账号和密码")

    user = (
        db.query(FrontUser)
        .filter(
            or_(
                FrontUser.username == identifier,
                FrontUser.email == normalized_email,
                FrontUser.phone == identifier,
            )
        )
        .first()
    )
    if user is None or user.status != "active" or not verify_front_user_password(raw_password, user.password_hash):
        raise ValueError("账号或密码错误")

    key_row = None
    if user.access_key_id:
        key_row = db.query(UserAccessKey).filter(UserAccessKey.id == user.access_key_id).first()
    if key_row is None:
        key_row = db.query(UserAccessKey).filter(UserAccessKey.front_user_id == user.id).first()
    if key_row is None or key_row.status != "active" or _is_access_key_expired(key_row):
        raise ValueError("账号未绑定可用密钥，请联系管理员")

    ensure_access_key_tenant_database(db, key_row)
    key_row.last_used_at = datetime.now()
    session_token, expires_at = _create_front_user_session(db, key_row)
    db.commit()
    db.refresh(key_row)
    return _session_from_record(
        _record_from_db_row(key_row),
        session_token=session_token,
        session_expires_at=expires_at,
    )


def verify_user_session_token(session_token: str, db: Session) -> VerifiedUserSession:
    ensure_access_key_admin_role_column(db)
    token_hash = hash_session_token(session_token)
    now = datetime.now()
    session_row = (
        db.query(FrontUserSession)
        .filter(FrontUserSession.session_token_hash == token_hash)
        .first()
    )
    if session_row is None or session_row.status != "active":
        raise ValueError("用户 Session 无效或已退出")
    if session_row.expires_at and session_row.expires_at < now:
        raise ValueError("用户 Session 已过期，请重新登录")

    key_row = db.query(UserAccessKey).filter(UserAccessKey.id == session_row.access_key_id).first()
    if key_row is None or key_row.status != "active" or _is_access_key_expired(key_row, now=now):
        raise ValueError("用户密钥无效或已停用")

    ensure_access_key_tenant_database(db, key_row)
    session_row.last_seen_at = now
    db.commit()
    return VerifiedUserSession(
        key_id=key_row.id,
        owner_name=key_row.owner_name,
        credit_balance=_credit(key_row.credit_balance),
        advanced_generation_enabled=bool(key_row.advanced_generation_enabled),
        allow_copy_export=bool(getattr(key_row, "allow_copy_export", False)),
        admin_role=normalize_access_key_admin_role(getattr(key_row, "admin_role", "user")),
        status=key_row.status,
    )


def set_advanced_generation_enabled(key_id: str, enabled: bool, db: Session | None = None) -> AccessKeySession:
    normalized_id = str(key_id or "").strip()
    if db is not None:
        ensure_access_key_admin_role_column(db)
        row = db.query(UserAccessKey).filter(UserAccessKey.id == normalized_id).first()
        if row is None:
            raise ValueError("密钥不存在")
        row.advanced_generation_enabled = bool(enabled)
        db.commit()
        db.refresh(row)
        return _session_from_record(_record_from_db_row(row))

    record = _ACCESS_KEYS.get(normalized_id)
    if record is None:
        raise ValueError("密钥不存在")
    record.advanced_generation_enabled = bool(enabled)
    return _session_from_record(record)


def set_copy_export_enabled(key_id: str, enabled: bool, db: Session | None = None) -> AccessKeySession:
    normalized_id = str(key_id or "").strip()
    if db is not None:
        ensure_access_key_admin_role_column(db)
        row = db.query(UserAccessKey).filter(UserAccessKey.id == normalized_id).first()
        if row is None:
            raise ValueError("密钥不存在")
        row.allow_copy_export = bool(enabled)
        db.commit()
        db.refresh(row)
        return _session_from_record(_record_from_db_row(row))

    record = _ACCESS_KEYS.get(normalized_id)
    if record is None:
        raise ValueError("密钥不存在")
    record.allow_copy_export = bool(enabled)
    return _session_from_record(record)


def _admin_item_from_row(row: UserAccessKey) -> AccessKeyAdminItem:
    return AccessKeyAdminItem(
        key_id=row.id,
        key_prefix=row.key_prefix,
        plain_key=str(getattr(row, "plain_key", "") or ""),
        owner_name=row.owner_name,
        contact=row.contact,
        status=row.status,
        credit_balance=_credit(row.credit_balance),
        advanced_generation_enabled=bool(row.advanced_generation_enabled),
        allow_copy_export=bool(getattr(row, "allow_copy_export", False)),
        admin_role=normalize_access_key_admin_role(getattr(row, "admin_role", "user")),
        last_used_at=row.last_used_at.isoformat() if row.last_used_at else None,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


def list_access_keys(db: Session, *, keyword: str = "", status: str = "") -> list[AccessKeyAdminItem]:
    ensure_access_key_admin_role_column(db)
    query = db.query(UserAccessKey).order_by(UserAccessKey.created_at.desc())
    normalized_keyword = str(keyword or "").strip()
    if normalized_keyword:
        like = f"%{normalized_keyword}%"
        query = query.filter(
            (UserAccessKey.owner_name.like(like))
            | (UserAccessKey.contact.like(like))
            | (UserAccessKey.key_prefix.like(like))
            | (UserAccessKey.plain_key.like(like))
        )
    normalized_status = str(status or "").strip()
    if normalized_status:
        query = query.filter(UserAccessKey.status == normalized_status)
    else:
        query = query.filter(UserAccessKey.status != "deleted")
    return [_admin_item_from_row(row) for row in query.limit(200).all()]


def _sqlite_ident(value: str) -> str:
    return '"' + str(value or "").replace('"', '""') + '"'


def _delete_by_in_values(db: Session, table_name: str, column_name: str, values: list[str]) -> int:
    if not values:
        return 0
    params = {f"v{i}": value for i, value in enumerate(values)}
    placeholders = ", ".join(f":v{i}" for i in range(len(values)))
    result = db.execute(
        text(
            f"DELETE FROM {_sqlite_ident(table_name)} "
            f"WHERE {_sqlite_ident(column_name)} IN ({placeholders})"
        ),
        params,
    )
    return int(result.rowcount or 0)


def _delete_owned_project_data(db: Session, access_key_id: str) -> int:
    """Delete projects and project-scoped child records owned by one access key."""
    try:
        inspector = inspect(db.get_bind())
        if not inspector.has_table("project_v2"):
            return 0
    except Exception:
        return 0

    from app.models.project_v2 import ProjectV2
    from app.routers.projects._helpers import (
        _remove_workspace_index_entry,
        _safe_rmtree,
        _workspace_delete_roots,
    )

    projects = db.query(ProjectV2).filter(ProjectV2.created_by == str(access_key_id or "").strip()).all()
    if not projects:
        return 0

    project_ids = [str(project.id) for project in projects]
    try:
        shot_ids = [
            str(row[0])
            for row in db.execute(
                text(
                    "SELECT id FROM shots "
                    f"WHERE project_id IN ({', '.join(f':p{i}' for i in range(len(project_ids)))})"
                ),
                {f"p{i}": value for i, value in enumerate(project_ids)},
            ).fetchall()
        ] if inspector.has_table("shots") else []
        if shot_ids and inspector.has_table("shot_prompts"):
            _delete_by_in_values(db, "shot_prompts", "shot_id", shot_ids)
    except Exception:
        pass

    try:
        episode_ids = [
            str(row[0])
            for row in db.execute(
                text(
                    "SELECT id FROM episode "
                    f"WHERE project_id IN ({', '.join(f':p{i}' for i in range(len(project_ids)))})"
                ),
                {f"p{i}": value for i, value in enumerate(project_ids)},
            ).fetchall()
        ] if inspector.has_table("episode") else []
        if episode_ids and inspector.has_table("scene"):
            _delete_by_in_values(db, "scene", "episode_id", episode_ids)
    except Exception:
        pass

    for table_name in inspector.get_table_names():
        if table_name == "project_v2":
            continue
        try:
            column_names = {column["name"] for column in inspector.get_columns(table_name)}
        except Exception:
            continue
        if "project_id" in column_names:
            _delete_by_in_values(db, table_name, "project_id", project_ids)

    for project in projects:
        workspace_path = str(project.workspace_path or "")
        if workspace_path:
            _safe_rmtree(workspace_path, allowed_roots=_workspace_delete_roots())
        _remove_workspace_index_entry(
            workspace=workspace_path,
            project_name=project.name,
            project_id=project.id,
        )
        db.delete(project)

    return len(projects)


def set_access_key_status(db: Session, key_id: str, status: str) -> AccessKeySession:
    ensure_access_key_admin_role_column(db)
    normalized_status = str(status or "").strip()
    if normalized_status not in {"active", "disabled"}:
        raise ValueError("密钥状态只能是 active 或 disabled")
    row = db.query(UserAccessKey).filter(UserAccessKey.id == str(key_id or "").strip()).first()
    if row is None or row.status == "deleted":
        raise ValueError("密钥不存在")
    row.status = normalized_status
    if normalized_status == "disabled":
        _disable_front_user_sessions(db, row.id)
    db.commit()
    db.refresh(row)
    return _session_from_record(_record_from_db_row(row))


def delete_access_key(db: Session, key_id: str) -> AccessKeySession:
    ensure_access_key_admin_role_column(db)
    row = db.query(UserAccessKey).filter(UserAccessKey.id == str(key_id or "").strip()).first()
    if row is None or row.status == "deleted":
        raise ValueError("密钥不存在")
    row.status = "deleted"
    _disable_front_user_sessions(db, row.id)
    _delete_owned_project_data(db, row.id)
    delete_access_key_tenant_database(db, row)
    db.commit()
    db.refresh(row)
    return _session_from_record(_record_from_db_row(row))


def recharge_access_key(
    db: Session,
    key_id: str,
    amount: Decimal | int | float | str,
    *,
    reason: str = "后台手动充值",
) -> AccessKeySession:
    ensure_access_key_admin_role_column(db)
    row = db.query(UserAccessKey).filter(UserAccessKey.id == str(key_id or "").strip()).first()
    if row is None:
        raise ValueError("密钥不存在")
    added = _credit(amount)
    if added <= 0:
        raise ValueError("充值额度必须大于 0")
    balance = _credit(row.credit_balance) + added
    row.credit_balance = balance
    db.add(CreditLedger(
        access_key_id=row.id,
        event_type="recharge",
        amount=added,
        balance_after=balance,
        human_reason=str(reason or "后台手动充值"),
    ))
    db.commit()
    db.refresh(row)
    return _session_from_record(_record_from_db_row(row))


def ensure_access_key_can_spend(
    db: Session,
    key_id: str,
    *,
    minimum_credit: Decimal | int | float | str = MINIMUM_GENERATION_CREDIT,
) -> AccessKeySession:
    ensure_access_key_admin_role_column(db)
    row = db.query(UserAccessKey).filter(UserAccessKey.id == str(key_id or "").strip()).first()
    if row is None or row.status != "active" or _is_access_key_expired(row):
        raise ValueError("密钥不存在或已停用")
    required = _credit(minimum_credit)
    if _credit(row.credit_balance) < required:
        raise ValueError(f"额度不足，至少需要 {required} 额度")
    return _session_from_record(_record_from_db_row(row))


def charge_access_key_for_generation(
    db: Session,
    key_id: str,
    *,
    actual_cost_cny: Decimal | int | float | str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    provider: str = "",
    model: str = "",
    generation_type: str = "generation",
    reason: str = "AI 生成成功扣费",
    input_cost_per_1k: Decimal | int | float | str | None = None,
    output_cost_per_1k: Decimal | int | float | str | None = None,
    billing_multiplier: Decimal | int | float | str | None = None,
    minimum_actual_cost_cny: Decimal | int | float | str | None = None,
) -> AccessKeySession:
    ensure_access_key_admin_role_column(db)
    row = db.query(UserAccessKey).filter(UserAccessKey.id == str(key_id or "").strip()).first()
    if row is None or row.status != "active" or _is_access_key_expired(row):
        raise ValueError("密钥不存在或已停用")

    actual_cost = (
        estimate_generation_actual_cost_cny(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            input_cost_per_1k=input_cost_per_1k if input_cost_per_1k is not None else DEFAULT_INPUT_COST_CNY_PER_1K,
            output_cost_per_1k=output_cost_per_1k if output_cost_per_1k is not None else DEFAULT_OUTPUT_COST_CNY_PER_1K,
            minimum_actual_cost_cny=minimum_actual_cost_cny if minimum_actual_cost_cny is not None else MINIMUM_ACTUAL_COST_CNY,
        )
        if actual_cost_cny is None
        else Decimal(str(actual_cost_cny))
    )
    bill = calculate_billable_credit(
        actual_cost,
        multiplier=billing_multiplier if billing_multiplier is not None else DEFAULT_BILLING_MULTIPLIER,
    )
    current_balance = _credit(row.credit_balance)
    if current_balance < bill.credit_amount:
        raise ValueError(f"额度不足，需要 {bill.credit_amount} 额度，当前余额 {current_balance}")

    balance = current_balance - bill.credit_amount
    row.credit_balance = balance
    db.add(CreditLedger(
        access_key_id=row.id,
        event_type="charge",
        amount=-bill.credit_amount,
        balance_after=balance,
        actual_cost_cny=bill.actual_cost_cny,
        billing_multiplier=bill.multiplier,
        provider=str(provider or ""),
        model=str(model or ""),
        prompt_tokens=max(0, int(prompt_tokens or 0)),
        completion_tokens=max(0, int(completion_tokens or 0)),
        generation_type=str(generation_type or "generation"),
        status="success",
        human_reason=str(reason or "AI 生成成功扣费"),
    ))
    db.commit()
    db.refresh(row)
    return _session_from_record(_record_from_db_row(row))


def record_generation_failure_without_charge(
    db: Session,
    key_id: str,
    *,
    provider: str = "",
    model: str = "",
    generation_type: str = "generation",
    reason: str = "AI 生成失败，未扣费",
) -> None:
    ensure_access_key_admin_role_column(db)
    row = db.query(UserAccessKey).filter(UserAccessKey.id == str(key_id or "").strip()).first()
    if row is None:
        return
    db.add(CreditLedger(
        access_key_id=row.id,
        event_type="charge",
        amount=Decimal("0.00"),
        balance_after=_credit(row.credit_balance),
        actual_cost_cny=Decimal("0.00"),
        provider=str(provider or ""),
        model=str(model or ""),
        generation_type=str(generation_type or "generation"),
        status="failed",
        human_reason=str(reason or "AI 生成失败，未扣费"),
    ))
    db.commit()
