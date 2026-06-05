import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause

from app.agent.exceptions import MySQLExecutionError, MySQLTimeoutError
from app.conf.app_config import app_config

from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo
from app.repositories.mysql.meta.mappers.column_info_mapper import ColumnInfoMapper
from app.repositories.mysql.meta.mappers.column_metric_mapper import ColumnMetricMapper
from app.repositories.mysql.meta.mappers.metric_info_mapper import MetricInfoMapper
from app.repositories.mysql.meta.mappers.table_info_mapper import TableInfoMapper


class MetaMySQLRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _execute_with_timeout(self, statement: TextClause, params: dict | None = None):
        try:
            return await asyncio.wait_for(
                self.session.execute(statement, params or {}),
                timeout=app_config.db_meta.query_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise MySQLTimeoutError(
                f"Meta MySQL 查询超过 {app_config.db_meta.query_timeout_seconds} 秒"
            ) from exc
        except Exception as exc:
            raise MySQLExecutionError(str(exc)) from exc

    async def save_table_infos(self, table_infos: list[TableInfo]):
        for table_info in table_infos:
            model = TableInfoMapper.to_model(table_info)
            await self.session.merge(model)

    async def save_column_infos(self, column_infos: list[ColumnInfo]):
        for column_info in column_infos:
            model = ColumnInfoMapper.to_model(column_info)
            await self.session.merge(model)

    async def save_metric_infos(self, metric_infos: list[MetricInfo]):
        for metric_info in metric_infos:
            model = MetricInfoMapper.to_model(metric_info)
            await self.session.merge(model)

    async def save_column_metrics(self, column_metrics: list[ColumnMetric]):
        for column_metric in column_metrics:
            model = ColumnMetricMapper.to_model(column_metric)
            await self.session.merge(model)

    async def get_column_info_by_id(self, column_id: str) -> ColumnInfo | None:
        """根据字段 ID 查询字段元信息"""

        sql = """
        select *
        from column_info
        where id = :column_id
        """

        result = await self._execute_with_timeout(
            text(sql),
            {"column_id": column_id},
        )

        row = result.mappings().first()

        if row is None:
            return None

        return ColumnInfo(**dict(row))

    async def get_table_info_by_id(self, table_id: str) -> TableInfo | None:
        """根据表 ID 查询表元信息"""

        sql = """
        select *
        from table_info
        where id = :table_id
        """

        result = await self._execute_with_timeout(
            text(sql),
            {"table_id": table_id},
        )

        row = result.mappings().first()

        if row is None:
            return None

        return TableInfo(**dict(row))

    async def get_key_columns_by_table_id(self, table_id: str) -> list[ColumnInfo]:
        """查询指定表的主键和外键字段"""

        sql = """
        select *
        from column_info
        where table_id = :table_id
          and role in ('primary_key', 'foreign_key')
        """

        result = await self._execute_with_timeout(
            text(sql),
            {"table_id": table_id},
        )

        return [
            ColumnInfo(**dict(row))
            for row in result.mappings().fetchall()
        ]