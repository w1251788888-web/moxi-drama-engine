#!/usr/bin/env python3
"""污染扫描器：揪出"系统生成的测试产物"混进【规则/知识库/头部样本库】的情况。

用途：每次大改素材/规则后重跑一次，防止测试生成内容再次污染金标准。
只读、只报告候选，不自动删除（由人确认）。

运行：cd 01-system-core && .venv/bin/python scripts/scan_contamination.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 受保护的"金标准/curated"区域（这里不该出现生成产物）
CURATED_DIRS = [
    REPO_ROOT / "02-creation-rules" / "core-rules",
    REPO_ROOT / "02-creation-rules" / "knowledge-base",
    REPO_ROOT / "02-creation-rules" / "templates",
    REPO_ROOT / "06-docs" / "archive" / "material-library-source-20260517" / "04-material-library" / "top-sample-scripts",
]

# 已知合法、天然包含生成关键词的"提示词模板"区，跳过（误报源）
WHITELIST_DIRS = [
    REPO_ROOT / "02-creation-rules" / "step-definitions",
]
WHITELIST_FILES = {
    REPO_ROOT / "02-creation-rules" / "system.md",
}

# 已审明的合法上下文：这些文件不是生成产物，只是在说明如何避免污染。
ALLOWED_SIGNATURES_BY_FILE = {
    REPO_ROOT / "02-creation-rules" / "knowledge-base" / "rag_cards" / "manga_platform_rules_2026.md": {
        "自由发挥",
    },
    REPO_ROOT
    / "06-docs"
    / "archive"
    / "material-library-source-20260517"
    / "04-material-library"
    / "top-sample-scripts"
    / "README.md": {
        "自由发挥",
        "context_output",
        "故事结束",
    },
}

# 生成/测试产物的强特征（出现在 curated 区即可疑）
GEN_SIGNATURES = [
    "自由发挥",
    "可在以上故事基础上",
    "context_output",
    "full_output",
    "故事结束",
    "（全文完）",
    "参考是枝裕和",          # 道别 brief 特征，泛化为"导演风格指令"
    "写出一个",              # "写出一个…式电影"类生成指令
]
# 头部样本库里：真样本应是拍摄稿(pdf)，可疑格式
SUSPECT_SAMPLE_EXT = {".docx", ".txt", ".md"}  # md=README 例外见下


def _is_whitelisted(p: Path) -> bool:
    if p in WHITELIST_FILES:
        return True
    return any(str(p).startswith(str(d)) for d in WHITELIST_DIRS)


def _allowed_signatures(p: Path) -> set[str]:
    return ALLOWED_SIGNATURES_BY_FILE.get(p, set())


def scan_text_signatures() -> list[tuple[Path, list[str]]]:
    hits: list[tuple[Path, list[str]]] = []
    for base in CURATED_DIRS:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or _is_whitelisted(p):
                continue
            if p.suffix.lower() not in {".md", ".txt", ".json"}:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            allowed = _allowed_signatures(p)
            found = [s for s in GEN_SIGNATURES if s in text and s not in allowed]
            if found:
                hits.append((p, found))
    return hits


def scan_sample_format() -> list[Path]:
    """头部样本库里非拍摄稿格式（docx/txt 而非 pdf）= 可疑伪装样本。"""
    suspects: list[Path] = []
    base = REPO_ROOT / "06-docs" / "archive" / "material-library-source-20260517" / "04-material-library" / "top-sample-scripts"
    if not base.exists():
        return suspects
    for p in base.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUSPECT_SAMPLE_EXT and p.name.lower() != "readme.md":
            suspects.append(p)
    return suspects


def main() -> int:
    print("=" * 60)
    print("污染扫描：生成产物混入 curated 区检测")
    print("=" * 60)

    sig_hits = scan_text_signatures()
    fmt_hits = scan_sample_format()

    if sig_hits:
        print(f"\n⚠️ [文本特征] {len(sig_hits)} 个文件含生成/测试产物特征（需人工确认）：")
        for p, found in sig_hits:
            print(f"  - {p.relative_to(REPO_ROOT)}  ←含 {found}")
    else:
        print("\n✅ [文本特征] curated 区未发现生成产物特征。")

    if fmt_hits:
        print(f"\n⚠️ [样本格式] 头部样本库有 {len(fmt_hits)} 个非拍摄稿格式文件（真头部应为 PDF 拍摄稿）：")
        for p in fmt_hits:
            print(f"  - {p.relative_to(REPO_ROOT)}")
    else:
        print("\n✅ [样本格式] 头部样本库均为拍摄稿格式。")

    total = len(sig_hits) + len(fmt_hits)
    print("\n" + "=" * 60)
    print(f"结论：{'发现 %d 个候选，请人工确认是否为污染并隔离。' % total if total else '未发现污染候选。'}")
    print("=" * 60)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
