#!/usr/bin/env python3
"""Validate the embedded diary data and inline JavaScript without dependencies."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = PROJECT_ROOT / "index.html"
CATEGORIES = ("schedule", "food", "activity", "health", "behavior", "family")
REQUIRED_FIELDS = {"date", *CATEGORIES}
OLD_FIELDS = {"play", "other"}
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RECORDS_PATTERN = re.compile(r"\bconst\s+records\s*=\s*(\{.*?\})\s*;", re.DOTALL)
SCRIPT_PATTERN = re.compile(r"<script(?:\s[^>]*)?>(.*?)</script>", re.DOTALL | re.IGNORECASE)


class ValidationError(Exception):
    """Raised when the diary cannot be validated safely."""


def extract_records(html: str) -> dict[str, object]:
    match = RECORDS_PATTERN.search(html)
    if not match:
        raise ValidationError("未找到 const records 数据对象")

    try:
        records = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise ValidationError(f"records 不是有效 JSON：{error}") from error

    if not isinstance(records, dict):
        raise ValidationError("records 必须是对象")
    if not records:
        raise ValidationError("records 至少需要一条记录")
    return records


def validate_records(records: dict[str, object]) -> list[str]:
    errors: list[str] = []

    for date_key, raw_record in records.items():
        if not DATE_PATTERN.fullmatch(date_key):
            errors.append(f"日期 key 格式错误：{date_key!r}")

        if not isinstance(raw_record, dict):
            errors.append(f"{date_key} 的记录必须是对象")
            continue

        actual_fields = set(raw_record)
        old_fields = actual_fields & OLD_FIELDS
        if old_fields:
            errors.append(f"{date_key} 包含旧字段：{', '.join(sorted(old_fields))}")

        missing_fields = REQUIRED_FIELDS - actual_fields
        extra_fields = actual_fields - REQUIRED_FIELDS
        if missing_fields:
            errors.append(f"{date_key} 缺少字段：{', '.join(sorted(missing_fields))}")
        if extra_fields:
            errors.append(f"{date_key} 包含多余字段：{', '.join(sorted(extra_fields))}")

        for category in CATEGORIES:
            events = raw_record.get(category)
            if not isinstance(events, list):
                errors.append(f"{date_key}.{category} 必须是数组")
                continue
            for index, event in enumerate(events):
                if not isinstance(event, str) or not event.strip():
                    errors.append(f"{date_key}.{category}[{index}] 必须是非空字符串")

    return errors


def validate_javascript(html: str, node_binary: str | None) -> None:
    scripts = SCRIPT_PATTERN.findall(html)
    if not scripts:
        raise ValidationError("index.html 中未找到 script 标签")
    if not node_binary:
        raise ValidationError("未找到 Node.js，无法检查 JavaScript 语法")

    result = subprocess.run(
        [node_binary, "--check", "-"],
        input="\n".join(scripts),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise ValidationError(f"JavaScript 语法检查失败：\n{details}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--node",
        default=shutil.which("node"),
        help="Node.js executable used for JavaScript syntax checking",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        html = INDEX_PATH.read_text(encoding="utf-8")
        records = extract_records(html)
        errors = validate_records(records)
        if errors:
            raise ValidationError("数据校验失败：\n- " + "\n- ".join(errors))
        validate_javascript(html, arguments.node)
    except (OSError, ValidationError) as error:
        print(f"VALIDATION FAILED\n{error}", file=sys.stderr)
        return 1

    print(f"VALIDATION PASSED: {len(records)} diary records, 6 categories, JavaScript syntax OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
