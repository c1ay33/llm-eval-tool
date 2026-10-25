"""输出规则检查。

只做可程序化判断的客观规则，不做"回答好不好"的主观评分。
每条检查返回 {type, passed, reason}，reason 在通过时为空字符串。
"""

import json

CODE_FENCE_PREFIX = "```"


def _strip_code_fence(text):
    """剥离 Markdown 代码块围栏。

    模型常把 JSON 包在 ```json ... ``` 里返回。评测关心的是内容本身
    是否为合法 JSON，因此解析前先剥围栏；没有围栏时原样返回。
    """
    stripped = text.strip()
    if not stripped.startswith(CODE_FENCE_PREFIX):
        return stripped
    lines = stripped.splitlines()
    # 去掉首行 ```json / ``` 和末行 ```
    if len(lines) >= 2 and lines[-1].strip().startswith(CODE_FENCE_PREFIX):
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _check_not_empty(output, _value):
    if output.strip():
        return True, ""
    return False, "输出为空"


def _check_json_valid(output, _value):
    try:
        json.loads(_strip_code_fence(output))
        return True, ""
    except (json.JSONDecodeError, ValueError) as exc:
        return False, f"输出不是合法 JSON: {exc}"


def _parse_json_object(output):
    """尝试把输出解析为顶层 JSON 对象，失败返回 (None, 原因)。"""
    try:
        data = json.loads(_strip_code_fence(output))
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"输出不是合法 JSON: {exc}"
    if not isinstance(data, dict):
        return None, f"输出 JSON 顶层不是对象，实际为 {type(data).__name__}"
    return data, ""


def _check_required_fields(output, value):
    data, reason = _parse_json_object(output)
    if data is None:
        return False, reason
    missing = [field for field in value if field not in data]
    if missing:
        return False, f"JSON 缺少必填字段: {missing}"
    return True, ""


def _check_max_length(output, value):
    length = len(output)
    if length <= value:
        return True, ""
    return False, f"输出长度 {length} 超过上限 {value}"


def _check_contains(output, value):
    if value in output:
        return True, ""
    return False, f"输出未包含关键词: {value!r}"


_CHECK_FUNCS = {
    "not_empty": _check_not_empty,
    "json_valid": _check_json_valid,
    "required_fields": _check_required_fields,
    "max_length": _check_max_length,
    "contains": _check_contains,
}


def run_checks(output, checks):
    """对模型输出逐条执行检查。

    output: 模型输出文本（None 按空字符串处理）
    checks: 用例里的检查项列表，每项形如 {"type": "max_length", "value": 500}
    返回检查结果列表，每项形如 {"type": ..., "passed": True/False, "reason": ""}
    """
    if output is None:
        output = ""
    results = []
    for check in checks:
        ctype = check["type"]
        passed, reason = _CHECK_FUNCS[ctype](output, check.get("value"))
        results.append({"type": ctype, "passed": passed, "reason": reason})
    return results
