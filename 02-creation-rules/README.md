# 02-creation-rules · 规则包（示例）

> ⚠️ **这是示例规则包，不是生产级方法论。**
> 它只用于让引擎开箱可跑、并演示规则包的目录契约。
> 真实项目中，请用一个**私有规则包**替换整个目录。

## 这是如何工作的

引擎通过 `01-system-core/prompts/` 下的符号链接读取本目录：

```
01-system-core/prompts/rules     -> ../../02-creation-rules/core-rules
01-system-core/prompts/steps     -> ../../02-creation-rules/step-definitions
01-system-core/prompts/agents    -> ../../02-creation-rules/agent-definitions
01-system-core/prompts/knowledge -> ../../02-creation-rules/knowledge-base
01-system-core/prompts/templates -> ../../02-creation-rules/templates
```

替换规则包时**无需改动任何引擎代码**。

## 替换方式

```bash
rm -rf 02-creation-rules
git submodule add <your-private-rules-repo> 02-creation-rules
```

只要保持下列目录结构，引擎即可正常加载：

| 目录 | 作用 |
|------|------|
| `core-rules/` | 写作规则：格式、节奏、冲突、钩子、合规 |
| `step-definitions/` | 各创作步骤的输入输出契约 |
| `agent-definitions/` | 各 Agent 的角色提示词 |
| `knowledge-base/` | 可检索的领域知识 |
| `templates/` | 提示词与任务模板 |
