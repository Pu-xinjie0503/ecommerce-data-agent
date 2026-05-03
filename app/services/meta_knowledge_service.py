import uuid
from dataclasses import asdict
from pathlib import Path

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.conf.meta_config import MetaConfig, load_meta_config
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo
from app.entities.value_info import ValueInfo
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.mysql.meta.models.base import Base

# 必须导入所有 ORM 模型，否则 Base.metadata 可能不知道这些表
from app.repositories.mysql.meta.models.column_info_mysql import ColumnInfoMySQL
from app.repositories.mysql.meta.models.column_metric_mysql import ColumnMetricMySQL
from app.repositories.mysql.meta.models.metric_info_mysql import MetricInfoMySQL
from app.repositories.mysql.meta.models.table_info_mysql import TableInfoMySQL
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class MetaKnowledgeService:
    def __init__(self):
        self.dw_mysql_repository: DWMySQLRepository | None = None
        self.meta_mysql_repository: MetaMySQLRepository | None = None
        self.column_qdrant_repository: ColumnQdrantRepository | None = None
        self.metric_qdrant_repository: MetricQdrantRepository | None = None
        self.value_es_repository: ValueESRepository | None = None

    async def _init_meta_tables(self):
        if meta_mysql_client_manager.engine is None:
            raise RuntimeError("meta_mysql_client_manager 未初始化")

        async with meta_mysql_client_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info("Meta MySQL 表结构初始化完成")

    async def build(self, config_path: Path):
        logger.info(f"开始构建元数据知识库，配置文件：{config_path}")

        meta_config: MetaConfig = load_meta_config(config_path)

        logger.info(f"读取到表数量：{len(meta_config.tables)}")
        logger.info(f"读取到指标数量：{len(meta_config.metrics)}")

        meta_mysql_client_manager.init()
        dw_mysql_client_manager.init()
        qdrant_client_manager.init()
        embedding_client_manager.init()
        es_client_manager.init()

        try:
            await self._init_meta_tables()

            if meta_mysql_client_manager.session_factory is None:
                raise RuntimeError("meta_mysql_client_manager.session_factory 未初始化")

            if dw_mysql_client_manager.session_factory is None:
                raise RuntimeError("dw_mysql_client_manager.session_factory 未初始化")

            if qdrant_client_manager.client is None:
                raise RuntimeError("qdrant_client_manager.client 未初始化")

            if es_client_manager.client is None:
                raise RuntimeError("es_client_manager.client 未初始化")

            async with meta_mysql_client_manager.session_factory() as meta_session:
                async with dw_mysql_client_manager.session_factory() as dw_session:
                    self.meta_mysql_repository = MetaMySQLRepository(meta_session)
                    self.dw_mysql_repository = DWMySQLRepository(dw_session)
                    self.column_qdrant_repository = ColumnQdrantRepository(
                        qdrant_client_manager.client
                    )
                    self.metric_qdrant_repository = MetricQdrantRepository(
                        qdrant_client_manager.client
                    )
                    self.value_es_repository = ValueESRepository(
                        es_client_manager.client
                    )

                    column_infos: list[ColumnInfo] = []

                    if meta_config.tables:
                        column_infos = await self._save_tables_to_meta_db(meta_config)
                        logger.info(f"表与字段同步完成，字段数量：{len(column_infos)}")

                        await self._save_column_info_to_qdrant(column_infos)
                        logger.info("字段向量索引构建完成")

                        await self._save_value_info_to_es(meta_config, column_infos)
                        logger.info("字段值全文索引构建完成")

                    if meta_config.metrics:
                        metric_infos = await self._save_metrics_to_meta_db(meta_config)
                        logger.info(f"指标信息同步完成，指标数量：{len(metric_infos)}")

                        await self._save_metrics_to_qdrant(metric_infos)
                        logger.info("指标向量索引构建完成")

            logger.info("第 9 章验证完成：字段与指标检索能力构建完成")

        finally:
            await meta_mysql_client_manager.close()
            await dw_mysql_client_manager.close()
            await qdrant_client_manager.close()
            await embedding_client_manager.close()
            await es_client_manager.close()

    async def _save_tables_to_meta_db(self, meta_config: MetaConfig) -> list[ColumnInfo]:
        if self.dw_mysql_repository is None:
            raise RuntimeError("DWMySQLRepository 未初始化")

        if self.meta_mysql_repository is None:
            raise RuntimeError("MetaMySQLRepository 未初始化")

        table_infos: list[TableInfo] = []
        column_infos: list[ColumnInfo] = []

        for table in meta_config.tables:
            logger.info(f"开始处理表：{table.name}")

            table_info = TableInfo(
                id=table.name,
                name=table.name,
                role=table.role,
                description=table.description,
            )

            table_infos.append(table_info)

            column_types = await self.dw_mysql_repository.get_column_types(table.name)

            logger.info(f"表 {table.name} 的真实字段类型：{column_types}")

            for column in table.columns:
                if column.name not in column_types:
                    raise ValueError(
                        f"配置中的字段不存在于 DW 表中：table={table.name}, column={column.name}"
                    )

                column_values = await self.dw_mysql_repository.get_column_values(
                    table.name,
                    column.name,
                    10,
                )

                column_info = ColumnInfo(
                    id=f"{table.name}.{column.name}",
                    name=column.name,
                    type=column_types[column.name],
                    role=column.role,
                    examples=column_values,
                    description=column.description,
                    alias=column.alias,
                    table_id=table.name,
                )

                logger.info(
                    f"构造字段元数据：id={column_info.id}, "
                    f"type={column_info.type}, examples={column_info.examples}"
                )

                column_infos.append(column_info)

        async with self.meta_mysql_repository.session.begin():
            await self.meta_mysql_repository.save_table_infos(table_infos)
            await self.meta_mysql_repository.save_column_infos(column_infos)

        logger.info("表信息和字段信息已写入 Meta MySQL")

        return column_infos

    async def _save_column_info_to_qdrant(self, column_infos: list[ColumnInfo]):
        if self.column_qdrant_repository is None:
            raise RuntimeError("ColumnQdrantRepository 未初始化")

        await self.column_qdrant_repository.ensure_collection()

        points: list[dict] = []

        for column_info in column_infos:
            points.append(
                {
                    "id": str(uuid.uuid4()),
                    "embedding_text": column_info.name,
                    "payload": asdict(column_info),
                }
            )

            points.append(
                {
                    "id": str(uuid.uuid4()),
                    "embedding_text": column_info.description,
                    "payload": asdict(column_info),
                }
            )

            for alias in column_info.alias:
                points.append(
                    {
                        "id": str(uuid.uuid4()),
                        "embedding_text": alias,
                        "payload": asdict(column_info),
                    }
                )

        embedding_texts = [point["embedding_text"] for point in points]

        embeddings: list[list[float]] = []
        embedding_batch_size = 20

        for i in range(0, len(embedding_texts), embedding_batch_size):
            batch_texts = embedding_texts[i : i + embedding_batch_size]
            batch_embeddings = await embedding_client_manager.aembed_documents(batch_texts)
            embeddings.extend(batch_embeddings)

        ids = [point["id"] for point in points]
        payloads = [point["payload"] for point in points]

        await self.column_qdrant_repository.upsert(ids, embeddings, payloads)

        logger.info(f"字段向量写入 Qdrant 完成，point 数量：{len(points)}")

    async def _save_value_info_to_es(
        self,
        meta_config: MetaConfig,
        column_infos: list[ColumnInfo],
    ):
        if self.value_es_repository is None:
            raise RuntimeError("ValueESRepository 未初始化")

        if self.dw_mysql_repository is None:
            raise RuntimeError("DWMySQLRepository 未初始化")

        await self.value_es_repository.ensure_index()

        column2sync: dict[str, bool] = {}

        for table in meta_config.tables:
            for column in table.columns:
                column2sync[f"{table.name}.{column.name}"] = (
                    column.sync or column.sync_values
                )

        value_infos: list[ValueInfo] = []

        for column_info in column_infos:
            sync = column2sync.get(column_info.id, False)

            if not sync:
                continue

            current_values = await self.dw_mysql_repository.get_column_values(
                column_info.table_id,
                column_info.name,
                100000,
            )

            for value in current_values:
                value_text = str(value)

                value_infos.append(
                    ValueInfo(
                        id=f"{column_info.id}.{value_text}",
                        value=value_text,
                        column_id=column_info.id,
                    )
                )

        await self.value_es_repository.index(value_infos)

        logger.info(f"字段真实值写入 ES 完成，value 数量：{len(value_infos)}")

    async def _save_metrics_to_meta_db(
        self,
        meta_config: MetaConfig,
    ) -> list[MetricInfo]:
        if self.meta_mysql_repository is None:
            raise RuntimeError("MetaMySQLRepository 未初始化")

        metric_infos: list[MetricInfo] = []
        column_metrics: list[ColumnMetric] = []

        for metric in meta_config.metrics:
            related_columns = metric.related_columns or metric.relevant_columns

            metric_info = MetricInfo(
                id=metric.name,
                name=metric.name,
                description=metric.description,
                related_columns=related_columns,
                alias=metric.alias,
            )

            metric_infos.append(metric_info)

            for column_id in related_columns:
                column_metrics.append(
                    ColumnMetric(
                        column_id=column_id,
                        metric_id=metric.name,
                    )
                )

        async with self.meta_mysql_repository.session.begin():
            await self.meta_mysql_repository.save_metric_infos(metric_infos)
            await self.meta_mysql_repository.save_column_metrics(column_metrics)

        logger.info("指标信息和指标字段关系已写入 Meta MySQL")

        return metric_infos

    async def _save_metrics_to_qdrant(self, metric_infos: list[MetricInfo]):
        if self.metric_qdrant_repository is None:
            raise RuntimeError("MetricQdrantRepository 未初始化")

        await self.metric_qdrant_repository.ensure_collection()

        points: list[dict] = []

        for metric_info in metric_infos:
            points.append(
                {
                    "id": str(uuid.uuid4()),
                    "embedding_text": metric_info.name,
                    "payload": asdict(metric_info),
                }
            )

            points.append(
                {
                    "id": str(uuid.uuid4()),
                    "embedding_text": metric_info.description,
                    "payload": asdict(metric_info),
                }
            )

            for alias in metric_info.alias:
                points.append(
                    {
                        "id": str(uuid.uuid4()),
                        "embedding_text": alias,
                        "payload": asdict(metric_info),
                    }
                )

        embedding_texts = [point["embedding_text"] for point in points]

        embeddings: list[list[float]] = []
        embedding_batch_size = 20

        for i in range(0, len(embedding_texts), embedding_batch_size):
            batch_texts = embedding_texts[i : i + embedding_batch_size]
            batch_embeddings = await embedding_client_manager.aembed_documents(batch_texts)
            embeddings.extend(batch_embeddings)

        ids = [point["id"] for point in points]
        payloads = [point["payload"] for point in points]

        await self.metric_qdrant_repository.upsert(ids, embeddings, payloads)

        logger.info(f"指标向量写入 Qdrant 完成，point 数量：{len(points)}")