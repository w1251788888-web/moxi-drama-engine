"""
极简自学习 API 路由

原则：
- 接口极简
- 用户无感知
- 后台自动学习
"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import verify_admin
from app.services.lightweight_learning_service import LightweightLearningService


router = APIRouter(prefix="/lightweight-learning", tags=["Lightweight Learning"])


class OptimizePromptRequest(BaseModel):
    project_id: str
    user_prompt: str
    segment_type: str  # hook/validation/explosion/resolution
    episode_no: int


class OptimizePromptResponse(BaseModel):
    final_prompt: str
    user_prompt: str  # 返回原始提示词，方便前端对比
    mode: str  # transparent/lightweight/smart
    has_optimization: bool
    message: str


class RecordGenerationRequest(BaseModel):
    project_id: str
    segment_type: str
    episode_no: int
    content: str
    validation_score: Optional[float] = None


class RecordEditRequest(BaseModel):
    project_id: str
    segment_type: str
    before_content: str
    after_content: str


class ProjectStatsResponse(BaseModel):
    total_segments: int
    current_mode: str
    input_length_saved: str
    message: str


@router.post("/optimize", response_model=OptimizePromptResponse)
def optimize_prompt(
    request: OptimizePromptRequest,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """
    极简提示词优化

    原则：
    - 100%保留用户原始提示词
    - 只在开头追加统计数据参考
    - 绝不修改、删除用户规则
    """
    service = LightweightLearningService(db)

    result = service.optimize_prompt(
        project_id=request.project_id,
        user_prompt=request.user_prompt,
        segment_type=request.segment_type,
        episode_no=request.episode_no
    )

    return OptimizePromptResponse(
        final_prompt=result.final_prompt,
        user_prompt=result.user_prompt,
        mode=result.mode,
        has_optimization=len(result.prefix) > 0 or len(result.suffix) > 0,
        message=get_mode_message(result.mode)
    )


@router.post("/record-generation")
def record_generation(
    request: RecordGenerationRequest,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """
    记录生成结果（自动学习，无感知）

    前端在保存生成结果时自动调用，用户无感知
    """
    service = LightweightLearningService(db)

    service.record_generation(
        project_id=request.project_id,
        segment_type=request.segment_type,
        episode_no=request.episode_no,
        content=request.content,
        validation_score=request.validation_score
    )

    return {"success": True, "message": "已记录到学习池"}


@router.post("/record-edit")
def record_edit(
    request: RecordEditRequest,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """
    记录用户编辑（候选沉淀模式）

    前端在检测到用户修改内容时自动调用；用户改稿只进入候选证据池，
    不自动升级为 approved 素材或全局规则。
    """
    service = LightweightLearningService(db)

    service.record_user_edit(
        project_id=request.project_id,
        segment_type=request.segment_type,
        before_content=request.before_content,
        after_content=request.after_content
    )

    return {"success": True, "message": "已记录您的修改，待人工审查后再决定是否升级规则"}


@router.get("/stats/{project_id}", response_model=ProjectStatsResponse)
def get_project_stats(
    project_id: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """
    获取项目学习统计

    展示给用户：系统正在学习，工作流越来越轻
    """
    service = LightweightLearningService(db)

    stats = service.get_project_stats_summary(project_id)

    return ProjectStatsResponse(**stats)


def get_mode_message(mode: str) -> str:
    """获取模式说明"""
    messages = {
        "transparent": "观察期：正在学习您的写作风格",
        "lightweight": "轻量优化：已追加历史数据参考",
        "smart": "智能补全：可简化输入，系统自动补全"
    }
    return messages.get(mode, "学习中...")


# ═══════════════════════════════════════════════════════════
# 自我进化相关 API (OpenSpace AUTO-IMPROVE)
# ═══════════════════════════════════════════════════════════

class EvolutionStatusResponse(BaseModel):
    project_id: str
    learning_stage: str
    total_samples: int
    high_quality_samples: int
    patterns_extracted: int
    input_savings_percent: float
    evolution_message: str
    next_milestone: dict


class SuccessPatternResponse(BaseModel):
    segment_type: str
    sample_count: int
    avg_word_count: float
    word_count_range: list
    quality_score_avg: float
    confidence: float
    prompt_hint: str


class OptimizedRulesResponse(BaseModel):
    project_id: str
    rules_content: Optional[str]
    generated_at: str
    message: str


@router.get("/evolution/{project_id}", response_model=EvolutionStatusResponse)
def get_evolution_status(
    project_id: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """
    获取项目的自我进化状态

    展示工作流如何变得越来越轻
    """
    service = LightweightLearningService(db)
    status = service.get_evolution_status(project_id)
    return EvolutionStatusResponse(**status)


@router.get("/patterns/{project_id}", response_model=List[SuccessPatternResponse])
def get_success_patterns(
    project_id: str,
    min_quality: Optional[float] = 0.8,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """
    获取项目提取的成功模式列表 (AUTO-IMPROVE)

    这些是系统从成功案例中学习的经验
    """
    service = LightweightLearningService(db)
    patterns = service.extract_success_patterns(project_id, min_quality)
    return [SuccessPatternResponse(**p) for p in patterns]


@router.post("/generate-rules/{project_id}", response_model=OptimizedRulesResponse)
def generate_optimized_rules(
    project_id: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    """
    基于学习数据生成优化规则

    实现：从成功案例中提取规则 → 用户可简化输入
    """
    service = LightweightLearningService(db)

    rules_content = service.generate_optimized_rules(project_id)

    if rules_content:
        return OptimizedRulesResponse(
            project_id=project_id,
            rules_content=rules_content,
            generated_at=datetime.now().isoformat(),
            message="已基于成功案例生成优化规则，可简化后续输入"
        )
    else:
        return OptimizedRulesResponse(
            project_id=project_id,
            rules_content=None,
            generated_at=datetime.now().isoformat(),
            message="样本不足，请继续生成更多内容以启用规则自动生成"
        )
