from dataclasses import asdict

from app.entities.table_info import TableInfo
from app.repositories.mysql.meta.models.table_info_mysql import TableInfoMySQL


class TableInfoMapper:
    @staticmethod
    def to_model(table_info: TableInfo) -> TableInfoMySQL:
        return TableInfoMySQL(**asdict(table_info))