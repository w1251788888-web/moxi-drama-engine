"""
OpenMOSS 任务调度中间件 — 数据库初始化
"""
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import config

# 确保数据目录存在
import os
db_dir = os.path.dirname(config.database_path)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("MOXI_SQLITE_BUSY_TIMEOUT_MS", "5000"))
SQLITE_CACHE_KB = int(os.getenv("MOXI_SQLITE_CACHE_KB", "20000"))

SQLITE_PERFORMANCE_INDEXES = {
    "task": [
        "CREATE INDEX IF NOT EXISTS ix_task_status_created ON task(status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_task_status_updated ON task(status, updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_task_type_created ON task(type, created_at)",
    ],
    "module": [
        "CREATE INDEX IF NOT EXISTS ix_module_task_created ON module(task_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_module_task_name ON module(task_id, name)",
    ],
    "sub_task": [
        "CREATE INDEX IF NOT EXISTS ix_sub_task_agent_status ON sub_task(assigned_agent, status)",
        "CREATE INDEX IF NOT EXISTS ix_sub_task_task_created ON sub_task(task_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_sub_task_task_status_created ON sub_task(task_id, status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_sub_task_module_created ON sub_task(module_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_sub_task_module_status_created ON sub_task(module_id, status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_sub_task_agent_status_created ON sub_task(assigned_agent, status, created_at)",
    ],
    "activity_log": [
        "CREATE INDEX IF NOT EXISTS ix_activity_log_created ON activity_log(created_at)",
        "CREATE INDEX IF NOT EXISTS ix_activity_log_action_created ON activity_log(action, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_activity_log_agent_created ON activity_log(agent_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_activity_log_sub_task_created ON activity_log(sub_task_id, created_at)",
    ],
}


def _quote_sqlite_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'

# SQLAlchemy 引擎
DATABASE_URL = f"sqlite:///{config.database_path}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite 需要
    echo=False,
)


def configure_sqlite_connection(dbapi_connection, *, enable_wal: bool = True) -> None:
    """Apply runtime PRAGMAs for the active SQLite connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute(f"PRAGMA cache_size=-{SQLITE_CACHE_KB}")
        if enable_wal:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


@event.listens_for(engine, "connect")
def _configure_sqlite_runtime(dbapi_connection, _connection_record) -> None:
    enable_wal = config.database_type == "sqlite" and config.database_path not in {":memory:", ""}
    configure_sqlite_connection(dbapi_connection, enable_wal=enable_wal)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI 依赖注入：获取数据库 Session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库：导入所有模型并创建表"""
    # 导入所有模型，确保 Base.metadata 知道所有表
    from app.models import (  # noqa: F401
        agent,
        admin_user,
        admin_session,
        task,
        module,
        sub_task,
        rule,
        issue_record,
        material_item,
        activity_log,
        review_record,
        reward_log,
        patrol_record,
        step_version,
        episode_segment,
        auto_fix,
        project_learning,
        rule_quality,
        saas_admin,
        knowledge_chunk,
        skill_registry,
        # 分镜与提示词系统
        storyboard,
        character_visual,
        # 三功能融合：协作 / 合规 / 法律资产
        collaboration,
        compliance,
        evidence,
        legal_assets,
        # 集纲生成后台任务（落库：重启不丢 + 按 owner 隔离）
        outline_job,
        # 短剧正文生成后台任务（前台唯一入口 + 后台轮询）
        short_drama_generation_job,
    )

    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    _init_full_text_search()
    print(f"[Database] 数据库初始化完成，共 {len(Base.metadata.tables)} 张表")

    # 静默迁移旧状态值（available/busy → active，offline → disabled）
    _migrate_agent_statuses()

    # 首次启动时，自动导入全局规则模板
    _load_default_rules()


def _migrate_schema():
    """静默补齐新增列，兼容已有 SQLite 数据库"""
    inspector = inspect(engine)
    with engine.begin() as conn:
        task_columns = {column["name"] for column in inspector.get_columns("task")} if inspector.has_table("task") else set()
        if "metadata_json" not in task_columns:
            conn.execute(text("ALTER TABLE task ADD COLUMN metadata_json TEXT DEFAULT ''"))
        if "metadata_version" not in task_columns:
            conn.execute(text("ALTER TABLE task ADD COLUMN metadata_version INTEGER DEFAULT 0 NOT NULL"))

        sub_task_columns = {column["name"] for column in inspector.get_columns("sub_task")} if inspector.has_table("sub_task") else set()
        if "metadata_json" not in sub_task_columns:
            conn.execute(text("ALTER TABLE sub_task ADD COLUMN metadata_json TEXT DEFAULT ''"))

        rule_columns = {column["name"] for column in inspector.get_columns("rule")} if inspector.has_table("rule") else set()
        material_columns = {column["name"] for column in inspector.get_columns("material_item")} if inspector.has_table("material_item") else set()

        if "rule_type" not in rule_columns:
            conn.execute(text("ALTER TABLE rule ADD COLUMN rule_type VARCHAR(30) DEFAULT 'core_rule'"))
        if "status" not in rule_columns:
            conn.execute(text("ALTER TABLE rule ADD COLUMN status VARCHAR(20) DEFAULT 'active'"))
        if "source" not in rule_columns:
            conn.execute(text("ALTER TABLE rule ADD COLUMN source VARCHAR(30) DEFAULT 'manual'"))

        # 素材表标签统一迁移：新增 project_tags_json 列
        if "project_tags_json" not in material_columns:
            conn.execute(text("ALTER TABLE material_item ADD COLUMN project_tags_json TEXT DEFAULT '[]'"))

        # admin_session 表：通过 create_all 自动创建，此处仅补充索引
        # （SQLAlchemy 的 Index 定义会在 create_all 时处理）

        # ── 分镜与提示词系统：step_versions 加确认字段 ──
        if inspector.has_table("step_versions"):
            sv_columns = {c["name"] for c in inspector.get_columns("step_versions")}
            if "is_confirmed" not in sv_columns:
                conn.execute(text("ALTER TABLE step_versions ADD COLUMN is_confirmed INTEGER DEFAULT 0"))
            if "confirmed_at" not in sv_columns:
                conn.execute(text("ALTER TABLE step_versions ADD COLUMN confirmed_at DATETIME"))
            if "rag_doc_ids" not in sv_columns:
                conn.execute(text("ALTER TABLE step_versions ADD COLUMN rag_doc_ids TEXT DEFAULT '{}'"))

        if inspector.has_table("front_user"):
            front_user_columns = {c["name"] for c in inspector.get_columns("front_user")}
            if "invite_code_id" not in front_user_columns:
                conn.execute(text("ALTER TABLE front_user ADD COLUMN invite_code_id VARCHAR(36) DEFAULT ''"))
            if "access_key_id" not in front_user_columns:
                conn.execute(text("ALTER TABLE front_user ADD COLUMN access_key_id VARCHAR(36) DEFAULT ''"))

        if inspector.has_table("project_v2"):
            ensure_project_v2_owner_name_uniqueness(conn)
            project_v2_columns = {c["name"] for c in inspector.get_columns("project_v2")}
            if "creation_mode" not in project_v2_columns:
                conn.execute(text("ALTER TABLE project_v2 ADD COLUMN creation_mode VARCHAR(20) DEFAULT 'solo'"))
            if "rights_capture_enabled" not in project_v2_columns:
                conn.execute(text("ALTER TABLE project_v2 ADD COLUMN rights_capture_enabled INTEGER DEFAULT 1"))

        if inspector.has_table("scene"):
            ensure_scene_episode_number_uniqueness(conn)

        if inspector.has_table("generation_job"):
            generation_job_columns = {c["name"] for c in inspector.get_columns("generation_job")}
            if "gate_warning" not in generation_job_columns:
                conn.execute(text("ALTER TABLE generation_job ADD COLUMN gate_warning TEXT DEFAULT ''"))

        if inspector.has_table("user_access_key"):
            access_key_columns = {c["name"] for c in inspector.get_columns("user_access_key")}
            if "plain_key" not in access_key_columns:
                conn.execute(text("ALTER TABLE user_access_key ADD COLUMN plain_key VARCHAR(120) DEFAULT ''"))
            if "front_user_id" not in access_key_columns:
                conn.execute(text("ALTER TABLE user_access_key ADD COLUMN front_user_id VARCHAR(36) DEFAULT ''"))
            if "allow_copy_export" not in access_key_columns:
                conn.execute(text("ALTER TABLE user_access_key ADD COLUMN allow_copy_export INTEGER DEFAULT 0"))
            if "tenant_db_path" not in access_key_columns:
                conn.execute(text("ALTER TABLE user_access_key ADD COLUMN tenant_db_path VARCHAR(500) DEFAULT ''"))
            if "tenant_storage_status" not in access_key_columns:
                conn.execute(text("ALTER TABLE user_access_key ADD COLUMN tenant_storage_status VARCHAR(30) DEFAULT 'pending'"))
            if "tenant_storage_updated_at" not in access_key_columns:
                conn.execute(text("ALTER TABLE user_access_key ADD COLUMN tenant_storage_updated_at DATETIME"))

        if inspector.has_table("model_provider"):
            model_provider_columns = {c["name"] for c in inspector.get_columns("model_provider")}
            if "input_cost_cny_per_1k" not in model_provider_columns:
                conn.execute(text("ALTER TABLE model_provider ADD COLUMN input_cost_cny_per_1k NUMERIC(12, 6) DEFAULT 0.002"))
            if "output_cost_cny_per_1k" not in model_provider_columns:
                conn.execute(text("ALTER TABLE model_provider ADD COLUMN output_cost_cny_per_1k NUMERIC(12, 6) DEFAULT 0.008"))
            if "billing_multiplier" not in model_provider_columns:
                conn.execute(text("ALTER TABLE model_provider ADD COLUMN billing_multiplier NUMERIC(8, 2) DEFAULT 5"))
            if "minimum_actual_cost_cny" not in model_provider_columns:
                conn.execute(text("ALTER TABLE model_provider ADD COLUMN minimum_actual_cost_cny NUMERIC(12, 4) DEFAULT 0.01"))

        if inspector.has_table("llm_provider_setting"):
            llm_provider_columns = {c["name"] for c in inspector.get_columns("llm_provider_setting")}
            if "input_cost_cny_per_1k" not in llm_provider_columns:
                conn.execute(text("ALTER TABLE llm_provider_setting ADD COLUMN input_cost_cny_per_1k NUMERIC(12, 6) DEFAULT 0.002"))
            if "output_cost_cny_per_1k" not in llm_provider_columns:
                conn.execute(text("ALTER TABLE llm_provider_setting ADD COLUMN output_cost_cny_per_1k NUMERIC(12, 6) DEFAULT 0.008"))
            if "billing_multiplier" not in llm_provider_columns:
                conn.execute(text("ALTER TABLE llm_provider_setting ADD COLUMN billing_multiplier NUMERIC(8, 2) DEFAULT 5"))
            if "minimum_actual_cost_cny" not in llm_provider_columns:
                conn.execute(text("ALTER TABLE llm_provider_setting ADD COLUMN minimum_actual_cost_cny NUMERIC(12, 4) DEFAULT 0.01"))

        ensure_sqlite_performance_indexes(conn, existing_tables={
            name
            for name in SQLITE_PERFORMANCE_INDEXES
            if inspector.has_table(name)
        })


def ensure_sqlite_performance_indexes(conn, *, existing_tables: set[str] | None = None) -> None:
    """Create performance indexes that older SQLite files may miss."""
    tables = set(SQLITE_PERFORMANCE_INDEXES) if existing_tables is None else existing_tables
    for table_name, statements in SQLITE_PERFORMANCE_INDEXES.items():
        if table_name not in tables:
            continue
        for statement in statements:
            conn.execute(text(statement))


def ensure_project_v2_owner_name_uniqueness(conn) -> None:
    """Use per-owner project-name uniqueness instead of global name uniqueness."""
    project_columns = {
        row["name"]
        for row in conn.execute(text("PRAGMA table_info('project_v2')")).mappings().all()
    }
    if not project_columns:
        return
    if "created_by" not in project_columns:
        conn.execute(text("ALTER TABLE project_v2 ADD COLUMN created_by VARCHAR(36) DEFAULT ''"))
    conn.execute(text("UPDATE project_v2 SET created_by = '' WHERE created_by IS NULL"))

    for row in conn.execute(text("PRAGMA index_list('project_v2')")).mappings().all():
        index_name = str(row.get("name") or "")
        if not index_name or not int(row.get("unique") or 0):
            continue
        columns = [
            str(info.get("name") or "")
            for info in conn.execute(
                text(f"PRAGMA index_info({_quote_sqlite_identifier(index_name)})")
            ).mappings().all()
        ]
        if columns == ["name"] and not index_name.startswith("sqlite_autoindex_"):
            conn.execute(text(f"DROP INDEX IF EXISTS {_quote_sqlite_identifier(index_name)}"))

    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_project_v2_name ON project_v2(name)"))
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_project_v2_owner_name "
            "ON project_v2(created_by, name)"
        )
    )


def ensure_scene_episode_number_uniqueness(conn) -> None:
    """Ensure one scene_number per episode, renumbering legacy duplicates first."""
    scene_columns = {
        row["name"]
        for row in conn.execute(text("PRAGMA table_info('scene')")).mappings().all()
    }
    if not {"id", "episode_id", "scene_number"}.issubset(scene_columns):
        return

    duplicate_groups = conn.execute(text(
        """
        SELECT episode_id, scene_number, COUNT(*) AS c
        FROM scene
        GROUP BY episode_id, scene_number
        HAVING c > 1
        """
    )).mappings().all()

    for group in duplicate_groups:
        episode_id = group["episode_id"]
        scene_number = int(group["scene_number"] or 0)
        rows = conn.execute(text(
            """
            SELECT id
            FROM scene
            WHERE episode_id = :episode_id AND scene_number = :scene_number
            ORDER BY created_at, id
            """
        ), {"episode_id": episode_id, "scene_number": scene_number}).mappings().all()
        used = {
            int(row["scene_number"] or 0)
            for row in conn.execute(
                text("SELECT scene_number FROM scene WHERE episode_id = :episode_id"),
                {"episode_id": episode_id},
            ).mappings().all()
        }
        episode = conn.execute(
            text("SELECT episode_number FROM episode WHERE id = :episode_id"),
            {"episode_id": episode_id},
        ).mappings().first()
        episode_number = int((episode or {}).get("episode_number") or 0)
        next_scene_number = max(used or {0}) + 1
        for row in rows[1:]:
            while next_scene_number in used:
                next_scene_number += 1
            used.add(next_scene_number)
            scene_code = f"{episode_number}-{next_scene_number}" if episode_number else str(next_scene_number)
            conn.execute(
                text("UPDATE scene SET scene_number = :scene_number, scene_code = :scene_code WHERE id = :id"),
                {"scene_number": next_scene_number, "scene_code": scene_code, "id": row["id"]},
            )

    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_scene_episode_number ON scene(episode_id, scene_number)"))


def _init_full_text_search():
    """初始化 FTS5 全文检索虚拟表；不可用时降级为跳过，不阻断启动。"""
    db = SessionLocal()
    try:
        from app.services.full_text_search_service import ensure_fts_index

        ensure_fts_index(db)
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[Database] FTS5 全文检索初始化跳过: {exc}")
    finally:
        db.close()


def _migrate_agent_statuses():
    """静默迁移旧 Agent 状态值，仅影响 available/busy/offline"""
    from sqlalchemy import text

    db = SessionLocal()
    try:
        r1 = db.execute(
            text("UPDATE agent SET status = 'active' WHERE status IN ('available', 'busy')")
        )
        r2 = db.execute(
            text("UPDATE agent SET status = 'disabled' WHERE status = 'offline'")
        )
        total = r1.rowcount + r2.rowcount
        if total:
            db.commit()
            print(f"[Database] 已静默迁移 {total} 个 Agent 状态（旧值 → active/disabled）")
        else:
            db.rollback()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _load_default_rules():
    """首次启动时导入 rules/global-rule-example.md 作为全局规则"""
    from app.models.rule import Rule
    import uuid

    db = SessionLocal()
    try:
        # 已有全局规则，跳过
        existing = db.query(Rule).filter(Rule.scope == "global").first()
        if existing:
            return

        rule_file = os.path.join(os.getcwd(), "rules", "global-rule-example.md")
        if not os.path.exists(rule_file):
            return

        with open(rule_file, "r", encoding="utf-8") as f:
            content = f.read()

        rule = Rule(
            id=str(uuid.uuid4()),
            scope="global",
            content=content,
        )
        db.add(rule)
        db.commit()
        print(f"[Database] 已导入全局规则模板 → rules/global-rule-example.md")
    finally:
        db.close()
