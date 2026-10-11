"""剧集段落任务拆分API

实现superpowers的2-5分钟任务拆分和gstack的阻塞式质量门
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.services.episode_segment_service import EpisodeSegmentService
from app.services import workspace_service

router = APIRouter(prefix="/admin/short-drama", tags=["Episode Segment Management"])


# ─────────────────────────────────────────────────────────
# 请求/响应模型
# ─────────────────────────────────────────────────────────

class GenerateSegmentRequest(BaseModel):
    content: str
    version_id: Optional[str] = None


class RefactorSegmentRequest(BaseModel):
    content: str
    reason: str = ""


class CreateSegmentReviewRequest(BaseModel):
    verdict: Literal["pass", "block", "request_changes"]
    comments: str = ""
    issues: list[dict] = Field(default_factory=list)
    rewrite_suggestion: str = ""
    is_blocking: bool = True
    score: Optional[int] = None


class PassGateRequest(BaseModel):
    bypass: bool = False
    reason: str = ""


# ─────────────────────────────────────────────────────────
# 段落管理API
# ─────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/episodes/{episode_no}/segments")
async def get_episode_segments(
    session_id: str,
    episode_no: int,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """获取一集的所有段落（自动初始化）"""
    service = EpisodeSegmentService(db)
    segments = service.get_episode_segments(session_id, episode_no)
    progress = service.get_segment_progress(session_id, episode_no)

    return {
        "segments": [s.to_dict() for s in segments],
        "progress": progress,
    }


@router.post("/segments/{segment_id}/generate")
async def generate_segment(
    segment_id: str,
    req: GenerateSegmentRequest,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """生成段落内容（红-绿循环）— 接收外部传入 content 仅做验证"""
    service = EpisodeSegmentService(db)
    try:
        segment = service.generate_segment(segment_id, req.content, req.version_id)
        return {
            "segment": segment.to_dict(),
            "validation": {
                "passed": segment.status == "green",
                "score": segment.validation_score,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class LlmGenerateSegmentOptions(BaseModel):
    n_candidates: int = Field(default=2, ge=1, le=4, description="候选数（修复25）")
    max_retries: int = Field(default=1, ge=0, le=3, description="失败重试次数（修复27）")
    diversity_against_history: bool = Field(default=True, description="启用历史段落多样性筛选")


@router.post("/sessions/{session_id}/episodes/{episode_no}/segments/{segment_type}/llm-generate")
async def llm_generate_segment(
    session_id: str,
    episode_no: int,
    segment_type: str,
    opts: Optional[LlmGenerateSegmentOptions] = None,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """修复19/22：用 LLM 直接生成本集指定段落内容（自动初始化段落、自动注入上段尾部 + cliffhanger + used_beats）"""
    from app.services.text_generation_service import generate_text
    from app.routers.short_drama_writing import (
        _get_session_task,
        _hydrate_session_project_runtime_context,
        _generation_kwargs_from_metadata,
        _build_base_template_vars,
        _render_step_prompt,
        _system_prompt_for_step,
    )
    import json

    if segment_type not in ("hook", "validation", "explosion", "resolution"):
        raise HTTPException(status_code=400, detail=f"非法段落类型: {segment_type}")

    task, metadata = _get_session_task(db, session_id)
    metadata = _hydrate_session_project_runtime_context(db, metadata)
    generation_kwargs = _generation_kwargs_from_metadata(metadata)

    # 初始化或获取本集 4 段
    service = EpisodeSegmentService(db)
    segments = service.get_episode_segments(session_id, episode_no)
    target = next((s for s in segments if s.segment_type == segment_type), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"段落不存在: ep{episode_no} {segment_type}")

    # 取上段尾部（350 字）作为承接锚点
    seq_order = ["hook", "validation", "explosion", "resolution"]
    cur_idx = seq_order.index(segment_type)
    prev_tail = ""
    if cur_idx > 0:
        prev_seg = next((s for s in segments if s.segment_type == seq_order[cur_idx - 1]), None)
        if prev_seg and prev_seg.content:
            prev_tail = prev_seg.content[-350:]

    # 加载段落模板
    seg_template_path = workspace_service.REPO_ROOT / "02-creation-rules" / "step-definitions" / "05a_segment_generate.md"
    if not seg_template_path.exists():
        raise HTTPException(status_code=500, detail="段落模板未找到")
    seg_template = seg_template_path.read_text(encoding="utf-8")

    # 拼模板变量（沿用 script_draft 的注入链）
    base_vars = _build_base_template_vars(metadata, draft_episode=episode_no)

    # 修复25: 把本集已通过段落 + 上 1 集成稿组成"多样性参考池"
    accepted_text = ""
    if opts is None or opts.diversity_against_history:
        for prev_seg in segments:
            if prev_seg.segment_type != segment_type and prev_seg.content:
                accepted_text += "\n" + prev_seg.content
        # 加上 1 集成稿（如果有）
        prev_ep_node = (metadata.get("episodes") or {}).get(str(episode_no - 1)) or {}
        prev_ep_steps = prev_ep_node.get("steps") if isinstance(prev_ep_node, dict) else None
        if isinstance(prev_ep_steps, dict):
            sd = prev_ep_steps.get("script_draft") or {}
            if isinstance(sd, dict):
                accepted_text += "\n" + str(sd.get("full_output") or "")[-1500:]

    # 调用 service 的 LLM 生成（带多候选 + 重试）
    try:
        n_cand = opts.n_candidates if opts else 2
        max_retries = opts.max_retries if opts else 1
        segment = service.generate_segment_with_llm(
            segment_id=target.id,
            template_vars=base_vars,
            system_prompt=_system_prompt_for_step("script_draft"),
            user_prompt_renderer=lambda tmpl, v: _render_simple(tmpl, v),
            generate_text_fn=generate_text,
            prompt_template=seg_template,
            generation_kwargs=generation_kwargs,
            previous_segment_tail=prev_tail,
            n_candidates=n_cand,
            accepted_segments_text=accepted_text,
            max_retries=max_retries,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"段落 LLM 生成失败: {exc}")

    return {
        "segment": segment.to_dict(),
        "validation": {
            "passed": segment.status == "green",
            "score": segment.validation_score,
        },
    }


def _render_simple(template: str, variables: dict) -> str:
    """简易 ${var} 替换（容错：缺失变量替换为空串而非抛错）"""
    import re as _re
    def _sub(m):
        key = m.group(1)
        return str(variables.get(key, ""))
    return _re.sub(r"\$\{(\w+)\}", _sub, template)


@router.post("/segments/{segment_id}/refactor")
async def refactor_segment(
    segment_id: str,
    req: RefactorSegmentRequest,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """重构段落（红-绿-重构循环）"""
    service = EpisodeSegmentService(db)
    try:
        segment = service.refactor_segment(segment_id, req.content, req.reason)
        return {
            "segment": segment.to_dict(),
            "remaining_refactors": segment.max_refactors - segment.refactor_count,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/segments/{segment_id}/complete")
async def complete_segment(
    segment_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """完成段落（绿状态确认）"""
    service = EpisodeSegmentService(db)
    try:
        segment = service.complete_segment(segment_id)
        return {"segment": segment.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions/{session_id}/episodes/{episode_no}/progress")
async def get_segment_progress(
    session_id: str,
    episode_no: int,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """获取段落进度和阻塞状态"""
    service = EpisodeSegmentService(db)
    progress = service.get_segment_progress(session_id, episode_no)
    return progress


@router.get("/sessions/{session_id}/episodes/{episode_no}/assembly")
async def get_episode_assembly(
    session_id: str,
    episode_no: int,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """组装完整的剧集内容"""
    service = EpisodeSegmentService(db)
    content = service.get_episode_assembly(session_id, episode_no)
    return {"content": content}


# ─────────────────────────────────────────────────────────
# 阻塞式评审API
# ─────────────────────────────────────────────────────────

@router.post("/segments/{segment_id}/reviews")
async def create_segment_review(
    segment_id: str,
    req: CreateSegmentReviewRequest,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """创建段落实时评审"""
    service = EpisodeSegmentService(db)

    segment = service.get_segment(segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="段落不存在")

    review = service.create_segment_review(
        segment_id=segment_id,
        session_id=segment.session_id,
        verdict=req.verdict,
        comments=req.comments,
        issues=req.issues,
        rewrite_suggestion=req.rewrite_suggestion,
        is_blocking=req.is_blocking,
        reviewed_by="user",
        score=req.score,
    )

    db.commit()

    return {
        "review": review.to_dict(),
        "blocking": req.is_blocking and req.verdict == "block",
    }


@router.get("/segments/{segment_id}/reviews")
async def get_segment_reviews(
    segment_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """获取段落的评审记录"""
    service = EpisodeSegmentService(db)
    reviews = service.get_segment_reviews(segment_id)
    return {"reviews": [r.to_dict() for r in reviews]}


@router.post("/reviews/{review_id}/resolve")
async def resolve_review(
    review_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """解决评审（取消阻塞）"""
    service = EpisodeSegmentService(db)
    try:
        review = service.resolve_review(review_id)
        db.commit()
        return {"review": review.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─────────────────────────────────────────────────────────
# 步骤质量门API（gstack式阻塞）
# ─────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/steps/{step_id}/gate")
async def get_step_gate(
    session_id: str,
    step_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """获取步骤质量门状态"""
    service = EpisodeSegmentService(db)
    gate = service.get_or_create_step_gate(session_id, step_id)

    # 评估最新状态
    gate = service.evaluate_step_gate(session_id, step_id)

    can_pass, reason = gate.can_pass()

    return {
        "gate": gate.to_dict(),
        "can_pass": can_pass,
        "reason": reason,
    }


@router.post("/sessions/{session_id}/steps/{step_id}/gate/pass")
async def pass_step_gate(
    session_id: str,
    step_id: str,
    req: PassGateRequest,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """通过步骤质量门"""
    service = EpisodeSegmentService(db)

    if req.bypass:
        # 绕过质量门
        gate = service.get_or_create_step_gate(session_id, step_id)
        gate.bypass(by="user", reason=req.reason)
        db.commit()
        return {"gate": gate.to_dict(), "bypassed": True}

    try:
        gate = service.pass_step_gate(session_id, step_id, by="user")
        db.commit()
        return {"gate": gate.to_dict(), "bypassed": False}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions/{session_id}/can-proceed")
async def can_proceed_to_next_step(
    session_id: str,
    current_step: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """检查是否可以进入下一步（核心阻塞API）"""
    service = EpisodeSegmentService(db)
    can_proceed, reason = service.can_proceed_to_next_step(session_id, current_step)

    return {
        "can_proceed": can_proceed,
        "reason": reason,
        "current_step": current_step,
    }


# ─────────────────────────────────────────────────────────
# 并行生成API
# ─────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/parallel-ready")
async def get_parallel_ready_segments(
    session_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """获取可以并行生成的段落"""
    service = EpisodeSegmentService(db)
    segments = service.get_parallel_ready_segments(session_id)

    return {
        "segments": [s.to_dict() for s in segments],
        "count": len(segments),
    }


# ─────────────────────────────────────────────────────────
# 批量操作API
# ─────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/episodes/{episode_no}/initialize")
async def initialize_episode_segments(
    session_id: str,
    episode_no: int,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """手动初始化一集的段落（通常自动调用）"""
    service = EpisodeSegmentService(db)
    segments = service.initialize_episode_segments(session_id, episode_no)
    db.commit()

    return {
        "segments": [s.to_dict() for s in segments],
        "message": f"已初始化 {len(segments)} 个段落",
    }


@router.get("/sessions/{session_id}/all-segments")
async def get_all_session_segments(
    session_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """获取会话的所有段落（用于总览）"""
    from app.models.episode_segment import EpisodeSegment

    segments = (
        db.query(EpisodeSegment)
        .filter_by(session_id=session_id)
        .order_by(EpisodeSegment.episode_no.asc(), EpisodeSegment.sequence.asc())
        .all()
    )

    # 按集数分组
    episodes = {}
    for seg in segments:
        ep = seg.episode_no
        if ep not in episodes:
            episodes[ep] = []
        episodes[ep].append(seg.to_dict())

    # 统计
    total_done = sum(1 for s in segments if s.status == "done")
    total_segments = len(segments)

    return {
        "episodes": episodes,
        "summary": {
            "total_segments": total_segments,
            "completed": total_done,
            "percent": int((total_done / total_segments) * 100) if total_segments > 0 else 0,
        },
    }
