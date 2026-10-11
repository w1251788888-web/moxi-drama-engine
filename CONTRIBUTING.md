# 贡献指南

感谢你愿意参与墨戏生花！本文说明如何提交改动。

## 前置约定

**请先阅读**：本项目是 [OpenMOSS](https://github.com/uluckyXH/OpenMOSS)（MIT）的衍生作品，
上游的版权与许可声明必须保留。提交时请勿移除或修改任何上游署名信息。

## 可以贡献什么

| 类型 | 说明 |
|------|------|
| 🐛 Bug 修复 | 后端、前端、工作流逻辑 |
| ✨ 引擎功能 | 与领域知识无关的通用能力 |
| 📝 文档 | 说明、示例、翻译 |
| 🧪 测试 | 提升覆盖率、补充边界用例 |
| 🌐 模型适配 | 新的模型供应商支持 |

## 什么**不要**提交

> ⚠️ 这几条是硬性要求，违反的 PR 会被直接关闭。

- ❌ **私有规则包内容** —— `02-creation-rules/` 中的示例规则可改进，但请勿提交任何生产级私有方法论
- ❌ **真实 API 密钥 / Token / 凭据** —— 一律使用占位符
- ❌ **本地绝对路径** —— 请使用相对路径或环境变量。测试会校验这一点
- ❌ **个人数据 / 客户数据 / 未脱敏的剧本内容**
- ❌ **未获授权的第三方代码** —— 引入依赖请先确认其许可证兼容 MIT

## 开发流程

### 1. 准备环境

```bash
git clone <this-repo>
cd <repo>/01-system-core

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.yaml.example config.yaml   # 填入你自己的 API Key（不要提交）
```

前端：

```bash
cd webui
npm install
```

### 2. 修改代码

- 保持改动聚焦，一个 PR 解决一个问题
- 遵循现有代码风格，不要顺手重构无关文件
- 新增行为请附带测试

### 3. 自测

```bash
# 后端测试
cd 01-system-core && pytest

# 前端类型检查与 lint
cd 01-system-core/webui
npm run type-check
npm run lint
```

**提交前必须全部通过。**

### 4. 提交

请使用语义化提交信息：

```
feat: 新增 xxx 能力
fix: 修复 xxx 问题
docs: 补充 xxx 说明
test: 补充 xxx 测试
chore: 调整 xxx 配置
```

### 5. 发起 Pull Request

PR 描述中请说明：

- **改了什么** —— 具体范围
- **为什么改** —— 解决的问题
- **怎么验证** —— 测试方式与结果

## 关于规则包

如果你希望为**示例规则包**做贡献：

- 可以改进表达、补充通用写作常识
- 请勿把特定商业方法论当作通用规则提交
- 新增规则文件请同步更新 `02-creation-rules/README.md` 的结构说明

## 代码风格

**Python**
- 遵循 PEP 8
- 使用类型标注
- 公共函数写 docstring

**TypeScript / Vue**
- 遵循项目 ESLint 配置
- Vue 3 Composition API + `<script setup>`
- 组件名使用 PascalCase

## 需要帮助

不确定某个改动是否合适？先开一个 Issue 讨论，避免白做工。

---

再次感谢你的参与 🙏
