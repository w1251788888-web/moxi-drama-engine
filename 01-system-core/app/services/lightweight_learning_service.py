"""
极简自学习服务 - 三明治注入法 (OpenSpace AUTO-LEARN 启发)

核心原则：
1. 只追加，不修改 - 100%保留用户规则
2. 无侵入 - 用户感知不到优化存在
3. 越用越轻 - 自动学习，自动优化 (任务越来越轻)
4. 自我进化 - 从成功模式中提取经验

OpenSpace 机制映射：
- AUTO-CAPTURE: record_generation / record_user_edit
- AUTO-IMPROVE: _extract_success_patterns
- AUTO-LEARN: optimize_prompt (基于历史自动优化)
"""
import os
import uuid
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.project_learning import (
    ProjectMaterial, UserEditRecord, WorkflowEfficiencyMetrics,
    MaterialStatus, MaterialType
)


@dataclass
class LightweightOptimizationResult:
    """极简优化结果"""
    final_prompt: str           # 最终提示词
    user_prompt: str            # 用户的原始提示词（100%保留）
    prefix: str                 # 开头追加的内容
    suffix: str                 # 结尾追加的内容
    stats: Dict                 # 使用的统计数据
    mode: str                   # 模式：transparent/lightweight/smart


class LightweightLearningService:
    """极简自学习服务 - 实现任务越来越轻的自我进化"""

    # 模式阈值 - 可从环境变量配置，实现灵活调整
    TRANSPARENT_THRESHOLD = int(os.getenv('LEARNING_TRANSPARENT_THRESHOLD', '3'))
    LIGHTWEIGHT_THRESHOLD = int(os.getenv('LEARNING_LIGHTWEIGHT_THRESHOLD', '10'))

    # 质量阈值
    QUALITY_THRESHOLD_HIGH = float(os.getenv('LEARNING_QUALITY_THRESHOLD_HIGH', '0.8'))
    QUALITY_THRESHOLD_MEDIUM = float(os.getenv('LEARNING_QUALITY_THRESHOLD_MEDIUM', '0.6'))

    # 智能模式触发：用户输入长度阈值
    SMART_MODE_INPUT_THRESHOLD = int(os.getenv('LEARNING_SMART_INPUT_THRESHOLD', '50'))

    def __init__(self, db: Session):
        self.db = db
        # 阈值需要在实例创建时读取，测试和运行时才能通过环境变量调整。
        self.TRANSPARENT_THRESHOLD = int(os.getenv('LEARNING_TRANSPARENT_THRESHOLD', str(type(self).TRANSPARENT_THRESHOLD)))
        self.LIGHTWEIGHT_THRESHOLD = int(os.getenv('LEARNING_LIGHTWEIGHT_THRESHOLD', str(type(self).LIGHTWEIGHT_THRESHOLD)))
        self.QUALITY_THRESHOLD_HIGH = float(os.getenv('LEARNING_QUALITY_THRESHOLD_HIGH', str(type(self).QUALITY_THRESHOLD_HIGH)))
        self.QUALITY_THRESHOLD_MEDIUM = float(os.getenv('LEARNING_QUALITY_THRESHOLD_MEDIUM', str(type(self).QUALITY_THRESHOLD_MEDIUM)))
        self.SMART_MODE_INPUT_THRESHOLD = int(os.getenv('LEARNING_SMART_INPUT_THRESHOLD', str(type(self).SMART_MODE_INPUT_THRESHOLD)))
        # 缓存用户成功模式，避免重复查询
        self._pattern_cache: Dict[str, Dict] = {}

    def optimize_prompt(self, project_id: str, user_prompt: str,
                       segment_type: str, episode_no: int) -> LightweightOptimizationResult:
        """
        极简提示词优化

        原则：
        1. 绝不修改user_prompt的任何内容
        2. 只在开头/结尾追加参考信息
        3. 追加内容必须是统计数据，不是规则
        """

        # 1. 检查项目历史数量
        history_count = self._get_project_segment_count(project_id)

        # 2. 根据历史选择模式
        if history_count < self.TRANSPARENT_THRESHOLD:
            return self._transparent_mode(project_id, user_prompt, segment_type)
        elif history_count < self.LIGHTWEIGHT_THRESHOLD:
            return self._lightweight_mode(project_id, user_prompt, segment_type)
        else:
            return self._smart_mode(project_id, user_prompt, segment_type, episode_no)

    def _transparent_mode(self, project_id: str, user_prompt: str,
                          segment_type: str) -> LightweightOptimizationResult:
        """
        透明模式：不干预，只记录
        """
        return LightweightOptimizationResult(
            final_prompt=user_prompt,
            user_prompt=user_prompt,
            prefix="",
            suffix="",
            stats={},
            mode="transparent"
        )

    def _lightweight_mode(self, project_id: str, user_prompt: str,
                          segment_type: str) -> LightweightOptimizationResult:
        """
        轻量模式：追加一句统计参考
        """
        # 获取同类段落的统计数据
        stats = self._get_segment_stats(project_id, segment_type)

        if not stats or stats['count'] < 2:
            # 数据不足，退回到透明模式
            return self._transparent_mode(project_id, user_prompt, segment_type)

        # 构建轻量参考（只包含数据，不包含规则）
        prefix = f"""【系统参考】本项目历史{segment_type}段数据：
- 平均字数：{stats['avg_words']:.0f}字
- 成功率：{stats['success_rate']*100:.0f}%
- 样本数：{stats['count']}个

================
核心规则（用户定义，请严格遵守）
================

"""

        final_prompt = prefix + user_prompt

        return LightweightOptimizationResult(
            final_prompt=final_prompt,
            user_prompt=user_prompt,
            prefix=prefix,
            suffix="",
            stats=stats,
            mode="lightweight"
        )

    def _smart_mode(self, project_id: str, user_prompt: str,
                    segment_type: str, episode_no: int) -> LightweightOptimizationResult:
        """
        智能模式：用户输入简化，系统自动补全
        """
        # 获取更详细的统计数据
        stats = self._get_detailed_stats(project_id, segment_type)

        # 如果用户输入很短（少于50字），说明依赖自动补全
        if len(user_prompt) < self.SMART_MODE_INPUT_THRESHOLD:
            # 自动补全用户的常用规则
            template = self._get_user_template(project_id)

            prefix = f"""【系统参考】基于项目历史自动补全：
{self._format_stats(stats)}

================
用户常用规则模板
================
{template}

================
本次任务
================

"""
            final_prompt = prefix + user_prompt
        else:
            # 用户输入完整，使用轻量模式
            return self._lightweight_mode(project_id, user_prompt, segment_type)

        # 添加后缀提醒
        suffix = """

================
【系统提醒】生成完成后请检查：字数是否符合要求，冲突是否充分
================"""
        final_prompt = final_prompt + suffix

        return LightweightOptimizationResult(
            final_prompt=final_prompt,
            user_prompt=user_prompt,
            prefix=prefix,
            suffix=suffix,
            stats=stats,
            mode="smart"
        )

    def record_generation(self, project_id: str, segment_type: str,
                         episode_no: int, content: str,
                         validation_score: float = None):
        """
        记录生成结果（自动学习，用户无感知）

        只记录数据，不分析原因：
        - 什么类型段落
        - 多少字
        - 质量分多少
        """
        # 自动提取基础数据
        word_count = len(content)

        # 简单统计冲突点（通过关键词）
        conflict_keywords = ['冲突', '矛盾', '对抗', '争吵', '争执', '斗']
        conflict_count = sum(1 for kw in conflict_keywords if kw in content)

        # 保存到观察池（不需要人工审核，纯数据）
        material = ProjectMaterial(
            id=str(uuid.uuid4()),
            project_id=project_id,
            material_type=getattr(MaterialType, f"OBSERVED_{segment_type.upper()}", MaterialType.OBSERVED_HOOK),
            title=f"第{episode_no}集{segment_type}段观察数据",
            content=content[:500],  # 只存前500字作为参考
            quality_score=validation_score or 0.7,
            status=MaterialStatus.AUTO_RECORDED.value,  # 使用枚举值
            tags=[segment_type, "auto"],
            # 存储统计数据
            context=json.dumps({
                "word_count": word_count,
                "conflict_count": conflict_count,
                "episode_no": episode_no
            })
        )
        self.db.add(material)

        # 更新效率指标
        self._update_efficiency_metrics(project_id, word_count)

        self.db.commit()

    def record_user_edit(self, project_id: str, segment_type: str,
                        before_content: str, after_content: str):
        """
        记录用户编辑（候选沉淀）

        不把用户改稿直接当作系统真理，只记录改了什么：
        - 改前多少字
        - 改后多少字
        - 是否值得进入人工复核候选池
        """
        # 简单判断是否是有效修改
        if len(after_content) < len(before_content) * 0.5:
            # 删除太多，可能不是改进
            return

        is_significant = len(after_content) > len(before_content) * 1.2

        # 记录编辑（只作为候选证据，不自动升级规则）
        edit_record = UserEditRecord(
            id=str(uuid.uuid4()),
            project_id=project_id,
            target_type="segment",
            target_id=f"{project_id}_{segment_type}",
            before_content=before_content[:1000],
            after_content=after_content[:1000],
            edit_diff=f"{len(before_content)}字 -> {len(after_content)}字",
            improvement_score=0.0,
            is_significant=is_significant,
            materialized=is_significant
        )
        self.db.add(edit_record)

        # 大幅改稿只进入候选证据池，不能自动 approved。
        if is_significant:
            material = ProjectMaterial(
                id=str(uuid.uuid4()),
                project_id=project_id,
                material_type=getattr(MaterialType, f"USER_IMPROVED_{segment_type.upper()}", MaterialType.USER_EDIT),
                title=f"用户改稿候选证据 - {segment_type}段",
                content=after_content,
                quality_score=0.0,
                user_rating=0,
                ai_score=0.0,
                status=MaterialStatus.CANDIDATE.value,
                tags=[segment_type, "user_edit", "candidate_evidence", "needs_human_review"],
                context=json.dumps({
                    "before_length": len(before_content),
                    "after_length": len(after_content),
                    "review_policy": "user_edit_candidate_only_not_auto_approved",
                }, ensure_ascii=False)
            )
            self.db.add(material)
            edit_record.material_id = material.id

        self.db.commit()

    def record_manual_edit_evidence(
        self,
        *,
        project_id: str,
        episode_no: int,
        scene_no: int,
        saved_content: str,
        evidence: dict,
        commit: bool = True,
    ) -> str:
        """保存用户改稿候选证据，等待人工复核后再决定是否升级规则。"""
        if not isinstance(evidence, dict) or not str(saved_content or "").strip():
            return ""
        delta = evidence.get("manual_edit_delta") if isinstance(evidence.get("manual_edit_delta"), dict) else {}
        candidate = (
            evidence.get("model_candidate_snapshot")
            if isinstance(evidence.get("model_candidate_snapshot"), dict)
            else {}
        )
        before_content = str(
            evidence.get("before_content")
            or candidate.get("content")
            or delta.get("candidate_tail_excerpt")
            or delta.get("previous_excerpt")
            or ""
        ).strip()
        candidate_hash = str(
            evidence.get("model_candidate_hash")
            or candidate.get("content_hash")
            or delta.get("previous_candidate_hash")
            or ""
        ).strip()
        if not before_content and not candidate_hash and not delta:
            return ""

        saved_hash = str(evidence.get("saved_content_hash") or "").strip()
        if not saved_hash:
            saved_hash = hashlib.sha256(str(saved_content or "").encode("utf-8")).hexdigest()
        target_id = f"ep{int(episode_no or 0)}:scene{int(scene_no or 0)}:saved:{saved_hash[:16]}"
        existing = (
            self.db.query(UserEditRecord)
            .filter(
                UserEditRecord.project_id == project_id,
                UserEditRecord.target_type == "scene",
                UserEditRecord.target_id == target_id,
            )
            .first()
        )
        if existing is not None:
            return str(getattr(existing, "material_id", "") or "")

        after_content = str(saved_content or "").strip()
        edit_record = UserEditRecord(
            id=str(uuid.uuid4()),
            project_id=project_id,
            target_type="scene",
            target_id=target_id,
            before_content=before_content[:1000],
            after_content=after_content[:1000],
            edit_diff=json.dumps({
                "episode_no": int(episode_no or 0),
                "scene_no": int(scene_no or 0),
                "candidate_hash": candidate_hash,
                "saved_content_hash": saved_hash,
                "manual_edit_delta": delta,
            }, ensure_ascii=False),
            edit_reason=str(evidence.get("change_note") or delta.get("change_note") or "用户保存改稿"),
            edit_category="general",
            improvement_score=0.0,
            is_significant=True,
            materialized=True,
        )
        self.db.add(edit_record)

        material = ProjectMaterial(
            id=str(uuid.uuid4()),
            project_id=project_id,
            material_type=MaterialType.USER_EDIT.value,
            title=f"用户改稿候选证据 - 第{int(episode_no or 0)}集第{int(scene_no or 0)}场",
            content=after_content[:2000],
            context=json.dumps({
                "before_excerpt": before_content[:500],
                "candidate_hash": candidate_hash,
                "saved_content_hash": saved_hash,
                "episode_no": int(episode_no or 0),
                "scene_no": int(scene_no or 0),
                "review_policy": "user_edit_candidate_only_not_auto_approved",
            }, ensure_ascii=False),
            quality_score=0.0,
            ai_score=0.0,
            user_rating=0,
            tags=["scene", "user_edit", "candidate_evidence", "needs_human_review"],
            status=MaterialStatus.CANDIDATE.value,
        )
        self.db.add(material)
        edit_record.material_id = material.id
        if commit:
            self.db.commit()
        return material.id

    def _get_project_segment_count(self, project_id: str) -> int:
        """获取项目已生成段落数"""
        count = self.db.query(ProjectMaterial).filter(
            ProjectMaterial.project_id == project_id
        ).count()
        return count

    def _get_segment_stats(self, project_id: str, segment_type: str) -> Optional[Dict]:
        """获取同类段落的统计数据"""
        materials = self.db.query(ProjectMaterial).filter(
            ProjectMaterial.project_id == project_id,
            ProjectMaterial.material_type.like(f"%{segment_type}%")
        ).all()

        try:
            materials = list(materials)
        except TypeError:
            materials = []

        if not materials:
            return None

        # 解析统计数据
        word_counts = []
        for m in materials:
            if m.context:
                try:
                    data = json.loads(m.context)
                    word_counts.append(data.get("word_count", len(m.content)))
                except (json.JSONDecodeError, TypeError, AttributeError) as e:
                    # 记录解析失败但不中断流程
                    word_counts.append(len(m.content))
            else:
                word_counts.append(len(m.content))

        return {
            "count": len(materials),
            "avg_words": sum(word_counts) / len(word_counts) if word_counts else 0,
            "success_rate": sum(m.quality_score or 0 for m in materials) / len(materials) if materials else 0
        }

    def _get_detailed_stats(self, project_id: str, segment_type: str) -> Dict:
        """获取详细统计数据"""
        basic = self._get_segment_stats(project_id, segment_type)
        if not basic:
            return {"count": 0}

        # 获取质量分布
        high_quality = self.db.query(ProjectMaterial).filter(
            ProjectMaterial.project_id == project_id,
            ProjectMaterial.material_type.like(f"%{segment_type}%"),
            ProjectMaterial.quality_score >= 0.8
        ).count()

        return {
            **basic,
            "high_quality_count": high_quality,
            "high_quality_rate": high_quality / basic["count"] if basic["count"] > 0 else 0
        }

    def _get_user_template(self, project_id: str) -> str:
        """获取用户的常用规则模板（从最高质量的素材中提取）"""
        # 简化实现：返回一个通用的模板
        # 实际可以从用户的成功素材中提取共用的规则部分
        return """你是一位专业的短剧剧本写作专家。

任务要求：
1. 严格遵循剧本格式
2. 保持人物性格一致性
3. 每段都有明确的情绪张力
"""

    def _format_stats(self, stats: Dict) -> str:
        """格式化统计数据"""
        if not stats or stats.get("count", 0) == 0:
            return "暂无历史数据"

        return f"""- 历史生成数量：{stats['count']}段
- 平均字数：{stats.get('avg_words', 0):.0f}字
- 高质量比例：{stats.get('high_quality_rate', 0)*100:.0f}%
- 成功率：{stats.get('success_rate', 0)*100:.0f}%"""

    def _update_efficiency_metrics(self, project_id: str, tokens_used: int):
        """更新效率指标"""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        metric = self.db.query(WorkflowEfficiencyMetrics).filter(
            WorkflowEfficiencyMetrics.project_id == project_id,
            WorkflowEfficiencyMetrics.date == today
        ).first()

        if not metric:
            metric = WorkflowEfficiencyMetrics(
                id=str(uuid.uuid4()),
                project_id=project_id,
                date=today,
                segments_generated=0,
                completion_tokens_total=0,
                material_applied_count=0,
                token_saved=0
            )
            self.db.add(metric)
            self.db.flush()  # 确保对象被创建

        metric.segments_generated += 1
        metric.completion_tokens_total += tokens_used // 4  # 估算

        self.db.commit()

    def get_project_stats_summary(self, project_id: str) -> Dict:
        """获取项目统计摘要（供前端展示）"""
        total_segments = self._get_project_segment_count(project_id)

        # 计算节省的输入长度
        if total_segments < 3:
            saved_ratio = 0
            mode = "观察期"
        elif total_segments < 10:
            saved_ratio = 0.1
            mode = "轻量优化"
        else:
            saved_ratio = 0.3
            mode = "智能补全"

        return {
            "total_segments": total_segments,
            "current_mode": mode,
            "input_length_saved": f"{saved_ratio*100:.0f}%",
            "message": self._get_mode_message(total_segments)
        }

    def _get_mode_message(self, count: int) -> str:
        """获取模式说明"""
        if count < self.TRANSPARENT_THRESHOLD:
            return "正在观察您的写作风格，暂不做干预"
        elif count < self.LIGHTWEIGHT_THRESHOLD:
            return "已为您追加历史数据参考，生成更精准"
        else:
            return "已学习您的风格，可以简化输入了"

    # ============================================================
    # 自我进化机制 - OpenSpace AUTO-IMPROVE 启发
    # ============================================================

    def extract_success_patterns(self, project_id: str, min_quality_score: float = None) -> List[Dict]:
        """
        从高质量素材中提取成功模式 (AUTO-IMPROVE)

        实现：
        1. 聚合分析项目的成功素材
        2. 提取共同特征（结构、关键词、节奏等）
        3. 生成可复用的模式模板

        返回：提取的模式列表
        """
        min_score = min_quality_score or self.QUALITY_THRESHOLD_HIGH

        # 获取项目的高质量素材
        materials = self.db.query(ProjectMaterial).filter(
            ProjectMaterial.project_id == project_id,
            ProjectMaterial.quality_score >= min_score,
            ProjectMaterial.status.in_([
                MaterialStatus.APPROVED.value,
                MaterialStatus.AUTO_RECORDED.value
            ])
        ).all()

        if len(materials) < 3:
            return []  # 数据不足，不提取模式

        patterns = []

        # 按段落类型分组分析
        from collections import defaultdict
        by_segment_type = defaultdict(list)
        for m in materials:
            segment_type = self._extract_segment_type(m.material_type)
            if segment_type:
                by_segment_type[segment_type].append(m)

        for segment_type, type_materials in by_segment_type.items():
            if len(type_materials) < 3:
                continue

            # 提取该类型的成功特征
            pattern = self._analyze_type_patterns(segment_type, type_materials)
            if pattern:
                patterns.append(pattern)

        return patterns

    def _extract_segment_type(self, material_type: str) -> Optional[str]:
        """从素材类型提取段落类型"""
        type_mapping = {
            'hook': ['OBSERVED_HOOK', 'USER_IMPROVED_HOOK', 'SUCCESSFUL_HOOK'],
            'validation': ['OBSERVED_VALIDATION', 'USER_IMPROVED_VALIDATION'],
            'explosion': ['OBSERVED_EXPLOSION', 'USER_IMPROVED_EXPLOSION'],
            'resolution': ['OBSERVED_RESOLUTION', 'USER_IMPROVED_RESOLUTION'],
        }
        for seg_type, keywords in type_mapping.items():
            if any(kw in material_type for kw in keywords):
                return seg_type
        return None

    def _analyze_type_patterns(self, segment_type: str, materials: List[ProjectMaterial]) -> Optional[Dict]:
        """分析特定段落类型的成功模式"""
        if not materials:
            return None

        # 计算统计特征
        word_counts = []
        conflict_counts = []

        for m in materials:
            if m.context:
                try:
                    data = json.loads(m.context)
                    word_counts.append(data.get('word_count', len(m.content)))
                    conflict_counts.append(data.get('conflict_count', 0))
                except (json.JSONDecodeError, TypeError):
                    pass

        if not word_counts:
            return None

        avg_words = sum(word_counts) / len(word_counts)
        avg_conflicts = sum(conflict_counts) / len(conflict_counts) if conflict_counts else 0

        # 构建模式定义
        pattern = {
            'segment_type': segment_type,
            'sample_count': len(materials),
            'avg_word_count': avg_words,
            'word_count_range': [min(word_counts), max(word_counts)],
            'avg_conflict_count': avg_conflicts,
            'quality_score_avg': sum(m.quality_score for m in materials) / len(materials),
            'extracted_at': datetime.now().isoformat(),
            'confidence': min(len(materials) / 10, 1.0),  # 样本越多置信度越高
            # 可复用的提示词片段
            'prompt_hint': self._generate_prompt_hint(segment_type, avg_words, avg_conflicts)
        }

        return pattern

    def _generate_prompt_hint(self, segment_type: str, avg_words: float, avg_conflicts: float) -> str:
        """生成可复用的提示词片段"""
        hints = {
            'hook': f"参考本项目历史成功钩子段：平均{avg_words:.0f}字，{'含冲突' if avg_conflicts > 0 else '氛围铺垫为主'}。",
            'validation': f"验证段参考：平均{avg_words:.0f}字，冲突点{avg_conflicts:.1f}个，注意节奏控制。",
            'explosion': f"爆发段参考：平均{avg_words:.0f}字，情绪张力求足。",
            'resolution': f"收尾段参考：平均{avg_words:.0f}字，注意尾钩设计。"
        }
        return hints.get(segment_type, f"{segment_type}段参考：平均{avg_words:.0f}字")

    def generate_optimized_rules(self, project_id: str) -> Optional[str]:
        """
        基于学习数据生成优化后的规则建议

        这是实现"任务越来越轻"的核心：
        - 前期：用户需要写详细规则
        - 中期：系统自动追加参考数据
        - 后期：系统从成功案例中提取规则，用户只需简单提示
        """
        patterns = self.extract_success_patterns(project_id)

        if not patterns:
            return None

        # 生成简化的规则提示
        rule_lines = ["# 基于项目成功案例自动生成的优化规则", ""]

        for p in patterns:
            rule_lines.append(f"## {p['segment_type'].upper()} 段优化规则")
            rule_lines.append(f"- 推荐字数：{p['word_count_range'][0]:.0f}-{p['word_count_range'][1]:.0f}字")
            rule_lines.append(f"- 样本质量：{p['quality_score_avg']:.2f}")
            rule_lines.append(f"- 使用提示：{p['prompt_hint']}")
            rule_lines.append("")

        rule_lines.append("# 使用建议")
        rule_lines.append("由于系统已学习您的成功案例，后续生成可简化输入，")
        rule_lines.append("直接指定段落类型和目标字数即可，系统会自动应用上述模式。")

        return "\n".join(rule_lines)

    def get_evolution_status(self, project_id: str) -> Dict:
        """
        获取项目的自我进化状态

        展示给用户：工作流如何越来越轻
        """
        total_materials = self._get_project_segment_count(project_id)

        # 获取各阶段数据
        approved_count = self.db.query(ProjectMaterial).filter(
            ProjectMaterial.project_id == project_id,
            ProjectMaterial.status == MaterialStatus.APPROVED.value
        ).count()

        patterns_extracted = len(self.extract_success_patterns(project_id))

        # 计算节省的输入量
        input_savings = self._calculate_input_savings(project_id)

        return {
            'project_id': project_id,
            'learning_stage': self._determine_learning_stage(total_materials),
            'total_samples': total_materials,
            'high_quality_samples': approved_count,
            'patterns_extracted': patterns_extracted,
            'input_savings_percent': input_savings,
            'evolution_message': self._get_evolution_message(total_materials, patterns_extracted),
            'next_milestone': self._get_next_milestone(total_materials)
        }

    def _calculate_input_savings(self, project_id: str) -> float:
        """计算输入长度节省百分比"""
        total = self._get_project_segment_count(project_id)

        if total < self.TRANSPARENT_THRESHOLD:
            return 0.0
        elif total < self.LIGHTWEIGHT_THRESHOLD:
            return 0.15  # 15% 节省（参考数据替代部分描述）
        else:
            # 基于模式数量的动态计算
            patterns = self.extract_success_patterns(project_id)
            base_savings = 0.30
            bonus = min(len(patterns) * 0.05, 0.20)  # 每个模式额外5%，最多20%
            return min(base_savings + bonus, 0.60)  # 最高60%节省

    def _determine_learning_stage(self, total_samples: int) -> str:
        """确定学习阶段"""
        if total_samples < self.TRANSPARENT_THRESHOLD:
            return 'observing'
        elif total_samples < self.LIGHTWEIGHT_THRESHOLD:
            return 'learning'
        elif total_samples < 20:
            return 'optimizing'
        else:
            return 'mature'

    def _get_evolution_message(self, total_samples: int, patterns: int) -> str:
        """获取进化状态消息"""
        stage = self._determine_learning_stage(total_samples)

        messages = {
            'observing': '系统正在观察您的写作风格...',
            'learning': f'已学习 {total_samples} 个样本，工作流开始变轻',
            'optimizing': f'已提取 {patterns} 个成功模式，输入可大幅简化',
            'mature': f'系统已深度进化，简单提示即可生成高质量内容'
        }
        return messages.get(stage, '学习中...')

    def _get_next_milestone(self, total_samples: int) -> Dict:
        """获取下一个里程碑信息"""
        milestones = [
            (self.TRANSPARENT_THRESHOLD, '开始轻量优化'),
            (self.LIGHTWEIGHT_THRESHOLD, '智能模式解锁'),
            (20, '模式提取启动'),
            (50, '工作流完全成熟')
        ]

        for threshold, description in milestones:
            if total_samples < threshold:
                return {
                    'samples_needed': threshold - total_samples,
                    'description': description
                }

        return {'samples_needed': 0, 'description': '已达到完全进化'}


# 使用示例
if __name__ == "__main__":
    from app.database import SessionLocal

    db = SessionLocal()
    service = LightweightLearningService(db)

    # 示例1: 新项目，透明模式
    result1 = service.optimize_prompt(
        project_id="new_project",
        user_prompt="请写一个钩子段落，有冲突，250字",
        segment_type="hook",
        episode_no=1
    )
    print(f"模式: {result1.mode}")
    print(f"是否修改: {result1.final_prompt == result1.user_prompt}")

    # 示例2: 有历史的项目，轻量模式
    result2 = service.optimize_prompt(
        project_id="project_with_history",
        user_prompt="请写一个钩子段落，有冲突，250字",
        segment_type="hook",
        episode_no=5
    )
    print(f"\n模式: {result2.mode}")
    print(f"追加前缀: {len(result2.prefix)}字符")
