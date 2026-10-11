# 01-system-core · 系统核心

墨戏生花的后端与前端主体。

> **来源说明**：本模块的多 Agent 协作内核（任务模型、Agent 调度、后台管理）
> 源自开源项目 **[OpenMOSS](https://github.com/uluckyXH/OpenMOSS)**（MIT License，
> 作者：小黄、动动枪），并在此基础上扩展了短剧剧本创作的领域逻辑与界面。
> 上游的版权与许可声明完整保留于仓库根目录的 [LICENSE](../LICENSE)。

## 结构

```
01-system-core/
├── app/            FastAPI 后端
│   ├── routers/      API 路由
│   ├── services/     业务服务
│   ├── models/       数据模型
│   └── main.py       应用入口
├── webui/          Vue 3 前端
│   └── src/views/    页面视图
├── prompts/        规则兼容入口（符号链接 → 02-creation-rules）
├── tests/          测试
├── requirements.txt
├── config.yaml.example
└── .env.example
```

## 启动

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml   # 填入你的 API Key
uvicorn app.main:app --reload --port 6565
```

前端：

```bash
cd webui && npm install && npm run dev
```

完整说明见仓库根目录 [README.md](../README.md)。
