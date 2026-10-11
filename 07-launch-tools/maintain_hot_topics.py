#!/usr/bin/env python3
"""
热榜知识库维护：
1. 为已结束的自然日生成 1 份日摘要文档
2. 删除超过保留窗口的 live 文档 / digest 文档

默认策略：
  - live 文档保留 72 小时
  - digest 文档保留 14 天
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta

from ingest_hot_topics import (
    LOCAL_TZ,
    SOURCES,
    delete_document,
    list_documents,
    load_state,
    local_now,
    push_to_dify,
    save_state,
)

LIVE_NAME_RE = re.compile(r"^(?P<platform>[a-z0-9-]+)_(?P<stamp>\d{8}_\d{4})$")
DIGEST_NAME_RE = re.compile(r"^digest_(?P<stamp>\d{8})$")


def parse_live_name(name: str) -> tuple[str, datetime] | None:
    match = LIVE_NAME_RE.match(name or "")
    if not match:
        return None
    platform = match.group("platform")
    if platform not in SOURCES:
        return None
    captured_at = datetime.strptime(match.group("stamp"), "%Y%m%d_%H%M").replace(tzinfo=LOCAL_TZ)
    return platform, captured_at


def parse_digest_name(name: str) -> datetime | None:
    match = DIGEST_NAME_RE.match(name or "")
    if not match:
        return None
    return datetime.strptime(match.group("stamp"), "%Y%m%d").replace(tzinfo=LOCAL_TZ)


def build_digest(day_key: str, payload: dict) -> tuple[str, str]:
    day = datetime.strptime(day_key, "%Y-%m-%d").strftime("%Y%m%d")
    platforms = {
        platform: item
        for platform, item in (payload.get("platforms") or {}).items()
        if (item.get("latest_titles") or []) or (item.get("emerging_titles") or [])
    }
    lines = [f"# 热榜日摘要 · {day_key}", ""]
    lines.append(f"- 覆盖平台数：{len(platforms)}")
    lines.append(f"- 生成时间：{local_now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append("")
    lines.append("## 平台概览")
    for platform in sorted(platforms):
        item = platforms[platform]
        latest_titles = item.get("latest_titles") or []
        emerging_titles = item.get("emerging_titles") or []
        lines.append(
            f"- {platform}：轮询 {item.get('polls', 0)} 次，入库 {item.get('ingested_docs', 0)} 次，"
            f"Top5 {(' / '.join(latest_titles) if latest_titles else '无')}"
        )
        if emerging_titles:
            lines.append(f"  新面孔：{' / '.join(emerging_titles[:6])}")
    lines.append("")
    lines.append("## 观察")
    most_active = sorted(
        ((platform, item.get("ingested_docs", 0)) for platform, item in platforms.items()),
        key=lambda pair: pair[1],
        reverse=True,
    )
    if most_active and most_active[0][1] > 0:
        lines.append(f"- 当日变化最频繁的平台：{most_active[0][0]}（入库 {most_active[0][1]} 次）")
    else:
        lines.append("- 当日平台整体较稳定，适合作为“热点降温 / 没有新爆点”的负信号参考。")
    lines.append("- 此摘要用于保留趋势轮廓，明细文档将在保留窗口后自动清理。")
    return f"digest_{day}", "\n".join(lines)


def ensure_daily_digests(state: dict, dry_run: bool = False) -> int:
    today_key = local_now().strftime("%Y-%m-%d")
    created = 0
    for day_key in sorted((state.get("daily_rollups") or {}).keys()):
        if day_key >= today_key:
            continue
        payload = state["daily_rollups"][day_key]
        if payload.get("digest_doc_id"):
            continue
        doc_name, content = build_digest(day_key, payload)
        if dry_run:
            print(f"[dry-run] would create digest {doc_name}")
            created += 1
            continue
        resp = push_to_dify(doc_name, content)
        doc_id = (resp.get("document") or {}).get("id", "")
        payload["digest_doc_name"] = doc_name
        payload["digest_doc_id"] = doc_id
        created += 1
        print(f"[ok]   digest {doc_name} → doc {doc_id}")
    return created


def cleanup_documents(state: dict, live_hours: int, digest_days: int, dry_run: bool = False) -> tuple[int, int]:
    now = local_now()
    deleted_live = 0
    deleted_digest = 0
    documents = list_documents()
    digest_ids_in_state = {
        payload.get("digest_doc_id")
        for payload in (state.get("daily_rollups") or {}).values()
        if payload.get("digest_doc_id")
    }

    for document in documents:
        document_id = document.get("id")
        name = document.get("name") or ""
        live_info = parse_live_name(name)
        digest_ts = parse_digest_name(name)

        if live_info:
            _, captured_at = live_info
            if now - captured_at > timedelta(hours=live_hours):
                if dry_run:
                    print(f"[dry-run] would delete live {name}")
                else:
                    delete_document(str(document_id))
                    print(f"[ok]   deleted live {name}")
                deleted_live += 1
            continue

        if digest_ts and now - digest_ts > timedelta(days=digest_days):
            if dry_run:
                print(f"[dry-run] would delete digest {name}")
            else:
                delete_document(str(document_id))
                print(f"[ok]   deleted digest {name}")
            deleted_digest += 1
            if document_id in digest_ids_in_state:
                for payload in (state.get("daily_rollups") or {}).values():
                    if payload.get("digest_doc_id") == document_id:
                        payload.pop("digest_doc_id", None)
                        payload.pop("digest_doc_name", None)
                        break

    return deleted_live, deleted_digest


def prune_rollup_state(state: dict, digest_days: int) -> None:
    today = local_now().date()
    kept: dict[str, dict] = {}
    for day_key, payload in (state.get("daily_rollups") or {}).items():
        try:
            day = datetime.strptime(day_key, "%Y-%m-%d").date()
        except ValueError:
            continue
        if (today - day).days <= digest_days + 2:
            kept[day_key] = payload
    state["daily_rollups"] = kept


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-hours", type=int, default=72, help="live 热榜文档保留小时数")
    parser.add_argument("--digest-days", type=int, default=14, help="digest 文档保留天数")
    parser.add_argument("--dry-run", action="store_true", help="只打印动作，不真正创建/删除")
    args = parser.parse_args()

    state = load_state()
    created = ensure_daily_digests(state, dry_run=args.dry_run)
    deleted_live, deleted_digest = cleanup_documents(
        state,
        live_hours=args.live_hours,
        digest_days=args.digest_days,
        dry_run=args.dry_run,
    )
    prune_rollup_state(state, digest_days=args.digest_days)
    if not args.dry_run:
        save_state(state)
    print(
        f"—— 维护完成：digest 新增 {created} / live 删除 {deleted_live} / digest 删除 {deleted_digest} ——"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
