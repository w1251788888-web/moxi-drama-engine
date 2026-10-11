"""
Token优化服务 - 带质量保障的提示词优化

核心设计原则：
1. 绝不牺牲质量换取token节省
2. 确保核心规则100%完整保留
3. 素材注入只能是"锦上添花"，不能"喧宾夺主"
4. 全流程可监控、可回滚
"""
import uuid
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.project_learning import PromptOptimizationCache, ProjectMaterial
from app.models.rule import Rule


@dataclass
class OptimizationResult:
    """优化结果"""
    optimized_prompt: str
    original_length: int
    optimized_length: int
    token_reduction: float
    materials_injected: List[str]
    quality_score: float  # 优化质量评分
    risk_flags: List[str]  # 风险提示
    cache_hit: bool
    safe_to_use: bool  # 是否安全可用


class TokenOptimizationService:
    """带质量保障的Token优化服务"""

    # 质量阈值配置
    QUALITY_THRESHOLDS = {
        "min_original_ratio": 0.7,  # 原始内容保留比例不低于70%
        "max_injection_ratio": 0.3,  # 注入内容不超过30%
        "max_total_length": 8000,   # 提示词总长度上限（字符）
        "min_rule_keywords": 5,     # 必须保留的规则关键词数
    }

    # 规则关键词（用于验证规则完整性）
    RULE_KEYWORDS = [
        "钩子", "冲突", "情绪", "节奏", "对话",
        "人物", "场景", "字数", "格式", "结构",
        "男频", "女频", "爽点", "代入感"
    ]

    def __init__(self, db: Session):
        self.db = db

    def optimize_with_guardrails(
        self,
        project_id: str,
        original_prompt: str,
        context: Dict[str, Any],
        force_optimize: bool = False
    ) -> OptimizationResult:
        """
        带护栏的提示词优化

        Args:
            project_id: 项目ID
            original_prompt: 原始提示词（必须包含完整规则）
            context: 上下文信息
            force_optimize: 是否强制优化（忽略部分风险）

        Returns:
            OptimizationResult: 包含质量评估的优化结果
        """

        # 1. 分析原始提示词质量
        original_analysis = self._analyze_prompt(original_prompt)

        # 2. 检查原始提示词是否适合优化
        if not original_analysis["is_valid"]:
            return OptimizationResult(
                optimized_prompt=original_prompt,
                original_length=len(original_prompt),
                optimized_length=len(original_prompt),
                token_reduction=0.0,
                materials_injected=[],
                quality_score=0.0,
                risk_flags=[f"原始提示词无效: {original_analysis['error']}"],
                cache_hit=False,
                safe_to_use=False
            )

        # 3. 提取核心规则部分（必须完整保留）
        core_rules = self._extract_core_rules(original_prompt)

        # 4. 尝试获取素材
        materials = self._get_materials_safe(
            project_id=project_id,
            segment_type=context.get("segment_type"),
            min_quality=0.75,  # 只使用高质量素材
            limit=2
        )

        # 5. 构建优化提示词
        if not materials:
            # 无素材，返回原始提示词
            return OptimizationResult(
                optimized_prompt=original_prompt,
                original_length=len(original_prompt),
                optimized_length=len(original_prompt),
                token_reduction=0.0,
                materials_injected=[],
                quality_score=1.0,
                risk_flags=["无可用素材，使用原始提示词"],
                cache_hit=False,
                safe_to_use=True
            )

        # 6. 构建优化版本
        optimized = self._build_optimized_prompt_safe(
            original_prompt=original_prompt,
            core_rules=core_rules,
            materials=materials,
            context=context
        )

        # 7. 质量验证
        quality_check = self._validate_quality(
            original=original_prompt,
            optimized=optimized,
            core_rules=core_rules
        )

        # 8. 决策：是否使用优化版本
        safe_to_use = quality_check["passed"] or force_optimize

        # 9. 计算token节省
        token_reduction = self._calculate_token_reduction(
            original_prompt, optimized if safe_to_use else original_prompt
        )

        return OptimizationResult(
            optimized_prompt=optimized if safe_to_use else original_prompt,
            original_length=len(original_prompt),
            optimized_length=len(optimized),
            token_reduction=token_reduction,
            materials_injected=[m.id for m in materials],
            quality_score=quality_check["score"],
            risk_flags=quality_check["risks"],
            cache_hit=False,
            safe_to_use=safe_to_use
        )

    def _analyze_prompt(self, prompt: str) -> Dict:
        """分析提示词质量"""
        result = {"is_valid": True, "error": None}

        # 检查长度
        if len(prompt) < 100:
            result["is_valid"] = False
            result["error"] = "提示词过短，可能缺少规则"
            return result

        if len(prompt) > 10000:
            result["is_valid"] = False
            result["error"] = "提示词过长，可能包含冗余内容"
            return result

        # 检查关键结构
        if "输出格式" not in prompt and "格式" not in prompt:
            result["warning"] = "提示词可能缺少输出格式要求"

        return result

    def _extract_core_rules(self, prompt: str) -> Dict[str, str]:
        """
        提取核心规则部分（绝对不能丢失）

        识别提示词结构：
        1. 角色设定（你是...）
        2. 任务描述（请...）
        3. 规则要求（必须/不要...）
        4. 输出格式（输出格式/格式要求...）
        """
        core = {
            "role_section": "",
            "task_section": "",
            "rules_section": "",
            "format_section": "",
            "keywords_present": []
        }

        lines = prompt.split('\n')
        current_section = "header"

        for line in lines:
            line_stripped = line.strip()

            # 识别角色设定
            if any(kw in line_stripped for kw in ["你是", "你是一位", "作为", "角色"]):
                current_section = "role"
                core["role_section"] += line + "\n"
                continue

            # 识别规则部分（必须、不要、注意）
            if any(kw in line_stripped for kw in ["必须", "不要", "禁止", "注意", "规则", "要求"]):
                current_section = "rules"
                core["rules_section"] += line + "\n"
                continue

            # 识别输出格式
            if any(kw in line_stripped for kw in ["输出格式", "格式要求", "返回格式", "输出要求"]):
                current_section = "format"
                core["format_section"] += line + "\n"
                continue

            # 继续当前section
            if current_section == "role":
                core["role_section"] += line + "\n"
            elif current_section == "rules":
                core["rules_section"] += line + "\n"
            elif current_section == "format":
                core["format_section"] += line + "\n"

        # 检查关键词完整性
        core["keywords_present"] = [kw for kw in self.RULE_KEYWORDS if kw in prompt]

        return core

    def _get_materials_safe(
        self,
        project_id: str,
        segment_type: Optional[str],
        min_quality: float = 0.75,
        limit: int = 2
    ) -> List[ProjectMaterial]:
        """安全地获取素材"""

        query = self.db.query(ProjectMaterial).filter(
            ProjectMaterial.project_id == project_id,
            ProjectMaterial.status == 'approved',
            ProjectMaterial.quality_score >= min_quality
        )

        if segment_type:
            query = query.filter(
                ProjectMaterial.material_type.like(f'%{segment_type}%')
            )

        materials = query.order_by(
            ProjectMaterial.quality_score.desc(),
            ProjectMaterial.usage_count.desc()
        ).limit(limit).all()

        return materials

    def _build_optimized_prompt_safe(
        self,
        original_prompt: str,
        core_rules: Dict[str, str],
        materials: List[ProjectMaterial],
        context: Dict[str, Any]
    ) -> str:
        """安全地构建优化提示词"""

        segment_type = context.get("segment_type", "segment")

        # 构建素材参考部分
        examples = []
        for i, m in enumerate(materials, 1):
            if m.content:
                # 只取前300字作为示例，避免过长
                content_preview = m.content[:300] + "..." if len(m.content) > 300 else m.content
                examples.append(f"示例{i}（质量分{int(m.quality_score*100)}%）：\n{content_preview}")

        material_section = "\n\n".join([
            "---",
            "【成功案例参考（仅供参考，请保持创作独立性）】",
            "",
            "\n\n".join(examples),
            "",
            f"注意：以上案例展示的是该类型段落的成功风格，"
            f"请在遵循核心规则的前提下，保持你的创作特色。",
            "---"
        ])

        # 构建优化后的提示词
        # 结构：角色设定 + 任务描述 + 核心规则 + 素材参考 + 输出格式
        sections = []

        if core_rules["role_section"]:
            sections.append(core_rules["role_section"].strip())

        # 任务描述（从原始提示词中提取）
        task_desc = self._extract_task_description(original_prompt)
        if task_desc:
            sections.append(task_desc)

        # 核心规则（最重要，必须完整保留）
        if core_rules["rules_section"]:
            sections.append("【核心规则（必须严格遵守）】\n" + core_rules["rules_section"].strip())

        # 素材参考（放在规则之后，避免喧宾夺主）
        sections.append(material_section)

        # 输出格式（必须保留）
        if core_rules["format_section"]:
            sections.append("【输出格式】\n" + core_rules["format_section"].strip())

        return "\n\n".join(sections)

    def _extract_task_description(self, prompt: str) -> str:
        """提取任务描述部分"""
        lines = prompt.split('\n')
        task_lines = []

        for line in lines:
            if any(kw in line for kw in ["请", "需要", "要求你", "任务"]):
                task_lines.append(line)

        return '\n'.join(task_lines) if task_lines else ""

    def _validate_quality(
        self,
        original: str,
        optimized: str,
        core_rules: Dict[str, str]
    ) -> Dict[str, Any]:
        """验证优化质量"""

        risks = []
        score = 1.0

        # 检查1: 核心规则保留率
        core_rule_text = core_rules["rules_section"]
        if core_rule_text:
            core_lines = [l.strip() for l in core_rule_text.split('\n') if l.strip()]
            preserved_lines = sum(1 for line in core_lines if line in optimized)
            preservation_rate = preserved_lines / len(core_lines) if core_lines else 1.0

            if preservation_rate < 0.95:  # 要求95%以上规则被保留
                risks.append(f"核心规则保留率仅{preservation_rate*100:.0f}%，可能丢失重要规则")
                score -= 0.3

        # 检查2: 输出格式完整性
        if core_rules["format_section"] and core_rules["format_section"] not in optimized:
            risks.append("输出格式部分丢失")
            score -= 0.4

        # 检查3: 关键词完整性
        missing_keywords = [
            kw for kw in core_rules["keywords_present"]
            if kw not in optimized
        ]
        if len(missing_keywords) > 2:
            risks.append(f"丢失关键词: {', '.join(missing_keywords[:3])}")
            score -= 0.2

        # 检查4: 总长度控制
        if len(optimized) > self.QUALITY_THRESHOLDS["max_total_length"]:
            risks.append(f"优化后提示词过长({len(optimized)}字符)，可能超出模型上下文限制")
            score -= 0.1

        # 检查5: 素材注入比例
        original_lines = len(original.split('\n'))
        optimized_lines = len(optimized.split('\n'))
        if optimized_lines > original_lines * 1.5:
            risks.append("素材注入过多，可能稀释核心规则")
            score -= 0.15

        return {
            "passed": len(risks) == 0 and score >= 0.8,
            "score": max(score, 0.0),
            "risks": risks,
            "details": {
                "preservation_rate": preservation_rate if core_rule_text else 1.0,
                "original_length": len(original),
                "optimized_length": len(optimized),
                "length_change": f"{((len(optimized) - len(original)) / len(original) * 100):+.0f}%"
            }
        }

    def _calculate_token_reduction(
        self,
        original: str,
        optimized: str
    ) -> float:
        """计算token节省比例（估算）"""
        # 简单估算：每4个字符约1个token
        original_tokens = len(original) / 4
        optimized_tokens = len(optimized) / 4

        if original_tokens <= 0:
            return 0.0

        reduction = (original_tokens - optimized_tokens) / original_tokens
        return max(reduction, 0.0)  # 不返回负值

    def get_cache_or_create(
        self,
        project_id: str,
        context: Dict[str, Any],
        original_prompt: str
    ) -> Tuple[str, bool]:
        """获取缓存或创建新缓存"""

        # 计算缓存键
        cache_key = self._compute_cache_key(project_id, context)

        # 查找缓存
        cached = self.db.query(PromptOptimizationCache).filter(
            PromptOptimizationCache.context_hash == cache_key,
            PromptOptimizationCache.expires_at > datetime.now()
        ).first()

        if cached:
            # 更新命中统计
            cached.hit_count += 1
            cached.last_hit_at = datetime.now()
            self.db.commit()
            return cached.optimized_prompt, True

        return None, False

    def save_to_cache(
        self,
        project_id: str,
        context: Dict[str, Any],
        original_prompt: str,
        optimized_prompt: str,
        token_reduction: float
    ):
        """保存到缓存"""

        cache_key = self._compute_cache_key(project_id, context)

        cache = PromptOptimizationCache(
            id=str(uuid.uuid4()),
            context_hash=cache_key,
            original_prompt=original_prompt,
            optimized_prompt=optimized_prompt,
            optimization_type="material_injection",
            token_reduction=token_reduction,
            expires_at=datetime.now() + timedelta(days=7)
        )
        self.db.add(cache)
        self.db.commit()

    def _compute_cache_key(self, project_id: str, context: Dict) -> str:
        """计算缓存键"""
        key_data = {
            "project_id": project_id,
            "segment_type": context.get("segment_type"),
            "step": context.get("step"),
            "genre": context.get("genre_tags", [])
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()[:32]
