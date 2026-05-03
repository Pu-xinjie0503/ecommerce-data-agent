import asyncio
from argparse import ArgumentParser
from pathlib import Path

from app.core.log import logger
from app.services.meta_knowledge_service import MetaKnowledgeService


async def build(config_path: Path):
    service = MetaKnowledgeService()
    await service.build(config_path)


if __name__ == "__main__":
    parser = ArgumentParser(description="构建元数据知识库")

    parser.add_argument(
        "-c",
        "--conf",
        required=True,
        help="meta_config.yaml 配置文件路径",
    )

    args = parser.parse_args()

    config_path = Path(args.conf)

    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在：{config_path}")

    logger.info(f"元数据知识库构建脚本启动，config_path={config_path}")

    asyncio.run(build(config_path))