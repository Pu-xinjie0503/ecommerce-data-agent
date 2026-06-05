import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.conf.app_config import DBConfig, app_config


class MySQLClientManager:
    def __init__(self, config: DBConfig):
        # Engine 是数据库连接层核心对象，底层维护连接池
        self.engine: AsyncEngine | None = None

        # session_factory 是 Session 工厂
        # 后面每次真正查库时，用它创建一个新的 Session
        self.session_factory = None

        # 保存数据库配置
        self.config = config

    def _get_url(self):
        # mysql+asyncmy 表示：
        # 使用 MySQL 数据库，并且底层驱动使用 asyncmy
        return (
            f"mysql+asyncmy://{self.config.user}:{self.config.password}"
            f"@{self.config.host}:{self.config.port}/{self.config.database}"
            f"?charset=utf8mb4&connect_timeout={self.config.connect_timeout_seconds}"
        )

    def init(self):
        # 创建异步 Engine
        # 可以理解成：准备好数据库连接能力
        self.engine = create_async_engine(
            self._get_url(),
            pool_size=10,
            pool_pre_ping=True,
        )

        # 基于 Engine 创建 Session 工厂
        # 后面真正查库时再创建 Session，而不是全局共用一个 Session
        self.session_factory = async_sessionmaker(
            self.engine,
            autoflush=True,
            expire_on_commit=False,
        )

    async def close(self):
        # 关闭连接池
        if self.engine:
            await self.engine.dispose()


# 一套连接元数据库 meta
meta_mysql_client_manager = MySQLClientManager(app_config.db_meta)

# 一套连接数仓模拟库 dw
dw_mysql_client_manager = MySQLClientManager(app_config.db_dw)


if __name__ == "__main__":
    # 这里先测试 dw 数仓库
    dw_mysql_client_manager.init()

    async def test():
        if dw_mysql_client_manager.session_factory is None:
            raise RuntimeError("MySQL session_factory 未初始化")

        async with dw_mysql_client_manager.session_factory() as session:
            sql = "select * from fact_order limit 10"

            result = await session.execute(text(sql))
            rows = result.mappings().fetchall()

            print(type(rows))
            print(len(rows))

            if rows:
                print(rows[0])
            else:
                print("fact_order 表存在，但没有数据")

        await dw_mysql_client_manager.close()

    asyncio.run(test())