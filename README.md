# 星幕设备 · Agent 数据中台演示版

这是一个用 Python 和 PostgreSQL 实现的本机业务原型。公司、项目、设备和价格均为**虚构演示数据**。

## 一分钟试用

1. 双击 `E:\XingmuAgentPlatform\run.cmd`。
2. 打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。
3. 点击页面上的示例问题，或输入“下周六上海的三个活动能同时交付吗？”。
4. 在“设备预订试用”里选项目和设备，先预览，再点“确认写入预订”。无需账号密码。

若 `run.cmd` 启动了网页服务，关闭该窗口或按 `Ctrl+C` 可停止它；若网页已经在运行，脚本只会提示地址。PostgreSQL 可继续运行；需要停止时使用 `E:\PostgreSQL-18\scripts\stop.ps1`。

**从 GitHub 克隆时：** 仓库只包含源码和说明，不包含 `.venv`、本机密钥、日志、备份或数据库。项目目前面向 Windows；需先准备 Python 3.11 与本机 PostgreSQL 18，在项目目录创建虚拟环境并安装 `requirements.txt`。将 PostgreSQL 管理密码放在其 `secrets\postgres-password.txt`，如安装目录不是 `E:\PostgreSQL-18`，设置环境变量 `XM_POSTGRES_ROOT`。当前 `run.cmd` 适配带 `scripts\start.ps1` 的便携版 PostgreSQL；其他安装方式先自行启动数据库，再运行 `python -m xingmu.server`。首次运行 `setup_demo.py` 会生成虚构数据并重置演示数据库，请勿对需要保留的数据运行。

## 项目做了什么

- **数据接入与模型**：PostgreSQL 保存公司、仓库、设备型号、逐台设备、项目、需求、预订、维修、可替代型号和跨仓线路。
- **业务服务**：按“备货 → 活动 → 归还检查”的完整时间段计算设备占用，排除已确认预订与维修，并比较本仓、跨仓、替代和外租的增量成本。
- **业务 Agent**：员工可用自然语言查询项目交付、库存、维修及项目清单。Agent 只调用预先定义的只读工具，不直接执行任意 SQL。
- **网页工作台**：展示项目、设备可用量、交付核算和对话结果。
- **安全边界**：网页仅监听 `127.0.0.1`；Agent 使用只读数据库账号，预订模块使用只能读取相关表、插入预订与审计的独立账号。写请求要求页面自动取得的会话校验令牌，并检查请求来源、大小与频率。无需账号密码登录。
- **并发预订**：先生成 10 分钟有效的签名方案，人工点击确认后重新检查项目、设备、维修和占用时间。事务锁、唯一请求号及数据库排斥约束防止重复写入和重叠占用。
- **并发服务**：Waitress 处理并发 HTTP 请求；读取与预订分别使用有上限的数据库连接池，请求等待和 SQL 执行都有超时。
- **追溯**：问题及意图记录在 `logs\agent-queries.jsonl`；预订结果保存在 `booking_audit`，拒绝与异常边界记录在 `logs\security.jsonl`。
- **数据质量**：`/api/quality` 检查项目需求、设备重复预订、预订与维修冲突、设备关联完整性。

## 演示数据

运行 `setup_demo.py` 时，会生成**下一周星期六**的活动数据。当前生成日期见网页顶部。包含 2 个仓库、48 台逐台编号设备、1 个已确认活动、3 个待确认活动、2 台维修设备。重新运行脚本会**重置并替换** `xingmu_equipment` 数据库里的演示数据。

数据库：`xingmu_equipment`，主机：`127.0.0.1`，端口：`5432`。网页专用用户密码保存在 `secrets\app-password.txt`，仅当前 Windows 用户可读取。PostgreSQL 管理密码保存在 `E:\PostgreSQL-18\secrets\postgres-password.txt`。

## 主要文件

| 文件 | 作用 |
| --- | --- |
| `setup_demo.py` | 创建数据库、只读用户和演示数据 |
| `schema.sql` | 数据库表结构 |
| `xingmu/services.py` | 库存、维修和交付核算工具 |
| `xingmu/agent.py` | 自然语言意图识别与工具调用 |
| `xingmu/app.py`、`xingmu/server.py` | Flask 应用装配与本机 HTTP 服务 |
| `xingmu/routes_read.py`、`xingmu/routes_booking.py` | 只读接口与预订接口 |
| `xingmu/security.py` | 页面会话校验、来源检查、限流、审计 |
| `xingmu/booking.py` | 预订方案、二次校验、事务写入 |
| `xingmu/db.py` | 只读与预订连接池 |
| `migrate_security.py` | 可重复运行的安全与并发数据库迁移；不重置数据 |
| `templates/index.html`、`static/` | 网页界面 |

## 运行检查

在项目目录执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

健康检查地址：`http://127.0.0.1:8765/api/health`。

代码评审用的组件 UML、一次请求的时序图以及可编辑的 PlantUML 源文件见 `docs\code-review-diagrams.md`。

当前安全与并发策略、剩余边界见 `docs\security-and-concurrency.md`，并发实测结果见 `docs\concurrency-test-report.md`。原来的企业扩展设计见 `docs\enterprise-extension-design.md`。

## 统一业务口径

- **设备占用窗口**：活动开始前 6 小时备货，到活动结束后 4 小时归还检查。
- **可用设备**：状态为 `active`，且在占用窗口内没有已确认预订或维修记录的逐台设备。跨仓设备还要满足线路运输提前量。
- **外租缺口**：项目需求数量减去可分配的自有设备数量。外租是建议，尚未确认供应商可供货。
- **估算增量成本**：跨仓运输费、替代设备溢价和演示外租单价之和；不含人工、车辆固定成本和税费。

## 当前边界

这是本机可试用原型。自然语言理解采用透明的规则路由，**无需大模型 API 密钥**；目前支持项目交付、设备库存、维修和项目列表这几类问题。调拨与外租方案按项目优先级和单件增量成本依次分配，属于规则建议，不保证跨所有项目的全局最优。预订只针对方案中的自有设备；外租、采购、人员排班与车辆调度尚未接入。当前没有员工身份，因此无法实现“不同员工看不同项目”的人员级权限；接入真实企业数据前必须另行接入统一身份系统。当前没有说明书或合同数据，故未加入 RAG。
