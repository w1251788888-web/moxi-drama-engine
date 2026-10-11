"""SSE 工具：format SSE 行 + 把同步 token 生成器桥接为 async（从 short_drama_writing.py 抽出）。

2 个工具：

- sse_event：把 (event, data) 编码成 “event: ...\\ndata: ...\\n\\n”
- stream_sync_text_generation：把 generate_text_stream 同步生成器桥接为 async 迭代器
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from app.services.text_generation_service import generate_text_stream


def sse_event(event: str, data: Any) -> str:
    """格式化 SSE 行。"""
    payload = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    return f"event: {event}\ndata: {payload}\n\n"


async def stream_sync_text_generation(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float | None = None,
    generation_kwargs: dict[str, Any] | None = None,
    cancel_event: threading.Event | None = None,
):
    """把同步 token 生成器桥接为 async 迭代器，做到真正边产边发。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    done_marker = object()
    generation_kwargs = generation_kwargs or {}
    cancel_event = cancel_event or threading.Event()

    def _worker() -> None:
        try:
            for token in generate_text_stream(
                system_prompt,
                user_prompt,
                temperature=temperature,
                **generation_kwargs,
            ):
                if cancel_event.is_set():
                    break
                loop.call_soon_threadsafe(queue.put_nowait, ("token", token))
        except Exception as exc:  # pragma: no cover - 运行时容错
            loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, ("done", done_marker))

    threading.Thread(target=_worker, daemon=True).start()

    try:
        while True:
            event, payload = await queue.get()
            if event == "token":
                yield str(payload or "")
                continue
            if event == "error":
                raise payload
            if event == "done":
                break
    except asyncio.CancelledError:
        cancel_event.set()
        raise
    finally:
        cancel_event.set()
