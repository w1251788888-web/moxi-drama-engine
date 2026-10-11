import json
import sqlite3
from app.routers.short_drama_writing import _auto_fix_testing_script_content
from app.models.task import Task
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "01-system-core")))
from app.database import engine, SessionLocal
from app.routers.short_drama_writing import TestingScriptValidationRequest

# 模拟请求
req = TestingScriptValidationRequest(
    project_id="test_proj",
    audience_axis="女频",
    word_count_min=1150,
    word_count_max=1250,
    mode="scene",
    scene_content="这是一个测试文本。字数不够，我们需要扩写它。这是主角出场的第一句话。因为字数限制，删除了部分原定剧情。",
)

original_content = "这是一个测试文本。字数不够，我们需要扩写它。这是主角出场的第一句话。因为字数限制，删除了部分原定剧情。"
db = SessionLocal()
task = Task()

try:
    print("Testing auto-fix logic...")
    resp = _auto_fix_testing_script_content(req, original_content)
    print("Auto-fix Response:")
    print("Content:", resp.content[:100], "...")
    print("Length:", len(resp.content))
    print("Overflow:", resp.overflow_content)
    print("SUCCESS")
except Exception as e:
    print("FAILED:", e)
finally:
    db.close()
