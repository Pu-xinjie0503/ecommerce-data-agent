from dataclasses import asdict

from app.entities.column_metric import ColumnMetric
from app.repositories.mysql.meta.models.column_metric_mysql import ColumnMetricMySQL


class ColumnMetricMapper:
    @staticmethod
    def to_model(column_metric: ColumnMetric) -> ColumnMetricMySQL:
        return ColumnMetricMySQL(**asdict(column_metric))