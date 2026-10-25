"""测试用例加载与校验。

职责：读取 cases.json，校验结构合法性，过滤 enabled=false 的用例，
返回规范化后的用例列表。加载阶段就发现配置错误，避免带着坏用例去花 API 调用费用。
"""

import json
from pathlib import Path

# V0.1 支持的检查类型
KNOWN_CHECK_TYPES = {"not_empty", "json_valid", "required_fields", "max_length", "contains"}

# 每条用例必填的字段
REQUIRED_FIELDS = ("case_id", "input", "checks")


class CaseLoadError(Exception):
    """用例文件不存在、不是合法 JSON 或用例内容不合法。"""


def _case_label(case, index):
    """用于报错信息中定位用例：优先用 case_id，否则用序号。"""
    case_id = case.get("case_id") if isinstance(case, dict) else None
    return f"用例[{index + 1}] {case_id!r}" if case_id else f"用例[{index + 1}]"


def _validate_check_value(case_label, check_index, check):
    """校验单条检查项的 value 是否符合该类型的要求，返回错误信息列表。"""
    problems = []
    ctype = check["type"]
    value = check.get("value")
    if ctype == "required_fields":
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(f, str) and f for f in value)
        ):
            problems.append(
                f"{case_label} 第{check_index + 1}条检查 required_fields 的 value "
                f"必须是非空字符串列表，实际为 {value!r}"
            )
    elif ctype == "max_length":
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            problems.append(
                f"{case_label} 第{check_index + 1}条检查 max_length 的 value "
                f"必须是正整数，实际为 {value!r}"
            )
    elif ctype == "contains":
        if not isinstance(value, str) or not value:
            problems.append(
                f"{case_label} 第{check_index + 1}条检查 contains 的 value "
                f"必须是非空字符串，实际为 {value!r}"
            )
    return problems


def _validate_case(case, index):
    """校验单条用例，返回错误信息列表（空列表表示合法）。"""
    label = _case_label(case, index)
    if not isinstance(case, dict):
        return [f"{label} 必须是对象，实际为 {type(case).__name__}"]

    problems = []
    for field in REQUIRED_FIELDS:
        if field not in case:
            problems.append(f"{label} 缺少必填字段 {field!r}")

    if not isinstance(case.get("case_id"), str) or not case.get("case_id"):
        problems.append(f"{label} 的 case_id 必须是非空字符串")
    if not isinstance(case.get("input"), str):
        # 注意：input 允许是空字符串（空输入用例），但不允许缺失或非字符串
        problems.append(f"{label} 的 input 必须是字符串")

    checks = case.get("checks")
    if not isinstance(checks, list) or not checks:
        problems.append(f"{label} 的 checks 必须是非空数组")
        return problems

    for check_index, check in enumerate(checks):
        if not isinstance(check, dict):
            problems.append(f"{label} 第{check_index + 1}条检查必须是对象")
            continue
        ctype = check.get("type")
        if ctype not in KNOWN_CHECK_TYPES:
            problems.append(
                f"{label} 第{check_index + 1}条检查 type 未知: {ctype!r}，"
                f"当前支持: {sorted(KNOWN_CHECK_TYPES)}"
            )
            continue
        problems.extend(_validate_check_value(label, check_index, check))
    return problems


def _normalize_case(case):
    """填充可选字段的默认值，返回规范化后的用例。"""
    return {
        "case_id": case["case_id"],
        "persona_tags": case.get("persona_tags", []),
        "scene": case.get("scene", ""),
        "input": case["input"],
        "checks": case["checks"],
        "expected": case.get("expected", ""),
        "enabled": case.get("enabled", True),
    }


def load_cases(path):
    """从 JSON 文件加载用例列表。

    返回 enabled=true 的规范化用例列表；文件或内容不合法时抛出 CaseLoadError，
    报错信息一次性列出所有问题。
    """
    path = Path(path)
    if not path.is_file():
        raise CaseLoadError(f"用例文件不存在: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaseLoadError(f"用例文件不是合法 JSON: {path} ({exc})") from exc

    if not isinstance(data, list):
        raise CaseLoadError(
            f"用例文件顶层必须是数组，实际为 {type(data).__name__}: {path}"
        )

    problems = []
    for index, case in enumerate(data):
        problems.extend(_validate_case(case, index))
    if problems:
        raise CaseLoadError(f"用例文件存在 {len(problems)} 个问题:\n" + "\n".join(problems))

    return [_normalize_case(case) for case in data if case.get("enabled", True)]
