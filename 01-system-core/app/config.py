"""
墨戏生花 短剧剧本智能创作系统 — 配置加载模块
"""
import os
import bcrypt
import yaml
import threading
from pathlib import Path
from typing import Optional


MOXI_CONFIG_PATH_ENV = "MOXI_CONFIG_PATH"


class AppConfig:
    """应用配置"""

    def __init__(self, config_path: str | None = None):
        self.base_dir = Path(__file__).resolve().parents[1]
        env_config_path = os.getenv(MOXI_CONFIG_PATH_ENV, "").strip()
        self._uses_external_config_path = False
        if config_path is None:
            if env_config_path:
                config_path = env_config_path
                self._uses_external_config_path = True
            else:
                config_path = "config.yaml"
        raw_path = Path(config_path)
        self.config_path = raw_path if raw_path.is_absolute() else self.base_dir / raw_path
        self._data = {}
        self._lock = threading.RLock()  # 可重入锁，防止内部方法嵌套调用时死锁
        self.load()

    def load(self):
        """加载配置文件"""
        if not self.config_path.exists():
            if self._uses_external_config_path:
                raise FileNotFoundError(
                    f"外部配置文件 {self.config_path} 不存在，请检查 {MOXI_CONFIG_PATH_ENV}"
                )
            # 如果没有 config.yaml，从模板复制
            example_path = self.base_dir / "config.example.yaml"
            if example_path.exists():
                import shutil
                shutil.copy(example_path, self.config_path)
                print(f"[Config] 已从 {example_path} 创建配置文件 {self.config_path}")
            else:
                raise FileNotFoundError(
                    f"配置文件 {self.config_path} 不存在，请从 config.example.yaml 复制"
                )

        with open(self.config_path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}

        # 启动时自动加密管理员密码
        self._auto_encrypt_password()

    @staticmethod
    def _as_string_list(value) -> list[str]:
        """将 YAML 列表或逗号分隔环境变量规整为字符串列表。"""
        if isinstance(value, str):
            items = value.split(",")
        elif isinstance(value, (list, tuple, set)):
            items = value
        else:
            return []

        result: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = str(item).strip().rstrip("/")
            if not text or text == "*" or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @staticmethod
    def _security_cors(data: dict) -> dict:
        security = data.get("security", {})
        if not isinstance(security, dict):
            return {}
        cors = security.get("cors", {})
        return cors if isinstance(cors, dict) else {}

    def _auto_encrypt_password(self):
        """如果密码是明文或旧的 MD5 格式，自动升级为 bcrypt 并回写配置文件"""
        admin = self._data.get("admin", {})
        password = str(admin.get("password", ""))

        if not password:
            return

        if password.startswith("bcrypt:"):
            # 已经是 bcrypt 格式，无需处理
            return

        if password.startswith("md5:"):
            # 旧的 MD5 格式，无法反向解密，需要用户重新设置密码
            # 使用默认密码 admin123 重新加密
            print(f"[Config] ⚠️ 检测到旧的 MD5 密码格式，自动升级为 bcrypt（使用默认密码 admin123）")
            print(f"[Config] ⚠️ 请登录后立即修改管理员密码！")
            raw_password = "admin123"
        else:
            # 明文密码
            raw_password = password

        # 用 bcrypt 加密
        hashed = bcrypt.hashpw(raw_password.encode(), bcrypt.gensalt()).decode()
        admin["password"] = f"bcrypt:{hashed}"
        self._data["admin"] = admin

        # 回写配置文件
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self._data, f, allow_unicode=True, default_flow_style=False)

        print(f"[Config] 管理员密码已加密为 bcrypt")

    def _save(self):
        """将当前配置数据回写到 YAML 文件"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self._data, f, allow_unicode=True, default_flow_style=False)

    def verify_admin_password(self, password: str) -> bool:
        """验证管理员密码"""
        stored = self._data.get("admin", {}).get("password", "")

        if stored.startswith("bcrypt:"):
            bcrypt_hash = stored[7:]  # 去掉 "bcrypt:" 前缀
            return bcrypt.checkpw(password.encode(), bcrypt_hash.encode())

        # 兜底：不应出现，但防御性处理
        return False

    @property
    def is_initialized(self) -> bool:
        """是否已完成初始化向导"""
        return self._data.get("setup", {}).get("initialized", False)

    def mark_initialized(self):
        """标记初始化完成（使用 RLock，可安全嵌套调用）"""
        with self._lock:
            if "setup" not in self._data:
                self._data["setup"] = {}
            self._data["setup"]["initialized"] = True
            self._save()

    def update(self, data: dict):
        """部分更新配置（合并更新 + 回写 YAML）

        支持的顶级 key：project, agent, notification, webui, workspace, server, market_insights, text_generation
        server 下仅允许更新 external_url（port/host 需手动改 config.yaml 后重启）
        不支持更新：setup, admin.password, database
        """
        ALLOWED_KEYS = {"project", "agent", "notification", "webui", "workspace", "server", "market_insights", "text_generation", "ai"}
        SERVER_ALLOWED_SUBKEYS = {"external_url"}

        with self._lock:
            for key, value in data.items():
                if key not in ALLOWED_KEYS:
                    raise ValueError(f"不允许更新配置项: {key}")
                # server 下做子字段白名单校验
                if key == "server" and isinstance(value, dict):
                    for sub_key in value:
                        if sub_key not in SERVER_ALLOWED_SUBKEYS:
                            raise ValueError(f"不允许通过 API 更新 server.{sub_key}，请手动修改 config.yaml")
                if isinstance(value, dict) and isinstance(self._data.get(key), dict):
                    self._data[key].update(value)
                else:
                    self._data[key] = value

            self._save()

    def update_password(self, old_password: str, new_password: str):
        """修改管理员密码（需验证旧密码）"""
        with self._lock:
            if not self.verify_admin_password(old_password):
                raise ValueError("旧密码验证失败")

            hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
            if "admin" not in self._data:
                self._data["admin"] = {}
            self._data["admin"]["password"] = f"bcrypt:{hashed}"
            self._save()

    def set_password(self, new_password: str):
        """直接设置新密码（跳过旧密码验证，用于初始化向导，调用方需持有锁）"""
        hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        if "admin" not in self._data:
            self._data["admin"] = {}
        self._data["admin"]["password"] = f"bcrypt:{hashed}"
        self._save()

    def get_safe_config(self) -> dict:
        """获取脱敏后的配置（密码/令牌等替换为 ***）"""
        import copy
        safe = copy.deepcopy(self._data)

        # 脱敏
        if "admin" in safe:
            safe["admin"]["password"] = "***"
        if "agent" in safe:
            safe["agent"]["registration_token"] = safe["agent"].get("registration_token", "")

        # 排除内部标记
        safe.pop("setup", None)

        return safe

    @property
    def server_port(self) -> int:
        return self._data.get("server", {}).get("port", 6565)

    @property
    def project_name(self) -> str:
        return self._data.get("project", {}).get("name", "OpenMOSS")

    @property
    def server_host(self) -> str:
        return self._data.get("server", {}).get("host", "0.0.0.0")

    @property
    def server_external_url(self) -> str:
        """外网访问地址（用于 Agent 工具下载和对接）

        如果未配置，兜底用 host:port 拼接（通常不可从外网访问）。
        旧版部署无此字段时自动兜底，不会报错。
        """
        url = self._data.get("server", {}).get("external_url", "")
        if not url:
            host = self.server_host
            if host == "0.0.0.0":
                host = "127.0.0.1"  # 0.0.0.0 不是有效访问地址，兜底用 localhost
            return f"http://{host}:{self.server_port}"
        return url.rstrip("/")

    @property
    def has_external_url(self) -> bool:
        """外网地址是否已配置（非空）"""
        return bool(self._data.get("server", {}).get("external_url", ""))

    @property
    def cors_allowed_origins(self) -> list[str]:
        """CORS 允许来源白名单。

        优先级：环境变量 MOXI_CORS_ALLOWED_ORIGINS > security.cors.allowed_origins
        > server.cors_allowed_origins > 本地开发默认值。禁止以 "*" 作为默认开放来源。
        """
        env_origins = self._as_string_list(os.getenv("MOXI_CORS_ALLOWED_ORIGINS", ""))
        if env_origins:
            return env_origins

        cors = self._security_cors(self._data)
        server = self._data.get("server", {})
        configured = self._as_string_list(
            cors.get("allowed_origins") or server.get("cors_allowed_origins")
        )

        defaults = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:6565",
            "http://127.0.0.1:6565",
        ]
        origins = configured or defaults
        if self.has_external_url:
            origins = [*origins, self.server_external_url]
        return self._as_string_list(origins)

    @property
    def cors_allow_origin_regex(self) -> str:
        """CORS 本地开发端口正则，生产环境可通过配置置空或收紧。"""
        env_regex = os.getenv("MOXI_CORS_ALLOW_ORIGIN_REGEX", "").strip()
        if env_regex:
            return env_regex

        cors = self._security_cors(self._data)
        regex = str(cors.get("allow_origin_regex", "")).strip()
        if regex:
            return regex
        return r"^https?://(localhost|127\.0\.0\.1|\[::1\]):\d+$"

    @property
    def database_path(self) -> str:
        return self._data.get("database", {}).get("path", "./data/tasks.db")

    @property
    def database_type(self) -> str:
        return self._data.get("database", {}).get("type", "sqlite")

    @property
    def registration_token(self) -> str:
        return self._data.get("agent", {}).get("registration_token", "")

    @staticmethod
    def redact_secret(value: str, visible: int = 4) -> str:
        """用于日志展示的敏感值脱敏，不改变真实配置。"""
        text = str(value or "").strip()
        if not text:
            return "(未配置)"
        if len(text) <= visible * 2:
            return "***"
        return f"{text[:visible]}...{text[-visible:]}"

    @property
    def redacted_registration_token(self) -> str:
        return self.redact_secret(self.registration_token)

    @property
    def allow_registration(self) -> bool:
        """Agent 自注册开关，默认开启"""
        return self._data.get("agent", {}).get("allow_registration", True)

    @property
    def workspace_root(self) -> str:
        return self._data.get("workspace", {}).get("root", "./workspace")

    @property
    def market_insights(self) -> dict:
        return self._data.get("market_insights", {})

    @property
    def text_generation(self) -> dict:
        return self._data.get("text_generation", {})

    @property
    def notification_config(self) -> dict:
        return self._data.get("notification", {})

    @property
    def public_feed_enabled(self) -> bool:
        """活动流展示页是否公开"""
        return self._data.get("webui", {}).get("public_feed", False)

    @property
    def feed_retention_days(self) -> int:
        """请求日志保留天数"""
        return self._data.get("webui", {}).get("feed_retention_days", 7)

    @property
    def cli_version(self) -> int:
        """CLI 工具最新版本号（直接从 task-cli.py 文件读取 CLI_VERSION）"""
        import re
        cli_path = Path(__file__).resolve().parent.parent / "skills" / "task-cli.py"
        try:
            content = cli_path.read_text(encoding="utf-8")
            match = re.search(r"^CLI_VERSION\s*=\s*(\d+)", content, re.MULTILINE)
            if match:
                return int(match.group(1))
        except Exception:
            pass
        return 1

    @property
    def raw(self) -> dict:
        """获取原始配置数据"""
        return self._data

    def initialize(self, data: dict):
        """初始化向导：原子性地检查 + 写入配置项

        在锁内检查 is_initialized，确保不会并发重复初始化。
        如果已初始化，返回 False；成功初始化返回 True。
        """
        with self._lock:
            # 原子性检查（防止并发竞态）
            if self.is_initialized:
                return False

            # 设置密码
            password = data.get("admin_password")
            if password:
                self.set_password(password)

            # 设置项目名
            if data.get("project_name"):
                if "project" not in self._data:
                    self._data["project"] = {}
                self._data["project"]["name"] = data["project_name"]

            # 设置工作目录
            if data.get("workspace_root"):
                if "workspace" not in self._data:
                    self._data["workspace"] = {}
                self._data["workspace"]["root"] = data["workspace_root"]

            # 设置注册令牌
            if "agent" not in self._data:
                self._data["agent"] = {}
            if data.get("registration_token"):
                self._data["agent"]["registration_token"] = data["registration_token"]
            else:
                # 自动生成随机令牌
                import secrets
                self._data["agent"]["registration_token"] = secrets.token_hex(16)

            if "allow_registration" in data:
                self._data["agent"]["allow_registration"] = data["allow_registration"]

            # 设置通知
            if data.get("notification"):
                self._data["notification"] = data["notification"]

            # 设置服务外网地址
            if data.get("external_url"):
                if "server" not in self._data:
                    self._data["server"] = {}
                self._data["server"]["external_url"] = data["external_url"]

            # 标记初始化完成
            self.mark_initialized()
            return True


# 全局配置实例
config = AppConfig()


# 全局配置访问函数（供API使用）
def get_config() -> dict:
    """获取完整配置数据"""
    return config.raw


def save_config(data: dict):
    """保存完整配置数据"""
    config._data = data
    config._save()
