#!/usr/bin/env python3
"""生成本地 Demo SaaS 用户密钥和邀请码。

明文密钥/邀请码只写到 data/demo_seed_latest.json（该目录已被 .gitignore 忽略），
不要提交到 Git。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.database import Base, SessionLocal, engine
from app.models.saas_admin import InviteCode  # noqa: F401
from app.services.saas_access_service import create_access_key
from app.services.saas_invite_service import create_invite_codes


DEFAULT_USERS = [
    ("内测编剧A", 99, True),
    ("普通体验用户B", 30, False),
    ("高级生成体验C", 199, True),
]


def seed_demo_saas(
    *,
    users: int,
    invites: int,
    out_path: Path,
) -> dict:
    Base.metadata.create_all(bind=engine)
    report: dict[str, object] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "users": [],
        "invite_codes": [],
        "notes": [
            "管理员账号仍使用 config.yaml 的 admin.password，不在数据库随机生成。",
            "普通用户通过 user_access_key 登录。",
            "邀请码明文只保存在本地 data/demo_seed_latest.json，不进入 Git。",
        ],
    }
    with SessionLocal() as db:
        for idx, (owner_name, credit, advanced) in enumerate(DEFAULT_USERS[: max(0, users)], start=1):
            issued = create_access_key(
                owner_name=f"{owner_name}-{idx}",
                initial_credit=credit,
                advanced_generation_enabled=advanced,
                db=db,
            )
            report["users"].append({
                "owner_name": issued.owner_name,
                "plain_key": issued.plain_key,
                "credit_balance": float(issued.credit_balance),
                "advanced_generation_enabled": issued.advanced_generation_enabled,
            })

        if invites > 0:
            issued_invites = create_invite_codes(
                db,
                count=invites,
                batch_name="demo-internal",
                max_uses=1,
                note="本地 Demo 种子",
            )
            report["invite_codes"] = [
                {
                    "plain_code": item.plain_code,
                    "code_prefix": item.code_prefix,
                    "batch_name": item.batch_name,
                    "status": item.status,
                }
                for item in issued_invites
            ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="生成本地 Demo SaaS 用户密钥和邀请码")
    parser.add_argument("--users", type=int, default=3, help="生成普通用户密钥数量，最多 3 个预设用户")
    parser.add_argument("--invites", type=int, default=5, help="生成邀请码数量")
    parser.add_argument(
        "--out",
        default="data/demo_seed_latest.json",
        help="明文种子输出路径，默认写入被 Git 忽略的 data 目录",
    )
    args = parser.parse_args()
    report = seed_demo_saas(
        users=min(max(args.users, 0), len(DEFAULT_USERS)),
        invites=min(max(args.invites, 0), 100),
        out_path=Path(args.out),
    )
    print(json.dumps({
        "users": len(report["users"]),
        "invite_codes": len(report["invite_codes"]),
        "out": str(Path(args.out).resolve()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
