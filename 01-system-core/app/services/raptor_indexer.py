"""RAPTOR 风格的剧本三层切片索引器

设计思路（参考 ICLR 2024 RAPTOR + Frontiers 2025 增强版）：
- 叶层（beats）：剧本中的关键情节单元（场景片段/转折/冲突），原文片段
- 中层（scene_cards）：场景卡，含人物/动作/转折点摘要
- 根层（summary）：本集梗概（200 字）

每一层都可作为独立文档写入 project_{project_id} 数据集，
但外部私有项目 RAG 默认关闭；用户项目事实源始终是 DB + 用户工作区目录。
metadata 必含 {episode, layer, scene_id?, character_ids[], beat_type?}，
检索时按 metadata 过滤，避免跨集人物指代崩溃。

如 Dify 不可达，返回降级结果（每层 doc_id 留空），不阻断主流程。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.rag_service import get_rag_retriever, private_project_rag_enabled
from app.services.text_generation_service import generate_text, generation_enabled

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────


@dataclass
class RaptorLayerDoc:
    layer: str                # summary / scene_card / beat
    name: str                 # 文档命名
    text: str                 # 文档正文
    metadata: dict = field(default_factory=dict)
    rag_doc_id: str = ""      # Dify 返回


@dataclass
class RaptorIndexResult:
    summary_doc_id: str = ""
    scene_card_doc_ids: list[str] = field(default_factory=list)
    beat_doc_ids: list[str] = field(default_factory=list)
    docs: list[RaptorLayerDoc] = field(default_factory=list)
    rag_enabled: bool = False
    error: str = ""

    def as_step_version_payload(self) -> dict:
        """写入 step_versions.rag_doc_ids 字段"""
        return {
            "summary": self.summary_doc_id,
            "scene_cards": self.scene_card_doc_ids,
            "beats": self.beat_doc_ids,
        }


# ─────────────────────────────────────────────────────────
# 摘要生成（使用现有 LLM）
# ─────────────────────────────────────────────────────────


_SUMMARY_SYSTEM = "你是短剧编剧助手，擅长用最简短的语言提炼剧情。请严格按要求输出，不要加任何额外说明。"


def _gen_episode_summary(script_text: str, episode: int) -> str:
    """生成本集梗概（≤200字）"""
    if not generation_enabled():
        return ""
    prompt = (
        f"为下面第 {episode} 集短剧剧本生成 200 字以内梗概，"
        f"必须包含：核心冲突、出场主要角色、本集关键转折点。"
        f"直接输出梗概正文，不要加'梗概：'前缀。\n\n剧本：\n{script_text}"
    )
    try:
        return (generate_text(_SUMMARY_SYSTEM, prompt, temperature=0.5, max_tokens=400) or "").strip()
    except Exception as exc:
        logger.warning("episode summary failed: %s", exc)
        return ""


def _gen_scene_card(scene_text: str, episode: int, scene_id: str) -> str:
    """生成单场景卡（≤120字）"""
    if not generation_enabled():
        return scene_text[:200]
    prompt = (
        f"为下面短剧第 {episode} 集场景 {scene_id} 生成场景卡，"
        f"格式（每项一行，超过 120 字截断）：\n"
        f"地点：...\n时间：...\n出场角色：...\n核心动作：...\n转折点：...\n情绪基调：...\n\n"
        f"场景内容：\n{scene_text}"
    )
    try:
        return (generate_text(_SUMMARY_SYSTEM, prompt, temperature=0.4, max_tokens=300) or "").strip()
    except Exception as exc:
        logger.warning("scene card failed: %s", exc)
        return scene_text[:200]


# ─────────────────────────────────────────────────────────
# 切场 / 切 beat（轻量，纯规则）
# ─────────────────────────────────────────────────────────


_SCENE_HEADER_PAT = re.compile(r"^\s*(\d+)\s*[-_\.]\s*(\d+)\s+", re.MULTILINE)


def _split_scenes(script_text: str) -> list[tuple[str, str]]:
    """按 "1-1 日 外 地点" 这种场景头切分。

    返回 [(scene_id, scene_body), ...]。如果识别不到场景头，整段当成一个 scene。
    """
    matches = list(_SCENE_HEADER_PAT.finditer(script_text))
    if not matches:
        return [("scene_001", script_text.strip())]

    scenes: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(script_text)
        scene_id = f"scene_{m.group(1).zfill(2)}_{m.group(2).zfill(2)}"
        body = script_text[start:end].strip()
        if body:
            scenes.append((scene_id, body))
    return scenes


def _extract_character_ids(text: str, name_to_id: dict[str, str]) -> list[str]:
    """从文本中找出涉及的角色 id（基于角色名字典）"""
    if not name_to_id:
        return []
    found = set()
    for name, cid in name_to_id.items():
        if name and name in text:
            found.add(cid)
    return sorted(found)


def _split_beats(scene_body: str, max_per_scene: int = 4) -> list[str]:
    """场景内按"动作行（△开头）+ 对白簇"粗切 beat。"""
    lines = [ln.strip() for ln in scene_body.split("\n") if ln.strip()]
    if not lines:
        return []
    beats: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        cur.append(ln)
        # 简单启发：每 ~6 行或遇到下一个 △ 动作行时切一个 beat
        if ln.startswith("△") and len(cur) >= 4:
            beats.append(cur)
            cur = []
        elif len(cur) >= 8:
            beats.append(cur)
            cur = []
    if cur:
        beats.append(cur)
    # 限制 per-scene beat 数
    if len(beats) > max_per_scene:
        # 合并尾部
        merged_tail = sum(beats[max_per_scene - 1:], [])
        beats = beats[:max_per_scene - 1] + [merged_tail]
    return ["\n".join(b) for b in beats]


# ─────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────


async def index_episode(
    *,
    project_id: str,
    episode: int,
    script_text: str,
    character_name_to_id: dict[str, str] | None = None,
    dataset_name: str | None = None,
) -> RaptorIndexResult:
    """对一集已确认剧本生成三层文档；外部 RAG 写入需显式开启。

    dataset_name 缺省为 f"project_{project_id}"。
    """
    rag = get_rag_retriever()
    allow_private_rag = private_project_rag_enabled()
    result = RaptorIndexResult(rag_enabled=rag.enabled and allow_private_rag)

    if not (script_text or "").strip():
        result.error = "empty_script"
        return result

    name_to_id = character_name_to_id or {}
    dataset = dataset_name or f"project_{project_id}"

    # 1) 顶层：本集梗概
    summary = _gen_episode_summary(script_text, episode)
    summary_doc = RaptorLayerDoc(
        layer="summary",
        name=f"ep{episode:02d}_summary",
        text=summary or script_text[:400],
        metadata={
            "episode": episode,
            "layer": "summary",
            "character_ids": _extract_character_ids(script_text, name_to_id),
        },
    )
    result.docs.append(summary_doc)

    # 2) 中层：场景卡
    scenes = _split_scenes(script_text)
    for scene_id, scene_body in scenes:
        card = _gen_scene_card(scene_body, episode, scene_id)
        result.docs.append(RaptorLayerDoc(
            layer="scene_card",
            name=f"ep{episode:02d}_{scene_id}_card",
            text=card,
            metadata={
                "episode": episode,
                "layer": "scene_card",
                "scene_id": scene_id,
                "character_ids": _extract_character_ids(scene_body, name_to_id),
            },
        ))

        # 3) 叶层：beats（不再调 LLM，纯规则切，原文片段）
        beats = _split_beats(scene_body)
        for i, beat_text in enumerate(beats):
            result.docs.append(RaptorLayerDoc(
                layer="beat",
                name=f"ep{episode:02d}_{scene_id}_beat{i+1:02d}",
                text=beat_text,
                metadata={
                    "episode": episode,
                    "layer": "beat",
                    "scene_id": scene_id,
                    "beat_index": i,
                    "character_ids": _extract_character_ids(beat_text, name_to_id),
                },
            ))

    # 4) 写入 Dify（默认关闭；任一失败不阻断）
    if rag.enabled and allow_private_rag:
        for doc in result.docs:
            doc_text_with_meta = (
                f"[metadata]\n{json.dumps(doc.metadata, ensure_ascii=False)}\n[/metadata]\n\n{doc.text}"
            )
            ret = await rag.create_text_document(
                dataset=dataset,
                name=doc.name,
                text=doc_text_with_meta,
            )
            if ret.get("ok"):
                # Dify 返回结构形如 {"document": {"id": "..."}}
                d = (ret.get("data") or {}).get("document") or {}
                doc.rag_doc_id = d.get("id") or ""

        result.summary_doc_id = next(
            (d.rag_doc_id for d in result.docs if d.layer == "summary"), ""
        )
        result.scene_card_doc_ids = [d.rag_doc_id for d in result.docs if d.layer == "scene_card" and d.rag_doc_id]
        result.beat_doc_ids = [d.rag_doc_id for d in result.docs if d.layer == "beat" and d.rag_doc_id]
    elif rag.enabled and not allow_private_rag:
        result.error = "private_project_rag_disabled"

    return result


async def retrieve_cross_episode_context(
    *,
    project_id: str,
    current_episode: int,
    query: str,
    top_k: int = 4,
    layer_filter: str = "scene_card",
) -> str:
    """检索前序集的相关上下文（用于分镜生成时增强）

    layer_filter: summary / scene_card / beat
    返回拼好的文本，供 prompt 注入；失败返回空字符串。
    """
    if not private_project_rag_enabled():
        return ""
    rag = get_rag_retriever()
    if not rag.enabled or not (query or "").strip():
        return ""

    # Dify 检索 API 不直接支持 metadata 过滤；这里用 query 注入约束词
    enriched_query = f"[layer:{layer_filter}] [before_episode:{current_episode}] {query}"
    try:
        text = await rag.retrieve_as_text(
            dataset=f"project_{project_id}",
            query=enriched_query,
            top_k=top_k,
            header=f"【前序集{layer_filter}检索结果】",
        )
        return text or ""
    except Exception as exc:
        logger.warning("cross-episode retrieve failed: %s", exc)
        return ""
