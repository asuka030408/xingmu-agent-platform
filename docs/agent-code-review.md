# DeepSeek Agent 代码 Review 入口

## 模块怎么分

```mermaid
flowchart LR
    UI[浏览器] --> HTTP[routes_read.py /api/ask]
    HTTP --> RT[agent/runtime.py 模型与工具循环]
    RT --> DS[agent/deepseek.py DeepSeek API]
    RT --> T[agent/tools.py 工具白名单与参数校验]
    T --> S[services.py 业务计算]
    S --> DB[db.py 只读连接池]
    DB --> PG[(PostgreSQL)]
    P[agent/prompts.py] --> RT
```

模型决定调用哪些工具、传什么参数以及如何组织最终回答。工具注册表限制了它能做的事；库存、时间冲突和成本计算仍由确定性的 Python 业务代码完成。预订写入不在 Agent 工具表中，仍需页面预览和人工确认。

## 一次提问怎么走

```mermaid
sequenceDiagram
    actor U as 使用者
    participant UI as 浏览器
    participant API as /api/ask
    participant A as Agent Runtime
    participant M as DeepSeek
    participant T as 只读业务工具
    participant DB as PostgreSQL
    U->>UI: 下周六上海的三个活动能同时交付吗？
    UI->>API: 问题 + 最近对话上下文
    API->>A: ask()
    A->>M: 问题 + 工具定义，要求先选工具
    M-->>A: get_delivery_plan(上海)
    A->>T: 校验参数并执行工具
    T->>DB: 只读查询
    DB-->>T: 项目、设备、维修和预订数据
    T-->>A: 核算结果
    A->>M: 工具结果
    M-->>A: 根据结果生成中文回答
    A-->>UI: 回答 + 工具名 + 数据来源
```

## Review 时看这几处

| 问题 | 代码位置 |
| --- | --- |
| 模型 Key 和 HTTP 请求怎样处理？ | `agent/deepseek.py`、`config.py` |
| 模型能调用哪些工具？ | `agent/tools.py` 的 `TOOL_SPECS` 与 `execute()` |
| 工具调用如何循环、限制轮次？ | `agent/runtime.py` 的 `ask()` |
| 业务数字从哪里来？ | `services.py` 与 `db.py` |
| API 怎样返回错误、记录工具调用？ | `routes_read.py` |

Key 只从本机环境变量或被 Git 忽略的路径文件读取。Agent API 默认没有规则回答兜底：DeepSeek 不可用时会明确返回错误。短期对话上下文由浏览器提交，最多 6 条；没有数据库中的长期记忆。当前没有文档库，因此没有 RAG 模块。
