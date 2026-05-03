from dataclasses import asdict

from app.entities.metric_info import MetricInfo
from app.repositories.mysql.meta.models.metric_info_mysql import MetricInfoMySQL


class MetricInfoMapper:
    @staticmethod
    def to_model(metric_info: MetricInfo) -> MetricInfoMySQL:
        return MetricInfoMySQL(**asdict(metric_info))