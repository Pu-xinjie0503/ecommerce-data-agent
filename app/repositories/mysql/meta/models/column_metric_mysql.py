from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.repositories.mysql.meta.models.base import Base


class ColumnMetricMySQL(Base):
    __tablename__ = "column_metric"

    column_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    metric_id: Mapped[str] = mapped_column(String(255), primary_key=True)