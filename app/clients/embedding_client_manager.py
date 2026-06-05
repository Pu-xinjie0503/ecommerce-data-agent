import asyncio
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, List

import httpx

from app.agent.exceptions import EmbeddingServiceError, EmbeddingTimeoutError
from app.conf.app_config import EmbeddingConfig, app_config


EMBEDDING_CACHE_MAX_SIZE = 4096


@dataclass
class EmbeddingCacheStats:
    """Embedding 缓存统计。"""

    embedding_cache_hit: int = 0
    embedding_cache_miss: int = 0

    def to_dict(self, cache_size: int | None = None) -> dict[str, int]:
        data = {
            "embedding_cache_hit": self.embedding_cache_hit,
            "embedding_cache_miss": self.embedding_cache_miss,
        }
        if cache_size is not None:
            data["embedding_cache_size"] = cache_size
        return data


_embedding_step_stats: ContextVar[EmbeddingCacheStats | None] = ContextVar(
    "embedding_step_stats",
    default=None,
)


def normalize_embedding_text(text: str) -> str:
    """归一化 embedding 文本，仅去首尾空白并合并连续空白。"""

    return " ".join(str(text).strip().split())


class EmbeddingClientManager:
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.client: httpx.AsyncClient | None = None
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._stats = EmbeddingCacheStats()

    def _get_url(self):
        return f"http://{self.config.host}:{self.config.port}"

    def _cache_key(self, text: str) -> str:
        normalized_text = normalize_embedding_text(text)
        return f"embedding:{self.config.model}:{normalized_text}"

    def _get_cached_embedding(self, cache_key: str) -> list[float] | None:
        cached = self._cache.get(cache_key)
        if cached is None:
            return None
        self._cache.move_to_end(cache_key)
        return cached

    def _set_cached_embedding(self, cache_key: str, embedding: list[float]) -> None:
        self._cache[cache_key] = list(embedding)
        self._cache.move_to_end(cache_key)
        if len(self._cache) > EMBEDDING_CACHE_MAX_SIZE:
            self._cache.popitem(last=False)

    def _record_hit(self) -> None:
        self._stats.embedding_cache_hit += 1
        step_stats = _embedding_step_stats.get()
        if step_stats is not None:
            step_stats.embedding_cache_hit += 1

    def _record_miss(self) -> None:
        self._stats.embedding_cache_miss += 1
        step_stats = _embedding_step_stats.get()
        if step_stats is not None:
            step_stats.embedding_cache_miss += 1

    @contextmanager
    def trace_cache_stats(self) -> Iterator[EmbeddingCacheStats]:
        """为当前 Trace step 收集 embedding 缓存统计。"""

        stats = EmbeddingCacheStats()
        token = _embedding_step_stats.set(stats)
        try:
            yield stats
        finally:
            _embedding_step_stats.reset(token)

    def get_cache_stats(self) -> dict[str, int]:
        """返回 embedding 缓存累计统计。"""

        return self._stats.to_dict(cache_size=len(self._cache))

    def reset_cache_stats(self) -> None:
        """重置 embedding 缓存命中统计，不清空缓存内容。"""

        self._stats = EmbeddingCacheStats()

    def clear_cache(self) -> None:
        """清空 embedding 缓存内容。"""

        self._cache.clear()

    def init(self):
        self.client = httpx.AsyncClient(
            base_url=self._get_url(),
            timeout=self.config.timeout_seconds,
        )

    async def close(self):
        if self.client:
            await self.client.aclose()

    async def _post_embed(self, inputs: str | list[str]) -> Any:
        if self.client is None:
            raise RuntimeError("Embedding client 未初始化")
        try:
            resp = await self.client.post(
                "/embed",
                json={"inputs": inputs},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException as exc:
            raise EmbeddingTimeoutError(f"Embedding 请求超过 {self.config.timeout_seconds} 秒") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingServiceError(str(exc)) from exc

    async def aembed_query(self, text: str) -> List[float]:
        if self.client is None:
            raise RuntimeError("Embedding client 未初始化")

        cache_key = self._cache_key(text)
        cached = self._get_cached_embedding(cache_key)
        if cached is not None:
            self._record_hit()
            return list(cached)

        self._record_miss()
        data = await self._post_embed(text)

        # TEI 对单条文本有时返回 [float, float, ...]
        # 对多条文本返回 [[float, float, ...], ...]
        if data and isinstance(data[0], list):
            embedding = data[0]
        else:
            embedding = data

        self._set_cached_embedding(cache_key, list(embedding))
        return embedding

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        if self.client is None:
            raise RuntimeError("Embedding client 未初始化")
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        miss_texts: list[str] = []
        miss_indices_by_key: dict[str, list[int]] = {}

        for index, text in enumerate(texts):
            cache_key = self._cache_key(text)
            cached = self._get_cached_embedding(cache_key)
            if cached is not None:
                self._record_hit()
                results[index] = list(cached)
                continue

            self._record_miss()
            if cache_key not in miss_indices_by_key:
                miss_texts.append(text)
                miss_indices_by_key[cache_key] = []
            miss_indices_by_key[cache_key].append(index)

        if miss_texts:
            data = await self._post_embed(miss_texts)
            embeddings = self._normalize_document_embeddings(data, len(miss_texts))

            for text, embedding in zip(miss_texts, embeddings):
                cache_key = self._cache_key(text)
                cached_embedding = list(embedding)
                self._set_cached_embedding(cache_key, cached_embedding)
                for index in miss_indices_by_key[cache_key]:
                    results[index] = list(cached_embedding)

        if any(item is None for item in results):
            raise RuntimeError("Embedding 批量结果数量与输入文本不一致")

        return [item for item in results if item is not None]

    def _normalize_document_embeddings(self, data: Any, expected_count: int) -> list[list[float]]:
        """把 TEI 批量 embedding 响应统一为二维列表。"""

        if expected_count == 1 and data and not isinstance(data[0], list):
            return [data]
        if not isinstance(data, list) or len(data) != expected_count:
            raise RuntimeError(
                f"Embedding 批量结果数量与输入文本不一致: expected={expected_count}, actual={len(data) if isinstance(data, list) else 'unknown'}"
            )
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
