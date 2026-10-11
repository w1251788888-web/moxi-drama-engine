"""
规则质量控制服务 - 防止规则污染

核心机制：
1. 分层晋升（项目级→类目级→全局级）
2. 效果追踪（A/B测试风格）
3. 自动降级（效果差的规则自动下线）
4. 冲突检测（新规则与现有规则的冲突）
"""
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.rule_quality import (
    RuleLevel, RuleStatus, RuleEffectivenessRecord,
    RulePromotionPath, RuleConflictDetection, GenreRulePool, RuleGuardrail
)
from app.models.rule import Rule
from app.models.project_learning import RuleExtractionJob


class RuleQualityService:
    """规则质量控制服务"""

    def __init__(self, db: Session):
        self.db = db
        self._ensure_guardrails()

    def _ensure_guardrails(self):
        """确保护栏配置存在"""
        guardrail = self.db.query(RuleGuardrail).first()
        if not guardrail:
            guardrail = RuleGuardrail(id=str(uuid.uuid4()))
            self.db.add(guardrail)
            self.db.commit()

    # ============================================
    # 1. 规则分层晋升
    # ============================================

    def evaluate_rule_promotion(self, rule_id: str) -> Dict[str, Any]:
        """
        评估规则是否符合晋升条件
        """
        rule = self.db.query(Rule).get(rule_id)
        if not rule:
            return {"error": "规则不存在"}

        guardrail = self.db.query(RuleGuardrail).first()

        # 获取规则效果统计
        effectiveness = self._get_rule_effectiveness(rule_id)

        # 确定当前层级和下一个目标层级
        current_level = self._get_rule_level(rule)
        target_level = self._get_next_level(current_level)

        if not target_level:
            return {
                "rule_id": rule_id,
                "current_level": current_level,
                "can_promote": False,
                "message": "已是最高层级"
            }

        # 检查晋升条件
        requirements = self._get_promotion_requirements(
            current_level, target_level, guardrail
        )

        meets_requirements = self._check_promotion_requirements(
            effectiveness, requirements
        )

        # 检查冲突
        conflicts = self._detect_conflicts(rule_id, target_level)

        result = {
            "rule_id": rule_id,
            "current_level": current_level,
            "target_level": target_level,
            "can_promote": meets_requirements["passed"] and len(conflicts) == 0,
            "effectiveness": effectiveness,
            "requirements_check": meets_requirements,
            "conflicts": conflicts,
            "requires_approval": self._requires_approval(target_level, guardrail),
            "message": self._generate_promotion_message(
                meets_requirements, conflicts, target_level
            )
        }

        # 如果符合条件，记录晋升路径
        if result["can_promote"]:
            self._record_promotion_path(rule_id, current_level, target_level, requirements)

        return result

    def _get_rule_level(self, rule: Rule) -> str:
        """获取规则当前层级"""
        if rule.scope == "global":
            return RuleLevel.GLOBAL
        elif rule.scope == "task":
            # 检查是否在类目规则池中
            genre_pool = self.db.query(GenreRulePool).filter(
                GenreRulePool.rule_id == rule.id
            ).first()
            if genre_pool:
                return RuleLevel.GENRE
            return RuleLevel.PROJECT
        return RuleLevel.PROJECT

    def _get_next_level(self, current: str) -> Optional[str]:
        """获取下一个目标层级"""
        level_map = {
            RuleLevel.PROJECT: RuleLevel.GENRE,
            RuleLevel.GENRE: RuleLevel.GLOBAL,
            RuleLevel.GLOBAL: None
        }
        return level_map.get(current)

    def _get_rule_effectiveness(self, rule_id: str, days: int = 30) -> Dict:
        """获取规则效果统计"""
        cutoff = datetime.now() - timedelta(days=days)

        records = self.db.query(RuleEffectivenessRecord).filter(
            RuleEffectivenessRecord.rule_id == rule_id,
            RuleEffectivenessRecord.date >= cutoff
        ).all()

        if not records:
            return {
                "total_applications": 0,
                "success_rate": 0.0,
                "avg_validation_score": 0.0,
                "user_override_rate": 0.0
            }

        total_apps = sum(r.applications_count for r in records)
        total_success = sum(r.success_count for r in records)
        total_overrides = sum(r.user_override_count for r in records)

        return {
            "total_applications": total_apps,
            "success_rate": total_success / total_apps if total_apps > 0 else 0.0,
            "avg_validation_score": sum(r.avg_validation_score for r in records) / len(records),
            "user_override_rate": total_overrides / total_apps if total_apps > 0 else 0.0,
            "unique_projects": len(set(r.project_id for r in records if r.project_id))
        }

    def _get_promotion_requirements(
        self,
        current: str,
        target: str,
        guardrail: RuleGuardrail
    ) -> Dict:
        """获取晋升条件"""
        if current == RuleLevel.PROJECT and target == RuleLevel.GENRE:
            return {
                "min_usage": guardrail.project_to_genre_min_usage,
                "min_success_rate": guardrail.project_to_genre_min_success_rate,
                "min_confidence": guardrail.project_to_genre_min_confidence
            }
        elif current == RuleLevel.GENRE and target == RuleLevel.GLOBAL:
            return {
                "min_usage": guardrail.genre_to_global_min_usage,
                "min_success_rate": guardrail.genre_to_global_min_success_rate,
                "min_projects": guardrail.genre_to_global_min_projects
            }
        return {}

    def _check_promotion_requirements(
        self,
        effectiveness: Dict,
        requirements: Dict
    ) -> Dict:
        """检查是否满足晋升条件"""
        checks = []

        if "min_usage" in requirements:
            passed = effectiveness["total_applications"] >= requirements["min_usage"]
            checks.append({
                "requirement": f"最少使用{requirements['min_usage']}次",
                "actual": effectiveness["total_applications"],
                "passed": passed
            })

        if "min_success_rate" in requirements:
            passed = effectiveness["success_rate"] >= requirements["min_success_rate"]
            checks.append({
                "requirement": f"最低成功率{requirements['min_success_rate']:.0%}",
                "actual": f"{effectiveness['success_rate']:.1%}",
                "passed": passed
            })

        if "min_projects" in requirements:
            passed = effectiveness["unique_projects"] >= requirements["min_projects"]
            checks.append({
                "requirement": f"至少{requirements['min_projects']}个项目验证",
                "actual": effectiveness["unique_projects"],
                "passed": passed
            })

        return {
            "checks": checks,
            "passed": all(c["passed"] for c in checks)
        }

    def _requires_approval(self, target_level: str, guardrail: RuleGuardrail) -> bool:
        """检查是否需要人工审核"""
        if target_level == RuleLevel.GENRE:
            return bool(guardrail.require_approval_for_genre)
        elif target_level == RuleLevel.GLOBAL:
            return bool(guardrail.require_approval_for_global)
        return False

    def _detect_conflicts(self, rule_id: str, target_level: str) -> List[Dict]:
        """检测规则冲突"""
        rule = self.db.query(Rule).get(rule_id)
        if not rule:
            return []

        conflicts = []

        # 获取同层级的其他规则
        if target_level == RuleLevel.GENRE:
            # 检查同类目的其他规则
            genre_pools = self.db.query(GenreRulePool).filter(
                GenreRulePool.rule_id != rule_id,
                GenreRulePool.status == "active"
            ).all()
            existing_rule_ids = [p.rule_id for p in genre_pools]
        elif target_level == RuleLevel.GLOBAL:
            existing_rule_ids = [r.id for r in self.db.query(Rule).filter(
                Rule.scope == "global",
                Rule.status == "active"
            ).all()]
        else:
            existing_rule_ids = []

        # 简单的关键词重叠检测
        rule_keywords = self._extract_keywords(rule.content)

        for existing_id in existing_rule_ids:
            existing = self.db.query(Rule).get(existing_id)
            if not existing:
                continue

            existing_keywords = self._extract_keywords(existing.content)
            overlap = set(rule_keywords) & set(existing_keywords)

            if len(overlap) > 3:  # 如果有3个以上关键词重叠
                conflict = RuleConflictDetection(
                    id=str(uuid.uuid4()),
                    new_rule_id=rule_id,
                    existing_rule_id=existing_id,
                    conflict_type="overlap",
                    conflict_description=f"与现有规则 {existing_id} 有{len(overlap)}个关键词重叠",
                    conflicting_keywords=list(overlap),
                    severity="medium"
                )
                self.db.add(conflict)
                conflicts.append({
                    "existing_rule_id": existing_id,
                    "type": "overlap",
                    "keywords": list(overlap)
                })

        self.db.commit()
        return conflicts

    def _extract_keywords(self, content: str) -> List[str]:
        """提取关键词（简化版）"""
        # 可以使用更复杂的NLP方法
        important_words = [
            "钩子", "冲突", "情绪", "对话", "节奏",
            "人物", "场景", "悬念", "转折", "高潮"
        ]
        return [w for w in important_words if w in content]

    def _record_promotion_path(
        self,
        rule_id: str,
        current: str,
        target: str,
        requirements: Dict
    ):
        """记录晋升路径"""
        path = RulePromotionPath(
            id=str(uuid.uuid4()),
            rule_id=rule_id,
            current_level=current,
            target_level=target,
            requirements=requirements,
            status="ready"
        )
        self.db.add(path)
        self.db.commit()

    def _generate_promotion_message(
        self,
        meets_requirements: Dict,
        conflicts: List,
        target_level: str
    ) -> str:
        """生成晋升消息"""
        if not meets_requirements["passed"]:
            failed = [c for c in meets_requirements["checks"] if not c["passed"]]
            return f"未满足晋升条件: {', '.join(f['requirement'] for f in failed)}"

        if conflicts:
            return f"符合晋升条件，但存在{len(conflicts)}个冲突需要解决"

        return f"符合{target_level}层级的晋升条件"

    # ============================================
    # 2. 规则效果追踪
    # ============================================

    def record_rule_application(
        self,
        rule_id: str,
        project_id: str,
        segment_type: str,
        success: bool,
        validation_score: float,
        user_override: bool = False,
        tokens_used: int = 0
    ):
        """
        记录规则应用效果
        """
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        record = self.db.query(RuleEffectivenessRecord).filter(
            RuleEffectivenessRecord.rule_id == rule_id,
            RuleEffectivenessRecord.project_id == project_id,
            RuleEffectivenessRecord.segment_type == segment_type,
            RuleEffectivenessRecord.date == today
        ).first()

        if not record:
            record = RuleEffectivenessRecord(
                id=str(uuid.uuid4()),
                rule_id=rule_id,
                project_id=project_id,
                segment_type=segment_type,
                date=today
            )
            self.db.add(record)

        record.applications_count += 1
        if success:
            record.success_count += 1
        else:
            record.failure_count += 1

        if user_override:
            record.user_override_count += 1

        # 更新平均验证分数（移动平均）
        if record.applications_count == 1:
            record.avg_validation_score = validation_score
        else:
            record.avg_validation_score = (
                record.avg_validation_score * (record.applications_count - 1) + validation_score
            ) / record.applications_count

        self.db.commit()

        # 检查是否需要降级
        self._check_degradation(rule_id)

    # ============================================
    # 3. 自动降级机制
    # ============================================

    def _check_degradation(self, rule_id: str):
        """
        检查规则是否需要降级"""
        guardrail = self.db.query(RuleGuardrail).first()
        effectiveness = self._get_rule_effectiveness(rule_id, days=14)

        # 检查是否触发降级条件
        should_degrade = False
        reason = ""

        # 条件1: 成功率过低
        if effectiveness["total_applications"] >= guardrail.degrade_min_samples:
            if effectiveness["success_rate"] < guardrail.degrade_threshold_success_rate:
                should_degrade = True
                reason = f"成功率{effectiveness['success_rate']:.1%}低于阈值{guardrail.degrade_threshold_success_rate:.0%}"

            # 条件2: 用户覆盖次数过多
            if effectiveness["user_override_rate"] > 0.3:  # 被覆盖率超过30%
                should_degrade = True
                reason += f"; 用户覆盖率{effectiveness['user_override_rate']:.1%}"

        if should_degrade:
            self._degrade_rule(rule_id, reason)

    def _degrade_rule(self, rule_id: str, reason: str):
        """降级规则"""
        rule = self.db.query(Rule).get(rule_id)
        if not rule:
            return

        # 只降级非项目级规则
        current_level = self._get_rule_level(rule)
        if current_level == RuleLevel.PROJECT:
            return  # 项目级规则直接禁用而不是降级

        # 更新规则状态
        rule.status = RuleStatus.DEGRADED

        # 记录降级
        if current_level == RuleLevel.GENRE:
            # 从类目规则池中暂停
            pool = self.db.query(GenreRulePool).filter(
                GenreRulePool.rule_id == rule_id
            ).first()
            if pool:
                pool.status = "suspended"

        self.db.commit()

        print(f"[规则降级] 规则{rule_id} 已降级: {reason}")

    def approve_promotion(self, path_id: str, approved: bool, approved_by: str) -> Dict:
        """
        人工审核规则晋升
        """
        path = self.db.query(RulePromotionPath).get(path_id)
        if not path:
            return {"error": "晋升路径不存在"}

        rule = self.db.query(Rule).get(path.rule_id)
        if not rule:
            return {"error": "规则不存在"}

        if approved:
            # 执行晋升
            if path.target_level == RuleLevel.GENRE:
                # 晋升到类目级
                self._promote_to_genre(rule)
            elif path.target_level == RuleLevel.GLOBAL:
                # 晋升到全局级
                rule.scope = "global"

            path.status = "promoted"
            path.promoted_at = datetime.now()
            path.promoted_by = approved_by
            message = f"规则已晋升到{path.target_level}层级"
        else:
            path.status = "rejected"
            path.rejection_reason = "人工审核未通过"
            message = "晋升已被拒绝"

        self.db.commit()

        return {
            "success": True,
            "rule_id": rule.id,
            "target_level": path.target_level,
            "status": path.status,
            "message": message
        }

    def _promote_to_genre(self, rule: Rule):
        """将规则晋升到类目级"""
        # 获取项目的类目信息
        # 这里需要根据实际业务获取，暂时使用默认值
        genre_main = "男频逆袭"
        genre_sub = "校园系统"

        # 创建类目规则池记录
        pool = GenreRulePool(
            id=str(uuid.uuid4()),
            genre_main=genre_main,
            genre_sub=genre_sub,
            rule_id=rule.id,
            contributing_projects=[rule.task_id] if rule.task_id else []
        )
        self.db.add(pool)

    # ============================================
    # 4. 冲突解决
    # ============================================

    def resolve_conflict(
        self,
        conflict_id: str,
        resolution: str,  # merge/replace/exclude
        resolved_by: str
    ) -> Dict:
        """
        解决规则冲突
        """
        conflict = self.db.query(RuleConflictDetection).get(conflict_id)
        if not conflict:
            return {"error": "冲突记录不存在"}

        if resolution == "exclude":
            # 不接受新规则
            new_rule = self.db.query(Rule).get(conflict.new_rule_id)
            if new_rule:
                new_rule.status = RuleStatus.ARCHIVED

        elif resolution == "replace":
            # 用新规则替换旧规则
            old_rule = self.db.query(Rule).get(conflict.existing_rule_id)
            if old_rule:
                old_rule.status = RuleStatus.ARCHIVED

        elif resolution == "merge":
            # 合并两个规则（简化处理）
            pass

        conflict.status = "resolved"
        conflict.resolution = resolution
        conflict.resolved_by = resolved_by
        conflict.resolved_at = datetime.now()

        self.db.commit()

        return {
            "success": True,
            "conflict_id": conflict_id,
            "resolution": resolution
        }

    # ============================================
    # 5. 查询与报告
    # ============================================

    def get_rule_quality_report(self, rule_id: str) -> Dict:
        """
        获取规则质量报告
        """
        rule = self.db.query(Rule).get(rule_id)
        if not rule:
            return {"error": "规则不存在"}

        effectiveness = self._get_rule_effectiveness(rule_id)

        # 获取晋升状态
        promotion_path = self.db.query(RulePromotionPath).filter(
            RulePromotionPath.rule_id == rule_id
        ).order_by(RulePromotionPath.created_at.desc()).first()

        # 获取冲突
        conflicts = self.db.query(RuleConflictDetection).filter(
            RuleConflictDetection.new_rule_id == rule_id,
            RuleConflictDetection.status == "pending"
        ).all()

        return {
            "rule_id": rule_id,
            "current_level": self._get_rule_level(rule),
            "status": rule.status,
            "effectiveness": effectiveness,
            "promotion_status": {
                "target_level": promotion_path.target_level if promotion_path else None,
                "status": promotion_path.status if promotion_path else None,
                "can_promote": promotion_path.status == "ready" if promotion_path else False
            } if promotion_path else None,
            "pending_conflicts": [
                {
                    "conflict_id": c.id,
                    "type": c.conflict_type,
                    "severity": c.severity,
                    "description": c.conflict_description
                }
                for c in conflicts
            ]
        }

    def get_pending_promotions(self, level: Optional[str] = None) -> List[Dict]:
        """
        获取待审核的晋升请求
        """
        query = self.db.query(RulePromotionPath).filter(
            RulePromotionPath.status == "ready"
        )

        if level:
            query = query.filter(RulePromotionPath.target_level == level)

        paths = query.all()

        return [
            {
                "path_id": p.id,
                "rule_id": p.rule_id,
                "current_level": p.current_level,
                "target_level": p.target_level,
                "requirements": p.requirements
            }
            for p in paths
        ]

    def get_degraded_rules(self, days: int = 7) -> List[Dict]:
        """
        获取最近降级的规则
        """
        cutoff = datetime.now() - timedelta(days=days)

        rules = self.db.query(Rule).filter(
            Rule.status == RuleStatus.DEGRADED,
            Rule.updated_at >= cutoff
        ).all()

        return [
            {
                "rule_id": r.id,
                "scope": r.scope,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None
            }
            for r in rules
        ]
