"""
项目学习沉淀服务 - 实现工作流自进化

核心功能：
1. 捕获用户编辑 → 沉淀项目素材
2. 分析项目素材 → 提取规则
3. 优化提示词 → 节省token
4. 持续监控 → 提升效率
"""
import uuid
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from difflib import unified_diff

from sqlalchemy.orm import Session

from app.models.project_learning import (
    ProjectMaterial, UserEditRecord, RuleExtractionJob,
    WorkflowEfficiencyMetrics, LearningInsight, PromptOptimizationCache
)
from app.models.episode_segment import EpisodeSegment
from app.models.step_version import StepVersion
from app.models.rule import Rule


class ProjectLearningService:
    """项目学习沉淀服务"""

    def __init__(self, db: Session):
        self.db = db

    # ============================================
    # 1. 用户编辑捕获与素材沉淀
    # ============================================

    def capture_user_edit(
        self,
        project_id: str,
        target_type: str,
        target_id: str,
        before_content: str,
        after_content: str,
        edit_reason: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> str:
        """
        捕获用户编辑，分析改动强度，并只沉淀为待审候选证据。

        用户改稿是强信号，但不是自动真理；不能因为用户改过就直接
        批准为全局素材或质量门规则。
        """
        # 计算差异
        diff = self._compute_diff(before_content, after_content)

        # 计算改进分数（简单启发式）
        improvement_score = self._calculate_improvement(
            before_content, after_content, target_type
        )

        # 判断是否是重大改进
        is_significant = improvement_score > 0.3 or len(diff) > 500

        # 分类编辑类型
        edit_category = self._categorize_edit(diff)

        # 创建编辑记录
        edit_record = UserEditRecord(
            id=str(uuid.uuid4()),
            project_id=project_id,
            session_id=session_id,
            target_type=target_type,
            target_id=target_id,
            before_content=before_content[:5000] if before_content else None,  # 限制长度
            after_content=after_content[:5000] if after_content else None,
            edit_diff=diff[:10000] if diff else None,  # 限制长度
            edit_reason=edit_reason,
            edit_category=edit_category,
            improvement_score=improvement_score,
            is_significant=is_significant,
            materialized=False
        )
        self.db.add(edit_record)

        # 如果是重大改动，只进入候选证据池，后续必须人工审查。
        material_id = None
        if is_significant:
            material_id = self._create_material_from_edit(edit_record)
            edit_record.materialized = True
            edit_record.material_id = material_id

        self.db.commit()

        return edit_record.id

    def _compute_diff(self, before: str, after: str) -> str:
        """计算统一diff格式"""
        before_lines = before.splitlines(keepends=True) if before else []
        after_lines = after.splitlines(keepends=True) if after else []
        diff = unified_diff(
            before_lines, after_lines,
            fromfile='before', tofile='after',
            lineterm=''
        )
        return '\n'.join(diff)

    def _calculate_improvement(
        self,
        before: str,
        after: str,
        target_type: str
    ) -> float:
        """计算改进程度分数 0-1"""
        scores = []

        # 字数改进（如果是段落）
        if target_type == 'segment':
            before_len = len(before) if before else 0
            after_len = len(after) if after else 0
            if before_len > 0:
                # 如果之前字数不足，现在达到目标，给予高分
                if before_len < 200 and after_len >= 250:
                    scores.append(0.8)
                elif abs(after_len - before_len) > 100:
                    scores.append(0.5)

        # 冲突元素检测
        conflict_words = ['冲突', '矛盾', '对抗', '争吵', '争执', '斗', '争']
        before_conflicts = sum(1 for w in conflict_words if w in (before or ''))
        after_conflicts = sum(1 for w in conflict_words if w in (after or ''))
        if after_conflicts > before_conflicts:
            scores.append(min(0.3 * (after_conflicts - before_conflicts), 0.9))

        # 情绪词检测
        emotion_words = ['怒', '恨', '气', '哭', '泪', '激动', '颤抖', '疯狂']
        before_emotions = sum(1 for w in emotion_words if w in (before or ''))
        after_emotions = sum(1 for w in emotion_words if w in (after or ''))
        if after_emotions > before_emotions:
            scores.append(min(0.2 * (after_emotions - before_emotions), 0.6))

        return max(scores) if scores else 0.1

    def _categorize_edit(self, diff: str) -> str:
        """分类编辑类型"""
        diff_lower = diff.lower()

        if any(w in diff_lower for w in ['节奏', '慢', '拖沓', '紧凑']):
            return 'pacing'
        elif any(w in diff_lower for w in ['情绪', '怒', '哭', '激动']):
            return 'emotion'
        elif any(w in diff_lower for w in ['对话', '说', '问', '答']):
            return 'dialogue'
        elif any(w in diff_lower for w in ['结构', '段落', '层次']):
            return 'structure'
        else:
            return 'general'

    def _create_material_from_edit(
        self,
        edit_record: UserEditRecord
    ) -> str:
        """从编辑记录创建素材"""

        # 确定素材类型
        material_type_map = {
            'pacing': 'pacing_pattern',
            'emotion': 'emotional_beats',
            'dialogue': 'dialogue_pattern',
            'structure': 'structure_pattern',
            'general': 'user_edit'
        }

        material = ProjectMaterial(
            id=str(uuid.uuid4()),
            project_id=edit_record.project_id,
            session_id=edit_record.session_id,
            material_type=material_type_map.get(edit_record.edit_category, 'user_edit'),
            source_segment_id=edit_record.target_id if edit_record.target_type == 'segment' else None,
            title=f"用户编辑 - {edit_record.edit_category}",
            content=edit_record.after_content,
            context=edit_record.before_content,
            quality_score=0.0,
            ai_score=0.0,
            user_rating=0,
            tags=[edit_record.edit_category, 'user_edit', 'candidate_evidence', 'needs_human_review'],
            status='candidate',
        )
        self.db.add(material)

        return material.id

    # ============================================
    # 2. 规则提取（任务结束后执行）
    # ============================================

    def start_rule_extraction(self, project_id: str) -> str:
        """启动规则提取任务"""

        # 获取项目的高质量素材
        materials = self.db.query(ProjectMaterial).filter(
            ProjectMaterial.project_id == project_id,
            ProjectMaterial.status == 'approved',
            ProjectMaterial.quality_score >= 0.6
        ).all()

        if len(materials) < 3:
            return "素材不足，至少需要3个高质量素材"

        job = RuleExtractionJob(
            id=str(uuid.uuid4()),
            project_id=project_id,
            status='running',
            total_materials=len(materials),
            selected_materials=[m.id for m in materials]
        )
        self.db.add(job)
        self.db.commit()

        # 执行提取
        try:
            self._extract_rules_from_materials(job, materials)
            job.status = 'completed'
            job.completed_at = datetime.now()
        except Exception as e:
            job.status = 'failed'
            job.extracted_rules = [{"error": str(e)}]

        self.db.commit()

        return job.id

    def _extract_rules_from_materials(
        self,
        job: RuleExtractionJob,
        materials: List[ProjectMaterial]
    ):
        """从素材中提取规则"""

        # 按类型分组
        by_type = {}
        for m in materials:
            by_type.setdefault(m.material_type, []).append(m)

        extracted_rules = []

        for mat_type, mats in by_type.items():
            if len(mats) < 2:
                continue

            # 提取该类型的共性模式
            pattern = self._extract_common_pattern(mats, mat_type)
            if pattern:
                extracted_rules.append({
                    "type": mat_type,
                    "pattern": pattern,
                    "sample_count": len(mats),
                    "avg_quality": sum(m.quality_score for m in mats) / len(mats)
                })

        job.extracted_rules = extracted_rules

        # 生成建议的规则内容
        if extracted_rules:
            job.suggested_rule_content = self._generate_rule_content(extracted_rules)
            job.confidence_score = min(len(extracted_rules) * 0.2 + 0.5, 0.95)

    def _extract_common_pattern(
        self,
        materials: List[ProjectMaterial],
        mat_type: str
    ) -> Optional[Dict]:
        """提取共性模式"""

        contents = [m.content for m in materials if m.content]
        if not contents:
            return None

        # 分析共同特征
        features = {}

        if mat_type == 'successful_hook':
            # 分析钩子开场方式
            opening_types = []
            for c in contents:
                first_50 = c[:50] if c else ''
                if '?' in first_50 or '？' in first_50:
                    opening_types.append('question')
                elif any(w in first_50 for w in ['不', '拒绝', '反对']):
                    opening_types.append('conflict')
                else:
                    opening_types.append('scene')
            features['opening_type_distribution'] = {
                t: opening_types.count(t) for t in set(opening_types)
            }
            features['avg_length'] = sum(len(c) for c in contents) / len(contents)

        elif mat_type == 'conflict_pattern':
            # 分析冲突元素
            conflict_indicators = ['冲突', '矛盾', '对抗', '争吵', '争执']
            avg_conflicts = sum(
                sum(1 for w in conflict_indicators if w in c)
                for c in contents
            ) / len(contents)
            features['avg_conflict_indicators'] = avg_conflicts

        elif mat_type == 'emotional_beats':
            # 分析情绪词
            emotion_words = ['怒', '恨', '气', '哭', '泪', '激动', '颤抖']
            avg_emotions = sum(
                sum(1 for w in emotion_words if w in c)
                for c in contents
            ) / len(contents)
            features['avg_emotion_words'] = avg_emotions

        return features

    def _generate_rule_content(self, extracted_rules: List[Dict]) -> str:
        """生成规则内容Markdown"""

        lines = ["# 项目沉淀规则\n", "基于本项目成功案例提取的定向规则：\n"]

        for rule in extracted_rules:
            rule_type = rule['type']
            pattern = rule['pattern']

            if rule_type == 'successful_hook':
                lines.append("## 钩子段写作规则\n")
                dist = pattern.get('opening_type_distribution', {})
                lines.append(f"- 样本数：{rule['sample_count']}个成功案例\n")
                lines.append(f"- 推荐开场方式：{max(dist, key=dist.get) if dist else '场景式'}\n")
                lines.append(f"- 目标字数：{int(pattern.get('avg_length', 250))}字左右\n\n")

            elif rule_type == 'conflict_pattern':
                lines.append("## 冲突设计规则\n")
                lines.append(f"- 样本数：{rule['sample_count']}个成功案例\n")
                lines.append(f"- 平均每段冲突元素数：{pattern.get('avg_conflict_indicators', 2):.1f}\n")
                lines.append("- 建议冲突强度：中高\n\n")

            elif rule_type == 'emotional_beats':
                lines.append("## 情绪渲染规则\n")
                lines.append(f"- 样本数：{rule['sample_count']}个成功案例\n")
                lines.append(f"- 平均每段情绪词数：{pattern.get('avg_emotion_words', 3):.1f}\n\n")

        lines.append("---\n")
        lines.append(f"*本规则由系统自动提取，置信度：{min(len(extracted_rules) * 0.2 + 0.5, 0.95):.0%}*\n")

        return ''.join(lines)

    def apply_extracted_rule(
        self,
        job_id: str,
        approve: bool = True,
        target_scope: str = 'task'
    ) -> Optional[str]:
        """应用提取的规则到系统"""

        job = self.db.query(RuleExtractionJob).get(job_id)
        if not job or job.status != 'completed':
            return None

        if not approve:
            job.apply_status = 'rejected'
            self.db.commit()
            return None

        # 创建规则
        rule = Rule(
            id=str(uuid.uuid4()),
            scope=target_scope,
            task_id=job.project_id if target_scope == 'task' else None,
            rule_type='project_learned',
            status='active',
            source='project_review',
            content=job.suggested_rule_content
        )
        self.db.add(rule)

        job.applied_to_rule_id = rule.id
        job.apply_status = 'approved'

        # 标记素材为已提升
        for material_id in job.selected_materials:
            material = self.db.query(ProjectMaterial).get(material_id)
            if material:
                material.promoted_to_global = True

        self.db.commit()

        return rule.id

    # ============================================
    # 3. Token优化与提示词缓存
    # ============================================

    def optimize_prompt(
        self,
        project_id: str,
        original_prompt: str,
        context: Dict[str, Any]
    ) -> Tuple[str, Dict]:
        """
        优化提示词，注入项目素材，减少token消耗
        """

        # 计算上下文哈希
        context_hash = self._hash_context(project_id, context)

        # 检查缓存
        cached = self.db.query(PromptOptimizationCache).filter(
            PromptOptimizationCache.context_hash == context_hash
        ).first()

        if cached and cached.expires_at and cached.expires_at > datetime.now():
            # 命中缓存
            cached.hit_count += 1
            cached.last_hit_at = datetime.now()
            self.db.commit()
            return cached.optimized_prompt, {
                "cached": True,
                "token_reduction": cached.token_reduction,
                "materials_injected": cached.materials_injected
            }

        # 获取相关素材
        segment_type = context.get('segment_type', '')
        genre_tags = context.get('genre_tags', [])

        materials = self._get_relevant_materials(
            project_id, segment_type, genre_tags, limit=3
        )

        # 构建优化后的提示词
        optimized = self._build_optimized_prompt(
            original_prompt, materials, context
        )

        # 计算token节省
        original_tokens = len(original_prompt) // 4  # 粗略估算
        optimized_tokens = len(optimized) // 4
        token_reduction = (original_tokens - optimized_tokens) / original_tokens if original_tokens > 0 else 0

        # 保存缓存
        cache = PromptOptimizationCache(
            id=str(uuid.uuid4()),
            context_hash=context_hash,
            original_prompt=original_prompt,
            optimized_prompt=optimized,
            optimization_type='material_injection',
            materials_injected=[m.id for m in materials],
            token_reduction=token_reduction,
            expires_at=datetime.now() + timedelta(days=7)
        )
        self.db.add(cache)
        self.db.commit()

        return optimized, {
            "cached": False,
            "token_reduction": token_reduction,
            "materials_injected": [m.id for m in materials],
            "materials_count": len(materials)
        }

    def _hash_context(self, project_id: str, context: Dict) -> str:
        """计算上下文哈希"""
        key_data = {
            "project_id": project_id,
            "segment_type": context.get('segment_type'),
            "step": context.get('step'),
            "genre": context.get('genre_tags', [])
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()[:32]

    def _get_relevant_materials(
        self,
        project_id: str,
        segment_type: str,
        genre_tags: List[str],
        limit: int = 3
    ) -> List[ProjectMaterial]:
        """获取相关素材"""

        # 先尝试获取同项目素材
        materials = self.db.query(ProjectMaterial).filter(
            ProjectMaterial.project_id == project_id,
            ProjectMaterial.status == 'approved',
            ProjectMaterial.material_type.like(f'%{segment_type}%')
        ).order_by(
            ProjectMaterial.quality_score.desc(),
            ProjectMaterial.usage_count.desc()
        ).limit(limit).all()

        if len(materials) < limit and genre_tags:
            # 补充同题材的其他项目素材 (简化查询，不使用overlap)
            # 获取高质量的其他项目素材作为补充
            additional = self.db.query(ProjectMaterial).filter(
                ProjectMaterial.project_id != project_id,
                ProjectMaterial.status == 'approved',
                ProjectMaterial.quality_score >= 0.7
            ).order_by(
                ProjectMaterial.quality_score.desc()
            ).limit(limit - len(materials)).all()
            materials.extend(additional)

        return materials

    def _build_optimized_prompt(
        self,
        original: str,
        materials: List[ProjectMaterial],
        context: Dict
    ) -> str:
        """构建优化后的提示词"""

        if not materials:
            return original

        # 构建示例部分
        examples = []
        for i, m in enumerate(materials[:2], 1):
            if m.content:
                examples.append(f"示例{i}（质量分{m.quality_score:.0%}）：\n{m.content[:500]}...")

        # 注入到提示词中
        injection = "\n\n---\n【项目成功案例参考】\n" + "\n\n".join(examples)
        injection += "\n\n请参照以上成功案例的风格和结构进行创作。\n---\n"

        # 将注入放在适当位置（在主要指令之后，输出格式之前）
        if "输出格式" in original:
            parts = original.split("输出格式")
            return parts[0] + injection + "\n输出格式" + parts[1]
        else:
            return original + injection

    # ============================================
    # 4. 效率追踪与洞察
    # ============================================

    def record_generation_metrics(
        self,
        project_id: str,
        tokens_used: int,
        segment_count: int = 1,
        auto_fix_used: bool = False,
        material_applied: bool = False
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

        metric.completion_tokens_total += tokens_used
        metric.segments_generated += segment_count
        if auto_fix_used:
            metric.auto_fix_triggered += 1
        if material_applied:
            metric.material_applied_count += 1

        self.db.commit()

    def get_efficiency_report(self, project_id: str, days: int = 7) -> Dict:
        """获取效率报告"""

        start_date = datetime.now() - timedelta(days=days)

        metrics = self.db.query(WorkflowEfficiencyMetrics).filter(
            WorkflowEfficiencyMetrics.project_id == project_id,
            WorkflowEfficiencyMetrics.date >= start_date
        ).all()

        if not metrics:
            return {"message": "暂无数据"}

        total_tokens = sum(m.completion_tokens_total for m in metrics)
        total_segments = sum(m.segments_generated for m in metrics)
        auto_fix_success = sum(m.auto_fix_success for m in metrics)
        auto_fix_total = sum(m.auto_fix_triggered for m in metrics)

        return {
            "period_days": days,
            "total_tokens": total_tokens,
            "total_segments": total_segments,
            "avg_tokens_per_segment": total_tokens / total_segments if total_segments > 0 else 0,
            "auto_fix_success_rate": auto_fix_success / auto_fix_total if auto_fix_total > 0 else 0,
            "total_auto_fix": auto_fix_total,
            "trend": [
                {
                    "date": m.date.strftime("%Y-%m-%d"),
                    "tokens": m.completion_tokens_total,
                    "segments": m.segments_generated
                }
                for m in sorted(metrics, key=lambda x: x.date)
            ]
        }

    def generate_learning_insights(self, project_id: str) -> List[Dict]:
        """生成学习洞察"""

        insights = []

        # 1. 分析最常见的失败模式
        from app.models.auto_fix import AutoFixRecord
        fix_records = self.db.query(AutoFixRecord).filter(
            AutoFixRecord.segment_id.in_(
                self.db.query(EpisodeSegment.id).filter(
                    EpisodeSegment.session_id.in_(
                        self.db.query(StepVersion.session_id).filter(
                            StepVersion.session_id == project_id
                        )
                    )
                )
            )
        ).all()

        if fix_records:
            pattern_counts = {}
            for r in fix_records:
                pattern_counts[r.failure_type] = pattern_counts.get(r.failure_type, 0) + 1

            most_common = max(pattern_counts.items(), key=lambda x: x[1])
            insights.append({
                "type": "warning",
                "title": f"常见失败模式：{most_common[0]}",
                "description": f"该项目中有{most_common[1]}次'{most_common[0]}'失败，建议在生成前加强检查。",
                "confidence": 0.8
            })

        # 2. 分析素材效果
        materials = self.db.query(ProjectMaterial).filter(
            ProjectMaterial.project_id == project_id,
            ProjectMaterial.usage_count > 0
        ).all()

        if materials:
            avg_quality = sum(m.quality_score for m in materials) / len(materials)
            if avg_quality > 0.8:
                insights.append({
                    "type": "suggestion",
                    "title": "高质量素材积累充足",
                    "description": f"项目已积累{len(materials)}个高质量素材，可提取为全局规则。",
                    "confidence": avg_quality
                })

        # 3. 效率趋势
        efficiency = self.get_efficiency_report(project_id, days=7)
        if efficiency.get("total_tokens", 0) > 0:
            avg_tokens = efficiency.get("avg_tokens_per_segment", 0)
            if avg_tokens > 2000:
                insights.append({
                    "type": "efficiency",
                    "title": "Token消耗偏高",
                    "description": f"平均每段消耗{avg_tokens:.0f} tokens，建议优化提示词或启用素材缓存。",
                    "confidence": 0.7
                })

        return insights
