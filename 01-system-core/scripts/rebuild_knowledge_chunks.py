#!/usr/bin/env python3
"""Rebuild durable knowledge chunks from the unified search document source."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import knowledge_chunk  # noqa: F401,E402
from app.services.knowledge_chunk_service import rebuild_knowledge_chunks  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild knowledge_chunks table")
    parser.add_argument("--types", default="", help="Comma-separated doc types: rule,material,project,skill")
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--chunk-overlap", type=int, default=120)
    args = parser.parse_args()

    doc_types = [item.strip() for item in args.types.split(",") if item.strip()]
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        result = rebuild_knowledge_chunks(
            db,
            doc_types=doc_types,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
