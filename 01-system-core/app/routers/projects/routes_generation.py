"""AI 生成任务 + 大纲分析（从 projects_v2.py 抽出）。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from sqlalchemy import desc
from pydantic import BaseModel, Field
import hashlib
import asyncio
import uuid
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_project_actor
from app.database import get_db
from app.models.project_v2 import (
    Checkpoint,
    ContentVersion,
    ContributionLedger,
    Episode,
    GenerationJob,
    ModelProvider,
    ProjectV2,
    Scene,
)

from app.routers.projects._schemas import (
    CharacterStoreRequest,
    CharacterStoreResponse,
    ContentSaveRequest,
    ContributionResponse,
    DiffResponse,
    EpisodeCreateRequest,
    EpisodeResponse,
    GenerationRequest,
    GenerationResponse,
    GenerationResult,
    ModelProviderRequest,
    ProjectConfig,
    ProjectConfigPatch,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    ProjectWorkflowContextRequest,
    ProjectWorkflowContextResponse,
    SceneCreateRequest,
    SceneResponse,
    StoryStateCardStoreRequest,
    StoryStateCardStoreResponse,
    VersionResponse,
)
from app.services.saas_access_service import ensure_access_key_can_spend
from app.services.c19_178_safe_label_gate import C19178GateBlocked, assert_c19_178_runtime_gate
from app.routers.projects._helpers import (
    REPO_ROOT,
    WORKSPACE_ROOT,
    _build_project_response,
    _calculate_contribution_score,
    _calculate_diff,
    _default_workflow_context,
    _deep_merge_dict,
    _derive_word_count_range,
    _generation_job_artifact_file_path,
    _get_project_for_actor_or_404,
    _get_next_checkpoint_code,
    _get_next_version_code,
    _get_workspace_path,
    _init_workspace,
    _load_workspace_project_data,
    _merge_episode_memory_cards,
    _normalize_canon_packet,
    _normalize_episode_memory_cards,
    _normalize_project_config_payload,
    _normalize_state_cards_payload,
    _normalize_workflow_context,
    _recommend_classification_tracks,
    _sync_workspace_project_index,
    _update_contribution_ledger,
    _write_workspace_project_data,
)

router = APIRouter()  # 无 prefix；由 projects_v2.py 的主 router 加 prefix 聚合

import logging
import sys
from string import Template

logger = logging.getLogger(__name__)


def _assert_c19_178_episode_generation_gate(db: Session, project: ProjectV2) -> None:
    try:
        assert_c19_178_runtime_gate(db, project=project, target_path="episode5_entry")
    except C19178GateBlocked as exc:
        raise HTTPException(status_code=409, detail=exc.decision.reason_code) from exc

# 把 skills/lib 加入 sys.path（projects_v2.py 顶部的旧逻辑）
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills" / "lib"))

try:
    from state_manager import StateManager, ProjectIndex
except ImportError:
    StateManager = None
    ProjectIndex = None

from app.services.text_generation_service import generate_text
from app.services.text_generation_service import begin_usage_collection, end_usage_collection
from app.services.short_drama_advanced_generation import (
    build_profile_generation_prompt,
    generation_system_prompt_for_profile,
    match_advanced_generation_profile,
    resolve_step_generation_route,
)
from app.services.acceptance_criteria_service import run_acceptance_checks
from app.services.short_drama_quality_helpers import build_acceptance_gate_warning


def _provider_pricing_config(provider: ModelProvider | None) -> dict[str, Any]:
    if not provider:
        return {}
    return {
        "input_cost_per_1k": provider.input_cost_cny_per_1k,
        "output_cost_per_1k": provider.output_cost_cny_per_1k,
        "billing_multiplier": provider.billing_multiplier,
        "minimum_actual_cost_cny": provider.minimum_actual_cost_cny,
    }


@router.post("/{project_id}/generate", response_model=GenerationResponse, summary="创建AI生成任务")
async def create_generation_job(
    project_id: str,
    req: GenerationRequest,
    background_tasks: BackgroundTasks,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """创建AI生成任务，异步执行"""
    from app.services.text_generation_service import get_generation_settings

    project = _get_project_for_actor_or_404(db, project_id, actor)
    _assert_c19_178_episode_generation_gate(db, project)

    # 确定使用的提供商和模型。优先级：
    # 1. 显式 provider_id
    # 2. 默认 ModelProvider
    # 3. 项目绑定 generation_provider / generation_model
    provider_id = req.provider_id
    provider = None
    generation_config: dict[str, Any] = {}

    if provider_id:
        provider = db.query(ModelProvider).filter(ModelProvider.id == provider_id).first()
        if not provider:
            raise HTTPException(status_code=404, detail="模型提供商不存在")
        generation_config = {
            "provider_type": provider.provider_type,
            "base_url": provider.base_url,
            "api_key": provider.api_key,
            "model_name": req.model_name or provider.default_model,
            **_provider_pricing_config(provider),
        }
    else:
        default_provider = db.query(ModelProvider).filter(ModelProvider.is_default == True).first()
        if default_provider:
            provider = default_provider
            provider_id = default_provider.id
            generation_config = {
                "provider_type": default_provider.provider_type,
                "base_url": default_provider.base_url,
                "api_key": default_provider.api_key,
                "model_name": req.model_name or default_provider.default_model,
                **_provider_pricing_config(default_provider),
            }
        else:
            project_config = project.get_config() if hasattr(project, "get_config") else {}
            project_provider = str(project_config.get("generation_provider") or "").strip()
            project_model = str(req.model_name or project_config.get("generation_model") or "").strip()
            settings = get_generation_settings(provider=project_provider or None, model=project_model or None)
            if not settings.get("enabled") or not settings.get("base_url") or not settings.get("api_key") or not settings.get("model"):
                raise HTTPException(status_code=400, detail="未指定模型提供商且项目/系统默认生成配置不可用")
            generation_config = {
                "provider_type": settings["provider"] or project_provider,
                "base_url": settings["base_url"],
                "api_key": settings["api_key"],
                "model_name": settings["model"],
            }

    model_name = generation_config["model_name"]

    if actor.is_user:
        try:
            ensure_access_key_can_spend(db, actor.access_key_id)
        except ValueError as exc:
            raise HTTPException(status_code=402, detail=str(exc)) from exc

    # 创建任务
    job = GenerationJob(
        project_id=project_id,
        job_type=req.job_type,
        episode_number=req.episode_number,
        scene_number=req.scene_number,
        provider_id=provider_id,
        model_name=model_name,
        status="pending",
        created_by="admin" if actor.is_admin else actor.access_key_id,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    # 后台执行任务
    background_tasks.add_task(
        execute_generation_job,
        job.id,
        project_id,
        req,
        generation_config
    )

    return GenerationResponse(
        job_id=job.id,
        status="pending",
        message="生成任务已创建"
    )


@router.get("/{project_id}/generate/{job_id}", response_model=GenerationResult, summary="获取生成任务状态")
async def get_generation_status(
    project_id: str,
    job_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """获取AI生成任务状态和结果"""
    _get_project_for_actor_or_404(db, project_id, actor)
    job = db.query(GenerationJob).filter(
        GenerationJob.id == job_id,
        GenerationJob.project_id == project_id
    ).first()

    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    result = None
    if job.result_path and Path(job.result_path).exists():
        result = Path(job.result_path).read_text(encoding="utf-8")

    return GenerationResult(
        job_id=job.id,
        status=job.status,
        content=result,
        progress=job.progress,
        prompt_tokens=job.prompt_tokens,
        completion_tokens=job.completion_tokens,
        total_tokens=job.total_tokens,
        error_message=job.error_message or None,
        gate_warning=job.gate_warning or "",
    )


async def execute_generation_job(
    job_id: str,
    project_id: str,
    req: GenerationRequest,
    generation_config: dict[str, Any]
):
    """执行AI生成任务（后台）"""
    from app.database import SessionLocal
    from app.services.text_generation_service import generate_text
    from app.services.evidence_event_service import record_evidence_event
    from app.services.saas_access_service import (
        charge_access_key_for_generation,
        record_generation_failure_without_charge,
    )

    db = SessionLocal()

    try:
        job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
        if not job:
            return

        job.status = "running"
        job.started_at = datetime.now()
        db.commit()

        # 构建提示词
        prompt = req.prompt_override or await build_generation_prompt(
            db, project_id, req.job_type, req.episode_number, req.scene_number
        )

        project = db.query(ProjectV2).filter(ProjectV2.id == project_id).first()

        # 保存提示词
        prompt_path = _generation_job_artifact_file_path(
            project,
            job_id=job_id,
            artifact_type="prompts",
            suffix=".txt",
        )
        prompt_path.write_text(prompt, encoding="utf-8")
        job.prompt_path = str(prompt_path)
        db.commit()

        project_config = project.get_config() if project and hasattr(project, "get_config") else {}
        profile_id = str(project_config.get("advanced_generation_profile_id") or "")
        if not profile_id and project:
            profile_id = str(match_advanced_generation_profile(project.project_type).get("id") or "short_drama")

        usage, usage_token = begin_usage_collection()
        try:
            # 调用模型生成
            result_text = await asyncio.to_thread(
                generate_text,
                system_prompt=generation_system_prompt_for_profile(profile_id),
                user_prompt=prompt,
                provider=generation_config.get("provider_type"),
                base_url=generation_config.get("base_url"),
                api_key=generation_config.get("api_key"),
                model=generation_config.get("model_name"),
                temperature=req.temperature,
            )
        finally:
            end_usage_collection(usage_token)

        job.prompt_tokens = int(usage.get("input_tokens") or 0)
        job.completion_tokens = int(usage.get("output_tokens") or 0)
        job.total_tokens = int(usage.get("total_tokens") or 0)
        if project and req.job_type in {"scene_draft", "script_draft", "continuation", "revision"}:
            track = str(project.genre_sub or project.genre_main or "短剧")
            checks = run_acceptance_checks(
                {"text": result_text, "summary": ""},
                track=track,
                previous_episodes=None,
            )
            job.gate_warning = build_acceptance_gate_warning(checks, "")

        result_path = _generation_job_artifact_file_path(
            project,
            job_id=job_id,
            artifact_type="results",
            suffix=".md",
        )
        result_path.write_text(result_text, encoding="utf-8")

        if job.created_by and job.created_by != "admin":
            charge_access_key_for_generation(
                db,
                job.created_by,
                prompt_tokens=job.prompt_tokens,
                completion_tokens=job.completion_tokens,
                provider=str(generation_config.get("provider_type") or ""),
                model=str(generation_config.get("model_name") or ""),
                generation_type=job.job_type,
                reason=f"项目生成任务 {job.id} 成功扣费",
                input_cost_per_1k=generation_config.get("input_cost_per_1k"),
                output_cost_per_1k=generation_config.get("output_cost_per_1k"),
                billing_multiplier=generation_config.get("billing_multiplier"),
                minimum_actual_cost_cny=generation_config.get("minimum_actual_cost_cny"),
            )

        # 结果文件写入和扣费都成功后再暴露 completed，避免“日志成功但无产物”。
        job.result_path = str(result_path)
        job.status = "completed"
        job.progress = 100
        job.completed_at = datetime.now()
        record_evidence_event(
            db,
            project_id=project_id,
            actor=None,
            event_type="ai_generation_completed",
            target_type="generation_job",
            target_id=job.id,
            content_hash=hashlib.sha256(result_text.encode("utf-8")).hexdigest(),
            summary=f"{job.job_type} 生成完成",
            metadata={
                "episode_number": job.episode_number,
                "scene_number": job.scene_number,
                "created_by": job.created_by,
                "model_name": job.model_name,
                "total_tokens": job.total_tokens,
            },
        )

        db.commit()

    except Exception as e:
        job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = str(e)
            db.commit()
            if job.created_by and job.created_by != "admin":
                record_generation_failure_without_charge(
                    db,
                    job.created_by,
                    provider=str(generation_config.get("provider_type") or ""),
                    model=str(generation_config.get("model_name") or ""),
                    generation_type=job.job_type,
                    reason=f"项目生成任务 {job.id} 失败，未扣费：{e}",
                )

    finally:
        db.close()


async def build_generation_prompt(
    db: Session,
    project_id: str,
    job_type: str,
    episode_number: int,
    scene_number: Optional[int]
) -> str:
    """构建生成提示词"""
    project = db.query(ProjectV2).filter(ProjectV2.id == project_id).first()

    project_payload = {
        "name": project.name,
        "description": project.description,
        "project_type": project.project_type,
        "audience_axis": project.audience_axis,
        "genre_main": project.genre_main,
        "genre_sub": project.genre_sub,
        "config": project.get_config() if hasattr(project, "get_config") else {},
    }
    context_parts = [
        build_profile_generation_prompt(
            project_payload,
            job_type=job_type,
            episode_number=episode_number,
            scene_number=scene_number,
        )
    ]

    # 加载角色信息
    # TODO: 从characters目录加载

    # 加载前集摘要
    if episode_number > 1:
        prev_episode = db.query(Episode).filter(
            Episode.project_id == project_id,
            Episode.episode_number == episode_number - 1
        ).first()
        if prev_episode and prev_episode.summary:
            context_parts.append(f"\n## 前集摘要\n{prev_episode.summary}")

    # 短剧旧任务保留一点兼容提示；其他形态的任务说明由 profile prompt 生成。
    if job_type == "scene_draft" and "短剧" in str(project.project_type or ""):
        context_parts.append(f"\n## 任务\n请创作第{episode_number}集")
        if scene_number:
            context_parts.append(f"第{scene_number}场")

    return "\n\n".join(context_parts)



# ============================================================

_OUTLINE_ANALYZE_SYSTEM = """你是一位短剧剧本分析专家，从大纲原文中结构化提取全部信息并按 JSON 返回。

【第一步（内部操作，不输出）】先判断原文是否存在“人物小传/人物设定/角色设定/角色库/主要角色/角色列表/人物设定表格”等明确人物资料。
【第二步】只提取明确人物资料里的角色；如果只是正文对白、快剪画面、场景动作、人：出场名单，不能写入 characters。

角色提取规则（严格遵守）：
- 每个字段只写大纲中真实存在的内容，大纲没有的留空字符串 ""，禁止编造。
- 没有人物小传/人物设定/角色表格时，characters 返回 []，不要从对白、快剪、正文里猜角色。
- characters.info 只能写人物设定：年龄、身份、职业/阵营、外貌、性格、说话方式、背景出身、目标/动机、弱点、人物弧线、与主线的功能、明确人物关系。
- 禁止把分集集纲、正文台词、场景动作、主场景、关系变化、信息揭露、爽点类型、转折爆点、阶段任务写进 characters.info。
- 角色只在剧情里出现但没有人物设定时，info 留空字符串 ""，不要用本集剧情代替人物小传。
- 角色关系只写“人物关系/角色关系/关系设计/关系表”中明确写出的，不推断。
- 若大纲某集包含实际台词/对白，逐字提取到 existing_script；纯情节概述不算。
- 集纲只按“第N集/第N级”识别；“1-1/2-1/第N场”是场次正文的一部分，不要拆成集纲。

返回格式（纯 JSON，无多余文字）：
{
  "genre": {
    "category": "大类别",
    "subCategory": "细分题材",
    "target": "目标受众",
    "confidence": 0.0到1.0
  },
  "sellingPoints": {
    "logline": "一句话梗概：主角+核心处境+核心冲突（不是题材/品类总结）",
    "worldview": "世界观/背景设定：时代、地点、规则、特殊世界设定（与金手指分开写）",
    "conflict": "全剧主要矛盾",
    "uniqueness": "金手指/特殊能力/差异化核心设定（完整描述，不截断）",
    "marketFit": 1到10的整数,
    "suggestions": ["建议1", "建议2"]
  },
  "characters": [
    {
      "id": "char-N",
      "name": "角色真实姓名（只写名字，不含括号说明）",
      "role": "protagonist|antagonist|supporting|minor",
      "info": "人物小传摘要，只允许写人物设定；没有明确设定则留空，绝不能粘贴集纲/正文/场景动作。"
    }
  ],
  "structure": {
    "pacing": "slow|medium|fast",
    "rhythm": ["节奏点1", "节奏点2"],
    "issues": ["问题1", "问题2"],
    "suggestions": ["建议1", "建议2"]
  },
  "episodes": [
    {
      "id": "ep-N",
      "episodeNumber": 集数（整数）,
      "title": "本集标题",
      "episode_outline": "本集集纲：这一集具体发生的事件",
      "plotPoints": [
        {
          "id": "pp-N-M",
          "type": "setup|inciting|rising|climax|falling|resolution",
          "content": "情节描述",
          "purpose": "作用",
          "emotion": "情绪",
          "suggestions": ["建议"]
        }
      ],
      "emotionArc": [
        {"stage": "阶段名", "level": 1-10, "description": "描述"}
      ],
      "scenes": [],
      "conflict": "本集核心冲突（一句话，描述这集最主要的矛盾焦点）",
      "turning": "本集转折/爆点，不写尾钩",
      "existing_script": "如果大纲原文中包含本集的实际剧本台词、场景描述或对白段落，逐字完整提取；若无则留空字符串",
      "evaluation": {
        "pacing": 1-10,
        "tension": 1-10,
        "completeness": 1-10,
        "issues": ["问题"],
        "suggestions": ["建议"]
      }
    }
  ]
}"""


def _infer_outline_target_episodes(outline: str) -> int:
    """Infer desired episode count from ranges like 前10集/10-20集/后30集."""
    import re

    candidates: list[int] = []
    for match in re.finditer(r"(\d{1,3})\s*[—\-~～至到]\s*(\d{1,3})\s*集?", outline or ""):
        for group in (1, 2):
            try:
                value = int(match.group(group))
            except Exception:
                continue
            if 1 <= value <= 200:
                candidates.append(value)
    for match in re.finditer(r"(?:第\s*)?(\d{1,3})\s*集", outline or ""):
        try:
            value = int(match.group(1))
        except Exception:
            continue
        if 1 <= value <= 200:
            candidates.append(value)
    for match in re.finditer(r"(?:前|中间|后)\s*(\d{1,3})\s*集", outline or ""):
        try:
            value = int(match.group(1))
        except Exception:
            continue
        if 1 <= value <= 200:
            candidates.append(value)
    return max(candidates) if candidates else 0


OUTLINE_ANALYZE_TIMEOUT_SECONDS = 18
OUTLINE_ANALYZE_EPISODE_CAP = 60
OUTLINE_ANALYZE_FAST_FALLBACK_CHARS = 5000
OUTLINE_UPLOAD_MAX_BYTES = 8 * 1024 * 1024
OUTLINE_UPLOAD_TEXT_MAX_CHARS = 300_000
# 集纲改走分批真实生成（不再单次大调用），外层等待需覆盖多批耗时
OUTLINE_EPISODE_GENERATE_TIMEOUT_SECONDS = 600
# 单批（默认 8 集）真实生成需要的时间，强模型远超 20s
OUTLINE_EPISODE_GENERATE_BATCH_TIMEOUT_SECONDS = 95
OUTLINE_EPISODE_GENERATE_BATCH_SIZE = 8
# 预测调用只产出元信息（梗概/世界观/极纲/人物），输出小，45s 足够且更稳
OUTLINE_PREDICT_TIMEOUT_SECONDS = 45

_OUTLINE_NAME_VARIANTS = str.maketrans({
    "铮": "争",
    "征": "争",
    "峥": "争",
})

_OUTLINE_SCENE_ROTATION = [
    "公司会议室",
    "地下车库",
    "医院走廊",
    "直播间",
    "家族老宅",
    "废弃实验室",
    "警局门口",
    "新闻发布会",
    "餐厅包厢",
    "旧仓库",
    "法庭外",
    "学校礼堂",
    "酒店电梯",
    "码头",
    "董事会",
    "出租屋",
]

_OUTLINE_ACTION_ROTATION = [
    "拿到关键证据副本",
    "公开一段被压下的录音",
    "追踪异常转账记录",
    "逼问唯一目击者",
    "抢在对手前签下关键协议",
    "救下被胁迫的证人",
    "反向设局诱出内鬼",
    "冻结对手手里的筹码",
    "把证据交到能公开发声的人手里",
    "拆穿对手准备好的伪证",
    "转移关键人物避免灭口",
    "正面对峙幕后操盘者",
    "用已有资源换取更高代价的真相",
    "联合旧敌完成一次反制",
    "让旁观者亲眼看见真相",
    "把前一集未兑现的信息落到具体后果",
]

_OUTLINE_INFO_ROTATION = [
    "确认上一集留下的线索不是偶然",
    "发现对手阵营内部有人说谎",
    "知道关键证据被转移到新地点",
    "意识到亲近的人隐瞒了核心事实",
    "看见家族/组织规则第一次失效",
    "拿到能改变人物关系的新信息",
    "发现反派真正目标不是表面利益",
    "确认主角必须付出代价才能继续追查",
]

_OUTLINE_RELATIONSHIP_ROTATION = [
    "试探转为短暂结盟",
    "信任被打破后重新谈条件",
    "保护关系变成共同承担风险",
    "对立双方第一次交换底牌",
    "配角从旁观转为站队",
    "核心关系因新证据出现裂缝",
    "主角从被动解释转为主动安排",
    "反派从轻视转为正式围剿",
]

_OUTLINE_TURNING_ROTATION = [
    "证据是真的，但来源指向主角最不愿怀疑的人",
    "对手以为已经毁掉证据，备份却在第三方手里出现",
    "主角赢下当场，却因此暴露更大的弱点",
    "被救的人反过来拿出一条更危险的线索",
    "表面盟友突然改口，迫使主角当场换策略",
    "围观者开始倒向主角，但代价立刻落到核心关系上",
    "旧秘密只揭开一半，新的行动必须马上开始",
    "对手的失败不是结局，而是引出更高层压力",
]

_OUTLINE_SATISFACTION_ROTATIONS = {
    "男频": ["S1 亮牌逆袭", "S2 围观打脸", "S3 规则兑现", "S12 身份暴露", "S13 连续反转"],
    "女频": ["S5 伤害被看见", "S6 关系反转", "S7 反击得偿", "S8 偏爱公开", "S13 连续反转"],
    "混合": ["S12 身份暴露", "S13 连续反转", "S14 现实代价", "S2 围观打脸", "S6 关系反转"],
}

_OUTLINE_HOOK_ROTATIONS = {
    "男频": ["H1 预示冲突", "H3 重要决定", "H7 新想法", "H4 震惊宣布", "H6 颠覆突转"],
    "女频": ["H4 震惊宣布", "H6 颠覆突转", "H5 激烈情绪", "H11 转折点", "H8 未答问题"],
    "悬疑": ["H2 秘密", "H6 颠覆突转", "H8 未答问题", "H9 神秘对白", "H10 预言异象"],
    "混合": ["H2 秘密", "H4 震惊宣布", "H6 颠覆突转", "H8 未答问题", "H11 转折点"],
}

_OUTLINE_CHARACTER_ROLE_MAP = {
    "男主": "protagonist",
    "女主": "protagonist",
    "主角": "protagonist",
    "男二": "supporting",
    "女二": "supporting",
    "配角": "supporting",
    "反派": "antagonist",
    "龙套": "minor",
}


def _compact_outline_analysis_text(value: Any, *, limit: int = 240) -> str:
    text = str(value or "")
    text = " ".join(text.replace("\r", "\n").split())
    return text[:limit].strip()


def _outline_character_role(label: str, index: int) -> str:
    normalized = str(label or "").strip()
    if normalized:
        # 直接保留 /outline/analyze 输出的规范英文角色，避免被位置规则降级
        if normalized.lower() in {"protagonist", "antagonist", "supporting", "minor"}:
            return normalized.lower()
        for key, role in _OUTLINE_CHARACTER_ROLE_MAP.items():
            if key in normalized:
                return role
    return "protagonist" if index == 0 else "supporting" if index == 1 else "minor"


def _clean_outline_character_name(value: str) -> str:
    import re

    name = re.sub(r"[（(].*?[）)]", "", str(value or "")).strip()
    name = re.sub(r"^(?:和|与|及|、|是|叫|为|的|了)+", "", name).strip()
    name = re.sub(r"(?:是|为|作为|，|,|。|；|;).*?$", "", name).strip()
    name = re.sub(r"(?:为了|被迫|想要|发现|掌握|保护|追查|提出|进入|作为|因为|需要|可能|身份|地位).*$", "", name).strip()
    return name


_OUTLINE_NON_CHARACTER_NAMES = {
    "故事大纲", "人物小传", "人物设定", "角色小传", "角色设定", "角色介绍", "一句话梗概", "梗概",
    "第一集", "第二集", "第三集", "第四集", "第五集", "第六集", "第七集", "第八集", "第九集", "第十集",
    "第一场", "第二场", "第三场", "第四场", "第五场", "场景", "时间", "地点", "正文", "原文",
    "范围集纲", "详细集纲", "分集集纲", "分集框架", "集纲", "剧情大纲", "故事背景",
    "核心冲突", "金手指", "世界观", "特殊设定", "爽点", "尾钩", "钩子", "转折", "爆点",
    "外貌参考", "外貌", "外观", "视觉档案", "视觉文档", "视觉设定",
    "处理方式", "主卖点", "核心卖点", "高位弃", "主要角色", "主要人物", "角色关系", "人物关系",
    "公开", "曝光", "揭露", "设局", "追杀", "反派公开", "反派动作", "证据公开",
    "系统", "新角色", "人物", "主卖点", "次卖点", "一阶段主线", "二阶段主线", "三阶段主线",
    "其余改编处理", "必须付出代价", "赢下当场", "资源减少", "筹码增多", "当场换策略",
    "最不愿怀疑的", "下场", "新想法", "震惊宣布", "颠覆突转", "重要决定",
    # 大纲常见的小节标题（label_re 会把“XX：”误当成角色）
    "大纲走向", "故事主线", "主线写法", "故事看点", "故事亮点", "故事概述", "内容简介",
    "故事简介", "剧名", "类型", "题材", "简介", "看点", "标题", "核心人物", "故事走向", "剧情走向",
    # 纯亲属/角色定位称谓（不是具体姓名）
    "继母", "后妈", "养母", "生母", "继父", "养父", "父亲", "母亲", "妹妹", "姐姐", "哥哥", "弟弟",
    "女儿", "儿子", "同父异母妹妹", "异母妹妹", "异母弟弟", "男主", "女主", "男二", "女二",
    "主角", "配角", "反派", "龙套",
}

_OUTLINE_NON_CHARACTER_PATTERN = (
    r"方式|处理|设定|冲突|集纲|剧情|正文|原文|角色|人物|关系|主线|支线|爽点|钩子|尾钩|"
    r"走向|剧名|题材|简介|看点|亮点|身世|推进|落定|启程|亮相|登场|归来|"
    r"卖点|世界观|金手指|内容|阶段|事件|反转|爆点|场景|时间|地点|规则|模板|框架|"
    r"外貌|外观|视觉档案|视觉文档|视觉设定|"
    r"高位弃|低位|身份|地位|公开|曝光|揭露|设局|追杀|阻止|压制|逼迫|威胁|控制|"
    r"旁观|被动|解释|主动|真正|目标|轻视|代价|赢下|当场|资源|筹码|策略|怀疑|"
    r"站队|围剿|结盟|承担|风险|证据|地点|确认|知道|震惊|宣布|颠覆|突转|决定|"
    r"第[一二三四五六七八九十百\d]{1,4}(?:集|场)"
)

_OUTLINE_CHARACTER_INFO_STOP_PATTERN = (
    r"(?:^|\n|\r|\s)(?:"
    r"主场景|关系变化|信息揭露|爽点类型|本集冲突|转折/爆点|转折爆点|"
    r"第\s*[一二三四五六七八九十百\d]{1,4}\s*(?:集|级)|"
    r"改编问题及解决方案|卖点概述|参考对标|故事概括|范围集纲|详细集纲|分集集纲|"
    r"一阶段主线|二阶段主线|三阶段主线"
    r")\s*[：:]?"
)

_OUTLINE_CHARACTER_SECTION_LABELS = {
    "人物小传", "人物设定", "角色小传", "角色设定", "角色介绍", "角色库", "主要角色", "角色列表", "人物",
}

_OUTLINE_CHARACTER_TABLE_LABELS = {
    "人物小传", "人物设定", "角色小传", "角色设定", "角色介绍", "角色库", "主要角色", "角色列表",
}

_OUTLINE_CHARACTER_TABLE_SUBFIELDS = {
    "年龄", "身份", "职业", "阵营", "外貌", "外貌参考", "外观", "参考例图", "视觉档案", "视觉文档", "视觉设定",
    "人物性格", "性格", "说话方式", "声线", "音色", "动机", "目标", "弱点", "人物弧线", "弧线", "成长",
    "背景", "身世背景", "出身", "功能", "关系", "人物关系", "角色关系", "备注",
}

_OUTLINE_CHARACTER_BIO_HINTS = (
    "年龄", "岁", "身份", "职业", "外貌", "外观", "性格", "说话", "语气", "音色",
    "动机", "目标", "欲望", "弱点", "弧线", "成长", "背景", "出身", "身世",
    "关系", "阵营", "功能", "主角", "配角", "反派", "龙套", "少年", "少女",
    "青年", "中年", "首领", "领袖", "继承人", "证据持有人", "巫观", "堂仙",
)

_OUTLINE_PLOT_ACTION_HINTS = (
    "第", "集", "场", "正文", "主场景", "关系变化", "信息揭露", "爽点类型",
    "发现", "拿到", "进入", "追查", "追杀", "围堵", "拦住", "递来", "封山",
    "承认", "派人", "逼迫", "偷袭", "吞噬", "安排", "站队", "揭露", "反制",
    "转为", "继续", "开始", "随后", "最终", "当场", "赢下", "失效",
)


def _outline_is_valid_character_name(name: str) -> bool:
    import re

    cleaned = _clean_outline_character_name(name)
    if not cleaned or cleaned in _OUTLINE_NON_CHARACTER_NAMES:
        return False
    if len(cleaned) < 2 or len(cleaned) > 6:
        return False
    if not re.fullmatch(r"[\u4e00-\u9fa5]{2,6}", cleaned):
        return False
    if re.search(_OUTLINE_NON_CHARACTER_PATTERN, cleaned):
        return False
    return True


def _outline_character_info_is_polluted(value: str) -> bool:
    import re

    text = str(value or "")
    if not text.strip():
        return False
    marker_count = len(re.findall(_OUTLINE_CHARACTER_INFO_STOP_PATTERN, text))
    episode_count = len(re.findall(r"第\s*[一二三四五六七八九十百\d]{1,4}\s*(?:集|级)", text))
    scaffold_hits = sum(
        1
        for word in ["主场景", "关系变化", "信息揭露", "爽点类型", "本集冲突", "转折/爆点", "卖点概述", "故事概括"]
        if word in text
    )
    return marker_count >= 2 or episode_count >= 1 or scaffold_hits >= 2


def _outline_character_info_is_plot_text(value: str) -> bool:
    import re

    text = _compact_outline_analysis_text(value, limit=600)
    if not text:
        return False
    if re.search(r"【\s*场|场\s*\d+[-－]\d+|[\u4e00-\u9fa5]{2,6}\s*[：:][“\"「]?", text):
        bio_label_re = (
            r"(?:^|[；;\n])\s*(?:年龄|身份|职业|阵营|外貌|外观|视觉档案|视觉文档|视觉设定|"
            r"人物性格|性格|说话方式|声线|音色|动机|目标|弱点|人物弧线|弧线|成长|背景|身世背景|身世|出身|功能|关系)\s*[：:]"
        )
        dialogue_or_scene_re = (
            r"【\s*场|场\s*\d+[-－]\d+|"
            r"(?:^|[；;\n])\s*(?!(?:年龄|身份|职业|阵营|外貌|外观|视觉档案|视觉文档|视觉设定|"
            r"人物性格|性格|说话方式|声线|音色|动机|目标|弱点|人物弧线|弧线|成长|背景|身世背景|身世|出身|功能|关系)\s*[：:])"
            r"[\u4e00-\u9fa5]{2,6}\s*[：:][“\"「]?"
        )
        return bool(re.search(dialogue_or_scene_re, text)) and not bool(re.fullmatch(rf"(?:{bio_label_re}.+)(?:[；;]\s*{bio_label_re}.+)*", text))
    if re.search(r"第\s*[一二三四五六七八九十百\d]{1,4}\s*(?:集|场|级)", text):
        return True
    bio_hits = sum(1 for word in _OUTLINE_CHARACTER_BIO_HINTS if word in text)
    action_hits = sum(1 for word in _OUTLINE_PLOT_ACTION_HINTS if word in text)
    return bio_hits == 0 and action_hits >= 2


def _sanitize_outline_character_info(value: Any, *, name: str = "", limit: int = 1000) -> str:
    """Keep character-card text inside the character boundary, not episode/prediction scaffolds."""
    import re

    raw = str(value or "").replace("\u00a0", " ").replace("\r", "\n")
    if not raw.strip():
        return ""
    cleaned_name = _clean_outline_character_name(name)
    kept: list[str] = []
    for line in raw.splitlines():
        compact = " ".join(line.split()).strip(" 　|")
        if not compact:
            continue
        if re.search(_OUTLINE_CHARACTER_INFO_STOP_PATTERN, compact):
            break
        if _outline_character_info_is_plot_text(compact):
            break
        if compact == "外貌参考":
            if kept:
                break
            continue
        visual_match = re.match(
            r"([\u4e00-\u9fa5]{2,6})\s+(?:\d{1,3}\s*岁|少年|少女|青年|中年|老年|男性|女性|男|女)",
            compact,
        )
        if visual_match and kept:
            other_name = _clean_outline_character_name(visual_match.group(1))
            if other_name and other_name != cleaned_name:
                break
        kept.append(compact)
    text = "\n".join(kept).strip()
    if not text:
        return ""
    stop = re.search(_OUTLINE_CHARACTER_INFO_STOP_PATTERN, text)
    if stop:
        text = text[:stop.start()].strip()
    text = _compact_outline_analysis_text(text, limit=limit)
    if _outline_character_info_is_plot_text(text):
        return ""
    if re.fullmatch(r"[-—~\s\d岁）()（）]+", text):
        return ""
    return text


def _outline_character_alias_key(name: str) -> str:
    import re

    cleaned = _clean_outline_character_name(name).translate(_OUTLINE_NAME_VARIANTS)
    return re.sub(r"\s+", "", cleaned)


def _outline_merge_unique_text(*values: str, limit: int = 1000) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _compact_outline_analysis_text(value, limit=limit)
        if not text:
            continue
        for part in [item.strip() for item in text.replace("\n", "；").split("；") if item.strip()]:
            if part in seen:
                continue
            seen.add(part)
            parts.append(part)
    return "；".join(parts)[:limit].strip()


def _outline_is_useful_character_info(value: str) -> bool:
    text = _compact_outline_analysis_text(value, limit=120)
    if _outline_character_info_is_polluted(value):
        return False
    if len(text) >= 12:
        return True
    return any(word in text for word in ["继承人", "证据", "掌握", "反派", "主角", "对手", "动机", "秘密", "目标"])


def _outline_character_scan_text(outline: str) -> str:
    import re

    text = str(outline or "")
    section = re.search(r"(?:人物小传|人物设定|角色小传|角色设定|角色介绍|角色库|主要角色|角色列表|人物)\s*[：:\n|]", text)
    if not section:
        return ""
    tail = text[section.end():]
    end = re.search(
        r"\n\s*(?:第\s*[一二三四五六七八九十百\d]{1,4}\s*集|分集|集纲|剧情大纲|故事大纲|人物关系|角色关系|关系设计)\s*[：:\-、]?",
        tail,
    )
    return tail[:end.start()] if end else tail


def _outline_character_table_field_label(label: str) -> str:
    normalized = str(label or "").strip()
    if normalized in {"参考例图", "外貌参考", "外貌", "外观", "视觉设定", "视觉文档"}:
        return "视觉档案"
    if normalized == "人物性格":
        return "性格"
    return normalized


def _extract_outline_character_table_blocks(outline: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    by_name: dict[str, dict[str, str]] = {}
    current_name = ""

    def append_info(name: str, role_hint: str = "", *parts: str) -> None:
        nonlocal current_name
        cleaned = _clean_outline_character_name(name)
        if not _outline_is_valid_character_name(cleaned):
            return
        current_name = cleaned
        role = _outline_character_role(role_hint, len(by_name))
        info = _sanitize_outline_character_info(
            "；".join(str(part).strip() for part in parts if str(part or "").strip()),
            name=cleaned,
            limit=900,
        )
        current = by_name.get(cleaned)
        if current:
            current["info"] = _outline_merge_unique_text(current.get("info", ""), info, limit=1200)
            if current.get("role") == "minor" and role in {"protagonist", "supporting", "antagonist"}:
                current["role"] = role
            return
        by_name[cleaned] = {"name": cleaned, "role": role, "info": info}
        rows.append(by_name[cleaned])

    def append_subfield(label: str, *parts: str) -> None:
        if not current_name or current_name not in by_name:
            return
        field_label = _outline_character_table_field_label(label)
        value = _sanitize_outline_character_info(
            "；".join(str(part).strip() for part in parts if str(part or "").strip()),
            name=current_name,
            limit=900,
        )
        if not value:
            return
        line = f"{field_label}：{value}" if field_label else value
        current = by_name[current_name]
        current["info"] = _outline_merge_unique_text(current.get("info", ""), line, limit=1200)

    inside_character_table = False
    for raw_line in str(outline or "").splitlines():
        if "|" not in raw_line:
            continue
        cells = [cell.strip(" 　") for cell in raw_line.split("|")]
        cells = [cell for cell in cells if cell]
        if len(cells) < 2:
            continue
        first = cells[0]
        if first in _OUTLINE_CHARACTER_TABLE_LABELS:
            inside_character_table = True
            subject = cells[1]
            payload = cells[2:]
        elif inside_character_table and first in _OUTLINE_CHARACTER_TABLE_SUBFIELDS and current_name:
            append_subfield(first, *cells[1:])
            continue
        elif inside_character_table and _outline_is_valid_character_name(first):
            subject = first
            payload = cells[1:]
        else:
            continue

        if subject in _OUTLINE_CHARACTER_TABLE_SUBFIELDS:
            append_subfield(subject, *payload)
            continue
        append_info(subject, subject, *payload)

    return rows


def _extract_outline_character_blocks(outline: str) -> list[dict[str, str]]:
    import re

    scan_text = _outline_character_scan_text(outline)
    label_re = re.compile(
        r"(?:^|\n)\s*(?:[-*•]\s*)?"
        r"(?:(男主|女主|男二|女二|反派|配角|龙套|主角)\s*)?"
        r"([\u4e00-\u9fa5]{2,6})"
        r"(?:[（(]([^）)]{1,16})[）)])?\s*[：:]\s*"
    )
    matches = list(label_re.finditer(scan_text))
    by_name: dict[str, dict[str, str]] = {}

    def add_character(name: str, role_hint: str = "", info: str = "") -> None:
        cleaned = _clean_outline_character_name(name)
        if not _outline_is_valid_character_name(cleaned):
            return
        current = by_name.get(cleaned)
        role = _outline_character_role(role_hint, len(by_name))
        compact_info = _sanitize_outline_character_info(info, name=cleaned, limit=800)
        if current:
            if compact_info and compact_info not in current["info"]:
                current["info"] = _compact_outline_analysis_text(
                    f"{current['info']}\n{compact_info}",
                    limit=1000,
                )
            if current["role"] == "minor" and role != "minor":
                current["role"] = role
            return
        by_name[cleaned] = {
            "name": cleaned,
            "role": role,
            "info": compact_info,
        }

    for character in _extract_outline_character_table_blocks(outline):
        add_character(character["name"], character.get("role", ""), character.get("info", ""))

    for index, match in enumerate(matches):
        role_label = (match.group(1) or match.group(3) or "").strip()
        name = match.group(2) or ""
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(scan_text)
        info = scan_text[match.end():next_start].strip()
        add_character(name, role_label, info)

    inline_section_re = re.compile(
        r"(?:^|[\n\r])\s*(?:核心人物|核心角色|主要人物|主要角色|人物介绍|人物设定|登场人物|出场人物|人物列表|角色列表|角色库|人物|角色)\s*[：:]\s*"
        r"([\s\S]{1,1600}?)(?=\n\s*(?:人物关系|角色关系|关系设计|视觉档案|视觉文档|"
        r"第\s*[一二三四五六七八九十百\d]{1,4}\s*集|分集|集纲|剧情大纲|故事大纲)\s*[：:\-、]?|$)"
    )
    inline_item_re = re.compile(
        r"^\s*(?:(男主|女主|男二|女二|反派|配角|龙套|主角)\s*)?"
        r"([\u4e00-\u9fa5]{2,6})"
        r"(?:[（(]([^）)]{1,120})[）)])?"
        r"(?:[：:，,]\s*(.*))?\s*$"
    )
    for section_match in inline_section_re.finditer(outline or ""):
        section_text = section_match.group(1) or ""
        for raw_part in re.split(r"[；;\n]+", section_text):
            part = raw_part.strip(" \t-•*。.")
            if not part:
                continue
            match = inline_item_re.match(part)
            if not match:
                continue
            role_label = (match.group(1) or "").strip()
            name = match.group(2) or ""
            bracket_info = (match.group(3) or "").strip()
            tail_info = (match.group(4) or "").strip()
            info = "，".join(item for item in [bracket_info, tail_info] if item)
            add_character(name, role_label or bracket_info, info)

    for match in re.finditer(r"(男主|女主|男二|女二|反派|配角|龙套|主角)\s*([\u4e00-\u9fa5]{2,6})", scan_text):
        role_label = match.group(1) or ""
        name = match.group(2) or ""
        pos = match.start()
        nearby = scan_text[max(0, pos - 40): pos + 240]
        add_character(name, role_label, nearby)

    visual_line_re = re.compile(
        r"(?:^|\n)\s*(?:[-*•]\s*)?"
        r"([\u4e00-\u9fa5]{2,6})(?:[（(][^）)]{1,16}[）)])?\s+"
        r"((?:\d{1,3}\s*岁|少年|少女|青年|中年|老年|男性|女性|男|女)[^\n\r]{4,160})"
    )
    for match in visual_line_re.finditer(scan_text):
        name = match.group(1) or ""
        info = match.group(2) or ""
        add_character(name, "", info)

    return list(by_name.values())


def _split_outline_analysis_sentences(outline: str) -> list[str]:
    import re

    return [
        item.strip()
        for item in re.split(r"[。！？!?；;\n]+", outline or "")
        if len(item.strip()) >= 8
    ]


def _pick_outline_analysis_sentence(outline: str, keywords: list[str], fallback_index: int = 0) -> str:
    sentences = _split_outline_analysis_sentences(outline)
    for sentence in sentences:
        if any(keyword in sentence for keyword in keywords):
            return _compact_outline_analysis_text(sentence, limit=180)
    if 0 <= fallback_index < len(sentences):
        return _compact_outline_analysis_text(sentences[fallback_index], limit=180)
    return _compact_outline_analysis_text(outline, limit=180)


def _is_outline_category_summary(text: str) -> bool:
    compact = _compact_outline_analysis_text(text, limit=120)
    if not compact:
        return False
    category_hits = sum(1 for word in ["现代", "都市", "悬疑", "男频", "女频", "短剧", "真人", "题材", "类型"] if word in compact)
    story_hits = sum(1 for word in ["男主", "女主", "主角", "发现", "卷入", "为了", "必须", "却", "被迫", "想要", "追查", "保护", "复仇"] if word in compact)
    return category_hits >= 2 and story_hits == 0


def _is_outline_scaffold_value(text: str) -> bool:
    import re

    compact = _compact_outline_analysis_text(text, limit=180)
    if not compact:
        return True
    if any(
        marker in compact
        for marker in [
            "我已有大纲文件",
            "已有大纲文件",
            "请先帮我",
            "系统能稳定识别",
            "点击上传",
            "拖拽文件",
            ".docx",
            ".markdown",
            ".txt",
        ]
    ):
        return True
    if re.match(
        r"^(?:主场景|关系变化|信息揭露|爽点类型|本集冲突|转折/爆点|转折爆点|核心冲突/爽点|"
        r"卖点概述|主卖点|次卖点|参考对标|改编问题及解决方案)\s*[：:]",
        compact,
    ):
        return True
    if re.match(
        r"^(?:世界观|核心冲突/爽点|核心冲突|爽点|一句话梗概)\s*(?:[：:]|\s+)"
        r"(?:次卖点|主卖点|卖点概述|信息揭露|关系变化|主场景|爽点类型|转折/爆点|转折爆点)",
        compact,
    ):
        return True
    if compact.startswith(("卖点概述", "主卖点", "次卖点", "参考对标")):
        return True
    return False


def _derive_outline_logline(outline: str) -> str:
    summary = _pick_labeled_outline_value(outline, ["故事概括", "故事简介", "剧情概括", "故事梗概"], limit=260)
    if summary:
        return summary
    sentences = _split_outline_analysis_sentences(outline)
    for sentence in sentences:
        cleaned = sentence
        cleaned = cleaned.replace("故事大纲：", "").replace("故事大纲:", "")
        cleaned = cleaned.replace("一句话梗概：", "").replace("一句话梗概:", "")
        cleaned = cleaned.replace("故事概括：", "").replace("故事概括:", "").replace("故事概括", "")
        cleaned = _compact_outline_analysis_text(cleaned, limit=220)
        if not cleaned or _is_outline_category_summary(cleaned) or _is_outline_scaffold_value(cleaned):
            continue
        if any(word in cleaned for word in ["男主", "女主", "主角", "发现", "卷入", "为了", "必须", "被迫", "追查", "保护", "复仇", "秘密", "证据"]):
            return cleaned
    for sentence in sentences:
        cleaned = _compact_outline_analysis_text(sentence, limit=220)
        if cleaned and not _is_outline_category_summary(cleaned) and not _is_outline_scaffold_value(cleaned):
            return cleaned
    return ""


def _pick_labeled_outline_value(outline: str, labels: list[str], *, limit: int = 220) -> str:
    import re

    label_pattern = "|".join(re.escape(label) for label in labels)
    stop_labels = (
        r"故事大纲|一句话梗概|故事概括|故事简介|剧情概括|故事梗概|作品名|卖点概述|主卖点|次卖点|核心卖点|"
        r"定位|作品体量|用户定位|参考对标|创作方向|角色库|世界观|背景设定|金手指|特殊设定|"
        r"核心冲突(?:/爽点)?|爽点|人物小传|人物设定|角色设定|第\s*[一二三四五六七八九十百\d]{1,4}\s*集|分集|集纲"
    )
    match = re.search(
        rf"(?:^|[\n\r])\s*(?:{label_pattern})\s*(?:[：:]|\s+|\s*\|\s*)\s*([\s\S]*?)(?=\n\s*(?:{stop_labels})\s*(?:[：:]|\s+|\s*\|\s*)|$)",
        outline or "",
    )
    if match:
        raw_value = re.sub(r"^[|：:\s]+", "", match.group(1) or "")
        raw_value = re.split(
            r"\n\s*(?:外貌参考|视觉档案|视觉文档|人物关系|角色关系|关系设计|"
            r"[\u4e00-\u9fa5]{2,8}\s*[（(](?:protagonist|supporting|antagonist|main|lead|主角|配角|反派|男主|女主))",
            raw_value,
            maxsplit=1,
        )[0]
        value = _compact_outline_analysis_text(raw_value, limit=limit)
        return "" if _is_outline_scaffold_value(value) else value
    for sentence in _split_outline_analysis_sentences(outline):
        if any(label in sentence for label in labels):
            value = _compact_outline_analysis_text(sentence, limit=limit)
            return "" if _is_outline_scaffold_value(value) else value
    return ""


def _derive_outline_worldview(outline: str) -> str:
    text = outline or ""
    if any(word in text for word in ("部落", "堂仙", "香火", "龙君", "妖", "精怪", "蛮荒", "巫")):
        return "原始部落信仰与精怪妖族共存，部族依靠堂仙庇护、香火供奉和巫祝规则维持生存秩序。"
    if any(word in text for word in ("现代", "都市", "公司", "集团", "医院", "学校", "法庭")):
        return "现代都市社会规则下，身份、资源和公共舆论共同推动人物冲突。"
    if any(word in text for word in ("古代", "王朝", "朝堂", "江湖", "宗门")):
        return "古代权力秩序与家族/门派规则交织，人物行动受身份阶层和阵营利益制约。"
    sentence = _pick_outline_analysis_sentence(text, ["背景", "世界", "规则", "设定"], 0)
    return "" if _is_outline_scaffold_value(sentence) else sentence


def _derive_outline_golden_finger(outline: str) -> str:
    text = outline or ""
    if "系统" in text:
        if "香火" in text or "龙君" in text:
            return "主角绑定龙君/香火类系统，通过庇护部族、兑现供奉和完成关键事件积累香火点，逐步解锁神通与化形能力。"
        return "主角拥有系统规则辅助，但能力兑现需要完成任务、承担代价或满足明确限制。"
    if any(word in text for word in ("重生", "前世", "预知")):
        return "主角拥有重生/预知带来的信息优势，但必须通过当下行动改变原有命运。"
    if any(word in text for word in ("神通", "化形", "香火", "堂仙", "龙君")):
        return "主角可通过香火、信仰或修行获得阶段性神通，能力增长必须服务于部族生存和主线冲突。"
    sentence = _pick_outline_analysis_sentence(text, ["特殊", "能力", "金手指", "系统", "规则"], 0)
    return "" if _is_outline_scaffold_value(sentence) else sentence


def _derive_outline_conflict(outline: str, characters: list[dict[str, str]] | None = None) -> str:
    text = outline or ""
    if any(word in text for word in ("黑山部", "妖", "精怪", "部族", "部落", "堂仙")):
        return "主角守护所在部族并积累信仰力量，对抗外部部族、精怪妖物和内部规则失控带来的连续生存危机。"
    names = [item.get("name", "") for item in (characters or []) if item.get("name")]
    if len(names) >= 2:
        return f"{names[0]}想推进核心目标，但受到{names[1]}及其背后利益阻碍，双方围绕资源、身份和真相持续升级。"
    sentence = _pick_outline_analysis_sentence(text, ["冲突", "矛盾", "对抗", "阻止", "危险", "生存"], 0)
    return "" if _is_outline_scaffold_value(sentence) else sentence


def _infer_outline_analysis_genre(outline: str) -> dict[str, str]:
    target = "混合"
    if "男频" in outline or "男主" in outline:
        target = "男频"
    elif "女频" in outline or "女主" in outline:
        target = "女频"

    if any(word in outline for word in ["悬疑", "推理", "凶", "杀", "秘密", "诡", "鬼", "恐怖"]):
        sub_category = "悬疑惊悚"
    elif any(word in outline for word in ["重生", "逆袭", "系统", "爽"]):
        sub_category = "重生逆袭"
    elif any(word in outline for word in ["婚", "总裁", "豪门", "恋", "爱"]):
        sub_category = "都市情感"
    elif any(word in outline for word in ["权谋", "古装", "朝堂", "王"]):
        sub_category = "古装权谋"
    else:
        sub_category = "都市短剧"
    return {"target": target, "category": target, "subCategory": sub_category}


def _extract_outline_analysis_characters(outline: str) -> list[dict[str, str]]:
    characters = _extract_outline_character_blocks(outline)
    return characters


def _extract_dialogue_speakers(outline: str) -> list[dict[str, str]]:
    """从带对白的剧本正文里提取台词说话人作为角色（用户输入完整剧本时兜底）。

    规则：行首 "名字：台词" 形态，名字 2-5 个汉字、通过角色名校验、且出现 ≥2 次
    （避免把一次性旁白/标签当角色）。返回 [{name, role, info}]。
    """
    import re
    from collections import Counter

    counts: Counter = Counter()
    for match in re.finditer(r"(?:^|\n)\s*([一-龥]{2,5})\s*[：:]\s*\S", outline or ""):
        name = _clean_outline_character_name(match.group(1))
        if _outline_is_valid_character_name(name):
            counts[name] += 1
    speakers = [name for name, count in counts.most_common() if count >= 2]
    return [
        {"name": name, "role": _outline_character_role("", index), "info": ""}
        for index, name in enumerate(speakers[:12])
    ]


def _extract_outline_analysis_relationships(outline: str, characters: list[dict[str, str]]) -> list[dict[str, Any]]:
    import re

    names = [item.get("name", "") for item in characters if _outline_is_valid_character_name(item.get("name", ""))]
    if len(names) < 2:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    section = re.search(r"(?:人物关系|角色关系|关系设计|关系表)\s*[：:\n]([\s\S]{0,1600})", outline or "")
    if not section:
        return []
    text = section.group(1)
    stop = re.search(r"\n\s*(?:第\s*[一二三四五六七八九十百\d]{1,4}\s*集|分集|集纲|剧情大纲|故事大纲|视觉档案|视觉文档)\s*[：:\-、]?", text)
    if stop:
        text = text[:stop.start()]
    for source in names:
        for target in names:
            if source == target:
                continue
            pattern = re.compile(
                rf"{re.escape(source)}\s*(?:与|和|对|vs|VS|—|-)\s*{re.escape(target)}"
                r"(?:[（(](.{1,80})[）)]|[：:，,]\s*(.{1,120}))?"
            )
            for match in pattern.finditer(text):
                raw = _compact_outline_analysis_text(match.group(1) or match.group(2) or "关系待补全", limit=120)
                rel_type = raw.split("，", 1)[0].split(",", 1)[0].strip() or "关系"
                key = (source, target, rel_type)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "source": source,
                    "target": target,
                    "type": rel_type,
                    "description": raw,
                    "strength": 70,
                })
    return rows[:24]


def _parse_outline_analysis_episode_no(value: str) -> int:
    import re

    digit = re.search(r"\d{1,3}", value or "")
    if digit:
        return int(digit.group(0))
    nums = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + nums.get(value[1:], 0)
    if "十" in value:
        ten, one = (value.split("十", 1) + [""])[:2]
        return (nums.get(ten, 1) * 10) + nums.get(one, 0)
    return nums.get(value or "", 0)


def _strip_outline_episode_heading(chunk: str) -> str:
    import re

    return re.sub(
        r"^\s*(?:第\s*)?[一二三四五六七八九十百\d]{1,4}\s*(?:集|级)[：:、\-\.\s]*[^\n\r]*",
        "",
        str(chunk or "").strip(),
        count=1,
    ).strip()


def _outline_chunk_has_script_body(chunk: str) -> bool:
    import re

    text = _strip_outline_episode_heading(chunk)
    if len(text) < 24:
        return False
    dialogue_lines = re.findall(r"^\s*[\u4e00-\u9fa5]{2,6}\s*[：:].{2,}", text, re.M)
    scene_headers = re.findall(r"(?:【[^】]{2,40}】|\b(?:内|外|日|夜)\b|场\s*\d+|第\s*\d+\s*场)", text)
    action_marks = text.count("△") + len(re.findall(r"^\s*[动作景]?描写\s*[：:]", text, re.M))
    return len(dialogue_lines) >= 2 or (len(dialogue_lines) >= 1 and len(scene_headers) >= 1) or action_marks >= 1


def _extract_outline_range_sections(outline: str) -> list[dict[str, Any]]:
    import re

    pattern = re.compile(
        r"(?:第\s*)?(\d{1,3})\s*(?:[-~～—至到])\s*(\d{1,3})\s*集\s*[：:、\-\s]*([^\n\r]*)"
    )
    sections: list[dict[str, Any]] = []
    matches = list(pattern.finditer(outline or ""))
    for index, match in enumerate(matches):
        start = int(match.group(1))
        end = int(match.group(2))
        if start <= 0 or end < start or end > 200:
            continue
        next_index = matches[index + 1].start() if index + 1 < len(matches) else len(outline or "")
        body = (match.group(3) or "") + "\n" + (outline or "")[match.end():next_index]
        body = _compact_outline_analysis_text(body, limit=600)
        if body:
            sections.append({"start": start, "end": end, "body": body})
    return sections


def _expand_outline_range_episodes(outline: str, episode_cap: int) -> list[dict[str, Any]]:
    sections = _extract_outline_range_sections(outline)
    if not sections:
        return []
    episodes: list[dict[str, Any]] = []
    for section in sections:
        for ep_no in range(section["start"], min(section["end"], episode_cap) + 1):
            slot = ep_no - section["start"] + 1
            summary = (
                f"第{section['start']}-{section['end']}集范围集纲内的第{slot}个事件："
                f"{section['body']}"
            )
            episodes.append({
                "episodeNumber": ep_no,
                "title": f"第{ep_no}集",
                "summary": _compact_outline_analysis_text(summary, limit=260),
                "conflict": _pick_outline_analysis_sentence(section["body"], ["冲突", "阻碍", "危险", "对抗", "追查", "揭露"], 0),
                "turning": _pick_outline_analysis_sentence(section["body"], ["转折", "爆点", "却", "突然", "发现", "反转"], 1),
            })
    return episodes[:episode_cap]


def _extract_outline_analysis_episodes(
    outline: str,
    target_episodes: int | None = None,
    *,
    cap_override: int | None = None,
) -> list[dict[str, Any]]:
    import re

    episode_cap = (
        max(1, min(200, int(cap_override)))
        if cap_override is not None
        else max(3, min(OUTLINE_ANALYZE_EPISODE_CAP, int(target_episodes or 10)))
    )
    headings: list[dict[str, Any]] = []
    heading_re = re.compile(
        r"(?:^|[\n\r])\s*(?:#{1,6}\s*)?(?:第\s*)?([一二三四五六七八九十百\d]{1,4})\s*(?:集|级)"
        r"[：:、\-\.\s]*([^\n\r。！？!?]{0,220})"
    )
    for match in heading_re.finditer(outline or ""):
        headings.append({
            "index": match.start(),
            "episodeNumber": _parse_outline_analysis_episode_no(match.group(1) or "") or len(headings) + 1,
            "lineText": _compact_outline_analysis_text(match.group(2) or "", limit=260),
        })

    if headings:
        episodes: list[dict[str, Any]] = []
        for index, heading in enumerate(headings[:episode_cap]):
            next_index = headings[index + 1]["index"] if index + 1 < len(headings) else len(outline or "")
            chunk = (outline or "")[heading["index"]: next_index]
            sentences = _split_outline_analysis_sentences(chunk)
            existing_script = _strip_outline_episode_heading(chunk) if _outline_chunk_has_script_body(chunk) else ""
            line_summary = heading.get("lineText") or ""
            summary = line_summary or _compact_outline_analysis_text("。".join(sentences[:3]), limit=260) or (
                "原稿正文已识别，剧本写作中将直接承接原文。"
            )
            episodes.append({
                "episodeNumber": heading["episodeNumber"],
                "title": f"第{heading['episodeNumber']}集",
                "summary": summary,
                "conflict": _pick_outline_analysis_sentence(chunk, ["冲突", "发现", "分手", "危险", "追", "逃", "杀", "秘密"], 1),
                "turning": _pick_outline_analysis_sentence(chunk, ["转折", "爆点", "却", "突然", "没想到", "发现"], 2),
                "existing_script": existing_script,
            })
        merged: dict[int, dict[str, Any]] = {}
        for episode in episodes:
            ep_no = int(episode.get("episodeNumber") or 0)
            if ep_no <= 0 or ep_no > episode_cap:
                continue
            current = merged.get(ep_no)
            if not current:
                merged[ep_no] = episode
                continue
            if episode.get("existing_script") and not current.get("existing_script"):
                current["existing_script"] = episode["existing_script"]
            if not current.get("summary") and episode.get("summary"):
                current["summary"] = episode["summary"]
            if not current.get("conflict") and episode.get("conflict"):
                current["conflict"] = episode["conflict"]
            if not current.get("turning") and episode.get("turning"):
                current["turning"] = episode["turning"]
        return [merged[ep_no] for ep_no in sorted(merged)]

    return []


def _build_outline_analysis_fallback(outline: str, target_episodes: int | None = None) -> dict[str, Any]:
    genre = _infer_outline_analysis_genre(outline or "")
    worldview = _pick_labeled_outline_value(outline, ["世界观", "背景设定", "故事背景", "时代背景"], limit=260)
    uniqueness = _pick_labeled_outline_value(outline, ["金手指", "特殊设定", "差异化", "核心设定"], limit=260)
    conflict = _pick_labeled_outline_value(outline, ["核心冲突", "主要矛盾", "全剧冲突"], limit=260)
    characters = _extract_outline_analysis_characters(outline or "")
    return {
        "genre": genre,
        "sellingPoints": {
            "logline": _derive_outline_logline(outline),
            "worldview": worldview,
            "uniqueness": uniqueness,
            "conflict": conflict,
        },
        "characters": characters,
        "relationships": _extract_outline_analysis_relationships(outline or "", characters),
        "episodes": _extract_outline_analysis_episodes(outline or "", target_episodes),
        "fallback": True,
        **_local_fallback_candidate_boundary("local_analysis"),
    }


def _local_fallback_candidate_boundary(reason: str) -> dict[str, Any]:
    return {
        "candidate_source": "local_fallback",
        "needs_user_confirmation": True,
        "main_chain_committed": False,
        "downstream_generation_allowed": False,
        "candidate_boundary_reason": reason,
    }


def _merge_outline_analysis_with_fallback(
    result: dict[str, Any],
    fallback: dict[str, Any],
    target_episodes: int,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = {}
    result.setdefault("genre", fallback["genre"])
    selling_points = result.setdefault("sellingPoints", {})
    if not isinstance(selling_points, dict):
        selling_points = {}
        result["sellingPoints"] = selling_points
    for key, value in fallback["sellingPoints"].items():
        if not selling_points.get(key):
            selling_points[key] = value
    result["characters"] = _merge_outline_analysis_characters(
        result.get("characters"),
        fallback.get("characters") or [],
    )
    if not isinstance(result.get("relationships"), list) or not result.get("relationships"):
        result["relationships"] = fallback.get("relationships") or []

    existing_episodes = _normalize_outline_episode_list(result.get("episodes"), target_episodes)
    if not existing_episodes:
        result["episodes"] = fallback["episodes"]
    else:
        fallback_by_no = {int(item.get("episodeNumber") or 0): item for item in fallback["episodes"]}
        dedup = {int(item["episodeNumber"]): item for item in existing_episodes if item.get("episodeNumber")}
        for ep_no, fallback_ep in fallback_by_no.items():
            if ep_no in dedup and fallback_ep.get("existing_script") and not dedup[ep_no].get("existing_script"):
                dedup[ep_no]["existing_script"] = fallback_ep["existing_script"]
        for ep_no in range(1, target_episodes + 1):
            if ep_no not in dedup and ep_no in fallback_by_no:
                dedup[ep_no] = fallback_by_no[ep_no]
        result["episodes"] = [dedup[k] for k in sorted(dedup)[:target_episodes]]
    return result


def _normalize_outline_analysis_characters(items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []

    characters: list[dict[str, str]] = []
    by_key: dict[str, dict[str, str]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = _clean_outline_character_name(
            item.get("name")
            or item.get("character_name")
            or item.get("title")
            or ""
        )
        if not _outline_is_valid_character_name(name):
            continue
        key = _outline_character_alias_key(name)
        if not key:
            continue
        role = _outline_character_role(str(item.get("role") or item.get("position") or ""), index)
        raw_info = _coerce_outline_text(
            item.get("info")
            or item.get("description")
            or item.get("identity")
            or item.get("background")
            or item.get("motivation")
            or "",
            limit=1000,
        )
        info = _sanitize_outline_character_info(raw_info, name=name, limit=1000)
        current = by_key.get(key)
        if current:
            current["info"] = _outline_merge_unique_text(current.get("info", ""), info, limit=1000)
            if current.get("role") == "minor" and role in {"protagonist", "supporting", "antagonist"}:
                current["role"] = role
            continue
        current = {"name": name, "role": role, "info": info}
        by_key[key] = current
        characters.append(current)
    return characters


def _merge_outline_analysis_characters(raw_items: Any, fallback_items: list[dict[str, str]]) -> list[dict[str, str]]:
    """Use local extraction as the boundary, then let AI enrich valid character rows only."""
    fallback = _normalize_outline_analysis_characters(fallback_items)
    incoming = _normalize_outline_analysis_characters(raw_items)
    if not fallback:
        return incoming
    if not incoming:
        return fallback

    by_key: dict[str, dict[str, str]] = {}
    ordered: list[str] = []
    for item in fallback:
        key = _outline_character_alias_key(item.get("name", ""))
        if not key:
            continue
        by_key[key] = dict(item)
        ordered.append(key)

    for item in incoming:
        key = _outline_character_alias_key(item.get("name", ""))
        if not key:
            continue
        existing = by_key.get(key)
        if existing:
            existing["info"] = _outline_merge_unique_text(
                existing.get("info", ""),
                item.get("info", ""),
                limit=1200,
            )
            if existing.get("role") == "minor" and item.get("role") in {"supporting", "antagonist"}:
                existing["role"] = item["role"]
            continue
        by_key[key] = dict(item)
        ordered.append(key)

    return [by_key[key] for key in ordered if key in by_key][:12]


def _coerce_outline_text(value: Any, *, limit: int = 240) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()[:limit]
    if isinstance(value, dict):
        for key in ("content", "summary", "text", "title"):
            if value.get(key):
                return str(value.get(key)).strip()[:limit]
        return json.dumps(value, ensure_ascii=False)[:limit]
    if isinstance(value, list):
        return "；".join(_coerce_outline_text(item, limit=80) for item in value if item)[:limit]
    return str(value).strip()[:limit]


def _normalize_outline_episode(raw: Any, episode_no: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    ep_value = raw.get("episodeNumber") or raw.get("episode_no") or raw.get("episode") or raw.get("ep") or episode_no
    try:
        ep_no = int(str(ep_value).strip())
    except Exception:
        ep_no = episode_no
    if ep_no <= 0:
        ep_no = episode_no

    title = _coerce_outline_text(raw.get("title"), limit=60) or f"第{ep_no}集"
    summary = _coerce_outline_text(
        raw.get("episode_outline") or raw.get("summary") or raw.get("main_event") or raw.get("event") or raw.get("plot") or raw.get("beat"),
        limit=360,
    )
    conflict = _coerce_outline_text(raw.get("conflict") or raw.get("core_conflict"), limit=180)
    turning = _coerce_outline_text(raw.get("turning") or raw.get("turning_point") or raw.get("reversal"), limit=200)
    if not summary:
        plot_points = raw.get("plotPoints") or raw.get("plot_points") or []
        summary = _coerce_outline_text(plot_points, limit=360)

    plot_points = [
        {
            "id": f"pp-{ep_no}-1",
            "type": "inciting",
            "content": summary or conflict or title,
            "purpose": "推进本集主事件",
            "emotion": "",
            "suggestions": [],
        },
        {
            "id": f"pp-{ep_no}-2",
            "type": "climax",
            "content": turning or conflict or summary or title,
            "purpose": "形成本集爆点或转折",
            "emotion": "",
            "suggestions": [],
        },
    ]
    return {
        "id": f"ep-{ep_no}",
        "episodeNumber": ep_no,
        "title": title,
        "episode_outline": summary,
        "summary": summary,
        "main_event": _coerce_outline_text(raw.get("main_event"), limit=220) or summary,
        "main_scene": _coerce_outline_text(raw.get("main_scene"), limit=80),
        "main_conflict": _coerce_outline_text(raw.get("main_conflict"), limit=220) or conflict,
        "turning": turning,
        "relationship_change": _coerce_outline_text(raw.get("relationship_change"), limit=160),
        "info_revealed": _coerce_outline_text(raw.get("info_revealed"), limit=160),
        "satisfaction_type": _coerce_outline_text(raw.get("satisfaction_type"), limit=80),
        "hook_subtag": _coerce_outline_text(raw.get("hook_subtag"), limit=80),
        "stage": _coerce_outline_text(raw.get("stage"), limit=40),
        "stage_task": _coerce_outline_text(raw.get("stage_task"), limit=160),
        "callbacks": raw.get("callbacks") if isinstance(raw.get("callbacks"), list) else [],
        "seeds": raw.get("seeds") if isinstance(raw.get("seeds"), list) else [],
        "cliffhanger_concrete": raw.get("cliffhanger_concrete") if isinstance(raw.get("cliffhanger_concrete"), dict) else {},
        "hook": {
            "content": "",
            "type": "悬念",
            "strength": 8,
            "suggestions": [],
        },
        "plotPoints": plot_points,
        "emotionArc": [],
        "scenes": [],
        "conflict": conflict or turning or summary,
        "existing_script": _coerce_outline_text(raw.get("existing_script"), limit=15000),
        "source": _coerce_outline_text(raw.get("source"), limit=40),
        "review_status": _coerce_outline_text(raw.get("review_status"), limit=60),
        "cliffhanger": {
            "content": "",
            "type": "悬念",
            "strength": 8,
            "suggestions": [],
        },
        "evaluation": {
            "pacing": 8,
            "tension": 8,
            "completeness": 8,
            "issues": [],
            "suggestions": [],
        },
    }


def _normalize_outline_episode_list(items: Any, target_episodes: int) -> list[dict[str, Any]]:
    if isinstance(items, dict):
        for key in ("episodes", "episode_outlines", "items"):
            if isinstance(items.get(key), list):
                items = items.get(key)
                break
    if not isinstance(items, list):
        return []

    episodes: list[dict[str, Any]] = []
    seen: set[int] = set()
    cap = target_episodes if target_episodes > 0 else 200
    for index, item in enumerate(items, start=1):
        normalized = _normalize_outline_episode(item, index)
        if not normalized:
            continue
        ep_no = int(normalized["episodeNumber"])
        if ep_no in seen or ep_no > cap:
            continue
        seen.add(ep_no)
        episodes.append(normalized)
    return sorted(episodes, key=lambda item: int(item["episodeNumber"]))


def _normalize_outline_episode_batch(
    items: Any,
    *,
    target_episodes: int,
    batch_start: int,
    batch_end: int,
) -> list[dict[str, Any]]:
    """Normalize one generated batch while tolerating relative episode numbers.

    LLMs sometimes obey the requested batch content but number the returned
    rows as 1..N. In a paged 30-episode job that would drop otherwise usable
    rows after filtering by absolute episode number.
    """

    if isinstance(items, dict):
        for key in ("episodes", "episode_outlines", "items"):
            if isinstance(items.get(key), list):
                items = items.get(key)
                break
    if not isinstance(items, list):
        return []

    allowed = {n for n in range(int(batch_start), int(batch_end) + 1)}
    expected_count = max(0, int(batch_end) - int(batch_start) + 1)
    normalized = _normalize_outline_episode_list(items, target_episodes)
    in_allowed = [item for item in normalized if int(item["episodeNumber"]) in allowed]
    if len(in_allowed) == expected_count:
        return in_allowed

    raw_items = [item for item in items if isinstance(item, dict)]
    if len(raw_items) >= expected_count and expected_count > 0:
        positional: list[dict[str, Any]] = []
        for offset, item in enumerate(raw_items[:expected_count]):
            ep_no = int(batch_start) + offset
            forced = dict(item)
            for key in ("episodeNumber", "episode_no", "episode", "ep"):
                forced.pop(key, None)
            normalized_item = _normalize_outline_episode(forced, ep_no)
            if normalized_item:
                positional.append(normalized_item)
        if len(positional) == expected_count:
            return positional

    return in_allowed


def _seed_outline_episode_map(seed_analysis: dict[str, Any] | None, target_episodes: int) -> dict[int, dict[str, Any]]:
    """Return page-parsed episode outlines as a floor for AI generation.

    The outline editor sends the user's current episodes in seed_analysis. That
    material is upstream truth for the chain: AI may improve it, but a model
    batch that omits some rows should not erase rows the user already supplied.
    """

    if not isinstance(seed_analysis, dict):
        return {}
    raw = seed_analysis.get("episodes") or seed_analysis.get("episode_outlines") or seed_analysis.get("episodeFrameworks")
    if not isinstance(raw, list):
        return {}
    normalized = _normalize_outline_episode_list(raw, target_episodes)
    by_no: dict[int, dict[str, Any]] = {}
    for item in normalized:
        try:
            ep_no = int(item.get("episodeNumber") or 0)
        except Exception:
            continue
        if 1 <= ep_no <= target_episodes and ep_no not in by_no:
            by_no[ep_no] = item
    return by_no


def _outline_generation_context(analysis: dict[str, Any] | None) -> str:
    if not isinstance(analysis, dict):
        return ""
    selling = analysis.get("sellingPoints") if isinstance(analysis.get("sellingPoints"), dict) else {}
    characters = analysis.get("characters") if isinstance(analysis.get("characters"), list) else []
    parts = [
        f"一句话梗概：{selling.get('logline') or ''}",
        f"核心冲突：{selling.get('conflict') or ''}",
        f"世界观：{selling.get('worldview') or ''}",
        f"差异化：{selling.get('uniqueness') or ''}",
    ]
    if characters:
        parts.append(
            "主要角色："
            + "；".join(
                f"{_coerce_outline_text(c.get('name'), limit=24)}：{_coerce_outline_text(c.get('info'), limit=120)}"
                for c in characters[:12]
                if isinstance(c, dict)
            )
        )
    return "\n".join(part for part in parts if part.strip("： \n"))


def _outline_story_axis(outline: str, seed_analysis: dict[str, Any] | None = None) -> str:
    context = json.dumps(seed_analysis or {}, ensure_ascii=False) + "\n" + (outline or "")
    if any(word in context for word in ["悬疑", "推理", "凶案", "案件", "调查", "证据", "秘密"]):
        return "悬疑"
    if "女频" in context or "女主" in context:
        return "女频"
    if "男频" in context or "男主" in context:
        return "男频"
    return "混合"


def _outline_episode_stage(ep_no: int, target: int) -> dict[str, str]:
    if target >= 30:
        if ep_no <= 3:
            return {"stage": "抢入", "task": "建立反差、主角目标和第一推力"}
        if ep_no <= 7:
            return {"stage": "蓄势", "task": "信息加密、关系拉紧、矛盾升级"}
        if ep_no <= 12:
            return {"stage": "首付墙", "task": "制造全剧最强未兑现悬念，禁止提前大结局式兑现"}
        if ep_no <= 18:
            return {"stage": "爬升", "task": "反派资源减少、主角筹码增多、关系档位变化"}
        if ep_no <= 25:
            return {"stage": "风暴", "task": "高密度爆点、关键反转和主要对抗"}
        if ep_no <= 28:
            return {"stage": "二付墙", "task": "最大爽感引爆前夜，先压到最低谷"}
        return {"stage": "终局", "task": "最终对决、反派下场、伏笔闭环"}

    ratio = ep_no / max(1, target)
    if ratio <= 0.15:
        return {"stage": "蓄势", "task": "世界观建立、角色亮相、第一危机埋雷"}
    if ratio <= 0.45:
        return {"stage": "爬升", "task": "冲突升温、关系拉扯、第一次爆点"}
    if ratio <= 0.8:
        return {"stage": "风暴", "task": "爽感集中区、主要对抗、关键反转"}
    return {"stage": "高潮", "task": "最终反转、情感爆发、结局落地"}


def _outline_quality_rule_context(outline: str, seed_analysis: dict[str, Any] | None, target: int) -> dict[str, Any]:
    axis = _outline_story_axis(outline, seed_analysis)
    hook_axis = "悬疑" if axis == "悬疑" else axis if axis in {"男频", "女频"} else "混合"
    characters = _merge_prediction_characters_with_seed(
        seed_analysis.get("characters") if isinstance(seed_analysis, dict) else None,
        _extract_outline_analysis_characters(outline or ""),
    )
    protagonist = next((c for c in characters if c.get("role") == "protagonist"), characters[0] if characters else {"name": "主角"})
    antagonist = next((c for c in characters if c.get("role") == "antagonist"), None)
    if antagonist is None:
        antagonist = next((c for c in characters if c.get("name") != protagonist.get("name")), {"name": "核心对手"})
    return {
        "axis": axis,
        "hook_rotation": _OUTLINE_HOOK_ROTATIONS.get(hook_axis, _OUTLINE_HOOK_ROTATIONS["混合"]),
        "satisfaction_rotation": _OUTLINE_SATISFACTION_ROTATIONS.get(axis if axis in {"男频", "女频"} else "混合", _OUTLINE_SATISFACTION_ROTATIONS["混合"]),
        "characters": characters,
        "protagonist": _coerce_outline_text(protagonist.get("name"), limit=20) or "主角",
        "antagonist": _coerce_outline_text(antagonist.get("name"), limit=20) or "核心对手",
        "target": target,
    }


def _outline_quality_pick(items: list[str], ep_no: int, salt: int = 0) -> str:
    if not items:
        return ""
    # salt 让不同字段在不同相位轮换，且每轮回再整体偏移一格，
    # 避免“每 N 集 info/relationship/turning 完全雷同”的循环复读。
    idx = (max(1, ep_no) - 1 + salt + (max(1, ep_no) - 1) // len(items)) % len(items)
    return items[idx]


def _outline_text_similarity(a: str, b: str) -> float:
    def _ngrams(value: str, size: int) -> set[str]:
        chars = [ch for ch in str(value or "") if ("\u4e00" <= ch <= "\u9fff") or ch.isalnum()]
        if len(chars) < size:
            return set(chars)
        return {"".join(chars[index:index + size]) for index in range(0, len(chars) - size + 1)}

    left_chars = _ngrams(a, 1)
    right_chars = _ngrams(b, 1)
    if not left_chars or not right_chars:
        return 0.0
    char_score = len(left_chars & right_chars) / max(1, len(left_chars | right_chars))
    left_bigrams = _ngrams(a, 2)
    right_bigrams = _ngrams(b, 2)
    bigram_score = len(left_bigrams & right_bigrams) / max(1, len(left_bigrams | right_bigrams)) if left_bigrams and right_bigrams else 0.0
    return max(char_score, bigram_score)


def _outline_episode_needs_quality_repair(
    episode: dict[str, Any],
    previous_texts: list[str],
) -> bool:
    summary = _coerce_outline_text(
        episode.get("episode_outline") or episode.get("summary") or episode.get("main_event"),
        limit=280,
    )
    conflict = _coerce_outline_text(episode.get("conflict") or episode.get("main_conflict"), limit=180)
    turning = _coerce_outline_text(episode.get("turning") or episode.get("turning_point") or episode.get("reversal"), limit=180)
    if len(summary) < 24 or len(conflict) < 10 or len(turning) < 10:
        return True
    if summary.startswith(("一句话梗概", "核心冲突", "人物小传", "人物设定", "角色设定", "世界观", "金手指")):
        return True
    if any(word in summary for word in ["继续推进", "围绕", "铺垫", "升级阶段", "收束阶段", "主线事件继续"]):
        return True
    if any(_outline_text_similarity(summary, prev) >= 0.62 for prev in previous_texts[-5:]):
        return True
    return False


def _fill_outline_continuity_contract(
    episode: dict[str, Any],
    *,
    ep_no: int,
    previous_summary: str,
    previous_event: str,
) -> dict[str, Any]:
    """补齐集纲承接硬字段，避免只靠提示词约束。"""
    if ep_no > 1 and not episode.get("callbacks"):
        episode["callbacks"] = [previous_summary or "承接上一集已落地的关系变化和未收压力继续推进"]

    current_event = _coerce_outline_text(episode.get("main_event") or episode.get("summary"), limit=160)
    if ep_no > 1 and previous_event and _outline_text_similarity(current_event, previous_event) >= 0.72:
        episode["main_event"] = f"{current_event}，并在第{ep_no}集推进一个新的不可逆结果"

    concrete = episode.get("cliffhanger_concrete")
    if not isinstance(concrete, dict):
        concrete = {}
    title = _coerce_outline_text(episode.get("title"), limit=40) or f"第{ep_no}集"
    main_scene = _coerce_outline_text(episode.get("main_scene"), limit=40) or "本集主场"
    info = _coerce_outline_text(episode.get("info_revealed"), limit=80) or _coerce_outline_text(episode.get("main_event"), limit=80)
    pressure = _coerce_outline_text(episode.get("conflict") or episode.get("main_conflict"), limit=100) or "对手压力仍未解除"
    concrete = {
        "freeze_prop": _coerce_outline_text(concrete.get("freeze_prop"), limit=100) or f"{main_scene}留下的关键证据/动作",
        "unresolved_question": _coerce_outline_text(concrete.get("unresolved_question"), limit=120) or f"{title}结尾仍未解释：{info}",
        "pressure": _coerce_outline_text(concrete.get("pressure"), limit=120) or pressure,
        "next_episode_must_pick_up": _coerce_outline_text(concrete.get("next_episode_must_pick_up"), limit=140) or f"下一集必须从{main_scene}的未收证据和角色压力继续承接",
    }
    episode["cliffhanger_concrete"] = concrete
    cliffhanger = episode.get("cliffhanger")
    if isinstance(cliffhanger, dict):
        cliffhanger["content"] = cliffhanger.get("content") or concrete["next_episode_must_pick_up"]
    return episode


def _build_rule_based_episode(
    *,
    ep_no: int,
    target: int,
    base_story: str,
    core_conflict: str,
    rule_context: dict[str, Any],
    previous_summary: str = "",
) -> dict[str, Any]:
    stage = _outline_episode_stage(ep_no, target)
    scene = _outline_quality_pick(_OUTLINE_SCENE_ROTATION, ep_no)
    action = _outline_quality_pick(_OUTLINE_ACTION_ROTATION, ep_no, salt=3)
    info = _outline_quality_pick(_OUTLINE_INFO_ROTATION, ep_no, salt=1)
    relationship = _outline_quality_pick(_OUTLINE_RELATIONSHIP_ROTATION, ep_no, salt=2)
    turning_seed = _outline_quality_pick(_OUTLINE_TURNING_ROTATION, ep_no, salt=5)
    satisfaction = _outline_quality_pick(rule_context.get("satisfaction_rotation") or [], ep_no, salt=2)
    hook_subtag = _outline_quality_pick(rule_context.get("hook_rotation") or [], ep_no, salt=1)
    protagonist = rule_context.get("protagonist") or "主角"
    antagonist = rule_context.get("antagonist") or "核心对手"
    title_action = action.replace("关键", "").replace("一段被压下的", "").replace("手里的", "")[:8]
    title = f"{scene[:2]}{title_action}"[:10] or f"第{ep_no}集"
    callback = previous_summary or "承接上一集确定的证据/关系变化继续推进"
    summary = (
        f"{stage['stage']}｜{protagonist}在{scene}为“{base_story}”推进具体行动：{action}。"
        f"{antagonist}以“{core_conflict or '核心利益冲突'}”施压阻断，"
        f"本集结果是{info}，并让{relationship}，局面发生不可逆变化。"
    )
    conflict = f"{scene}里，{protagonist}要{action}，{antagonist}阻止真相/筹码外流，矛盾落到{stage['task']}。"
    turning = f"{satisfaction} + {hook_subtag}：{turning_seed}。"
    return {
        "episodeNumber": ep_no,
        "title": title,
        "episode_outline": _compact_outline_analysis_text(summary, limit=320),
        "summary": _compact_outline_analysis_text(summary, limit=320),
        "main_event": action,
        "main_scene": scene,
        "main_conflict": conflict,
        "conflict": conflict,
        "turning": turning,
        "relationship_change": relationship,
        "info_revealed": info,
        "satisfaction_type": satisfaction,
        "hook_subtag": hook_subtag,
        "stage": stage["stage"],
        "stage_task": stage["task"],
        "callbacks": [] if ep_no == 1 else [callback],
        "seeds": [f"{info}后仍保留下一步行动压力"],
    }


def _repair_outline_episode_quality(
    episodes: list[dict[str, Any]],
    *,
    outline: str,
    target_episodes: int,
    seed_analysis: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    target = max(1, min(200, int(target_episodes or len(episodes) or 1)))
    rule_context = _outline_quality_rule_context(outline, seed_analysis, target)
    selling = seed_analysis.get("sellingPoints") if isinstance(seed_analysis, dict) and isinstance(seed_analysis.get("sellingPoints"), dict) else {}
    base_story = (
        _coerce_outline_text(selling.get("logline"), limit=120)
        or _derive_outline_logline(outline)
        or _coerce_outline_text(outline, limit=120)
        or "主线目标"
    )
    core_conflict = (
        _coerce_outline_text(selling.get("conflict"), limit=140)
        or _pick_labeled_outline_value(outline, ["核心冲突", "主要矛盾", "全剧冲突"], limit=140)
        or "主角目标与对手利益正面冲突"
    )
    by_no = {int(item.get("episodeNumber") or 0): item for item in episodes if int(item.get("episodeNumber") or 0) > 0}
    repaired: list[dict[str, Any]] = []
    previous_texts: list[str] = []
    previous_summary = ""
    for ep_no in range(1, target + 1):
        current = dict(by_no.get(ep_no) or {})
        existing_script = _coerce_outline_text(current.get("existing_script"), limit=15000)
        if not current or _outline_episode_needs_quality_repair(current, previous_texts):
            current = _build_rule_based_episode(
                ep_no=ep_no,
                target=target,
                base_story=base_story,
                core_conflict=core_conflict,
                rule_context=rule_context,
                previous_summary=previous_summary,
            )
        else:
            stage_hint = _outline_episode_stage(ep_no, target)
            if not _coerce_outline_text(current.get("stage"), limit=40):
                current["stage"] = stage_hint["stage"]
            if not _coerce_outline_text(current.get("stage_task"), limit=160):
                current["stage_task"] = stage_hint["task"]
            if not _coerce_outline_text(current.get("main_scene"), limit=80):
                current["main_scene"] = _outline_quality_pick(_OUTLINE_SCENE_ROTATION, ep_no)
            if not _coerce_outline_text(current.get("relationship_change"), limit=160):
                current["relationship_change"] = _outline_quality_pick(_OUTLINE_RELATIONSHIP_ROTATION, ep_no)
            if not _coerce_outline_text(current.get("info_revealed"), limit=160):
                current["info_revealed"] = _outline_quality_pick(_OUTLINE_INFO_ROTATION, ep_no)
            if not _coerce_outline_text(current.get("satisfaction_type"), limit=80):
                current["satisfaction_type"] = _outline_quality_pick(rule_context.get("satisfaction_rotation") or [], ep_no)
            if not _coerce_outline_text(current.get("hook_subtag"), limit=80):
                current["hook_subtag"] = _outline_quality_pick(rule_context.get("hook_rotation") or [], ep_no)
        if existing_script:
            current["existing_script"] = existing_script
        normalized = _normalize_outline_episode(current, ep_no)
        if normalized:
            normalized = _fill_outline_continuity_contract(
                normalized,
                ep_no=ep_no,
                previous_summary=previous_summary,
                previous_event=previous_texts[-1] if previous_texts else "",
            )
            repaired.append(normalized)
            summary_text = _coerce_outline_text(normalized.get("episode_outline") or normalized.get("summary"), limit=220)
            previous_texts.append(summary_text)
            previous_summary = f"第{ep_no}集：{summary_text}"
    return repaired


def _extract_episode_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("episodes", "episode_outlines", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if any(key in payload for key in ("episode", "episodeNumber", "ep", "title", "main_event", "summary")):
        return [payload]
    return []


def _generate_episode_frameworks_fallback(
    *,
    outline: str,
    target_episodes: int,
    seed_analysis: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build usable episode outlines when the LLM is unavailable or times out."""
    target = _require_confirmed_target_episodes(target_episodes)
    extracted = _extract_outline_analysis_episodes(outline or "", target, cap_override=target)
    by_no = {
        int(item.get("episodeNumber") or 0): item
        for item in extracted
        if int(item.get("episodeNumber") or 0) > 0
    }
    selling = seed_analysis.get("sellingPoints") if isinstance(seed_analysis, dict) and isinstance(seed_analysis.get("sellingPoints"), dict) else {}
    base_story = (
        _coerce_outline_text(selling.get("logline"), limit=180)
        or _derive_outline_logline(outline)
        or _coerce_outline_text(outline, limit=180)
        or "主线事件继续推进"
    )
    core_conflict = _coerce_outline_text(selling.get("conflict"), limit=160) if isinstance(selling, dict) else ""
    sentences = _split_outline_analysis_sentences(outline)
    fallback_items: list[dict[str, Any]] = []
    for ep_no in range(1, target + 1):
        item = by_no.get(ep_no)
        if item:
            summary = _coerce_outline_text(item.get("summary"), limit=260)
            conflict = _coerce_outline_text(item.get("conflict"), limit=180)
            turning = _coerce_outline_text(item.get("turning"), limit=160)
            title = _coerce_outline_text(item.get("title"), limit=60) or f"第{ep_no}集"
        else:
            source_sentence = sentences[(ep_no - 1) % len(sentences)] if sentences else base_story
            phase = "开端" if ep_no <= max(1, target // 3) else "升级" if ep_no <= max(1, target * 2 // 3) else "收束"
            title = f"第{ep_no}集"
            summary = _compact_outline_analysis_text(
                f"{phase}阶段：围绕“{base_story}”，推进本集具体事件：{source_sentence}",
                limit=260,
            )
            conflict = core_conflict
            turning = ""
        fallback_items.append({
            "episodeNumber": ep_no,
            "title": title,
            "episode_outline": summary,
            "conflict": conflict,
            "turning": turning,
        })
    return _repair_outline_episode_quality(
        fallback_items,
        outline=outline,
        target_episodes=target,
        seed_analysis=seed_analysis,
    )


def _retrieve_outline_rag_block(
    *,
    outline: str,
    seed_analysis: dict[str, Any] | None,
    datasets: tuple[str, ...] = ("moxi_scripts", "asset_library_hq"),
    per_top_k: int = 4,
    max_chars: int = 2600,
) -> str:
    """从 Dify 检索同赛道爆款全季骨架/高分桥段，拼成参考块。

    任何失败（未配置 / 不可达 / 已在事件循环中）都返回空串，绝不阻断集纲生成。
    """
    try:
        import asyncio

        from app.services.rag_service import get_rag_retriever
    except Exception:
        return ""
    try:
        rag = get_rag_retriever()
    except Exception:
        return ""
    if not getattr(rag, "enabled", False):
        return ""

    axis = _outline_story_axis(outline, seed_analysis)
    selling = (
        seed_analysis.get("sellingPoints")
        if isinstance(seed_analysis, dict) and isinstance(seed_analysis.get("sellingPoints"), dict)
        else {}
    )
    query = " ".join(
        part
        for part in [
            axis,
            _coerce_outline_text(selling.get("conflict"), limit=60),
            _coerce_outline_text(selling.get("logline"), limit=90),
        ]
        if part
    ).strip()[:220] or (outline or "").strip()[:220]

    async def _go() -> list[str]:
        refs: list[str] = []
        for dataset in datasets:
            try:
                chunks = await rag.retrieve(dataset=dataset, query=query, top_k=per_top_k)
            except Exception:
                chunks = []
            for chunk in chunks:
                text = (chunk.as_reference() if hasattr(chunk, "as_reference") else str(chunk)).strip()
                if text:
                    refs.append(text[:420])
        return refs

    try:
        refs = asyncio.run(_go())
    except RuntimeError:
        return ""  # 已处于运行中的事件循环：跳过 RAG，不阻断主流程
    except Exception:
        return ""
    if not refs:
        return ""
    return ("\n---\n".join(refs))[:max_chars]


def _generate_episode_frameworks(
    *,
    outline: str,
    target_episodes: int,
    temperature: float,
    seed_analysis: dict[str, Any] | None = None,
    rag_block: str | None = None,
    progress_cb: Any = None,
    generation_kwargs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from app.services.text_generation_service import generate_json, TextGenerationError

    target = _require_confirmed_target_episodes(target_episodes)
    batch_size = OUTLINE_EPISODE_GENERATE_BATCH_SIZE
    if rag_block is None:
        rag_block = _retrieve_outline_rag_block(outline=outline, seed_analysis=seed_analysis)
    system_prompt = """你是短剧全剧情推演规划师。你的任务是把用户的大纲先做全剧情因果推演，再输出集纲。

硬规则：
- 必须严格覆盖指定集号范围，不能少集、不能合并集。
- 如果原文是“前10集/中间20集/后30集”这类三段式大纲，必须展开为逐集集纲。
- 每集必须承接上一集结果，不能重启同一冲突。
- 每集只推进当前集应发生的信息，不能提前吃掉后续大反转。
- 分集框架只写“集纲/本集事件”，不要输出开场钩子、结尾钩子、尾钩或下一集预告。
- 输出纯 JSON 对象，不要 markdown，不要解释。

JSON 格式：
{
  "episodes": [
    {
      "episodeNumber": 1,
      "title": "本集标题",
      "episode_outline": "本集集纲：这一集具体发生的事件，必须是可拍动作和因果推进，不写抽象结构评价",
      "conflict": "本集核心冲突",
      "turning": "本集转折/爆点"
    }
  ]
}"""
    analysis_context = _outline_generation_context(seed_analysis)
    quality_axis = _outline_quality_rule_context(outline, seed_analysis, target)
    rag_reference_block = (
        f"""## 同赛道爆款全季骨架参考（RAG 检索 · 仅借鉴节拍分布/集尾倒钩/付费墙节奏与场景多样性，严禁照搬人名台词具体情节）
{rag_block}

"""
        if rag_block
        else ""
    )
    quality_rule_block = f"""规则结构（必须内化到每集，不要输出为尾钩字段）：
- 每集必须有 main_event / main_scene / relationship_change / info_revealed / conflict / turning。
- main_event 必须是不可逆事件，不能写“继续调查/继续冲突/局势升级”这类空话。
- conflict 必须写清：地点 + 角色目标 + 对手阻断方式。
- turning 必须写清：本集爆点或反转如何改变关系、信息或权力状态。
- 追看类型轮换参考：{' → '.join(quality_axis.get('hook_rotation') or [])}。
- 爽点类型轮换参考：{' → '.join(quality_axis.get('satisfaction_rotation') or [])}。
- 场景必须多样，参考：{'、'.join(_OUTLINE_SCENE_ROTATION[:12])}。
- 连续 5 集内不得重复同一主事件、同一冲突表达或同一爆点模板。"""
    all_items: list[dict[str, Any]] = []
    prev_summary = ""
    used_titles: list[str] = []
    used_scenes: list[str] = []
    used_events: list[str] = []

    for batch_start in range(1, target + 1, batch_size):
        batch_end = min(batch_start + batch_size - 1, target)
        stage_hints = "；".join(
            f"第{ep}集[{_outline_episode_stage(ep, target)['stage']}]:{_outline_episode_stage(ep, target)['task']}"
            for ep in range(batch_start, batch_end + 1)
        )
        ledger_block = ""
        if used_titles or used_scenes or used_events:
            ledger_block = (
                "已使用、本批必须避免雷同的内容（标题不得重名/主要场景不得连续复用/主事件不得换皮重写）：\n"
                f"- 已用标题：{'、'.join(used_titles[-40:])}\n"
                f"- 已用主要场景：{'、'.join(list(dict.fromkeys(used_scenes))[-24:])}\n"
                f"- 已发生主事件：{'；'.join(used_events[-24:])}\n\n"
            )
        user_prompt = f"""请基于以下大纲做全剧情推演，并只输出第 {batch_start}-{batch_end} 集的集纲。

目标总集数：{target}
本批集号：{batch_start}-{batch_end}
本批每集所处爆款阶段（main_event 密度与类型必须贴合该阶段）：{stage_hints}

原始大纲：
---
{outline.strip()}
---

已提取信息：
{analysis_context or "（无）"}

{rag_reference_block}{quality_rule_block}

{ledger_block}前序批次摘要（必须严格承接，不得重启已结束的冲突）：
{prev_summary or "（首批，无前序）"}

要求：
1. 只输出第 {batch_start}-{batch_end} 集，不要输出其他集。
2. 每集 episode_outline 必须是具体事件，不要写“铺垫/升级/反转/收束”等纯结构词。
3. 不要输出 hook、opening_hook、cliffhanger、ending_hook、tail_hook、尾钩。
4. 每集必须额外输出 main_scene、relationship_change、info_revealed、satisfaction_type、hook_subtag，供后端做质量校验。
5. 严禁与上面“已使用内容”雷同：标题不得重名、主要场景不得连续重复、主事件不得换皮重写。
6. 输出 JSON 对象，键名为 episodes。"""
        try:
            payload = generate_json(
                system_prompt,
                user_prompt,
                temperature=temperature,
                max_tokens=5000,
                timeout_seconds=OUTLINE_EPISODE_GENERATE_BATCH_TIMEOUT_SECONDS,
                max_retries=1,
                **_clean_outline_generation_kwargs(generation_kwargs),
            )
        except TextGenerationError as exc:
            raise HTTPException(status_code=400, detail=f"第 {batch_start}-{batch_end} 集集纲生成失败: {exc}")
        batch_items = _normalize_outline_episode_batch(
            _extract_episode_payload(payload),
            target_episodes=target,
            batch_start=batch_start,
            batch_end=batch_end,
        )
        all_items.extend(batch_items)
        for item in batch_items:
            title = _coerce_outline_text(item.get("title"), limit=30)
            if title:
                used_titles.append(title)
            scene = _coerce_outline_text(item.get("main_scene"), limit=24)
            if scene:
                used_scenes.append(scene)
            event = _coerce_outline_text(
                item.get("main_event") or item.get("episode_outline") or item.get("summary"), limit=60
            )
            if event:
                used_events.append(event)
        prev_summary = (
            prev_summary
            + "\n"
            + "\n".join(
                f"第{item['episodeNumber']}集：{_coerce_outline_text(item.get('title'), limit=20)}"
                f"｜事件:{_coerce_outline_text(item.get('main_event') or item.get('episode_outline') or item.get('summary'), limit=70)}"
                f"｜场景:{_coerce_outline_text(item.get('main_scene'), limit=16)}"
                f"｜信息:{_coerce_outline_text(item.get('info_revealed'), limit=40)}"
                for item in batch_items
            )
        )[-3600:]
        if progress_cb is not None:
            try:
                progress_cb(min(batch_end, target), target)
            except Exception:
                pass

    dedup: dict[int, dict[str, Any]] = {}
    for item in all_items:
        ep_no = int(item["episodeNumber"])
        if 1 <= ep_no <= target and ep_no not in dedup:
            dedup[ep_no] = item

    seed_by_no = _seed_outline_episode_map(seed_analysis, target)
    for ep_no in range(1, target + 1):
        if ep_no in dedup or ep_no not in seed_by_no:
            continue
        seed_item = dict(seed_by_no[ep_no])
        seed_item["source"] = seed_item.get("source") or "seed_outline"
        seed_item["review_status"] = seed_item.get("review_status") or "needs_user_review"
        dedup[ep_no] = seed_item

    missing = [n for n in range(1, target + 1) if n not in dedup]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"集纲完整性不足：要求 {target} 集，实际 {len(dedup)} 集，缺失 {missing[:20]}{'...' if len(missing) > 20 else ''}",
        )
    return _repair_outline_episode_quality(
        [dedup[n] for n in range(1, target + 1)],
        outline=outline,
        target_episodes=target,
        seed_analysis=seed_analysis,
    )


def _prediction_target_episodes(outline: str, requested: int | None) -> int:
    return max(1, min(200, int(requested or _infer_outline_target_episodes(outline) or 12)))


def _require_confirmed_target_episodes(requested: int | None) -> int:
    if requested is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "episode_count_unconfirmed",
                "message": "请先确认总集数；用户确认多少集，系统就按多少集生成。",
            },
        )
    try:
        target = int(requested)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "episode_count_unconfirmed",
                "message": "请先确认总集数；用户确认多少集，系统就按多少集生成。",
            },
        ) from exc
    if target < 1:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "episode_count_unconfirmed",
                "message": "请先确认总集数；用户确认多少集，系统就按多少集生成。",
            },
        )
    return max(1, min(200, target))


def _outline_prediction_seed_value(seed_analysis: dict[str, Any] | None, key: str) -> str:
    if not isinstance(seed_analysis, dict):
        return ""
    selling = seed_analysis.get("sellingPoints")
    if isinstance(selling, dict):
        aliases = {
            "goldenFinger": ("goldenFinger", "golden_finger", "uniqueness"),
            "worldview": ("worldview",),
            "conflict": ("conflict",),
            "logline": ("logline", "brief"),
        }.get(key, (key,))
        for alias in aliases:
            value = _coerce_outline_text(selling.get(alias), limit=320)
            if value:
                return value
    return ""


def _normalize_prediction_characters(items: Any, fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    use_fallback = not (isinstance(items, list) and items)
    source = fallback if use_fallback else items
    default_source = "source" if use_fallback else "ai"
    characters: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(source):
        if not isinstance(item, dict):
            continue
        name = _clean_outline_character_name(
            _coerce_outline_text(item.get("name") or item.get("character_name"), limit=24)
        )
        if not _outline_is_valid_character_name(name) or name in seen:
            continue
        role = _outline_character_role(_coerce_outline_text(item.get("role") or item.get("position"), limit=40), index)
        raw_info = _coerce_outline_text(
            item.get("info")
            or item.get("description")
            or item.get("identity")
            or item.get("background")
            or item.get("motivation"),
            limit=1000,
        )
        info = _sanitize_outline_character_info(raw_info, name=name, limit=1000)
        characters.append({
            "name": name,
            "role": role,
            "info": info,
            "source": _coerce_outline_text(item.get("source"), limit=20) or default_source,
        })
        seen.add(name)
    return characters


def _merge_prediction_characters_with_seed(
    raw_items: Any,
    fallback: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Keep user/seed characters authoritative and only use AI to enrich or add missing roles."""
    seeded = _normalize_prediction_characters(fallback, [])
    by_key: dict[str, dict[str, str]] = {}
    ordered_keys: list[str] = []

    for item in seeded:
        key = _outline_character_alias_key(item.get("name", ""))
        if not key:
            continue
        by_key[key] = dict(item)
        ordered_keys.append(key)

    has_seed_protagonist = any(item.get("role") == "protagonist" for item in seeded)
    for item in _normalize_prediction_characters(raw_items, []):
        key = _outline_character_alias_key(item.get("name", ""))
        if not key:
            continue
        existing = by_key.get(key)
        if existing:
            # Preserve the canonical seed name/role. This prevents variants such as 何征 overwriting 何铮.
            extra_info = item.get("info", "") if _outline_is_useful_character_info(item.get("info", "")) else ""
            existing["info"] = _outline_merge_unique_text(
                existing.get("info", ""),
                extra_info,
                limit=1200,
            )
            if existing.get("role") == "minor" and item.get("role") in {"supporting", "antagonist"}:
                existing["role"] = item["role"]
            existing["source"] = existing.get("source") or item.get("source") or "source"
            continue

        role = item.get("role") or "supporting"
        if role == "protagonist" and has_seed_protagonist:
            role = "supporting"
        item["role"] = role
        item["source"] = item.get("source") or "ai"
        if not _outline_is_useful_character_info(item.get("info", "")) and item["source"] == "ai":
            continue
        by_key[key] = item
        ordered_keys.append(key)

    return [by_key[key] for key in ordered_keys if key in by_key]


def _build_outline_prediction_fallback(
    *,
    outline: str,
    target_episodes: int | None = None,
    seed_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = _prediction_target_episodes(outline, target_episodes)
    fallback_analysis = _build_outline_analysis_fallback(outline, min(target, OUTLINE_ANALYZE_EPISODE_CAP))
    selling = dict(fallback_analysis.get("sellingPoints") or {})
    for key in ("logline", "worldview", "conflict"):
        selling[key] = selling.get(key) or _outline_prediction_seed_value(seed_analysis, key)
    selling["uniqueness"] = selling.get("uniqueness") or _outline_prediction_seed_value(seed_analysis, "goldenFinger")

    explicit_mainline = _pick_labeled_outline_value(outline, ["故事主线", "主线写法", "主线"], limit=360)
    logline = _coerce_outline_text(selling.get("logline"), limit=260)
    # 前端 /outline/analyze 给的角色（seed）经过专用提示词提取，比正则兜底干净；
    # 有合法 seed 角色时以 seed 为权威，正则兜底只作补充，避免“大纲走向/身世线推进”等碎片污染人物小传。
    _seed_characters_src = seed_analysis.get("characters") if isinstance(seed_analysis, dict) else []
    seed_characters = [
        c
        for c in (_seed_characters_src or [])
        if isinstance(c, dict)
        and _outline_is_valid_character_name(_clean_outline_character_name(_coerce_outline_text(c.get("name"), limit=24)))
    ]
    if seed_characters:
        characters = _merge_prediction_characters_with_seed(
            fallback_analysis.get("characters") or [],
            seed_characters,
        )
    else:
        characters = _merge_prediction_characters_with_seed(
            None,
            fallback_analysis.get("characters") or [],
        )
    worldview = _coerce_outline_text(selling.get("worldview"), limit=320)
    golden_finger = _coerce_outline_text(selling.get("uniqueness"), limit=320)
    conflict = _coerce_outline_text(selling.get("conflict"), limit=260)
    generated_fields: list[str] = []
    if not worldview:
        worldview = _derive_outline_worldview(outline)
        if worldview:
            generated_fields.append("worldview")
    if not golden_finger:
        golden_finger = _derive_outline_golden_finger(outline)
        if golden_finger:
            generated_fields.append("goldenFinger")
    if not conflict:
        conflict = _derive_outline_conflict(outline, characters)
        if conflict:
            generated_fields.append("conflict")
    selling["worldview"] = worldview
    selling["uniqueness"] = golden_finger
    selling["conflict"] = conflict
    mainline = explicit_mainline
    if not mainline and (logline or conflict):
        mainline = _compact_outline_analysis_text(
            f"围绕“{logline or conflict}”推进，先确立主角目标与对手压力，再通过连续事件升级矛盾，最终回收核心冲突。",
            limit=360,
        )

    special_settings = _pick_labeled_outline_value(outline, ["特殊设定", "核心设定", "差异化"], limit=260)
    selling_points = _pick_labeled_outline_value(outline, ["爽点", "看点", "卖点"], limit=260)
    episodes = _generate_episode_frameworks_fallback(
        outline=outline,
        target_episodes=target,
        seed_analysis={
            "sellingPoints": selling,
            "characters": characters,
        },
    )
    if mainline and not explicit_mainline:
        generated_fields.append("mainline")
    if episodes:
        generated_fields.append("episodes")

    prediction = {
        "logline": logline,
        "worldview": worldview,
        "goldenFinger": golden_finger,
        "conflict": conflict,
        "mainline": mainline,
        "character_count": len(characters),
        "characters": characters,
        "episodes": episodes,
        "details": {
            "worldview": worldview,
            "goldenFinger": golden_finger,
            "specialSettings": special_settings or golden_finger,
            "coreConflict": conflict,
            "sellingPoints": selling_points,
        },
    }
    return {
        "prediction": prediction,
        "generated_fields": generated_fields,
        "fallback": True,
        "fallback_reason": "local_prediction",
        **_local_fallback_candidate_boundary("local_prediction"),
    }


def _merge_outline_prediction_with_fallback(
    result: dict[str, Any],
    fallback: dict[str, Any],
    target_episodes: int,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        return fallback
    raw_prediction = result.get("prediction") if isinstance(result.get("prediction"), dict) else result
    if not isinstance(raw_prediction, dict):
        return fallback

    merged = json.loads(json.dumps(fallback, ensure_ascii=False))
    prediction = merged["prediction"]
    generated_fields = set(merged.get("generated_fields") or [])

    for key in ("logline", "worldview", "goldenFinger", "conflict", "mainline"):
        value = _coerce_outline_text(raw_prediction.get(key), limit=380)
        if value:
            if prediction.get(key) != value:
                generated_fields.add(key)
            prediction[key] = value

    details = raw_prediction.get("details") if isinstance(raw_prediction.get("details"), dict) else {}
    if details:
        prediction.setdefault("details", {})
        for key in ("worldview", "goldenFinger", "specialSettings", "coreConflict", "sellingPoints"):
            value = _coerce_outline_text(details.get(key), limit=380)
            if value:
                if prediction["details"].get(key) != value:
                    generated_fields.add(f"details.{key}")
                prediction["details"][key] = value

    characters = _merge_prediction_characters_with_seed(raw_prediction.get("characters"), prediction.get("characters") or [])
    if characters:
        if characters != prediction.get("characters"):
            generated_fields.add("characters")
        prediction["characters"] = characters
        prediction["character_count"] = len(characters)

    episodes = _normalize_outline_episode_list(
        raw_prediction.get("episodes") or raw_prediction.get("episode_outlines"),
        target_episodes,
    )
    if episodes:
        fallback_by_no = {int(item.get("episodeNumber") or 0): item for item in prediction.get("episodes") or []}
        merged_by_no = {int(item["episodeNumber"]): item for item in episodes if item.get("episodeNumber")}
        for ep_no in range(1, target_episodes + 1):
            if ep_no not in merged_by_no and ep_no in fallback_by_no:
                merged_by_no[ep_no] = fallback_by_no[ep_no]
        prediction["episodes"] = _repair_outline_episode_quality(
            [merged_by_no[n] for n in sorted(merged_by_no)[:target_episodes]],
            outline="",
            target_episodes=target_episodes,
            seed_analysis={
                "sellingPoints": {
                    "logline": prediction.get("logline"),
                    "worldview": prediction.get("worldview"),
                    "conflict": prediction.get("conflict"),
                    "uniqueness": prediction.get("goldenFinger"),
                },
                "characters": characters,
            },
        )
        generated_fields.add("episodes")

    result_generated = result.get("generated_fields")
    if isinstance(result_generated, list):
        generated_fields.update(str(item) for item in result_generated if item)

    merged["generated_fields"] = sorted(generated_fields)
    merged["fallback"] = False
    merged.pop("fallback_reason", None)
    return merged


def _predict_outline_payload(
    *,
    outline: str,
    target_episodes: int | None,
    temperature: float,
    seed_analysis: dict[str, Any] | None = None,
    generation_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the global story prediction once and return a complete, repaired structure."""
    from app.services.text_generation_service import generate_json, TextGenerationError, generation_enabled

    target = _prediction_target_episodes(outline, target_episodes)
    fallback = _build_outline_prediction_fallback(
        outline=outline,
        target_episodes=target,
        seed_analysis=seed_analysis,
    )
    if not generation_enabled():
        fallback["fallback_reason"] = "text_generation_disabled"
        return fallback

    rag_block = _retrieve_outline_rag_block(outline=outline, seed_analysis=seed_analysis)
    rag_reference_block = (
        f"""## 同赛道爆款参考（RAG 检索 · 借鉴世界观写法/人设维度/主线推进，严禁照搬人名台词具体情节）
{rag_block}

"""
        if rag_block
        else ""
    )

    # 这一步只预测“元信息”（梗概/世界观/金手指/核心冲突/极纲/人物小传），输出小、速度快。
    # 逐集集纲不在这里产出，改由 _generate_episode_frameworks 分批真实生成，
    # 避免“单次大调用要全部集纲”超时退化成模板（这正是旧版重复的根因）。
    system_prompt = """你是短剧全剧预测策划，只做生成前的“结构预测”和缺失项补全，不写逐集集纲、不写正文。

硬规则：
- 必须基于用户大纲与已有字段，不得推翻已有事实；大纲没写的可合理补足，并把字段名写入 generated_fields。
- 一句话梗概必须描述故事本身：主角 + 处境/事件 + 行动 + 对手/冲突；不能只写“现代都市/女频/悬疑”等品类标签。
- worldview（世界观）：交代时代、地点、规则与特殊世界设定，2-4 句，具体可感。
- characters（人物小传）：每个主要角色一段可直接用于生成的小传——身份、动机、底牌/秘密、与主角的关系张力；以已有角色为权威，同名不得拆成两人。
- mainline（极纲/全剧主线骨架）：一段话写清本剧专属的全剧因果主线——主角目标如何确立 → 第一推力 → 中段如何连环升级 → 首付墙（最强未兑现悬念）→ 风暴段核心反转 → 终局如何兑现/反派下场/情感落点。禁止套话与品类描述。
- 输出纯 JSON 对象，不要 markdown，不要解释，不要输出 episodes 字段。

JSON 格式：
{
  "prediction": {
    "logline": "全剧一句话梗概",
    "worldview": "世界观/背景；没有则合理补全",
    "goldenFinger": "金手指/特殊设定；没有则留空",
    "conflict": "核心冲突/爽点",
    "mainline": "极纲：本剧专属的全剧因果主线（开端→首付墙→风暴→终局）",
    "character_count": 3,
    "characters": [
      {"name": "角色名", "role": "protagonist|antagonist|supporting|minor", "info": "人物小传：身份+动机+底牌/秘密+与主角关系张力", "source": "source|ai"}
    ],
    "details": {
      "worldview": "世界观",
      "goldenFinger": "金手指",
      "specialSettings": "特殊设定",
      "coreConflict": "核心冲突",
      "sellingPoints": "爽点/追看动力"
    }
  },
  "generated_fields": ["worldview", "mainline"]
}"""
    user_prompt = f"""请对下面的大纲做“剧本结构预测”，补齐缺失字段（不要输出逐集集纲）。

目标集数：{target}

原始大纲/当前字段：
---
{outline.strip()}
---

已有结构化信息：
{json.dumps(seed_analysis or {}, ensure_ascii=False)}

{rag_reference_block}要求：
1. 重点产出 mainline（极纲）：本剧专属的全剧因果主线，必须覆盖开端→首付墙→风暴→终局四段，写成连贯因果，不要套话。
2. worldview 与每个 character.info 要具体、可直接用于后续逐集生成。
3. logline 必须是故事本身，不能是品类标签。
4. generated_fields 标明所有由 AI 补足的字段。"""

    try:
        result = generate_json(
            system_prompt,
            user_prompt,
            temperature=temperature,
            max_tokens=2600,
            timeout_seconds=OUTLINE_PREDICT_TIMEOUT_SECONDS,
            max_retries=1,
            **_clean_outline_generation_kwargs(generation_kwargs),
        )
        return _merge_outline_prediction_with_fallback(result, fallback, target)
    except (TextGenerationError, HTTPException) as exc:
        fallback["fallback_reason"] = type(exc).__name__
        return fallback


class OutlineAnalyzeRequest(BaseModel):
    outline: str = Field(..., description="原始大纲文本", min_length=10)
    temperature: float = Field(0.3, description="生成温度（低温提高结构稳定性）", ge=0.0, le=1.0)
    target_episodes: Optional[int] = Field(None, description="目标集数；传入后会把三段式大纲展开为逐集集纲", ge=1, le=200)


class OutlineEpisodesGenerateRequest(BaseModel):
    outline: str = Field(..., description="原始大纲或已结构化大纲文本", min_length=10)
    target_episodes: Optional[int] = Field(None, description="用户确认后的目标集数", ge=1, le=200)
    temperature: float = Field(0.3, description="生成温度", ge=0.0, le=1.0)
    project_id: str | None = Field(default=None, description="项目 ID，用于解析项目级多模型路由")
    generation_provider: str | None = Field(default=None, description="项目基础生成供应商")
    generation_model: str | None = Field(default=None, description="项目基础生成模型")
    seed_analysis: dict[str, Any] | None = Field(
        default=None,
        description="前端大纲分析结果，用于给分集生成补充卖点和角色上下文",
    )


class OutlinePredictRequest(BaseModel):
    outline: str = Field(..., description="原始大纲或已结构化大纲文本", min_length=10)
    target_episodes: Optional[int] = Field(None, description="目标集数", ge=1, le=200)
    temperature: float = Field(0.25, description="生成温度", ge=0.0, le=1.0)
    seed_analysis: dict[str, Any] | None = Field(
        default=None,
        description="前端已有大纲字段，用于只补齐缺失项",
    )


def _decode_outline_upload_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _extract_docx_outline_text(raw: bytes) -> str:
    from io import BytesIO
    import re

    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except Exception as exc:  # pragma: no cover - dependency exists in runtime requirements
        raise HTTPException(status_code=500, detail="服务器缺少 Word 文档解析依赖 python-docx") from exc

    try:
        document = Document(BytesIO(raw))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Word 文档读取失败，请确认文件不是损坏或加密文档") from exc

    parts: list[str] = []
    table_no = 0

    def clean_cell_text(value: str) -> str:
        text = str(value or "").replace("\u00a0", " ").replace("\r", "\n")
        lines = [" ".join(line.split()).strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        return " / ".join(lines)

    def append_table(table: Table) -> None:
        nonlocal table_no
        table_no += 1
        table_lines: list[str] = []
        for row in table.rows:
            cells: list[str] = []
            previous = ""
            for cell in row.cells:
                text = clean_cell_text(cell.text)
                if not text or text == previous:
                    previous = text
                    continue
                cells.append(text)
                previous = text
            if cells:
                table_lines.append(" | ".join(cells))
        if table_lines:
            parts.append(f"【表格{table_no}】")
            parts.extend(table_lines)

    for child in document.element.body.iterchildren():
        tag = str(child.tag or "")
        if tag.endswith("}p"):
            paragraph = Paragraph(child, document)
            text = re.sub(r"\s+", " ", paragraph.text.replace("\u00a0", " ")).strip()
            if text:
                parts.append(text)
        elif tag.endswith("}tbl"):
            append_table(Table(child, document))
    return "\n".join(parts)


@router.post("/outline/extract-file", summary="读取大纲上传文件")
async def extract_outline_file(
    file: UploadFile = File(...),
    _: ProjectAccessActor = Depends(verify_project_actor),
):
    filename = file.filename or "outline"
    suffix = Path(filename).suffix.lower()
    if suffix not in {".docx", ".md", ".markdown", ".txt"}:
        raise HTTPException(status_code=400, detail="当前只支持 Word(.docx)、Markdown(.md) 和 TXT 文本")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(raw) > OUTLINE_UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件过大，请控制在 8MB 以内")

    if suffix == ".docx":
        text = _extract_docx_outline_text(raw)
        kind = "docx"
    else:
        text = _decode_outline_upload_text(raw)
        kind = "markdown" if suffix in {".md", ".markdown"} else "txt"

    text = text.replace("\r", "\n").strip()
    if not text:
        raise HTTPException(status_code=400, detail="文件中没有可识别的大纲文本")
    truncated = len(text) > OUTLINE_UPLOAD_TEXT_MAX_CHARS
    if truncated:
        text = text[:OUTLINE_UPLOAD_TEXT_MAX_CHARS]
    return {
        "filename": filename,
        "kind": kind,
        "text": text,
        "chars": len(text),
        "truncated": truncated,
    }


@router.post("/outline/analyze", summary="智能分析大纲（OutlineEditor 专用）")
async def analyze_outline(
    req: OutlineAnalyzeRequest,
    _: ProjectAccessActor = Depends(verify_project_actor),
):
    """
    调用 AI 对原始大纲进行结构化分析，返回 AnalysisResult JSON。
    供 OutlineEditorView 的"分析大纲"功能使用，替代原有 mock 数据。
    """
    from app.services.text_generation_service import generate_json, TextGenerationError, generation_enabled

    inferred_target = req.target_episodes or _infer_outline_target_episodes(req.outline)
    analysis_target = max(3, min(OUTLINE_ANALYZE_EPISODE_CAP, int(inferred_target or 10)))
    fallback = _build_outline_analysis_fallback(req.outline, analysis_target)

    def _supplement_dialogue_speakers(payload: dict[str, Any]) -> dict[str, Any]:
        """输入是带对白的剧本正文、却没解析出角色时，用台词说话人补齐 characters。"""
        if isinstance(payload, dict) and not (payload.get("characters") or []):
            speakers = _extract_dialogue_speakers(req.outline)
            if speakers:
                payload["characters"] = [
                    {"id": f"char-{i + 1}", "name": s["name"], "role": s["role"], "info": s.get("info", "")}
                    for i, s in enumerate(speakers)
                ]
        return payload

    if not generation_enabled():
        return _supplement_dialogue_speakers(fallback)

    if len(req.outline or "") >= OUTLINE_ANALYZE_FAST_FALLBACK_CHARS:
        return _supplement_dialogue_speakers(fallback)

    user_prompt = f"""请分析以下短剧大纲：

---
{req.outline.strip()}
---

请严格按照系统提示的 JSON 格式返回分析结果，不要包含任何 markdown 代码块标记。"""

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                generate_json,
                _OUTLINE_ANALYZE_SYSTEM,
                user_prompt,
                temperature=req.temperature,
                max_tokens=4096,
            ),
            timeout=OUTLINE_ANALYZE_TIMEOUT_SECONDS,
        )
    except (asyncio.TimeoutError, TextGenerationError):
        return _supplement_dialogue_speakers(fallback)

    return _supplement_dialogue_speakers(_merge_outline_analysis_with_fallback(result, fallback, analysis_target))


@router.post("/outline/predict", summary="剧本预测与大纲缺失项补全")
async def predict_outline(
    req: OutlinePredictRequest,
    _: ProjectAccessActor = Depends(verify_project_actor),
):
    """
    在剧本正式生成前进行全剧预测：角色数量、逐集集纲、故事主线和细节设定。
    接口始终返回可用结构；AI 不可用或超时时回退到本地规则预测，避免前端按钮空转。
    """
    target = _require_confirmed_target_episodes(req.target_episodes)
    fallback = _build_outline_prediction_fallback(
        outline=req.outline,
        target_episodes=target,
        seed_analysis=req.seed_analysis,
    )
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _predict_outline_payload,
                outline=req.outline,
                target_episodes=target,
                temperature=req.temperature,
                seed_analysis=req.seed_analysis,
            ),
            timeout=OUTLINE_PREDICT_TIMEOUT_SECONDS + 5,
        )
        return result
    except asyncio.TimeoutError as exc:
        fallback["fallback_reason"] = type(exc).__name__
        return fallback


def _predict_then_generate_episodes(
    *,
    outline: str,
    target: int,
    temperature: float,
    seed_analysis: dict[str, Any] | None,
    progress_cb: Any = None,
    generation_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """先做轻量元信息预测（梗概/世界观/极纲/人物），再用分批真实生成产出逐集集纲。

    在同一线程内串起来，供端点用单次 wait_for 包裹。
    """
    prediction_payload = _predict_outline_payload(
        outline=outline,
        target_episodes=target,
        temperature=temperature,
        seed_analysis=seed_analysis,
        generation_kwargs=generation_kwargs,
    )
    prediction = prediction_payload.get("prediction") if isinstance(prediction_payload, dict) else {}
    if not isinstance(prediction, dict):
        prediction = {}
    seed_for_eps = {
        "sellingPoints": {
            "logline": prediction.get("logline"),
            "conflict": prediction.get("conflict"),
            "worldview": prediction.get("worldview"),
            "uniqueness": prediction.get("goldenFinger"),
        },
        "characters": prediction.get("characters")
        or (seed_analysis.get("characters") if isinstance(seed_analysis, dict) else []),
        "episodes": seed_analysis.get("episodes") if isinstance(seed_analysis, dict) else [],
    }
    episodes = _generate_episode_frameworks(
        outline=outline,
        target_episodes=target,
        temperature=temperature,
        seed_analysis=seed_for_eps,
        progress_cb=progress_cb,
        generation_kwargs=generation_kwargs,
    )
    return {
        "episodes": episodes,
        "prediction": prediction,
        "global_prediction_used": True,
        "fallback": False,
        "fallback_reason": prediction_payload.get("fallback_reason") if isinstance(prediction_payload, dict) else "",
        "generated_fields": (prediction_payload.get("generated_fields") if isinstance(prediction_payload, dict) else []) or [],
    }


# ── 集纲生成后台任务（落库版）─────────────────────────────────────
# 30-60 集真实生成需 1-5 分钟，远超前端 90s 超时。改为后台任务：
# start 立即返回 job_id，前端轮询 status 取进度/结果。
# 任务落库 outline_episode_job：重启不丢、可多实例共享、按 owner(access_key) 隔离。
_OUTLINE_EPISODE_JOB_TASKS: set[Any] = set()  # 持有后台 task 引用，避免被 GC
_OUTLINE_EPISODE_JOB_TTL_SECONDS = 1800  # 完成/失败任务保留 30 分钟


def _cleanup_outline_episode_jobs(db: Session, *, now: datetime | None = None) -> None:
    """Keep active jobs visible while removing only terminal stale jobs.

    Pending/running jobs may be the user's only clue that a long task existed.
    If they are stale, mark them as error instead of deleting them outright.
    """
    from app.models.outline_job import OutlineEpisodeJob

    current = now or datetime.now()
    cutoff = current - timedelta(seconds=_OUTLINE_EPISODE_JOB_TTL_SECONDS)
    db.query(OutlineEpisodeJob).filter(
        OutlineEpisodeJob.updated_at < cutoff,
        OutlineEpisodeJob.status.in_(["done", "error"]),
    ).delete(synchronize_session=False)
    stale_active_jobs = db.query(OutlineEpisodeJob).filter(
        OutlineEpisodeJob.updated_at < cutoff,
        OutlineEpisodeJob.status.in_(["pending", "running"]),
    ).all()
    for job in stale_active_jobs:
        job.status = "error"
        job.error = "任务长时间没有进度，可能已在服务重启时中断，请重新生成"
        job.updated_at = current


def _outline_job_run(
    job_id: str,
    *,
    outline: str,
    target: int,
    temperature: float,
    seed_analysis: dict[str, Any] | None,
    generation_kwargs: dict[str, Any] | None = None,
    route_reason: str = "",
) -> None:
    """后台线程执行：独立 DB 会话，按批写进度，最终写结果/错误。"""
    from app.database import SessionLocal
    from app.models.outline_job import OutlineEpisodeJob

    def _update(**fields: Any) -> None:
        db = SessionLocal()
        try:
            job = db.query(OutlineEpisodeJob).filter(OutlineEpisodeJob.id == job_id).first()
            if job is not None:
                for key, value in fields.items():
                    setattr(job, key, value)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def _progress(done: int, total: int) -> None:
        _update(status="running", progress_done=int(done), progress_total=int(total))

    try:
        result = _predict_then_generate_episodes(
            outline=outline,
            target=target,
            temperature=temperature,
            seed_analysis=seed_analysis,
            progress_cb=_progress,
            generation_kwargs=generation_kwargs,
        )
        if generation_kwargs:
            result["generation_route"] = {
                key: value
                for key, value in _clean_outline_generation_kwargs(generation_kwargs).items()
                if key in {"provider", "model"}
            }
        if route_reason:
            result["generation_route_reason"] = route_reason
        _update(
            status="done",
            progress_done=target,
            progress_total=target,
            result_json=json.dumps(result, ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001 — 后台任务任何异常都要落到任务状态
        _update(status="error", error=str(exc) or type(exc).__name__)


class OutlineEpisodesStartRequest(BaseModel):
    outline: str = Field(..., description="原始大纲或已结构化大纲文本", min_length=10)
    target_episodes: Optional[int] = Field(None, description="用户确认后的目标集数", ge=1, le=200)
    temperature: float = Field(0.3, description="生成温度", ge=0.0, le=1.0)
    project_id: str | None = Field(default=None, description="项目 ID，用于解析项目级多模型路由")
    generation_provider: str | None = Field(default=None, description="项目基础生成供应商")
    generation_model: str | None = Field(default=None, description="项目基础生成模型")
    seed_analysis: dict[str, Any] | None = Field(
        default=None,
        description="前端大纲分析结果，用于补充卖点和角色上下文",
    )


def _clean_outline_generation_kwargs(raw: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key in ("provider", "model"):
        value = str(raw.get(key) or "").strip()
        if value:
            cleaned[key] = value
    return cleaned


def _resolve_outline_episode_generation_route(
    *,
    db: Session,
    actor: ProjectAccessActor,
    project_id: str | None,
    generation_provider: str | None,
    generation_model: str | None,
    temperature: float,
) -> tuple[dict[str, str], float, str]:
    base_kwargs = _clean_outline_generation_kwargs({
        "provider": generation_provider,
        "model": generation_model,
    })
    if not str(project_id or "").strip():
        return base_kwargs, temperature, "未提供项目 ID，沿用请求模型或全局默认模型。"

    project = _get_project_for_actor_or_404(db, str(project_id).strip(), actor)
    project_config = _normalize_project_config_payload(
        project.get_config(),
        project_type=project.project_type,
        audience_axis=project.audience_axis,
        genre_main=project.genre_main,
        genre_sub=project.genre_sub,
    )
    metadata = {
        "project": {
            "project_type": project.project_type,
            "config": project_config,
        }
    }
    route = resolve_step_generation_route(
        "episode_outlines",
        metadata,
        base_kwargs,
        temperature,
    )
    return (
        _clean_outline_generation_kwargs(route.generation_kwargs),
        float(route.temperature if route.temperature is not None else temperature),
        route.reason,
    )


@router.post("/outline/episodes/start", summary="启动集纲生成后台任务（立即返回 job_id）")
async def start_outline_episodes(
    req: OutlineEpisodesStartRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    """启动逐集集纲的后台生成：立即返回 job_id，前端轮询 status 取进度/结果。"""
    from app.services.text_generation_service import generation_enabled
    from app.database import SessionLocal
    from app.models.outline_job import OutlineEpisodeJob

    if not generation_enabled():
        raise HTTPException(status_code=503, detail="AI 生成服务未启用，请在模型设置中配置后再试")

    generation_kwargs, routed_temperature, route_reason = _resolve_outline_episode_generation_route(
        db=db,
        actor=actor,
        project_id=req.project_id,
        generation_provider=req.generation_provider,
        generation_model=req.generation_model,
        temperature=req.temperature,
    )
    target = _require_confirmed_target_episodes(req.target_episodes)
    job_id = uuid.uuid4().hex
    job_db = SessionLocal()
    try:
        _cleanup_outline_episode_jobs(job_db)
        job_db.add(
            OutlineEpisodeJob(
                id=job_id,
                owner_key=getattr(actor, "access_key_id", "") or "",
                owner_is_admin=bool(getattr(actor, "is_admin", False)),
                status="pending",
                progress_done=0,
                progress_total=target,
            )
        )
        job_db.commit()
    finally:
        job_db.close()

    task = asyncio.create_task(
        asyncio.to_thread(
            _outline_job_run,
            job_id,
            outline=req.outline,
            target=target,
            temperature=routed_temperature,
            seed_analysis=req.seed_analysis,
            generation_kwargs=generation_kwargs,
            route_reason=route_reason,
        )
    )
    _OUTLINE_EPISODE_JOB_TASKS.add(task)
    task.add_done_callback(_OUTLINE_EPISODE_JOB_TASKS.discard)

    return {"job_id": job_id, "status": "pending", "total": target}


@router.get("/outline/episodes/status/{job_id}", summary="查询集纲生成任务状态/进度/结果")
async def outline_episodes_status(
    job_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    from app.database import SessionLocal
    from app.models.outline_job import OutlineEpisodeJob

    db = SessionLocal()
    try:
        _cleanup_outline_episode_jobs(db)
        db.commit()
        job = db.query(OutlineEpisodeJob).filter(OutlineEpisodeJob.id == job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在或已过期，请重新生成")
        # 数据隔离：仅任务发起者本人或管理员可查询
        if not getattr(actor, "is_admin", False):
            if (job.owner_key or "") != (getattr(actor, "access_key_id", "") or ""):
                raise HTTPException(status_code=404, detail="任务不存在或已过期，请重新生成")

        out: dict[str, Any] = {
            "job_id": job_id,
            "status": job.status or "unknown",
            "progress": {"done": int(job.progress_done or 0), "total": int(job.progress_total or 0)},
        }
        if job.status == "done":
            try:
                result = json.loads(job.result_json or "{}")
            except Exception:
                result = {}
            out["episodes"] = result.get("episodes") or []
            out["prediction"] = result.get("prediction") or {}
            out["fallback"] = bool(result.get("fallback"))
            out["fallback_reason"] = result.get("fallback_reason") or ""
            out["generated_fields"] = result.get("generated_fields") or []
            for key in (
                "candidate_source",
                "needs_user_confirmation",
                "main_chain_committed",
                "downstream_generation_allowed",
                "candidate_boundary_reason",
            ):
                if key in result:
                    out[key] = result.get(key)
        elif job.status == "error":
            out["error"] = job.error or "生成失败"
        return out
    finally:
        db.close()


@router.post("/outline/episodes/generate", summary="按目标集数生成分集框架")
async def generate_outline_episodes(
    req: OutlineEpisodesGenerateRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    """
    将完整大纲或三段式大纲推演成逐集集纲，供前端“AI生成框架”使用。
    先做轻量元信息预测（极纲/世界观/人物），再分批真实生成逐集集纲；
    分批之间携带已生成清单与去重台账，避免批次重复；任一步失败回退到本地规则集纲。
    """
    target = _prediction_target_episodes(req.outline, req.target_episodes)
    generation_kwargs, routed_temperature, route_reason = _resolve_outline_episode_generation_route(
        db=db,
        actor=actor,
        project_id=req.project_id,
        generation_provider=req.generation_provider,
        generation_model=req.generation_model,
        temperature=req.temperature,
    )
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _predict_then_generate_episodes,
                outline=req.outline,
                target=target,
                temperature=routed_temperature,
                seed_analysis=req.seed_analysis,
                generation_kwargs=generation_kwargs,
            ),
            timeout=OUTLINE_EPISODE_GENERATE_TIMEOUT_SECONDS,
        )
        if result.get("episodes"):
            if route_reason:
                result["generation_route_reason"] = route_reason
            return result
    except Exception as exc:
        return {
            "episodes": _generate_episode_frameworks_fallback(
                outline=req.outline,
                target_episodes=target,
                seed_analysis=req.seed_analysis,
            ),
            "fallback": True,
            "fallback_reason": type(exc).__name__,
            "global_prediction_used": False,
            **_local_fallback_candidate_boundary("local_episode_frameworks"),
        }

    return {
        "episodes": _generate_episode_frameworks_fallback(
            outline=req.outline,
            target_episodes=target,
            seed_analysis=req.seed_analysis,
        ),
        "fallback": True,
        "fallback_reason": "empty_global_prediction",
        "global_prediction_used": False,
        **_local_fallback_candidate_boundary("local_episode_frameworks"),
    }
