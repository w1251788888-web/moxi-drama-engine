"""
管理端配置路由
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import verify_admin
from app.config import config
from app.services.text_generation_v2 import OpenAICompatibleClient


router = APIRouter(prefix="/admin/config", tags=["Admin Config"])
logger = logging.getLogger(__name__)


class ConfigUpdateRequest(BaseModel):
    """可更新的配置项"""
    project: Optional[dict] = Field(None, description='项目配置，如 {"name": "xxx"}')
    agent: Optional[dict] = Field(None, description='Agent 配置，如 {"registration_token": "xxx", "allow_registration": true}')
    notification: Optional[dict] = Field(None, description="通知配置")
    webui: Optional[dict] = Field(None, description="WebUI 配置")
    workspace: Optional[dict] = Field(None, description='工作目录配置，如 {"root": "/path"}')
    server: Optional[dict] = Field(None, description='服务配置，如 {"external_url": "https://..."}')
    market_insights: Optional[dict] = Field(None, description="市场验证配置，如热榜来源和评分权重")
    ai: Optional[dict] = Field(None, description='AI 配置，如 {"provider": "openai", "api_key": "...", "base_url": "...", "model": "..."}')


class UpdatePasswordRequest(BaseModel):
    old_password: str = Field(..., description="当前管理员密码")
    new_password: str = Field(..., min_length=6, description="新管理员密码")


@router.get("", summary="获取配置")
async def get_config(_: bool = Depends(verify_admin)):
    """获取脱敏后的配置"""
    return config.get_safe_config()


@router.put("", summary="更新配置")
async def update_config(req: ConfigUpdateRequest, _: bool = Depends(verify_admin)):
    """部分更新系统配置"""
    try:
        config.update(req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 配置变更后重置 RAG 单例，避免 base_url / api_key / datasets 更新但仍用旧客户端
    try:
        from app.services.rag_service import reset_rag_retriever
        reset_rag_retriever()
    except Exception:
        pass
    return config.get_safe_config()


@router.put("/password", summary="修改管理员密码")
async def update_password(req: UpdatePasswordRequest, _: bool = Depends(verify_admin)):
    """修改管理员密码"""
    try:
        config.update_password(req.old_password, req.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "密码修改成功"}


class AITestRequest(BaseModel):
    """AI 连接测试请求"""
    provider: str = Field(..., description="供应商 ID")
    api_key: str = Field(..., description="API Key")
    base_url: str = Field(..., description="API Base URL")
    model: str = Field(..., description="模型名称")


@router.post("/ai-test", summary="测试 AI API 连接")
async def test_ai_connection(req: AITestRequest, _: bool = Depends(verify_admin)):
    """测试 AI API 连接是否可用"""
    try:
        client = OpenAICompatibleClient(
            base_url=req.base_url,
            api_key=req.api_key,
            default_model=req.model
        )

        # 发送一个简单的测试请求
        # temperature=1 对普通模型和思考模型（如 kimi-k2.5）都兼容
        result = await client.generate(
            prompt="你好，这是一个测试消息，请回复'连接成功'。",
            model=req.model,
            system_prompt="你是一个 helpful 助手。",
            temperature=1,
            max_tokens=50
        )

        await client.close()

        return {
            "success": True,
            "message": "连接测试成功",
            "model": result.model,
            "response_preview": result.content[:100] if result.content else "无响应内容"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接测试失败: {str(e)}")


# ─── AI 创作聊天 ──────────────────────────────────────────────────────────────

# 规则文件基础路径（相对于本文件上溯到项目根目录）
_RULES_BASE = Path(__file__).parent.parent.parent.parent / "02-creation-rules" / "core-rules"

# 与前端 chatBrainstormContext.ts 共用的字符预算。Python 的 len() 和前端
# Array.from(...).length 都按 Unicode codepoint 计算，避免中文或 emoji 被两端
# 用不同规则错误截断。
CHAT_CONTEXT_MAX_CHARS = 18_000
_CHAT_CONTEXT_PACKET_REQUEST_HEADER = "\n\n【本轮用户要求】\n"


def _load_rule_file(filename: str, max_chars: int = 2000) -> str:
    """读取规则文件，限制长度避免 token 过多。文件不存在时静默返回空。"""
    path = _RULES_BASE / filename
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text[:max_chars] if len(text) > max_chars else text
    except Exception as exc:
        logger.warning("rule file unavailable: file=%s error=%s", filename, exc)
        return ""


def _build_category_rules(audience_axis: str, genre: str, format_type: str = "", *, include_dialogue: bool = True) -> str:
    """根据受众轴和题材类型，动态组装并返回规则注入文本。"""
    parts: list[str] = []

    # 注意：short_drama_core.md 等结构规则由新的 short_drama_writing.py 链路注入
    # admin_config.py 的 aiChat 仅用于大纲/角色等轻量建议，不注入剧本写作规则

    # 1. 受众轴规则
    axis = (audience_axis or "").strip()
    if "男频" in axis:
        rule = _load_rule_file("male_core.md")
        style = _load_rule_file("male_style.md", max_chars=800)
        if rule:
            parts.append(f"【男频受众核心规则】\n{rule}")
        if style:
            parts.append(f"【男频风格偏好】\n{style}")
    elif "女频" in axis:
        rule = _load_rule_file("female_core.md")
        style = _load_rule_file("female_style.md", max_chars=800)
        subgenre = _load_rule_file("female_subgenres.md", max_chars=1200)
        if rule:
            parts.append(f"【女频受众核心规则】\n{rule}")
        if style:
            parts.append(f"【女频风格偏好】\n{style}")
        if subgenre:
            parts.append(f"【女频子类型参考（按 genre_main 选取对应小节）】\n{subgenre}")
    else:
        rule = _load_rule_file("hybrid_genre.md", max_chars=1500)
        if rule:
            parts.append(f"【混合题材融合规则】\n{rule}")

    # 2. 对白规则（剧本/角色建议需要；选题反馈和聊天转大纲不注入，避免拖慢首轮响应）
    if include_dialogue:
        dialogue = _load_rule_file("short_drama_dialogue.md")
        if dialogue:
            parts.append(f"【对白规则】\n{dialogue}")

    # 3. 格式适配规则（漫剧/AI真人有特殊要求）
    fmt = (format_type or "").strip()
    if fmt and fmt != "真人短剧":
        fmt_rule = _load_rule_file("format_adaptation.md", max_chars=1000)
        if fmt_rule:
            parts.append(f"【格式适配规则（{fmt}）】\n{fmt_rule}")

    return "\n\n".join(parts)


class AIChatMessage(BaseModel):
    role: str = Field(..., description="角色: user | assistant | system")
    content: str = Field(..., description="消息内容")


class AIChatRequest(BaseModel):
    messages: List[AIChatMessage] = Field(..., description="对话历史")
    chat_context_packet: str | None = Field(
        None,
        description="前台已编译的完整聊天上下文包；仅 context=chat 时使用",
    )
    system_prompt: str = Field(
        "你是一个专业的短剧剧本创作助手，擅长爆款题材分析、故事结构设计和台词打磨。请用中文回复，保持专业且富有创意。",
        description="系统提示词"
    )
    context: str = Field("chat", description="上下文类型: chat|outline|character|script")
    max_tokens: int = Field(800, ge=50, le=4096, description="最大生成 token 数")
    audience_axis: Optional[str] = Field(None, description="受众轴: 男频|女频|混合")
    genre: Optional[str] = Field(None, description="题材类型，如「甜宠先婚后爱」「系统流」等")
    format_type: Optional[str] = Field(None, description="制作形式: 真人短剧|漫剧|AI真人")


_CONTEXT_PROMPTS = {
    "chat": """你是短剧选题策划，也是用户的创作脑暴伙伴。
直接理解用户本轮自然语言，结合完整聊天上下文继续讨论并提供新灵感。
不要根据“继续、下一步、好的”等词切换隐藏流程，也不要把模型回复视为用户确认。
所有大纲字段都由前台右侧确认区显式整理和确认。
请保持中文回复简洁、具体、有创作启发。""",
    "outline": """你是一位专业的短剧编剧，当前正在帮助用户优化大纲结构。

【大纲审核重点】
1. 一句话梗概：必须包含角色+冲突+独特设定，钩子力度强，10字内能吸引人
2. 世界观/赛道：设定是否独特，与市面同类区分度
3. 金手指设计：主角核心能力/优势是否合理且有张力
4. 分集节奏：每集必须有冲突升级，奇数集悬念，偶数集反转
5. 人物关系：主线关系是否有足够张力（恩怨/权力/情感）
6. 钩子密度：前3集是否都有强钩子（每集结尾1个视觉化悬念）

请给出具体、可操作的修改建议，不要泛泛而谈。""",
    "outline_structuring": """你负责把用户主动提交的聊天内容整理成大纲编辑器候选字段。
只允许整理：创作方向、一句话梗概、世界观、金手指/特殊设定、核心冲突、人物小传、人物关系、总集数和分集集纲。
模型结果只能是候选；不得把任何字段标记为用户已确认。
不得输出编辑器没有的隐藏字段，不做剧本正文，不输出 Markdown。""",
    "character": """你是一位角色设计专家，擅长创作有魅力、有弧光的短剧角色。

【角色设计审核重点】
1. 角色动机：是否清晰、强烈、与故事主题一致
2. 人物弧线：角色从哪里开始，经历什么改变，到哪里结束
3. 声音特征：这个角色说话有没有独特的腔调和口头禅
4. 关系张力：与其他角色的关系是否有足够冲突或情感张力
5. 功能定位：角色在故事中的功能是否清晰（推进情节/制造冲突/提供情感支撑）
6. 记忆点：观众记住这个角色的标签是什么

请分析角色设定的吸引力，并给出可操作的强化建议。""",
    "characters": """你是一位角色设计专家，擅长创作有魅力、有弧光的短剧角色。

【角色设计审核重点】
1. 角色动机：是否清晰、强烈、与故事主题一致
2. 人物弧线：角色从哪里开始，经历什么改变，到哪里结束
3. 声音特征：这个角色说话有没有独特的腔调和口头禅
4. 关系张力：与其他角色的关系是否有足够冲突或情感张力
5. 功能定位：角色在故事中的功能是否清晰（推进情节/制造冲突/提供情感支撑）
6. 记忆点：观众记住这个角色的标签是什么

请分析角色设定的吸引力，并给出可操作的强化建议。""",
    "script": """你是一位专业的短剧剧本写作专家，严格遵守以下写作规范。

【绝对禁止（任何情况下不得出现）】
❌ 禁止在结尾或任何位置出现"下集揭晓""预告下集""敬请期待""且听下回分解""欲知后事如何"等预告语或总结语
❌ 禁止用"VO（角色名）：下集..."做预告
❌ 禁止"画面渐黑""镜头定格""画面切换到"等电影镜头描述语
❌ 禁止旁白式叙述（如"这是他命运改变的开始""留下悬念"）
❌ 禁止在对白格式中加入非角色名前缀（如"系统女：SYS：内容"→应写"系统女：内容"）
❌ 禁止"场景标题："前缀标签（直接写 1-1  日  外  地点）

【剧本格式规范（严格执行）】
场景行：1-1  日  外  地点名称
动作描述：△动作描述（独占一行，写实际发生的物理动作）
对白：角色名：台词内容
内心独白：角色名OS：内容 / 角色名（情绪）OS：内容
离镜发声：VO（角色名）：内容

【字数要求】
- 90秒短剧目标约1200纯字符，默认交付区间为1000-1550纯字符
- 每集内部可自然分多场，按剧情需要推进，不由前端手动新建场次
- 每句台词必须有功能，不写废话

【核心结构】
- 开场1-3场必须出现冲突/威胁/反常，先结果后原因
- 每场戏：角色想要什么→谁阻止→如何行动→结局如何改变
- 每2-3句对白有转折点
- 每集结尾：用一个具体的台词或动作画面收尾，不用旁白总结

【对白原则】
- 短句口语化，拒绝解释性台词
- 不同角色有不同腔调
- 用行动代替说明

【节奏原则】
- 先冲击后解释
- 用画面说话，不用台词总结情绪
- 主角OS每集3-6条，不滥用""",
}


def _chat_generation_budget(context: str) -> dict[str, int | float]:
    normalized = (context or "chat").strip()
    if normalized == "chat":
        return {"timeout_seconds": 30, "max_retries": 2, "max_tokens_cap": 900, "history_messages": 6}
    if normalized == "outline_structuring":
        return {"timeout_seconds": 90, "max_retries": 2, "max_tokens_cap": 4096, "history_messages": 2}
    if normalized == "outline":
        return {"timeout_seconds": 75, "max_retries": 2, "max_tokens_cap": 1200, "history_messages": 4}
    return {"timeout_seconds": 90, "max_retries": 2, "max_tokens_cap": 1200, "history_messages": 6}


def _build_compiled_chat_packet_prompt(req: AIChatRequest) -> str | None:
    """验证并拼接前台编译包；返回 None 表示继续走旧接口兼容逻辑。"""
    context_key = (req.context or "chat").strip()
    packet = req.chat_context_packet
    if context_key != "chat" or not isinstance(packet, str) or not packet.strip():
        return None

    if not req.messages:
        raise HTTPException(status_code=422, detail="聊天上下文包要求最后一条消息为非空用户原话。")

    latest_message = req.messages[-1]
    if latest_message.role != "user":
        raise HTTPException(status_code=422, detail="聊天上下文包要求最后一条消息必须是用户原话。")
    if not latest_message.content.strip():
        raise HTTPException(status_code=422, detail="聊天上下文包的最后一条用户消息不能为空。")

    # packet 和本轮用户原话均保持客户端原文。后端只负责验证总预算，不重新裁剪，
    # 这样 trace 中“已纳入”的材料与实际送入模型的材料严格一致。
    prompt = f"{packet}{_CHAT_CONTEXT_PACKET_REQUEST_HEADER}{latest_message.content}"
    if len(prompt) > CHAT_CONTEXT_MAX_CHARS:
        raise HTTPException(
            status_code=422,
            detail="聊天上下文超过 18000 字符预算，请缩短或重新编译后发送。",
        )
    return prompt


async def generate_ai_chat_response(req: AIChatRequest) -> dict[str, str]:
    """
    统一的 AI 聊天生成逻辑。

    管理端和前台项目工作区共用这段生成逻辑，但鉴权入口分开：
    - /admin/config/ai/chat 仍只允许管理员
    - /user/ai/chat 允许已登录前台用户或管理员
    """
    from app.services.text_generation_service import generate_text, TextGenerationError, generation_enabled

    # 新版前台在调用模型前完成本轮上下文验证，确保 422 不受 AI 服务开关影响，
    # 且不向模型或响应正文暴露超限 packet 的原文。
    compiled_packet_prompt = _build_compiled_chat_packet_prompt(req)

    if not generation_enabled():
        raise HTTPException(
            status_code=503,
            detail="AI 生成服务未启用，请在系统设置中配置 AI 连接。"
        )

    latest_user_text = req.messages[-1].content if req.messages else ""

    # 构建系统提示词
    # context 规则永远保留（包含格式规范和禁令）
    context_key = (req.context or "chat").strip()
    context_rules = _CONTEXT_PROMPTS.get(context_key, _CONTEXT_PROMPTS["chat"])
    default_sp = "你是一个专业的短剧剧本创作助手，擅长爆款题材分析、故事结构设计和台词打磨。请用中文回复，保持专业且富有创意。"

    if context_key == "chat" and req.system_prompt and "短剧选题策划" in req.system_prompt:
        # 前台聊天已传入同一阶段边界，避免与后台 chat 规则重复拼接导致提示词变长。
        system = req.system_prompt
    elif req.system_prompt and req.system_prompt != default_sp:
        # 自定义 system_prompt（来自前端，含角色档案等）放前面，context 规则追加在后
        # 这样角色档案 + 格式规范都生效，互不覆盖
        system = req.system_prompt + "\n\n" + context_rules
    else:
        system = context_rules

    # 注入分类规则（受众轴 + 题材 + 制作形式）
    if context_key not in {"chat", "outline_structuring"}:
        category_rules = _build_category_rules(
            req.audience_axis or "",
            req.genre or "",
            req.format_type or "",
            include_dialogue=context_key not in {"chat", "outline_structuring"},
        )
        if category_rules:
            system = system + "\n\n" + category_rules

    # 新版前台传入的包已经由浏览器按完整消息边界编译；绝不能在此再按“最近
    # 6 条”裁剪。没有包的旧前端及管理端调用仍保留以下兼容路径。
    budget = _chat_generation_budget(context_key)
    if compiled_packet_prompt is not None:
        prompt = compiled_packet_prompt
    else:
        history_parts = []
        for msg in req.messages[:-1]:  # 除最后一条外的历史
            prefix = "用户" if msg.role == "user" else "助手"
            history_parts.append(f"{prefix}: {msg.content}")

        last_msg = latest_user_text
        prompt = last_msg
        if history_parts:
            history_limit = int(budget["history_messages"])
            history_text = "\n".join(history_parts[-history_limit:])
            prompt = f"对话历史：\n{history_text}\n\n用户：{last_msg}"

    try:
        result = await asyncio.to_thread(
            generate_text,
            system_prompt=system,
            user_prompt=prompt,
            temperature=0.72 if context_key == "chat" else 0.55,
            max_tokens=min(req.max_tokens, int(budget["max_tokens_cap"])),
            timeout_seconds=float(budget["timeout_seconds"]),
            max_retries=int(budget["max_retries"]),
        )
        return {"content": result, "role": "assistant"}
    except TextGenerationError as exc:
        raise exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"服务器错误: {exc}")


@router.post("/ai/chat", summary="AI创作聊天助手")
async def ai_chat(req: AIChatRequest, _: bool = Depends(verify_admin)):
    """
    管理端 AI 聊天接口，用于设置页/后台场景。

    前台项目工作区请走 /api/user/ai/chat，避免普通用户误打管理员专用接口。
    """
    return await generate_ai_chat_response(req)
