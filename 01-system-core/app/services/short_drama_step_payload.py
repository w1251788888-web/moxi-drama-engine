"""短剧写作会话 metadata 中 "步骤产物" 的统一读写工具（从 short_drama_writing.py 抽出）。

设计：
- 部分步骤（scene_list / script_draft / quality_check / narrative_consistency / storyboard）
  按"集"维护，存在 metadata["episodes"][episode_no]["steps"][step_id]
- 项目级步骤直接放在 metadata["steps"][step_id]
- 写按集步骤时，会同步把"最新一份"镜像写到 metadata["steps"]，旧前端能继续读

把它从主 router 抽出来：
- 后续多个子文件（export_routes、validate_routes 等）共享同一份读写约定
- 单元测试直接对纯函数写断言，不必启 FastAPI app
"""
from __future__ import annotations

from typing import Any

PER_EPISODE_STEPS: set[str] = {
    "scene_list",
    "script_draft",
    "quality_check",
    "narrative_consistency",
    "storyboard",
}


def is_per_episode_step(step_id: str) -> bool:
    return step_id in PER_EPISODE_STEPS


def get_step_payload(metadata: dict, step_id: str, episode_no: int = 0) -> dict | None:
    """统一读取 step 输出。

    指定集号读取按集步骤时，只读取该集自己的命名空间，避免缺失集误读
    metadata["steps"] 里的“最近一次镜像”而串到别的集。
    """
    if not isinstance(metadata, dict):
        return None
    if is_per_episode_step(step_id) and episode_no and episode_no > 0:
        episodes = metadata.get("episodes")
        if isinstance(episodes, dict):
            ep_node = episodes.get(str(episode_no))
            if isinstance(ep_node, dict):
                steps = ep_node.get("steps")
                if isinstance(steps, dict):
                    payload = steps.get(step_id)
                    if isinstance(payload, dict):
                        return payload
        return None
    # 回退到旧位置（项目级步骤或历史数据）
    legacy = metadata.get("steps")
    if isinstance(legacy, dict):
        payload = legacy.get(step_id)
        if isinstance(payload, dict):
            return payload
    return None


def set_step_payload(metadata: dict, step_id: str, episode_no: int, payload: dict) -> None:
    """统一写入 step 输出。"""
    if not isinstance(metadata, dict):
        return
    if is_per_episode_step(step_id) and episode_no and episode_no > 0:
        episodes = metadata.setdefault("episodes", {})
        if not isinstance(episodes, dict):
            episodes = {}
            metadata["episodes"] = episodes
        ep_node = episodes.setdefault(str(episode_no), {})
        if not isinstance(ep_node, dict):
            ep_node = {}
            episodes[str(episode_no)] = ep_node
        steps = ep_node.setdefault("steps", {})
        if not isinstance(steps, dict):
            steps = {}
            ep_node["steps"] = steps
        steps[step_id] = payload
        # 同时维护 metadata["steps"] 的最新一份镜像，便于旧前端查看"最近一集"
        legacy = metadata.setdefault("steps", {})
        if isinstance(legacy, dict):
            legacy[step_id] = payload
        return
    # 项目级步骤：仍写到 metadata["steps"]
    legacy = metadata.setdefault("steps", {})
    if not isinstance(legacy, dict):
        legacy = {}
        metadata["steps"] = legacy
    legacy[step_id] = payload


def list_episodes_with_steps(metadata: dict) -> list[int]:
    """列出 metadata 中所有有 step 输出的集号（升序）。"""
    if not isinstance(metadata, dict):
        return []
    episodes = metadata.get("episodes")
    if not isinstance(episodes, dict):
        return []
    out: list[int] = []
    for k, v in episodes.items():
        try:
            n = int(k)
        except Exception:
            continue
        if n <= 0:
            continue
        if isinstance(v, dict) and isinstance(v.get("steps"), dict) and v["steps"]:
            out.append(n)
    return sorted(out)
