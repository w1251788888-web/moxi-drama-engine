# 部署指南

本文说明如何把墨戏生花部署到生产环境。

## 架构回顾

```
浏览器
  │
  ▼
后端 (FastAPI, :6565)  ─── 统一托管前端静态资源
  │
  ├── SQLite (本地文件)
  ├── 项目工作区 (本地目录)
  ├── 规则包 (02-creation-rules/)
  └── 大模型 API (外部)
```

单进程即可运行，无需额外中间件。前端构建后由后端统一托管，生产环境只需暴露一个端口。

## 前置要求

| 组件 | 版本 |
|------|------|
| Python | 3.11+ |
| Node.js | `^20.19.0` 或 `>=22.12.0`（仅构建前端时需要） |

## 一、准备代码与规则包

```bash
git clone <this-repo> moxi
cd moxi

# 接入你自己的规则包（本仓库自带的是示例包）
rm -rf 02-creation-rules
git submodule add <your-private-rules-repo> 02-creation-rules
git submodule update --init --recursive
```

## 二、后端

```bash
cd 01-system-core

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp config.yaml.example config.yaml
cp .env.example .env
```

编辑 `config.yaml`，至少配置：

- `ai.api_key` —— 模型 API 密钥
- `ai.base_url` / `ai.model` —— 使用的模型端点
- `admin.password` —— 管理端密码（**务必修改**，不要用默认值）
- `agent.registration_token` —— Agent 注册令牌（**务必修改**）

> ⚠️ `config.yaml` 与 `.env` 已在 `.gitignore` 中，**不要提交**。

## 三、前端构建

```bash
cd 01-system-core/webui
npm install
npm run build
```

构建产物输出到 `dist/`，由后端自动托管。

## 四、启动

```bash
cd 01-system-core
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 6565
```

访问 `http://<host>:6565` 即可。

首次访问会引导进入初始化流程（`/setup`），创建管理员账号。

### 用 systemd 常驻（Linux）

```ini
[Unit]
Description=Moxi Engine
After=network.target

[Service]
Type=simple
User=moxi
WorkingDirectory=/opt/moxi/01-system-core
Environment=PATH=/opt/moxi/01-system-core/.venv/bin
ExecStart=/opt/moxi/01-system-core/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 6565
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## 五、反代与 HTTPS（推荐）

生产环境务必置于反向代理之后并启用 HTTPS：

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    client_max_body_size 64m;   # 剧本/大纲导入需要

    location / {
        proxy_pass http://127.0.0.1:6565;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 长文本生成耗时较长，需放宽超时
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
```

## 六、更新部署

```bash
cd /opt/moxi
git pull
git submodule update --init --recursive   # 同步规则包

cd 01-system-core
source .venv/bin/activate
pip install -r requirements.txt

cd webui && npm install && npm run build && cd ..

sudo systemctl restart moxi
```

## 七、运维要点

### 备份

需要备份三样东西：

| 内容 | 位置 |
|------|------|
| 数据库 | `01-system-core/data/*.db` |
| 项目工作区 | `03-project-library/` |
| 规则包 | `02-creation-rules/`（若为 submodule，备份其源仓库） |

### 日志

后端日志默认输出到 stdout，由 systemd 或容器收集。

### 安全清单

上线前请逐项确认：

- [ ] `admin.password` 已改为强密码
- [ ] `agent.registration_token` 已改为随机值
- [ ] `config.yaml` / `.env` 未被提交到版本库
- [ ] 已启用 HTTPS 反代
- [ ] 数据库与工作区目录不在公网可访问路径下
- [ ] 已配置备份

## 八、常见问题

**Q：启动后控制台出现 `[PromptHealth] 缺失入口`**

规则包符号链接失效。检查 `01-system-core/prompts/` 下五个符号链接是否指向 `02-creation-rules/`。
详见 [规则包规范](./rules-pack.md)。

**Q：前端构建后访问是空白页**

确认 `npm run build` 产物在 `01-system-core/webui/dist/`，并重启后端。

**Q：生成长文本时请求超时**

放宽反向代理的 `proxy_read_timeout`（见上文 Nginx 配置）。

**Q：如何确认部署的是干净版本**

```bash
cd 01-system-core && pytest -q
```

测试全绿即为健康状态。
