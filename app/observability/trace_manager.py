"""Agent 结构化 Trace 管理器。"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from app.observability.trace_schema import TraceRecord, TraceStep, TraceStatus

MAX_STRING_LENGTH = 500
MAX_LIST_ITEMS = 5
MAX_RESULT_ROWS = 3
MAX_DEPTH = 3
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TraceManager:
    """记录一次 Agent 请求的结构化执行轨迹。"""

    def __init__(self, request_id: str, query: str, root_dir: str | Path | None = None):
        self.request_id = request_id
        self.query = query
        self.root_dir = Path(root_dir) if root_dir else PROJECT_ROOT / "traces"
        self.started_at = time.perf_counter()
        self.start_time = _now_iso()
        self.trace_path = self.root_dir / datetime.now().strftime("%Y-%m-%d") / f"{request_id}.json"
        self.record: TraceRecord = {
            "request_id": request_id,
            "query": query,
            "status": "running",
            "start_time": self.start_time,
            "end_time": None,
            "duration_ms": None,
            "trace_path": str(self.trace_path),
            "steps": [],
        }
        self._running_steps: dict[str, tuple[TraceStep, float]] = {}

    def start_step(self, name: str, state: dict[str, Any]) -> None:
        step: TraceStep = {
            "name": name,
            "status": "running",
            "start_time": _now_iso(),
            "end_time": None,
            "duration_ms": None,
            "input_summary": summarize_payload(state),
            "output_summary": {},
            "error_message": None,
        }
        self.record["steps"].append(step)
        self._running_steps[name] = (step, time.perf_counter())

    def end_step(
        self,
        name: str,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        step, started_at = self._running_steps.pop(name, (None, None))
        if step is None or started_at is None:
            return

        step["status"] = "failed" if error else "success"
        step["end_time"] = _now_iso()
        step["duration_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
        step["output_summary"] = summarize_payload(output or {})
        step["error_message"] = error

    def finish(self, status: TraceStatus = "success") -> None:
        self.record["status"] = status
        self.record["end_time"] = _now_iso()
        self.record["duration_ms"] = round((time.perf_counter() - self.started_at) * 1000, 2)

    def save(self) -> str:
        try:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self.root_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(self.trace_path)
            self._write_json(self.root_dir / "latest.json")
        except Exception as exc:
            logger.warning(f"Trace 写入失败: {exc}")

        return str(self.trace_path)

    def _write_json(self, path: Path) -> None:
        with path.open("w", encoding="utf-8") as file:
            json.dump(self.record, file, ensure_ascii=False, indent=2, default=str)


def summarize_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"value": safe_jsonable(payload)}

    summary: dict[str, Any] = {}
    query = payload.get("query")
    if query:
        summary["query"] = safe_jsonable(query)

    if "keywords" in payload:
        summary["keywords"] = safe_jsonable(payload.get("keywords"))

    if "retrieved_value_infos" in payload:
        values = payload.get("retrieved_value_infos") or []
        summary["retrieved_value_infos"] = summarize_items(values, ["table_name", "column_name", "value", "score"])

    if "retrieved_column_infos" in payload:
        columns = payload.get("retrieved_column_infos") or []
        summary["retrieved_column_infos"] = summarize_items(columns, ["table_name", "name", "column_name", "role"])

    if "retrieved_metric_infos" in payload:
        metrics = payload.get("retrieved_metric_infos") or []
        summary["retrieved_metric_infos"] = summarize_items(metrics, ["name", "description", "alias"])

    if "table_infos" in payload:
        tables = payload.get("table_infos") or []
        summary["table_infos"] = {
            "count": len(tables) if isinstance(tables, list) else None,
            "names": extract_names(tables),
            "items": summarize_items(tables, ["name", "role", "description"]),
        }

    if "metric_infos" in payload:
        metrics = payload.get("metric_infos") or []
        summary["metric_infos"] = {
            "count": len(metrics) if isinstance(metrics, list) else None,
            "names": extract_names(metrics),
            "items": summarize_items(metrics, ["name", "description", "alias"]),
        }

    for key in ("date_info", "db_info", "sql", "error"):
        if key in payload:
            summary[key] = safe_jsonable(payload.get(key))

    if "result" in payload:
        result = payload.get("result")
        if isinstance(result, list):
            summary["result"] = {
                "row_count": len(result),
                "preview": safe_jsonable(result[:MAX_RESULT_ROWS]),
            }
        else:
            summary["result"] = safe_jsonable(result)

    return summary


def summarize_items(items: Any, preferred_keys: list[str]) -> dict[str, Any]:
    if not isinstance(items, list):
        return {"count": None, "items": safe_jsonable(items)}

    summarized = []
    for item in items[:MAX_LIST_ITEMS]:
        item_dict = object_to_dict(item)
        if isinstance(item_dict, dict):
            picked = {
                key: safe_jsonable(item_dict[key])
                for key in preferred_keys
                if key in item_dict and item_dict[key] is not None
            }
            summarized.append(picked or safe_jsonable(item_dict, max_depth=1))
        else:
            summarized.append(safe_jsonable(item))

    return {"count": len(items), "items": summarized}


def extract_names(items: Any) -> list[Any]:
    if not isinstance(items, list):
        return []

    names = []
    for item in items[:MAX_LIST_ITEMS]:
        item_dict = object_to_dict(item)
        if isinstance(item_dict, dict):
            value = item_dict.get("name") or item_dict.get("table_name")
            if value is not None:
                names.append(safe_jsonable(value))
    return names


def safe_jsonable(value: Any, max_depth: int = MAX_DEPTH) -> Any:
    if max_depth < 0:
        return _truncate(str(value))

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate(value)
    if isinstance(value, dict):
        return {
            str(key): safe_jsonable(item, max_depth=max_depth - 1)
            for key, item in list(value.items())[:MAX_LIST_ITEMS]
        }
    if isinstance(value, (list, tuple, set)):
        return [safe_jsonable(item, max_depth=max_depth - 1) for item in list(value)[:MAX_LIST_ITEMS]]

    value_dict = object_to_dict(value)
    if isinstance(value_dict, dict):
        return safe_jsonable(value_dict, max_depth=max_depth - 1)

    return _truncate(str(value))


def object_to_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            return None
    if hasattr(value, "dict"):
        try:
            return value.dict()
        except Exception:
            return None
    if hasattr(value, "__dict__"):
        return vars(value)
    return None


def _truncate(value: str) -> str:
    if len(value) <= MAX_STRING_LENGTH:
        return value
    return value[:MAX_STRING_LENGTH] + "..."


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")
