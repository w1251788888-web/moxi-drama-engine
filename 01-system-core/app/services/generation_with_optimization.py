"""
带Token优化的生成服务 - 质量保障版

核心特性：
1. A/B测试风格对比（优化版vs原始版）
2. 质量不达标自动回滚
3. 完整的效果追踪
4. 渐进式启用（从项目级到全局级）
"""
import asyncio
import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.services.token_optimization_service import TokenOptimizationService, OptimizationResult
from app.services.project_learning_service import ProjectLearningService
from app.services.text_generation_service import generate_text as sync_generate_text
from app.models.project_learning import WorkflowEfficiencyMetrics


@dataclass
class GenerationResult:
    """生成结果"""
    content: str
    tokens_used: int
    generation_time: float
    prompt_type: str  # "original" | "optimized" | "fallback"
    quality_score: float
    optimization_meta: Optional[Dict]
    risk_flags: List[str]


class OptimizedGenerationService:
    """带优化的生成服务"""

    def __init__(self, db: Session):
        self.db = db
        self.opt_service = TokenOptimizationService(db)
        self.learning_service = ProjectLearningService(db)

    async def generate_with_quality_guard(
        self,
        project_id: str,
        segment_id: str,
        original_prompt: str,
        context: Dict[str, Any],
        enable_ab_test: bool = False
    ) -> GenerationResult:
        """
        带质量保障的生成

        Args:
            project_id: 项目ID
            segment_id: 段落ID（用于追踪）
            original_prompt: 原始提示词（包含完整规则）
            context: 上下文（segment_type, genre等）
            enable_ab_test: 是否启用A/B测试（同时生成两个版本对比）

        Returns:
            GenerationResult: 生成结果
        """

        # 步骤1: 尝试优化提示词
        opt_result = self.opt_service.optimize_with_guardrails(
            project_id=project_id,
            original_prompt=original_prompt,
            context=context,
            force_optimize=False  # 默认不强制，优先质量
        )

        # 记录优化决策
        self._log_optimization_decision(segment_id, opt_result)

        # 步骤2: 如果优化不安全，直接使用原始提示词
        if not opt_result.safe_to_use:
            print(f"[生成] 优化未通过安全检查，使用原始提示词")
            print(f"[生成] 风险: {opt_result.risk_flags}")

            result = await self._generate_with_original(
                original_prompt, segment_id
            )
            result.prompt_type = "original"
            result.optimization_meta = {
                "attempted": True,
                "accepted": False,
                "reason": opt_result.risk_flags
            }
            return result

        # 步骤3: A/B测试模式（可选）
        if enable_ab_test:
            return await self._generate_ab_test(
                original_prompt=original_prompt,
                optimized_prompt=opt_result.optimized_prompt,
                segment_id=segment_id,
                opt_meta=opt_result
            )

        # 步骤4: 正常模式 - 使用优化提示词
        print(f"[生成] 使用优化提示词（质量分: {opt_result.quality_score:.2f}）")
        print(f"[生成] Token节省预估: {opt_result.token_reduction*100:.0f}%")

        result = await self._generate_with_prompt(
            opt_result.optimized_prompt, segment_id
        )

        # 步骤5: 验证生成质量
        quality_ok = self._validate_generation_quality(result)

        if not quality_ok:
            print(f"[生成] 质量不达标，回滚到原始提示词重试")

            # 回滚到原始提示词
            result = await self._generate_with_original(
                original_prompt, segment_id
            )
            result.prompt_type = "fallback"
            result.risk_flags.append("优化版本质量不达标，已回滚")

            # 记录回滚
            self._record_rollback(segment_id, opt_result)
        else:
            result.prompt_type = "optimized"
            # 保存到缓存
            self.opt_service.save_to_cache(
                project_id=project_id,
                context=context,
                original_prompt=original_prompt,
                optimized_prompt=opt_result.optimized_prompt,
                token_reduction=opt_result.token_reduction
            )

        result.optimization_meta = {
            "attempted": True,
            "accepted": True,
            "quality_score": opt_result.quality_score,
            "token_reduction": opt_result.token_reduction,
            "materials_injected": opt_result.materials_injected
        }

        # 步骤6: 记录效果
        self._record_generation_metrics(
            project_id=project_id,
            segment_id=segment_id,
            result=result,
            opt_result=opt_result
        )

        return result

    async def _generate_ab_test(
        self,
        original_prompt: str,
        optimized_prompt: str,
        segment_id: str,
        opt_meta: OptimizationResult
    ) -> GenerationResult:
        """
        A/B测试：生成两个版本并对比
        """
        print(f"[A/B测试] 同时生成原始版和优化版...")

        # 生成原始版
        result_original = await self._generate_with_prompt(
            original_prompt, segment_id + "_original"
        )

        # 生成优化版
        result_optimized = await self._generate_with_prompt(
            optimized_prompt, segment_id + "_optimized"
        )

        # 评估两个版本
        score_original = self._score_generation(result_original)
        score_optimized = self._score_generation(result_optimized)

        print(f"[A/B测试] 原始版质量分: {score_original:.2f}")
        print(f"[A/B测试] 优化版质量分: {score_optimized:.2f}")

        # 选择更好的版本
        if score_optimized >= score_original * 0.95:  # 允许5%的质量损失
            print(f"[A/B测试] 选择优化版（token节省{opt_meta.token_reduction*100:.0f}%）")
            result_optimized.prompt_type = "optimized_ab_test"
            result_optimized.optimization_meta = {
                "ab_test": True,
                "original_score": score_original,
                "optimized_score": score_optimized,
                "token_reduction": opt_meta.token_reduction
            }
            return result_optimized
        else:
            print(f"[A/B测试] 选择原始版（优化版质量损失过大）")
            result_original.prompt_type = "original_ab_test"
            result_original.optimization_meta = {
                "ab_test": True,
                "original_score": score_original,
                "optimized_score": score_optimized,
                "reject_reason": "质量不达标"
            }
            return result_original

    async def _generate_with_original(
        self,
        original_prompt: str,
        segment_id: str
    ) -> GenerationResult:
        """使用原始提示词生成"""
        return await self._generate_with_prompt(original_prompt, segment_id)

    async def _generate_with_prompt(
        self,
        prompt: str,
        segment_id: str
    ) -> GenerationResult:
        """使用指定提示词生成（真实调用）。"""
        start_time = time.perf_counter()
        system_prompt = (
            "你是短剧写作生成助手。"
            "请严格按照用户提示词完成正文，不要输出解释、标题包装或额外说明。"
        )
        max_tokens = min(4000, max(800, len(prompt) // 2))

        content = await asyncio.to_thread(
            sync_generate_text,
            system_prompt,
            prompt,
            temperature=0.6,
            max_tokens=max_tokens,
        )
        generation_time = time.perf_counter() - start_time
        normalized_content = str(content or "").strip()
        estimated_tokens = max(1, (len(prompt) + len(normalized_content)) // 4)
        risk_flags: List[str] = []
        if len(normalized_content) < 120:
            risk_flags.append("生成内容偏短，可能存在信息缺失")
        if "```" in normalized_content:
            risk_flags.append("生成结果含代码块包装")

        return GenerationResult(
            content=normalized_content,
            tokens_used=estimated_tokens,
            generation_time=generation_time,
            prompt_type="unknown",
            quality_score=self._estimate_quality_score(normalized_content),
            optimization_meta=None,
            risk_flags=risk_flags,
        )

    def _estimate_quality_score(self, content: str) -> float:
        """根据输出完整度做一个轻量质量估分，供回滚逻辑使用。"""
        length = len(str(content or "").strip())
        if length < 80:
            return 0.45
        if length < 180:
            return 0.62
        if length < 320:
            return 0.74
        if length < 600:
            return 0.84
        return 0.9

    def _validate_generation_quality(self, result: GenerationResult) -> bool:
        """验证生成质量"""
        # 检查生成内容是否有效
        if not result.content or len(result.content) < 50:
            return False

        # 检查质量分
        if result.quality_score < 0.6:
            return False

        # 检查生成时间（异常快的可能是缓存错误）
        if result.generation_time < 0.05:
            return False

        return True

    def _score_generation(self, result: GenerationResult) -> float:
        """给生成结果打分"""
        score = result.quality_score

        # 字数充足加分
        if len(result.content) > 200:
            score += 0.05

        # token效率加分（节省token是优势）
        if result.tokens_used < 1500:
            score += 0.05

        return min(score, 1.0)

    def _log_optimization_decision(
        self,
        segment_id: str,
        opt_result: OptimizationResult
    ):
        """记录优化决策"""
        status = "✅ 通过" if opt_result.safe_to_use else "❌ 拒绝"
        print(f"[优化决策] {status} | 质量分: {opt_result.quality_score:.2f}")

        if opt_result.risk_flags:
            for flag in opt_result.risk_flags:
                print(f"[优化决策] ⚠️  {flag}")

    def _record_rollback(self, segment_id: str, opt_result: OptimizationResult):
        """记录回滚事件"""
        print(f"[回滚记录] 段落 {segment_id} 从优化版回滚到原始版")
        print(f"[回滚记录] 原因: {opt_result.risk_flags}")

        # 这里可以记录到专门的回滚日志表

    def _record_generation_metrics(
        self,
        project_id: str,
        segment_id: str,
        result: GenerationResult,
        opt_result: OptimizationResult
    ):
        """记录生成指标"""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        metric = self.db.query(WorkflowEfficiencyMetrics).filter(
            WorkflowEfficiencyMetrics.project_id == project_id,
            WorkflowEfficiencyMetrics.date == today
        ).first()

        if not metric:
            metric = WorkflowEfficiencyMetrics(
                id=str(uuid.uuid4()),
                project_id=project_id,
                date=today
            )
            self.db.add(metric)

        # 更新指标
        metric.completion_tokens_total += result.tokens_used
        metric.segments_generated += 1

        if result.prompt_type == "optimized":
            metric.material_applied_count += 1
            metric.token_saved += int(opt_result.token_reduction * 2000)  # 估算

        self.db.commit()


# 全局配置：控制优化启用策略
class OptimizationConfig:
    """优化配置"""

    # 渐进式启用策略
    ENABLE_STRATEGY = {
        "new_project": False,      # 新项目：前3段不使用优化（积累素材）
        "after_3_segments": True,  # 3段后：启用优化
        "ab_test_rate": 0.1,       # 10%的生成使用A/B测试
        "force_after_validation": True,  # 验证通过后强制启用
    }

    # 质量阈值
    QUALITY_THRESHOLDS = {
        "min_quality_score": 0.8,      # 最低质量分
        "max_rollback_rate": 0.2,      # 最大回滚率（超过则暂停优化）
        "min_success_rate": 0.75,      # 最低成功率
    }


import asyncio


async def demo():
    """演示"""
    from app.database import SessionLocal

    db = SessionLocal()
    service = OptimizedGenerationService(db)

    # 模拟生成
    result = await service.generate_with_quality_guard(
        project_id="test-project",
        segment_id="segment-001",
        original_prompt="""
你是一位短剧剧本写作专家。

任务：写一个钩子段落，开场要有吸引力。

核心规则：
- 字数控制在250-300字
- 前50字必须有冲突或悬念
- 建立强烈的情绪张力

输出格式：
直接返回段落内容，不需要解释。
""",
        context={"segment_type": "hook", "genre_tags": ["男频逆袭"]},
        enable_ab_test=False
    )

    print(f"\n生成结果:")
    print(f"类型: {result.prompt_type}")
    print(f"Token消耗: {result.tokens_used}")
    print(f"质量分: {result.quality_score:.2f}")
    print(f"优化信息: {result.optimization_meta}")


if __name__ == "__main__":
    asyncio.run(demo())
