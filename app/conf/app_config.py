from dataclasses import dataclass
from pathlib import Path

from omegaconf import OmegaConf
from dotenv import load_dotenv

@dataclass
class File:
    enable: bool
    level: str
    path: str
    rotation: str
    retention: str


@dataclass
class Console:
    enable: bool
    level: str


@dataclass
class LoggingConfig:
    file: File
    console: Console


@dataclass
class DBConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    connect_timeout_seconds: int = 10
    query_timeout_seconds: int = 10


@dataclass
class QdrantConfig:
    host: str
    port: int
    embedding_size: int
    timeout_seconds: int = 5


@dataclass
class EmbeddingConfig:
    host: str
    port: int
    model: str
    timeout_seconds: int = 10


@dataclass
class ESConfig:
    host: str
    port: int
    index_name: str
    timeout_seconds: int = 5


@dataclass
class LLMConfig:
    model_name: str
    api_key: str
    base_url: str
    timeout_seconds: int = 30
    max_concurrency: int = 3
    slot_timeout_seconds: int = 30


@dataclass
class AppConfig:
    logging: LoggingConfig
    db_meta: DBConfig
    db_dw: DBConfig
    qdrant: QdrantConfig
    embedding: EmbeddingConfig
    es: ESConfig
    llm: LLMConfig


project_root = Path(__file__).parents[2]

config_file = project_root / "conf" / "app_config.yaml"

load_dotenv(project_root / ".env")

context = OmegaConf.load(config_file)
schema = OmegaConf.structured(AppConfig)

app_config: AppConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))


if __name__ == "__main__":
    print(app_config.es.host)
    print(app_config.qdrant.host)
    print(app_config.db_meta.database)