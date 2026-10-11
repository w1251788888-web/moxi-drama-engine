"""短剧写作会话的"导出"工具（从 short_drama_writing.py 抽出）。

提供：
- resolve_export_episode_range：根据 scope（all_episodes / one_episode）确定导集范围
- normalize_script_text：把 LLM 偶发产出的 JSON 嵌套剧本格式还原成纯剧本文本
- export_txt / export_docx：写到项目库验收产物目录

写盘路径来自 workspace_service，统一落在项目库受控产物根下。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from app.services import workspace_service
from app.services.short_drama_quality_helpers import coerce_generation_text
from app.services.short_drama_step_payload import get_step_payload, list_episodes_with_steps


class NoExportableScriptError(ValueError):
    """导出范围内没有可用剧本正文。"""


def resolve_export_episode_range(metadata: dict, scope: str, episode_no: int) -> list[int]:
    """根据 scope 确定要导出的集号列表。"""
    if scope == "all_episodes":
        eps = list_episodes_with_steps(metadata)
        if eps:
            return eps
        # 兜底：按 project.episode_count 推断
        try:
            n = int((metadata.get("project") or {}).get("episode_count") or 0)
        except Exception:
            n = 0
        if n > 0:
            return list(range(1, n + 1))
        return [episode_no]
    return [episode_no]


def _collect_exportable_scripts(metadata: dict, episode_no: int, scope: str) -> list[tuple[int, str]]:
    scripts: list[tuple[int, str]] = []
    episodes_to_export = resolve_export_episode_range(metadata, scope, episode_no)
    for ep in episodes_to_export:
        sd_payload = get_step_payload(metadata, "script_draft", ep)
        if not isinstance(sd_payload, dict):
            continue
        raw_content = coerce_generation_text(sd_payload.get("full_output"))
        if not raw_content:
            continue
        clean_text = normalize_script_text(raw_content)
        if not clean_text:
            continue
        scripts.append((ep, clean_text))
    if not scripts:
        raise NoExportableScriptError("未找到可导出的剧本正文，请先生成并保存剧本")
    return scripts


def normalize_script_text(raw: str) -> str:
    """修复44: 把 LLM 可能产出的 JSON 嵌套剧本格式还原成纯剧本文本。
    支持以下退化路径：
    - JSON 对象（"场1": {"场景":..., "人物":..., "描述":...}）→ 提取场次标头 + 描述文本
    - JSON 数组里塞剧本字段 → 同上
    - 已经是纯文本 → 原样返回
    """
    if not raw:
        return ""
    text = (raw or "").strip()
    if not text:
        return ""
    # 已是纯文本（不以 { [ 开头）→ 直接返回
    if not text.startswith(("{", "[")):
        return text
    # 尝试 JSON 解析
    try:
        data = json.loads(text)
    except Exception:
        return text  # 解析不了就当文本

    out_lines: list[str] = []

    def _emit(s: str) -> None:
        if s:
            out_lines.append(s.rstrip())

    def _walk(node, depth: int = 0) -> None:
        """递归把 dict 解构成剧本文本。"""
        if isinstance(node, dict):
            for k, v in node.items():
                key_str = str(k or "").strip()
                # 跳过元数据键（不进剧本正文）
                if key_str in (
                    "context_output", "角色名清单", "本集冲突链", "本集关键反转",
                    "集末钩子", "爽感爆发点列表", "声纹卡校验结果",
                    "漫剧项目-实际字数", "一句话说明本集命中的平台热分类与爆点类型",
                    "platform_match", "char_voice_check", "metadata",
                ):
                    continue
                # 场次标头模式："场1" / "【场1-1：日 内 地点】" / "第1集"
                if re.match(r'^(?:【\s*场\s*\d|场\s*\d|第\s*\d+\s*集)', key_str):
                    _emit("")
                    if "【" in key_str:
                        _emit(key_str)  # 已是完整标头
                    else:
                        # 尝试从 value 抽场景信息拼成标头
                        if isinstance(v, dict):
                            scene_hint = str(v.get("场景") or v.get("时间") or "").strip()
                            place_hint = str(v.get("地点") or "").strip()
                            if scene_hint or place_hint:
                                hdr = f"【{key_str}：{scene_hint}{(' ' + place_hint) if place_hint else ''}】".strip()
                                _emit(hdr)
                            else:
                                _emit(f"【{key_str}】")
                        else:
                            _emit(f"【{key_str}】")
                    if isinstance(v, dict):
                        # 提取人物列表
                        chars = v.get("人物")
                        if chars:
                            if isinstance(chars, list):
                                _emit("人物：" + "，".join(str(c).strip() for c in chars if c))
                            else:
                                _emit(f"人物：{chars}")
                        # 描述/剧情字段：可能是字符串、列表、或键值动作行
                        for desc_key in ("描述", "剧情", "内容"):
                            desc_v = v.get(desc_key)
                            if desc_v is None:
                                continue
                            if isinstance(desc_v, str):
                                # 已经是带 △/角色台词 的多行文本
                                for ln in desc_v.split("\n"):
                                    _emit(ln.strip())
                            elif isinstance(desc_v, list):
                                for item in desc_v:
                                    if isinstance(item, str):
                                        _emit(item.strip())
                                    elif isinstance(item, dict):
                                        # 极端情况，再递归
                                        _walk(item, depth + 1)
                        # 兜底：如果没有标准 description，把所有 △ 开头的 key 直接提取
                        for sub_k, sub_v in v.items():
                            sk = str(sub_k or "").strip()
                            if sk in ("人物", "场景", "时间", "地点", "描述", "剧情", "内容"):
                                continue
                            if sk.startswith(("△", "▲")):
                                _emit(sk)
                            elif re.match(r'^[^\s：:]{1,8}[（(].*?[)）][：:]|^[^\s：:]{1,8}[：:]', sk):
                                _emit(sk)
                            elif isinstance(sub_v, str) and sub_v.strip():
                                _emit(f"{sk}：{sub_v.strip()}")
                    elif isinstance(v, str):
                        _emit(v)
                    elif isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                _emit(item.strip())
                            elif isinstance(item, dict):
                                _walk(item, depth + 1)
                    continue
                # 集标题（如 "第1集": "《抢婚揭秘》"）
                if re.match(r'^第\s*\d+\s*集$', key_str) and isinstance(v, str):
                    _emit("")
                    _emit(f"# {key_str} {v}")
                    continue
                # 普通分场结尾、注释类键 → 当作场尾备注
                if isinstance(v, str) and v.strip():
                    if "结尾" in key_str:
                        _emit(v.strip())
                    elif key_str.startswith(("△", "▲")):
                        _emit(key_str)  # JSON key 本身就是动作行
                    # 其他简单键值跳过（多半是元数据）
                    continue
                # 字典/列表 value → 递归
                if isinstance(v, (dict, list)):
                    _walk(v, depth + 1)
        elif isinstance(node, list):
            for item in node:
                _walk(item, depth + 1)

    _walk(data)
    cleaned = "\n".join(out_lines).strip()
    return cleaned or text  # 如果走完没产出，兜底返回原文


def export_txt(session_name: str, metadata: dict, episode_no: int, scope: str = "one_episode") -> Path:
    """严格按剧本样式导出 txt，除剧本本身外其他内容一概不要。"""
    scripts = _collect_exportable_scripts(metadata, episode_no, scope)
    export_root = workspace_service.ensure_acceptance_artifacts_root()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    project = metadata.get("project") or {}
    proj_name = str(project.get("name") or session_name).strip()
    path = workspace_service.artifact_path(f"{proj_name}-剧本-{timestamp}.txt", root=export_root)

    parts: list[str] = []
    parts.append(f"# {proj_name}\n")
    for ep, clean_text in scripts:
        parts.append(f"\n## 第 {ep} 集\n{clean_text}\n")

    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def export_docx(session_name: str, metadata: dict, episode_no: int, scope: str = "one_episode") -> Path:
    """严格按剧本样式导出 docx，除剧本本身外其他内容一概不要。"""
    from docx import Document

    scripts = _collect_exportable_scripts(metadata, episode_no, scope)
    export_root = workspace_service.ensure_acceptance_artifacts_root()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    project = metadata.get("project") or {}
    proj_name = str(project.get("name") or session_name).strip()
    path = workspace_service.artifact_path(f"{proj_name}-剧本-{timestamp}.docx", root=export_root)

    doc = Document()
    # 仅保留极简标题
    doc.add_heading(proj_name, level=0)

    for ep, clean_text in scripts:
        # 集标题
        doc.add_heading(f"第 {ep} 集", level=1)
        # 逐行输出（保持原有空行 / 场次分隔）
        for ln in clean_text.split("\n"):
            ln = ln.rstrip()
            doc.add_paragraph(ln)
        # 集间空行
        doc.add_paragraph("")

    doc.save(path)
    return path
