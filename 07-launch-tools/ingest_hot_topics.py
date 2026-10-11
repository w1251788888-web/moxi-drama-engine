#!/usr/bin/env python3
"""
热榜采集 → Dify market_signals_hq 入库
用法:
    python ingest_hot_topics.py            # 跑一次
    python ingest_hot_topics.py --watch    # 默认每 6 小时跑一次
依赖: requests (stdlib 兜底用 urllib)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib import request as urlreq
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

DAILYHOT_BASE = "http://localhost:6688"
DIFY_BASE = "http://localhost/v1"
DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
DATASET_ID = "4983206d-28f9-4979-9291-64e036b3a53b"  # market_signals_hq
LOCAL_TZ = ZoneInfo(os.getenv("TZ") or "Asia/Bangkok")

# 聚焦短剧创作相关的榜单（避免政治/股票/开发者技术类噪声）
SOURCES = [
    "douyin", "weibo", "bilibili", "zhihu", "baidu",
    "douban-movie", "douban-group", "toutiao", "kuaishou", "xiaohongshu",
]

STATE_FILE = Path.home() / ".moxi_hot_state.json"  # 记录已入库 hash，避免重复
TOP_N = 20
TOP10_OVERLAP_THRESHOLD = 0.8
TOP30_NEW_RATIO_THRESHOLD = 0.2
STATE_RETENTION_DAYS = 21
FAILURE_RETENTION_DAYS = 14


def http_get_json(url: str, timeout: int = 15, token: str | None = None) -> dict:
    headers = {"User-Agent": "moxi-hot-ingest/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urlreq.Request(url, headers=headers)
    with urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post_json(url: str, payload: dict, token: str, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urlreq.Request(
        url, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "moxi-hot-ingest/1.0",
        },
    )
    with urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_delete(url: str, token: str, timeout: int = 60) -> None:
    req = urlreq.Request(
        url,
        method="DELETE",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "moxi-hot-ingest/1.0",
        },
    )
    with urlreq.urlopen(req, timeout=timeout):
        return None


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def default_state() -> dict:
    return {
        "hashes": [],
        "platform_snapshots": {},
        "daily_rollups": {},
        "source_failures": {},
    }


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            if isinstance(data, dict):
                state = default_state()
                state.update(data)
                if not isinstance(state.get("platform_snapshots"), dict):
                    state["platform_snapshots"] = {}
                if not isinstance(state.get("daily_rollups"), dict):
                    state["daily_rollups"] = {}
                if not isinstance(state.get("source_failures"), dict):
                    state["source_failures"] = {}
                hashes = state.get("hashes") or []
                state["hashes"] = list(hashes)[-500:]
                return state
        except Exception:
            return default_state()
    return default_state()


def prune_state(state: dict) -> dict:
    today = local_now().date()
    daily_rollups = state.get("daily_rollups") or {}
    kept_rollups: dict[str, dict] = {}
    for day_key, payload in daily_rollups.items():
        try:
            day = datetime.strptime(day_key, "%Y-%m-%d").date()
        except ValueError:
            continue
        if (today - day).days <= STATE_RETENTION_DAYS:
            kept_rollups[day_key] = payload
    state["daily_rollups"] = kept_rollups

    source_failures = state.get("source_failures") or {}
    kept_failures: dict[str, dict] = {}
    for source, payload in source_failures.items():
        last_failed_at = payload.get("last_failed_at")
        if not last_failed_at:
            continue
        try:
            failed_at = datetime.fromisoformat(last_failed_at)
        except ValueError:
            continue
        if local_now() - failed_at <= timedelta(days=FAILURE_RETENTION_DAYS):
            kept_failures[source] = payload
    state["source_failures"] = kept_failures
    return state


def save_state(state: dict) -> None:
    pruned = prune_state(state)
    STATE_FILE.write_text(json.dumps(pruned, ensure_ascii=False, indent=2))


def normalize_title(item: dict) -> str:
    raw = (item.get("title") or item.get("desc") or "").strip()
    if not raw:
        return ""
    if raw.lower() in {"undefined", "null", "none"}:
        return ""
    return raw


def filter_valid_items(items: list[dict]) -> list[dict]:
    valid: list[dict] = []
    for item in items:
        if not normalize_title(item):
            continue
        valid.append(item)
    return valid


def extract_titles(items: list[dict], limit: int) -> list[str]:
    titles: list[str] = []
    for item in items[:limit]:
        title = normalize_title(item)
        if title:
            titles.append(title)
    return titles


def calculate_change_metrics(previous: dict | None, current_items: list[dict]) -> tuple[float, float]:
    if not previous:
        return 0.0, 1.0

    prev_top10 = set(previous.get("top10_titles") or [])
    prev_top30 = set(previous.get("top30_titles") or [])
    curr_top10 = extract_titles(current_items, 10)
    curr_top30 = extract_titles(current_items, 30)
    if not curr_top10 or not curr_top30:
        return 0.0, 0.0

    overlap = len(prev_top10 & set(curr_top10)) / max(1, len(curr_top10))
    new_ratio = sum(1 for title in curr_top30 if title not in prev_top30) / max(1, len(curr_top30))
    return overlap, new_ratio


def should_ingest(previous: dict | None, current_items: list[dict], force: bool = False) -> tuple[bool, str, float, float]:
    overlap, new_ratio = calculate_change_metrics(previous, current_items)
    if force or not previous:
        return True, "forced" if force else "first snapshot", overlap, new_ratio
    if overlap < TOP10_OVERLAP_THRESHOLD:
        return True, f"top10 overlap {overlap:.0%} < {TOP10_OVERLAP_THRESHOLD:.0%}", overlap, new_ratio
    if new_ratio >= TOP30_NEW_RATIO_THRESHOLD:
        return True, f"top30 new ratio {new_ratio:.0%} >= {TOP30_NEW_RATIO_THRESHOLD:.0%}", overlap, new_ratio
    return False, f"stable overlap={overlap:.0%}, new_ratio={new_ratio:.0%}", overlap, new_ratio


def top_emerging_titles(previous: dict | None, current_items: list[dict], limit: int = 8) -> list[str]:
    previous_titles = set((previous or {}).get("top30_titles") or [])
    emerging: list[str] = []
    for title in extract_titles(current_items, 30):
        if title in previous_titles or title in emerging:
            continue
        emerging.append(title)
        if len(emerging) >= limit:
            break
    return emerging


def build_document(platform: str, items: list[dict]) -> tuple[str, str]:
    """把一个平台的热榜聚合成一个 Dify document。"""
    now = local_now().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [f"# {platform} 热榜 · {now}\n"]
    for i, it in enumerate(items[:TOP_N], 1):
        title = normalize_title(it)
        desc = (it.get("desc") or "").strip()
        url = (it.get("url") or it.get("mobileUrl") or "").strip()
        hot = it.get("hot") or ""
        if not title:
            continue
        line = f"{i}. **{title}**"
        if hot:
            line += f" · 热度 {hot}"
        if desc and desc != title:
            line += f"\n   - {desc}"
        if url:
            line += f"\n   - 来源: {url}"
        lines.append(line)
    body = "\n".join(lines)
    doc_name = f"{platform}_{local_now().strftime('%Y%m%d_%H%M')}"
    return doc_name, body


def push_to_dify(doc_name: str, content: str) -> dict:
    url = f"{DIFY_BASE}/datasets/{DATASET_ID}/document/create-by-text"
    payload = {
        "name": doc_name,
        "text": content,
        "indexing_technique": "high_quality",
        "process_rule": {
            "mode": "automatic",
        },
    }
    return http_post_json(url, payload, DIFY_API_KEY)


def list_documents(limit: int = 100) -> list[dict]:
    documents: list[dict] = []
    page = 1
    while True:
        payload = http_get_json(
            f"{DIFY_BASE}/datasets/{DATASET_ID}/documents?page={page}&limit={limit}",
            timeout=20,
            token=DIFY_API_KEY,
        )
        batch = payload.get("data") or []
        documents.extend(batch)
        if not payload.get("has_more"):
            break
        page += 1
    return documents


def delete_document(document_id: str) -> None:
    url = f"{DIFY_BASE}/datasets/{DATASET_ID}/documents/{document_id}"
    http_delete(url, DIFY_API_KEY)


def update_platform_snapshot(state: dict, source: str, items: list[dict], doc_name: str | None = None, doc_id: str | None = None) -> None:
    snapshot = {
        "top10_titles": extract_titles(items, 10),
        "top30_titles": extract_titles(items, 30),
        "last_fingerprint": hashlib.sha1(f"{source}|{json.dumps(extract_titles(items, 30), ensure_ascii=False)}".encode()).hexdigest(),
        "last_captured_at": local_now().isoformat(),
    }
    if doc_name:
        snapshot["last_doc_name"] = doc_name
    if doc_id:
        snapshot["last_doc_id"] = doc_id
    state.setdefault("platform_snapshots", {})[source] = snapshot


def record_daily_rollup(
    state: dict,
    source: str,
    items: list[dict],
    *,
    ingested: bool,
    doc_name: str | None,
    doc_id: str | None,
    overlap: float,
    new_ratio: float,
    previous_snapshot: dict | None,
) -> None:
    day_key = local_now().strftime("%Y-%m-%d")
    day_entry = state.setdefault("daily_rollups", {}).setdefault(day_key, {"platforms": {}})
    platform_entry = day_entry["platforms"].setdefault(
        source,
        {
            "polls": 0,
            "ingested_docs": 0,
            "latest_titles": [],
            "emerging_titles": [],
        },
    )
    platform_entry["polls"] += 1
    if ingested:
        platform_entry["ingested_docs"] += 1
    if doc_name:
        platform_entry["last_doc_name"] = doc_name
    if doc_id:
        platform_entry["last_doc_id"] = doc_id
    platform_entry["last_captured_at"] = local_now().isoformat()
    platform_entry["latest_titles"] = extract_titles(items, 5)
    platform_entry["latest_overlap"] = round(overlap, 4)
    platform_entry["latest_new_ratio"] = round(new_ratio, 4)
    existing_emerging = platform_entry.get("emerging_titles") or []
    for title in top_emerging_titles(previous_snapshot, items):
        if title in existing_emerging:
            continue
        existing_emerging.append(title)
        if len(existing_emerging) >= 12:
            break
    platform_entry["emerging_titles"] = existing_emerging


def record_source_failure(state: dict, source: str, error: str) -> None:
    payload = state.setdefault("source_failures", {}).setdefault(source, {"consecutive_failures": 0})
    payload["consecutive_failures"] = int(payload.get("consecutive_failures") or 0) + 1
    payload["last_error"] = error
    payload["last_failed_at"] = local_now().isoformat()


def clear_source_failure(state: dict, source: str) -> None:
    if source in (state.get("source_failures") or {}):
        state["source_failures"].pop(source, None)


def run_once(force: bool = False) -> dict[str, int]:
    state = load_state()
    total_new = 0
    total_skip = 0
    total_fail = 0
    for src in SOURCES:
        previous_snapshot = (state.get("platform_snapshots") or {}).get(src)
        try:
            data = http_get_json(f"{DAILYHOT_BASE}/{src}")
        except (HTTPError, URLError, TimeoutError) as e:
            record_source_failure(state, src, str(e))
            print(f"[skip] {src}: {e}", file=sys.stderr)
            total_fail += 1
            continue
        items = filter_valid_items(data.get("data") or [])
        if not items:
            print(f"[skip] {src}: empty/invalid")
            total_skip += 1
            continue

        clear_source_failure(state, src)
        ingest, reason, overlap, new_ratio = should_ingest(previous_snapshot, items, force=force)
        if not ingest:
            update_platform_snapshot(state, src, items)
            record_daily_rollup(
                state,
                src,
                items,
                ingested=False,
                doc_name=None,
                doc_id=None,
                overlap=overlap,
                new_ratio=new_ratio,
                previous_snapshot=previous_snapshot,
            )
            print(f"[skip] {src}: {reason}")
            total_skip += 1
            continue
        doc_name, body = build_document(src, items)
        try:
            resp = push_to_dify(doc_name, body)
            doc_id = (resp.get("document") or {}).get("id", "?")
            print(f"[ok]   {src}: pushed {min(len(items), TOP_N)} items ({reason}) → doc {doc_id}")
            update_platform_snapshot(state, src, items, doc_name=doc_name, doc_id=doc_id)
            record_daily_rollup(
                state,
                src,
                items,
                ingested=True,
                doc_name=doc_name,
                doc_id=str(doc_id),
                overlap=overlap,
                new_ratio=new_ratio,
                previous_snapshot=previous_snapshot,
            )
            total_new += 1
        except HTTPError as e:
            record_source_failure(state, src, f"HTTP {e.code}")
            body_err = e.read().decode("utf-8", errors="replace")[:200]
            print(f"[err]  {src}: HTTP {e.code} {body_err}", file=sys.stderr)
            total_fail += 1
        except Exception as e:
            record_source_failure(state, src, str(e))
            print(f"[err]  {src}: {e}", file=sys.stderr)
            total_fail += 1
    save_state(state)
    print(f"—— 本轮新入库 {total_new} 个平台 / 跳过 {total_skip} / 失败 {total_fail} ——")
    return {"new": total_new, "skip": total_skip, "fail": total_fail}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--watch", action="store_true", help="持续运行，每小时跑一次")
    p.add_argument("--interval", type=int, default=21600, help="watch 间隔秒，默认 6 小时")
    p.add_argument("--force", action="store_true", help="忽略稳定性阈值，强制入库")
    args = p.parse_args()

    if args.watch:
        while True:
            try:
                run_once(force=args.force)
            except Exception as e:
                print(f"[fatal] {e}", file=sys.stderr)
            time.sleep(args.interval)
    else:
        run_once(force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
