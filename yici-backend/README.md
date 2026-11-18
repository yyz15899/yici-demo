# 一词之差 · 自动分析后端

《一词之差》英语阅读训练应用的自动分析服务。Python + FastAPI，无数据库、无登录，
题目 / 笔记 / 进度全部由前端保存在浏览器 IndexedDB，本服务只做一次性分析，不落盘任何用户内容。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 部署健康检查。模型未配置时仍返回 200 |
| POST | `/api/v1/reviews/analyze` | 提交初答与依据，返回选项差异、逐字引文、解释、追问 |

交互式文档：启动后访问 `http://127.0.0.1:8000/docs`。

## 本地启动

要求 Python 3.11+（本机已用 CPython 3.13 验证；msys2/mingw 版 Python 无法安装 pydantic 二进制依赖，请勿使用）。

```bash
cd yici-backend

# 创建虚拟环境（Windows 标准 Python）
python -m venv .venv
.venv\Scripts\activate        # Git Bash 用: source .venv/Scripts/activate

pip install -r requirements.txt -r requirements-dev.txt

# 配置环境变量（可选，默认 mock 模式无需任何密钥）
copy .env.example .env        # Git Bash 用: cp .env.example .env

# 启动
uvicorn app.main:app --host 127.0.0.1 --port 8000
# 或不激活 venv 直接运行：
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

运行测试：

```bash
.venv\Scripts\python.exe -m pytest tests -q
```

## 环境变量（.env.example）

| 变量 | 默认 | 说明 |
|---|---|---|
| `MODEL_BACKEND` | `mock` | `mock` 确定性模拟模型（联调用）；`openai` 走真实模型 |
| `OPENAI_BASE_URL` | 空 | OpenAI 兼容地址。DashScope：`https://dashscope.aliyuncs.com/compatible-mode/v1`；DeepSeek：`https://api.deepseek.com/v1` |
| `OPENAI_API_KEY` | 空 | 密钥只存服务端环境变量，绝不返回给前端、不写日志 |
| `MODEL_NAME` | 空 | 如 `qwen-plus` / `deepseek-chat` |
| `MODEL_TIMEOUT_SECONDS` | `30` | 模型调用超时 |
| `MAX_BODY_BYTES` | `65536` | 请求体上限（64KB） |
| `RATE_LIMIT_PER_MINUTE` | `10` | 每 IP 每分钟 analyze 次数，0 不限 |
| `CORS_ORIGINS` | `*` | 允许的前端来源，逗号分隔；上线建议改为具体域名 |
| `TRUST_PROXY` | `false` | 反向代理部署时设 true，按 X-Forwarded-For 限流 |

`MODEL_BACKEND=openai` 但三项配置不全时：`/healthz` 仍 200（`model_configured:false`），
analyze 返回 503 `MODEL_NOT_CONFIGURED`，前端可继续手动复盘。

## 请求示例（规划书图书馆题）

```json
POST /api/v1/reviews/analyze
{
  "article_text": "During exam week, the library moved its closing time from eight to ten. Some students used the extra time to study. Students who depended on the last bus still left at eight every evening.",
  "question_stem": "Which statement is supported by the report?",
  "options": [
    {"id": "A", "text": "The last bus began running two hours later."},
    {"id": "B", "text": "All students stayed longer after the library extended its hours."},
    {"id": "C", "text": "Students asked the library to open earlier during exam week."},
    {"id": "D", "text": "Some students took advantage of the later closing time."}
  ],
  "student_choice": "B",
  "compare_choice": "D",
  "answer_basis": "evidence",
  "evidence": [
    {"quote": "Some students used the extra time to study.", "start": 72, "end": 115}
  ],
  "reference_answer": "D",
  "reference_explanation": "第二句直接支持 D；B 将受益群体扩大至全体。"
}
```

字段说明：
- `answer_basis`：`evidence`（有依据）/ `elimination`（排除法）/ `guess`（猜的）/ `dont_remember`（记不清）。
  后两者不会得到确定错因（`definitive_cause:false`）。
- `evidence[].start/end`：原文字符偏移，可省略；给了就必须与 `quote` 逐字一致，否则 422。
- `reference_answer` / `reference_explanation`：可省略，缺参考答案仍可分析。
- 只提交本次复盘所需材料，不要带个人笔记全文或剧情存档。

## 响应示例

成功（HTTP 200）：

```json
{
  "status": "ok",
  "review": {
    "status": "ok",
    "advisory": "suggestion",
    "differences": [
      {"kind": "added", "detail_zh": "选项 B 比 D 多提到了 “all, stayed, longer, library”…"},
      {"kind": "omitted", "detail_zh": "选项 D 提到而 B 漏掉了 “some, took, advantage, later”…"}
    ],
    "quotes": [
      {"text": "Some students used the extra time to study.", "start": 72, "end": 115,
       "option_id": "B", "note_zh": "你圈出的依据"}
    ],
    "explanation_zh": "…",
    "follow_up_zh": "你圈的这句「Some students used the extra time to…」更接近选项 D 的说法：它写的是谁、哪些情况？…",
    "issue_types": ["scope"],
    "definitive_cause": true,
    "needs_review_reasons": []
  },
  "error": null
}
```

待核对（HTTP 200，`status:"needs_review"`）：引文无法逐字定位、参考答案冲突、材料不足时，
`needs_review_reasons` 给出 `code` + 中文原因，其余建议字段仍可用。

错误（HTTP 4xx/5xx，`status:"error"`）：

```json
{"status": "error", "review": null,
 "error": {"code": "MODEL_TIMEOUT", "message_zh": "自动分析超时。可稍后重试，或直接继续手动复盘，已填写的内容不受影响。"}}
```

### 错误码一览

| HTTP | code | 含义 | 前端处理 |
|---|---|---|---|
| 422 | `VALIDATION_ERROR` | 编号/长度/字段格式不合法 | 提示修改字段，保留已填内容 |
| 422 | `EVIDENCE_NOT_FOUND` | 证据无法在原文逐字定位 | 引导回原文重新圈选 |
| 429 | `RATE_LIMITED` | 超过每 IP 限流 | 提示稍后再试，可手动复盘 |
| 413 | `BODY_TOO_LARGE` | 请求体超 64KB | 提示精简文章 |
| 503 | `MODEL_NOT_CONFIGURED` | 服务端未配置模型 | 隐藏自动分析入口或提示，手动复盘 |
| 503 | `MODEL_TIMEOUT` | 模型超时 | 可重试，手动复盘不受影响 |
| 503 | `MODEL_INVALID_OUTPUT` | 模型输出不符合固定结构 | 同上 |
| 500 | `INTERNAL_ERROR` | 未预期错误 | 同上 |

`needs_review_reasons` 内的 code：`QUOTE_NOT_LOCATABLE`（模型编造引文，已剔除）、
`REFERENCE_CONFLICT`（与参考答案冲突）、`INSUFFICIENT_MATERIAL`（未提交依据）。

## 前端联调说明

1. 前端通过环境变量配置 API 地址（Vite 示例）：`.env` 中 `VITE_API_BASE_URL=http://127.0.0.1:8000`，
   代码里 `fetch(`${import.meta.env.VITE_API_BASE_URL}/api/v1/reviews/analyze`, …)`。
2. 启动后端（默认 mock 模式，无需密钥）→ 前端提交上述图书馆题 payload → 核对 `review.quotes`
   的 `start/end` 能否在原文高亮回跳。
3. 错误处理约定：**任何非 `status:"ok"` 的结果都不清空用户已填内容**。
   `needs_review` 展示原因并允许标记待核对；`error` 展示 `message_zh` 并保留手动复盘入口。
4. 所有模型反馈带 `advisory:"suggestion"`，UI 必须标“建议”，允许学生纠正；
   `definitive_cause:false` 时不得展示确定错因。模型结果不参与独立复测判定。
5. 圈选证据时尽量带上 `start/end`（字符偏移），服务端会逐字校验；编辑原文后旧偏移失效会返回
   `EVIDENCE_NOT_FOUND`，前端应重新定位或提示失效。
6. 发送前向学生说明将提交哪些材料（文章、题干、选项、选择、证据、可选参考答案/解析）。
7. 联调通过后将后端 `.env` 改为 `MODEL_BACKEND=openai` 并填三项配置，即可切换真实模型，
   前端代码无需改动。

## 安全与隐私

- 密钥仅从服务端环境变量读取；日志只记录状态码与耗时，不记录原文、笔记、密钥。
- 校验错误响应不回显输入内容。
- 提交材料在模型提示词中包裹于 `<material>` 标记内，系统提示明确其中任何指令一律视为文章内容，
  不执行（防提示注入）。
- 每处模型引文都服务端逐字定位校验，编造引文自动剔除并转待核对。

## 已验证 / 待验证

已验证（pytest 18 项 + 本地 uvicorn 实测，见交付报告）：mock 全流程、6 个指定异常场景、
陌生文章迁移、限流、请求体上限、健康检查。

待验证：真实模型（需配置密钥后实测）、反向代理下的限流与 HTTPS、
Qoder Sites 能否托管 Python 后端（预计需独立部署，前端静态站 + 本服务分离）、多进程部署时
限流需换共享存储（当前为单进程内存实现）。