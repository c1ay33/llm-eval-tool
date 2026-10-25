"""report.py 的测试：统计数字必须与结果列表一致，人工复核/空输入不混入通过率。"""

import json

from evaluator.report import summarize, write_summary


def make_result(case_id, status, error_type=None, check_results=None,
                output="输出", detail="", input_text="输入", manual_review=False):
    return {
        "run_id": "20261025_120000",
        "case_id": case_id,
        "persona_tags": ["冷静"],
        "scene": "测试",
        "manual_review": manual_review,
        "model": "test-model",
        "status": status,
        "error_type": error_type,
        "latency_ms": 100,
        "input": input_text,
        "output": output,
        "check_results": check_results or [],
        "detail": detail,
        "timestamp": "2026-10-25T12:00:00",
    }


def test_summarize_counts_match_results():
    results = [
        make_result("TC001", "passed"),
        make_result("TC002", "failed", "check_failed",
                    [{"type": "max_length", "passed": False, "reason": "超长"}]),
        make_result("TC003", "failed", "check_failed",
                    [{"type": "json_valid", "passed": False, "reason": "非法 JSON"}]),
        make_result("TC004", "error", "timeout"),
        make_result("TC005", "error", "http_error"),
        make_result("TC006", "passed", manual_review=True),      # 人工复核，不计入通过率
        make_result("TC007", "invalid_input"),                    # 空输入，未调 API
    ]
    stats = summarize(results)
    assert stats["total"] == 7
    assert stats["manual"] == 1
    assert stats["invalid_input"] == 1
    assert stats["passed"] == 1
    assert stats["failed"] == 2
    assert stats["error"] == 2
    assert stats["error_types"] == {"timeout": 1, "http_error": 1}
    assert stats["check_failures"] == {"max_length": 1, "json_valid": 1}
    assert stats["pass_rate_all"] == 0.2            # 1/5，只算自动检查用例
    assert stats["pass_rate_quality"] == 1 / 3      # 剔除 2 条调用异常


def test_manual_review_cases_excluded_from_rates():
    results = [
        make_result("TC_A", "passed"),
        make_result("TC_M", "passed", manual_review=True),
        make_result("TC_M2", "passed", manual_review=True),
    ]
    stats = summarize(results)
    assert stats["passed"] == 1        # 只统计自动检查用例
    assert stats["pass_rate_all"] == 1.0
    assert stats["pass_rate_quality"] == 1.0


def test_failed_result_with_multiple_failing_checks_counts_each_type():
    results = [
        make_result("TC001", "failed", "check_failed", [
            {"type": "not_empty", "passed": True, "reason": ""},
            {"type": "max_length", "passed": False, "reason": "超长"},
            {"type": "contains", "passed": False, "reason": "缺关键词"},
        ]),
    ]
    stats = summarize(results)
    assert stats["check_failures"] == {"max_length": 1, "contains": 1}


def test_write_summary_generates_consistent_markdown(tmp_path):
    results = [
        make_result("TC001", "passed"),
        make_result("TC002", "failed", "check_failed",
                    [{"type": "max_length", "passed": False, "reason": "输出长度 612 超过上限 500"}]),
        make_result("TC003", "error", "timeout", detail="等待响应超时（连接层断开）"),
    ]
    # 用例文件需要真实存在，报告要计算内容指纹
    cases_path = tmp_path / "cases.json"
    cases_path.write_text("[]", encoding="utf-8")

    path = write_summary(tmp_path, results, cases_path, "20261025_120000",
                         elapsed_seconds=12.34, model="test-model")
    text = path.read_text(encoding="utf-8")

    assert "| 总用例数 | 3 |" in text
    assert "| 需人工复核（不计入自动通过率） | 0 |" in text
    assert "| 未调用 API（空输入） | 0 |" in text
    assert "| 通过 passed | 1 |" in text
    assert "| 输出失败 failed | 1 |" in text
    assert "| 调用异常 error | 1 |" in text
    assert "| timeout | 1 |" in text
    assert "| max_length | 1 |" in text
    assert "TC002" in text and "612" in text  # Bad Case 行包含原因
    assert "TC003" in text and "timeout" in text
    assert "`test-model`" in text and "12.3s" in text


def test_manual_review_listed_separately_not_in_bad_case(tmp_path):
    results = [
        make_result("TC_M", "passed", manual_review=True, output="待人工复核的输出"),
        make_result("TC_A", "failed", "check_failed",
                    [{"type": "not_empty", "passed": False, "reason": "空"}]),
    ]
    cases_path = tmp_path / "cases.json"
    cases_path.write_text("[]", encoding="utf-8")
    path = write_summary(tmp_path, results, cases_path, "r1", 1.0, "m")
    text = path.read_text(encoding="utf-8")

    assert "| 需人工复核（不计入自动通过率） | 1 |" in text
    assert "需人工复核用例" in text and "TC_M" in text and "待人工复核的输出" in text
    # 人工复核用例不能出现在 Bad Case 表里
    bad_case_section = text.split("典型 Bad Case")[1]
    assert "TC_M" not in bad_case_section
    assert "TC_A" in bad_case_section


def test_write_summary_all_passed(tmp_path):
    results = [make_result("TC001", "passed")]
    cases_path = tmp_path / "cases.json"
    cases_path.write_text("[]", encoding="utf-8")
    path = write_summary(tmp_path, results, cases_path, "r1", 1.0, "m")
    text = path.read_text(encoding="utf-8")
    assert "无，自动检查用例全部通过。" in text


def test_write_summary_snippets_truncated_and_json_serializable(tmp_path):
    results = [make_result("TC001", "failed", "check_failed",
                           [{"type": "not_empty", "passed": False, "reason": "空"}],
                           output="长" * 500, input_text="问" * 200)]
    cases_path = tmp_path / "cases.json"
    cases_path.write_text("[]", encoding="utf-8")
    path = write_summary(tmp_path, results, cases_path, "r1", 1.0, "m")
    text = path.read_text(encoding="utf-8")
    assert "…" in text  # 摘要被截断
    # 报告本身可被 JSON 转义检查（无非法控制字符）——这里仅验证写出的内容可重新读取
    json.dumps({"summary": text}, ensure_ascii=False)
