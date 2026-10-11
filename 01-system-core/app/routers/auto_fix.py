"""
AUTO-FIX API 路由
"""
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.services.auto_fix_service import AutoFixService, FixResult
from app.models.episode_segment import EpisodeSegment as SegmentModel


router = APIRouter(
    prefix="/auto-fix",
    tags=["Auto-Fix"],
    dependencies=[Depends(verify_admin)],
)


class FixRequest(BaseModel):
    segment_id: str
    validation_result: dict
    max_iterations: int = 3


class FixResponse(BaseModel):
    success: bool
    pattern_code: str
    strategy_code: str
    fix_prompt: Optional[str] = None
    system_prompt: Optional[str] = None
    message: str


class FixResultRequest(BaseModel):
    segment_id: str
    fixed_content: str
    final_score: float
    iterations: int
    success: bool


class FailurePatternItem(BaseModel):
    code: str
    name: str
    triggered: int
    fixed: int
    success_rate: float


class StrategyItem(BaseModel):
    code: str
    name: str
    applied: int
    success: int
    success_rate: float
    avg_iterations: float


class AnalysisReport(BaseModel):
    failure_distribution: List[FailurePatternItem]
    strategy_effectiveness: List[StrategyItem]


@router.post("/detect", response_model=FixResponse)
def detect_and_fix(request: FixRequest, db: Session = Depends(get_db)):
    """检测失败模式并返回修复提示词"""
    service = AutoFixService(db)

    segment = db.query(SegmentModel).get(request.segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="段落不存在")

    result: FixResult = service.auto_fix(
        segment,
        request.validation_result,
        max_iterations=request.max_iterations
    )

    # 获取系统提示词
    system_prompt = None
    if result.strategy_code and result.strategy_code != "NOT_FOUND":
        from app.models.auto_fix import FixStrategy
        strategy = db.query(FixStrategy).filter(
            FixStrategy.strategy_code == result.strategy_code
        ).first()
        if strategy:
            system_prompt = strategy.system_prompt

    return FixResponse(
        success=result.success,
        pattern_code=result.pattern_code,
        strategy_code=result.strategy_code,
        fix_prompt=result.message if result.pattern_code != "NONE" else None,
        system_prompt=system_prompt,
        message="检测到失败模式，请使用fix_prompt进行修复" if result.pattern_code != "NONE" else "未检测到失败模式"
    )


@router.post("/record-result")
def record_fix_result(request: FixResultRequest, db: Session = Depends(get_db)):
    """记录修复结果"""
    service = AutoFixService(db)
    service.record_fix_result(
        segment_id=request.segment_id,
        fixed_content=request.fixed_content,
        final_score=request.final_score,
        iterations=request.iterations,
        success=request.success
    )
    return {"success": True}


@router.get("/analysis", response_model=AnalysisReport)
def get_analysis_report(db: Session = Depends(get_db)):
    """获取失败分析报告"""
    service = AutoFixService(db)
    report = service.get_failure_analysis_report()

    return AnalysisReport(
        failure_distribution=[
            FailurePatternItem(**item) for item in report["failure_distribution"]
        ],
        strategy_effectiveness=[
            StrategyItem(**item) for item in report["strategy_effectiveness"]
        ]
    )


@router.get("/patterns/{segment_type}")
def get_recommended_patterns(segment_type: str, limit: int = 3, db: Session = Depends(get_db)):
    """获取推荐的成功模式"""
    service = AutoFixService(db)
    patterns = service.get_recommended_patterns(segment_type, limit=limit)
    return {"patterns": patterns}


@router.get("/bottlenecks")
def get_bottlenecks(limit: int = 5, db: Session = Depends(get_db)):
    """获取性能瓶颈"""
    service = AutoFixService(db)
    bottlenecks = service.get_segment_bottlenecks(limit=limit)
    return {"bottlenecks": bottlenecks}
