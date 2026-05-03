from dataclasses import asdict

from app.entities.column_info import ColumnInfo
from app.repositories.mysql.meta.models.column_info_mysql import ColumnInfoMySQL


class ColumnInfoMapper:
    @staticmethod
    def to_model(column_info: ColumnInfo) -> ColumnInfoMySQL:
        return ColumnInfoMySQL(**asdict(column_info))