# idh

**中文** | [English](README.en.md)

`idh` 是 IOSDecryptHub 的 PC 端连接与 MCP 网关。它通过 `connect` 手动指定设备地址，
并把设备上的 Streamable HTTP MCP 转换为本地 stdio MCP。

> HTTP/MCP 服务没有身份认证，只能在可信局域网中使用，不要暴露到公网。

## 安装

要求 Python 3.10 或更高版本，运行时只使用 Python 标准库。

推荐使用 pipx 独立安装：

```bash
pipx install ios-decrypt-hub
```

也可以直接通过 pip 安装：

```bash
python3 -m pip install ios-decrypt-hub
```

升级到最新版：

```bash
pipx upgrade ios-decrypt-hub
```

## 连接设备

先手动连接设备（IP 从设备端面板或局域网获取）：

```bash
idh connect 192.168.100.65:8088
idh devices
```

连接会保存到 `~/.config/idh/connections.json`，后续 `devices`、`call`、`export` 和 `mcp` 会自动使用，不需要重复传参数。查看或移除连接：

```bash
idh connect
idh disconnect 192.168.100.65:8088
idh disconnect --all
```

`connect` 默认先验证 `/api/stats`；设备暂时离线但仍需预先保存时使用 `--force`。
可通过 `IDH_CONFIG_PATH` 修改配置位置，或用 `--no-saved` 让单次命令忽略已保存连接。

```bash
idh devices
idh devices --json
```

`idh --devices` 是 `idh devices` 的兼容快捷写法。`devices --json` 返回的
`target_id` 是当前在线 App 进程的唯一标识，AI Agent 和自动化脚本应优先使用它；
Bundle ID、App 名称、序号和 MCP URL 仅作为便利选择器。

临时地址仍可只用于单次命令（不保存）：

```bash
idh devices --endpoint http://192.168.1.20:8088
```

## 命令行调用 MCP

一次性调用只读工具：

```bash
idh call <target_id> get_stats
idh call <target_id> query_events \
  --arguments '{"category":"digest","limit":3}' --json
```

修改远端状态的工具必须显式确认：

```bash
idh call <target_id> set_pause \
  --arguments '{"paused":true}' --allow-mutation
```

`idh` 的聚合网关和单 App 透明代理都会执行同一检查。透明代理会在修改型远端工具的
schema 中增加必填 `allow_mutation`，确认后在本地移除该字段再转发。直接绕过 `idh` 请求
设备 `/api/mcp` 不经过这层防误操作检查；设备服务无认证，只能在可信网络使用。

## 导出事件 JSON

把当前 App 保留的完整事件自动分页导出到本地：

```bash
idh export <target_id> --output events.json
idh export <target_id> --category sym --max-blob-bytes 131072 --output aes.json
```

只有一个在线设备时可以省略 `target_id`。`idh` 会固定设备返回的 seq 上界、自动拉取后续页，
并通过同目录临时文件原子生成最终 JSON；已有文件默认不会覆盖，确认替换时传 `--force`。
默认每个 key/iv/input/output 最多导出 64KB，使用 `--include-dumps` 才会额外写入 hexdump。

导出文件可能包含密钥、明文、密文、Token、路径和请求内容，应作为敏感材料保存和分享。

## MCP 聚合网关

聚合网关同时管理多个已连接 App，只需在 MCP 客户端配置一次：

```json
{
  "mcpServers": {
    "idh": {
      "command": "idh",
      "args": ["mcp"]
    }
  }
}
```

网关提供固定工具集，避免设备上下线后 MCP 客户端缓存动态 `tools/list`：

- `idh_list_devices`
- `idh_list_tools`
- `idh_get_tool_schema`
- `idh_call_tool`
- `idh_get_panel_url`

### AI Agent 调用协议

`idh` 不解析自然语言，也不替 AI 决定“应该怎样分析”。自然语言理解、目标判断和分析规划
属于 AI Agent；`idh` 只提供在线事实、设备端真实工具描述、参数 schema 和确定性路由。

当用户说“帮我分析 xxxx App”时，Agent 应按以下协议工作：

1. 调用 `idh_list_devices` 获取当前在线 App，不使用历史 target 或缓存序号。
2. 由 Agent 将用户说的 `xxxx` 与返回的 `app`、`bundle` 字段对照。
3. 只有一个明确候选时，保存并使用该候选本轮返回的 `target_id`。
4. 多个候选都合理时，向用户展示 App、Bundle ID 和设备并要求选择；不得自行猜测。
5. 没有候选时，提示用户启动目标 App 并确认 IOSDecryptHub 已注入。
6. 调用 `idh_list_tools` 阅读设备端真实工具描述，不臆造不存在的分析能力。
7. 调用 `idh_get_tool_schema` 获取准备调用工具的完整 schema。
8. 调用 `idh_call_tool`，传入 `target`、`tool_name` 和 `tool_arguments`。
9. 查询、读取、反汇编等只读操作可根据用户目标自主执行；具有副作用的工具只有在用户
   明确要求后才传 `allow_mutation=true`。
10. 对调用栈或分支地址先检查 `symbolicate.symbol_source/confidence`，优先使用
    `function_start` / `disassemble_function.resolved_start`，不要只靠 prologue 字节猜函数头。
11. xref/字符串/selector/函数扫描若 `scan.coverage_complete=false`，必须沿
    `scan.next_scan_offset` 翻页完成覆盖，未扫完时不能断言“不存在引用”。
12. 完整导出使用 `export_events`；后续页保持 `cursor.snapshot_until_seq` 不变，并沿
    `cursor.next_after_seq` 继续，直到 `cursor.has_more=false`。

示例流程：

```text
用户：帮我分析 Example App 最近的加密行为
Agent → idh_list_devices({})
Agent：根据 app/bundle 字段确定唯一候选，取得 target_id
Agent → idh_list_tools({"target":"<target_id>","query":"crypto"})
Agent → idh_get_tool_schema({"target":"<target_id>","tool_name":"query_events"})
Agent → idh_call_tool({
  "target":"<target_id>",
  "tool_name":"query_events",
  "tool_arguments":{"category":"all","limit":100}
})
```

上述工具链提供事实和执行能力，具体选择 `query_events` 还是其他工具应由 Agent 根据用户目标
和设备端返回的 description/schema 判断，而不是由 `idh` 内置关键词或自然语言规则决定。

希望 Agent 自主选择在线目标时，应配置聚合网关 `idh mcp`。透明代理的 target 在进程启动时
已经固定，更适合用户或上层系统预先确定目标的场景。

## 单 App 透明代理

固定分析一个 App 时，透明代理会把远端工具及完整 schema 原样暴露给 AI Agent，调用体验最好：

```json
{
  "mcpServers": {
    "idh-demo": {
      "command": "idh",
      "args": ["mcp", "--target", "com.example.app"]
    }
  }
}
```

多台设备运行相同 Bundle ID 时，应改用 `idh devices --json` 返回的 `target_id`，
或者显式指定唯一 MCP URL。透明代理启动时要求目标已连接，否则直接报错退出。

本地 Simulator 联调：

```bash
idh mcp --target 1 --endpoint http://127.0.0.1:8088
```

所有日志写入 stderr，stdout 严格保留给逐行 JSON-RPC stdio 消息。

## 连接状态

- `devices` / `connect` 每次都会用 `/api/stats` 探测所有已保存连接，离线设备显示
  `offline` 状态。
- 路由前（`resolve_live_target`）会对目标做 HTTP 复核，离线连接直接过滤。

## 开发

```bash
uv sync --extra dev
uv run python -m pytest tests/ -q
uv run ruff check src/ tests/
uv run python -m build
```

详细实施和验收步骤见
[MCP_GATEWAY_AGENT_OPTIMIZATION_PLAN.md](docs/MCP_GATEWAY_AGENT_OPTIMIZATION_PLAN.md)。

## 自我更新

```bash
idh update          # 检查并升级到 PyPI 最新版
idh update --check-only   # 只检查，不升级
idh update --yes    # 跳过确认直接升级
```

通过 `sys.executable -m pip install --upgrade` 在安装环境内升级；失败时会提示用 `pipx upgrade ios-decrypt-hub`。

## 协议

[MIT](./LICENSE)

## 关注

微信搜一搜 **DecryptHub**，点下面二维码也能加公众号。

<p align="center">
  <img src="./wechat-qr.png" alt="微信公众号 DecryptHub" width="168">
</p>

- Telegram：https://t.me/decrypthubteam
- X：https://x.com/decrypthub_
