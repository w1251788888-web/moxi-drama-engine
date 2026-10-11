"""Lightweight script compliance scanning and review helpers."""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.compliance import ComplianceFinding, CompliancePatch, ComplianceScan
from app.models.project_v2 import ContentVersion, Episode, ProjectV2, Scene
from app.services.evidence_event_service import actor_fields, record_evidence_event
from app.services.official_source_consistency import (
    OfficialSourceConsistencyError,
    validate_locked_official_source_consistency,
)

RULES = [
    {
        "rule_id": "C-MINOR-ROMANCE",
        "severity": "redline",
        "category": "未成年人敏感",
        "keywords": ["未成年恋爱", "未成年人恋爱", "高中生同居", "未成年性"],
        "reason": "未成年人相关恋爱、性暗示或同居描写属于红线风险。",
        "suggestion": "将角色年龄调整为成年人，删除性暗示，或改为非恋爱关系冲突。",
    },
    {
        "rule_id": "C-CRIME-GLORIFY",
        "severity": "redline",
        "category": "美化违法",
        "keywords": ["教你诈骗", "吸毒很酷", "赌博稳赚", "杀人无罪"],
        "reason": "以正面方式呈现违法犯罪且缺少后果，存在导向风险。",
        "suggestion": "删除教程式表达，补充违法后果和明确的负面评价。",
    },
    {
        "rule_id": "C-SELF-HARM",
        "severity": "redline",
        "category": "自伤自杀",
        "keywords": ["自杀才解脱", "自残很美", "殉情自杀"],
        "reason": "浪漫化或鼓励自伤自杀属于红线风险。",
        "suggestion": "改为求助、干预、救援或心理支持情节。",
    },
    {
        "rule_id": "C-VIOLENCE-DETAIL",
        "severity": "high_risk",
        "category": "过度暴力",
        "keywords": ["血肉模糊", "肢解", "虐杀", "砍断"],
        "reason": "暴力细节过重，可能触发平台审核。",
        "suggestion": "弱化过程描写，保留情节后果与人物反应。",
    },
    {
        "rule_id": "C-LEGAL-MEDICAL-ADVICE",
        "severity": "warning",
        "category": "医疗/法律伪装",
        "keywords": ["保证治好", "不用看医生", "法院一定判", "法律上绝对"],
        "reason": "具体医疗或法律结论可能被误用。",
        "suggestion": "改成角色观点，并补充专业机构/专业人士处理。",
    },
]


def collect_episode_text(db: Session, project_id: str, episode_number: int) -> tuple[str, str, str]:
    project = db.query(ProjectV2).filter(ProjectV2.id == project_id).first()
    if project is not None:
        locked_version = (
            db.query(ContentVersion)
            .filter(
                ContentVersion.project_id == project_id,
                ContentVersion.episode_number == episode_number,
                ContentVersion.scene_number == 0,
                ContentVersion.content_hash != "",
            )
            .order_by(ContentVersion.created_at.desc())
            .first()
        )
        if locked_version is not None:
            try:
                locked_source = validate_locked_official_source_consistency(
                    db,
                    project_id=project_id,
                    episode_number=episode_number,
                    project_workspace_path=str(project.workspace_path or ""),
                    content_version_id=str(locked_version.id or ""),
                )
            except OfficialSourceConsistencyError:
                return "", "", ""
            return locked_source.content, locked_source.content_version_id, locked_source.content_hash

    episode = db.query(Episode).filter(Episode.project_id == project_id, Episode.episode_number == episode_number).first()
    if episode is None:
        return "", "", ""
    scenes = db.query(Scene).filter(Scene.episode_id == episode.id).order_by(Scene.scene_number).all()
    text = "\n\n".join(str(scene.content or "").strip() for scene in scenes if str(scene.content or "").strip())
    latest_version = db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == episode_number,
    ).order_by(ContentVersion.created_at.desc()).first()
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
    return text, latest_version.id if latest_version else "", latest_version.content_hash if latest_version else content_hash


def mark_episode_compliance_stale(db: Session, project_id: str, episode_number: int) -> None:
    episode = db.query(Episode).filter(Episode.project_id == project_id, Episode.episode_number == episode_number).first()
    if episode:
        episode.compliance_status = "stale"
    db.query(ComplianceFinding).filter(
        ComplianceFinding.project_id == project_id,
        ComplianceFinding.episode_number == episode_number,
        ComplianceFinding.status.in_(["open", "resolved", "false_positive"]),
    ).update({"status": "stale"}, synchronize_session=False)


def scan_episode(db: Session, *, project_id: str, episode_number: int, actor: Any = None) -> ComplianceScan:
    text, version_id, content_hash = collect_episode_text(db, project_id, episode_number)
    scan = ComplianceScan(
        project_id=project_id,
        episode_number=episode_number,
        content_version_id=version_id,
        content_hash=content_hash,
        status="completed",
        verdict="pass",
        summary="未发现合规风险" if text else "本集暂无可审查正文",
    )
    db.add(scan)
    db.flush()

    worst = "pass"
    finding_count = 0
    for rule in RULES:
        for keyword in rule["keywords"]:
            idx = text.find(keyword)
            if idx < 0:
                continue
            severity = rule["severity"]
            if severity == "redline":
                worst = "reject"
            elif severity == "high_risk" and worst != "reject":
                worst = "warning"
            finding_count += 1
            db.add(ComplianceFinding(
                scan_id=scan.id,
                project_id=project_id,
                rule_id=rule["rule_id"],
                severity=severity,
                category=rule["category"],
                episode_number=episode_number,
                scene_number=0,
                start_offset=idx,
                end_offset=idx + len(keyword),
                quote=keyword,
                reason=rule["reason"],
                suggestion=rule["suggestion"],
                confidence=0.72,
                content_version_id=version_id,
                content_hash=content_hash,
            ))
            break

    scan.verdict = worst
    if finding_count:
        scan.summary = f"发现 {finding_count} 处合规风险，结论：{worst}"
    episode = db.query(Episode).filter(Episode.project_id == project_id, Episode.episode_number == episode_number).first()
    if episode:
        episode.compliance_status = worst
    record_evidence_event(
        db,
        project_id=project_id,
        actor=actor,
        event_type="compliance_scan_completed",
        target_type="episode",
        target_id=str(episode_number),
        content_version_id=version_id,
        content_hash=content_hash,
        summary=scan.summary,
        metadata={"verdict": worst, "finding_count": finding_count},
    )
    db.commit()
    db.refresh(scan)
    return scan


def decide_finding(
    db: Session,
    *,
    finding: ComplianceFinding,
    actor: Any,
    decision: str,
    note: str = "",
) -> ComplianceFinding:
    normalized = str(decision or "").strip()
    if normalized not in {"approved", "rejected", "false_positive", "accepted_patch", "rewrite_required"}:
        raise ValueError("人工审核结论无效")
    fields = actor_fields(actor)
    finding.human_decision = normalized
    finding.human_note = str(note or "")
    finding.decided_by = fields["actor_id"]
    finding.decided_at = datetime.now()
    finding.updated_at = datetime.now()
    finding.status = "false_positive" if normalized == "false_positive" else "resolved"
    record_evidence_event(
        db,
        project_id=finding.project_id,
        actor=actor,
        event_type="compliance_finding_decided",
        target_type="compliance_finding",
        target_id=finding.id,
        content_version_id=finding.content_version_id,
        content_hash=finding.content_hash,
        summary=f"{finding.rule_id}: {normalized}",
        metadata={"decision": normalized, "note": note},
    )
    db.commit()
    db.refresh(finding)
    return finding


def propose_patch(db: Session, *, finding: ComplianceFinding, actor: Any) -> CompliancePatch:
    replacement = finding.suggestion or "请按审核意见弱化或改写该段内容。"
    patch = CompliancePatch(
        finding_id=finding.id,
        project_id=finding.project_id,
        before_text=finding.quote,
        after_text=f"【修改建议】{replacement}",
        status="proposed",
        created_by=actor_fields(actor)["actor_id"],
    )
    db.add(patch)
    record_evidence_event(
        db,
        project_id=finding.project_id,
        actor=actor,
        event_type="compliance_patch_proposed",
        target_type="compliance_finding",
        target_id=finding.id,
        summary=finding.suggestion,
    )
    db.commit()
    db.refresh(patch)
    return patch


def finding_to_dict(row: ComplianceFinding) -> dict[str, Any]:
    return {
        "id": row.id,
        "scan_id": row.scan_id,
        "rule_id": row.rule_id,
        "severity": row.severity,
        "category": row.category,
        "episode_number": row.episode_number,
        "scene_number": row.scene_number,
        "start_offset": row.start_offset,
        "end_offset": row.end_offset,
        "quote": row.quote,
        "reason": row.reason,
        "suggestion": row.suggestion,
        "confidence": row.confidence,
        "content_version_id": row.content_version_id,
        "content_hash": row.content_hash,
        "status": row.status,
        "human_decision": row.human_decision,
        "human_note": row.human_note,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def scan_to_dict(row: ComplianceScan, findings: list[ComplianceFinding] | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "episode_number": row.episode_number,
        "content_version_id": row.content_version_id,
        "content_hash": row.content_hash,
        "status": row.status,
        "verdict": row.verdict,
        "summary": row.summary,
        "findings": [finding_to_dict(item) for item in findings or []],
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }
