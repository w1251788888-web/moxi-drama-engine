# -*- coding: utf-8 -*-
"""Shared utilities for human-aligned scoring calibration scripts.

The functions here are deliberately small and auditable. They never print API
keys and keep all scoring outputs reproducible from local files.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import ssl
import statistics as st
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "benchmark" / "human_scoring"
DOCS_DIR = ROOT.parent / "06-docs"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            rows.append(json.loads(text))
    return rows


def atomic_json_dump(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def atomic_jsonl_dump(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")
    os.replace(tmp, path)


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"another calibration process is writing {path}") from exc
        yield


def episode_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "full_output", "body"):
            if isinstance(value.get(key), str):
                return value[key]
    return ""


def load_samples(exclude_anchors: bool = True) -> list[dict[str, Any]]:
    episode_texts = load_json(DATA_DIR / "episode_texts.json", {})
    dataset = load_json(DATA_DIR / "human_scoring_dataset.json", {})
    labels: dict[tuple[str, str], float] = {}
    for drama in dataset.get("data", []):
        drama_name = drama.get("drama_folder") or drama.get("source_file") or ""
        for item in drama.get("episodes_scored", []):
            score = item.get("benchmark_total")
            if isinstance(score, (int, float)):
                labels[(drama_name, str(item.get("episode")))] = float(score)

    anchors = load_json(DATA_DIR / "judge_anchors.json", {})

    def is_anchor(drama_name: str, episode: str) -> bool:
        if not exclude_anchors:
            return False
        for anchor in anchors.values():
            if not isinstance(anchor, dict):
                continue
            anchor_drama = str(anchor.get("drama") or "")
            anchor_ep = str(anchor.get("ep") or anchor.get("episode") or "")
            if anchor_drama and anchor_drama in drama_name and anchor_ep == episode:
                return True
        return False

    samples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_name, episodes in episode_texts.items():
        label_drama = next(
            (key[0] for key in labels if key[0][:6] in source_name or source_name[:6] in key[0]),
            None,
        )
        if not label_drama:
            continue
        items = episodes.items() if isinstance(episodes, dict) else enumerate(episodes, 1)
        for ep_key, raw_episode in items:
            episode = str(ep_key)
            if is_anchor(label_drama, episode):
                continue
            text = episode_text(raw_episode).strip()
            human = labels.get((label_drama, episode))
            if human is None or not text:
                continue
            sample_id = f"{label_drama}::ep{episode}"
            if sample_id in seen:
                continue
            seen.add(sample_id)
            samples.append(
                {
                    "id": sample_id,
                    "drama": label_drama,
                    "source_name": source_name,
                    "ep": episode,
                    "human": human,
                    "text": text,
                    "text_chars": len(text),
                }
            )
    return samples


def rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = sum(range(i, j + 1)) / (j - i + 1)
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    rx, ry = rank(xs), rank(ys)
    mx, my = st.mean(rx), st.mean(ry)
    sx = sum((x - mx) ** 2 for x in rx) ** 0.5
    sy = sum((y - my) ** 2 for y in ry) ** 0.5
    if sx * sy == 0:
        return None
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(len(xs)))
    return cov / (sx * sy)


def rounded(value: float | None, ndigits: int = 3) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, ndigits)


def resolve_settings(provider: str, model: str | None) -> dict[str, Any]:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    from app.services import text_generation_service as tg

    settings = tg.get_generation_settings(provider=provider, model=model)
    if model:
        settings["model"] = model
    if not settings.get("base_url"):
        raise RuntimeError(f"{provider} base_url is missing")
    if not settings.get("api_key"):
        raise RuntimeError(f"{provider} api_key is missing")
    endpoint = str(settings.get("endpoint") or "/v1/chat/completions")
    settings["url"] = join_url(str(settings["base_url"]), endpoint)
    return settings


def join_url(base_url: str, endpoint: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    path = str(endpoint or "").strip()
    path = path if path.startswith("/") else f"/{path}"
    if base.endswith("/v1") and path.startswith("/v1/"):
        path = path[3:]
    return f"{base}{path}"


def chat_completion(
    settings: dict[str, Any],
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    timeout: int,
    retries: int,
    retry_sleep: float,
) -> dict[str, Any]:
    ctx = ssl.create_default_context()
    if not bool(settings.get("ssl_verify", True)):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    body = {
        "model": settings["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": "Bearer " + str(settings["api_key"]),
        "Content-Type": "application/json",
    }
    started = time.perf_counter()
    last_error = None
    for attempt in range(1, retries + 2):
        try:
            req = urllib.request.Request(settings["url"], encoded, headers)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                payload = json.loads(resp.read())
            raw = payload["choices"][0]["message"].get("content", "") or ""
            return {
                "ok": True,
                "raw": raw,
                "attempts": attempt,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": None,
            }
        except urllib.error.HTTPError as exc:
            body_text = ""
            try:
                body_text = exc.read().decode("utf-8", "ignore")[:300]
            except Exception:
                body_text = ""
            last_error = f"http_{exc.code}:{body_text}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}:{str(exc)[:220]}"
        if attempt <= retries:
            time.sleep(retry_sleep * attempt)
    return {
        "ok": False,
        "raw": "",
        "attempts": retries + 1,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "error": last_error or "unknown_error",
    }

