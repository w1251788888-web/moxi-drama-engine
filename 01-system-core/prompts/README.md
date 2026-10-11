# Prompts 兼容入口说明

本目录不是独立规则仓，而是运行时兼容入口。

当前目录下的：

- `agents`
- `knowledge`
- `rules`
- `steps`
- `templates`

均应保持为符号链接，并指向：

- `02-creation-rules/agent-definitions`
- `02-creation-rules/knowledge-base`
- `02-creation-rules/core-rules`
- `02-creation-rules/step-definitions`
- `02-creation-rules/templates`

维护原则：

- 请把 `02-creation-rules/` 视为规则唯一真源。
- 本目录只负责保持系统代码路径稳定，不应单独维护另一套规则正文。
