"""Legal material matrix, rights checks, and evidence package generation."""
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.collaboration import ProjectMember
from app.models.compliance import ComplianceFinding, ComplianceScan
from app.models.evidence import EvidenceEvent
from app.models.legal_assets import EvidencePackage, LegalMaterial, RightsCheckResult, RightsProfile
from app.models.project_v2 import ContentVersion, ContributionLedger, GenerationJob, ProjectV2
from app.models.short_drama_generation_job import ShortDramaGenerationJob
from app.services import workspace_service
from app.services.evidence_event_service import actor_fields, json_loads, record_evidence_event
from app.services.official_source_consistency import (
    OfficialSourceConsistencyError,
    validate_locked_official_source_consistency,
)

SYSTEM_MATERIALS = [
    ("final_script", "最终稿与版本链"),
    ("version_hash_manifest", "版本哈希清单"),
    ("contribution_report", "贡献归因报告"),
    ("ai_creation_statement", "AI 创作过程说明"),
    ("compliance_report", "合规审核报告"),
]

USER_MATERIALS = [
    ("party_identity", "作者/参与方主体信息"),
    ("rights_agreement", "合作/委托/职务创作协议"),
    ("source_license", "改编/IP授权证明"),
]

EXTERNAL_MATERIALS = [
    ("trusted_timestamp", "可信时间戳/公证/区块链回执"),
    ("broadcast_filing", "广电备案/发行许可证号"),
]


def ensure_rights_profile(db: Session, project: ProjectV2) -> RightsProfile:
    profile = db.query(RightsProfile).filter(RightsProfile.project_id == project.id).first()
    if profile:
        return profile
    profile = RightsProfile(
        project_id=project.id,
        project_origin_type="adaptation" if "改编" in str(project.project_type or "") else "original",
        ai_assist_flag=1,
        rights_status="draft",
    )
    db.add(profile)
    db.flush()
    return profile


def build_material_matrix(db: Session, project: ProjectV2) -> dict[str, Any]:
    profile = ensure_rights_profile(db, project)
    existing = {
        row.material_type: row
        for row in db.query(LegalMaterial).filter(LegalMaterial.project_id == project.id).all()
    }
    versions = db.query(ContentVersion).filter(ContentVersion.project_id == project.id).count()
    ai_jobs = _count_ai_generation_jobs(db, project.id)
    compliance = db.query(ComplianceScan).filter(ComplianceScan.project_id == project.id).order_by(ComplianceScan.created_at.desc()).first()
    members = db.query(ProjectMember).filter(ProjectMember.project_id == project.id, ProjectMember.status == "active").count()

    def item(material_type: str, title: str, provider: str, status: str, detail: str = "") -> dict[str, Any]:
        row = existing.get(material_type)
        return {
            "material_type": material_type,
            "title": title,
            "provider": provider,
            "status": row.status if row else status,
            "detail": row.content_text if row and row.content_text else detail,
            "file_path": row.file_path if row else "",
            "file_hash": row.file_hash if row else "",
        }

    system = [
        item("final_script", "最终稿与版本链", "system", "ready" if versions else "missing", f"已记录 {versions} 个版本"),
        item("version_hash_manifest", "版本哈希清单", "system", "ready" if versions else "missing"),
        item("contribution_report", "贡献归因报告", "system", "ready" if members or versions else "missing", f"协作成员 {members} 人"),
        item("ai_creation_statement", "AI 创作过程说明", "system", "ready" if ai_jobs else "missing", f"AI 任务 {ai_jobs} 次"),
        item("compliance_report", "合规审核报告", "system", "ready" if compliance else "missing", compliance.summary if compliance else ""),
    ]
    user = [item(code, title, "user", "missing") for code, title in USER_MATERIALS]
    external = [item(code, title, "external", "missing") for code, title in EXTERNAL_MATERIALS]
    ready = sum(1 for group in (system, user, external) for value in group if value["status"] == "ready")
    total = sum(len(group) for group in (system, user, external))
    profile.rights_score = int(round(ready / total * 100)) if total else 0
    profile.rights_status = "ready_to_package" if profile.rights_score >= 70 else "draft"
    db.commit()
    return {
        "project_id": project.id,
        "rights_status": profile.rights_status,
        "rights_score": profile.rights_score,
        "system_generated": system,
        "user_required": user,
        "external_required": external,
    }


def upsert_legal_material(
    db: Session,
    *,
    project_id: str,
    material_type: str,
    title: str = "",
    content_text: str = "",
    provider: str = "user",
    status: str = "ready",
    actor: Any = None,
) -> LegalMaterial:
    row = db.query(LegalMaterial).filter(
        LegalMaterial.project_id == project_id,
        LegalMaterial.material_type == material_type,
    ).first()
    if row is None:
        row = LegalMaterial(project_id=project_id, material_type=material_type)
        db.add(row)
    row.title = title or row.title or material_type
    row.content_text = content_text
    row.provider = provider
    row.status = status
    row.file_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest() if content_text else row.file_hash
    row.updated_at = datetime.now()
    db.flush()
    record_evidence_event(
        db,
        project_id=project_id,
        actor=actor,
        event_type="legal_material_upserted",
        target_type="legal_material",
        target_id=row.id,
        content_hash=row.file_hash,
        summary=row.title,
        metadata={"material_type": material_type, "status": status},
    )
    db.commit()
    db.refresh(row)
    return row


def _latest_episode_official_versions(db: Session, project_id: str) -> list[ContentVersion]:
    rows = (
        db.query(ContentVersion)
        .filter(
            ContentVersion.project_id == project_id,
            ContentVersion.scene_number == 0,
            ContentVersion.content_hash != "",
        )
        .order_by(ContentVersion.episode_number.asc(), ContentVersion.created_at.desc())
        .all()
    )
    latest_by_episode: dict[int, ContentVersion] = {}
    for row in rows:
        episode_number = int(row.episode_number or 0)
        if episode_number and episode_number not in latest_by_episode:
            latest_by_episode[episode_number] = row
    return [latest_by_episode[key] for key in sorted(latest_by_episode)]


def _latest_bound_compliance_scan(
    db: Session,
    *,
    project_id: str,
    episode_number: int,
    content_version_id: str,
    content_hash: str,
) -> ComplianceScan | None:
    return (
        db.query(ComplianceScan)
        .filter(
            ComplianceScan.project_id == project_id,
            ComplianceScan.episode_number == episode_number,
            ComplianceScan.content_version_id == content_version_id,
            ComplianceScan.content_hash == content_hash,
            ComplianceScan.status == "completed",
        )
        .order_by(ComplianceScan.created_at.desc())
        .first()
    )


def _locked_source_binding_for_scan(
    scan: ComplianceScan,
    locked_sources_by_episode: dict[int, Any],
) -> dict[str, Any]:
    locked_source = locked_sources_by_episode.get(int(scan.episode_number or 0))
    if locked_source is None:
        return {"binding_status": "locked_official_source_missing"}
    if (
        str(scan.content_version_id or "") == locked_source.content_version_id
        and str(scan.content_hash or "") == locked_source.content_hash
    ):
        return {
            "binding_status": "matched_locked_official_source",
            "locked_content_version_id": locked_source.content_version_id,
            "locked_content_hash": locked_source.content_hash,
        }
    return {
        "binding_status": "mismatched_locked_official_source",
        "locked_content_version_id": locked_source.content_version_id,
        "locked_content_hash": locked_source.content_hash,
    }


def check_export_gate(db: Session, *, project: ProjectV2) -> RightsCheckResult:
    matrix = build_material_matrix(db, project)
    blockers: list[str] = []
    warnings: list[str] = []
    latest_compliance = db.query(ComplianceScan).filter(ComplianceScan.project_id == project.id).order_by(ComplianceScan.created_at.desc()).first()
    if latest_compliance is None:
        blockers.append("尚未完成内容合规审核")
    elif latest_compliance.verdict == "reject":
        blockers.append("存在 P0 合规红线，不能正式导出")
    official_versions = _latest_episode_official_versions(db, project.id)
    if not official_versions:
        blockers.append("缺少可证明一致的 locked official source，不能正式导出")
    else:
        for version in official_versions:
            episode_number = int(version.episode_number or 0)
            try:
                locked_source = validate_locked_official_source_consistency(
                    db,
                    project_id=project.id,
                    episode_number=episode_number,
                    project_workspace_path=str(project.workspace_path or ""),
                    content_version_id=str(version.id or ""),
                )
            except OfficialSourceConsistencyError as exc:
                blockers.append(f"第 {episode_number} 集 locked official source 不一致：{exc.reason_code}")
                continue
            bound_scan = _latest_bound_compliance_scan(
                db,
                project_id=project.id,
                episode_number=episode_number,
                content_version_id=locked_source.content_version_id,
                content_hash=locked_source.content_hash,
            )
            if bound_scan is None:
                blockers.append(f"第 {episode_number} 集合规扫描未绑定当前 locked official source，不能正式导出")
            elif str(bound_scan.verdict or "") != "pass":
                blockers.append(f"第 {episode_number} 集合规扫描未通过：{bound_scan.verdict or 'unknown'}")
    if "改编" in str(project.project_type or ""):
        source_license_ready = any(
            item["material_type"] == "source_license" and item["status"] == "ready"
            for item in matrix["user_required"]
        )
        if not source_license_ready:
            blockers.append("改编项目缺少 IP/改编授权证明")
    if not any(item["material_type"] == "ai_creation_statement" and item["status"] == "ready" for item in matrix["system_generated"]):
        warnings.append("AI 创作过程说明尚不完整")
    status = "blocked" if blockers else ("warning" if warnings else "pass")
    result = RightsCheckResult(
        project_id=project.id,
        check_type="export_gate",
        status=status,
        score=int(matrix["rights_score"]),
        blockers_json=json.dumps(blockers, ensure_ascii=False),
        warnings_json=json.dumps(warnings, ensure_ascii=False),
        metadata_json=json.dumps({
            "rights_status": matrix["rights_status"],
            "locked_official_source_required": True,
            "compliance_scan_binding_required": True,
        }, ensure_ascii=False),
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def generate_evidence_package(db: Session, *, project: ProjectV2, package_type: str, actor: Any) -> EvidencePackage:
    versions = db.query(ContentVersion).filter(ContentVersion.project_id == project.id).order_by(ContentVersion.created_at.asc()).all()
    locked_sources_by_version: dict[str, Any] = {}
    locked_sources_by_episode: dict[int, Any] = {}
    for row in versions:
        if int(row.scene_number or 0) != 0:
            continue
        locked_source = validate_locked_official_source_consistency(
            db,
            project_id=project.id,
            episode_number=int(row.episode_number or 0),
            project_workspace_path=str(project.workspace_path or ""),
            content_version_id=str(row.id or ""),
        )
        locked_sources_by_version[str(row.id or "")] = locked_source
        locked_sources_by_episode[int(row.episode_number or 0)] = locked_source
    matrix = build_material_matrix(db, project)
    events = db.query(EvidenceEvent).filter(EvidenceEvent.project_id == project.id).order_by(EvidenceEvent.created_at.asc()).limit(500).all()
    ledgers = db.query(ContributionLedger).filter(ContributionLedger.project_id == project.id).all()
    compliance_scans = db.query(ComplianceScan).filter(ComplianceScan.project_id == project.id).order_by(ComplianceScan.created_at.asc()).all()
    compliance_findings = db.query(ComplianceFinding).filter(ComplianceFinding.project_id == project.id).order_by(ComplianceFinding.created_at.asc()).all()
    legal_materials = db.query(LegalMaterial).filter(LegalMaterial.project_id == project.id).order_by(LegalMaterial.created_at.asc()).all()
    export_root = workspace_service.ensure_acceptance_artifacts_root()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    package_name = f"{project.name}-法律资产包-{package_type}-{timestamp}.zip"
    package_path = workspace_service.artifact_path(package_name, root=export_root)
    files: dict[str, bytes] = {
        "README.txt": "本资产包为事实材料整理，不构成法律意见。\n".encode("utf-8"),
        "ai_creation_statement.txt": build_ai_statement(db, project).encode("utf-8"),
        "legal_matrix.json": json.dumps(matrix, ensure_ascii=False, indent=2).encode("utf-8"),
        "contribution_report.json": json.dumps({
            "notice": "贡献统计是事实记录，不等于最终版权归属。",
            "contributors": [
                {
                    "user_id": row.user_id,
                    "user_name": row.user_name,
                    "episodes_touched": row.episodes_touched,
                    "scenes_written": row.scenes_written,
                    "total_edits": row.total_edits,
                    "words_added": row.words_added,
                    "words_deleted": row.words_deleted,
                    "ai_generations_accepted": row.ai_generations_accepted,
                    "ai_generations_modified": row.ai_generations_modified,
                    "final_score": row.final_score,
                }
                for row in ledgers
            ],
        }, ensure_ascii=False, indent=2).encode("utf-8"),
        "compliance_report.json": json.dumps({
            "scans": [
                {
                    "id": row.id,
                    "episode_number": row.episode_number,
                    "content_version_id": row.content_version_id,
                    "verdict": row.verdict,
                    "summary": row.summary,
                    "content_hash": row.content_hash,
                    "locked_source_binding": _locked_source_binding_for_scan(row, locked_sources_by_episode),
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                }
                for row in compliance_scans
            ],
            "findings": [
                {
                    "id": row.id,
                    "rule_id": row.rule_id,
                    "severity": row.severity,
                    "episode_number": row.episode_number,
                    "quote": row.quote,
                    "reason": row.reason,
                    "suggestion": row.suggestion,
                    "human_decision": row.human_decision,
                    "status": row.status,
                }
                for row in compliance_findings
            ],
        }, ensure_ascii=False, indent=2).encode("utf-8"),
        "legal_materials.json": json.dumps([
            {
                "material_type": row.material_type,
                "title": row.title,
                "provider": row.provider,
                "status": row.status,
                "content_text": row.content_text,
                "file_hash": row.file_hash,
            }
            for row in legal_materials
        ], ensure_ascii=False, indent=2).encode("utf-8"),
    }
    final_parts: list[str] = []
    for row in versions:
        source_path = Path(row.content_path or "")
        if source_path.is_file():
            if int(row.scene_number or 0) == 0:
                locked_source = locked_sources_by_version[str(row.id or "")]
                payload = locked_source.content.encode("utf-8")
            else:
                payload = source_path.read_bytes()
            files[f"versions/E{row.episode_number:03d}_S{row.scene_number:03d}_{row.version_code}.md"] = payload
            if row.scene_number == 0:
                final_parts.append(payload.decode("utf-8", errors="replace"))
    files["final_script.md"] = ("\n\n".join(final_parts) if final_parts else "尚未发现锁稿版本。\n").encode("utf-8")
    hash_manifest = {
        path: hashlib.sha256(payload).hexdigest()
        for path, payload in sorted(files.items())
    }
    files["hash_manifest.json"] = json.dumps(hash_manifest, ensure_ascii=False, indent=2).encode("utf-8")
    manifest = {
        "project": {"id": project.id, "name": project.name, "creation_mode": getattr(project, "creation_mode", "solo")},
        "package_type": package_type,
        "generated_at": datetime.now().isoformat(),
        "matrix": matrix,
        "hash_manifest": {
            path: hashlib.sha256(payload).hexdigest()
            for path, payload in sorted(files.items())
        },
        "versions": [
            {"id": row.id, "version_code": row.version_code, "episode_number": row.episode_number, "scene_number": row.scene_number, "hash": row.content_hash}
            for row in versions
        ],
        "locked_official_sources": [
            locked_sources_by_episode[key].source_map
            for key in sorted(locked_sources_by_episode)
        ],
        "compliance_scan_bindings": [
            {
                "episode_number": key,
                "scan_id": scan.id,
                "scan_content_version_id": scan.content_version_id,
                "scan_content_hash": scan.content_hash,
                "locked_content_version_id": locked_source.content_version_id,
                "locked_content_hash": locked_source.content_hash,
                "binding_status": "matched_locked_official_source",
            }
            for key in sorted(locked_sources_by_episode)
            for locked_source in [locked_sources_by_episode[key]]
            for scan in [_latest_bound_compliance_scan(
                db,
                project_id=project.id,
                episode_number=key,
                content_version_id=locked_source.content_version_id,
                content_hash=locked_source.content_hash,
            )]
            if scan is not None
        ],
        "evidence_events": [
            {"event_type": row.event_type, "target_type": row.target_type, "target_id": row.target_id, "created_at": row.created_at.isoformat() if row.created_at else ""}
            for row in events
        ],
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    files["manifest.json"] = manifest_bytes
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename, payload in sorted(files.items()):
            zf.writestr(filename, payload)
    fields = actor_fields(actor)
    package = EvidencePackage(
        project_id=project.id,
        package_type=package_type,
        status="generated",
        package_path=str(package_path),
        manifest_hash=manifest_hash,
        manifest_json=json.dumps(manifest, ensure_ascii=False),
        created_by=fields["actor_id"],
    )
    db.add(package)
    db.flush()
    record_evidence_event(
        db,
        project_id=project.id,
        actor=actor,
        event_type="evidence_package_generated",
        target_type="evidence_package",
        target_id=package.id,
        content_hash=manifest_hash,
        summary=f"生成 {package_type} 法律资产包",
    )
    db.commit()
    db.refresh(package)
    return package


def build_ai_statement(db: Session, project: ProjectV2) -> str:
    jobs = db.query(GenerationJob).filter(GenerationJob.project_id == project.id).order_by(GenerationJob.created_at.asc()).all()
    short_drama_jobs = (
        db.query(ShortDramaGenerationJob)
        .filter(ShortDramaGenerationJob.project_id == project.id)
        .order_by(ShortDramaGenerationJob.created_at.asc())
        .all()
    )
    lines = [
        f"项目：{project.name}",
        "声明：本说明根据系统实时记录自动生成，用于描述 AI 辅助创作过程。",
        "",
    ]
    if not jobs and not short_drama_jobs:
        lines.append("当前未记录到 AI 生成任务。")
    for idx, job in enumerate(jobs, 1):
        lines.append(f"{idx}. {job.job_type or 'generation'} / {job.model_name or 'unknown'} / {job.status}")
        lines.append(f"   集/场：{job.episode_number}/{job.scene_number}；提示词路径：{job.prompt_path or '-'}")
    offset = len(jobs)
    for idx, job in enumerate(short_drama_jobs, offset + 1):
        lines.append(f"{idx}. 短剧科研链路 / {job.status}")
        lines.append(f"   集/场：{job.episode_no}/{job.scene_no}；任务ID：{job.id}")
    return "\n".join(lines)


def _count_ai_generation_jobs(db: Session, project_id: str) -> int:
    legacy_count = db.query(GenerationJob).filter(GenerationJob.project_id == project_id).count()
    short_drama_count = (
        db.query(ShortDramaGenerationJob)
        .filter(ShortDramaGenerationJob.project_id == project_id)
        .count()
    )
    return int(legacy_count or 0) + int(short_drama_count or 0)


def rights_check_to_dict(row: RightsCheckResult) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "check_type": row.check_type,
        "status": row.status,
        "score": row.score,
        "blockers": json_loads(row.blockers_json, []),
        "warnings": json_loads(row.warnings_json, []),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def package_to_dict(row: EvidencePackage) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "package_type": row.package_type,
        "status": row.status,
        "package_path": row.package_path,
        "manifest_hash": row.manifest_hash,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }
