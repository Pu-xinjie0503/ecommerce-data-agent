"""
Prompt 模板加载工具
"""

from pathlib import Path


def load_prompt(name: str) -> str:
    """读取 prompts 目录下的 .prompt 文件"""

    prompt_path = Path(__file__).parents[2] / "prompts" / f"{name}.prompt"
    return prompt_path.read_text(encoding="utf-8")