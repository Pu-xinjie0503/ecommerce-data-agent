"""缓存实验控制与统计测试。"""

import asyncio

from app.agent.nodes import keyword_expansion_cache
from app.clients.embedding_client_manager import EmbeddingClientManager
from app.conf.app_config import EmbeddingConfig


class StubEmbeddingClientManager(EmbeddingClientManager):
    """避免真实 HTTP 调用的 Embedding 测试替身。"""

    def __init__(self, *, cache_enabled: bool):
        super().__init__(
            EmbeddingConfig(host="localhost", port=8081, model="test-model"),
            cache_enabled=cache_enabled,
            cache_max_size=8,
        )
        self.client = object()
        self.post_count = 0

    async def _post_embed(self, inputs):
        self.post_count += 1
        return [1.0, 2.0]


def test_embedding_cache_disabled_bypasses_read_and_write():
    """关闭缓存时重复请求必须重复访问底层服务。"""

    manager = StubEmbeddingClientManager(cache_enabled=False)

    asyncio.run(manager.aembed_query("销售额"))
    asyncio.run(manager.aembed_query("销售额"))

    assert manager.post_count == 2
    assert manager.get_cache_stats() == {
        "embedding_cache_enabled": False,
        "embedding_cache_hit": 0,
        "embedding_cache_miss": 0,
        "embedding_cache_bypass": 2,
        "embedding_cache_size": 0,
        "embedding_cache_hit_rate": 0.0,
    }


def test_embedding_cache_clear_resets_content_and_stats():
    """冷缓存实验必须同时清空内容与累计统计。"""

    manager = StubEmbeddingClientManager(cache_enabled=True)
    asyncio.run(manager.aembed_query("销售额"))
    asyncio.run(manager.aembed_query("销售额"))

    manager.clear_cache(reset_stats=True)

    assert manager.get_cache_stats()["embedding_cache_size"] == 0
    assert manager.get_cache_stats()["embedding_cache_hit"] == 0
    assert manager.get_cache_stats()["embedding_cache_miss"] == 0


def test_keyword_cache_disabled_does_not_store_entries():
    """关键词缓存关闭后写入操作应被旁路。"""

    original_enabled = keyword_expansion_cache.is_cache_enabled()
    try:
        keyword_expansion_cache.set_cache_enabled(False)
        keyword_expansion_cache.clear_cache(reset_stats=True)
        keyword_expansion_cache._set_cached_keywords("key", ["销售额"])

        stats = keyword_expansion_cache.get_cache_stats()
        assert stats["keyword_expand_cache_enabled"] is False
        assert stats["keyword_expand_cache_size"] == 0
        assert stats["keyword_expand_cache_hit_rate"] == 0.0
    finally:
        keyword_expansion_cache.set_cache_enabled(original_enabled)
        keyword_expansion_cache.clear_cache(reset_stats=True)
