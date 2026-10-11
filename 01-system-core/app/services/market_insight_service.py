"""
短剧市场验证与题材推荐服务
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

from app.config import config


STYLE_AXES = {"male", "female", "mixed"}

HOOK_KEYWORDS = {
    "爆": 6,
    "反转": 8,
    "秘密": 7,
    "复仇": 8,
    "离婚": 8,
    "重生": 8,
    "逆袭": 8,
    "豪门": 7,
    "身份": 7,
    "替身": 6,
    "婚礼": 6,
    "出轨": 7,
    "背叛": 7,
    "系统": 6,
    "禁忌": 6,
    "失踪": 7,
    "绑架": 8,
    "假死": 8,
    "真相": 6,
    "孩子": 6,
    "前夫": 7,
    "前妻": 7,
    "契约": 6,
    "救赎": 5,
    "家族": 4,
}

MALE_FIT_KEYWORDS = {
    "逆袭": 8,
    "系统": 8,
    "爽": 7,
    "复仇": 7,
    "战斗": 7,
    "权谋": 6,
    "都市": 4,
    "悬疑": 5,
    "修真": 7,
    "机甲": 7,
    "古武": 7,
    "打脸": 8,
    "商业": 6,
    "创业": 6,
    "职场": 5,
}

FEMALE_FIT_KEYWORDS = {
    "情感": 7,
    "婚姻": 8,
    "离婚": 8,
    "复婚": 6,
    "豪门": 7,
    "虐恋": 8,
    "甜宠": 6,
    "追妻": 8,
    "替身": 7,
    "暗恋": 6,
    "家庭": 6,
    "逆袭": 6,
    "契约": 6,
    "误会": 7,
    "救赎": 6,
    "反转": 5,
}

MIXED_FIT_KEYWORDS = {
    "悬疑": 7,
    "反转": 7,
    "爽": 6,
    "关系": 6,
    "家庭": 5,
    "秘密": 7,
    "权力": 5,
    "身份": 6,
    "代价": 5,
    "博弈": 6,
}

OVERUSED_WORDS = {
    "战神",
    "赘婿",
    "神医",
    "总裁",
    "豪门",
    "复仇",
    "重生",
    "逆袭",
    "替身",
}

MALE_TITLE_PATTERNS = [
    "{topic}之后，我才知道自己被人做局了",
    "{topic}那天，我把所有人都打懵了",
    "别碰{topic}，代价你扛不起",
    "{topic}一翻盘，全场都变了脸",
    "{topic}背后，藏着真正的局",
    "我在{topic}里，赢回了自己",
]

FEMALE_TITLE_PATTERNS = [
    "{topic}那晚，我终于看清了他",
    "{topic}之后，他再也回不来了",
    "别把{topic}当成玩笑",
    "{topic}撕开后，所有人都慌了",
    "我在{topic}里，失去了也拿回了",
    "{topic}这局，我不想再让了",
]

MIXED_TITLE_PATTERNS = [
    "{topic}之后，真相比想象更狠",
    "{topic}一翻开，所有关系都变了",
    "我在{topic}里，第一次不想退",
    "{topic}背后，藏着谁都不敢说的事",
    "{topic}那次反转，让所有人失算",
    "别急，{topic}的答案还没到",
]

MALE_CHARACTER_ARCHETYPES = [
    ("主角", "硬扛型主角", "先被压制再反扑", "擅长对局、决断、反击"),
    ("对立者", "强压型对手", "用规则和资源压人", "擅长卡局、设局、逼迫"),
    ("帮手", "破局型帮手", "在关键节点递刀", "擅长提供信息、证据、通道"),
    ("搅局者", "变数型角色", "让局势突然失控", "擅长制造误差、误判、反噬"),
]

FEMALE_CHARACTER_ARCHETYPES = [
    ("主角", "情感与选择型主角", "在关系中做出代价选择", "擅长试探、忍耐、反击"),
    ("对立者", "控制型对手", "用情感、身份或规则施压", "擅长操控、冷处理、压线"),
    ("帮手", "支持型角色", "在关键时刻给到支点", "擅长安抚、提醒、揭真相"),
    ("搅局者", "误会制造者", "把关系推向更危险的地方", "擅长错位信息、截断对话"),
]

MIXED_CHARACTER_ARCHETYPES = [
    ("主角", "目标驱动主角", "在利益与关系之间作选择", "擅长推进、拆局、止损"),
    ("对立者", "双面施压者", "一边给甜头一边设门槛", "擅长诱导、反制、翻供"),
    ("帮手", "关键证人/关键资源", "在关键时刻改变局势", "擅长补证、补刀、补真相"),
    ("搅局者", "不稳定变量", "让原本的计划失效", "擅长曝光、误导、反转"),
]

MALE_NAMES = ["林峥", "陆沉", "顾寒", "沈砚", "周野", "江屿"]
FEMALE_NAMES = ["苏晚", "沈知意", "林若", "顾念", "温言", "乔安"]
MIXED_NAMES = ["林峥", "苏晚", "顾寒", "沈知意", "陆沉", "温言"]


@dataclass
class NormalizedTrendItem:
    source: str
    title: str
    summary: str
    tags: list[str]
    heat: float
    audience_axis: str
    genre_hint: str
    style_hint: str
    raw: dict[str, Any]


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, tuple) or isinstance(value, set):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value).strip()]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _combine_text(item: dict[str, Any]) -> str:
    parts = [
        _clean_text(item.get("title")),
        _clean_text(item.get("summary")),
        _clean_text(item.get("genre_hint")),
        _clean_text(item.get("style_hint")),
        " ".join(_as_list(item.get("tags"))),
    ]
    return " ".join(part for part in parts if part)


def _guess_axis(text: str, explicit_axis: str | None = None) -> str:
    if explicit_axis in STYLE_AXES:
        return explicit_axis
    if any(keyword in text for keyword in FEMALE_FIT_KEYWORDS):
        return "female"
    if any(keyword in text for keyword in MALE_FIT_KEYWORDS):
        return "male"
    return "mixed"


def normalize_trend_item(raw: dict[str, Any], source: str | None = None) -> NormalizedTrendItem:
    data = raw or {}
    title = _clean_text(
        data.get("topic")
        or data.get("title")
        or data.get("name")
        or data.get("keyword")
        or data.get("tag")
        or data.get("query")
    )
    summary = _clean_text(data.get("summary") or data.get("description") or data.get("content") or data.get("text"))
    tags = _as_list(data.get("tags") or data.get("keywords") or data.get("labels"))
    source_name = _clean_text(source or data.get("source") or data.get("platform") or data.get("channel") or "external")
    heat = _safe_float(
        data.get("heat")
        or data.get("hot_score")
        or data.get("popularity")
        or data.get("score")
        or data.get("engagement")
        or data.get("trend_score")
        or 0,
        0.0,
    )
    audience_axis = _guess_axis(f"{title} {summary} {' '.join(tags)}", _clean_text(data.get("audience_axis") or data.get("audience")))
    genre_hint = _clean_text(data.get("genre_hint") or data.get("genre") or data.get("category") or "")
    style_hint = _clean_text(data.get("style_hint") or data.get("style") or "")
    return NormalizedTrendItem(
        source=source_name,
        title=title,
        summary=summary,
        tags=tags,
        heat=heat,
        audience_axis=audience_axis,
        genre_hint=genre_hint,
        style_hint=style_hint,
        raw=data,
    )


def _extract_payload_items(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "data", "results", "list", "topics"):
            if isinstance(payload.get(key), list):
                return [item for item in payload[key] if isinstance(item, dict)]
        return [payload]
    return []


def fetch_trends_from_urls(urls: Iterable[str]) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    if not urls:
        return items, errors

    from app.services.text_generation_service import get_ssl_verify
    timeout = httpx.Timeout(12.0)
    with httpx.Client(timeout=timeout, verify=get_ssl_verify()) as client:
        for url in urls:
            if not url:
                continue
            try:
                response = client.get(url)
                response.raise_for_status()
                payload = response.json()
                extracted = _extract_payload_items(payload)
                if extracted:
                    items.extend(extracted)
                else:
                    errors.append(f"{url}: 响应中未找到可解析的列表数据")
            except Exception as exc:
                errors.append(f"{url}: {exc}")
    return items, errors


def _keyword_score(text: str, keywords: dict[str, int]) -> int:
    total = 0
    for keyword, score in keywords.items():
        if keyword in text:
            total += score
    return total


def _novelty_score(text: str, tags: list[str], genre_hint: str, style_hint: str) -> int:
    base = 35
    combo_bonus = min(len(set(tags)), 5) * 6
    mixed_bonus = 10 if genre_hint and style_hint and genre_hint not in style_hint else 0
    overused_penalty = sum(6 for word in OVERUSED_WORDS if word in text)
    score = base + combo_bonus + mixed_bonus - overused_penalty
    return max(0, min(100, score))


def _style_score(text: str, axis: str) -> int:
    if axis == "male":
        return max(_keyword_score(text, MALE_FIT_KEYWORDS), 20)
    if axis == "female":
        return max(_keyword_score(text, FEMALE_FIT_KEYWORDS), 20)
    return max(_keyword_score(text, MIXED_FIT_KEYWORDS), 20)


def _fit_score(text: str, axis: str) -> int:
    base = _keyword_score(text, HOOK_KEYWORDS)
    if axis == "male":
        base += _keyword_score(text, MALE_FIT_KEYWORDS)
    elif axis == "female":
        base += _keyword_score(text, FEMALE_FIT_KEYWORDS)
    else:
        base += _keyword_score(text, MIXED_FIT_KEYWORDS)
    return max(0, min(100, base))


def score_trend_item(item: NormalizedTrendItem, weights: dict[str, float] | None = None, focus_axis: str | None = None) -> dict[str, Any]:
    weights = weights or {}
    focus_axis = focus_axis if focus_axis in STYLE_AXES else item.audience_axis
    text = _combine_text(item.__dict__)
    heat_score = max(0, min(100, int(item.heat)))
    novelty_score = _novelty_score(text, item.tags, item.genre_hint, item.style_hint)
    fit_score = _fit_score(text, focus_axis)
    style_score = _style_score(text, focus_axis)
    hook_score = max(0, min(100, _keyword_score(text, HOOK_KEYWORDS)))
    weight_heat = float(weights.get("heat", 0.3))
    weight_novelty = float(weights.get("novelty", 0.2))
    weight_fit = float(weights.get("fit", 0.3))
    weight_hook = float(weights.get("hook", 0.2))
    total = round(
        heat_score * weight_heat
        + novelty_score * weight_novelty
        + fit_score * weight_fit
        + hook_score * weight_hook
        + style_score * 0.1,
        2,
    )
    return {
        "source": item.source,
        "title": item.title,
        "summary": item.summary,
        "tags": item.tags,
        "heat": item.heat,
        "audience_axis": item.audience_axis,
        "genre_hint": item.genre_hint,
        "style_hint": item.style_hint,
        "scores": {
            "heat": heat_score,
            "novelty": novelty_score,
            "fit": fit_score,
            "style": style_score,
            "hook": hook_score,
            "total": total,
        },
        "raw": item.raw,
    }


def recommend_topics(
    items: Iterable[dict[str, Any]],
    source_urls: Iterable[str] | None = None,
    focus_axis: str | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    config_block = config.market_insights if hasattr(config, "market_insights") else {}
    weights = config_block.get("weights", {})
    default_top_k = _safe_int(config_block.get("top_k"), 8)
    requested_top_k = _safe_int(top_k, default_top_k)
    resolved_focus_axis = focus_axis if focus_axis in STYLE_AXES else config_block.get("default_style_axis", "mixed")

    source_items = list(items or [])
    fetched_items, fetch_errors = fetch_trends_from_urls(source_urls or config_block.get("source_urls", []))
    source_items.extend(fetched_items)

    normalized = [normalize_trend_item(raw) for raw in source_items if isinstance(raw, dict)]
    scored = [score_trend_item(item, weights=weights, focus_axis=resolved_focus_axis) for item in normalized]
    scored.sort(key=lambda row: row["scores"]["total"], reverse=True)

    return {
        "focus_axis": resolved_focus_axis,
        "top_k": requested_top_k,
        "source_count": len(source_items),
        "recommendations": scored[:requested_top_k],
        "fetch_errors": fetch_errors,
    }


def _select_name_pool(axis: str) -> list[str]:
    if axis == "male":
        return MALE_NAMES
    if axis == "female":
        return FEMALE_NAMES
    return MIXED_NAMES


def _pick_names(axis: str, count: int = 4) -> list[str]:
    pool = _select_name_pool(axis)
    if count <= len(pool):
        return pool[:count]
    return [pool[index % len(pool)] for index in range(count)]


def _topic_core(topic: str, summary: str, genre_hint: str, style_axis: str) -> str:
    pieces = [topic, summary, genre_hint]
    text = " ".join(piece for piece in pieces if piece)
    if style_axis == "male":
        return text or topic
    if style_axis == "female":
        return text or topic
    return text or topic


def _build_title_candidates(topic: str, style_axis: str) -> list[str]:
    patterns = MALE_TITLE_PATTERNS if style_axis == "male" else FEMALE_TITLE_PATTERNS if style_axis == "female" else MIXED_TITLE_PATTERNS
    return [pattern.format(topic=topic) for pattern in patterns]


def _build_outline(topic: str, summary: str, style_axis: str) -> str:
    if style_axis == "male":
        return "\n".join(
            [
                f"## 题材主轴：{topic}",
                f"## 核心设定：{summary or '先压局，再翻盘。'}",
                "## 大纲",
                "1. 开场直接给冲突或危机，主角被推到局里。",
                "2. 第一次反击失败，但拿到一条关键线索。",
                "3. 真正对立者出手，局势升级，代价出现。",
                "4. 主角反手掀桌，完成一轮反杀。",
                "5. 隐藏真相浮出，关系和利益同时撕裂。",
                "6. 集末留下更大钩子，下一集直接接爆点。",
            ]
        )
    if style_axis == "female":
        return "\n".join(
            [
                f"## 题材主轴：{topic}",
                f"## 核心设定：{summary or '关系拉扯先行，真相慢慢露。'}",
                "## 大纲",
                "1. 开场从关系异常入手，观众先知道谁在隐瞒。",
                "2. 试探与误会开始，角色之间的边界被碰到。",
                "3. 关键承诺出现，关系温度发生变化。",
                "4. 秘密被逼近，情感与现实冲突同时升级。",
                "5. 真相露头，人物必须在爱、信任、利益间做选择。",
                "6. 结尾留下关系代价或秘密悬念。",
            ]
        )
    return "\n".join(
        [
            f"## 题材主轴：{topic}",
            f"## 核心设定：{summary or '冲突与关系并行，快进快出。'}",
            "## 大纲",
            "1. 开场给出异常或结果，快速拉进戏。",
            "2. 人物进入对抗局，信息不对称开始放大。",
            "3. 反转出现，角色关系和目标同时变形。",
            "4. 再升级一次，把代价抬上来。",
            "5. 揭示一层关键真相，但不讲全。",
            "6. 结尾留钩子，下一集还有更狠的局。",
        ]
    )


def _build_synopsis(topic: str, summary: str, style_axis: str) -> str:
    base = summary or f"围绕{topic}展开的短剧故事。"
    if style_axis == "male":
        return f"{base} 故事从高压局和反击开始，主角一路破局、反杀、揭真相，最终把局面打回自己手里。"
    if style_axis == "female":
        return f"{base} 故事从关系变化切入，在试探、误会、拉扯与秘密暴露中推进，最终让情感与现实一起翻面。"
    return f"{base} 故事以快速冲突为起点，在对抗、反转与代价之间推进，最后把最强钩子留给下一集。"


def _build_characters(topic: str, style_axis: str) -> list[dict[str, Any]]:
    if style_axis == "male":
        names = _pick_names("male", 4)
        archetypes = MALE_CHARACTER_ARCHETYPES
    elif style_axis == "female":
        names = _pick_names("female", 4)
        archetypes = FEMALE_CHARACTER_ARCHETYPES
    else:
        names = _pick_names("mixed", 4)
        archetypes = MIXED_CHARACTER_ARCHETYPES

    roles = []
    for index, (role, label, objective, strength) in enumerate(archetypes):
        name = names[index]
        roles.append(
            {
                "name": name,
                "role": role,
                "label": label,
                "objective": f"围绕{topic}推进{objective}",
                "weakness": "被情绪、利益或真相卡住",
                "strength": strength,
                "dialogue_style": "短句、断句、带停顿" if style_axis != "male" else "短硬、反问、压迫感",
                "relationship": "与主角形成直接冲突或支点关系",
            }
        )
    return roles


def build_starter_pack(topic_data: dict[str, Any], style_axis: str | None = None) -> dict[str, Any]:
    axis = style_axis if style_axis in STYLE_AXES else _guess_axis(
        _combine_text(topic_data),
        _clean_text(topic_data.get("audience_axis") or topic_data.get("style_axis") or topic_data.get("axis")),
    )
    topic = _clean_text(topic_data.get("title") or topic_data.get("topic") or topic_data.get("name") or "推荐题材")
    summary = _clean_text(topic_data.get("summary") or topic_data.get("description") or "")
    genre_hint = _clean_text(topic_data.get("genre_hint") or topic_data.get("genre") or topic_data.get("category") or "")
    hot_score = _safe_float(topic_data.get("heat") or topic_data.get("hot_score") or 0)
    titles = _build_title_candidates(topic, axis)
    outline = _build_outline(topic, summary, axis)
    synopsis = _build_synopsis(topic, summary, axis)
    characters = _build_characters(topic, axis)

    return {
        "topic": topic,
        "style_axis": axis,
        "genre_hint": genre_hint,
        "heat": hot_score,
        "title_candidates": titles,
        "outline": outline,
        "synopsis": synopsis,
        "character_library": characters,
        "prompt_brief": {
            "topic": topic,
            "style_axis": axis,
            "summary": summary,
            "genre_hint": genre_hint,
            "titles": titles[:3],
            "characters": [role["name"] for role in characters],
        },
    }
