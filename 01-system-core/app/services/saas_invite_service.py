"""SaaS 邀请码服务：生成、查询和停用内测邀请码。"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.saas_admin import InviteCode


@dataclass(frozen=True)
class IssuedInviteCode:
    invite_id: str
    plain_code: str
    code_prefix: str
    batch_name: str
    status: str
    max_uses: int
    used_count: int
    assigned_to: str
    note: str


@dataclass(frozen=True)
class InviteCodeItem:
    invite_id: str
    code_prefix: str
    batch_name: str
    status: str
    max_uses: int
    used_count: int
    assigned_to: str
    note: str
    created_at: str | None


def ensure_invite_code_table(db: Session) -> None:
    """兼容已有 SQLite：服务调用时确保 invite_code 表存在。"""
    InviteCode.__table__.create(bind=db.get_bind(), checkfirst=True)


def hash_invite_code(plain_code: str) -> str:
    return hashlib.sha256(str(plain_code or "").strip().encode("utf-8")).hexdigest()


def generate_plain_invite_code() -> str:
    parts = [secrets.token_hex(2).upper() for _ in range(3)]
    return "MOXI-INV-" + "-".join(parts)


def _item_from_row(row: InviteCode) -> InviteCodeItem:
    return InviteCodeItem(
        invite_id=row.id,
        code_prefix=row.code_prefix,
        batch_name=row.batch_name,
        status=row.status,
        max_uses=int(row.max_uses or 1),
        used_count=int(row.used_count or 0),
        assigned_to=row.assigned_to,
        note=row.note,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


def _issued_from_row(row: InviteCode, plain_code: str) -> IssuedInviteCode:
    return IssuedInviteCode(
        invite_id=row.id,
        plain_code=plain_code,
        code_prefix=row.code_prefix,
        batch_name=row.batch_name,
        status=row.status,
        max_uses=int(row.max_uses or 1),
        used_count=int(row.used_count or 0),
        assigned_to=row.assigned_to,
        note=row.note,
    )


def create_invite_codes(
    db: Session,
    *,
    count: int = 1,
    batch_name: str = "demo",
    max_uses: int = 1,
    assigned_to: str = "",
    note: str = "",
) -> list[IssuedInviteCode]:
    ensure_invite_code_table(db)
    normalized_count = min(max(1, int(count or 1)), 100)
    normalized_max_uses = min(max(1, int(max_uses or 1)), 100)
    issued: list[IssuedInviteCode] = []

    for _ in range(normalized_count):
        plain_code = generate_plain_invite_code()
        row = InviteCode(
            code_hash=hash_invite_code(plain_code),
            code_prefix=plain_code[:18],
            batch_name=str(batch_name or "demo").strip() or "demo",
            status="active",
            max_uses=normalized_max_uses,
            used_count=0,
            assigned_to=str(assigned_to or "").strip(),
            note=str(note or "").strip(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(row)
        db.flush()
        issued.append(_issued_from_row(row, plain_code))

    db.commit()
    return issued


def list_invite_codes(db: Session, *, status: str = "", batch_name: str = "") -> list[InviteCodeItem]:
    ensure_invite_code_table(db)
    query = db.query(InviteCode).order_by(InviteCode.created_at.desc())
    normalized_status = str(status or "").strip()
    if normalized_status:
        query = query.filter(InviteCode.status == normalized_status)
    normalized_batch = str(batch_name or "").strip()
    if normalized_batch:
        query = query.filter(InviteCode.batch_name == normalized_batch)
    return [_item_from_row(row) for row in query.limit(200).all()]


def set_invite_code_status(db: Session, invite_id: str, status: str) -> InviteCodeItem:
    ensure_invite_code_table(db)
    normalized_status = str(status or "").strip()
    if normalized_status not in {"active", "disabled"}:
        raise ValueError("邀请码状态只能是 active 或 disabled")
    row = db.query(InviteCode).filter(InviteCode.id == str(invite_id or "").strip()).first()
    if row is None:
        raise ValueError("邀请码不存在")
    row.status = normalized_status
    row.updated_at = datetime.now()
    db.commit()
    db.refresh(row)
    return _item_from_row(row)


def consume_invite_code(
    db: Session,
    plain_code: str,
    *,
    assigned_to: str = "",
    commit: bool = True,
) -> InviteCode:
    """校验并占用邀请码；注册链路可在同一事务中延迟提交。"""
    ensure_invite_code_table(db)
    code_hash = hash_invite_code(plain_code)
    row = db.query(InviteCode).filter(InviteCode.code_hash == code_hash).first()
    if row is None:
        raise ValueError("邀请码不存在")
    if row.status != "active":
        raise ValueError("邀请码不可用")
    if row.expires_at and row.expires_at < datetime.now():
        row.status = "disabled"
        row.updated_at = datetime.now()
        if commit:
            db.commit()
        raise ValueError("邀请码已过期")
    if int(row.used_count or 0) >= int(row.max_uses or 1):
        row.status = "used"
        row.updated_at = datetime.now()
        if commit:
            db.commit()
        raise ValueError("邀请码已被使用")

    row.used_count = int(row.used_count or 0) + 1
    row.assigned_to = str(assigned_to or row.assigned_to or "").strip()
    if int(row.used_count or 0) >= int(row.max_uses or 1):
        row.status = "used"
    row.updated_at = datetime.now()
    if commit:
        db.commit()
        db.refresh(row)
    return row
