# 启动说明

## 快捷方式

| 文件 | 用途 | 访问地址 |
|------|------|----------|
| `start.command` | **生产模式** — 自动构建前端后启动 | http://127.0.0.1:6565 |
| `start-background.command` | **后台管理台** — 自动构建前端后打开后台 | http://127.0.0.1:6565/moxi-admin |
| `dev-mode.command` | **开发模式** — 前后端热重载，推荐改代码时使用 | http://localhost:5173 |
| `moxi-rag.command` | **Dify/DeFi RAG** — 启动或停止本机知识库服务 | http://localhost |
| `stop.command` | 停止所有服务 | — |

## 使用场景

### 日常体验 / 演示
双击 `start.command`，等待 ~5 秒，浏览器自动打开。

每次双击都会重新构建前端（约 2 秒），保证运行的是最新代码。

### 开发调试（改前端/后端代码）
双击 `dev-mode.command`：
- **后端** 启用 `--reload`，修改 Python 文件后自动重启
- **前端** 启用 Vite HMR，修改 Vue/TS 文件后浏览器即时刷新
- 登录 token 持久化到 SQLite，后端重启后 **无需重新登录**
- 浏览器访问 **http://localhost:5173**（不是 6565）

### 启动 Dify/DeFi RAG

双击 `moxi-rag.command`：
- 第一次会启动 Colima、Ollama、Dify Docker 容器和热榜采集源。
- 再次双击会停止 Dify 容器，保留 Colima 以便下次更快启动。
- Dify 运行目录在 `02-creation-rules/dify-rag-runtime/`，脚本会自动按项目路径定位，不再依赖桌面 `rag` 目录。

## 注意事项

- 改了前端代码，必须重新构建（`npm run build`）才能在 6565 端口生效
- 开发模式下使用 5173 端口，API 通过 Vite 代理自动转发到 6565
- 两个端口同时开着没有冲突

## 手动启动

```bash
# 仅启动后端
cd 01-system-core
source .venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 6565 --reload

# 仅启动前端开发服务器
cd 01-system-core/webui
npm run dev

# 仅构建前端
cd 01-system-core/webui
npm run build
```
