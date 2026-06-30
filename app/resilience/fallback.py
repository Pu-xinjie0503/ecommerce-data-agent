"""召回链路降级输出工具。"""


def build_recall_fallback(
    result_key: str,
    warning_key: str,
    dependency_name: str,
    reason: str,
) -> dict:
    """构造召回弱依赖失败后的非阻断输出。"""

    return {
        result_key: [],
        warning_key: f"{dependency_name} 不可用，已降级跳过该路召回：{reason}",
    }

