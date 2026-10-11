#!/usr/bin/env python3
"""Production smoke test for the deployed 墨戏生花 app.

The script tests the real HTTP surface that a key user depends on:
SPA shell, access-key login, user session, project isolation, project CRUD,
workflow context, characters, episode/scene persistence, and optional LLM
features. It creates a temporary project when --write is enabled and deletes it
by default.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any


class SmokeError(RuntimeError):
    pass


@dataclass
class CheckResult:
    name: str
    ok: bool
    status: int | None
    elapsed: float
    detail: str


class HttpClient:
    def __init__(self, base_url: str, *, insecure: bool = False):
        self.base_url = base_url.rstrip("/")
        self.headers: dict[str, str] = {}
        self.insecure = insecure

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Any | None = None,
        timeout: float = 30,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any, float]:
        url = self.base_url + path
        data = None
        request_headers = dict(self.headers)
        request_headers.update(headers or {})
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        started = time.time()
        try:
            context = ssl._create_unverified_context() if self.insecure and url.startswith("https://") else None
            with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
                raw = resp.read().decode("utf-8", "ignore")
                elapsed = time.time() - started
                content_type = resp.headers.get("content-type", "")
                if "application/json" in content_type:
                    return resp.status, json.loads(raw) if raw else {}, elapsed
                return resp.status, raw, elapsed
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "ignore")
            elapsed = time.time() - started
            try:
                body: Any = json.loads(raw)
            except Exception:
                body = raw[:800]
            return exc.code, body, elapsed
        except urllib.error.URLError as exc:
            elapsed = time.time() - started
            return 0, {"detail": str(exc.reason)}, elapsed

    def get(self, path: str, **kwargs) -> tuple[int, Any, float]:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, payload: Any | None = None, **kwargs) -> tuple[int, Any, float]:
        return self.request("POST", path, payload=payload, **kwargs)

    def put(self, path: str, payload: Any | None = None, **kwargs) -> tuple[int, Any, float]:
        return self.request("PUT", path, payload=payload, **kwargs)

    def delete(self, path: str, **kwargs) -> tuple[int, Any, float]:
        return self.request("DELETE", path, **kwargs)


def workflow_context_roundtrip_matches(workflow_context: Any, marker: str) -> bool:
    if not isinstance(workflow_context, dict):
        return False
    outline_state = workflow_context.get("outline_state")
    chat_brainstorm = workflow_context.get("chat_brainstorm")
    if not isinstance(outline_state, dict) or not isinstance(chat_brainstorm, dict):
        return False
    messages = chat_brainstorm.get("messages")
    if not isinstance(messages, list):
        return False
    chat_marker = f"部署烟测 {marker}"
    return (
        outline_state.get("deployment_smoke_marker") == marker
        and any(
            isinstance(item, dict)
            and item.get("role") == "user"
            and item.get("content") == chat_marker
            for item in messages
        )
    )


class SmokeRunner:
    def __init__(self, client: HttpClient, *, verbose: bool = False):
        self.client = client
        self.verbose = verbose
        self.results: list[CheckResult] = []
        self.project_id: str | None = None

    def check(self, name: str, status: int | None, elapsed: float, ok: bool, detail: str = "") -> None:
        self.results.append(CheckResult(name, ok, status, elapsed, detail))
        prefix = "PASS" if ok else "FAIL"
        print(f"[{prefix}] {name} ({status if status is not None else '-'}) {elapsed:.2f}s {detail}")
        if not ok:
            raise SmokeError(f"{name} failed: {detail}")

    def expect_status(self, name: str, status: int, body: Any, elapsed: float, expected: int = 200) -> Any:
        detail = ""
        if status != expected:
            detail = json.dumps(body, ensure_ascii=False)[:500]
        self.check(name, status, elapsed, status == expected, detail)
        return body

    def run_public_checks(self) -> None:
        status, body, elapsed = self.client.get("/api/health", timeout=20)
        self.expect_status("health", status, body, elapsed)
        if isinstance(body, dict):
            self.check("health service name", status, 0, body.get("service") == "墨戏生花", str(body))

        status, body, elapsed = self.client.get("/login", timeout=20)
        ok = status == 200 and isinstance(body, str) and "<div id=\"app\"" in body and "墨戏生花" in body
        self.check("frontend spa login shell", status, elapsed, ok, "login SPA loaded" if ok else str(body)[:300])

    def login_access_key(self, access_key: str) -> dict[str, Any]:
        status, body, elapsed = self.client.post(
            "/api/user/access-key/login",
            {"access_key": access_key},
            timeout=30,
        )
        session = self.expect_status("access key login", status, body, elapsed)
        token = session.get("session_token") if isinstance(session, dict) else ""
        if not token:
            raise SmokeError("access key login did not return session_token")
        self.client.headers["X-User-Session"] = token
        return session

    def run_user_checks(self) -> None:
        status, body, elapsed = self.client.get("/api/user/session", timeout=30)
        session = self.expect_status("user session", status, body, elapsed)
        if isinstance(session, dict):
            self.check(
                "user session permissions",
                status,
                0,
                "advanced_generation_enabled" in session and "allow_copy_export" in session,
                json.dumps({
                    "advanced": session.get("advanced_generation_enabled"),
                    "copy": session.get("allow_copy_export"),
                }, ensure_ascii=False),
            )

        status, body, elapsed = self.client.get("/api/v2/projects/?limit=10", timeout=30)
        projects = self.expect_status("project list", status, body, elapsed)
        self.check("project list shape", status, 0, isinstance(projects, list), f"count={len(projects) if isinstance(projects, list) else 'n/a'}")

    def run_write_chain(self, *, keep_project: bool, script_segment: bool = False) -> None:
        project_name = f"部署烟测-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        status, body, elapsed = self.client.post(
            "/api/v2/projects/",
            {
                "name": project_name,
                "description": "线上部署烟测临时项目，可删除",
                "project_type": "short_drama",
                "audience_axis": "男频",
                "genre_main": "现代都市",
                "genre_sub": "逆袭",
                "creation_mode": "solo",
                "config": {"total_episodes": 30},
            },
            timeout=40,
        )
        project = self.expect_status("create project", status, body, elapsed)
        self.project_id = project.get("id") if isinstance(project, dict) else None
        if not self.project_id:
            raise SmokeError("create project did not return id")

        try:
            marker = f"smoke-{int(time.time())}"
            status, body, elapsed = self.client.put(
                f"/api/v2/projects/{self.project_id}/workflow-context",
                {
                    "merge": True,
                    "workflow_context": {
                        "chat_brainstorm": {
                            "schema_version": 1,
                            "messages": [{"role": "user", "content": f"部署烟测 {marker}"}],
                        },
                        "outline_state": {
                            "deployment_smoke_marker": marker,
                            "logline": "测试主角在危机中反击并完成自我证明。",
                        },
                    },
                },
                timeout=40,
            )
            self.expect_status("save workflow context", status, body, elapsed)

            status, body, elapsed = self.client.get(f"/api/v2/projects/{self.project_id}/workflow-context", timeout=40)
            ctx = self.expect_status("load workflow context", status, body, elapsed)
            workflow_context = ctx.get("workflow_context", {}) if isinstance(ctx, dict) else {}
            found_marker = workflow_context_roundtrip_matches(workflow_context, marker)
            self.check("workflow context roundtrip", status, 0, found_marker, marker)

            characters = [
                {"id": "c1", "name": "何铮", "role": "主角", "bio": "高位男主，外冷内热，背负家族危机。"},
                {"id": "c2", "name": "吴雪", "role": "配角", "bio": "低位女主，聪明克制，是主角反击链路的关键盟友。"},
            ]
            status, body, elapsed = self.client.put(
                f"/api/v2/projects/{self.project_id}/characters",
                {"characters": characters},
                timeout=40,
            )
            self.expect_status("save characters", status, body, elapsed)
            status, body, elapsed = self.client.get(f"/api/v2/projects/{self.project_id}/characters", timeout=40)
            loaded = self.expect_status("load characters", status, body, elapsed)
            loaded_chars = loaded.get("characters") if isinstance(loaded, dict) else []
            self.check("characters roundtrip", status, 0, len(loaded_chars) >= 2, f"count={len(loaded_chars)}")

            status, body, elapsed = self.client.post(
                f"/api/v2/projects/{self.project_id}/episodes",
                {"title": "第1集 危机开局", "summary": "主角被迫面对家族危机。"},
                timeout=40,
            )
            if status not in (200, 201):
                self.check("create episode", status, elapsed, False, json.dumps(body, ensure_ascii=False)[:500])
            else:
                self.check("create episode", status, elapsed, True, "episode 1")

            status, body, elapsed = self.client.post(
                f"/api/v2/projects/{self.project_id}/episodes/1/scenes",
                {
                    "time": "夜",
                    "location_type": "内景",
                    "location_name": "办公室",
                    "content": "何铮收到坏消息，意识到局面已经失控。",
                },
                timeout=40,
            )
            if status not in (200, 201):
                self.check("create scene", status, elapsed, False, json.dumps(body, ensure_ascii=False)[:500])
            else:
                self.check("create scene", status, elapsed, True, "scene 1")

            status, body, elapsed = self.client.post(
                f"/api/v2/projects/{self.project_id}/episodes/1/scenes/1/save",
                {
                    "content": "第1集 第1场\n夜，办公室。\n何铮盯着手机里的坏消息，终于明白这次不是普通危机，而是有人故意逼他下桌。",
                    "editor_type": "deployment_smoke",
                    "editor_name": "production_smoke_test",
                    "change_note": "部署烟测保存剧本",
                    "create_checkpoint": True,
                },
                timeout=40,
            )
            self.expect_status("save scene content", status, body, elapsed)

            status, body, elapsed = self.client.get(f"/api/v2/projects/{self.project_id}/episodes", timeout=40)
            episodes = self.expect_status("list episodes", status, body, elapsed)
            self.check("episodes persisted", status, 0, isinstance(episodes, list) and len(episodes) >= 1, f"count={len(episodes) if isinstance(episodes, list) else 'n/a'}")

            status, body, elapsed = self.client.get(f"/api/v2/projects/{self.project_id}/episodes/1/scenes", timeout=40)
            scenes = self.expect_status("list scenes", status, body, elapsed)
            self.check("scenes persisted", status, 0, isinstance(scenes, list) and len(scenes) >= 1, f"count={len(scenes) if isinstance(scenes, list) else 'n/a'}")

            status, body, elapsed = self.client.post(
                f"/api/v2/projects/{self.project_id}/episodes",
                {"title": "第2集 删除烟测", "summary": "用于验证单集删除。"},
                timeout=40,
            )
            if status not in (200, 201):
                self.check("create deletable episode", status, elapsed, False, json.dumps(body, ensure_ascii=False)[:500])
            else:
                self.check("create deletable episode", status, elapsed, True, "episode 2")

            status, body, elapsed = self.client.delete(
                f"/api/v2/projects/{self.project_id}/episodes/2",
                timeout=40,
            )
            self.expect_status("delete single episode", status, body, elapsed)

            status, body, elapsed = self.client.get(f"/api/v2/projects/{self.project_id}/episodes", timeout=40)
            episodes_after_delete = self.expect_status("list episodes after single delete", status, body, elapsed)
            deleted_episode_absent = (
                isinstance(episodes_after_delete, list)
                and all(int(item.get("episode_number") or 0) != 2 for item in episodes_after_delete)
            )
            self.check(
                "single episode delete persisted",
                status,
                0,
                deleted_episode_absent,
                f"episodes={len(episodes_after_delete) if isinstance(episodes_after_delete, list) else 'n/a'}",
            )

            if script_segment:
                self.run_script_segment_generation()
        finally:
            if self.project_id and not keep_project:
                self.delete_current_project()

    def run_script_segment_generation(self) -> None:
        if not self.project_id:
            raise SmokeError("script segment smoke needs an existing project")
        payload = {
            "project_id": self.project_id,
            "project_type": "真人短剧-男频",
            "audience_axis": "男频",
            "genre_main": "现代都市",
            "genre_sub": "逆袭",
            "format_type": "真人短剧",
            "episode_count": 30,
            "episode_minutes": 1.5,
            "scene_header_style": "bracket",
            "brief": "高位男主何铮在发布会被反派当众逼宫，低位女主吴雪带着关键旧手机出现，二人形成临时同盟。",
            "worldview": "现代都市集团权力斗争。",
            "conflict": "何铮被柳玉宗构陷，必须在公众场合保住权限并找回证据。",
            "episode_no": 1,
            "scene_no": 1,
            "episode_title": "发布会逼宫",
            "episode_summary": "柳玉宗在发布会上拿伪造签名逼何铮停权，吴雪带旧手机闯入。",
            "episode_conflict": "伪造签名与旧手机证据对撞。",
            "episode_hook": "旧手机里弹出一条未读消息，指向真正签字人。",
            "current_content": "",
            "continuity_notes": "",
            "word_count_target": 250,
            "word_count_min": 120,
            "word_count_max": 280,
            "target_chars": 250,
            "exclude_punctuation_for_count": True,
            "enforce_standard_format": True,
            "mode": "segment",
            "segment_id": "hook",
            "selected_character_ids": ["c1", "c2"],
            "characters": [
                {
                    "id": "c1",
                    "name": "何铮",
                    "role": "protagonist",
                    "age": "30岁左右",
                    "info": "高位男主，集团继承人，被伪造签名构陷。外冷内稳，压着怒意反击。",
                    "background": "集团核心继承人，掌握关键项目权限。",
                    "motivation": "保住权限，查出幕后构陷者。",
                    "relationships": [{"targetId": "c2", "targetName": "吴雪", "type": "临时同盟", "strength": 65}],
                },
                {
                    "id": "c2",
                    "name": "吴雪",
                    "role": "supporting",
                    "age": "24岁左右",
                    "info": "低位女主，曾被项目牵连，手里有旧手机证据。聪明克制，敢在公开场合破局。",
                    "background": "项目旧员工，知道签名造假的线索。",
                    "motivation": "自证清白，同时帮何铮撬开真相。",
                    "relationships": [{"targetId": "c1", "targetName": "何铮", "type": "临时同盟", "strength": 65}],
                },
            ],
            "generation_provider": "fufuapi",
            "generation_model": "gpt-5.4-mini",
        }
        status, body, elapsed = self.client.post(
            "/api/admin/short-drama/testing/script-scene/stream",
            payload,
            timeout=220,
            headers={"Accept": "text/event-stream"},
        )
        self.check("script segment stream status", status, elapsed, status == 200, str(body)[:500])
        events = parse_sse_events(str(body))
        error_events = [data for event, data in events if event == "error"]
        done_events = [data for event, data in events if event == "done"]
        if error_events:
            self.check("script segment stream error-free", status, 0, False, json.dumps(error_events[-1], ensure_ascii=False)[:700])
        if not done_events:
            self.check("script segment stream done", status, 0, False, str(body)[:700])
        content = str(done_events[-1].get("content") or "")
        self.check("script segment generated content", status, 0, len(content.strip()) >= 80, content[:120])

    def delete_current_project(self) -> None:
        if not self.project_id:
            return
        status, body, elapsed = self.client.delete(
            f"/api/v2/projects/{self.project_id}?delete_workspace=true",
            timeout=40,
        )
        self.expect_status("delete smoke project", status, body, elapsed)
        self.project_id = None

    def run_llm_checks(self) -> None:
        status, body, elapsed = self.client.post(
            "/api/user/ai/chat",
            {
                "messages": [{"role": "user", "content": "请只回复：OK"}],
                "context": "chat",
                "max_tokens": 50,
            },
            timeout=130,
        )
        content = body.get("content", "") if isinstance(body, dict) else ""
        self.expect_status("user ai chat", status, body, elapsed)
        self.check("user ai chat content", status, 0, bool(content.strip()), content[:80])

        status, body, elapsed = self.client.post(
            "/api/user/market/ai-topics",
            {"keyword": "复仇", "style_axis": "female", "count": 1},
            timeout=160,
        )
        self.expect_status("user market ai topics", status, body, elapsed)
        required = {"hotWords", "trending", "recommended", "cases", "inspirations"}
        ok = isinstance(body, dict) and required.issubset(body.keys())
        self.check("user market ai topics shape", status, 0, ok, ",".join(sorted(body.keys())) if isinstance(body, dict) else "")

    def run_admin_check(self, username: str, password: str) -> None:
        status, body, elapsed = self.client.post(
            "/api/admin/login",
            {"username": username, "password": password},
            timeout=30,
        )
        self.expect_status("admin login", status, body, elapsed)

    def summary(self) -> dict[str, Any]:
        passed = sum(1 for item in self.results if item.ok)
        failed = sum(1 for item in self.results if not item.ok)
        return {
            "passed": passed,
            "failed": failed,
            "project_id_left": self.project_id,
            "results": [item.__dict__ for item in self.results],
        }


def parse_sse_events(raw: str) -> list[tuple[str, Any]]:
    events: list[tuple[str, Any]] = []
    for part in str(raw or "").split("\n\n"):
        lines = [line.strip() for line in part.splitlines() if line.strip()]
        if not lines:
            continue
        event_type = "message"
        data_lines: list[str] = []
        for line in lines:
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip() or "message"
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        if not data_lines:
            continue
        data_text = "\n".join(data_lines)
        try:
            data: Any = json.loads(data_text)
        except Exception:
            data = data_text
        events.append((event_type, data))
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Run production smoke test for 墨戏生花")
    parser.add_argument("--base-url", default=os.getenv("MOXI_SMOKE_BASE_URL", "http://127.0.0.1:6565"))
    parser.add_argument("--access-key", default=os.getenv("MOXI_TEST_ACCESS_KEY", ""))
    parser.add_argument("--write", action="store_true", help="Create/save/delete a temporary project")
    parser.add_argument("--keep-project", action="store_true", help="Keep the temporary project for manual inspection")
    parser.add_argument("--llm", action="store_true", help="Run paid/slow LLM smoke checks")
    parser.add_argument("--script-segment", action="store_true", help="Run paid/slow script segmented-writing smoke check")
    parser.add_argument("--insecure", action="store_true", help="Skip local TLS certificate verification")
    parser.add_argument("--admin-username", default=os.getenv("MOXI_ADMIN_USERNAME", ""))
    parser.add_argument("--admin-password", default=os.getenv("MOXI_ADMIN_PASSWORD", ""))
    parser.add_argument("--json-out", default="", help="Optional JSON report path")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    client = HttpClient(args.base_url, insecure=args.insecure)
    runner = SmokeRunner(client, verbose=args.verbose)
    try:
        runner.run_public_checks()
        if args.admin_username and args.admin_password:
            runner.run_admin_check(args.admin_username, args.admin_password)
        if args.access_key:
            runner.login_access_key(args.access_key)
            runner.run_user_checks()
            if args.write:
                runner.run_write_chain(keep_project=args.keep_project, script_segment=args.script_segment)
            if args.llm:
                runner.run_llm_checks()
        else:
            print("[SKIP] user checks need --access-key or MOXI_TEST_ACCESS_KEY")
    except SmokeError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as fh:
                json.dump(runner.summary(), fh, ensure_ascii=False, indent=2)
        return 1

    summary = runner.summary()
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    print(f"\nSUMMARY: {summary['passed']} passed, {summary['failed']} failed")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
