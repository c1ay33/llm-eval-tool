"""runner.py 与 api_client.py 的测试。

所有网络请求都通过 mock 完成，不依赖真实 API：
- api_client：mock requests.post，验证各类调用异常的归类
- runner：mock api_client.chat_completion，验证状态三分与"单条失败不中断"
"""

import json
import os
from unittest import mock

import pytest
import requests

from evaluator import api_client, runner
from evaluator.cli import load_dotenv


# ---------------------------------------------------------------------------
# api_client 配置解析
# ---------------------------------------------------------------------------

def test_resolve_config_missing_env_raises(monkeypatch):
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(api_client.ApiConfigError, match="LLM_API_KEY"):
        api_client.resolve_config()


def test_resolve_config_reads_env_and_args_override(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    config = api_client.resolve_config()
    assert config == {
        "api_key": "test-key",
        "base_url": "https://env.example.com/v1",
        "model": "env-model",
    }
    overridden = api_client.resolve_config(model="cli-model",
                                           base_url="https://cli.example.com/v1")
    assert overridden["model"] == "cli-model"
    assert overridden["base_url"] == "https://cli.example.com/v1"


# ---------------------------------------------------------------------------
# api_client：mock requests.post，验证调用异常归类
# ---------------------------------------------------------------------------

def make_response(status_code=200, json_data=None, text="", json_raises=False):
    response = mock.Mock()
    response.status_code = status_code
    response.text = text
    if json_raises:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = json_data
    return response


OPENAI_OK = {"choices": [{"message": {"content": "模型回答"}}]}


def test_chat_completion_success():
    with mock.patch.object(api_client.requests, "post",
                           return_value=make_response(json_data=OPENAI_OK)) as post:
        result = api_client.chat_completion("hi", "key", "https://api.example.com/v1",
                                            "m1", timeout=5)
    assert result.ok is True
    assert result.output == "模型回答"
    assert result.error_type is None
    assert result.http_status == 200
    # 请求打到 {base_url}/chat/completions，且密钥只出现在请求头
    assert post.call_args.args[0] == "https://api.example.com/v1/chat/completions"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer key"
    # 结果对象不携带密钥
    assert "key" not in str(result)


def test_chat_completion_timeout_classified():
    with mock.patch.object(api_client.requests, "post",
                           side_effect=requests.exceptions.Timeout):
        result = api_client.chat_completion("hi", "key", "https://x/v1", "m", 5)
    assert result.ok is False
    assert result.error_type == "timeout"


def test_chat_completion_connection_error_classified():
    with mock.patch.object(api_client.requests, "post",
                           side_effect=requests.exceptions.ConnectionError("refused")):
        result = api_client.chat_completion("hi", "key", "https://x/v1", "m", 5)
    assert result.ok is False
    assert result.error_type == "connection_error"


def test_read_timeout_surfacing_as_connection_error_classified_as_timeout():
    # 网关/LB 空闲后断开连接时，读超时以 ConnectionError 形态出现，应按语义归为 timeout
    exc = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='api.deepseek.com', port=443): Read timed out.")
    with mock.patch.object(api_client.requests, "post", side_effect=exc):
        result = api_client.chat_completion("hi", "key", "https://x/v1", "m", 30)
    assert result.ok is False
    assert result.error_type == "timeout"


def test_chat_completion_http_error_includes_status():
    with mock.patch.object(api_client.requests, "post",
                           return_value=make_response(status_code=401,
                                                      text='{"error": "bad key"}')):
        result = api_client.chat_completion("hi", "key", "https://x/v1", "m", 5)
    assert result.ok is False
    assert result.error_type == "http_error"
    assert result.http_status == 401
    assert "401" in result.detail


def test_chat_completion_wrong_structure_is_invalid_response():
    with mock.patch.object(api_client.requests, "post",
                           return_value=make_response(json_data={"foo": []})):
        result = api_client.chat_completion("hi", "key", "https://x/v1", "m", 5)
    assert result.ok is False
    assert result.error_type == "invalid_response"


def test_chat_completion_non_json_body_is_invalid_response():
    with mock.patch.object(api_client.requests, "post",
                           return_value=make_response(json_raises=True, text="<html>")):
        result = api_client.chat_completion("hi", "key", "https://x/v1", "m", 5)
    assert result.ok is False
    assert result.error_type == "invalid_response"


def test_chat_completion_null_content_becomes_empty_output():
    data = {"choices": [{"message": {"content": None}}]}
    with mock.patch.object(api_client.requests, "post",
                           return_value=make_response(json_data=data)):
        result = api_client.chat_completion("hi", "key", "https://x/v1", "m", 5)
    assert result.ok is True
    assert result.output == ""


# ---------------------------------------------------------------------------
# cli.load_dotenv：${VAR} 展开
# ---------------------------------------------------------------------------

def test_load_dotenv_expands_env_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-123")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text('LLM_API_KEY=${DEEPSEEK_API_KEY}\n', encoding="utf-8")
    load_dotenv(env_file)
    assert os.environ["LLM_API_KEY"] == "sk-test-123"


def test_load_dotenv_unresolved_reference_keeps_literal_and_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("NOT_EXISTING_VAR", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text('LLM_API_KEY=${NOT_EXISTING_VAR}\n', encoding="utf-8")
    load_dotenv(env_file)
    assert os.environ["LLM_API_KEY"] == "${NOT_EXISTING_VAR}"
    assert "不存在" in capsys.readouterr().err


def test_load_dotenv_real_env_var_takes_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "from-shell")
    env_file = tmp_path / ".env"
    env_file.write_text('LLM_API_KEY=${DEEPSEEK_API_KEY}\n', encoding="utf-8")
    load_dotenv(env_file)
    assert os.environ["LLM_API_KEY"] == "from-shell"  # setdefault 不覆盖


# ---------------------------------------------------------------------------
# runner：mock api_client.chat_completion，验证状态三分与批处理不中断
# ---------------------------------------------------------------------------

def ok_client(output):
    """构造一个调用成功的 fake chat_completion。"""
    return lambda *args, **kwargs: api_client.ApiResult(
        True, output, None, 200, "", latency_ms=10)


CONFIG = {"api_key": "test-key", "base_url": "https://x/v1", "model": "test-model"}
CASE = {
    "case_id": "TC001",
    "persona_tags": ["冷静"],
    "scene": "正常提问",
    "input": "问题",
    "checks": [{"type": "not_empty"}],
    "expected": "",
    "enabled": True,
}


def test_runner_passed_when_checks_pass():
    with mock.patch.object(api_client, "chat_completion", ok_client("有效回答")):
        result = runner.run_case(CASE, CONFIG, timeout=5, run_id="r1")
    assert result["status"] == "passed"
    assert result["error_type"] is None
    assert result["output"] == "有效回答"
    assert result["check_results"][0]["passed"] is True


def test_runner_failed_is_not_error():
    # 调用成功但输出为空：not_empty 不通过 → failed 而不是 error
    with mock.patch.object(api_client, "chat_completion", ok_client("")):
        result = runner.run_case(CASE, CONFIG, timeout=5, run_id="r1")
    assert result["status"] == "failed"
    assert result["error_type"] == "check_failed"
    assert result["check_results"][0]["passed"] is False


def test_runner_error_keeps_timeout_separate_from_failed():
    def timeout_client(*args, **kwargs):
        return api_client.ApiResult(False, "", "timeout", None, "请求超时", 5000)

    with mock.patch.object(api_client, "chat_completion", timeout_client):
        result = runner.run_case(CASE, CONFIG, timeout=5, run_id="r1")
    assert result["status"] == "error"
    assert result["error_type"] == "timeout"
    assert result["check_results"] == []
    # 关键区别：error 的结果不参与检查，不会和 failed 混淆


def test_runner_single_crash_does_not_stop_batch(tmp_path, capsys):
    case_a = dict(CASE, case_id="TC_A")
    case_b = dict(CASE, case_id="TC_B", checks=[{"type": "contains", "value": "关键词"}])
    case_c = dict(CASE, case_id="TC_C")

    calls = {"n": 0}

    def counting_client(prompt, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:  # 第二条用例抛意外异常
            raise RuntimeError("boom")
        return api_client.ApiResult(True, "正常输出 含关键词", None, 200, "", 10)

    with mock.patch.object(api_client, "chat_completion", counting_client):
        run_id, results = runner.run_batch([case_a, case_b, case_c], CONFIG,
                                           timeout=5, out_dir=tmp_path)
    assert len(results) == 3  # 三条都有结果，没有中断
    assert [r["status"] for r in results] == ["passed", "error", "passed"]
    assert results[1]["error_type"] == runner.UNEXPECTED_ERROR
    assert "boom" in results[1]["detail"]


def test_run_batch_writes_results_jsonl(tmp_path):
    case_b = dict(CASE, case_id="TC_B", checks=[{"type": "max_length", "value": 3}])
    with mock.patch.object(api_client, "chat_completion", ok_client("一段比较长的回答")):
        run_id, results = runner.run_batch([CASE, case_b], CONFIG,
                                           timeout=5, out_dir=tmp_path)
    assert len(run_id) == 15 and run_id[8] == "_"  # YYYYMMDD_HHMMSS
    path = tmp_path / "results.jsonl"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    for field in ("run_id", "case_id", "model", "status", "error_type",
                  "latency_ms", "input", "output", "check_results", "timestamp"):
        assert field in first
    assert all(r["run_id"] == run_id for r in results)


def test_run_batch_overwrites_previous_results(tmp_path):
    with mock.patch.object(api_client, "chat_completion", ok_client("回答")):
        runner.run_batch([CASE], CONFIG, timeout=5, out_dir=tmp_path, run_id="r1")
    with mock.patch.object(api_client, "chat_completion", ok_client("回答")):
        runner.run_batch([CASE], CONFIG, timeout=5, out_dir=tmp_path, run_id="r2")
    lines = (tmp_path / "results.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["run_id"] == "r2"
