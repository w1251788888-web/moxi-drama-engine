"""剧集段落任务拆分模型

实现superpowers的2-5分钟任务拆分原则：
每集剧本拆分为4个段落（钩子/验证/爆发/收尾），每段约300字，5分钟内可完成

支持红-绿-重构循环：
- 红：定义验收标准（测试用例）
- 绿：生成内容并通过验证
- 重构：如果验证失败，局部重写
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, Index, Float
from sqlalchemy.orm import relationship

from app.database import Base


class EpisodeSegment(Base):
    """剧集段落

    每集剧本拆分为4个段落：
    1. hook - 钩子段（开局吸引，建立悬念）
    2. validation - 验证段（主角行动，验证实力）
    3. explosion - 爆发段（高潮冲突，情绪顶点）
    4. resolution - 收尾段（悬念收尾，钩子预告）

    每个段落独立生成、独立评审、独立版本控制
    遵循红-绿-重构循环
    """
    __tablename__ = "episode_segments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("task.id"), nullable=False, index=True)

    # 所属步骤（目前仅script_draft支持拆分）
    step_id = Column(String(32), nullable=False, default="script_draft")

    # 集数
    episode_no = Column(Integer, nullable=False)

    # 段落类型
    segment_type = Column(String(16), nullable=False)  # hook/validation/explosion/resolution

    # 段落顺序（用于排序）
    sequence = Column(Integer, default=0)

    # 内容（生成的剧本段落）
    content = Column(Text, default="")

    # 预估字数（用于验证）
    target_word_count = Column(Integer, default=300)
    actual_word_count = Column(Integer, default=0)

    # 状态：pending/red(待生成)/green(通过)/refactor(需重构)/done(完成)
    status = Column(String(16), default="pending")

    # 所属版本（关联StepVersion）
    version_id = Column(String(36), nullable=True)

    # 验收标准（JSON：定义"红"状态）
    acceptance_criteria = Column(Text, default="[]")
    # e.g., [{"check": "字数300±50", "weight": 0.3}, {"check": "含主角台词", "weight": 0.4}]

    # 验证结果（JSON：记录是否通过"绿"状态）
    validation_results = Column(Text, default="[]")
    # e.g., [{"criterion": "字数", "passed": true, "score": 0.9}]

    # 验证总分
    validation_score = Column(Float, default=0.0)

    # 重构次数（防止无限循环）
    refactor_count = Column(Integer, default=0)
    max_refactors = Column(Integer, default=3)

    # 关联的评审记录IDs（JSON数组）
    review_ids = Column(Text, default="[]")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_episode_segments_session_episode", "session_id", "episode_no"),
        Index("ix_episode_segments_type", "session_id", "step_id", "segment_type"),
        Index("ix_episode_segments_status", "session_id", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "step_id": self.step_id,
            "episode_no": self.episode_no,
            "segment_type": self.segment_type,
            "sequence": self.sequence,
            "content": self.content,
            "target_word_count": self.target_word_count,
            "actual_word_count": self.actual_word_count,
            "status": self.status,
            "version_id": self.version_id,
            "acceptance_criteria": json.loads(self.acceptance_criteria or "[]"),
            "validation_results": json.loads(self.validation_results or "[]"),
            "validation_score": self.validation_score,
            "refactor_count": self.refactor_count,
            "max_refactors": self.max_refactors,
            "review_ids": json.loads(self.review_ids or "[]"),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def compute_word_count(self) -> int:
        """计算实际字数"""
        import re
        if not self.content:
            return 0
        # 只计算中文字符和英文单词
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', self.content))
        english_words = len(re.findall(r'[a-zA-Z]+', self.content))
        return chinese_chars + english_words

    def update_word_count(self):
        """更新字数统计"""
        self.actual_word_count = self.compute_word_count()

    def validate(self) -> dict:
        """运行验证（红-绿循环中的"测试"阶段）"""
        results = []
        total_weight = 0
        weighted_score = 0

        criteria = json.loads(self.acceptance_criteria or "[]")
        if not criteria:
            # 默认验收标准
            criteria = [
                {"check": "字数", "min": self.target_word_count - 50, "max": self.target_word_count + 50, "weight": 0.3},
                {"check": "主角出现", "required": True, "weight": 0.3},
                {"check": "冲突存在", "required": True, "weight": 0.4},
            ]

        for criterion in criteria:
            result = {"criterion": criterion.get("check", "unknown"), "passed": False, "score": 0.0}
            weight = criterion.get("weight", 0.1)

            if criterion.get("check") == "字数":
                min_words = criterion.get("min", self.target_word_count - 50)
                max_words = criterion.get("max", self.target_word_count + 50)
                if min_words <= self.actual_word_count <= max_words:
                    result["passed"] = True
                    result["score"] = 1.0
                else:
                    # 线性扣分
                    deviation = abs(self.actual_word_count - self.target_word_count)
                    result["score"] = max(0, 1.0 - deviation / self.target_word_count)

            elif criterion.get("check") in ["主角出现", "冲突存在", "含主角台词"]:
                # 简单检查：内容中是否包含关键词
                keywords = criterion.get("keywords", [])
                if keywords:
                    found = sum(1 for kw in keywords if kw in self.content)
                    result["score"] = min(1.0, found / max(1, len(keywords) * 0.5))
                    result["passed"] = result["score"] >= 0.5 and criterion.get("required", False)
                else:
                    # 默认通过（需要更复杂的NLP检查）
                    result["passed"] = len(self.content) > 100
                    result["score"] = 0.7

            results.append(result)
            total_weight += weight
            weighted_score += result["score"] * weight

        self.validation_results = json.dumps(results)
        self.validation_score = weighted_score / total_weight if total_weight > 0 else 0.0

        # 判断是否通过（绿状态）
        passed = all(r["passed"] for r in results if r.get("required", True))

        return {
            "passed": passed,
            "score": self.validation_score,
            "results": results,
        }

    def can_refactor(self) -> bool:
        """检查是否还可以重构"""
        return self.refactor_count < self.max_refactors

    def mark_for_refactor(self, reason: str = ""):
        """标记需要重构（红状态）"""
        self.status = "refactor"
        self.refactor_count += 1

    def mark_complete(self):
        """标记完成（绿状态确认）"""
        self.status = "done"
        self.completed_at = datetime.utcnow()


class SegmentReview(Base):
    """段落实时评审

    支持阻塞式评审：不通过则不能进入下一段
    """
    __tablename__ = "segment_reviews"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    segment_id = Column(String(36), ForeignKey("episode_segments.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("task.id"), nullable=False, index=True)

    # 评审结果：pass/block/request_changes
    verdict = Column(String(16), nullable=False)

    # 是否阻塞（block会阻止进入下一段）
    is_blocking = Column(Integer, default=1)  # 0=false, 1=true

    # 评审意见
    comments = Column(Text, default="")

    # 具体问题
    issues = Column(Text, default="[]")

    # 建议的修正提示
    rewrite_suggestion = Column(Text, default="")

    # 评分（可选）
    score = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_by = Column(String(16), default="ai")  # ai/user/system

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "segment_id": self.segment_id,
            "session_id": self.session_id,
            "verdict": self.verdict,
            "is_blocking": bool(self.is_blocking),
            "comments": self.comments,
            "issues": json.loads(self.issues or "[]"),
            "rewrite_suggestion": self.rewrite_suggestion,
            "score": self.score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_by": self.reviewed_by,
        }


class StepGate(Base):
    """步骤质量门

    实现阻塞式质量门：评审不通过不能进入下一步
    类似gstack的/review → /ship流程
    """
    __tablename__ = "step_gates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("task.id"), nullable=False, index=True)
    step_id = Column(String(32), nullable=False)

    # 质量门状态：open/passed/failed/bypassed
    status = Column(String(16), default="open")

    # 通过所需的最低评分
    min_score = Column(Float, default=0.7)

    # 实际评分
    actual_score = Column(Float, nullable=True)

    # 检查项（JSON）
    check_items = Column(Text, default="[]")
    # e.g., [{"item": "角色完整度", "required": true}, {"item": "字数达标", "required": true}]

    # 检查结果
    check_results = Column(Text, default="[]")

    # 评审意见汇总
    summary = Column(Text, default="")

    # 谁通过了质量门
    passed_by = Column(String(16), nullable=True)
    passed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_step_gates_session_step", "session_id", "step_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "step_id": self.step_id,
            "status": self.status,
            "min_score": self.min_score,
            "actual_score": self.actual_score,
            "check_items": json.loads(self.check_items or "[]"),
            "check_results": json.loads(self.check_results or "[]"),
            "summary": self.summary,
            "passed_by": self.passed_by,
            "passed_at": self.passed_at.isoformat() if self.passed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def can_pass(self) -> tuple[bool, str]:
        """检查是否可以通过质量门"""
        if self.status == "passed":
            return True, "已通过"

        if self.status == "bypassed":
            return True, "已绕过"

        if self.actual_score is None:
            return False, "尚未评分"

        if self.actual_score < self.min_score:
            return False, f"评分不足：{self.actual_score:.2f} < {self.min_score}"

        # 检查必须项
        results = json.loads(self.check_results or "[]")
        items = json.loads(self.check_items or "[]")

        for item in items:
            if item.get("required", False):
                result = next((r for r in results if r.get("item") == item["item"]), None)
                if not result or not result.get("passed", False):
                    return False, f"未通过检查项：{item['item']}"

        return True, "可以通行"

    def pass_gate(self, by: str = "user"):
        """通过质量门"""
        can_pass, reason = self.can_pass()
        if not can_pass:
            raise ValueError(f"不能通过质量门：{reason}")

        self.status = "passed"
        self.passed_by = by
        self.passed_at = datetime.utcnow()

    def fail_gate(self, reason: str = ""):
        """质量门失败"""
        self.status = "failed"
        self.summary = reason

    def bypass(self, by: str = "user", reason: str = ""):
        """绕过质量门（管理员权限）"""
        self.status = "bypassed"
        self.passed_by = by
        self.passed_at = datetime.utcnow()
        self.summary = f"绕过原因：{reason}"
