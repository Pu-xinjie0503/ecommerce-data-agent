from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState, MetricInfoState
from app.core.log import logger


SALES_METRIC_KEYWORDS = ["销售额", "GMV", "成交金额", "成交额", "交易额", "销售总额", "总销售额"]
AOV_METRIC_KEYWORDS = ["客单价", "平均订单金额", "AOV"]
ORDER_COUNT_KEYWORDS = ["订单数", "订单量"]


def query_contains_any(query: str, keywords: list[str]) -> bool:
    query_lower = query.lower()
    return any(keyword.lower() in query_lower for keyword in keywords)


def metric_name_matches(metric_info: MetricInfoState, names: set[str]) -> bool:
    metric_names = {metric_info["name"].lower()}
    metric_names.update(alias.lower() for alias in metric_info.get("alias", []))
    return bool(metric_names & {name.lower() for name in names})


def dedupe_metric_infos(metric_infos: list[MetricInfoState]) -> list[MetricInfoState]:
    metric_info_map: dict[str, MetricInfoState] = {}

    for metric_info in metric_infos:
        metric_info_map.setdefault(metric_info["name"], metric_info)

    return list(metric_info_map.values())


def filter_metrics_by_rules(query: str, metric_infos: list[MetricInfoState]) -> list[MetricInfoState]:
    if not metric_infos:
        return []

    need_sales = query_contains_any(query, SALES_METRIC_KEYWORDS)
    need_aov = query_contains_any(query, AOV_METRIC_KEYWORDS)
    need_order_count = query_contains_any(query, ORDER_COUNT_KEYWORDS)

    if not (need_sales or need_aov or need_order_count):
        return metric_infos

    filtered_metric_infos: list[MetricInfoState] = []

    if need_sales:
        filtered_metric_infos.extend(
            metric_info
            for metric_info in metric_infos
            if metric_name_matches(metric_info, {"GMV"})
        )

    if need_aov:
        filtered_metric_infos.extend(
            metric_info
            for metric_info in metric_infos
            if metric_name_matches(metric_info, {"AOV"})
        )

    if need_order_count:
        filtered_metric_infos.extend(
            metric_info
            for metric_info in metric_infos
            if metric_name_matches(metric_info, {"order_count", "订单数", "订单量"})
        )

    if not filtered_metric_infos:
        return [
            metric_info
            for metric_info in metric_infos
            if not metric_name_matches(metric_info, {"AOV"})
        ]

    return dedupe_metric_infos(filtered_metric_infos)


async def filter_metric(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    writer = runtime.stream_writer
    step = "过滤指标信息"

    writer({"type": "progress", "step": step, "status": "running"})

    try:
        query = state["query"]
        metric_infos = state.get("metric_infos", [])

        logger.info(f"过滤前指标: {[metric_info['name'] for metric_info in metric_infos]}")

        filtered_metric_infos = filter_metrics_by_rules(query, metric_infos)

        logger.info(f"过滤后指标: {[metric_info['name'] for metric_info in filtered_metric_infos]}")
        writer({"type": "progress", "step": step, "status": "success"})

        return {"metric_infos": filtered_metric_infos}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
