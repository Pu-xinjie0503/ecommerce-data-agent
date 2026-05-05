"""
关键词抽取节点

负责从用户自然语言问题中抽取检索关键词。
后续字段召回、指标召回、字段取值召回都会基于这些关键词展开。
"""

import jieba.analyse
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger


async def extract_keywords(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    """抽取用户问题中的关键词"""

    step = "抽取关键词"
    writer = runtime.stream_writer
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        query = state["query"]

        # 只保留更可能承载业务含义的词性
        allow_pos = (
            "n",    # 名词：商品、订单、销售额
            "nr",   # 人名
            "ns",   # 地名：华北、上海、北京
            "nt",   # 机构团体名：门店、品牌、渠道
            "nz",   # 专有名词：SKU、GMV、AOV
            "v",    # 动词：统计、查询、对比
            "vn",   # 名动词：销售、成交、退款
            "a",    # 形容词：新增、有效、活跃
            "an",   # 名形词
            "eng",  # 英文：GMV、SKU、ROI
            "i",    # 成语或习用语
            "l",    # 固定短语
        )

        keywords = jieba.analyse.extract_tags(
            query,
            allowPOS=allow_pos,
        )

        # 加上原始问题作为兜底，避免分词不准导致完整语义丢失
        keywords = list(set(keywords + [query]))

        writer({"type": "progress", "step": step, "status": "success"})
        logger.info(f"抽取关键词成功: {keywords}")

        return {"keywords": keywords}

    except Exception as e:
        writer({"type": "progress", "step": step, "status": "error"})
        logger.error(f"抽取关键词失败: {e}")
        raise