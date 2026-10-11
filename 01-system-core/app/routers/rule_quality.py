"""
规则质量控制 API 路由
防止规则污染的管理接口
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.services.rule_quality_service import RuleQualityService


router = APIRouter(
    prefix="/rule-quality",
    tags=["Rule Quality"],
    dependencies=[Depends(verify_admin)],
)


# ============ 请求/响应模型 ============

class PromotionEvaluationResponse(BaseModel):
    rule_id: str
    current_level: str
    target_level: Optional[str]
    can_promote: bool
    effectiveness: Dict[str, Any]
    requirements_check: Dict[str, Any]
    conflicts: List[Dict]
    requires_approval: bool
    message: str


class ApprovePromotionRequest(BaseModel):
    path_id: str
    approved: bool
    approved_by: str


class ApprovePromotionResponse(BaseModel):
    success: bool
    rule_id: str
    target_level: Optional[str]
    status: str
    message: str


class ResolveConflictRequest(BaseModel):
    conflict_id: str
    resolution: str  # merge/replace/exclude
    resolved_by: str


class RuleQualityReportResponse(BaseModel):
    rule_id: str
    current_level: str
    status: str
    effectiveness: Dict[str, Any]
    promotion_status: Optional[Dict[str, Any]]
    pending_conflicts: List[Dict]


class PendingPromotionItem(BaseModel):
    path_id: str
    rule_id: str
    current_level: str
    target_level: str
    requirements: Dict[str, Any]


class RecordRuleApplicationRequest(BaseModel):
    rule_id: str
    project_id: str
    segment_type: str
    success: bool
    validation_score: float
    user_override: bool = False
    tokens_used: int = 0


# ============ API 端点 ============

@router.get("/evaluate-promotion/{rule_id}", response_model=PromotionEvaluationResponse)
def evaluate_rule_promotion(rule_id: str, db: Session = Depends(get_db)):
    """
    评估规则是否符合晋升条件
    """
    service = RuleQualityService(db)
    result = service.evaluate_rule_promotion(rule_id)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return PromotionEvaluationResponse(**result)


@router.post("/approve-promotion", response_model=ApprovePromotionResponse)
def approve_promotion(request: ApprovePromotionRequest, db: Session = Depends(get_db)):
    """
    人工审核规则晋升
    """
    service = RuleQualityService(db)
    result = service.approve_promotion(
        path_id=request.path_id,
        approved=request.approved,
        approved_by=request.approved_by
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return ApprovePromotionResponse(**result)


@router.get("/pending-promotions", response_model=List[PendingPromotionItem])
def get_pending_promotions(level: Optional[str] = None, db: Session = Depends(get_db)):
    """
    获取待审核的晋升请求
    """
    service = RuleQualityService(db)
    promotions = service.get_pending_promotions(level=level)

    return [PendingPromotionItem(**p) for p in promotions]


@router.post("/record-application")
def record_rule_application(request: RecordRuleApplicationRequest, db: Session = Depends(get_db)):
    """
    记录规则应用效果（供内部调用）
    """
    service = RuleQualityService(db)
    service.record_rule_application(
        rule_id=request.rule_id,
        project_id=request.project_id,
        segment_type=request.segment_type,
        success=request.success,
        validation_score=request.validation_score,
        user_override=request.user_override,
        tokens_used=request.tokens_used
    )

    return {"success": True}


@router.get("/quality-report/{rule_id}", response_model=RuleQualityReportResponse)
def get_rule_quality_report(rule_id: str, db: Session = Depends(get_db)):
    """
    获取规则质量报告
    """
    service = RuleQualityService(db)
    report = service.get_rule_quality_report(rule_id)

    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])

    return RuleQualityReportResponse(**report)


@router.post("/resolve-conflict")
def resolve_conflict(request: ResolveConflictRequest, db: Session = Depends(get_db)):
    """
    解决规则冲突
    """
    service = RuleQualityService(db)
    result = service.resolve_conflict(
        conflict_id=request.conflict_id,
        resolution=request.resolution,
        resolved_by=request.resolved_by
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@router.get("/degraded-rules")
def get_degraded_rules(days: int = 7, db: Session = Depends(get_db)):
    """
    获取最近降级的规则
    """
    service = RuleQualityService(db)
    rules = service.get_degraded_rules(days=days)

    return {"degraded_rules": rules}
