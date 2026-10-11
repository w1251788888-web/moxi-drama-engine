"""
规则提示词业务逻辑 — 含三级合并与变量替换
"""
import uuid
from sqlalchemy.orm import Session

from app.models.rule import Rule
from app.config import config


ACTIVE_RULE_TYPES = {"core_rule", "material_guideline"}
VALID_RULE_TYPES = ACTIVE_RULE_TYPES | {"suggestion"}
VALID_RULE_STATUSES = {"active", "candidate", "archived"}
VALID_RULE_SOURCES = {"manual", "project_review", "crawler_summary", "workflow_summary"}


def create_rule(
    db: Session,
    scope: str,
    content: str,
    task_id: str = None,
    sub_task_id: str = None,
    rule_type: str = "core_rule",
    status: str = "active",
    source: str = "manual",
) -> Rule:
    """创建规则"""
    valid_scopes = {"global", "task", "sub_task"}
    if scope not in valid_scopes:
        raise ValueError(f"无效作用域 '{scope}'，可选: {', '.join(valid_scopes)}")
    if rule_type not in VALID_RULE_TYPES:
        raise ValueError(f"无效规则类型 '{rule_type}'，可选: {', '.join(sorted(VALID_RULE_TYPES))}")
    if status not in VALID_RULE_STATUSES:
        raise ValueError(f"无效规则状态 '{status}'，可选: {', '.join(sorted(VALID_RULE_STATUSES))}")
    if source not in VALID_RULE_SOURCES:
        raise ValueError(f"无效规则来源 '{source}'，可选: {', '.join(sorted(VALID_RULE_SOURCES))}")

    if scope == "task" and not task_id:
        raise ValueError("task 级别规则必须指定 task_id")
    if scope == "sub_task" and not sub_task_id:
        raise ValueError("sub_task 级别规则必须指定 sub_task_id")

    # 全局正式规则只允许一条 active core_rule/material_guideline 记录
    if scope == "global" and status == "active" and rule_type in ACTIVE_RULE_TYPES:
        existing = db.query(Rule).filter(
            Rule.scope == "global",
            Rule.status == "active",
            Rule.rule_type.in_(ACTIVE_RULE_TYPES),
        ).first()
        if existing:
            raise ValueError("全局正式规则已存在，请编辑现有规则或创建候选建议")

    rule = Rule(
        id=str(uuid.uuid4()),
        scope=scope,
        content=content,
        task_id=task_id,
        sub_task_id=sub_task_id,
        rule_type=rule_type,
        status=status,
        source=source,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_rule(
    db: Session,
    rule_id: str,
    content: str,
    rule_type: str | None = None,
    status: str | None = None,
    source: str | None = None,
) -> Rule:
    """更新规则内容"""
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise ValueError(f"规则 {rule_id} 不存在")

    if rule_type is not None and rule_type not in VALID_RULE_TYPES:
        raise ValueError(f"无效规则类型 '{rule_type}'，可选: {', '.join(sorted(VALID_RULE_TYPES))}")
    if status is not None and status not in VALID_RULE_STATUSES:
        raise ValueError(f"无效规则状态 '{status}'，可选: {', '.join(sorted(VALID_RULE_STATUSES))}")
    if source is not None and source not in VALID_RULE_SOURCES:
        raise ValueError(f"无效规则来源 '{source}'，可选: {', '.join(sorted(VALID_RULE_SOURCES))}")

    next_rule_type = rule_type or rule.rule_type
    next_status = status or rule.status
    if rule.scope == "global" and next_status == "active" and next_rule_type in ACTIVE_RULE_TYPES:
        conflict = db.query(Rule).filter(
            Rule.id != rule.id,
            Rule.scope == "global",
            Rule.status == "active",
            Rule.rule_type.in_(ACTIVE_RULE_TYPES),
        ).first()
        if conflict:
            raise ValueError("已存在其他全局正式规则，请先归档后再激活当前规则")

    rule.content = content
    if rule_type is not None:
        rule.rule_type = rule_type
    if status is not None:
        rule.status = status
    if source is not None:
        rule.source = source
    db.commit()
    db.refresh(rule)
    return rule


def promote_rule(db: Session, rule_id: str) -> Rule:
    """将候选建议晋升为正式规则"""
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise ValueError(f"规则 {rule_id} 不存在")
    if rule.rule_type != "suggestion":
        raise ValueError("只有 suggestion 类型规则可以晋升")

    if rule.scope == "global":
        existing = db.query(Rule).filter(
            Rule.id != rule.id,
            Rule.scope == "global",
            Rule.status == "active",
            Rule.rule_type.in_(ACTIVE_RULE_TYPES),
        ).all()
        for item in existing:
            item.status = "archived"

    rule.rule_type = "core_rule"
    rule.status = "active"
    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(db: Session, rule_id: str) -> bool:
    """删除规则"""
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise ValueError(f"规则 {rule_id} 不存在")

    db.delete(rule)
    db.commit()
    return True


def list_rules(
    db: Session,
    scope: str = None,
    task_id: str = None,
    status: str = None,
    rule_type: str = None,
) -> list:
    """查询规则列表"""
    query = db.query(Rule)
    if scope:
        query = query.filter(Rule.scope == scope)
    if task_id:
        query = query.filter(Rule.task_id == task_id)
    if status:
        query = query.filter(Rule.status == status)
    if rule_type:
        query = query.filter(Rule.rule_type == rule_type)
    return query.order_by(Rule.created_at).all()


def list_rule_suggestions(db: Session, scope: str = None, task_id: str = None) -> list:
    query = db.query(Rule).filter(Rule.rule_type == "suggestion")
    if scope:
        query = query.filter(Rule.scope == scope)
    if task_id:
        query = query.filter(Rule.task_id == task_id)
    return query.order_by(Rule.created_at.desc()).all()


def get_rule(db: Session, rule_id: str) -> Rule:
    """获取单条规则"""
    return db.query(Rule).filter(Rule.id == rule_id).first()


def _replace_variables(content: str) -> str:
    """替换规则中的变量"""
    variables = {
        "{{workspace_root}}": config.workspace_root,
        "{{project_name}}": config.project_name,
    }
    for var, value in variables.items():
        content = content.replace(var, value)
    return content


def get_merged_rules(
    db: Session,
    task_id: str = None,
    sub_task_id: str = None,
) -> str:
    """
    获取合并后的规则提示词（含变量替换）。
    合并顺序：全局规则 + 任务级规则 + 子任务级规则
    仅注入 active 且属于正式类型的规则，杜绝候选建议污染运行时。
    """
    parts = []

    # 1. 全局规则
    global_rules = db.query(Rule).filter(
        Rule.scope == "global",
        Rule.status == "active",
        Rule.rule_type.in_(ACTIVE_RULE_TYPES),
    ).order_by(Rule.created_at).all()
    for r in global_rules:
        parts.append(r.content)

    # 2. 任务级规则
    if task_id:
        task_rules = db.query(Rule).filter(
            Rule.scope == "task",
            Rule.task_id == task_id,
            Rule.status == "active",
            Rule.rule_type.in_(ACTIVE_RULE_TYPES),
        ).order_by(Rule.created_at).all()
        for r in task_rules:
            parts.append(r.content)

    # 3. 子任务级规则
    if sub_task_id:
        sub_task_rules = db.query(Rule).filter(
            Rule.scope == "sub_task",
            Rule.sub_task_id == sub_task_id,
            Rule.status == "active",
            Rule.rule_type.in_(ACTIVE_RULE_TYPES),
        ).order_by(Rule.created_at).all()
        for r in sub_task_rules:
            parts.append(r.content)

    merged = "\n\n---\n\n".join(parts) if parts else ""
    return _replace_variables(merged)
