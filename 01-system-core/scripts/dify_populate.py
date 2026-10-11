#!/usr/bin/env python3
"""
Dify 知识库灌库工具

用法示例：
    # 把 04-material-library 下的所有 md/txt 上传到 market_signals 知识库
    python scripts/dify_populate.py \\
        --dataset market_signals \\
        --source-dir ../04-material-library \\
        --ext md,txt

    # 把某个项目目录下 quality_check >=42 的 script_draft 上传到 asset_library
    python scripts/dify_populate.py \\
        --dataset asset_library \\
        --source-dir ../03-project-library/new-projects/PROJECT_A \\
        --ext md,txt,json \\
        --filter-json-key quality_score --filter-json-min 42

    # 上传单个小说文件到 novel_<project_id> 知识库
    python scripts/dify_populate.py \\
        --dataset-id <dify_dataset_uuid> \\
        --file ../05-素材库/小说/甜宠霸总.txt \\
        --chunk-size 800

依赖：httpx pyyaml
配置来源：优先读取 config.yaml 的 rag.dify.{base_url,api_key,datasets}，CLI 参数覆盖。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
import yaml


def load_dify_config(config_path: Path) -> tuple[str, str, dict]:
    if not config_path.exists():
        return "", "", {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    dify = ((data.get("rag") or {}).get("dify") or {})
    return (
        str(dify.get("base_url", "")).rstrip("/"),
        str(dify.get("api_key", "")),
        dict(dify.get("datasets") or {}),
    )


def resolve_dataset_id(name_or_id: str, dataset_map: dict, base_url: str, api_key: str) -> str:
    """name_or_id 既可能是逻辑名（asset_library）也可能是 Dify dataset_id（UUID）。"""
    if name_or_id in dataset_map and dataset_map[name_or_id]:
        return dataset_map[name_or_id]
    # 当作 UUID 直接返回
    if len(name_or_id) >= 20:
        return name_or_id
    # 尝试通过 Dify /v1/datasets 列表匹配 name
    try:
        r = httpx.get(
            f"{base_url}/v1/datasets",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"page": 1, "limit": 100},
            timeout=10.0,
        )
        r.raise_for_status()
        for ds in (r.json().get("data") or []):
            if ds.get("name") == name_or_id:
                return ds.get("id", "")
    except Exception as exc:
        print(f"[warn] 无法自动查询 dataset 列表：{exc}", file=sys.stderr)
    raise SystemExit(
        f"❌ 无法解析 dataset='{name_or_id}'。请在 config.yaml 的 rag.dify.datasets 中填入映射，或传入 --dataset-id <UUID>。"
    )


def iter_source_files(source_dir: Path, exts: list[str]) -> list[Path]:
    ext_set = {e.lower().lstrip(".") for e in exts}
    files: list[Path] = []
    for p in source_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower().lstrip(".") in ext_set:
            files.append(p)
    return sorted(files)


def apply_json_filter(path: Path, key: str, min_value: float) -> bool:
    if path.suffix.lower() != ".json":
        return True  # 非 JSON 不过滤
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    # 递归查找 key
    def find_val(d):
        if isinstance(d, dict):
            if key in d:
                return d[key]
            for v in d.values():
                r = find_val(v)
                if r is not None:
                    return r
        elif isinstance(d, list):
            for v in d:
                r = find_val(v)
                if r is not None:
                    return r
        return None

    val = find_val(data)
    try:
        return val is not None and float(val) >= min_value
    except Exception:
        return False


TEXT_EXTS = {"md", "txt", "markdown"}
BINARY_EXTS = {"docx", "pdf", "html", "htm", "xlsx", "pptx", "csv"}


def upload_text(base_url: str, api_key: str, dataset_id: str, name: str, text: str,
                indexing: str = "economy", retries: int = 3) -> bool:
    url = f"{base_url}/v1/datasets/{dataset_id}/document/create-by-text"
    payload = {
        "name": name[:120],
        "text": text,
        "indexing_technique": indexing,
        "process_rule": {"mode": "automatic"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(1, retries + 1):
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=60.0)
            if r.status_code in (200, 201):
                return True
            print(f"  ❌ {r.status_code} {r.text[:200]}", file=sys.stderr)
        except Exception as exc:
            print(f"  ⚠️ attempt {attempt}: {exc}", file=sys.stderr)
        time.sleep(2 * attempt)
    return False


def upload_file(base_url: str, api_key: str, dataset_id: str, path: Path,
                indexing: str = "economy", retries: int = 3) -> bool:
    """用于 .docx/.pdf/.html/.xlsx/.pptx/.csv 等 Dify 原生支持的文档格式。"""
    url = f"{base_url}/v1/datasets/{dataset_id}/document/create-by-file"
    data_payload = {
        "indexing_technique": indexing,
        "process_rule": {"mode": "automatic"},
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    for attempt in range(1, retries + 1):
        try:
            with open(path, "rb") as fh:
                files = {
                    "file": (path.name, fh, "application/octet-stream"),
                    "data": (None, json.dumps(data_payload), "application/json"),
                }
                r = httpx.post(url, files=files, headers=headers, timeout=120.0)
            if r.status_code in (200, 201):
                return True
            print(f"  ❌ {r.status_code} {r.text[:200]}", file=sys.stderr)
        except Exception as exc:
            print(f"  ⚠️ attempt {attempt}: {exc}", file=sys.stderr)
        time.sleep(2 * attempt)
    return False


def main() -> int:
    default_config = Path(__file__).resolve().parents[1] / "config.yaml"

    ap = argparse.ArgumentParser(description="上传本地文件到 Dify 知识库")
    ap.add_argument("--config", default=str(default_config), help="config.yaml 路径")
    ap.add_argument("--base-url", default=None, help="覆盖 config.yaml 中 base_url")
    ap.add_argument("--api-key", default=None, help="覆盖 config.yaml 中 api_key")
    ap.add_argument("--dataset", default=None, help="知识库逻辑名（对照 config.yaml 映射）")
    ap.add_argument("--dataset-id", default=None, help="直接传 Dify dataset_id（UUID），优先级高于 --dataset")
    ap.add_argument("--source-dir", default=None, help="批量上传：源目录")
    ap.add_argument("--file", default=None, help="单文件上传")
    ap.add_argument("--ext", default="md,txt,docx,pdf", help="批量模式下接受的文件扩展名，逗号分隔")
    ap.add_argument("--chunk-size", type=int, default=1000, help="每段最大 token")
    ap.add_argument("--indexing", default="economy", choices=["economy", "high_quality"],
                    help="economy=关键词索引（无需嵌入模型，默认），high_quality=向量索引（需嵌入模型）")
    ap.add_argument("--filter-json-key", default=None, help="针对 .json 文件：只上传 key 值 >= min 的文件")
    ap.add_argument("--filter-json-min", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    base_url_cfg, api_key_cfg, dataset_map = load_dify_config(Path(args.config))
    base_url = (args.base_url or base_url_cfg or "http://localhost").rstrip("/")
    api_key = args.api_key or api_key_cfg
    if not api_key:
        print("❌ 未配置 Dify api_key（config.yaml:rag.dify.api_key 或 --api-key）", file=sys.stderr)
        return 2

    if not args.dataset and not args.dataset_id:
        print("❌ 必须指定 --dataset 或 --dataset-id", file=sys.stderr)
        return 2

    dataset_id = args.dataset_id or resolve_dataset_id(args.dataset, dataset_map, base_url, api_key)
    print(f"▶ 目标知识库：{dataset_id}")

    # 收集文件
    if args.file:
        files = [Path(args.file)]
    elif args.source_dir:
        src = Path(args.source_dir).resolve()
        if not src.is_dir():
            print(f"❌ 源目录不存在：{src}", file=sys.stderr)
            return 2
        files = iter_source_files(src, [e.strip() for e in args.ext.split(",") if e.strip()])
    else:
        print("❌ 必须指定 --file 或 --source-dir", file=sys.stderr)
        return 2

    if args.filter_json_key:
        files = [f for f in files if apply_json_filter(f, args.filter_json_key, args.filter_json_min)]

    print(f"▶ 待上传文件数：{len(files)}")
    if args.dry_run:
        for f in files:
            print(f"  - {f}")
        return 0

    success, failed = 0, 0
    for idx, fp in enumerate(files, 1):
        ext = fp.suffix.lower().lstrip(".")
        name = f"{fp.parent.name}/{fp.name}"
        print(f"[{idx}/{len(files)}] 上传 {name}")
        ok = False
        if ext in TEXT_EXTS:
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore").strip()
            except Exception as exc:
                print(f"  ⚠️ 读取失败：{exc}")
                text = ""
            if text:
                ok = upload_text(base_url, api_key, dataset_id, name, text, indexing=args.indexing)
        elif ext in BINARY_EXTS:
            ok = upload_file(base_url, api_key, dataset_id, fp, indexing=args.indexing)
        else:
            print(f"  ⏭️ 跳过不支持的扩展名 .{ext}")
            continue
        success += int(ok)
        failed += int(not ok)
        time.sleep(0.3)  # 限速

    print(f"\n✅ 成功 {success} / ❌ 失败 {failed} / 共 {len(files)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
