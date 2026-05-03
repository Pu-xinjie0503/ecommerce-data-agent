from dataclasses import dataclass


@dataclass
class MetricInfo:
    id: str
    name: str
    description: str
    related_columns: list[str]
    alias: list[str]