from __future__ import annotations

import json
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Literal

from app.conf.app_config import app_config

RecallType = Literal["column", "metric", "value"]


KEYWORD_EXPANSION_CACHE_MAX_SIZE = 1024


@dataclass
class KeywordExpansionCacheStats:
    """关键词扩展缓存统计。"""

    keyword_expand_cache_hit_column: int = 0
    keyword_expand_cache_miss_column: int = 0
    keyword_expand_cache_hit_metric: int = 0
    keyword_expand_cache_miss_metric: int = 0
    keyword_expand_cache_hit_value: int = 0
    keyword_expand_cache_miss_value: int = 0
    keyword_expand_cache_bypass: int = 0

    def to_dict(
        self,
        cache_size: int | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        hits = (
            self.keyword_expand_cache_hit_column
            + self.keyword_expand_cache_hit_metric
            + self.keyword_expand_cache_hit_value
        )
        misses = (
            self.keyword_expand_cache_miss_column
            + self.keyword_expand_cache_miss_metric
            + self.keyword_expand_cache_miss_value
        )
        data = {
            "keyword_expand_cache_enabled": enabled,
            "keyword_expand_cache_hit_column": self.keyword_expand_cache_hit_column,
            "keyword_expand_cache_miss_column": self.keyword_expand_cache_miss_column,
            "keyword_expand_cache_hit_metric": self.keyword_expand_cache_hit_metric,
            "keyword_expand_cache_miss_metric": self.keyword_expand_cache_miss_metric,
            "keyword_expand_cache_hit_value": self.keyword_expand_cache_hit_value,
            "keyword_expand_cache_miss_value": self.keyword_expand_cache_miss_value,
            "keyword_expand_cache_bypass": self.keyword_expand_cache_bypass,
            "keyword_expand_cache_hit_rate": (
                round(hits / (hits + misses) * 100, 2) if hits + misses else 0.0
            ),
        }
        if cache_size is not None:
            data["keyword_expand_cache_size"] = cache_size
        return data


_cache: OrderedDict[str, list[str]] = OrderedDict()
_stats = KeywordExpansionCacheStats()
_cache_enabled = app_config.cache.keyword_expansion_enabled
_cache_max_size = app_config.cache.keyword_expansion_max_size
_keyword_step_stats: ContextVar[KeywordExpansionCacheStats | None] = ContextVar(
    "keyword_step_stats",
    default=None,
)


def normalize_keyword_text(text: str) -> str:
    """归一化关键词缓存 key 文本，仅去首尾空白并合并连续空白。"""

    return " ".join(str(text).strip().split())


def build_keyword_expand_cache_key(
    recall_type: RecallType,
    query: str,
    keywords: list[str],
) -> str:
    normalized_query = normalize_keyword_text(query)
    normalized_keywords = [normalize_keyword_text(keyword) for keyword in keywords]
    keywords_part = json.dumps(normalized_keywords, ensure_ascii=False, separators=(",", ":"))
    return f"keyword_expand:{recall_type}:{normalized_query}:{keywords_part}"


@contextmanager
def trace_keyword_cache_stats() -> Iterator[KeywordExpansionCacheStats]:
    """为当前 Trace step 收集关键词扩展缓存统计。"""

    stats = KeywordExpansionCacheStats()
    token = _keyword_step_stats.set(stats)
    try:
        yield stats
    finally:
        _keyword_step_stats.reset(token)


def get_cache_stats() -> dict[str, Any]:
    """返回关键词扩展缓存累计统计。"""

    return _stats.to_dict(cache_size=len(_cache), enabled=_cache_enabled)


def reset_cache_stats() -> None:
    """重置关键词扩展缓存命中统计，不清空缓存内容。"""

    global _stats
    _stats = KeywordExpansionCacheStats()


def clear_cache(*, reset_stats: bool = False) -> None:
    """清空关键词扩展缓存内容，并可同时重置累计统计。"""

    _cache.clear()
    if reset_stats:
        reset_cache_stats()


def set_cache_enabled(enabled: bool) -> None:
    """切换关键词扩展缓存读写。"""

    global _cache_enabled
    _cache_enabled = bool(enabled)


def is_cache_enabled() -> bool:
    """返回关键词扩展缓存是否启用。"""

    return _cache_enabled


def _get_cached_keywords(cache_key: str) -> list[str] | None:
    if not _cache_enabled:
        return None
    cached = _cache.get(cache_key)
    if cached is None:
        return None
    _cache.move_to_end(cache_key)
    return cached


def _set_cached_keywords(cache_key: str, expanded_keywords: list[str]) -> None:
    if not _cache_enabled:
        return
    _cache[cache_key] = list(expanded_keywords)
    _cache.move_to_end(cache_key)
    if len(_cache) > _cache_max_size:
        _cache.popitem(last=False)


async def expand_keywords_with_cache(
    *,
    recall_type: RecallType,
    prompt_name: str,
    query: str,
    keywords: list[str],
):
    """带进程内缓存的关键词扩展，保持原 LLM 扩展结果结构不变。"""

    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.prompts import PromptTemplate

    from app.agent.llm import ainvoke_llm_chain, llm
    from app.prompt.prompt_loader import load_prompt

    cache_key = build_keyword_expand_cache_key(recall_type, query, keywords)
    if _cache_enabled:
        cached = _get_cached_keywords(cache_key)
        if cached is not None:
            _record_hit(recall_type)
            return list(cached)
        _record_miss(recall_type)
    else:
        _record_bypass()
    prompt = PromptTemplate(
        template=load_prompt(prompt_name),
        input_variables=["query"],
    )
    output_parser = JsonOutputParser()
    chain = prompt | llm | output_parser
    llm_result = await ainvoke_llm_chain(chain, {"query": query})
    expanded_keywords = llm_result.value

    if isinstance(expanded_keywords, list):
        _set_cached_keywords(cache_key, expanded_keywords)

    return expanded_keywords


def _record_hit(recall_type: RecallType) -> None:
    _increment(recall_type, hit=True, stats=_stats)
    step_stats = _keyword_step_stats.get()
    if step_stats is not None:
        _increment(recall_type, hit=True, stats=step_stats)


def _record_miss(recall_type: RecallType) -> None:
    _increment(recall_type, hit=False, stats=_stats)
    step_stats = _keyword_step_stats.get()
    if step_stats is not None:
        _increment(recall_type, hit=False, stats=step_stats)


def _record_bypass() -> None:
    _stats.keyword_expand_cache_bypass += 1
    step_stats = _keyword_step_stats.get()
    if step_stats is not None:
        step_stats.keyword_expand_cache_bypass += 1


def _increment(recall_type: RecallType, *, hit: bool, stats: KeywordExpansionCacheStats) -> None:
    suffix = "hit" if hit else "miss"
    field_name = f"keyword_expand_cache_{suffix}_{recall_type}"
    setattr(stats, field_name, getattr(stats, field_name) + 1)
