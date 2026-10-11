"""测试页 TestingScriptRequest "回填项目上下文" 工具（从 short_drama_writing.py 抽出）。

这两个函数原先在主 router 内：
- load_testing_project_payload：从 DB+磁盘 拼出当前项目的 (project_payload, workspace_payload)
- enrich_testing_request_from_project：把 req 中"调用方没填的字段"用项目数据回填

抽出后：
- validate / deep-audit / auto-fix 等 endpoint 可以直接 import 用
- 主 router 只保留薄薄一层别名（不再 80 行函数）
- 单元测试更易写（纯数据 + DB 注入）
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models.project_v2 import Episode, ProjectV2
from app.services import workspace_service
from app.services.issue_feedback_service import build_issue_feedback_snapshot
from app.services.material_library_service import select_project_materials
from app.services.official_source_consistency import (
    OfficialSourceConsistencyError,
    validate_locked_official_source_consistency,
)
from app.services.short_drama_testing_normalizers import (
    normalize_testing_canon_packet,
    normalize_testing_episode_memory_cards,
    normalize_testing_series_simulation_packet,
    testing_workflow_context_defaults,
)

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


class PreviousOfficialSourceGateError(RuntimeError):
    """Raised when a next-episode request cannot prove the direct previous official source."""

    def __init__(
        self,
        reason_code: str,
        *,
        project_id: str,
        target_episode_no: int,
        previous_episode_no: int,
    ) -> None:
        self.reason_code = reason_code
        self.project_id = project_id
        self.target_episode_no = target_episode_no
        self.previous_episode_no = previous_episode_no
        super().__init__(reason_code)


def _previous_official_reason(reason_code: str) -> str:
    if reason_code.startswith("locked_official_"):
        return f"previous_{reason_code}"
    return reason_code


def _rebased_release_workspace_path(project: ProjectV2) -> Path | None:
    raw_workspace = str(project.workspace_path or "").strip()
    project_name = str(project.name or "").strip()
    if not raw_workspace or not project_name:
        return None

    parts = Path(raw_workspace).expanduser().parts
    for index, part in enumerate(parts):
        if part != "03-project-library":
            continue
        if index + 2 >= len(parts):
            continue
        root_name = parts[index + 1]
        if root_name not in {"new-projects", "新建项目"}:
            continue
        relative_parts = parts[index + 2:]
        if not relative_parts or relative_parts[-1] != project_name:
            return None
        target_root = (
            workspace_service.WORKSPACE_ROOT
            if root_name == "new-projects"
            else workspace_service.LEGACY_WORKSPACE_ROOT
        )
        return target_root.joinpath(*relative_parts)
    return None


def _ensure_testing_project_workspace(project: ProjectV2, *, create: bool) -> Path:
    allowed_roots = workspace_service.project_workspace_roots()
    try:
        return workspace_service.ensure_project_workspace(
            project.workspace_path or "",
            allowed_roots=allowed_roots,
            create=create,
        )
    except workspace_service.WorkspaceBoundaryError:
        rebased = _rebased_release_workspace_path(project)
        if rebased is None:
            raise
        source = Path(str(project.workspace_path or "")).expanduser()
        if not rebased.exists():
            if source.exists() and source.is_dir():
                rebased.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, rebased, dirs_exist_ok=True)
            elif create:
                rebased.mkdir(parents=True, exist_ok=True)
        workspace = workspace_service.ensure_project_workspace(
            rebased,
            allowed_roots=allowed_roots,
            create=create,
        )
        project.workspace_path = str(workspace)
        return workspace


def _compact_saved_scene_excerpt(content: str, *, limit: int = 700) -> str:
    lines = [
        line.replace("\r", " ").strip()
        for line in str(content or "").splitlines()
        if line.strip()
    ]
    text = " ".join(lines)
    if len(text) <= limit:
        return text
    return text[-limit:].strip()


def _saved_scene_tail(content: str, *, limit: int = 260) -> str:
    lines = [
        line.strip()
        for line in str(content or "").splitlines()
        if line.strip()
    ]
    if not lines:
        return ""
    tail = lines[-1]
    return tail[-limit:].strip()


def _load_saved_episode_memory_cards(
    db: Session,
    project_id: str,
    *,
    before_episode_no: int,
    project_workspace_path: str = "",
    limit: int = 9,
) -> list[dict[str, Any]]:
    if before_episode_no <= 1:
        return []

    previous_episode_no = before_episode_no - 1
    episode = (
        db.query(Episode)
        .filter(
            Episode.project_id == project_id,
            Episode.episode_number == previous_episode_no,
        )
        .first()
    )
    if episode is None:
        return []

    try:
        official = validate_locked_official_source_consistency(
            db,
            project_id=project_id,
            episode_number=previous_episode_no,
            project_workspace_path=project_workspace_path,
        )
    except OfficialSourceConsistencyError as exc:
        raise PreviousOfficialSourceGateError(
            _previous_official_reason(exc.reason_code),
            project_id=project_id,
            target_episode_no=before_episode_no,
            previous_episode_no=previous_episode_no,
        ) from exc

    full_content = official.content
    tail = _saved_scene_tail(full_content)
    body_excerpt = _compact_saved_scene_excerpt(full_content)
    source_map = official.source_map
    return [{
        "episode_no": previous_episode_no,
        "title": str(episode.title or ""),
        "summary": str(episode.summary or ""),
        "opening_state": "",
        "ending_state": tail,
        "relationship_delta": [],
        "information_delta": [],
        "power_delta": [],
        "unresolved_hooks": [tail] if tail else [],
        "spoiler_guard": [],
        "tail_excerpt": tail,
        "body_excerpt": body_excerpt,
        "actual_progress": body_excerpt,
        "quality_summary": "",
        "source": "episode_locked_content_version",
        "source_label": "episode_locked_content_version",
        "official_source": "episode_locked",
        "content_version_id": official.content_version_id,
        "content_hash": official.content_hash,
        "source_map": source_map,
    }]


def _merge_saved_episode_memory_cards(existing: list[dict[str, Any]], saved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_ep: dict[int, dict[str, Any]] = {}
    for item in existing or []:
        if not isinstance(item, dict):
            continue
        ep_no = int(item.get("episode_no") or 0)
        if ep_no > 0:
            by_ep[ep_no] = dict(item)
    for item in saved:
        ep_no = int(item.get("episode_no") or 0)
        if ep_no > 0:
            by_ep[ep_no] = {**by_ep.get(ep_no, {}), **item}
    return [by_ep[ep_no] for ep_no in sorted(by_ep)]


def _merge_saved_previous_episode_briefs(existing: list[dict[str, Any]], saved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_ep: dict[int, dict[str, Any]] = {}
    for item in existing or []:
        if not isinstance(item, dict):
            continue
        ep_no = int(item.get("episode_no") or item.get("ep") or 0)
        if ep_no > 0:
            by_ep[ep_no] = dict(item)
    for card in saved:
        ep_no = int(card.get("episode_no") or 0)
        if ep_no <= 0:
            continue
        current = dict(by_ep.get(ep_no, {}))
        current.update({
            "episode_no": ep_no,
            "title": current.get("title") or card.get("title", ""),
            "summary": current.get("summary") or card.get("summary", ""),
            "ending_state": card.get("ending_state", ""),
            "tail_excerpt": card.get("tail_excerpt", ""),
            "body_excerpt": card.get("body_excerpt", ""),
            "actual_progress": card.get("actual_progress") or card.get("body_excerpt", ""),
            "unresolved_hooks": card.get("unresolved_hooks", []),
            "source": card.get("source", ""),
            "source_label": card.get("source_label", card.get("source", "")),
            "official_source": card.get("official_source", ""),
            "content_version_id": card.get("content_version_id", ""),
            "content_hash": card.get("content_hash", ""),
            "source_map": card.get("source_map", {}),
        })
        by_ep[ep_no] = current
    return [by_ep[ep_no] for ep_no in sorted(by_ep)]


def load_testing_project_payload(db: Session, project_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """从 DB+磁盘 加载当前项目的 (project_payload, workspace_payload)。

    project_payload：DB 里项目基本字段
    workspace_payload：磁盘 project.json 里的 workspace 数据（characters/state_cards/...）
    """
    project = db.query(ProjectV2).filter(ProjectV2.id == project_id).first()
    if not project:
        return {}, {}
    project_payload = {
        "id": project.id,
        "name": project.name,
        "project_type": project.project_type,
        "audience_axis": project.audience_axis,
        "genre_main": project.genre_main,
        "genre_sub": project.genre_sub,
        "config": project.get_config() if hasattr(project, "get_config") else {},
        "workspace_path": project.workspace_path or "",
    }
    try:
        workspace = _ensure_testing_project_workspace(project, create=False)
    except workspace_service.WorkspaceError:
        workspace_payload = {}
    else:
        db.flush()
        workspace_payload = workspace_service.read_project_json(workspace)
    return project_payload, workspace_payload


def enrich_testing_request_from_project(req: "TestingScriptRequest", db: Session) -> "TestingScriptRequest":
    """把 req 中"调用方没填的字段"用项目数据回填。

    回填策略：
    1. 项目基础字段（project_type / audience_axis / 题材轴 / series_title）从 DB 项目读
    2. subgenre_track / sample_track 从 project.config 读
    3. characters / state_cards / episode_memory_cards / canon_packet / series_simulation_packet
       从磁盘 workspace_payload 读（normalizer 兜底空对象）
    4. materials —— 工作流上下文里没有就调推荐
    5. issue_feedback —— 工作流上下文里没有就实时算一份
    6. rule_profile / world_rules / ... / RAG 一堆字符串字段也从工作流上下文读
    """
    project_id = str(getattr(req, "project_id", "") or "").strip()
    if not project_id:
        return req
    project_payload, workspace_payload = load_testing_project_payload(db, project_id)
    if not project_payload:
        return req

    workflow_context = (
        workspace_payload.get("workflow_context")
        if isinstance(workspace_payload.get("workflow_context"), dict)
        else testing_workflow_context_defaults()
    )
    workflow_context = {**testing_workflow_context_defaults(), **workflow_context}
    config_payload = project_payload.get("config") if isinstance(project_payload.get("config"), dict) else {}
    updates: dict[str, Any] = {}
    saved_episode_cards = _load_saved_episode_memory_cards(
        db,
        project_id,
        before_episode_no=int(getattr(req, "episode_no", 1) or 1),
        project_workspace_path=str(project_payload.get("workspace_path") or ""),
    )

    for key in ("project_type", "audience_axis", "genre_main", "genre_sub", "series_title"):
        req_value = getattr(req, key, "") if key != "series_title" else getattr(req, "series_title", "")
        if not str(req_value or "").strip():
            if key == "series_title":
                updates["series_title"] = str(project_payload.get("name") or "")
            else:
                updates[key] = str(project_payload.get(key) or "")

    if not str(req.subgenre_track or "").strip():
        updates["subgenre_track"] = str(config_payload.get("subgenre_track") or "")
    if not str(req.sample_track or "").strip():
        updates["sample_track"] = str(config_payload.get("sample_track") or "")
    if not req.characters:
        updates["characters"] = workspace_payload.get("characters") if isinstance(workspace_payload.get("characters"), list) else []
    if not req.state_cards:
        updates["state_cards"] = workspace_payload.get("state_cards") if isinstance(workspace_payload.get("state_cards"), dict) else {}
    if not req.episode_memory_cards:
        updates["episode_memory_cards"] = normalize_testing_episode_memory_cards(workspace_payload.get("episode_memory_cards"))
    if saved_episode_cards:
        base_memory_cards = (
            updates.get("episode_memory_cards")
            if "episode_memory_cards" in updates
            else req.episode_memory_cards
        )
        if not base_memory_cards:
            base_memory_cards = normalize_testing_episode_memory_cards(workspace_payload.get("episode_memory_cards"))
        updates["episode_memory_cards"] = _merge_saved_episode_memory_cards(
            list(base_memory_cards or []),
            saved_episode_cards,
        )
        updates["previous_episode_briefs"] = _merge_saved_previous_episode_briefs(
            req.previous_episode_briefs,
            saved_episode_cards,
        )
    if not req.canon_packet:
        updates["canon_packet"] = normalize_testing_canon_packet(workspace_payload.get("canon_packet"))
    if not req.series_simulation_packet:
        updates["series_simulation_packet"] = normalize_testing_series_simulation_packet(workflow_context.get("series_simulation_packet"))

    if not req.materials:
        materials = workflow_context.get("materials") if isinstance(workflow_context.get("materials"), list) else []
        if not materials:
            project_tags = [
                str(project_payload.get("genre_main") or "").strip(),
                str(project_payload.get("genre_sub") or "").strip(),
                str(project_payload.get("audience_axis") or "").strip(),
            ]
            category_path = " / ".join(part for part in project_tags[:2] if part) or "当前赛道"
            materials = select_project_materials(
                db,
                content_type=str(project_payload.get("project_type") or "短剧"),
                project_tags=[tag for tag in project_tags if tag],
                limit=3,
                issue_feedback=workflow_context.get("issue_feedback") or {},
                category_path=category_path,
            )
        updates["materials"] = materials

    if not req.issue_feedback:
        issue_feedback = workflow_context.get("issue_feedback") if isinstance(workflow_context.get("issue_feedback"), dict) else {}
        if not issue_feedback:
            category_path = " / ".join(
                part for part in [
                    str(project_payload.get("genre_main") or "").strip(),
                    str(project_payload.get("genre_sub") or "").strip(),
                ] if part
            ) or "当前赛道"
            issue_feedback = build_issue_feedback_snapshot(db, category_path)
        updates["issue_feedback"] = issue_feedback

    for key in ("rule_profile", "world_rules", "golden_finger_rules", "conflict_plan", "episode_novel_anchor"):
        if not str(getattr(req, key, "") or "").strip():
            updates[key] = str(workflow_context.get(key) or "")
    for key in ("quality_report", "compliance_report", "manual_edit_context"):
        if not getattr(req, key, {}):
            updates[key] = workflow_context.get(key) if isinstance(workflow_context.get(key), dict) else {}
    for key in (
        "rag_asset_references",
        "rag_market_signals",
        "rag_novel_chapters",
        "rag_script_references",
        "rag_character_references",
        "rag_beat_references",
        "rag_review_references",
    ):
        if not str(getattr(req, key, "") or "").strip():
            rag_ctx = workflow_context.get("rag_context") if isinstance(workflow_context.get("rag_context"), dict) else {}
            updates[key] = str(rag_ctx.get(key) or "")

    return req.model_copy(update=updates) if updates else req
