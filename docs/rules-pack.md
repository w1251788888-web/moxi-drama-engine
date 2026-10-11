# 规则包规范

本文说明墨戏生花的**规则包（Rule Pack）**机制 —— 引擎与领域知识如何解耦。

## 设计动机

短剧创作的核心竞争力在于**方法论**：怎样的开场抓人、钩子如何埋设、爽点怎么排布、
不同受众偏好的节奏差异。这些属于**领域知识资产**，而非通用工程代码。

把它们与引擎耦合会导致：

- 引擎无法复用于其他题材 / 语种
- 方法论更新必须改动代码并重新发布
- 无法按项目、题材、受众差异化配置

因此引擎只负责**编排**，所有领域知识外置为规则包。

## 目录契约

引擎期望在仓库根目录存在 `02-creation-rules/`，结构如下：

```
02-creation-rules/
├── core-rules/           # 写作规则
├── step-definitions/     # 创作步骤定义
├── agent-definitions/    # Agent 角色提示词
├── knowledge-base/       # 可检索领域知识
├── templates/            # 提示词与任务模板
├── pipeline.toml         # 流水线配置（可选）
└── system.md             # 系统级总纲（可选）
```

## 引擎如何找到规则

引擎**不直接**引用 `02-creation-rules/`，而是通过一个「兼容入口」：

```
01-system-core/prompts/
├── agents     -> ../../02-creation-rules/agent-definitions
├── knowledge  -> ../../02-creation-rules/knowledge-base
├── rules      -> ../../02-creation-rules/core-rules
├── steps      -> ../../02-creation-rules/step-definitions
└── templates  -> ../../02-creation-rules/templates
```

这五个条目**必须是符号链接**。引擎代码中的路径解析为：

```python
# app/services/short_drama_rule_resolver.py
def prompts_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "prompts"
```

即 **相对于代码位置**解析，而非硬编码绝对路径 —— 因此仓库可以放在任意目录。

> 引擎启动时会执行 `_check_prompt_symlink_health()` 自检，若符号链接缺失或指向错误，
> 会在控制台打印 `[PromptHealth]` 警告（**不阻断启动**，便于排查）。

## 各目录职责

### `core-rules/`

写作规则正文。典型文件：

| 文件 | 作用 |
|------|------|
| `drama-format.md` | 剧本格式规范 |
| `rhythm-control.md` | 节奏控制 |
| `conflict-design.md` | 冲突设计方法 |
| `hook-patterns.md` | 钩子类型库 |
| `content-compliance.md` | 内容合规红线 |
| `<受众>_core.md` / `<受众>_style.md` | 按受众/题材分支的规则 |

### `step-definitions/`

每个创作步骤的输入输出契约。引擎按步骤名加载，用于构造该步骤的提示词上下文。

### `agent-definitions/`

Agent 角色提示词，例如 `executor-script-draft.md`。
部分文件使用 YAML frontmatter 声明角色与任务：

```markdown
---
role: executor
task: script_draft
---

你是短剧剧本写手。
...
```

### `knowledge-base/`

可被检索（RAG）注入的领域知识。引擎会将其切分为知识块建立索引。

### `templates/`

任务模板与提示词骨架，使用 `{{variable}}` 占位符。

## 接入自己的规则包

### 方式一：直接替换目录

```bash
rm -rf 02-creation-rules
git clone <your-private-rules-repo> 02-creation-rules
```

### 方式二：Git Submodule（推荐用于私有规则）

```bash
rm -rf 02-creation-rules
git submodule add <your-private-rules-repo> 02-creation-rules
git commit -m "chore: 接入私有规则包"
```

子模块的好处：私有规则可独立版本管理，引擎仓库保持干净，且不会误提交。

### 方式三：部署时挂载

在生产环境用容器卷或符号链接把规则包挂到 `02-creation-rules/`，
适合规则需要频繁热更新、或规则由非研发人员维护的场景。

## 校验你的规则包

替换后建议做三项检查：

1. **符号链接有效**

   ```bash
   cd 01-system-core
   for l in agents knowledge rules steps templates; do
     [ -e "prompts/$l" ] && echo "OK $l" || echo "断链 $l"
   done
   ```

2. **无 PromptHealth 警告**
   启动后端，观察控制台是否输出 `[PromptHealth]`。

3. **跑通相关测试**

   ```bash
   pytest tests/ -q
   ```

## 注意事项

- ⚠️ **规则包可能包含你的核心方法论，请放在私有仓库。** 本仓库的 `02-creation-rules/` 仅为示例。
- 规则包中的路径引用请使用相对路径，避免因仓库位置变化而失效。
- 若规则包较大，注意 `knowledge-base/` 的切分与索引开销。
