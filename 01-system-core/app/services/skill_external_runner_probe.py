from __future__ import annotations

import json
import sys
from typing import Any


def main() -> int:
    """Minimal fixed-command runner used by the Skill executor gate."""
    raw = sys.stdin.read()
    try:
        payload: dict[str, Any] = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": f"invalid json: {exc}"}, ensure_ascii=False))
        return 2

    parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
    result = {
        "ok": True,
        "runner_name": payload.get("runner_name", ""),
        "skill_name": payload.get("skill_name", ""),
        "request_invocation_id": payload.get("request_invocation_id", ""),
        "parameter_keys": sorted(str(key) for key in parameters),
        "payload_chars": len(raw),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
