"""
电商问数 Agent 运行上下文

Context 保存图执行过程中需要复用的外部依赖。
这些对象不是业务中间结果，所以不放进 State。
"""

from typing import TypedDict

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class DataAgentContext(TypedDict):
    """LangGraph Runtime 中传递的上下文对象"""

    # 字段向量仓储
    column_qdrant_repository: ColumnQdrantRepository

    # Embedding 客户端
    embedding_client: HuggingFaceEndpointEmbeddings

    # 指标向量仓储
    metric_qdrant_repository: MetricQdrantRepository

    # 字段取值全文检索仓储
    value_es_repository: ValueESRepository

    # 元数据仓储，用于补齐字段、表、主外键
    meta_mysql_repository: MetaMySQLRepository

    # 数仓仓储，用于读取数据库方言、版本等执行环境信息
    dw_mysql_repository: DWMySQLRepository