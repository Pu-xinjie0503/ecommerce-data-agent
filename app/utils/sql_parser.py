import re


MYSQL_OPTIMIZER_OUTPUT_PATTERN = re.compile(
    r"/\*\s*select#\d+\s*\*/",
    re.IGNORECASE,
)


DANGEROUS_SQL_PATTERN = re.compile(
    r"\b("
    r"insert|update|delete|drop|alter|truncate|create|replace|merge|"
    r"grant|revoke|call|exec|execute|load|outfile"
    r")\b",
    re.IGNORECASE,
)


def remove_markdown_code_fence(text: str) -> str:
    text = text.strip()

    match = re.search(
        r"```(?:sql)?\s*(.*?)```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group(1).strip()

    return text


def cut_mysql_optimizer_output(sql: str) -> str:
    match = MYSQL_OPTIMIZER_OUTPUT_PATTERN.search(sql)
    if match:
        return sql[: match.start()].strip()

    return sql.strip()


def split_first_statement(sql: str) -> str:
    in_single_quote = False
    in_double_quote = False

    for i, ch in enumerate(sql):
        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif ch == ";" and not in_single_quote and not in_double_quote:
            return sql[:i].strip()

    return sql.strip()


def remove_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n\r]*", " ", sql)
    return sql.strip()


def extract_sql(raw_text: str) -> str:
    if not raw_text or not raw_text.strip():
        raise ValueError("LLM 没有返回 SQL 内容")

    text = remove_markdown_code_fence(raw_text)

    match = re.search(r"\b(select|with)\b", text, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"没有找到 SELECT/WITH SQL: {raw_text}")

    sql = text[match.start() :].strip()
    sql = cut_mysql_optimizer_output(sql)
    sql = split_first_statement(sql)
    sql = remove_sql_comments(sql)
    sql = re.sub(r"\s+", " ", sql).strip()

    if not sql:
        raise ValueError("SQL 清洗后为空")

    if not re.match(r"^(select|with)\b", sql, flags=re.IGNORECASE):
        raise ValueError(f"只允许 SELECT/WITH 查询，不允许该 SQL: {sql}")

    if DANGEROUS_SQL_PATTERN.search(sql):
        raise ValueError(f"SQL 包含危险关键字，已拒绝: {sql}")

    if ";" in sql:
        raise ValueError(f"检测到多语句 SQL，已拒绝: {sql}")

    return sql
