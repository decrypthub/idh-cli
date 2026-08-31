# idh

[中文](README.md) | **English**

`idh` is the PC-side connector and MCP gateway for IOSDecryptHub. Use `connect` to set
the device address, then bridge the device's Streamable HTTP MCP to local stdio MCP.

> The HTTP/MCP service has no authentication. Use it only on a trusted LAN; do not expose it to the public internet.

## Install

Requires Python 3.10+. Runtime uses the Python standard library only.

Recommended: install with pipx:

```bash
pipx install ios-decrypt-hub
```

Or with pip:

```bash
python3 -m pip install ios-decrypt-hub
```

Upgrade:

```bash
pipx upgrade ios-decrypt-hub
```

## Connect a device

Connect the device first (get the IP from the on-device panel or your LAN):

```bash
idh connect 192.168.100.65:8088
idh devices
```

Connections are saved to `~/.config/idh/connections.json`. Later `devices`, `call`,
`export`, and `mcp` reuse them. List or remove connections:

```bash
idh connect
idh disconnect 192.168.100.65:8088
idh disconnect --all
```

`connect` verifies `/api/stats` first. Use `--force` to save a device that is temporarily
offline. Override the config path with `IDH_CONFIG_PATH`, or pass `--no-saved` to ignore
saved connections for one command.

```bash
idh devices
idh devices --json
```

`idh --devices` is a shortcut for `idh devices`. In `devices --json`, `target_id` is the
unique id of the currently live App process — AI agents and scripts should prefer it.
Bundle ID, app name, index, and MCP URL are convenience selectors only.

A one-off address (not saved):

```bash
idh devices --endpoint http://192.168.1.20:8088
```

## Call MCP from the CLI

One-shot read-only tools:

```bash
idh call <target_id> get_stats
idh call <target_id> query_events \
  --arguments '{"category":"digest","limit":3}' --json
```

Tools that change remote state need an explicit confirm:

```bash
idh call <target_id> set_pause \
  --arguments '{"paused":true}' --allow-mutation
```

Both the aggregate gateway and the single-app proxy enforce this. The proxy adds a
required `allow_mutation` field to mutating remote tools, then strips it locally before
forwarding. Calling the device `/api/mcp` directly skips this check; the device service
has no auth and must stay on a trusted network.

## Export events JSON

Page through all events kept by the current App and write them locally:

```bash
idh export <target_id> --output events.json
idh export <target_id> --category sym --max-blob-bytes 131072 --output aes.json
```

Omit `target_id` when only one device is online. `idh` pins the seq upper bound from the
device, fetches remaining pages, and writes the final JSON atomically via a sibling temp
file. Existing files are not overwritten unless you pass `--force`. Each key/iv/input/output
is capped at 64KB by default; pass `--include-dumps` to also write hexdumps.

Exports may contain keys, plaintext, ciphertext, tokens, paths, and request bodies. Treat
them as sensitive.

## Aggregate MCP gateway

The gateway manages every connected App. Configure the MCP client once:

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

It exposes a fixed tool set so clients do not cache a stale dynamic `tools/list`:

- `idh_list_devices`
- `idh_list_tools`
- `idh_get_tool_schema`
- `idh_call_tool`
- `idh_get_panel_url`

### AI Agent protocol

`idh` does not parse natural language or decide how to analyze a target. That belongs to
the AI Agent. `idh` only supplies live facts, real on-device tool descriptions, parameter
schemas, and deterministic routing.

When a user says “analyze xxxx App”, the Agent should:

1. Call `idh_list_devices` for currently live Apps. Do not reuse historical targets or cached indexes.
2. Match the user’s `xxxx` against returned `app` and `bundle` fields.
3. If there is exactly one clear candidate, keep and use that round’s `target_id`.
4. If several candidates fit, show App, Bundle ID, and device and ask the user. Do not guess.
5. If there is none, tell the user to launch the target App and confirm IOSDecryptHub is injected.
6. Call `idh_list_tools` and read the real on-device descriptions. Do not invent tools.
7. Call `idh_get_tool_schema` for the tool you are about to invoke.
8. Call `idh_call_tool` with `target`, `tool_name`, and `tool_arguments`.
9. Read-only work (query, read, disassemble) may proceed from the user’s goal. Mutating
   tools require an explicit user request before passing `allow_mutation=true`.
10. For stacks or branch addresses, check `symbolicate.symbol_source/confidence` first.
    Prefer `function_start` / `disassemble_function.resolved_start`; do not guess a
    function head from prologue bytes alone.
11. If xref/string/selector/function scans report `scan.coverage_complete=false`, keep
    paging with `scan.next_scan_offset`. Do not claim “no references” until coverage is complete.
12. Full export uses `export_events`. Keep `cursor.snapshot_until_seq` stable across pages
    and continue with `cursor.next_after_seq` until `cursor.has_more=false`.

Example:

```text
User: analyze recent crypto activity in Example App
Agent → idh_list_devices({})
Agent: pick the unique candidate from app/bundle, get target_id
Agent → idh_list_tools({"target":"<target_id>","query":"crypto"})
Agent → idh_get_tool_schema({"target":"<target_id>","tool_name":"query_events"})
Agent → idh_call_tool({
  "target":"<target_id>",
  "tool_name":"query_events",
  "tool_arguments":{"category":"all","limit":100}
})
```

This toolchain supplies facts and execution. Whether to call `query_events` or another
tool is the Agent’s call from the user’s goal and the on-device description/schema — not
from keywords baked into `idh`.

If the Agent should pick a live target itself, use the aggregate gateway `idh mcp`.
The transparent proxy’s target is fixed at process start, which fits cases where the user
or an upstream system already chose the target.

## Single-app transparent proxy

When you always analyze one App, the proxy exposes remote tools and their full schemas
as-is:

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

If several devices run the same Bundle ID, use the `target_id` from `idh devices --json`,
or pass a unique MCP URL. The proxy exits if the target is not connected at startup.

Local Simulator:

```bash
idh mcp --target 1 --endpoint http://127.0.0.1:8088
```

Logs go to stderr. stdout is reserved for line-delimited JSON-RPC stdio messages.

## Connection status

- `devices` / `connect` probe every saved connection via `/api/stats`. Offline devices
  show as `offline`.
- Before routing (`resolve_live_target`), the target is rechecked over HTTP. Offline
  connections are filtered out.

## Development

```bash
uv sync --extra dev
uv run python -m pytest tests/ -q
uv run ruff check src/ tests/
uv run python -m build
```

See [MCP_GATEWAY_AGENT_OPTIMIZATION_PLAN.md](docs/MCP_GATEWAY_AGENT_OPTIMIZATION_PLAN.md)
for implementation and acceptance notes.

## Self-update

```bash
idh update          # check and upgrade to the latest PyPI release
idh update --check-only   # check only
idh update --yes    # upgrade without prompting
```

Upgrades with `sys.executable -m pip install --upgrade` inside the install env. On
failure it suggests `pipx upgrade ios-decrypt-hub`.

## License

[MIT](./LICENSE)

## Follow

Search **DecryptHub** in WeChat, or scan the QR below.

<p align="center">
  <img src="./wechat-qr.png" alt="WeChat Official Account DecryptHub" width="168">
</p>

- Telegram: https://t.me/decrypthubteam
- X: https://x.com/decrypthub_
