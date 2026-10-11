"""短剧规则与提示词模板加载（从 short_drama_writing.py 抽出）。

包含：
- prompts/ 目录定位
- 步骤模板 / Agent prompt / 规则文件加载
- 子赛道（subgenre） / 样本赛道（sample track）路由推断
- {{rules:xxx}} 占位替换

这些函数都是纯函数 + 文件读取，不涉及数据库。
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

SUBGENRE_TRACK_TO_RULE: dict[str, str] = {
    "subgenre_female_face_slap": "subgenre_female_face_slap",
    "subgenre_female_power_taming": "subgenre_female_power_taming",
    "subgenre_female_misrecognition": "subgenre_female_misrecognition",
    "subgenre_hybrid_realistic_family": "subgenre_hybrid_realistic_family",
    "female_subgenres": "female_subgenres",
    "male_subgenres": "male_subgenres",
    "hybrid_subgenres": "hybrid_subgenres",
}

SAMPLE_TRACK_TO_RULE: dict[str, str] = {
    "sample_track_a_high_pressure_female": "sample_track_a_high_pressure_female",
    "sample_track_b_power_taming": "sample_track_b_power_taming",
    "sample_track_c_misrecognition_secret": "sample_track_c_misrecognition_secret",
    "sample_track_d_realistic_family": "sample_track_d_realistic_family",
}

_ROUTING_TEXT_KEYS: tuple[str, ...] = (
    "project_type",
    "audience_axis",
    "genre_main",
    "genre_sub",
    "rule_profile",
    "brief",
    "concept",
    "scene_list",
    "beat_sheet",
    "material_borrow_focus",
    "issue_feedback_summary",
)

_SAMPLE_TRACK_INFERENCE_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "sample_track_d_realistic_family",
        ("回乡", "返乡", "乡土", "上坟", "送站", "送别", "罚单", "债务", "看病", "父亲", "母亲", "奶奶", "县医院", "空村"),
        "现实家庭/乡土样本赛道",
    ),
    (
        "sample_track_c_misrecognition_secret",
        ("替嫁", "错认", "误认", "错嫁", "婚房", "花轿", "盖头", "婚配", "身份错位", "认错"),
        "错认/秘密延迟样本赛道",
    ),
    (
        "sample_track_b_power_taming",
        ("督军", "少帅", "军阀", "家法", "军令", "规矩", "驯服", "压服", "危险关系"),
        "权力驯服样本赛道",
    ),
    (
        "sample_track_a_high_pressure_female",
        ("豪门", "打脸", "虐渣", "证据", "录音", "站队", "偏爱缺席", "公开羞辱", "背叛"),
        "高压女频打脸样本赛道",
    ),
)

_SUBGENRE_FEMALE_INFERENCE_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "subgenre_female_face_slap",
        ("豪门", "打脸", "虐渣", "订婚宴", "录音", "证据", "站队", "偏爱缺席"),
        "女频打脸子赛道",
    ),
    (
        "subgenre_female_power_taming",
        ("危险关系", "权力驯服", "督军", "少帅", "军阀", "家法", "规矩", "民国"),
        "女频权力驯服子赛道",
    ),
    (
        "subgenre_female_misrecognition",
        ("先婚后爱", "错认", "误认", "婚房", "花轿", "盖头", "婚配", "秘密延迟"),
        "女频错认子赛道",
    ),
)

_SUBGENRE_HYBRID_REALISTIC_TOKENS: tuple[str, ...] = (
    "现实情感",
    "乡土",
    "亲情",
    "代际",
    "回乡",
    "送站",
    "上坟",
    "看病",
    "债务",
    "罚单",
    "父亲",
    "母亲",
    "县医院",
)


@dataclass(frozen=True)
class RuleRoutingDecision:
    """规则路由的审计结果：保留旧规则名，同时解释来源和依据。"""

    rule_name: str
    source: str
    confidence: float
    reason: str = ""
    matched_tokens: tuple[str, ...] = ()
    requested: str = ""


def prompts_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "prompts"


def load_step_template(file_name: str) -> str:
    path = prompts_dir() / "steps" / file_name
    return path.read_text(encoding="utf-8")


def load_agent_prompt(file_name: str) -> str:
    path = prompts_dir() / "agents" / file_name
    content = path.read_text(encoding="utf-8")
    if content.startswith("---"):
        content = re.sub(r"^---\n.*?\n---\n", "", content, count=1, flags=re.DOTALL)
    return content.strip()


def try_load_rule(rule_name: str) -> str:
    """加载规则文件；文件缺失时返回占位注释而非抛出异常。"""
    path = prompts_dir() / "rules" / f"{rule_name}.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return f"<!-- rule:{rule_name} not found -->"


def _routing_text(variables: dict[str, str]) -> str:
    return " ".join(str(variables.get(key) or "").strip() for key in _ROUTING_TEXT_KEYS)


def _matched_tokens(text: str, tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(token for token in tokens if token and token in text)


def _confidence_for_hits(hits: tuple[str, ...], *, base: float = 0.72) -> float:
    if not hits:
        return 0.0
    return min(0.92, round(base + (len(hits) - 1) * 0.03, 2))


def _explicit_decision(raw: str, mapping: dict[str, str], *, label: str) -> RuleRoutingDecision | None:
    explicit = str(raw or "").strip()
    if not explicit:
        return None
    resolved = mapping.get(explicit, explicit if explicit in mapping.values() else "")
    if not resolved:
        return RuleRoutingDecision(
            rule_name="",
            source="explicit_invalid",
            confidence=0.0,
            reason=f"用户显式选择了未知{label}：{explicit}",
            requested=explicit,
        )
    return RuleRoutingDecision(
        rule_name=resolved,
        source="explicit",
        confidence=1.0,
        reason=f"用户显式选择{label}：{explicit}",
        matched_tokens=(explicit,),
        requested=explicit,
    )


def resolve_sample_track_rule_decision_from_variables(variables: dict[str, str]) -> RuleRoutingDecision:
    explicit = _explicit_decision(str(variables.get("sample_track") or ""), SAMPLE_TRACK_TO_RULE, label="样本赛道")
    if explicit is not None:
        return explicit

    text = _routing_text(variables)
    for rule_name, tokens, label in _SAMPLE_TRACK_INFERENCE_RULES:
        hits = _matched_tokens(text, tokens)
        if hits:
            return RuleRoutingDecision(
                rule_name=rule_name,
                source="inferred",
                confidence=_confidence_for_hits(hits),
                reason=f"根据项目字段命中{label}：{'、'.join(hits[:6])}",
                matched_tokens=hits,
            )

    return RuleRoutingDecision(
        rule_name="",
        source="none",
        confidence=0.0,
        reason="未命中任何样本赛道关键词，避免强行套用题材规则",
    )


def infer_sample_track_rule_name_from_variables(variables: dict[str, str]) -> str:
    decision = resolve_sample_track_rule_decision_from_variables({**variables, "sample_track": ""})
    return decision.rule_name


def resolve_sample_track_rule_name_from_variables(variables: dict[str, str]) -> str:
    return resolve_sample_track_rule_decision_from_variables(variables).rule_name


def resolve_subgenre_rule_decision_from_variables(variables: dict[str, str]) -> RuleRoutingDecision:
    explicit = _explicit_decision(str(variables.get("subgenre_track") or ""), SUBGENRE_TRACK_TO_RULE, label="子赛道")
    if explicit is not None:
        return explicit

    audience_axis = str(variables.get("audience_axis") or "").strip()
    text = _routing_text(variables)

    if "女频" in audience_axis:
        for rule_name, tokens, label in _SUBGENRE_FEMALE_INFERENCE_RULES:
            hits = _matched_tokens(text, tokens)
            if hits:
                return RuleRoutingDecision(
                    rule_name=rule_name,
                    source="inferred",
                    confidence=_confidence_for_hits(hits),
                    reason=f"根据女频项目字段命中{label}：{'、'.join(hits[:6])}",
                    matched_tokens=hits,
                )
        return RuleRoutingDecision(
            rule_name="female_subgenres",
            source="inferred",
            confidence=0.55,
            reason="用户/项目字段标明女频，但未命中更细子赛道，回退到女频通用规则",
            matched_tokens=("女频",),
        )

    if "男频" in audience_axis:
        return RuleRoutingDecision(
            rule_name="male_subgenres",
            source="inferred",
            confidence=0.55,
            reason="用户/项目字段标明男频，回退到男频通用规则",
            matched_tokens=("男频",),
        )

    realistic_hits = _matched_tokens(text, _SUBGENRE_HYBRID_REALISTIC_TOKENS)
    if realistic_hits:
        return RuleRoutingDecision(
            rule_name="subgenre_hybrid_realistic_family",
            source="inferred",
            confidence=_confidence_for_hits(realistic_hits),
            reason=f"根据项目字段命中现实家庭/亲情子赛道：{'、'.join(realistic_hits[:6])}",
            matched_tokens=realistic_hits,
        )

    if "混合" in audience_axis or audience_axis == "":
        hits = ("混合",) if "混合" in audience_axis else ()
        return RuleRoutingDecision(
            rule_name="hybrid_subgenres",
            source="inferred",
            confidence=0.5 if hits else 0.35,
            reason="未命中更细子赛道，回退到混合通用规则",
            matched_tokens=hits,
        )

    return RuleRoutingDecision(
        rule_name="",
        source="none",
        confidence=0.0,
        reason="未命中任何子赛道规则，避免强行套用题材规则",
    )


def infer_subgenre_rule_name_from_variables(variables: dict[str, str]) -> str:
    decision = resolve_subgenre_rule_decision_from_variables({**variables, "subgenre_track": ""})
    return decision.rule_name


def resolve_subgenre_rule_name_from_variables(variables: dict[str, str]) -> str:
    return resolve_subgenre_rule_decision_from_variables(variables).rule_name


def resolve_rules_injection(text: str, variables: dict[str, str]) -> str:
    """将 prompt 中的 {{rules:rule_name}} 替换为对应规则文件内容。

    audience_axis → audience_rules 特殊路由：
      - 含"男频" → male_core + male_style
      - 含"女频" → female_core + female_style
      - 其余    → hybrid_genre
    """
    audience_axis = variables.get("audience_axis", "")
    subgenre_rule = resolve_subgenre_rule_name_from_variables(variables)
    sample_track_rule = resolve_sample_track_rule_name_from_variables(variables)

    def _get_audience_rules() -> str:
        if "男频" in audience_axis:
            return try_load_rule("male_core") + "\n\n" + try_load_rule("male_style")
        elif "女频" in audience_axis:
            return try_load_rule("female_core") + "\n\n" + try_load_rule("female_style")
        else:
            return try_load_rule("hybrid_genre")

    def _replace(match: re.Match) -> str:
        rule_name = match.group(1)
        if rule_name == "audience_rules":
            return _get_audience_rules()
        if rule_name == "subgenre_rules":
            return try_load_rule(subgenre_rule) if subgenre_rule else ""
        if rule_name == "sample_track_rules":
            return try_load_rule(sample_track_rule) if sample_track_rule else ""
        return try_load_rule(rule_name)

    return re.sub(r"\{\{rules:(\w+)\}\}", _replace, text)
