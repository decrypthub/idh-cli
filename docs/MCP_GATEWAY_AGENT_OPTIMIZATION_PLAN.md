# idh MCP 网关 Agent 适配优化与验证计划

## 1. 目标

让 AI Agent 在单设备和多设备环境中都能可靠完成以下流程：

1. 发现当前在线的 IOSDecryptHub App。
2. 无歧义地选择目标进程。
3. 以较低 token 成本了解远端工具。
4. 按完整 JSON Schema 组装参数并调用工具。
5. 对修改状态的调用进行显式确认。
6. 在 App 重启、设备下线和 IP 更新后恢复工作。

本计划不改变设备端 HTTP/MCP 端口和路径：HTTP/MCP 继续使用 8088，MCP 继续使用
`POST /api/mcp`，设备由 `idh connect` 手动指定。服务没有认证，只能在可信局域网中使用。

### 1.1 Agent 与网关的职责边界

AI Agent 负责：

- 理解用户自然语言中的 App 名称和分析目标。
- 根据 `idh_list_devices` 返回的事实选择唯一候选，或在歧义时向用户澄清。
- 根据设备端工具 description 和 inputSchema 制定分析步骤。
- 在任务范围内决定是否执行具有副作用的操作。

`idh` 负责：

- 返回当前在线 App、稳定的本轮 `target_id` 和连接状态。
- 转发设备端真实工具描述和 schema。
- 按明确的 `target_id` 和工具参数做确定性路由。
- 对歧义 target、离线设备、无效 schema 和副作用调用返回结构化错误。

明确不做：

- 不解析“帮我分析 xxxx App”等自然语言。
- 不内置 App 名称评分、关键词匹配或所谓置信度算法。
- 不根据用户目标自动编排反汇编、事件查询或动态 hook。
- 不伪造设备端不存在的分析能力。

这些非目标用于避免把不可靠的语义判断放入基础设施层。Agent 的可用性应通过 MCP
`instructions`、工具 description、严格 schema 和结构化结果提升，而不是新增一个看似智能、
实际不可验证的 `analyze_app` 类函数。

## 2. 基线问题与设计决定

| 问题 | 风险 | 设计决定 |
|---|---|---|
| `target` 同时接受序号、名称、Bundle ID、URL 和部分匹配 | 多设备时容易匹配失败 | `target_id` 作为 Agent 的唯一规范标识，其他选择器只保留兼容 |
| App 重启后生成新实例 UUID，旧实例不删除 | 同一 Bundle ID 出现假歧义 | 新进程立即替换同 IP、同 Bundle ID 的旧进程，并增加 TTL |
| 网关对已保存但离线的连接直接路由失败 | 设备未上线时初始化失败 | 路由前用 /api/stats 复核并过滤离线连接 |
| 聚合网关直接发送 `tools/list`/`tools/call` | 不符合严格 MCP 初始化顺序 | 每个远端会话先执行 initialize 和 initialized 通知 |
| `idh_call_tool.arguments` 没有具体远端 schema | Agent 容易猜错参数且工具列表消耗较多 token | 工具摘要与单工具 schema 分离 |
| 读写工具统一隐藏在一个网关工具后 | MCP 客户端无法判断副作用 | 已知修改型工具要求 `allow_mutation=true` |
| 人类命令行只能手工构造 JSON-RPC | 调试成本高 | 增加 `idh call` 一次性调用命令 |

## 3. 分阶段实施步骤

### 阶段 A：建立规范 target 契约

实施：

- `AppEndpoint.as_dict()` 同时返回兼容字段 `id` 和规范字段 `target_id`。
- 网关工具 schema 明确要求优先使用 `idh_list_devices` 返回的 `target_id`。
- Bundle ID、App 名称、序号、服务名和 URL 继续兼容。
- 匹配失败返回结构化错误码和候选列表，不静默选择。

验证：

```bash
idh devices --json
uv run python -m pytest tests/test_models.py -q
```

验收标准：

- 每个 App 都包含非空 `target_id`。
- 两台设备运行相同 Bundle ID 时返回 `ambiguous_target` 和两个候选项。
- 使用候选项中的 `target_id` 可以准确解析到一个 App。

### 阶段 B：修复发现生命周期

实施：

- 保存每个 UDP 实例的最后信标时间。
- 6 秒未收到信标时标记 `beacon_status=stale`；路由前通过 `/api/stats` 复核，
  HTTP 可达的实例继续参与 target 解析。
- 10 秒未收到信标时从注册表删除。
- 同一发送 IP、同一 Bundle ID 的新 UUID 立即替换旧 UUID。
- 手动 `--endpoint` 不受 UDP TTL 影响。
- 对无效端口、无效实例 ID 和非信标 UDP 数据静默忽略。

验证：

```bash
uv run python -m pytest tests/test_discovery.py -q
idh watch --json
```

手工验证时启动目标 App，确认出现 `add`；终止 App 后等待 10 秒，确认出现 `remove`。

验收标准：

- App 重启后同一设备和 Bundle ID 只保留新 `target_id`。
- stale 且 HTTP 不可达的实例不会造成 Bundle ID 匹配歧义。
- stale 但 HTTP 可达的实例仍可正常调用 MCP。
- 下线实例最迟 10 秒从 `watch` 和 `devices` 消失。

### 阶段 C：按 target 等待透明代理启动

实施：

- `DiscoveryRegistry.wait()` 支持 predicate。
- `idh mcp --target X` 等待 X 可解析，而不是发现任意 App 后立即继续。
- 超时后仍返回结构化 target 错误，便于 MCP 客户端显示原因。

验证：

```bash
uv run python -m pytest \
  tests/test_discovery.py::test_registry_waits_for_requested_target_not_first_device -q
idh mcp --target com.example.app --startup-timeout 6
```

验收标准：先启动一个不匹配 App，再在 6 秒内启动目标 App，透明代理初始化成功。

### 阶段 D：补齐远端 MCP 握手

实施：

- 聚合网关首次访问每个远端实例时依次发送：
  `initialize`、`notifications/initialized`、实际请求。
- 保存设备返回的 `Mcp-Session-Id`。
- MCP URL 改变时清除旧 session 和初始化状态。
- 不自动重放 `tools/call`。

验证：

```bash
uv run python -m pytest tests/test_gateway.py::test_gateway_lists_and_calls_remote_tools -q
```

验收标准：测试服务收到的方法顺序必须是
`initialize -> notifications/initialized -> tools/list/tools/call`，同一会话只初始化一次。

### 阶段 E：降低 Agent schema 歧义

实施：

- 固定网关工具集增加 `idh_get_tool_schema`。
- `idh_list_tools` 默认返回名称、描述和 annotations 摘要。
- `detail=full` 保留一次返回全部 schema 的能力。
- `query` 支持按名称或描述过滤。
- `idh_call_tool` 规范参数改为 `tool_name` 和 `tool_arguments`。
- 旧参数 `name` 和 `arguments` 保留兼容并标记 deprecated。
- 所有网关输入 schema 增加 `additionalProperties=false`。

Agent 验证流程：

```text
idh_list_devices({})
idh_list_tools({"target":"<target_id>","query":"event"})
idh_get_tool_schema({"target":"<target_id>","tool_name":"query_events"})
idh_call_tool({
  "target":"<target_id>",
  "tool_name":"query_events",
  "tool_arguments":{"category":"digest","limit":3}
})
```

验收标准：Agent 不需要读取全部工具 schema，即可准确调用一个复杂工具。

### 阶段 E.1：验证 Agent 使用说明

实施：

- MCP initialize 的 `instructions` 明确目标发现、候选澄清、schema 获取和权限边界。
- 每个固定网关工具的 description 说明输入来源、事实边界和下一步。
- `idh_list_devices` 不替 Agent 选择 App；`idh_call_tool` 不理解自然语言。

验证：

```bash
uv run python -m pytest tests/test_gateway.py -q
```

验收标准：

- instructions 明确要求从 `idh_list_devices` 开始。
- instructions 明确规定多个候选时向用户澄清。
- tools/list 中不存在 `analyze_app`、`prepare_analysis` 等语义编排工具。
- 工具 description 明确以设备端返回的 description/schema 为事实来源。

### 阶段 F：保护修改型调用

实施：

- 网关维护明确的修改型工具集合。
- 未传 `allow_mutation=true` 时返回 `mutation_confirmation_required`。
- 只读工具不需要确认。
- 透明代理保持原样透传；其工具 schema 和 annotations 由设备端负责。

验证：

```bash
uv run python -m pytest \
  tests/test_gateway.py::test_gateway_requires_confirmation_for_mutating_tool -q
```

验收标准：`clear_events` 在未确认时不产生任何远端 HTTP 请求，确认后只执行一次。

### 阶段 G：增加一次性 CLI 调用

实施：

```bash
idh call <target_id> get_stats
idh call <target_id> query_events \
  --arguments '{"category":"digest","limit":3}' --json
idh call <target_id> set_pause \
  --arguments '{"paused":true}' --allow-mutation
```

验证：

```bash
uv run python -m pytest tests/test_gateway.py::test_cli_call_invokes_remote_tool -q
```

验收标准：成功调用退出码为 0，远端错误或确认缺失退出码为 1，无效 JSON 退出码为 2。

## 4. 完整自动化验证

在 `idh/` 目录执行：

```bash
uv run python -m pytest tests/ -q
uv run ruff check src/ tests/
uv run python -m build
```

验收标准：

- 所有测试通过。
- Ruff 无错误。
- sdist 和 wheel 构建成功。
- 运行时依赖仍为空。

## 5. Simulator 端到端验证

在 `IOSDecryptHub/` 目录执行：

```bash
make sim
scripts/sim_install.sh
```

在 `idh/` 目录执行：

```bash
idh devices --timeout 4 --json
idh call com.taisuii.cryptotesthost get_capabilities --timeout 4 --json
idh call com.taisuii.cryptotesthost get_stats --timeout 4 --json
idh call com.taisuii.cryptotesthost query_events \
  --arguments '{"category":"digest","limit":3}' --timeout 4 --json
```

然后验证聚合 stdio 网关和透明代理：

```bash
idh mcp --startup-timeout 4
idh mcp --target com.taisuii.cryptotesthost --startup-timeout 4
```

验收标准：

- UDP 自动发现成功，状态为 online。
- `target_id` 非空且同一进程内稳定。
- 三个一次性调用均返回 `isError=false`。
- 聚合网关按 `target_id` 调用成功。
- 透明代理直接暴露设备端工具。
- `/api/stats` 中 `hookFails=0`、`httpFailed=false`。

## 6. 兼容性与发布检查

- 保留 `id`、`name`、`arguments` 旧字段，旧客户端可继续工作。
- `target_id` 是进程实例 ID，App 重启后会变化；Agent 每个新任务都应重新调用
  `idh_list_devices`，不能跨重启缓存。
- Bundle ID 只有在唯一匹配时才能作为 target。
- `idh mcp --target` 透明代理行为保持不变。
- 不新增运行时依赖，不改 8088 和 `/api/mcp`。
- README 必须保留“无认证，仅限可信网络”的警告。

## 7. 完成定义

- [x] 阶段 A-G 的单元测试全部通过。
- [x] 完整 pytest、Ruff 和构建通过。
- [x] Simulator 自动发现、聚合调用和透明代理调用通过。
- [x] App 重启和下线 TTL 手工验证通过。
- [x] README 与实际 UDP 协议一致。
- [x] `git diff` 中没有捕获日志、设备数据、密钥或构建产物。

## 8. 本次执行记录（2026-07-28）

- 自动化：26 个 pytest 测试通过，Ruff 通过。
- 构建：`ios_decrypt_hub-0.2.0.tar.gz` 和 wheel 构建成功。
- Simulator：自动发现 `Crypto Test`，`get_stats`、`query_events`、透明代理调用成功。
- Agent schema：固定 5 个网关工具，摘要查询和单工具 schema 查询成功。
- 安全检查：未确认的 `clear_events` 返回 `mutation_confirmation_required`，没有发往设备。
- 生命周期：终止 App 后收到 remove；重新启动后收到新 target_id 的 add。
- 本机命令：pipx 可执行文件已更新为 `idh 0.2.0`。
