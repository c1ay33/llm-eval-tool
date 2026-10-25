"""批量执行测试用例。

核心约定：
- status 取值：passed / failed / error / invalid_input
  - error：调用层出问题（超时、HTTP 错误、响应结构不对、意外异常），与模型输出质量无关
  - failed：调用成功，但输出没通过规则检查（error_type=check_failed）
  - passed：调用成功且全部检查通过
  - invalid_input：空输入等客户端可直接判定的问题，不调用 API，不算模型失败
- manual_review=true 的用例照常执行，但结果由人工复核，
  报告中单独列出且不计入自动通过率——自动检查和人工评估边界清晰。
- 单条用例抛出任何异常都不能中断整批，该条记为 error 继续跑下一条。
- 每条结果立即写盘并 flush，中途退出已跑完的结果不丢。
"""

import datetime
import json
from pathlib import Path

from evaluator import api_client
from evaluator.checks import run_checks

RESULTS_FILENAME = "results.jsonl"

# 意外异常（bug、环境问题等）的 error_type，不属于调用层已知的四类错误
UNEXPECTED_ERROR = "unexpected_error"

# 空输入等无效输入的状态：不调用 API，不算模型失败
INVALID_INPUT = "invalid_input"


def _make_result(case, run_id, model, status, error_type, latency_ms,
                 output, check_results, detail):
    return {
        "run_id": run_id,
        "case_id": case["case_id"],
        "persona_tags": case.get("persona_tags", []),
        "scene": case.get("scene", ""),
        "manual_review": case.get("manual_review", False),
        "model": model,
        "status": status,
        "error_type": error_type,
        "latency_ms": latency_ms,
        "input": case["input"],
        "output": output,
        "check_results": check_results,
        "detail": detail,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def run_case(case, config, timeout, run_id):
    """执行单条用例，返回结果字典。调用层异常已被 api_client 封装，不抛网络异常。"""
    if not case["input"].strip():
        # 空输入在客户端就能判定：调用 API 只会浪费一次请求，且结果没有评测意义
        return _make_result(case, run_id, config["model"], INVALID_INPUT,
                            None, 0, "", [], "空输入，未调用 API")

    api_result = api_client.chat_completion(
        case["input"],
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        timeout=timeout,
    )

    if not api_result.ok:
        # 调用异常：与模型输出质量无关，不计入检查
        return _make_result(case, run_id, config["model"], "error",
                            api_result.error_type, api_result.latency_ms,
                            "", [], api_result.detail)

    check_results = run_checks(api_result.output, case["checks"])
    all_passed = all(item["passed"] for item in check_results)
    return _make_result(case, run_id, config["model"],
                        "passed" if all_passed else "failed",
                        None if all_passed else "check_failed",
                        api_result.latency_ms,
                        api_result.output, check_results, "")


def _run_case_safe(case, config, timeout, run_id):
    """兜底保护：单条用例的任何意外异常都转为 error 结果，不中断整批。"""
    try:
        return run_case(case, config, timeout, run_id)
    except Exception as exc:  # noqa: BLE001 兜底保证批处理不中断
        return _make_result(case, run_id, config["model"], "error",
                            UNEXPECTED_ERROR, 0, "", [], repr(exc))


def run_batch(cases, config, timeout, out_dir, run_id=None):
    """逐条执行全部用例，结果逐行写入 out_dir/results.jsonl。

    返回 (run_id, results)。
    """
    run_id = run_id or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    results_path = out_dir / RESULTS_FILENAME
    with results_path.open("w", encoding="utf-8") as f:
        for index, case in enumerate(cases, start=1):
            result = _run_case_safe(case, config, timeout, run_id)
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
            f.flush()
            results.append(result)
            print(f"[{index}/{len(cases)}] {result['case_id']}: "
                  f"{result['status']} ({result['latency_ms']}ms)", flush=True)
    return run_id, results
