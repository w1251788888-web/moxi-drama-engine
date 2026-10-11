"""
项目学习沉淀 API 路由
实现工作流自进化的HTTP接口
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.services.project_learning_service import ProjectLearningService


router = APIRouter(
    prefix="/project-learning",
    tags=["Project Learning"],
    dependencies=[Depends(verify_admin)],
)


# ============ 请求/响应模型 ============

class UserEditRequest(BaseModel):
    project_id: str
    target_type: str  # segment/step_version/scene
    target_id: str
    before_content: str
    after_content: str
    edit_reason: Optional[str] = None
    session_id: Optional[str] = None


class UserEditResponse(BaseModel):
    edit_id: str
    materialized: bool
    material_id: Optional[str] = None
    improvement_score: float
    message: str


class RuleExtractionRequest(BaseModel):
    project_id: str


class RuleExtractionResponse(BaseModel):
    job_id: str
    status: str
    total_materials: int
    extracted_rules: List[Dict]
    suggested_rule_content: Optional[str] = None
    confidence_score: float


class ApplyRuleRequest(BaseModel):
    job_id: str
    approve: bool = True
    target_scope: str = "task"  # task/global


class OptimizePromptRequest(BaseModel):
    project_id: str
    original_prompt: str
    context: Dict[str, Any]  # segment_type, step, genre_tags等


class OptimizePromptResponse(BaseModel):
    optimized_prompt: str
    cached: bool
    token_reduction: float
    materials_injected: List[str]
    materials_count: int


class EfficiencyReportResponse(BaseModel):
    period_days: int
    total_tokens: int
    total_segments: int
    avg_tokens_per_segment: float
    auto_fix_success_rate: float
    total_auto_fix: int
    trend: List[Dict]


class LearningInsightResponse(BaseModel):
    insights: List[Dict]


class ProjectMaterialItem(BaseModel):
    id: str
    material_type: str
    title: str
    quality_score: float
    usage_count: int
    tags: List[str]
    status: str
    created_at: str


# ============ API 端点 ============

@router.post("/capture-edit", response_model=UserEditResponse)
def capture_user_edit(request: UserEditRequest, db: Session = Depends(get_db)):
    """
    捕获用户编辑，分析改动强度，只沉淀为候选证据
    """
    service = ProjectLearningService(db)

    result_id = service.capture_user_edit(
        project_id=request.project_id,
        target_type=request.target_type,
        target_id=request.target_id,
        before_content=request.before_content,
        after_content=request.after_content,
        edit_reason=request.edit_reason,
        session_id=request.session_id
    )

    # 查询是否已沉淀为素材
    from app.models.project_learning import UserEditRecord
    edit_record = db.query(UserEditRecord).get(result_id)

    if edit_record:
        return UserEditResponse(
            edit_id=edit_record.id,
            materialized=edit_record.materialized,
            material_id=edit_record.material_id,
            improvement_score=edit_record.improvement_score,
            message="编辑已捕获，重大改动已进入候选证据池，待人工审查" if edit_record.is_significant else "编辑已记录"
        )
    else:
        # 兼容旧返回路径；新协议不应把用户编辑直接写为 approved 素材。
        return UserEditResponse(
            edit_id=result_id,
            materialized=False,
            material_id=result_id,
            improvement_score=0.0,
            message="编辑已进入候选证据池，待人工审查"
        )


@router.post("/extract-rules", response_model=RuleExtractionResponse)
def start_rule_extraction(request: RuleExtractionRequest, db: Session = Depends(get_db)):
    """
    启动规则提取任务（任务结束后调用）
    """
    service = ProjectLearningService(db)

    job_id = service.start_rule_extraction(request.project_id)

    if isinstance(job_id, str) and job_id.startswith("素材不足"):
        raise HTTPException(status_code=400, detail=job_id)

    from app.models.project_learning import RuleExtractionJob
    job = db.query(RuleExtractionJob).get(job_id)

    return RuleExtractionResponse(
        job_id=job.id,
        status=job.status,
        total_materials=job.total_materials,
        extracted_rules=job.extracted_rules or [],
        suggested_rule_content=job.suggested_rule_content,
        confidence_score=job.confidence_score
    )


@router.post("/apply-extracted-rule")
def apply_extracted_rule(request: ApplyRuleRequest, db: Session = Depends(get_db)):
    """
    批准或拒绝提取的规则
    """
    service = ProjectLearningService(db)

    rule_id = service.apply_extracted_rule(
        job_id=request.job_id,
        approve=request.approve,
        target_scope=request.target_scope
    )

    if rule_id:
        return {
            "success": True,
            "rule_id": rule_id,
            "message": "规则已成功应用到系统"
        }
    else:
        return {
            "success": False,
            "message": "规则已拒绝或未找到有效规则"
        }


@router.post("/optimize-prompt", response_model=OptimizePromptResponse)
def optimize_prompt(request: OptimizePromptRequest, db: Session = Depends(get_db)):
    """
    优化提示词，注入项目素材，减少token消耗
    """
    service = ProjectLearningService(db)

    optimized_prompt, meta = service.optimize_prompt(
        project_id=request.project_id,
        original_prompt=request.original_prompt,
        context=request.context
    )

    return OptimizePromptResponse(
        optimized_prompt=optimized_prompt,
        cached=meta.get("cached", False),
        token_reduction=meta.get("token_reduction", 0.0),
        materials_injected=meta.get("materials_injected", []),
        materials_count=meta.get("materials_count", 0)
    )


@router.get("/efficiency-report/{project_id}", response_model=EfficiencyReportResponse)
def get_efficiency_report(project_id: str, days: int = 7, db: Session = Depends(get_db)):
    """
    获取项目效率报告
    """
    service = ProjectLearningService(db)
    report = service.get_efficiency_report(project_id, days=days)

    if "message" in report:
        raise HTTPException(status_code=404, detail=report["message"])

    return EfficiencyReportResponse(**report)


@router.get("/insights/{project_id}", response_model=LearningInsightResponse)
def get_learning_insights(project_id: str, db: Session = Depends(get_db)):
    """
    获取项目学习洞察
    """
    service = ProjectLearningService(db)
    insights = service.generate_learning_insights(project_id)

    return LearningInsightResponse(insights=insights)


@router.get("/materials/{project_id}", response_model=List[ProjectMaterialItem])
def get_project_materials(
    project_id: str,
    material_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    获取项目素材库
    """
    from app.models.project_learning import ProjectMaterial

    query = db.query(ProjectMaterial).filter(
        ProjectMaterial.project_id == project_id
    )

    if material_type:
        query = query.filter(ProjectMaterial.material_type == material_type)
    if status:
        query = query.filter(ProjectMaterial.status == status)

    materials = query.order_by(
        ProjectMaterial.quality_score.desc(),
        ProjectMaterial.created_at.desc()
    ).limit(limit).all()

    return [
        ProjectMaterialItem(
            id=m.id,
            material_type=m.material_type,
            title=m.title,
            quality_score=m.quality_score,
            usage_count=m.usage_count,
            tags=m.tags or [],
            status=m.status,
            created_at=m.created_at.isoformat() if m.created_at else ""
        )
        for m in materials
    ]


@router.post("/record-metrics")
def record_generation_metrics(
    project_id: str,
    tokens_used: int,
    segment_count: int = 1,
    auto_fix_used: bool = False,
    material_applied: bool = False,
    db: Session = Depends(get_db)
):
    """
    记录生成指标（供内部调用）
    """
    service = ProjectLearningService(db)
    service.record_generation_metrics(
        project_id=project_id,
        tokens_used=tokens_used,
        segment_count=segment_count,
        auto_fix_used=auto_fix_used,
        material_applied=material_applied
    )
    return {"success": True}
