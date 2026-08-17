"""实验元数据与可比性测试。"""

from pathlib import Path

import pytest

from eval.experiment import ExperimentCompatibilityError, file_sha256, validate_comparable


def test_file_sha256_is_stable():
    """相同文件内容必须得到稳定哈希。"""

    case_file = Path(__file__)

    assert file_sha256(case_file) == file_sha256(case_file)
    assert len(file_sha256(case_file)) == 64


def test_validate_comparable_allows_cache_mode_difference():
    """缓存消融允许 cache_mode 和 run_id 不同。"""

    baseline = _metadata(cache_mode="disabled", run_id="run-a")
    candidate = _metadata(cache_mode="warm", run_id="run-b")

    validate_comparable(baseline, candidate)


@pytest.mark.parametrize("field", ["model", "temperature", "dataset_sha256", "prompt_sha256"])
def test_validate_comparable_rejects_confounded_runs(field: str):
    """关键实验条件不同不得计算提升。"""

    baseline = _metadata()
    candidate = _metadata()
    candidate[field] = "different"

    with pytest.raises(ExperimentCompatibilityError, match=field):
        validate_comparable(baseline, candidate)


def _metadata(**overrides):
    metadata = {
        "run_id": "run-a",
        "model": "deepseek-chat",
        "temperature": 0,
        "dataset_sha256": "cases-hash",
        "prompt_sha256": "prompt-hash",
        "cache_mode": "disabled",
        "code_revision": "abc123",
    }
    metadata.update(overrides)
    return metadata
