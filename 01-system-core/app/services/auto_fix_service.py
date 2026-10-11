"""
AUTO-FIX 自动修复服务 — OpenSpace 启发
核心功能：失败模式识别 + 自动修复 + 成功模式提取
"""
import uuid
import json
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.auto_fix import (
    FailurePattern, FixStrategy, AutoFixRecord,
    SuccessPattern, SegmentMetrics
)
from app.models.episode_segment import EpisodeSegment


@dataclass
class FixResult:
    """修复结果"""
    success: bool
    fixed_content: Optional[str]
    pattern_code: str
    strategy_code: str
    iterations: int
    final_score: float
    message: str


def _segment_content(segment: EpisodeSegment) -> str:
    """Return the current segment text across old/new model field names."""
    return str(
        getattr(segment, "generated_content", None)
        or getattr(segment, "content", None)
        or ""
    )


# ============================================
# 内置失败模式定义
# ============================================

BUILTIN_FAILURE_PATTERNS = [
    {
        "code": "WORD_COUNT_INSUFFICIENT",
        "name": "字数不足",
        "description": "实际字数低于目标字数的80%",
        "detection_logic": {
            "type": "word_count_ratio",
            "threshold": 0.8
        },
        "fix_strategy": "EXPAND_CONTENT",
        "priority": 9,
    },
    {
        "code": "MISSING_CONFLICT",
        "name": "缺少冲突",
        "description": "段落内容未检测到冲突元素",
        "detection_logic": {
            "type": "keyword_absence",
            "keywords": ["冲突", "矛盾", "对抗", "对立", "争执", "争吵", "斗", "争", "不", "拒绝", "反对"]
        },
        "fix_strategy": "ADD_CONFLICT_POINT",
        "priority": 8,
    },
    {
        "code": "PACING_TOO_SLOW",
        "name": "节奏拖沓",
        "description": "平均句长过长，节奏缓慢",
        "detection_logic": {
            "type": "avg_sentence_length",
            "threshold": 40
        },
        "fix_strategy": "TIGHTEN_PACING",
        "priority": 7,
    },
    {
        "code": "HOOK_TOO_WEAK",
        "name": "钩子无力",
        "description": "钩子段缺乏悬念或吸引力",
        "detection_logic": {
            "type": "segment_specific",
            "segment_type": "hook",
            "check": "no_question_or_exclamation"
        },
        "fix_strategy": "STRENGTHEN_HOOK",
        "priority": 10,
    },
    {
        "code": "EXPLOSION_INSUFFICIENT",
        "name": "爆发不足",
        "description": "爆发段情绪张力不够",
        "detection_logic": {
            "type": "segment_specific",
            "segment_type": "explosion",
            "check": "emotion_words_count",
            "min_count": 3
        },
        "fix_strategy": "AMPLIFY_EMOTION",
        "priority": 8,
    },
    {
        "code": "RESOLUTION_UNCLEAR",
        "name": "收尾不清",
        "description": "收尾段没有明确的悬念或过渡",
        "detection_logic": {
            "type": "segment_specific",
            "segment_type": "resolution",
            "check": "ending_hook_absent"
        },
        "fix_strategy": "ADD_CLIFFHANGER",
        "priority": 7,
    },
]

BUILTIN_FIX_STRATEGIES = [
    {
        "code": "EXPAND_CONTENT",
        "name": "扩展内容",
        "description": "通过增加细节描述和人物反应来扩充字数",
        "param_template": {"expand_ratio": 1.3, "focus": "description"},
        "system_prompt": """你是一个剧本扩展专家。任务：在保持原有剧情和风格的前提下，增加内容字数。

扩展策略：
1. 增加环境描写（光线、声音、氛围）
2. 细化人物动作和表情
3. 添加内心独白或潜台词
4. 延长对话中的停顿和反应

注意事项：
- 不要改变原有剧情走向
- 保持人物性格一致
- 维持原有节奏感
- 每句对话后增加动作描写""",
        "user_prompt_template": """请扩展以下内容，从 {current_words} 字扩展到 {target_words} 字左右：

原文：
{content}

扩展要求：
1. 增加 {expand_ratio} 倍细节
2. 重点扩展：{focus}
3. 保持原有对话和剧情
4. 增加人物动作和表情描写"""
    },
    {
        "code": "ADD_CONFLICT_POINT",
        "name": "添加冲突点",
        "description": "在合适位置插入冲突元素",
        "param_template": {"conflict_type": "dialogue", "intensity": "medium"},
        "system_prompt": """你是一个冲突设计专家。任务：在现有内容中强化或添加冲突元素。

冲突类型选择：
1. 语言冲突：对话中的针锋相对
2. 动作冲突：肢体对抗或阻止行为
3. 心理冲突：内心挣扎或两难选择
4. 情境冲突：外部环境的阻碍

添加原则：
- 冲突要符合人物性格
- 冲突要有明确的目的性
- 冲突要推动剧情发展
- 冲突强度要适中""",
        "user_prompt_template": """请在以下内容中添加或强化冲突元素：

原文：
{content}

冲突要求：
1. 冲突类型：{conflict_type}
2. 冲突强度：{intensity}
3. 冲突要自然融入现有对话
4. 保持人物性格一致性"""
    },
    {
        "code": "TIGHTEN_PACING",
        "name": "收紧节奏",
        "description": "缩短句子长度，加快节奏",
        "param_template": {"target_avg_length": 20, "cut_fluff": True},
        "system_prompt": """你是一个节奏控制专家。任务：收紧节奏，让内容更紧凑有力。

收紧策略：
1. 长句拆短句（每句不超过25字）
2. 删除冗余修饰词
3. 对话直接切入主题
4. 增加动作描写替代叙述

原则：
- 保持信息完整
- 增强戏剧张力
- 每句都有推进作用""",
        "user_prompt_template": """请收紧以下内容的节奏：

原文：
{content}

收紧要求：
1. 目标平均句长：{target_avg_length}字
2. 删除冗余：{cut_fluff}
3. 保持核心剧情不变
4. 让对话更直接有力"""
    },
    {
        "code": "STRENGTHEN_HOOK",
        "name": "强化钩子",
        "description": "增强开头吸引力",
        "param_template": {"hook_type": "conflict", "mystery_level": "high"},
        "system_prompt": """你是一个开篇设计专家。任务：设计强有力的开场钩子。

钩子类型：
1. 冲突式：直接呈现矛盾对抗
2. 疑问式：抛出悬念问题
3. 场景式：营造强烈氛围
4. 颠覆式：打破常规预期

优秀钩子特征：
- 3秒内抓住注意力
- 引发好奇或情绪
- 暗示更大冲突
- 与后续剧情呼应""",
        "user_prompt_template": """请为以下内容重写开头，增强吸引力：

原文：
{content}

钩子要求：
1. 类型：{hook_type}
2. 悬念程度：{mystery_level}
3. 前3句必须有冲击力
4. 建立强烈的情绪张力"""
    },
    {
        "code": "AMPLIFY_EMOTION",
        "name": "放大情绪",
        "description": "增强情绪张力和爆发感",
        "param_template": {"emotion_type": "anger", "amplification": 1.5},
        "system_prompt": """你是一个情绪描写专家。任务：放大情绪张力，增强爆发感。

情绪放大技巧：
1. 身体反应描写（颤抖、心跳、呼吸）
2. 感官细节强化（声音、光线、气味）
3. 对话情绪化（短句、重复、停顿）
4. 内心独白外化

原则：
- 情绪要有层次递进
- 从压抑到爆发
- 通过动作展现情绪
- 避免直接说"他很生气"
""",
        "user_prompt_template": """请放大以下内容的情绪张力：

原文：
{content}

情绪要求：
1. 主要情绪：{emotion_type}
2. 放大倍数：{amplification}
3. 增加身体反应描写
4. 对话更有情绪冲击力"""
    },
    {
        "code": "ADD_CLIFFHANGER",
        "name": "添加尾钩",
        "description": "添加悬念结尾",
        "param_template": {"cliffhanger_type": "revelation", "hint_level": "subtle"},
        "system_prompt": """你是一个悬念设计专家。任务：设计强有力的结尾钩子。

尾钩类型：
1. 揭示型：揭露惊人真相
2. 威胁型：新危机出现
3. 选择型：两难抉择
4. 异变型：意外转折

设计原则：
- 留下强烈悬念
- 引发下一集期待
- 不解决核心冲突
- 暗示更大风暴""",
        "user_prompt_template": """请为以下内容添加强有力的结尾钩子：

原文：
{content}

尾钩要求：
1. 类型：{cliffhanger_type}
2. 提示程度：{hint_level}
3. 最后一句必须有悬念
4. 引发对下一集的期待"""
    },
]


class AutoFixService:
    """自动修复服务"""

    def __init__(self, db: Session):
        self.db = db
        self._ensure_builtin_patterns()

    def _ensure_builtin_patterns(self):
        """确保内置模式已加载"""
        # 加载失败模式
        for pattern_data in BUILTIN_FAILURE_PATTERNS:
            existing = self.db.query(FailurePattern).filter(
                FailurePattern.pattern_code == pattern_data["code"]
            ).first()
            if not existing:
                pattern = FailurePattern(
                    id=str(uuid.uuid4()),
                    pattern_code=pattern_data["code"],
                    pattern_name=pattern_data["name"],
                    description=pattern_data["description"],
                    detection_logic=json.dumps(pattern_data["detection_logic"]),
                    fix_strategy_code=pattern_data["fix_strategy"],
                    default_priority=pattern_data["priority"],
                )
                self.db.add(pattern)

        # 加载修复策略
        for strategy_data in BUILTIN_FIX_STRATEGIES:
            existing = self.db.query(FixStrategy).filter(
                FixStrategy.strategy_code == strategy_data["code"]
            ).first()
            if not existing:
                strategy = FixStrategy(
                    id=str(uuid.uuid4()),
                    strategy_code=strategy_data["code"],
                    strategy_name=strategy_data["name"],
                    description=strategy_data["description"],
                    param_template=strategy_data["param_template"],
                    system_prompt=strategy_data["system_prompt"],
                    user_prompt_template=strategy_data["user_prompt_template"],
                )
                self.db.add(strategy)

        self.db.commit()

    # ============================================
    # 失败模式检测
    # ============================================

    def detect_failure_patterns(
        self,
        segment: EpisodeSegment,
        validation_result: Dict[str, Any]
    ) -> List[Dict]:
        """检测内容中的失败模式"""
        detected = []
        content = _segment_content(segment)

        # 从数据库获取所有活跃模式
        patterns = self.db.query(FailurePattern).filter(
            FailurePattern.is_active == 1
        ).all()

        for pattern in patterns:
            logic = json.loads(pattern.detection_logic or "{}")
            if self._check_pattern(content, segment, logic, validation_result):
                detected.append({
                    "pattern": pattern,
                    "priority": pattern.default_priority,
                })

        # 按优先级排序
        detected.sort(key=lambda x: x["priority"], reverse=True)
        return detected

    def _check_pattern(
        self,
        content: str,
        segment: EpisodeSegment,
        logic: Dict,
        validation_result: Dict
    ) -> bool:
        """检查单个模式"""
        logic_type = logic.get("type")

        if logic_type == "word_count_ratio":
            target = segment.target_word_count or 300
            actual = segment.actual_word_count or 0
            threshold = logic.get("threshold", 0.8)
            return actual < target * threshold

        elif logic_type == "keyword_absence":
            keywords = logic.get("keywords", [])
            return not any(kw in content for kw in keywords)

        elif logic_type == "avg_sentence_length":
            threshold = logic.get("threshold", 40)
            avg = self._calc_avg_sentence_length(content)
            return avg > threshold

        elif logic_type == "segment_specific":
            if segment.segment_type != logic.get("segment_type"):
                return False
            check_type = logic.get("check")

            if check_type == "no_question_or_exclamation":
                # 钩子段没有问号或感叹号
                return "?" not in content and "？" not in content and "!" not in content and "！" not in content

            elif check_type == "emotion_words_count":
                # 情绪词不足
                emotion_words = ["怒", "恨", "气", "哭", "泪", "激动", "颤抖", "疯狂"]
                count = sum(1 for w in emotion_words if w in content)
                return count < logic.get("min_count", 3)

            elif check_type == "ending_hook_absent":
                # 结尾缺少悬念词
                hook_markers = ["竟然", "居然", "没想到", "原来", "难道", "突然"]
                last_100 = content[-100:] if len(content) > 100 else content
                return not any(m in last_100 for m in hook_markers)

        return False

    def _calc_avg_sentence_length(self, content: str) -> float:
        """计算平均句长"""
        # 简单分句
        sentences = re.split(r'[。！？!?.]+', content)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return 0
        total = sum(len(s) for s in sentences)
        return total / len(sentences)

    # ============================================
    # 自动修复执行
    # ============================================

    def auto_fix(
        self,
        segment: EpisodeSegment,
        validation_result: Dict[str, Any],
        max_iterations: int = 3
    ) -> FixResult:
        """执行自动修复"""

        # 1. 检测失败模式
        detected_patterns = self.detect_failure_patterns(segment, validation_result)

        if not detected_patterns:
            return FixResult(
                success=True,
                fixed_content=_segment_content(segment),
                pattern_code="NONE",
                strategy_code="NONE",
                iterations=0,
                final_score=segment.validation_score or 0,
                message="未检测到失败模式"
            )

        # 2. 选择最高优先级的模式进行修复
        primary_pattern = detected_patterns[0]["pattern"]

        # 3. 获取对应的修复策略
        strategy = self.db.query(FixStrategy).filter(
            FixStrategy.strategy_code == primary_pattern.fix_strategy_code
        ).first()

        if not strategy:
            return FixResult(
                success=False,
                fixed_content=None,
                pattern_code=primary_pattern.pattern_code,
                strategy_code="NOT_FOUND",
                iterations=0,
                final_score=0,
                message=f"未找到修复策略: {primary_pattern.fix_strategy_code}"
            )

        # 4. 关闭同一段落的旧 pending，避免重复统计和永远挂起的记录
        for pending in self.db.query(AutoFixRecord).filter(
            AutoFixRecord.segment_id == segment.id,
            AutoFixRecord.status == "pending",
        ).all():
            pending.status = "aborted"
            pending.completed_at = datetime.now()

        fix_params = dict(strategy.param_template or {})
        fix_params["max_iterations"] = max_iterations

        # 5. 创建修复记录
        record = AutoFixRecord(
            id=str(uuid.uuid4()),
            segment_id=segment.id,
            pattern_id=primary_pattern.id,
            strategy_id=strategy.id,
            failure_type=primary_pattern.pattern_code,
            failure_detail=json.dumps(validation_result, ensure_ascii=False),
            before_content=_segment_content(segment),
            fix_params=fix_params,
            status="pending",
        )
        self.db.add(record)
        self.db.commit()

        # 6. 执行修复（这里返回提示词，实际调用需要上层服务）
        fix_prompt = self._build_fix_prompt(
            segment, strategy, fix_params
        )

        # 7. 更新统计
        primary_pattern.total_triggered += 1
        self.db.commit()

        return FixResult(
            success=True,  # 修复请求已创建
            fixed_content=None,  # 需要通过AI生成
            pattern_code=primary_pattern.pattern_code,
            strategy_code=strategy.strategy_code,
            iterations=0,  # 待执行后更新
            final_score=0,  # 待验证后更新
            message=fix_prompt  # 返回提示词给调用方
        )

    def _build_fix_prompt(
        self,
        segment: EpisodeSegment,
        strategy: FixStrategy,
        params: Dict
    ) -> str:
        """构建修复提示词"""
        template = strategy.user_prompt_template or ""

        # 填充变量
        context = {
            "content": _segment_content(segment),
            "current_words": segment.actual_word_count or 0,
            "target_words": segment.target_word_count or 300,
            "segment_type": segment.segment_type or "unknown",
            **params
        }

        try:
            return template.format(**context)
        except (KeyError, IndexError, ValueError):
            return template

    def record_fix_result(
        self,
        segment_id: str,
        fixed_content: str,
        final_score: float,
        iterations: int,
        success: bool
    ):
        """记录修复结果"""
        record = self.db.query(AutoFixRecord).filter(
            AutoFixRecord.segment_id == segment_id,
            AutoFixRecord.status == "pending"
        ).order_by(AutoFixRecord.created_at.desc()).first()

        if record:
            record.after_content = fixed_content
            record.final_score = final_score
            record.iterations = iterations
            record.status = "success" if success else "failed"
            record.completed_at = datetime.now()

            # 更新策略统计
            strategy = self.db.query(FixStrategy).get(record.strategy_id)
            if strategy:
                strategy.total_applied += 1
                if success:
                    strategy.total_success += 1
                strategy.success_rate = strategy.total_success / strategy.total_applied

            # 更新模式统计
            pattern = self.db.query(FailurePattern).get(record.pattern_id)
            if pattern and success:
                pattern.total_fixed += 1
                pattern.success_rate = pattern.total_fixed / pattern.total_triggered

            self.db.commit()

    # ============================================
    # 性能指标与模式提取
    # ============================================

    def update_segment_metrics(self, segment_id: str, generation_time: float = 0):
        """更新段落性能指标"""
        metrics = self.db.query(SegmentMetrics).filter(
            SegmentMetrics.segment_id == segment_id
        ).first()

        if not metrics:
            metrics = SegmentMetrics(
                id=str(uuid.uuid4()),
                segment_id=segment_id,
            )
            self.db.add(metrics)

        # 更新指标
        metrics.total_generations += 1
        if generation_time > 0:
            if metrics.avg_generation_time == 0:
                metrics.avg_generation_time = generation_time
            else:
                metrics.avg_generation_time = (
                    metrics.avg_generation_time * (metrics.total_generations - 1) + generation_time
                ) / metrics.total_generations

        metrics.last_generation_at = datetime.now()
        if not metrics.first_generation_at:
            metrics.first_generation_at = datetime.now()

        self.db.commit()

    def extract_success_pattern(self, segment: EpisodeSegment) -> Optional[str]:
        """从高质量段落提取成功模式"""
        if (segment.validation_score or 0) < 0.85:
            return None

        # 分析内容特征
        content = _segment_content(segment)
        features = {
            "avg_sentence_length": self._calc_avg_sentence_length(content),
            "word_count": len(content),
            "segment_type": segment.segment_type,
        }

        # 检测开场类型
        if "?" in content[:50] or "？" in content[:50]:
            features["opening_type"] = "question"
        elif any(w in content[:50] for w in ["不", "拒绝", "反对", "冲突"]):
            features["opening_type"] = "conflict"
        else:
            features["opening_type"] = "scene"

        # 创建成功模式
        pattern = SuccessPattern(
            id=str(uuid.uuid4()),
            source_segment_id=segment.id,
            segment_type=segment.segment_type,
            pattern_features=features,
            key_elements=self._extract_key_elements(content),
            avg_score=segment.validation_score or 0,
        )
        self.db.add(pattern)
        self.db.commit()

        return pattern.id

    def _extract_key_elements(self, content: str) -> List[str]:
        """提取关键元素"""
        elements = []

        # 检测冲突
        if any(w in content for w in ["冲突", "矛盾", "对抗", "争吵"]):
            elements.append("conflict")

        # 检测悬念
        if any(w in content for w in ["竟然", "居然", "没想到", "难道"]):
            elements.append("suspense")

        # 检测情绪
        if any(w in content for w in ["怒", "恨", "泪", "颤抖"]):
            elements.append("emotion")

        # 检测对话
        if '"' in content or '"' in content:
            elements.append("dialogue")

        return elements

    def get_recommended_patterns(
        self,
        segment_type: str,
        project_type: str = "all",
        limit: int = 3
    ) -> List[Dict]:
        """获取推荐的成功模式"""
        patterns = self.db.query(SuccessPattern).filter(
            SuccessPattern.segment_type == segment_type,
        ).order_by(
            SuccessPattern.avg_score.desc()
        ).limit(limit).all()

        return [
            {
                "id": p.id,
                "features": p.pattern_features,
                "key_elements": p.key_elements,
                "score": p.avg_score,
                "usage_count": p.usage_count,
            }
            for p in patterns
        ]

    # ============================================
    # 数据驱动优化报告
    # ============================================

    def get_failure_analysis_report(self, project_id: Optional[str] = None) -> Dict:
        """获取失败分析报告"""
        patterns = self.db.query(FailurePattern).all()

        return {
            "failure_distribution": [
                {
                    "code": p.pattern_code,
                    "name": p.pattern_name,
                    "triggered": p.total_triggered,
                    "fixed": p.total_fixed,
                    "success_rate": round(p.success_rate * 100, 1) if p.total_triggered > 0 else 0,
                }
                for p in sorted(patterns, key=lambda x: x.total_triggered, reverse=True)
            ],
            "strategy_effectiveness": [
                {
                    "code": s.strategy_code,
                    "name": s.strategy_name,
                    "applied": s.total_applied,
                    "success": s.total_success,
                    "success_rate": round(s.success_rate * 100, 1) if s.total_applied > 0 else 0,
                    "avg_iterations": round(s.avg_iterations, 1),
                }
                for s in self.db.query(FixStrategy).all()
            ]
        }

    def get_segment_bottlenecks(self, limit: int = 5) -> List[Dict]:
        """识别性能瓶颈"""
        metrics = self.db.query(SegmentMetrics).order_by(
            SegmentMetrics.total_refactors.desc()
        ).limit(limit).all()

        return [
            {
                "segment_id": m.segment_id,
                "refactors": m.total_refactors,
                "avg_score": m.avg_validation_score,
                "pass_rate": m.pass_rate,
                "failure_dist": m.failure_distribution,
            }
            for m in metrics
        ]
