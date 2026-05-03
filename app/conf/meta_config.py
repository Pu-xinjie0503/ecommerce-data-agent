from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from omegaconf import OmegaConf


@dataclass
class ColumnConfig:
    name: str
    role: str
    description: str
    alias: List[str] = field(default_factory=list)
    sync: bool = False
    sync_values: bool = False


@dataclass
class TableConfig:
    name: str
    role: str
    description: str
    columns: List[ColumnConfig] = field(default_factory=list)


@dataclass
class MetricConfig:
    name: str
    description: str
    alias: List[str] = field(default_factory=list)
    related_columns: List[str] = field(default_factory=list)
    relevant_columns: List[str] = field(default_factory=list)


@dataclass
class MetaConfig:
    tables: List[TableConfig] = field(default_factory=list)
    metrics: List[MetricConfig] = field(default_factory=list)


def load_meta_config(config_path: Path) -> MetaConfig:
    context = OmegaConf.load(config_path)
    schema = OmegaConf.structured(MetaConfig)
    return OmegaConf.to_object(OmegaConf.merge(schema, context))


if __name__ == "__main__":
    config = load_meta_config(Path("conf/meta_config.yaml"))

    print(type(config))
    print("tables:", len(config.tables))
    print("metrics:", len(config.metrics))

    if config.tables:
        print("first table:", config.tables[0].name)
        print("columns:", [column.name for column in config.tables[0].columns])

    if config.metrics:
        print("first metric:", config.metrics[0].name)