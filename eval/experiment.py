"""实验元数据、哈希与可比性校验。"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any, Iterable


COMPARABLE_FIELDS = (
    "model",
    "temperature",
    "dataset_sha256",
    "prompt_sha256",
)


class ExperimentCompatibilityError(ValueError):
    """两次运行的关键实验条件不一致。"""


def file_sha256(path: str | Path) -> str:
    """计算单个文件的 SHA-256。"""

    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def paths_sha256(paths: Iterable[str | Path]) -> str:
    """按路径名和文件内容计算一组文件的稳定 SHA-256。"""

    digest = hashlib.sha256()
    for path in sorted((Path(item) for item in paths), key=lambda item: item.as_posix()):
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(file_sha256(path).encode("ascii"))
    return digest.hexdigest()


def validate_comparable(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    required_fields: Iterable[str] = COMPARABLE_FIELDS,
) -> None:
    """校验两次运行是否满足计算提升比例的前提。"""

    mismatches = [
        field
        for field in required_fields
        if baseline.get(field) != candidate.get(field)
    ]
    if mismatches:
        details = ", ".join(
            f"{field}: {baseline.get(field)!r} != {candidate.get(field)!r}"
            for field in mismatches
        )
        raise ExperimentCompatibilityError(f"实验条件不可比：{details}")


def git_revision(project_root: str | Path) -> str | None:
    """读取当前代码版本，失败时返回空值而不中断评测。"""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(project_root),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None
