"""FastAPI 应用入口

负责创建后端应用实例，注册应用生命周期函数，并把各业务模块中的 router
挂载到同一个 app 上。
"""

from fastapi import FastAPI

from app.api.lifespan import lifespan
from app.api.routers.query_router import query_router
import uuid
from fastapi import Request
from app.core.context import request_id_ctx_var

app = FastAPI(lifespan=lifespan)

app.include_router(query_router)

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request_id_ctx_var.set(request_id)

    response = await call_next(request)

    return response