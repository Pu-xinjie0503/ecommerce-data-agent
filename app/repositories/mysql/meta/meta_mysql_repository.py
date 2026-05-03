from sqlalchemy.ext.asyncio import AsyncSession

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