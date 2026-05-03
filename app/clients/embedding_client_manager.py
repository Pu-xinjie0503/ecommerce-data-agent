import asyncio
from typing import List

import httpx

from app.conf.app_config import EmbeddingConfig, app_config


class EmbeddingClientManager:
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.client: httpx.AsyncClient | None = None

    def _get_url(self):
        return f"http://{self.config.host}:{self.config.port}"

    def init(self):
        self.client = httpx.AsyncClient(
            base_url=self._get_url(),
            timeout=120,
        )

    async def close(self):
        if self.client:
            await self.client.aclose()

    async def aembed_query(self, text: str) -> List[float]:
        if self.client is None:
            raise RuntimeError("Embedding client 未初始化")

        resp = await self.client.post(
            "/embed",
            json={"inputs": text},
        )
        resp.raise_for_status()

        data = resp.json()

        # TEI 对单条文本有时返回 [float, float, ...]
        # 对多条文本返回 [[float, float, ...], ...]
        if data and isinstance(data[0], list):
            return data[0]

        return data

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        if self.client is None:
            raise RuntimeError("Embedding client 未初始化")

        resp = await self.client.post(
            "/embed",
            json={"inputs": texts},
        )
        resp.raise_for_status()

        data = resp.json()

        return data


embedding_client_manager = EmbeddingClientManager(app_config.embedding)


if __name__ == "__main__":
    embedding_client_manager.init()

    async def test():
        query_result = await embedding_client_manager.aembed_query("什么是电商销售额？")

        print(type(query_result))
        print(len(query_result))
        print(query_result[:5])

        await embedding_client_manager.close()

    asyncio.run(test())