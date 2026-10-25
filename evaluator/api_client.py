"""OpenAI Chat Completions 兼容的 API 客户端。

不绑定具体服务商：base_url / model / api_key / timeout 全部可配置。
API Key 只从环境变量读取，不落盘、不打印。

调用结果统一封装为 ApiResult，把所有调用层问题归类为
timeout / connection_error / request_error / http_error / invalid_response，
供 runner 区分"调用异常"和"输出失败"。
"""

import os
import time
from dataclasses import dataclass

import requests

CHAT_COMPLETIONS_PATH = "/chat/completions"

# 错误详情/响应体最多记录的字符数，避免超长输出撑爆结果文件
MAX_DETAIL_CHARS = 300


class ApiConfigError(Exception):
    """环境变量缺失或非法，无法构造 API 配置。"""


@dataclass
class ApiResult:
    ok: bool                 # True 表示拿到模型输出（不代表输出合格，合格与否由 checks 判断）
    output: str              # ok=True 时为模型回复文本，否则为空字符串
    error_type: str | None   # timeout / connection_error / request_error / http_error / invalid_response
    http_status: int | None
    detail: str              # 失败原因描述，成功时为空字符串
    latency_ms: int


def resolve_config(model=None, base_url=None):
    """从环境变量读取配置，命令行参数优先。配置缺失时抛出 ApiConfigError。"""
    env_key = os.environ.get("LLM_API_KEY", "")
    env_base_url = base_url or os.environ.get("LLM_BASE_URL", "")
    env_model = model or os.environ.get("LLM_MODEL", "")

    missing = [
        name
        for name, value in (
            ("LLM_API_KEY", env_key),
            ("LLM_BASE_URL", env_base_url),
            ("LLM_MODEL", env_model),
        )
        if not value
    ]
    if missing:
        raise ApiConfigError(
            f"缺少 API 配置环境变量: {', '.join(missing)}。"
            f"请在终端设置，或复制 .env.example 为 .env 后填入真实值。"
        )
    return {"api_key": env_key, "base_url": env_base_url, "model": env_model}


def _truncate(text):
    text = text or ""
    return text[:MAX_DETAIL_CHARS] + ("..." if len(text) > MAX_DETAIL_CHARS else "")


def chat_completion(prompt, api_key, base_url, model, timeout):
    """调用一次 Chat Completions，永不抛网络类异常，失败信息都在 ApiResult 里。

    返回值不含密钥，可安全写入结果文件。
    """
    url = base_url.rstrip("/") + CHAT_COMPLETIONS_PATH
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }

    start = time.perf_counter()
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        return ApiResult(False, "", "timeout", None,
                         f"请求超时（timeout={timeout}s）", _elapsed_ms(start))
    except requests.exceptions.ConnectionError as exc:
        # 网关/负载均衡在等待响应期间断开连接时，读超时会以 ConnectionError 形态出现
        # （消息含 "Read timed out"，而非 requests.exceptions.ReadTimeout）。
        # 按语义归为 timeout：等待响应超时与"根本没连上"是两类问题。
        if "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
            return ApiResult(False, "", "timeout", None,
                             f"等待响应超时（连接层断开）: {exc}", _elapsed_ms(start))
        return ApiResult(False, "", "connection_error", None,
                         f"连接失败: {exc}", _elapsed_ms(start))
    except requests.exceptions.RequestException as exc:
        return ApiResult(False, "", "request_error", None,
                         f"请求失败: {exc}", _elapsed_ms(start))

    latency_ms = _elapsed_ms(start)

    if not 200 <= response.status_code < 300:
        return ApiResult(False, "", "http_error", response.status_code,
                         f"HTTP {response.status_code}: {_truncate(response.text)}",
                         latency_ms)

    try:
        data = response.json()
        output = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        return ApiResult(False, "", "invalid_response", response.status_code,
                         f"响应结构不符合 Chat Completions 格式: {exc}；"
                         f"响应片段: {_truncate(response.text)}",
                         latency_ms)

    return ApiResult(True, output if isinstance(output, str) else "",
                     None, response.status_code, "", latency_ms)


def _elapsed_ms(start):
    return round((time.perf_counter() - start) * 1000)
