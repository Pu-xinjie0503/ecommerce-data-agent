from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DWMySQLRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        # 简单保护一下表名、字段名，防止反引号破坏 SQL
        if "`" in identifier:
            raise ValueError(f"非法标识符：{identifier}")
        return f"`{identifier}`"

    @staticmethod
    def _to_json_safe(value: Any):
        # MySQL JSON 不认识 Decimal / datetime，所以这里统一转成可序列化值
        if isinstance(value, Decimal):
            return float(value)

        if isinstance(value, (datetime, date)):
            return value.isoformat(sep=" ")

        return value
    
    async def validate(self, sql: str):
        """用 EXPLAIN 校验 SQL 是否能被数据库解析"""

        validate_sql = f"explain {sql}"

        try:
            await self.session.execute(text("SET SESSION sql_notes = 0"))
            await self.session.execute(text(validate_sql))
        finally:
            await self.session.execute(text("SET SESSION sql_notes = 1"))


    async def run(self, sql: str) -> list[dict]:
        """执行 SQL，并返回字典列表结果"""

        result = await self.session.execute(text(sql))
        return [dict(row) for row in result.mappings().fetchall()]

    async def get_column_types(self, table_name: str) -> dict[str, str]:
        table = self._quote_identifier(table_name)

        sql = f"SHOW COLUMNS FROM {table}"

        result = await self.session.execute(text(sql))
        rows = result.mappings().all()

        return {row["Field"]: row["Type"] for row in rows}

    async def get_column_values(self, table_name: str, column_name: str, limit: int):
        table = self._quote_identifier(table_name)
        column = self._quote_identifier(column_name)

        sql = f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL LIMIT {limit}"

        result = await self.session.execute(text(sql))
        values = result.scalars().all()

        return [self._to_json_safe(value) for value in values]
    
    async def get_db_info(self):
        """读取当前数仓数据库的方言和版本，供 SQL 生成提示词使用"""

        sql = "select version()"
        result = await self.session.execute(text(sql))
        version = result.scalar()

        dialect = self.session.bind.dialect.name

        return {
            "dialect": dialect,
            "version": version,
        }