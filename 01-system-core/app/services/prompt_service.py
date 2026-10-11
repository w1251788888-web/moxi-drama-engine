"""
提示词管理业务逻辑 — 文件扫描、frontmatter 解析、Prompt 组合
"""
import re
from pathlib import Path
from datetime import date
from typing import Optional

import frontmatter

from app.config import config

# ── 目录常量 ────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[2]  # app/services → app → 项目根目录
TEMPLATES_DIR = BASE_DIR / "prompts" / "templates"
AGENTS_DIR = BASE_DIR / "prompts" / "agents"

# ── 合法角色列表 ────────────────────────────────────────
VALID_ROLES = {"planner", "executor", "reviewer", "patrol"}

# ── 系统垃圾文件过滤 ───────────────────────────────────
IGNORED_FILES = {".DS_Store", "Thumbs.db", "desktop.ini", ".gitkeep"}

# ── 文件名校验（只允许小写英文、数字、短横线） ──────────
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


# ======================================================================
#  工具函数
# ======================================================================

def _is_valid_md(path: Path) -> bool:
    """判断是否为合法的 .md 文件（排除垃圾文件和非 .md）"""
    return (
        path.is_file()
        and path.suffix == ".md"
        and path.name not in IGNORED_FILES
    )


def _parse_prompt_file(path: Path) -> dict:
    """解析单个提示词文件，返回元数据 + 内容"""
    post = frontmatter.load(str(path))
    slug = path.stem  # 文件名去掉 .md

    # 从 frontmatter 取元数据，缺失则标记
    meta = {
        "slug": slug,
        "filename": path.name,
        "name": post.get("name", ""),
        "role": post.get("role", ""),
        "description": post.get("description", ""),
        "created_at": str(post.get("created_at", "")),
        "example": bool(post.get("example", False)),
        "content": post.content,
        "has_frontmatter": bool(post.metadata),
    }

    # 诊断状态
    if not post.metadata:
        meta["status"] = "unconfigured"  # 无 frontmatter
    elif meta["role"] and not slug.startswith(meta["role"] + "-"):
        meta["status"] = "rename_suggested"  # 命名不规范
    else:
        meta["status"] = "ok"

    return meta


def _validate_slug(slug: str) -> Optional[str]:
    """校验 slug 合法性，返回错误信息或 None"""
    if not slug:
        return "slug 不能为空"
    if not SLUG_PATTERN.match(slug):
        return "slug 只允许小写英文、数字和短横线，且不能以短横线开头"
    return None


# ======================================================================
#  模板 CRUD
# ======================================================================

def list_templates() -> list[dict]:
    """列出所有角色模板"""
    if not TEMPLATES_DIR.exists():
        return []

    result = []
    for path in sorted(TEMPLATES_DIR.iterdir()):
        if not _is_valid_md(path):
            continue
        # 从文件名提取角色：task-executor.md → executor, planner.md → planner
        role = path.stem
        if role.startswith("task-"):
            role = role[5:]
        content = path.read_text(encoding="utf-8")
        result.append({
            "role": role,
            "filename": path.name,
            "content": content,
        })
    return result


def get_template(role: str) -> Optional[dict]:
    """获取指定角色模板（支持 {role}.md 和 task-{role}.md 两种命名）"""
    # 优先查找 {role}.md
    path = TEMPLATES_DIR / f"{role}.md"
    if not path.exists():
        # 兼容 task-{role}.md 命名
        path = TEMPLATES_DIR / f"task-{role}.md"
    if not path.exists():
        return None
    return {
        "role": role,
        "filename": path.name,
        "content": path.read_text(encoding="utf-8"),
    }


def update_template(role: str, content: str) -> dict:
    """更新角色模板内容"""
    if role not in VALID_ROLES:
        raise ValueError(f"无效角色 '{role}'，可选: {', '.join(VALID_ROLES)}")

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMPLATES_DIR / f"{role}.md"
    path.write_text(content, encoding="utf-8")
    return {"role": role, "filename": path.name}


# ======================================================================
#  Agent 提示词 CRUD
# ======================================================================

def list_agents() -> list[dict]:
    """列出所有 Agent 提示词（扫描 prompts/agents/ 目录）"""
    if not AGENTS_DIR.exists():
        return []

    result = []
    for path in sorted(AGENTS_DIR.iterdir()):
        if not _is_valid_md(path):
            continue
        try:
            meta = _parse_prompt_file(path)
            # 列表不返回完整内容，节省带宽
            meta.pop("content", None)
            result.append(meta)
        except Exception:
            # 解析失败的文件跳过
            continue
    return result


def get_agent(slug: str) -> Optional[dict]:
    """获取 Agent 提示词详情"""
    path = AGENTS_DIR / f"{slug}.md"
    if not path.exists():
        return None
    return _parse_prompt_file(path)


def create_agent(
    slug: str,
    name: str,
    role: str,
    description: str,
    content: str,
) -> dict:
    """新建 Agent 提示词"""
    # 校验 role
    if role not in VALID_ROLES:
        raise ValueError(f"无效角色 '{role}'，可选: {', '.join(VALID_ROLES)}")

    # 拼接完整 slug: {role}-{slug}
    full_slug = f"{role}-{slug}" if not slug.startswith(role + "-") else slug

    # 校验 slug
    err = _validate_slug(full_slug)
    if err:
        raise ValueError(err)

    # 检查唯一性
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = AGENTS_DIR / f"{full_slug}.md"
    if path.exists():
        raise ValueError(f"文件 '{full_slug}.md' 已存在，请更换名称")

    # 组装 frontmatter + 内容
    post = frontmatter.Post(content)
    post["name"] = name
    post["role"] = role
    post["description"] = description
    post["created_at"] = str(date.today())

    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return {"slug": full_slug, "filename": path.name}


def update_agent(
    slug: str,
    name: Optional[str] = None,
    role: Optional[str] = None,
    description: Optional[str] = None,
    content: Optional[str] = None,
) -> dict:
    """编辑 Agent 提示词（支持重命名）"""
    path = AGENTS_DIR / f"{slug}.md"
    if not path.exists():
        raise ValueError(f"文件 '{slug}.md' 不存在")

    post = frontmatter.load(str(path))

    # 更新字段
    if name is not None:
        post["name"] = name
    if role is not None:
        if role not in VALID_ROLES:
            raise ValueError(f"无效角色 '{role}'，可选: {', '.join(VALID_ROLES)}")
        post["role"] = role
    if description is not None:
        post["description"] = description
    if content is not None:
        post.content = content

    # 确保 created_at 存在
    if "created_at" not in post.metadata:
        post["created_at"] = str(date.today())

    new_role = post.get("role", "")
    new_slug = slug

    # 如果 role 变了或文件名不规范，自动重命名
    if new_role and not slug.startswith(new_role + "-"):
        # 去掉旧的 role 前缀（如果有）
        base_name = slug
        for r in VALID_ROLES:
            if slug.startswith(r + "-"):
                base_name = slug[len(r) + 1:]
                break
        new_slug = f"{new_role}-{base_name}"

        new_path = AGENTS_DIR / f"{new_slug}.md"
        if new_path.exists() and new_path != path:
            raise ValueError(f"重命名目标 '{new_slug}.md' 已存在")

        # 写入新文件，删除旧文件
        new_path.write_text(frontmatter.dumps(post), encoding="utf-8")
        if new_path != path:
            path.unlink()
    else:
        path.write_text(frontmatter.dumps(post), encoding="utf-8")

    return {"slug": new_slug, "filename": f"{new_slug}.md"}


def delete_agent(slug: str) -> bool:
    """删除 Agent 提示词"""
    path = AGENTS_DIR / f"{slug}.md"
    if not path.exists():
        raise ValueError(f"文件 '{slug}.md' 不存在")
    path.unlink()
    return True


# ======================================================================
#  Prompt 组合（一键复制用）
# ======================================================================

def compose_prompt(slug: str) -> str:
    """
    生成完整 Prompt。
    Agent 文件内容已包含角色模板（创建时已合并），
    因此只需追加对接指引即可。
    """
    agent_data = get_agent(slug)
    if not agent_data:
        raise ValueError(f"Agent 提示词 '{slug}' 不存在")

    role = agent_data.get("role", "")
    agent_content = agent_data.get("content", "")

    # 内容已包含对接指引，直接返回
    if ONBOARDING_MARKER in agent_content:
        return agent_content.strip()

    # 拼接 Agent 内容 + 对接指引（不再重复拼接模板）
    parts = []
    if agent_content:
        parts.append(agent_content.strip())
    parts.append(generate_onboarding(role))

    return "\n\n---\n\n".join(parts)


ONBOARDING_MARKER = "## 🔧 平台对接"


def generate_onboarding(role: str = "") -> str:
    """生成平台对接指引文本（变量从 config 自动填充）"""
    external_url = config.server_external_url
    registration_token = config.registration_token
    bs = "\\"  # single backslash

    lines = [
        "## 🔧 平台对接（仅用于首次注册，完成后请删除本段）",
        "",
        "> ⚠️ **重要提示**：以下内容仅用于首次注册，注册完成后务必从系统提示词中移除本段。",
        "> 请勿将本段写入 AGENTS.md、SOUL.md 或任何长期使用的系统提示词中。",
        "",
        "### 第一步：注册到任务系统（如已注册可跳过）",
        "",
        "```bash",
        f"curl -X POST {external_url}/api/agents/register {bs}",
        f'  -H "Content-Type: application/json" {bs}',
        f'  -H "X-Registration-Token: {registration_token}" {bs}',
        f"""  -d '{{"name": "你的名字", "role": "{role}", "description": "简要描述你的职责"}}'""",
        "```",
        "",
        "> **字段说明**：",
        "> - `name`：你的名字（如 AI小吴）",
        "> - `role`：角色类型（planner / executor / reviewer / patrol）",
        "> - `description`：简要描述你的职责（如「后端开发，负责 API 和数据库」）",
        "",
        "→ 返回你的 API Key，后续所有操作需要携带",
        "",
        "> ⚠️ **API Key 只在注册时显示一次，请务必立即记录。** 如果遗失，需要联系管理员重置。",
        "",
        "### 第二步：获取工作工具并保存为 Skill",
        "",
        "```bash",
        "# 下载 CLI 工具",
        f"curl -o task-cli.py {bs}",
        f'  -H "Authorization: Bearer 你的API_KEY" {bs}',
        f"  {external_url}/api/tools/cli",
        "",
        "# 获取技能提示词（Skill 说明，API Key 已自动填入）",
        f'curl -H "Authorization: Bearer 你的API_KEY" {bs}',
        f"  {external_url}/api/agents/me/skill",
        "```",
        "",
        "**请将以上内容保存为 Skill 目录**：",
        f"- 创建目录 `task-{role}-skill/`",
        f"- 将 CLI 工具保存为 `task-{role}-skill/task-cli.py`",
        f"- 将技能提示词保存为 `task-{role}-skill/SKILL.md`",
        "- Skill 是你的工作工具箱，后续按 SKILL.md 中的指引操作即可",
        "",
        "### 第三步：确认 API Key 已保存",
        "",
        "打开 SKILL.md，确认 `## 认证信息` 部分已包含你的 API Key：",
        "",
        "```markdown",
        "## 认证信息",
        "",
        "- API_KEY: `ock_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`",
        "```",
        "",
        "如果 API Key 未自动填入，请手动将注册时获得的 Key 填写到上述位置。",
        "",
        "### 第四步：开始工作",
        "",
        "```bash",
        "python task-cli.py rules    # 查看工作规则",
        "python task-cli.py next     # 领取任务",
        "python task-cli.py submit   # 提交成果",
        "```",
        "",
        "### 连接信息",
        f"- 服务地址: {external_url}",
        f"- 注册令牌: {registration_token}",
    ]
    return "\n".join(lines)
