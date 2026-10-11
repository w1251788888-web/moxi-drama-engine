"""后台敏感配置加密服务。"""
from __future__ import annotations

import hashlib
import base64

from app.config import config


def _key_stream(length: int) -> bytes:
    seed = f"{config.project_name}:{config.raw.get('admin', {}).get('password', '')}"
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < length:
        chunks.append(hashlib.sha256(f"{seed}:{counter}".encode("utf-8")).digest())
        counter += 1
    return b"".join(chunks)[:length]


def _xor(data: bytes) -> bytes:
    stream = _key_stream(len(data))
    return bytes(byte ^ stream[index] for index, byte in enumerate(data))


def encrypt_secret(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    encoded = base64.urlsafe_b64encode(_xor(raw.encode("utf-8"))).decode("utf-8")
    return "moxi1:" + encoded


def decrypt_secret(value: str) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    if not raw.startswith("moxi1:"):
        return raw
    try:
        data = base64.urlsafe_b64decode(raw[6:].encode("utf-8"))
        return _xor(data).decode("utf-8")
    except Exception:
        return ""


def mask_secret(value: str) -> str:
    secret = decrypt_secret(value)
    if not secret:
        return ""
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}...{secret[-4:]}"
