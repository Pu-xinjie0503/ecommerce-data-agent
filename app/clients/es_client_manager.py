import asyncio
from typing import Optional

from elasticsearch import AsyncElasticsearch

from app.conf.app_config import ESConfig, app_config


class ESClientManager:
    def __init__(self, es_config: ESConfig):
        self.es_config = es_config
        self.client: Optional[AsyncElasticsearch] = None

    def _get_url(self):
        return f"http://{self.es_config.host}:{self.es_config.port}"

    def init(self):
        self.client = AsyncElasticsearch(
            hosts=[self._get_url()],
            request_timeout=self.es_config.timeout_seconds,
        )

    async def close(self):
        if self.client:
            await self.client.close()


es_client_manager = ESClientManager(app_config.es)


if __name__ == "__main__":
    es_client_manager.init()

    async def test():
        client = es_client_manager.client

        if client is None:
            raise RuntimeError("ES client 未初始化")

        index_name = "my-books"

        if await client.indices.exists(index=index_name):
            await client.indices.delete(index=index_name)

        await client.indices.create(
            index=index_name,
            mappings={
                "dynamic": False,
                "properties": {
                    "name": {"type": "text"},
                    "author": {"type": "text"},
                    "release_date": {"type": "date", "format": "yyyy-MM-dd"},
                    "page_count": {"type": "integer"},
                },
            },
        )

        await client.bulk(
            operations=[
                {"index": {"_index": index_name}},
                {
                    "name": "Revelation Space",
                    "author": "Alastair Reynolds",
                    "release_date": "2000-03-15",
                    "page_count": 585,
                },
                {"index": {"_index": index_name}},
                {
                    "name": "1984",
                    "author": "George Orwell",
                    "release_date": "1985-06-01",
                    "page_count": 328,
                },
                {"index": {"_index": index_name}},
                {
                    "name": "Fahrenheit 451",
                    "author": "Ray Bradbury",
                    "release_date": "1953-10-15",
                    "page_count": 227,
                },
                {"index": {"_index": index_name}},
                {
                    "name": "Brave New World",
                    "author": "Aldous Huxley",
                    "release_date": "1932-06-01",
                    "page_count": 268,
                },
            ],
            refresh=True,
        )

        resp = await client.search(
            index=index_name,
            query={"match": {"name": "brave"}},
        )

        print(resp)

        await es_client_manager.close()

    asyncio.run(test())
