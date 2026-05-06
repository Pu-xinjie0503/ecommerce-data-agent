"""问数接口请求体定义

集中声明 API 层输入输出的数据结构。
当前第 15 章只需要一个 query 字段，用来承载用户输入的自然语言问题。
"""

from pydantic import BaseModel


class QuerySchema(BaseModel):
    """POST /api/query 请求体"""

    query: str