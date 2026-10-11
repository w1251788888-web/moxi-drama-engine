"""步骤版本管理服务

实现版本树的创建、查询、切换、对比等核心功能。
遵循gstack的Git-like版本管理理念。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal, Optional

from sqlalchemy.orm import Session

from app.models.step_version import StepVersion, StepDependency, DynamicRule, StepReview
from app.models.task import Task


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _parse_version_number(vn: str) -> tuple[int, int]:
    """解析版本号 v1.2 -> (1, 2)"""
    match = re.match(r"v(\d+)\.(\d+)", vn)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 1, 0


def _increment_version(vn: str, major: bool = False) -> str:
    """递增版本号"""
    major_ver, minor_ver = _parse_version_number(vn)
    if major:
        return f"v{major_ver + 1}.0"
    else:
        return f"v{major_ver}.{minor_ver + 1}"


class StepVersionService:
    """步骤版本管理服务"""

    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────────────────────
    # 版本管理
    # ─────────────────────────────────────────────────────────

    def get_version_tree(self, session_id: str, step_id: str) -> list[dict]:
        """获取步骤的版本树"""
        versions = (
            self.db.query(StepVersion)
            .filter_by(session_id=session_id, step_id=step_id)
            .order_by(StepVersion.created_at.asc())
            .all()
        )
        return [v.to_dict() for v in versions]

    def get_current_version(self, session_id: str, step_id: str) -> Optional[StepVersion]:
        """获取当前激活的版本"""
        return (
            self.db.query(StepVersion)
            .filter_by(session_id=session_id, step_id=step_id, is_current=1)
            .first()
        )

    def create_version(
        self,
        session_id: str,
        step_id: str,
        context_output: str,
        full_output: str,
        change_type: Literal["ai_generated", "manual_edit", "merged", "forked"],
        change_log: str = "",
        prompt_file: str = "",
        input_summary: str = "",
        base_version_id: Optional[str] = None,
        created_by: str = "ai",
    ) -> StepVersion:
        """创建新版本

        Args:
            base_version_id: 基于哪个版本创建（None表示从当前版本升级）
        """
        # 确定版本号
        if base_version_id:
            base = self.db.query(StepVersion).filter_by(id=base_version_id).first()
            if base:
                parent_id = base.id
                is_fork = change_type == "forked"
                version_number = _increment_version(base.version_number, major=is_fork)
            else:
                parent_id = None
                version_number = "v1.0"
        else:
            current = self.get_current_version(session_id, step_id)
            if current:
                parent_id = current.id
                version_number = _increment_version(current.version_number, major=False)
            else:
                parent_id = None
                version_number = "v1.0"

        # 取消当前版本的激活状态
        self.db.query(StepVersion).filter_by(
            session_id=session_id, step_id=step_id, is_current=1
        ).update({"is_current": 0})

        # 创建新版本
        version = StepVersion(
            session_id=session_id,
            step_id=step_id,
            version_number=version_number,
            parent_version_id=parent_id,
            content_hash=StepVersion.compute_content_hash(context_output, full_output),
            context_output=context_output,
            full_output=full_output,
            change_type=change_type,
            change_log=change_log,
            prompt_file=prompt_file,
            input_summary=input_summary,
            is_current=1,
            created_by=created_by,
        )
        self.db.add(version)
        self.db.flush()

        # 检查并创建依赖关系
        self._check_downstream_dependencies(session_id, step_id, version.id)

        return version

    def switch_version(self, session_id: str, step_id: str, version_id: str) -> StepVersion:
        """切换到指定版本"""
        # 取消当前版本
        self.db.query(StepVersion).filter_by(
            session_id=session_id, step_id=step_id, is_current=1
        ).update({"is_current": 0})

        # 激活目标版本
        target = (
            self.db.query(StepVersion)
            .filter_by(id=version_id, session_id=session_id, step_id=step_id)
            .first()
        )
        if not target:
            raise ValueError(f"版本不存在: {version_id}")

        target.is_current = 1
        self.db.flush()

        # 更新依赖状态
        self._check_downstream_dependencies(session_id, step_id, version_id)

        return target

    def diff_versions(self, left_id: str, right_id: str) -> dict:
        """对比两个版本的差异"""
        left = self.db.query(StepVersion).filter_by(id=left_id).first()
        right = self.db.query(StepVersion).filter_by(id=right_id).first()

        if not left or not right:
            raise ValueError("版本不存在")

        # 简单的文本对比
        left_lines = (left.full_output or "").split("\n")
        right_lines = (right.full_output or "").split("\n")

        # 使用简单差异算法
        diff_result = []
        max_len = max(len(left_lines), len(right_lines))

        for i in range(max_len):
            left_line = left_lines[i] if i < len(left_lines) else None
            right_line = right_lines[i] if i < len(right_lines) else None

            if left_line is None:
                diff_result.append({"type": "add", "line": i + 1, "content": right_line})
            elif right_line is None:
                diff_result.append({"type": "remove", "line": i + 1, "content": left_line})
            elif left_line != right_line:
                diff_result.append({
                    "type": "change",
                    "line": i + 1,
                    "left": left_line,
                    "right": right_line,
                })

        return {
            "left": left.to_dict(),
            "right": right.to_dict(),
            "diff": diff_result,
            "stats": {
                "added": sum(1 for d in diff_result if d["type"] == "add"),
                "removed": sum(1 for d in diff_result if d["type"] == "remove"),
                "changed": sum(1 for d in diff_result if d["type"] == "change"),
            },
        }

    # ─────────────────────────────────────────────────────────
    # 依赖管理
    # ─────────────────────────────────────────────────────────

    def _check_downstream_dependencies(self, session_id: str, upstream_step: str, upstream_version_id: str):
        """检查下游依赖并标记需要同步的步骤"""
        # 定义步骤顺序
        step_order = [
            "project_init_check",
            "novel_analysis",
            "character_lock",
            "market_check",
            "concept",
            "characters",
            "beat_sheet",
            "scene_list",
            "script_draft",
            "quality_check",
            "compliance_check",
            "storyboard",
        ]

        if upstream_step not in step_order:
            return

        upstream_idx = step_order.index(upstream_step)
        downstream_steps = step_order[upstream_idx + 1 :]

        for down_step in downstream_steps:
            # 检查下游步骤是否有已完成的版本
            down_versions = (
                self.db.query(StepVersion)
                .filter_by(session_id=session_id, step_id=down_step)
                .all()
            )

            for down_ver in down_versions:
                # 创建或更新依赖关系
                dep = (
                    self.db.query(StepDependency)
                    .filter_by(
                        session_id=session_id,
                        upstream_step=upstream_step,
                        downstream_step=down_step,
                        downstream_version_id=down_ver.id,
                    )
                    .first()
                )

                if not dep:
                    dep = StepDependency(
                        session_id=session_id,
                        upstream_step=upstream_step,
                        upstream_version_id=upstream_version_id,
                        downstream_step=down_step,
                        downstream_version_id=down_ver.id,
                        dependency_type="hard",
                        sync_status="pending",
                    )
                    self.db.add(dep)
                else:
                    dep.sync_status = "pending"
                    dep.upstream_version_id = upstream_version_id

                # 生成同步建议
                dep.sync_suggestion = self._generate_sync_suggestion(
                    upstream_step, down_step
                )

        self.db.flush()

    def _generate_sync_suggestion(self, upstream: str, downstream: str) -> str:
        """生成同步建议"""
        suggestions = {
            ("characters", "beat_sheet"): "角色变更可能影响节拍表中的角色出场安排",
            ("characters", "script_draft"): "角色变更需要同步到剧本正文",
            ("beat_sheet", "scene_list"): "节拍表变更需要更新分场表",
            ("beat_sheet", "script_draft"): "节拍表变更需要同步到剧本正文",
            ("scene_list", "script_draft"): "分场表变更需要同步到剧本正文",
            ("script_draft", "storyboard"): "剧本正文变更需要更新分镜",
        }
        return suggestions.get((upstream, downstream), f"{upstream} 变更可能影响 {downstream}")

    def get_dependency_status(self, session_id: str) -> list[dict]:
        """获取会话的依赖状态"""
        deps = (
            self.db.query(StepDependency)
            .filter_by(session_id=session_id)
            .order_by(StepDependency.updated_at.desc())
            .all()
        )
        return [d.to_dict() for d in deps]

    def sync_downstream(
        self,
        session_id: str,
        upstream_step: str,
        strategy: Literal["smart", "full", "manual"],
    ) -> dict:
        """同步下游步骤"""
        pending_deps = (
            self.db.query(StepDependency)
            .filter_by(session_id=session_id, upstream_step=upstream_step, sync_status="pending")
            .all()
        )

        synced = []
        for dep in pending_deps:
            if strategy == "smart":
                # 智能同步：只更新受影响的部分
                # TODO: 实现智能同步逻辑
                pass
            elif strategy == "full":
                # 完全重新生成
                pass

            dep.sync_status = "synced"
            synced.append(dep.downstream_step)

        self.db.flush()
        return {"synced_steps": list(set(synced)), "strategy": strategy}

    # ─────────────────────────────────────────────────────────
    # 动态规则
    # ─────────────────────────────────────────────────────────

    def add_dynamic_rule(
        self,
        content: str,
        scope: Literal["global", "project", "step", "once"],
        session_id: Optional[str] = None,
        target_step: Optional[str] = None,
        target_episode: Optional[int] = None,
        apply_timing: Literal["immediate", "next_generation"] = "next_generation",
        created_by: str = "user",
    ) -> DynamicRule:
        """添加动态规则"""
        rule = DynamicRule(
            session_id=session_id,
            content=content,
            scope=scope,
            target_step=target_step,
            target_episode=target_episode,
            apply_timing=apply_timing,
            created_by=created_by,
        )
        self.db.add(rule)
        self.db.flush()
        return rule

    def get_active_rules(
        self,
        session_id: Optional[str] = None,
        step_id: Optional[str] = None,
        episode: Optional[int] = None,
    ) -> list[DynamicRule]:
        """获取生效中的规则"""
        query = self.db.query(DynamicRule).filter_by(is_active=1)

        if session_id:
            # global规则 + 当前会话规则
            query = query.filter(
                (DynamicRule.session_id == None) | (DynamicRule.session_id == session_id)
            )

            if step_id:
                # step规则和project规则
                query = query.filter(
                    (DynamicRule.scope.in_(["global", "project"]))
                    | ((DynamicRule.scope == "step") & (DynamicRule.target_step == step_id))
                    | ((DynamicRule.scope == "once") & (DynamicRule.target_step == step_id))
                )

        return query.all()

    def get_rules_for_generation(
        self,
        session_id: str,
        step_id: str,
        episode: Optional[int] = None,
    ) -> list[dict]:
        """获取用于生成的规则列表（自动标记已应用）"""
        rules = self.get_active_rules(session_id, step_id, episode)
        result = []

        for rule in rules:
            # 跳过已应用的一次性规则
            if rule.scope == "once":
                applied = json.loads(rule.applied_version_ids or "[]")
                # 检查当前版本是否已应用
                current = self.get_current_version(session_id, step_id)
                if current and current.id in applied:
                    continue

            result.append(rule.to_dict())

        return result

    def mark_rule_applied(self, rule_id: str, version_id: str):
        """标记规则已应用到指定版本"""
        rule = self.db.query(DynamicRule).filter_by(id=rule_id).first()
        if rule:
            rule.mark_applied(version_id)
            # 一次性规则应用后自动失效
            if rule.scope == "once":
                rule.is_active = 0
            self.db.flush()

    # ─────────────────────────────────────────────────────────
    # 评审循环
    # ─────────────────────────────────────────────────────────

    def create_review(
        self,
        version_id: str,
        session_id: str,
        verdict: Literal["pass", "needs_fix", "reject"],
        comments: str = "",
        issues: list[dict] = None,
        rewrite_hint: str = "",
        review_type: Literal["auto", "manual"] = "auto",
        reviewed_by: str = "ai",
        score: Optional[int] = None,
    ) -> StepReview:
        """创建评审记录"""
        review = StepReview(
            version_id=version_id,
            session_id=session_id,
            review_type=review_type,
            verdict=verdict,
            score=score,
            comments=comments,
            issues=json.dumps(issues or []),
            rewrite_hint=rewrite_hint,
            reviewed_by=reviewed_by,
        )
        self.db.add(review)
        self.db.flush()
        return review

    def get_reviews_for_version(self, version_id: str) -> list[StepReview]:
        """获取版本的所有评审记录"""
        return (
            self.db.query(StepReview)
            .filter_by(version_id=version_id)
            .order_by(StepReview.created_at.desc())
            .all()
        )

    def get_latest_review(self, version_id: str) -> Optional[StepReview]:
        """获取最新评审记录"""
        return (
            self.db.query(StepReview)
            .filter_by(version_id=version_id)
            .order_by(StepReview.created_at.desc())
            .first()
        )

    def needs_rewrite(self, version_id: str) -> tuple[bool, str]:
        """检查是否需要重写"""
        latest = self.get_latest_review(version_id)
        if not latest:
            return False, ""
        if latest.verdict in ["needs_fix", "reject"]:
            return True, latest.rewrite_hint
        return False, ""
