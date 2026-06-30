"""问数接口请求体定义

集中声明 API 层输入输出的数据结构。
当前第 15 章只需要一个 query 字段，用来承载用户输入的自然语言问题。
"""

from pydantic import BaseModel, Field
from typing import Optional

from app.security.permission_policy import PermissionContext


class QuerySchema(BaseModel):
    """POST /api/query 请求体"""

    query: str
    user_id: str = "demo_admin"
    role: str = "admin"
    tenant_id: Optional[str] = None
    allowed_region_ids: list[int] = Field(default_factory=list)
    allowed_region_names: list[str] = Field(default_factory=list)

    def to_permission_context(self) -> PermissionContext:
        """把 API 请求体转换为 Agent 运行时权限上下文。"""

        return PermissionContext(
            user_id=self.user_id,
            role=self.role,
            tenant_id=self.tenant_id,
            allowed_region_ids=self.allowed_region_ids,
            allowed_region_names=self.allowed_region_names,
        )
