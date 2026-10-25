"""从结果列表生成 summary.md 汇总报告。

统计数字全部来自 results 列表（与 results.jsonl 同源），保证报告与结果文件一致。
"""

import datetime
import hashlib
from pathlib import Path

SUMMARY_FILENAME = "summary.md"

# 摘要最大长度（字符）
INPUT_SNIPPET_CHARS = 50
OUTPUT_SNIPPET_CHARS = 80

STATUS_LABELS = {"passed": "passed", "failed": "failed", "error": "error"}


def _md5_fingerprint(path):
    """用例文件内容 MD5 前 8 位，作为该次运行所用用例的版本指纹。"""
    return hashlib.md5(Path(path).read_bytes()).hexdigest()[:8]


def _snippet(text, max_chars):
    """压缩换行为空格并截断，用于报告中的输入/输出摘要。"""
    text = (text or "").replace("\n", " ").replace("\r", " ").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def summarize(results):
    """统计结果列表，返回报告所需的数字。"""
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "passed")
    failed = sum(1 for r in results if r["status"] == "failed")
    error = sum(1 for r in results if r["status"] == "error")

    error_types = {}
    for r in results:
        if r["status"] == "error":
            error_types[r["error_type"]] = error_types.get(r["error_type"], 0) + 1

    check_failures = {}
    for r in results:
        if r["status"] == "failed":
            for check in r["check_results"]:
                if not check["passed"]:
                    check_failures[check["type"]] = check_failures.get(check["type"], 0) + 1

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "error": error,
        "error_types": error_types,
        "check_failures": check_failures,
        # 全量通过率：passed / 总数
        "pass_rate_all": passed / total if total else 0.0,
        # 输出质量通过率：剔除调用异常，只看真正拿到模型输出的用例
        "pass_rate_quality": passed / (passed + failed) if (passed + failed) else 0.0,
    }


def _bad_case_reason(result):
    if result["status"] == "error":
        return f"[{result['error_type']}] {result['detail']}"
    reasons = [c["reason"] for c in result["check_results"] if not c["passed"]]
    return "; ".join(reasons) if reasons else "-"


def render_summary(results, cases_path, run_id, elapsed_seconds, model):
    """生成 summary.md 的 Markdown 文本。"""
    stats = summarize(results)
    lines = [
        "# LLM 输出质量测试报告",
        "",
        f"- run_id: `{run_id}`",
        f"- 报告生成时间: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"- 模型: `{model}`",
        f"- 用例文件: `{cases_path}`（内容指纹: `{_md5_fingerprint(cases_path)}`）",
        f"- 总耗时: {elapsed_seconds:.1f}s",
        "",
        "## 总体结果",
        "",
        "| 指标 | 数量 |",
        "|---|---|",
        f"| 总用例数 | {stats['total']} |",
        f"| 通过 passed | {stats['passed']} |",
        f"| 输出失败 failed | {stats['failed']} |",
        f"| 调用异常 error | {stats['error']} |",
        f"| 全量通过率 | {stats['pass_rate_all']:.1%} |",
        f"| 输出质量通过率（剔除调用异常） | {stats['pass_rate_quality']:.1%} |",
        "",
        "> 调用异常（error）表示 API 层出问题（超时/HTTP 错误等），",
        "> 不代表模型回答不合格，因此单独列出，不计入输出质量通过率。",
        "",
    ]

    lines += ["## 调用异常细分", ""]
    if stats["error_types"]:
        lines += ["| error_type | 数量 |", "|---|---|"]
        lines += [f"| {etype} | {count} |" for etype, count in sorted(stats["error_types"].items())]
    else:
        lines += ["无"]
    lines += [""]

    lines += ["## 按检查类型统计失败（仅 failed 用例）", ""]
    if stats["check_failures"]:
        lines += ["| 检查类型 | 失败次数 |", "|---|---|"]
        lines += [f"| {ctype} | {count} |" for ctype, count in sorted(stats["check_failures"].items())]
    else:
        lines += ["无"]
    lines += [""]

    lines += ["## 典型 Bad Case", ""]
    bad_cases = [r for r in results if r["status"] != "passed"]
    if bad_cases:
        lines += [
            "| case_id | 状态 | 失败原因 | 输入摘要 | 输出摘要 |",
            "|---|---|---|---|---|",
        ]
        for r in bad_cases:
            output = _snippet(r["output"], OUTPUT_SNIPPET_CHARS) if r["output"] else "-"
            lines.append(
                "| {case_id} | {status} | {reason} | {input} | {output} |".format(
                    case_id=r["case_id"],
                    status=STATUS_LABELS[r["status"]],
                    reason=_snippet(_bad_case_reason(r), 120),
                    input=_snippet(r["input"], INPUT_SNIPPET_CHARS),
                    output=output,
                )
            )
    else:
        lines += ["无，全部用例通过。"]
    lines += [""]
    return "\n".join(lines)


def write_summary(out_dir, results, cases_path, run_id, elapsed_seconds, model):
    """写出 summary.md，返回文件路径。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / SUMMARY_FILENAME
    text = render_summary(results, cases_path, run_id, elapsed_seconds, model)
    summary_path.write_text(text, encoding="utf-8")
    return summary_path
