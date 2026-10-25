"""命令行入口：python -m evaluator run --cases cases.json --out results/"""

import argparse
import os
import sys
import time
from pathlib import Path

from evaluator import api_client, report, runner
from evaluator.loader import load_cases

DEFAULT_CASES = "cases/cases.json"
DEFAULT_OUT = "results"
DEFAULT_TIMEOUT = 30

EXIT_OK = 0
EXIT_CONFIG_OR_LOAD_ERROR = 2


def _expand_value(key, value):
    """展开 ${VAR} 形式的环境变量引用；引用不存在时保留原样并警告。"""
    expanded = os.path.expandvars(value)
    if "${" in expanded:
        print(f"[配置警告] .env 中 {key} 引用的环境变量不存在，"
              f"值仍为字面量: {expanded}", file=sys.stderr)
    return expanded


def load_dotenv(path=".env"):
    """极简 .env 加载：KEY=VALUE、# 注释、${VAR} 引用已有环境变量，真实环境变量优先。

    不引入 python-dotenv 依赖，只覆盖本工具需要的用法。
    """
    env_path = Path(path)
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = _expand_value(key, value.strip().strip('"').strip("'"))
        if key:
            os.environ.setdefault(key, value)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="evaluator",
        description="大模型输出质量自动化评测工具（V0.1）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="运行一批测试用例并生成报告")
    run_cmd.add_argument("--cases", default=DEFAULT_CASES,
                         help=f"用例 JSON 文件路径（默认 {DEFAULT_CASES}）")
    run_cmd.add_argument("--out", default=DEFAULT_OUT,
                         help=f"结果输出目录（默认 {DEFAULT_OUT}）")
    run_cmd.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                         help=f"单次 API 请求超时秒数（默认 {DEFAULT_TIMEOUT}）")
    run_cmd.add_argument("--model", default=None,
                         help="覆盖环境变量 LLM_MODEL")
    run_cmd.add_argument("--base-url", default=None,
                         help="覆盖环境变量 LLM_BASE_URL")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.command == "run":
        return cmd_run(args)
    return EXIT_OK


def cmd_run(args):
    load_dotenv()

    try:
        config = api_client.resolve_config(model=args.model, base_url=args.base_url)
    except api_client.ApiConfigError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return EXIT_CONFIG_OR_LOAD_ERROR

    try:
        cases = load_cases(args.cases)
    except Exception as exc:  # loader 的 CaseLoadError / IO 错误，启动前失败
        print(f"[用例加载失败] {exc}", file=sys.stderr)
        return EXIT_CONFIG_OR_LOAD_ERROR

    print(f"用例文件: {args.cases}（有效用例 {len(cases)} 条）")
    print(f"模型: {config['model']}  base_url: {config['base_url']}  timeout: {args.timeout}s")

    start = time.perf_counter()
    run_id, results = runner.run_batch(cases, config, timeout=args.timeout, out_dir=args.out)
    elapsed = time.perf_counter() - start

    summary_path = report.write_summary(
        args.out, results, args.cases, run_id, elapsed, config["model"])

    stats = report.summarize(results)
    print(f"\n完成 run_id={run_id}，耗时 {elapsed:.1f}s")
    print(f"通过 {stats['passed']} / 输出失败 {stats['failed']} / 调用异常 {stats['error']}"
          f" / 人工复核 {stats['manual']} / 空输入未调用 {stats['invalid_input']}"
          f"（总 {stats['total']}）")
    print(f"结果文件: {Path(args.out) / runner.RESULTS_FILENAME}")
    print(f"汇总报告: {summary_path}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
