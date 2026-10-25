"""checks.py 的测试：5 种检查类型的通过/不通过行为。"""

from evaluator.checks import run_checks


def test_not_empty_passes_for_nonempty_output():
    results = run_checks("接口测试是验证系统间数据交换的测试。", [{"type": "not_empty"}])
    assert results == [{"type": "not_empty", "passed": True, "reason": ""}]


def test_not_empty_fails_for_blank_output():
    for blank in ["", "   \n\t "]:
        results = run_checks(blank, [{"type": "not_empty"}])
        assert results[0]["passed"] is False
        assert "空" in results[0]["reason"]


def test_json_valid_passes_for_plain_json():
    results = run_checks('{"name": "interface"}', [{"type": "json_valid"}])
    assert results[0]["passed"] is True


def test_json_valid_passes_for_fenced_json():
    output = "```json\n{\"name\": \"interface\"}\n```"
    results = run_checks(output, [{"type": "json_valid"}])
    assert results[0]["passed"] is True


def test_json_valid_fails_for_broken_json():
    results = run_checks('{"name": "interface",}', [{"type": "json_valid"}])
    assert results[0]["passed"] is False
    assert "JSON" in results[0]["reason"]


def test_json_valid_fails_for_json_with_surrounding_text():
    output = '结果如下：{"name": "interface"}'
    results = run_checks(output, [{"type": "json_valid"}])
    assert results[0]["passed"] is False


def test_required_fields_passes_when_all_present():
    output = '{"name": "interface", "method": "POST"}'
    checks = [{"type": "required_fields", "value": ["name", "method"]}]
    results = run_checks(output, checks)
    assert results[0]["passed"] is True


def test_required_fields_fails_and_lists_missing():
    output = '{"name": "interface"}'
    checks = [{"type": "required_fields", "value": ["name", "status"]}]
    results = run_checks(output, checks)
    assert results[0]["passed"] is False
    assert "status" in results[0]["reason"]


def test_required_fields_fails_for_non_object_json():
    results = run_checks('["name", "status"]', [{"type": "required_fields", "value": ["name"]}])
    assert results[0]["passed"] is False


def test_max_length_passes_at_limit_and_fails_over():
    checks = [{"type": "max_length", "value": 5}]
    assert run_checks("abcde", checks)[0]["passed"] is True
    over = run_checks("abcdef", checks)[0]
    assert over["passed"] is False
    assert "6" in over["reason"] and "5" in over["reason"]


def test_contains_passes_and_fails():
    checks = [{"type": "contains", "value": "冒烟"}]
    assert run_checks("冒烟测试是冒烟测试。", checks)[0]["passed"] is True
    miss = run_checks("这是一句不相关的话。", checks)[0]
    assert miss["passed"] is False
    assert "冒烟" in miss["reason"]


def test_multiple_checks_run_in_order():
    output = "冒烟测试"
    checks = [
        {"type": "not_empty"},
        {"type": "max_length", "value": 2},
        {"type": "contains", "value": "冒烟"},
    ]
    results = run_checks(output, checks)
    assert [r["type"] for r in results] == ["not_empty", "max_length", "contains"]
    assert [r["passed"] for r in results] == [True, False, True]


def test_none_output_treated_as_empty():
    results = run_checks(None, [{"type": "not_empty"}])
    assert results[0]["passed"] is False
