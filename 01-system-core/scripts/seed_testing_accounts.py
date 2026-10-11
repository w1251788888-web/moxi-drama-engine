#!/usr/bin/env python3
"""配置本地测试用 AI、管理员、前台用户和邀请码。

明文测试账号只写入 data/test_accounts_latest.json。data/ 已被 Git 忽略，
不要把该文件提交到仓库。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.config import config
from app.database import Base, SessionLocal, engine
from app.routers.admin import upsert_admin_user
from app.services.saas_access_service import (
    create_front_user_by_admin,
    update_front_user_by_admin,
)
from app.services.saas_admin_query_service import save_llm_provider
from app.services.saas_invite_service import create_invite_codes
from app.models.saas_admin import FrontUser  # noqa: F401


ADMIN_SEEDS = [
    {
        "username": "admin_ops",
        "password": "MoxiAdmin-2026-Ops!",
        "role": "admin",
        "note": "本地测试管理员：运营配置",
    },
    {
        "username": "admin_editor",
        "password": "MoxiAdmin-2026-Edit!",
        "role": "admin",
        "note": "本地测试管理员：内容验收",
    },
    {
        "username": "admin_audit",
        "password": "MoxiAdmin-2026-Audit!",
        "role": "admin",
        "note": "本地测试管理员：审计查看",
    },
]

FRONT_USER_SEEDS = [
    {
        "username": "moxi_user_writer",
        "password": "MoxiUser-Writer-2026!",
        "email": "writer@example.local",
        "credit": 99,
        "advanced": True,
        "note": "本地测试前台用户：高级生成",
    },
    {
        "username": "moxi_user_creator",
        "password": "MoxiUser-Creator-2026!",
        "email": "creator@example.local",
        "credit": 50,
        "advanced": False,
        "note": "本地测试前台用户：普通生成",
    },
    {
        "username": "moxi_user_reviewer",
        "password": "MoxiUser-Reviewer-2026!",
        "email": "reviewer@example.local",
        "credit": 199,
        "advanced": True,
        "note": "本地测试前台用户：验收复核",
    },
]


def _tail(value: str, size: int = 6) -> str:
    value = str(value or "")
    return value[-size:] if value else ""


def _configure_yaml(api_key: str, *, model: str) -> None:
    """同步传统配置，供 text_generation 主链路直接读取。"""
    data = config._data
    data.setdefault("ai", {})
    data["ai"].update({
        "provider": "kimi",
        "base_url": "https://api.moonshot.cn",
        "model": model,
        "api_key": api_key,
    })

    data.setdefault("text_generation", {})
    data["text_generation"].update({
        "enabled": True,
        "provider": "kimi",
        "base_url": "https://api.moonshot.cn",
        "endpoint": "/v1/chat/completions",
        "model": model,
        "api_key": api_key,
        "temperature": data["text_generation"].get("temperature", 0.7),
        "timeout_seconds": data["text_generation"].get("timeout_seconds", 120),
        "ssl_verify": data["text_generation"].get("ssl_verify", True),
    })

    data.setdefault("model_providers", {})
    data["model_providers"].setdefault("kimi", {})
    data["model_providers"]["kimi"].update({
        "name": "Kimi (月之暗面)",
        "provider_type": "openai",
        "base_url": "https://api.moonshot.cn",
        "default_model": model,
        "available_models": ["moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k", "moonshot-v1-auto", "kimi-k2.5"],
        "api_key": api_key,
        "is_default": True,
        "rate_limit_rpm": 60,
        "rate_limit_tpm": 128000,
    })
    config._save()


def _seed_front_user(db, item: dict[str, Any]) -> dict[str, Any]:
    existing = (
        db.query(FrontUser)
        .filter(FrontUser.username == item["username"], FrontUser.status != "deleted")
        .first()
    )
    if existing is not None:
        updated = update_front_user_by_admin(
            db,
            existing.id,
            {
                "username": item["username"],
                "password": item["password"],
                "email": item["email"],
                "status": "active",
                "note": item["note"],
            },
        )
        return {
            "username": item["username"],
            "password": item["password"],
            "plain_key": None,
            "credit_balance": updated.credit_balance,
            "advanced_generation_enabled": updated.advanced_generation_enabled,
            "note": "账号已存在，已重置密码；请用账号登录。",
        }

    created = create_front_user_by_admin(
        db,
        username=item["username"],
        password=item["password"],
        email=item["email"],
        note=item["note"],
        initial_credit=item["credit"],
        advanced_generation_enabled=item["advanced"],
    )
    return {
        "username": item["username"],
        "password": item["password"],
        "plain_key": created.plain_key,
        "credit_balance": created.user.credit_balance,
        "advanced_generation_enabled": created.user.advanced_generation_enabled,
        "note": "新建测试账号。",
    }


def seed_testing_accounts(*, api_key: str, model: str, invites: int, out_path: Path) -> dict[str, Any]:
    if not api_key:
        raise SystemExit("缺少 Moonshot API Key：请传 --api-key 或先写入 config.yaml")

    _configure_yaml(api_key, model=model)
    Base.metadata.create_all(bind=engine)

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ai_config": {
            "provider": "kimi",
            "console_url": "https://platform.moonshot.cn/console",
            "base_url": "https://api.moonshot.cn",
            "model": model,
            "api_key_tail": _tail(api_key),
            "configured_in": ["config.yaml", "llm_provider_setting", "model_provider"],
        },
        "admin_accounts": [],
        "front_user_accounts": [],
        "invite_codes": [],
        "notes": [
            "内置管理员 admin 仍然保留，密码来自 config.yaml。",
            "新增管理员账号存入 admin_user 表，可在 /moxi-admin 登录。",
            "普通用户可用账号密码登录，也可用新建时返回的 plain_key 登录。",
        ],
    }

    with SessionLocal() as db:
        save_llm_provider(db, "kimi", {
            "display_name": "Kimi (Moonshot)",
            "base_url": "https://api.moonshot.cn/v1",
            "api_key": api_key,
            "default_model": model,
            "models": ["moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k", "moonshot-v1-auto", "kimi-k2.5"],
            "is_active": True,
            "is_default": True,
            "input_cost_cny_per_1k": 0.002,
            "output_cost_cny_per_1k": 0.008,
            "billing_multiplier": 5,
            "minimum_actual_cost_cny": 0.01,
        })

        for item in ADMIN_SEEDS:
            row = upsert_admin_user(db, **item)
            report["admin_accounts"].append({
                "username": row.username,
                "password": item["password"],
                "role": row.role,
                "status": row.status,
                "note": row.note,
            })

        for item in FRONT_USER_SEEDS:
            report["front_user_accounts"].append(_seed_front_user(db, item))

        if invites > 0:
            issued_invites = create_invite_codes(
                db,
                count=min(max(invites, 0), 100),
                batch_name="uat-registration",
                max_uses=1,
                assigned_to="manual-testing",
                note="本地测试注册邀请码",
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
    parser = argparse.ArgumentParser(description="配置本地测试账号、邀请码和 Kimi AI")
    parser.add_argument("--api-key", default="", help="Moonshot API Key；留空则沿用 config.yaml")
    parser.add_argument("--model", default="moonshot-v1-128k", help="默认生成模型")
    parser.add_argument("--invites", type=int, default=6, help="生成邀请码数量")
    parser.add_argument("--out", default="data/test_accounts_latest.json", help="明文测试清单输出路径")
    args = parser.parse_args()

    api_key = (
        args.api_key.strip()
        or str(config._data.get("text_generation", {}).get("api_key") or "").strip()
        or str(config._data.get("ai", {}).get("api_key") or "").strip()
    )
    report = seed_testing_accounts(
        api_key=api_key,
        model=args.model,
        invites=args.invites,
        out_path=Path(args.out),
    )
    print(json.dumps({
        "ai_configured": bool(report["ai_config"]["api_key_tail"]),
        "admin_accounts": len(report["admin_accounts"]),
        "front_user_accounts": len(report["front_user_accounts"]),
        "invite_codes": len(report["invite_codes"]),
        "out": str(Path(args.out).resolve()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
