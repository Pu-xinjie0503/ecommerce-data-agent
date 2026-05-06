"""FastAPI 应用入口

负责创建后端应用实例，并把各业务模块中的 router 挂载到同一个 app 上。
第 15 章先只注册问数查询接口。
"""

from fastapi import FastAPI

from app.api.routers.query_router import query_router


app = FastAPI()

app.include_router(query_router)