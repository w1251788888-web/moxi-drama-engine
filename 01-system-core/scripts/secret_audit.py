#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


CORE_ROOT = Path(__file__).resolve().parents[1]
DATA_SUFFIXES = {".json", ".log", ".txt", ".md", ".yaml", ".yml"}
EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "assets",
    "dist",
    "node_modules",
    "static",
}
PLACEHOLDER_WORDS = {
    "changeme",
    "change_me",
    "demo",
    "dummy",
    "example",
    "fake",
    "placeholder",
    "test",
    "your_api_key",
    "your_api_key_here",
    "your_key",
}


@dataclass(frozen=True)
class Finding:
    type: str
    file: str
    line: int
    snippet: str


KNOWN_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[0-9A-Za-z_]{20,}\b")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
)

GENERIC_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    (?P<name>
        [A-Z0-9_.-]*
        (api[_-]?key|access[_-]?key|secret|token|password|passwd|private[_-]?key)
        [A-Z0-9_.-]*
    )
    \s*[:=]\s*
    (?P<quote>["']?)
    (?P<value>[^\s"'#,}]{12,})
    (?P=quote)
    """
)


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def is_placeholder(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    if not normalized:
        return True
    if normalized in PLACEHOLDER_WORDS:
        return True
    return any(word in normalized for word in PLACEHOLDER_WORDS)


def redact_snippet(line: str, secret: str) -> str:
    return line.strip().replace(secret, mask_secret(secret))


def _finding(secret_type: str, path: Path, line_no: int, line: str, value: str, root: Path) -> Finding:
    try:
        file_name = path.relative_to(root).as_posix()
    except ValueError:
        file_name = path.as_posix()
    return Finding(
        type=secret_type,
        file=file_name,
        line=line_no,
        snippet=redact_snippet(line, value),
    )


def scan_line(path: Path, line_no: int, line: str, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    seen_values: set[str] = set()

    for secret_type, pattern in KNOWN_SECRET_PATTERNS:
        for match in pattern.finditer(line):
            value = match.group(0)
            if value in seen_values or is_placeholder(value):
                continue
            seen_values.add(value)
            findings.append(_finding(secret_type, path, line_no, line, value, root))

    for match in GENERIC_ASSIGNMENT_PATTERN.finditer(line):
        value = match.group("value")
        if value in seen_values or is_placeholder(value):
            continue
        seen_values.add(value)
        findings.append(_finding("generic_secret_assignment", path, line_no, line, value, root))

    return findings


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_PARTS for part in path.parts)


def iter_default_scan_files(root: Path) -> Iterable[Path]:
    for name in ("config.yaml", "config.yaml.example"):
        path = root / name
        if path.is_file() and not is_excluded(path):
            yield path

    for path in root.glob(".env*"):
        if path.is_file() and not is_excluded(path):
            yield path

    data_root = root / "data"
    if data_root.is_dir():
        for path in data_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in DATA_SUFFIXES and not is_excluded(path):
                yield path


def scan_file(path: Path, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line_no, line in enumerate(handle, start=1):
                findings.extend(scan_line(path, line_no, line.rstrip("\n"), root))
    except OSError as exc:
        try:
            file_name = path.relative_to(root).as_posix()
        except ValueError:
            file_name = path.as_posix()
        print(f"warning: failed to read {file_name}: {exc}", file=sys.stderr)
    return findings


def scan(root: Path = CORE_ROOT, paths: Iterable[Path] | None = None) -> list[Finding]:
    root = root.resolve()
    scan_paths = paths if paths is not None else iter_default_scan_files(root)
    findings: list[Finding] = []
    seen_files: set[Path] = set()
    for path in scan_paths:
        resolved = path.resolve()
        if resolved in seen_files or is_excluded(resolved):
            continue
        seen_files.add(resolved)
        if resolved.is_file():
            findings.extend(scan_file(resolved, root))
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only audit for likely secrets in local config and data text artifacts."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=CORE_ROOT,
        help="01-system-core root to scan. Defaults to this script's parent project.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    findings = scan(args.root)

    if args.json:
        print(json.dumps([asdict(finding) for finding in findings], ensure_ascii=False, indent=2))
    else:
        for finding in findings:
            print(f"{finding.type} {finding.file}:{finding.line} {finding.snippet}")
        print(f"secret audit complete: {len(findings)} finding(s)")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
