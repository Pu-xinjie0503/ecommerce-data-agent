"""FastAPI 应用入口

负责创建后端应用实例，注册应用生命周期函数，并把各业务模块中的 router
挂载到同一个 app 上。
"""

from fastapi import FastAPI

from app.api.lifespan import lifespan
from app.api.routers.query_router import query_router


app = FastAPI(lifespan=lifespan)

app.include_router(query_router)