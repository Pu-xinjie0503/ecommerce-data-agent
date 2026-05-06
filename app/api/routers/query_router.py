"""问数查询接口路由

第 15 章先不接入真实 LangGraph Agent。
这里只用 fake_streamer 模拟智能体执行过程，验证 FastAPI + SSE 流式响应是否可用。
"""

import asyncio

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from app.api.schemas.query_schema import QuerySchema


query_router = APIRouter()


async def fake_streamer():
    """模拟智能体逐步返回执行进度的异步生成器"""

    for i in range(10):
        # 暂停 1 秒只是为了方便观察流式效果
        await asyncio.sleep(1)

        # SSE 消息格式：
        # data: 内容\n\n
        yield f"data: step:{i}\n\n"


@query_router.post("/api/query")
async def query_handler(query: QuerySchema):
    """接收用户自然语言问题，并以 SSE 形式持续返回处理进度"""

    return StreamingResponse(
        fake_streamer(),
        media_type="text/event-stream",
    )