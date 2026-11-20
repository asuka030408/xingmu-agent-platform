# 星幕设备项目：代码 Review 图

这两张图记录最初的规则路由版本，作为历史资料保留。当前 DeepSeek 工具调用架构及请求时序见 `agent-code-review.md`；预订请求时序见 `security-and-concurrency.md`。

## 1. 组件 UML

![组件 UML](component-uml.svg)

源文件：[component-uml.puml](component-uml.puml)。图展示浏览器、Flask、Agent、业务服务、只读数据库连接，以及演示数据初始化脚本的边界。

## 2. 一次请求的时序图

![请求时序图](request-sequence.svg)

源文件：[request-sequence.puml](request-sequence.puml)。时序从 `static/app.js` 的 `ask()` 开始，经过 `POST /api/ask`，最终回到页面的 `appendMessage()` 和 `renderPlan()`。

## 对照代码

| Review 点 | 代码位置 |
| --- | --- |
| 网页发送请求与显示结果 | `static/app.js` 的 `ask()` |
| HTTP 校验、调用 Agent、写日志、序列化响应 | `xingmu/security.py`、`xingmu/routes_read.py`、`xingmu/jsonutil.py` |
| 模型选择工具和生成中文回答 | `xingmu/agent/runtime.py`、`xingmu/agent/deepseek.py` |
| 查询业务数据、设备分配与成本估算 | `xingmu/agent/tools.py`、`xingmu/services.py` |
| 只读数据库连接 | `xingmu/db.py` 的 `connect()` |
| 表结构和关联 | `schema.sql` |

## 值得讨论的实现点

1. 上面两张图片是早期架构，当前请求链路以 `agent-code-review.md` 为准。
2. `_planning_data()` 在一次连接中执行多次 `SELECT`，然后在 Python 内存中按优先级和单件增量成本贪心分配；它不保证全局最低成本。
3. Agent 查询使用只读账号 `xingmu_app`；预订确认走 `routes_booking.py` 和单独的 `xingmu_booking` 账号。`POST /api/ask` 本身不写预订或采购记录。
