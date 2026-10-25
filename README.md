# llm-eval-tool

一个轻量级命令行工具：读取一批测试用例，自动调用大模型 API，用可程序化的规则检查模型输出，保存每条结果并生成汇总报告。

**它不是聊天机器人，而是"大模型输出质量测试工具"**——核心价值在于：可复用、可重复运行、能统计结果，把大模型相关工作中零散的测试行为沉淀成规范的评测流程。

## 它解决什么问题

在有大模型参与的测试工作里，"模型回答好不好"如果只靠肉眼逐条看，无法重复、无法统计、无法对比。本工具把其中**可以客观判断的部分**自动化：

- 输出是否为空、是否超长、是否是合法 JSON、是否包含必需字段或关键词；
- 把"API 调用失败"和"模型输出不合格"严格分开统计，避免把超时误判成回答差；
- 每条用例留全量记录（输入、输出、耗时、逐项检查结果），便于复测和归因。

## 当前版本（V0.1）的能力边界

**已实现：**

- 读取 JSON 用例文件，加载时即校验合法性（缺字段、未知检查类型、格式错误会一次性报出）
- 5 种检查规则：`not_empty` / `json_valid` / `required_fields` / `max_length` / `contains`
- 兼容 OpenAI Chat Completions 风格 API（不绑定服务商，base_url/model/key 全部可配置）
- 结果逐条写入 `results.jsonl`，生成 `summary.md` 汇总报告
- 单条用例超时/异常不中断整批；每条结果即跑即落盘，中途退出不丢已跑数据
- 45 个 pytest 测试，网络请求全部 mock，不依赖真实 API

**明确不做（后续版本计划）：**

- Web 页面、FastAPI 服务、Docker、用户系统（V0.4 才考虑）
- 数据库、历史运行对比、按人物标签统计（V0.3）
- 主观评分：不做"回答好不好""人物像不像"的自动判断，人物一致性用例只记录输出供人工复核

## 环境变量配置

API Key 只从环境变量读取，仓库中不保存任何真实密钥。

方式一：复制 `.env.example` 为 `.env` 并填入真实值（`.env` 已被 `.gitignore` 排除）：

```bash
LLM_API_KEY=你的密钥
LLM_BASE_URL=你的OpenAI兼容接口地址   # 通常以 /v1 结尾
LLM_MODEL=你的模型名
```

方式二：直接在终端设置同名环境变量（优先级高于 `.env`）。

任何一家 OpenAI Chat Completions 兼容服务都可以，工具只向 `{LLM_BASE_URL}/chat/completions` 发 POST 请求。

## 如何运行

```bash
pip install -r requirements.txt

# 完整参数
python -m evaluator run --cases cases/cases.json --out results/ --timeout 30

# --model / --base-url 可临时覆盖环境变量
python -m evaluator run --model gpt-4o-mini --base-url https://api.example.com/v1

# 运行测试（不需要真实 API）
python -m pytest -v
```

批量运行中单条用例失败或异常**不会中断**整批测试；命令行会逐条打印进度，结束时输出统计。

## 输入：cases.json

顶层是数组，每条用例：

```json
{
  "case_id": "TC001",
  "persona_tags": ["冷静", "严谨"],
  "scene": "用户询问普通问题",
  "input": "请解释什么是接口测试",
  "checks": [
    {"type": "not_empty"},
    {"type": "max_length", "value": 500}
  ],
  "expected": "输出包含有效回答，不超过500字",
  "enabled": true
}
```

必填字段：`case_id`、`input`、`checks`；`persona_tags`、`scene`、`expected`、`enabled` 缺省时取默认值。`input` 允许空字符串（空输入本身就是一种测试场景）。`enabled=false` 的用例不会执行。

### 检查类型

| type | 说明 | 需要的参数 |
|---|---|---|
| `not_empty` | 输出去掉空白后非空 | 无 |
| `json_valid` | 输出能解析为合法 JSON（自动剥离 Markdown 代码围栏） | 无 |
| `required_fields` | 输出 JSON 顶层对象包含指定字段 | `value`: 字符串数组 |
| `max_length` | 输出字符数不超过上限 | `value`: 正整数 |
| `contains` | 输出包含指定关键词 | `value`: 非空字符串 |

只做客观可程序化判断，`contains` 请仅用于用例里明确约束过的关键词。

## 输出：results/ 目录

每次运行产生两个文件（同一目录重复运行会覆盖，run_id 可区分批次）：

**`results.jsonl`** —— 每条用例一行：

```json
{
  "run_id": "20261025_143001",
  "case_id": "TC001",
  "model": "模型名",
  "status": "passed",
  "error_type": null,
  "latency_ms": 1234,
  "input": "原输入",
  "output": "模型输出",
  "check_results": [{"type": "not_empty", "passed": true, "reason": ""}],
  "timestamp": "2026-10-25T12:00:00"
}
```

**`summary.md`** —— 汇总报告：总用例数、通过数、输出失败数、调用异常数、按 `error_type` 和检查类型的失败统计、典型 Bad Case 列表（case_id、失败原因、输入/输出摘要）、运行时间、模型名、用例文件版本指纹。

### status 的三种取值（核心设计）

| status | 含义 | error_type |
|---|---|---|
| `passed` | API 调用成功且全部检查通过 | `null` |
| `failed` | API 调用成功，但输出未通过规则检查 | `check_failed` |
| `error` | 调用层出问题，与模型输出质量无关 | `timeout` / `connection_error` / `request_error` / `http_error` / `invalid_response` / `unexpected_error` |

**为什么必须区分 error 和 failed？** "API 超时"说明的是网络或服务问题，不是模型回答不合格。如果混为一谈，报告里"失败 10 条"就失去意义——你不知道该去修网络还是改提示词。所以报告给出两个通过率：全量通过率（passed/总数）和输出质量通过率（passed/(passed+failed)，剔除调用异常）。

**HTTP 200 也不代表测试通过**——200 只说明调用成功，模型输出仍可能为空、超长、不是合法 JSON，这些由 checks 层判定为 failed。

## 目录结构

```
llm-eval-tool/
├── README.md
├── requirements.txt          # requests, pytest
├── .env.example              # 环境变量模板
├── .gitignore                # 排除 .env、results/、__pycache__ 等
├── conftest.py               # 让 pytest 可直接导入 evaluator 包
├── cases/
│   └── cases.json            # 测试用例（当前 20 条）
├── evaluator/
│   ├── __main__.py           # python -m evaluator 入口
│   ├── cli.py                # 命令行参数、.env 加载、流程编排
│   ├── loader.py             # 用例读取与校验
│   ├── api_client.py         # OpenAI 兼容 API 客户端
│   ├── checks.py             # 5 种规则检查
│   ├── runner.py             # 批量执行、状态分类、结果落盘
│   └── report.py             # summary.md 生成
├── results/                  # 运行产物（gitignore，保留 .gitkeep）
└── tests/                    # 45 个测试，网络请求全部 mock
    ├── test_loader.py
    ├── test_checks.py
    ├── test_report.py
    └── test_runner.py
```

## 当前限制

1. **只支持一种 API 协议**：OpenAI Chat Completions 风格；多模型自动适配是后续计划。
2. **只做客观规则检查**：回答质量、人物一致性等主观维度必须人工评分，工具只负责把输出和上下文完整记录下来。
3. **结果覆盖**：同一输出目录重复运行会覆盖 `results.jsonl` 和 `summary.md`；历史对比、SQLite 存储是 V0.3 计划。
4. **顺序执行**：用例逐条串行调用，大批量跑批耗时与用例数成正比；并发执行是后续优化项。
5. **`.env` 解析极简**：只支持 `KEY=VALUE`、`#` 注释和 `${VAR}` 引用**已存在的**环境变量（如密钥存放在 Windows 用户变量中，`.env` 里写 `LLM_API_KEY=${DEEPSEEK_API_KEY}`）；不支持在 `.env` 内定义变量、多行值等高级语法。
6. **json_valid 有已知宽容**：对被 ```json 围栏包裹的输出会先剥围栏再解析（模型常见行为），严格场景下请注意。
7. **单轮对话**：只发单条 user 消息，不支持多轮上下文用例。

## 安全与隐私

- API Key 只从环境变量读取，不写入任何文件、日志或结果
- `.gitignore` 排除 `.env`、`results/`、`__pycache__/`
- 测试用例不含真实个人隐私数据；请勿把敏感数据写进 `input`
