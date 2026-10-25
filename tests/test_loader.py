"""loader.py 的测试：加载、校验、过滤、报错信息。"""

import json

import pytest

from evaluator.loader import CaseLoadError, load_cases

VALID_CASE = {
    "case_id": "TC001",
    "persona_tags": ["冷静"],
    "scene": "正常提问",
    "input": "请解释什么是接口测试",
    "checks": [{"type": "not_empty"}],
    "expected": "非空回答",
    "enabled": True,
}


def write_cases_file(tmp_path, data):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_valid_cases(tmp_path):
    path = write_cases_file(tmp_path, [VALID_CASE])
    cases = load_cases(path)
    assert len(cases) == 1
    assert cases[0]["case_id"] == "TC001"
    assert cases[0]["input"] == "请解释什么是接口测试"
    assert cases[0]["checks"] == [{"type": "not_empty"}]


def test_optional_fields_get_defaults(tmp_path):
    case = {"case_id": "TC010", "input": "hi", "checks": [{"type": "not_empty"}]}
    path = write_cases_file(tmp_path, [case])
    cases = load_cases(path)
    assert cases[0]["persona_tags"] == []
    assert cases[0]["scene"] == ""
    assert cases[0]["expected"] == ""
    assert cases[0]["enabled"] is True


def test_disabled_case_is_filtered(tmp_path):
    disabled = dict(VALID_CASE, case_id="TC002", enabled=False)
    enabled = dict(VALID_CASE, case_id="TC003")
    path = write_cases_file(tmp_path, [disabled, enabled])
    cases = load_cases(path)
    assert [case["case_id"] for case in cases] == ["TC003"]


def test_missing_required_field_raises(tmp_path):
    case = {"case_id": "TC001", "checks": [{"type": "not_empty"}]}  # 缺 input
    path = write_cases_file(tmp_path, [case])
    with pytest.raises(CaseLoadError, match="input"):
        load_cases(path)


def test_empty_input_string_is_allowed(tmp_path):
    # 空输入是合法用例（TC002 空输入场景），不允许的是缺失或非字符串
    case = dict(VALID_CASE, input="")
    path = write_cases_file(tmp_path, [case])
    cases = load_cases(path)
    assert cases[0]["input"] == ""


def test_top_level_not_list_raises(tmp_path):
    path = write_cases_file(tmp_path, {"cases": []})
    with pytest.raises(CaseLoadError, match="数组"):
        load_cases(path)


def test_unknown_check_type_raises(tmp_path):
    case = dict(VALID_CASE, checks=[{"type": "looks_good"}])
    path = write_cases_file(tmp_path, [case])
    with pytest.raises(CaseLoadError, match="looks_good"):
        load_cases(path)


def test_required_fields_check_requires_string_list(tmp_path):
    case = dict(VALID_CASE, checks=[{"type": "required_fields", "value": "name"}])
    path = write_cases_file(tmp_path, [case])
    with pytest.raises(CaseLoadError, match="required_fields"):
        load_cases(path)


def test_max_length_check_requires_positive_int(tmp_path):
    case = dict(VALID_CASE, checks=[{"type": "max_length", "value": -1}])
    path = write_cases_file(tmp_path, [case])
    with pytest.raises(CaseLoadError, match="max_length"):
        load_cases(path)


def test_multiple_problems_reported_together(tmp_path):
    bad1 = {"case_id": "", "input": "hi", "checks": [{"type": "not_empty"}]}
    bad2 = {"case_id": "TC002", "input": "hi", "checks": [{"type": "max_length"}]}
    path = write_cases_file(tmp_path, [bad1, bad2])
    with pytest.raises(CaseLoadError) as exc_info:
        load_cases(path)
    message = str(exc_info.value)
    assert "case_id" in message and "max_length" in message


def test_invalid_json_raises(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CaseLoadError, match="合法 JSON"):
        load_cases(path)


def test_file_not_found_raises(tmp_path):
    with pytest.raises(CaseLoadError, match="不存在"):
        load_cases(tmp_path / "nope.json")
