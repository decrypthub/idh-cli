from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.client import HTTPConnection, HTTPException
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .config import (
    clear_endpoints,
    config_path,
    load_saved_endpoints,
    load_selected,
    remove_endpoint,
    save_endpoint,
    save_selected,
)
from .gateway import (
    GatewayServer,
    TransparentProxy,
    inventory,
    is_mutating_tool,
    resolve_target,
    serve_stdio,
)
from .http_mcp import MCPHTTPClient, MCPTransportError, probe_endpoint
from .models import AppEndpoint
from .prompts import maybe_update_prompts
from .selfupdate import (
    check_for_update,
    detect_install_method,
    maybe_auto_update,
    run_upgrade,
)
from .settings import load_settings, update_settings
from .status import status
from .usbmux import UsbMuxError, resolve_endpoint, usb_endpoint, usbmux_devices

PROBE_TIMEOUT = 3.0


class UsageError(Exception):
    """The command line is missing a selector or a credential."""


def _manual_endpoints(values: Sequence[str], *, include_saved: bool = True) -> list[AppEndpoint]:
    endpoints = list(load_saved_endpoints()) if include_saved else []
    seen = {endpoint.mcp_url.casefold() for endpoint in endpoints}
    for value in values:
        if value == "usb" or value.startswith("usb:"):
            manual = _pick_usb_endpoint(value[4:] or None)
        else:
            manual = AppEndpoint.from_url(value)
        key = manual.mcp_url.casefold()
        if key in seen:
            continue
        endpoints.append(manual)
        seen.add(key)
    return endpoints


def _pick_usb_endpoint(udid: str | None = None) -> AppEndpoint:
    """frida -U 等价入口：usb 或 usb:<udid>。单设备免选，多设备按 udid 选。"""
    try:
        devices = usbmux_devices()
    except UsbMuxError as exc:
        raise ValueError(f"cannot reach usbmuxd: {exc}") from exc
    if udid:
        matches = [device for device in devices if device["udid"].casefold() == udid.casefold()]
        if not matches:
            raise ValueError(f"usb device not attached: {udid}")
    elif len(devices) == 1:
        matches = devices
    elif not devices:
        raise ValueError("no USB devices attached")
    else:
        lines = "\n".join(f"  {device['udid']}" for device in devices)
        raise ValueError(f"multiple USB devices attached; use usb:<udid>\n{lines}")
    return usb_endpoint(matches[0]["udid"])


def _probed_endpoints(endpoints: Sequence[AppEndpoint], *, timeout: float = 1.0) -> list[AppEndpoint]:
    if not endpoints:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(endpoints))) as pool:
        return list(pool.map(lambda e: probe_endpoint(resolve_endpoint(e), timeout=timeout), endpoints))


def _endpoint_label(endpoint: AppEndpoint) -> str:
    kind = endpoint.kind or "unrecognized"
    name = "idhjd" if endpoint.kind == "device" else endpoint.app_name
    return f"{endpoint.key}: {endpoint.primary_address}:{endpoint.port} ({kind}, {name})"


def _address_matches(endpoint: AppEndpoint, value: str) -> bool:
    folded = value.strip().casefold()
    return folded in {
        f"{endpoint.primary_address}:{endpoint.port}".casefold(),
        endpoint.base_url.casefold(),
        endpoint.mcp_url.casefold(),
        endpoint.key.casefold(),
    }


def _resolve_device(
    endpoints: Sequence[AppEndpoint], target: str | None, *, command: str
) -> AppEndpoint:
    """解析一条连接。地址、连接 ID 或 App 的 bundle 都可以。未指定时只用唯一在线连接。"""
    probed = _probed_endpoints(endpoints)
    if target and target.strip():
        matches = [endpoint for endpoint in probed if _address_matches(endpoint, target)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise SystemExit(
                f"idh: {target} matches multiple connections; pass one address or connection id\n"
                + "\n".join(f"  {_endpoint_label(endpoint)}" for endpoint in matches)
            )
        try:
            return resolve_target(probed, target)
        except LookupError as exc:
            raise SystemExit(f"idh: {exc}") from exc
    online = [endpoint for endpoint in probed if endpoint.properties.get("status") == "online"]
    if len(online) == 1:
        return online[0]
    if len(online) > 1:
        raise SystemExit(
            f"idh: {len(online)} connections online; specify an address or connection id\n"
            + "\n".join(f"  {_endpoint_label(endpoint)}" for endpoint in online)
        )
    offline = ", ".join(endpoint.base_url for endpoint in probed) or "none saved"
    raise SystemExit(
        f"idh: no online connection for {command} ({offline})\n"
        f"  idh connect <device IP>:8088"
    )


def _device_client(endpoint: AppEndpoint) -> MCPHTTPClient:
    endpoint = resolve_endpoint(endpoint)
    if endpoint.mcp_url != endpoint.base_url + "/api/mcp":
        raise UsageError("idh: the device endpoint does not expose a session MCP URL")
    return MCPHTTPClient(endpoint)


def _serve_device_session(endpoint: AppEndpoint) -> int:
    try:
        client = _device_client(endpoint)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    def handle(message):
        method = message.get("method") if isinstance(message, dict) else None
        identity = message.get("id") if isinstance(message, dict) else None
        params = message.get("params") if isinstance(message, dict) else None
        name = params.get("name") if isinstance(params, dict) else None
        try:
            reply = client.send(message)
            if method == "initialize" and isinstance(reply, dict) and "error" not in reply:
                if reply.get("result", {}).get("serverInfo", {}).get("name") != "idhjd":
                    raise MCPTransportError("expected the device session service")
            return reply
        except (MCPTransportError, UsageError) as error:
            if identity is None:
                return None
            return {"jsonrpc": "2.0", "id": identity, "error": {"code": -32000, "message": str(error)}}

    serve_stdio(handle)
    return 0


def _add_endpoint_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--endpoint",
        action="append",
        default=[],
        metavar="URL",
        help="add an HTTP endpoint manually; repeatable",
    )
    parser.add_argument("--no-saved", action="store_true", help="ignore addresses saved by idh connect for this run")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="idh", description="IOSDecryptHub connection & MCP gateway")
    parser.add_argument("--version", action="version", version=f"idh {__version__}")
    parser.add_argument(
        "--no-auto-update",
        action="store_true",
        help="disable auto-update for this run",
    )
    parser.add_argument(
        "--force-update",
        action="store_true",
        help="force an auto-update check for this run",
    )
    subparsers = parser.add_subparsers(dest="command")

    connect = subparsers.add_parser("connect", help="save and connect a device address")
    connect.add_argument("endpoint", nargs="?", help="device address (192.168.100.65:8088), usb, or usb:<udid>")
    connect.add_argument("--timeout", type=float, default=PROBE_TIMEOUT, help="HTTP probe timeout in seconds")
    connect.add_argument("--force", action="store_true", help="save the address even when the device is unreachable")
    connect.add_argument("--json", action="store_true", help="output JSON")

    disconnect = subparsers.add_parser("disconnect", help="remove a saved device address")
    disconnect.add_argument("endpoint", nargs="?", help="device address to remove")
    disconnect.add_argument("--all", action="store_true", help="remove all saved addresses")

    devices = subparsers.add_parser("devices", help="list saved devices and --endpoint targets")
    devices.add_argument("--json", action="store_true", help="output JSON")
    _add_endpoint_options(devices)

    inventory_parser = subparsers.add_parser("status", help="read-only connection and live App facts for desktop Agents")
    inventory_parser.add_argument("--json", action="store_true")
    inventory_parser.add_argument("--timeout", type=float, default=PROBE_TIMEOUT)
    _add_endpoint_options(inventory_parser)

    tools = subparsers.add_parser("tools", help="read the selected App's real MCP tools and argument schemas")
    tools.add_argument("--target", help="current target_id returned by status or devices")
    tools.add_argument("--json", action="store_true")
    _add_endpoint_options(tools)

    mcp = subparsers.add_parser("mcp", help="start the stdio MCP gateway")
    mcp.add_argument("--target", help="transparent proxy to one app; omit for the aggregate gateway")
    mcp.add_argument("--device-session", action="store_true", help="connect to the device session service over a loopback forward")
    _add_endpoint_options(mcp)

    call = subparsers.add_parser("call", help="call an MCP tool on a device (defaults to the only online device)")
    call.add_argument("target", nargs="?", help="address, connection id, or app bundle; omit with one online connection")
    call.add_argument("tool_name", nargs="?", help="remote MCP tool name")
    call.add_argument("--arguments", default="{}", metavar="JSON", help="tool arguments as a JSON object")
    call.add_argument("--allow-mutation", action="store_true", help="allow tools that mutate remote state")
    call.add_argument("--json", action="store_true", help="output the full MCP tool result JSON")
    _add_endpoint_options(call)

    export = subparsers.add_parser("export", help="export retained events to a local JSON file")
    export.add_argument("target", nargs="?", help="target_id from `idh devices`; omit with a single online device")
    export.add_argument("--output", "-o", metavar="PATH", help="output path (default: timestamped file in the current directory)")
    export.add_argument("--force", action="store_true", help="replace an existing output file")
    export.add_argument(
        "--category",
        choices=("all", "digest", "hmac", "sym", "asym", "file", "sys", "net", "keychain", "other"),
        default="all",
        help="event category (default: all)",
    )
    export.add_argument("--query", default="", help="keyword filter")
    export.add_argument("--after-seq", type=int, default=0, help="export events after this seq")
    export.add_argument("--until-seq", type=int, help="inclusive upper seq bound")
    export.add_argument("--since-ts-ms", type=int, help="minimum event timestamp in epoch milliseconds")
    export.add_argument("--until-ts-ms", type=int, help="maximum event timestamp in epoch milliseconds")
    export.add_argument("--page-size", type=int, default=10, help="records requested per page (1-100, default 10)")
    export.add_argument(
        "--max-blob-bytes",
        type=int,
        default=64 * 1024,
        help="max bytes per key/iv/input/output field (0-1048576, default 65536)",
    )
    export.add_argument("--include-dumps", action="store_true", help="include hexdumps in addition to hex")
    _add_endpoint_options(export)

    panel = subparsers.add_parser("panel", help="serve the device page on this computer")
    panel.add_argument("--bind", default="127.0.0.1:8766", help="local address for the page")
    _add_endpoint_options(panel)

    update = subparsers.add_parser("update", help="check for and upgrade idh to the latest version")
    update.add_argument("--check-only", action="store_true", help="only check the latest PyPI version, do not upgrade")
    update.add_argument("--yes", "-y", action="store_true", help="upgrade without confirmation")

    settings = subparsers.add_parser("settings", help="view or change idh settings")
    settings.add_argument("--json", action="store_true", help="output settings as JSON")
    settings.add_argument("--auto-update", choices=("on", "off"), help="enable/disable automatic idh updates")
    settings.add_argument("--update-interval", type=float, metavar="SECONDS", help="seconds between auto-update checks")
    settings.add_argument("--prompt-interval", type=float, metavar="SECONDS", help="seconds between prompt/skill refreshes")
    settings.add_argument("--prompt-registry", metavar="URL", help="prompt/skill registry index URL")
    return parser


def _normalize_argv(argv: Sequence[str]) -> list[str]:
    values = list(argv)
    if values and values[0] == "--devices":
        return ["devices", *values[1:]]
    return values


def _print_inventory(data: dict[str, object]) -> None:
    devices = data.get("devices", [])
    if not devices:
        print("no saved or specified IOSDecryptHub devices")
        print("run: idh connect <device IP>:8088")
        return
    online_count = 0
    total = 0
    for device in devices:
        print(f"{device['name']}")
        for app in device["apps"]:
            total += 1
            status = app["properties"].get("status", "unknown")
            online = status == "online"
            online_count += 1 if online else 0
            flag = "✓" if online else "✗"
            print(f"  [{app['index']}] {flag} {app['app']}  {app['device']}:{app['port']}")
            print(f"      target: {app['id']}")
            print(f"      MCP: {app['mcp']}")
    print(f"\n{online_count}/{total} online")


def _run_connect(args: argparse.Namespace) -> int:
    if not args.endpoint:
        endpoints = load_saved_endpoints()
        data = inventory(endpoints)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(f"config: {config_path()}")
            _print_inventory(data)
        return 0
    try:
        if args.endpoint == "usb" or args.endpoint.startswith("usb:"):
            endpoint = _pick_usb_endpoint(args.endpoint[4:] or None)
        else:
            endpoint = AppEndpoint.from_url(args.endpoint)
    except ValueError as exc:
        print(f"idh: {exc}", file=sys.stderr)
        return 2
    probed = probe_endpoint(resolve_endpoint(endpoint), timeout=max(0.1, args.timeout))
    online = probed.properties.get("status") == "online"
    if not online and not args.force:
        print(
            f"idh: cannot reach {endpoint.base_url}; make sure the target app is running, or use --force to save",
            file=sys.stderr,
        )
        return 1
    if probed.kind not in {"app", "device"}:
        for saved in load_saved_endpoints():
            if saved.mcp_url.casefold() == endpoint.mcp_url.casefold() and saved.kind:
                probed = probed.with_kind(saved.kind)
                break
    added = save_endpoint(probed)
    result = {
        "saved": True,
        "added": added,
        "config": str(config_path()),
        "endpoint": probed.as_dict(),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        state = "connected and saved" if online else "device unreachable, saved anyway"
        duplicate = " (already exists)" if not added else ""
        print(f"{state}{duplicate}: {endpoint.base_url}")
        if online and probed.kind == "device":
            print(f"  Device: idhjd  apps {probed.properties.get('app_count', '0')}")
            print(f"  MCP: {probed.mcp_url}")
        elif online:
            print(f"  App: {probed.app_name}  {probed.bundle_id or '-'}")
            print(f"  MCP: {probed.mcp_url}")
    return 0


def _run_disconnect(args: argparse.Namespace) -> int:
    if args.all:
        count = clear_endpoints()
        print(f"removed {count} saved connection(s)")
        return 0
    if not args.endpoint:
        print("idh: disconnect needs an address, or use --all", file=sys.stderr)
        return 2
    try:
        removed = remove_endpoint(args.endpoint)
    except ValueError as exc:
        print(f"idh: {exc}", file=sys.stderr)
        return 2
    if not removed:
        print(f"idh: no saved connection found: {args.endpoint}", file=sys.stderr)
        return 1
    print(f"removed: {AppEndpoint.from_url(args.endpoint).base_url}")
    return 0


def _usb_available(endpoints: Sequence[AppEndpoint]) -> list[dict]:
    saved = {endpoint.properties.get("usb_udid") for endpoint in endpoints}
    try:
        devices = usbmux_devices(timeout=1.0)
    except UsbMuxError:
        return []
    return [device for device in devices if device["udid"] not in saved]


def _run_devices(args: argparse.Namespace) -> int:
    endpoints = _manual_endpoints(args.endpoint, include_saved=not args.no_saved)
    data = inventory(endpoints)
    available = _usb_available(endpoints)
    if args.json:
        if available:
            data["usb_available"] = available
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_inventory(data)
        for device in available:
            print(f"  [usb] {device['udid']}  (connect: idh connect usb:{device['udid']})")
    return 0


def _run_status(args: argparse.Namespace) -> int:
    endpoints = _manual_endpoints(args.endpoint, include_saved=not args.no_saved)
    print(json.dumps(status(endpoints, timeout=args.timeout), ensure_ascii=False, indent=2))
    return 0


def _run_tools(args: argparse.Namespace) -> int:
    endpoints = _manual_endpoints(args.endpoint, include_saved=not args.no_saved)
    try:
        endpoint = _resolve_device(endpoints, args.target, command="tools")
        client = _device_client(endpoint) if endpoint.kind == "device" else MCPHTTPClient(endpoint, timeout=10.0)
        client.ensure_initialized()
        response = client.send({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        result = response.get("result") if isinstance(response, dict) and "error" not in response else None
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            print("idh: invalid tools/list response", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (SystemExit, MCPTransportError) as exc:
        print(f"idh: {exc}", file=sys.stderr)
        return 1


def _run_mcp(args: argparse.Namespace) -> int:
    if args.device_session:
        return _run_device_session_mcp(args)
    endpoints = _manual_endpoints(args.endpoint, include_saved=not args.no_saved)
    if not endpoints:
        print(
            "idh: no devices; run idh connect <device IP>:8088 or pass --endpoint",
            file=sys.stderr,
        )
        return 2
    try:
        if args.target:
            endpoint = _resolve_device(endpoints, args.target, command="mcp")
        else:
            online = [item for item in _probed_endpoints(endpoints) if item.properties.get("status") == "online"]
            if len(online) == 1:
                endpoint = online[0]
            elif any(item.kind == "device" for item in online):
                print(
                    "idh: more than one connection is online; pass an address or connection id",
                    file=sys.stderr,
                )
                return 2
            else:
                handler = GatewayServer(lambda: endpoints).handle
                serve_stdio(handler)
                return 0
    except (SystemExit, UsageError) as exc:
        print(str(exc), file=sys.stderr)
        return 2 if isinstance(exc, UsageError) else 1
    if endpoint.kind == "device":
        return _serve_device_session(endpoint)
    print(f"idh: proxying to {endpoint.base_url} ({endpoint.app_name})", file=sys.stderr)
    serve_stdio(TransparentProxy(lambda: endpoints, endpoint.key).handle)
    return 0


def _run_device_session_mcp(args: argparse.Namespace) -> int:
    if args.target or len(args.endpoint) != 1:
        print("idh: --device-session requires exactly one loopback --endpoint", file=sys.stderr)
        return 2
    try:
        endpoint = AppEndpoint.from_url(args.endpoint[0])
    except ValueError:
        print("idh: invalid device-session endpoint", file=sys.stderr)
        return 2
    return _serve_device_session(endpoint)


def _run_call(args: argparse.Namespace) -> int:
    try:
        tool_arguments = json.loads(args.arguments)
    except json.JSONDecodeError as exc:
        print(f"idh: --arguments is not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(tool_arguments, dict):
        print("idh: --arguments must be a JSON object", file=sys.stderr)
        return 2
    if args.tool_name is None and args.target:
        args.tool_name = args.target
        args.target = None
    if not args.tool_name:
        print("idh: call needs a tool name", file=sys.stderr)
        return 2

    endpoints = _manual_endpoints(args.endpoint, include_saved=not args.no_saved)
    try:
        endpoint = _resolve_device(endpoints, args.target, command="call")
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if is_mutating_tool(args.tool_name) and not args.allow_mutation:
        print(
            f"idh: tool {args.tool_name} mutates remote state; pass --allow-mutation to confirm",
            file=sys.stderr,
        )
        return 2
    try:
        client = (
            _device_client(endpoint)
            if endpoint.kind == "device"
            else MCPHTTPClient(endpoint)
        )
        client.ensure_initialized()
        response = client.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": args.tool_name, "arguments": tool_arguments},
            }
        )
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except MCPTransportError as exc:
        print(f"idh: {exc}", file=sys.stderr)
        return 1
    if isinstance(response, dict) and "error" in response:
        print(f"idh: remote MCP error: {json.dumps(response['error'], ensure_ascii=False)}", file=sys.stderr)
        return 1
    result = response.get("result", {}) if isinstance(response, dict) else {}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        content = result.get("content", []) if isinstance(result, dict) else []
        texts = [item.get("text") for item in content if isinstance(item, dict) and item.get("text")]
        if texts:
            print("\n".join(texts))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if isinstance(result, dict) and result.get("isError") else 0


def _export_page(client: MCPHTTPClient, arguments: dict[str, object], request_id: int) -> dict[str, object]:
    response = client.send(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "export_events", "arguments": arguments},
        }
    )
    if not isinstance(response, dict):
        raise TypeError("remote export_events returned no valid response")
    if "error" in response:
        raise ValueError(f"remote MCP error: {json.dumps(response['error'], ensure_ascii=False)}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise TypeError("remote export_events response is missing result")
    if result.get("isError"):
        content = result.get("content")
        if isinstance(content, list):
            messages = [
                item.get("text")
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            if messages:
                raise ValueError("; ".join(messages))
        raise ValueError("remote export_events failed")
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        raise TypeError("remote export_events returned no structuredContent; update IOSDecryptHub")
    if not isinstance(structured.get("events"), list) or not isinstance(structured.get("cursor"), dict):
        raise TypeError("remote export_events returned an invalid page")
    return structured


def _safe_filename_part(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in ".-_" else "_" for char in value)
    return cleaned.strip("._") or "app"


def _run_export(args: argparse.Namespace) -> int:
    if args.after_seq < 0 or (args.until_seq is not None and args.until_seq < 0):
        print("idh: --after-seq and --until-seq must be >= 0", file=sys.stderr)
        return 2
    if not 1 <= args.page_size <= 100:
        print("idh: --page-size must be between 1 and 100", file=sys.stderr)
        return 2
    if not 0 <= args.max_blob_bytes <= 1024 * 1024:
        print("idh: --max-blob-bytes must be between 0 and 1048576", file=sys.stderr)
        return 2

    endpoints = _manual_endpoints(args.endpoint, include_saved=not args.no_saved)
    try:
        endpoint = _resolve_device(endpoints, args.target, command="export")
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if endpoint.kind == "device":
        print("idh: a device connection reads saved sessions; it does not export app events", file=sys.stderr)
        return 2

    if args.output:
        output = Path(args.output).expanduser().resolve()
    else:
        identity = endpoint.bundle_id or endpoint.app_name
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        output = (Path.cwd() / f"idh-events-{_safe_filename_part(identity)}-{stamp}.json").resolve()
    if output.exists() and not args.force:
        print(f"idh: output already exists: {output} (use --force to replace)", file=sys.stderr)
        return 2

    arguments: dict[str, object] = {
        "category": args.category,
        "after_seq": args.after_seq,
        "limit": args.page_size,
        "max_blob_bytes": args.max_blob_bytes,
        "include_dumps": args.include_dumps,
    }
    if args.query:
        arguments["query"] = args.query
    if args.until_seq is not None:
        arguments["until_seq"] = args.until_seq
    if args.since_ts_ms is not None:
        arguments["since_ts_ms"] = args.since_ts_ms
    if args.until_ts_ms is not None:
        arguments["until_ts_ms"] = args.until_ts_ms

    temp_path: Path | None = None
    try:
        client = MCPHTTPClient(endpoint, timeout=30.0)
        client.ensure_initialized()
        page = _export_page(client, arguments, 1)
        cursor = page["cursor"]
        snapshot_until = cursor.get("snapshot_until_seq")
        if not isinstance(snapshot_until, int):
            raise TypeError("remote export_events cursor is missing snapshot_until_seq")
        arguments["until_seq"] = snapshot_until

        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp:
            temp_path = Path(temp.name)
            metadata = {
                "format": "iosdecrypthub.export.v1",
                "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "source": endpoint.as_dict(),
                "server_version": page.get("server_version"),
                "process": page.get("process", {}),
                "start_after_seq": args.after_seq,
                "snapshot_until_seq": snapshot_until,
                "filters": {
                    key: value
                    for key, value in arguments.items()
                    if key not in {"after_seq", "until_seq", "limit"}
                },
                "retention_note": page.get("retention_note"),
                "sensitive_data_warning": page.get("sensitive_data_warning"),
            }
            prefix = json.dumps(metadata, ensure_ascii=False, indent=2).rstrip()
            temp.write(prefix[:-1])
            temp.write(',\n  "events": [\n')

            count = 0
            first_event = True
            request_id = 2
            previous_after = args.after_seq
            while True:
                events = page["events"]
                for event in events:
                    if not isinstance(event, dict):
                        raise TypeError("remote export_events page contains a non-object event")
                    if not first_event:
                        temp.write(",\n")
                    temp.write("    ")
                    temp.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
                    first_event = False
                    count += 1

                cursor = page["cursor"]
                if not cursor.get("has_more"):
                    break
                next_after = cursor.get("next_after_seq")
                if not isinstance(next_after, int) or next_after <= previous_after:
                    raise ValueError("remote export_events cursor did not advance")
                if cursor.get("snapshot_until_seq") != snapshot_until:
                    raise ValueError("remote export_events changed snapshot_until_seq during paging")
                previous_after = next_after
                arguments["after_seq"] = next_after
                page = _export_page(client, arguments, request_id)
                request_id += 1

            temp.write(f'\n  ],\n  "count": {count}\n}}\n')
            temp.flush()
            os.fsync(temp.fileno())
        if output.exists() and not args.force:
            raise FileExistsError(f"output appeared during export: {output} (use --force to replace)")
        os.replace(temp_path, output)
    except (MCPTransportError, OSError, TypeError, ValueError) as exc:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        print(f"idh: export failed: {exc}", file=sys.stderr)
        return 1

    print(f"exported {count} event(s) from {endpoint.app_name} to {output}")
    print("warning: the file may contain keys, plaintext, ciphertext, tokens, and request data", file=sys.stderr)
    return 0


def _run_update(args: argparse.Namespace) -> int:
    info = check_for_update()
    current = info["current"]
    latest = info["latest"]
    if not latest:
        print("idh: cannot check the latest PyPI version (network unreachable)", file=sys.stderr)
        return 1
    if not info["update_available"]:
        print(f"idh is already up to date ({current})")
        return 0
    print(f"new version available: {current} -> {latest}")
    method = detect_install_method()
    print(f"install method: {method}")
    if args.check_only:
        return 0
    if not args.yes:
        try:
            confirm = input("upgrade now? [y/N] ")
        except EOFError:
            confirm = ""
        if confirm.strip().lower() != "y":
            print("cancelled")
            return 0
    print(f"upgrading idh -> {latest} ...")
    ok, output = run_upgrade(method, capture=True)
    if output:
        print(output)
    if not ok:
        print(f"idh: upgrade failed: {output}", file=sys.stderr)
        print(f"idh: run manually: {method} upgrade", file=sys.stderr)
        return 1
    print(f"upgrade complete, current version: {latest}")
    return 0


def _run_settings(args: argparse.Namespace) -> int:
    changes: dict[str, object] = {}
    if args.auto_update:
        changes["auto_update"] = args.auto_update == "on"
    if args.update_interval is not None:
        changes["update_interval"] = max(0.0, args.update_interval)
    if args.prompt_interval is not None:
        changes["prompt_interval"] = max(0.0, args.prompt_interval)
    if args.prompt_registry:
        changes["prompt_registry"] = args.prompt_registry.strip()
    settings = update_settings(**changes) if changes else load_settings()
    if args.json:
        print(json.dumps(settings, ensure_ascii=False, indent=2))
    else:
        print(f"auto_update: {str(settings['auto_update']).lower()}")
        print(f"update_interval: {int(settings['update_interval'])}")
        print(f"last_update_check: {settings['last_update_check']}")
        print(f"last_update_version: {settings['last_update_version']}")
        print(f"prompt_registry: {settings['prompt_registry']}")
        print(f"prompt_interval: {int(settings['prompt_interval'])}")
        print(f"last_prompt_check: {settings['last_prompt_check']}")
    return 0


def _run_auto_update(args: argparse.Namespace) -> None:
    if getattr(args, "no_auto_update", False):
        return
    force = bool(getattr(args, "force_update", False))
    with contextlib.suppress(Exception):
        maybe_update_prompts(force=force, timeout=3.0)
    if args.command == "mcp":
        thread = threading.Thread(
            target=maybe_auto_update,
            kwargs={"force": force, "allow_upgrade": True},
            daemon=True,
        )
        thread.start()
        return
    with contextlib.suppress(Exception):
        maybe_auto_update(force=force, allow_upgrade=True)


_PANEL_SESSION_ROUTE = re.compile(r"/api/sessions(?:/[A-Za-z0-9_-]{1,64}(?:/events)?)?")
_PANEL_APP_EVENTS_ROUTE = re.compile(r"/api/apps/[A-Za-z0-9][A-Za-z0-9._-]{0,254}/events")
_PANEL_APP_ICON_ROUTE = re.compile(r"/api/apps/[A-Za-z0-9][A-Za-z0-9._-]{0,254}/icon")
_PANEL_SETTINGS_ROUTE = "/api/session-settings"
_PANEL_SETTINGS_MAX_BYTES = 4096
# 设备侧注入接口（GET 读 / POST 写）与本机设备注册表
_PANEL_DEVICE_READ = {"/api/apps", "/api/injection-scope"}
_PANEL_DEVICE_WRITE = {"/api/injection-scope", "/api/apps/relaunch", "/api/apps/clear"}
_PANEL_DEVICES_ROUTE = "/api/devices"
_BUNDLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}")


def _panel_request(
    endpoint: AppEndpoint, path: str, *, body: bytes | None = None
) -> tuple[int, object]:
    endpoint = resolve_endpoint(endpoint)
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    with contextlib.closing(HTTPConnection(endpoint.primary_address, endpoint.port, timeout=3)) as connection:
        connection.request("GET" if body is None else "POST", path, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read() if response.status == 200 or path == _PANEL_SETTINGS_ROUTE else b""
        return response.status, json.loads(payload) if payload else None


def _panel_blob(endpoint: AppEndpoint, path: str) -> tuple[int, bytes]:
    endpoint = resolve_endpoint(endpoint)
    with contextlib.closing(HTTPConnection(endpoint.primary_address, endpoint.port, timeout=3)) as connection:
        connection.request("GET", path, headers={"Accept": "image/png"})
        response = connection.getresponse()
        return response.status, response.read() if response.status == 200 else b""


def _run_panel(args: argparse.Namespace) -> int:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    endpoints = _manual_endpoints(args.endpoint, include_saved=not args.no_saved)
    try:
        endpoint = _resolve_device(endpoints, None, command="panel")
    except SystemExit:
        # 多设备在线不报错退出：取第一台在线设备，页面里可切换
        endpoint = next(
            (e for e in _probed_endpoints(endpoints)
             if e.kind == "device" and e.properties.get("status") == "online"),
            None,
        )  # 零设备时为 None：面板照常起，由页面里的设备入口添加
    if endpoint is not None and endpoint.kind != "device":
        print("idh: panel serves a device connection", file=sys.stderr)
        return 2
    host, _, port_text = args.bind.rpartition(":")
    host = host or "127.0.0.1"
    try:
        port = int(port_text)
        if host not in {"127.0.0.1", "localhost"} or not 0 <= port <= 65535:
            raise ValueError
    except ValueError:
        print("idh: --bind must use 127.0.0.1 or localhost and a valid port", file=sys.stderr)
        return 2
    saved_selected = load_selected()
    if saved_selected:
        for saved in load_saved_endpoints():
            if saved.mcp_url.casefold() == saved_selected.casefold() and saved.kind == "device":
                endpoint = saved
                break
    current = {"endpoint": endpoint}

    def device_pool() -> list[AppEndpoint]:
        merged = {e.mcp_url.casefold(): e for e in endpoints}
        for entry in load_saved_endpoints():
            if entry.kind == "device":
                merged[entry.mcp_url.casefold()] = entry
        return list(merged.values())

    def device_records() -> dict:
        saved = device_pool()
        probed = [item for item in _probed_endpoints(saved, timeout=3.0) if item.kind != "app"]
        selected = current["endpoint"].mcp_url if current["endpoint"] else ""
        return {
            "devices": [
                {
                    "id": item.mcp_url,
                    "address": item.base_url,
                    "kind": item.kind,
                    "transport": item.properties.get("transport"),
                    "online": item.properties.get("status") == "online",
                    "selected": item.mcp_url == selected,
                }
                for item in probed
            ],
            "usb": [device["udid"] for device in _usb_available(saved)],
            "selected": selected,
        }

    try:
        if current["endpoint"] is not None:
            code, health = _panel_request(current["endpoint"], "/health")
            if code != 200 or not isinstance(health, dict) or health.get("service") != "idhjd":
                raise UsageError("idh: panel serves a device connection")
        panel_files = files("idh")
        device_url = current["endpoint"].base_url if current["endpoint"] else ""
        metadata = f'<meta name="idh-device-endpoint" content="{device_url}">'.encode()
        page = panel_files.joinpath("panel.html").read_bytes().replace(
            b"<!-- IDH_DEVICE_ENDPOINT -->", metadata
        )
        assets = {
            "/wechat-follow.png": (panel_files.joinpath("wechat-follow.png").read_bytes(), "image/png"),
        }
    except (HTTPException, OSError, ValueError, UsageError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    class Handler(BaseHTTPRequestHandler):
        timeout = 5

        def valid_host(self) -> bool:
            allowed_hosts = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            if self.server.server_port == 80:
                allowed_hosts.update(("127.0.0.1", "localhost"))
            hosts = self.headers.get_all("Host") or []
            return len(hosts) == 1 and hosts[0] in allowed_hosts

        def write_body(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def write_json(self, code: int, data: object) -> None:
            self.write_body(code, json.dumps(data).encode(), "application/json")

        def relay_settings(self, body: bytes | None = None) -> None:
            endpoint = current["endpoint"]
            if not endpoint:
                self.write_json(502, {"error": "device_unavailable"})
                return
            try:
                code, data = _panel_request(endpoint, _PANEL_SETTINGS_ROUTE, body=body)
            except (HTTPException, OSError, ValueError, UsageError):
                self.write_json(502, {"error": "device_unavailable"})
                return
            if code not in {200, 400, 401, 403, 404, 409, 500}:
                self.write_json(502, {"error": "device_unavailable"})
                return
            self.write_json(code, data if isinstance(data, dict) else {"error": "settings_unavailable"})

        def device_action(self, body: bytes) -> None:
            try:
                request = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                request = None
            if not isinstance(request, dict):
                self.write_json(400, {"error": "invalid_device_request"})
                return
            action = request.get("action")
            if action == "add":
                udid = request.get("usb")
                try:
                    if udid:
                        endpoint = _pick_usb_endpoint(str(udid))
                    else:
                        endpoint = AppEndpoint.from_url(str(request.get("address") or ""))
                except ValueError:
                    self.write_json(400, {"error": "invalid_address"})
                    return
                probed = probe_endpoint(resolve_endpoint(endpoint), timeout=3)
                if probed.properties.get("status") == "online" and probed.kind != "device":
                    self.write_json(400, {"error": "not_a_device"})
                    return
                save_endpoint(probed)
                self.write_json(200, device_records())
                return
            target = str(request.get("id") or "")
            if action == "select":
                for entry in device_pool():
                    if entry.mcp_url.casefold() == target.casefold():
                        if any(e.mcp_url.casefold() == target.casefold() for e in load_saved_endpoints()):
                            save_selected(entry.mcp_url)
                        current["endpoint"] = entry
                        self.write_json(200, device_records())
                        return
                self.write_json(404, {"error": "unknown_device"})
                return
            if action == "remove":
                try:
                    removed = remove_endpoint(target)
                except ValueError:
                    removed = False
                if not removed:
                    self.write_json(404, {"error": "unknown_device"})
                    return
                if current["endpoint"] and current["endpoint"].mcp_url.casefold() == target.casefold():
                    save_selected(next((e.mcp_url for e in load_saved_endpoints() if e.kind == "device"), ""))
                    current["endpoint"] = next((e for e in load_saved_endpoints() if e.kind == "device"), None)
                self.write_json(200, device_records())
                return
            self.write_json(400, {"error": "invalid_device_request"})

        def do_POST(self) -> None:
            if not self.valid_host():
                self.send_error(400)
                return
            allowed = {_PANEL_SETTINGS_ROUTE, _PANEL_DEVICES_ROUTE} | _PANEL_DEVICE_WRITE
            if self.path not in allowed:
                self.send_error(404)
                return
            if self.headers.get_all("Origin") != [f"http://{self.headers['Host']}"]:
                self.write_json(403, {"error": "origin_required"})
                return
            lengths = self.headers.get_all("Content-Length") or []
            if (len(lengths) != 1 or re.fullmatch(r"[0-9]{1,4}", lengths[0]) is None or
                    self.headers.get("Transfer-Encoding") or
                    self.headers.get_content_type() != "application/json"):
                self.write_json(400, {"error": "invalid_settings"})
                return
            length = int(lengths[0])
            if not 0 < length <= _PANEL_SETTINGS_MAX_BYTES:
                self.write_json(400, {"error": "invalid_settings"})
                return
            try:
                body = self.rfile.read(length)
            except OSError:
                self.write_json(408, {"error": "incomplete_settings"})
                return
            if len(body) != length:
                self.write_json(400, {"error": "incomplete_settings"})
                return
            if self.path == _PANEL_SETTINGS_ROUTE:
                self.relay_settings(body)
                return
            if self.path == _PANEL_DEVICES_ROUTE:
                self.device_action(body)
                return
            endpoint = current["endpoint"]
            if not endpoint:
                self.write_json(502, {"error": "device_unavailable"})
                return
            try:
                request = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                request = None
            if not isinstance(request, dict):
                self.write_json(400, {"error": "invalid_request"})
                return
            if self.path in {"/api/apps/relaunch", "/api/apps/clear"}:
                bundle = str(request.get("bundleId") or "")
                if not _BUNDLE_ID.fullmatch(bundle) or bundle.startswith("com.apple."):
                    self.write_json(400, {"error": "invalid_bundle_id"})
                    return
            else:
                ids = [request.get(key, []) for key in ("add", "remove")]
                if any(not isinstance(value, list) or len(value) > 256 or
                       any(not _BUNDLE_ID.fullmatch(str(item)) for item in value)
                       for value in ids):
                    self.write_json(400, {"error": "invalid_bundle_id"})
                    return
            try:
                code, data = _panel_request(endpoint, self.path, body=body)
            except (HTTPException, OSError, ValueError, UsageError):
                self.write_json(502, {"error": "device_unavailable"})
                return
            if code not in {200, 400, 401, 403, 404, 409, 500}:
                self.write_json(502, {"error": "device_unavailable"})
                return
            self.write_json(code, data if isinstance(data, dict) else {"error": "device_unavailable"})

        def do_GET(self) -> None:
            if not self.valid_host():
                self.send_error(400)
                return
            if self.path == _PANEL_SETTINGS_ROUTE:
                self.relay_settings()
                return
            if self.path == _PANEL_DEVICES_ROUTE:
                self.write_json(200, device_records())
                return
            try:
                target = urlsplit(self.path)
            except ValueError:
                self.send_error(400)
                return
            if target.scheme or target.netloc or target.fragment:
                self.send_error(400)
                return
            session_route = _PANEL_SESSION_ROUTE.fullmatch(target.path) and (
                not target.query or target.path.endswith("/events")
            )
            app_events_route = _PANEL_APP_EVENTS_ROUTE.fullmatch(target.path)
            if not target.query and target.path in {"/", "/index.html"}:
                body = page
                kind = "text/html; charset=utf-8"
            elif not target.query and target.path in assets:
                body, kind = assets[target.path]
            elif not target.query and _PANEL_APP_ICON_ROUTE.fullmatch(target.path):
                if current["endpoint"] is None:
                    self.send_error(502)
                    return
                try:
                    code, blob = _panel_blob(current["endpoint"], self.path)
                except (HTTPException, OSError, ValueError, UsageError):
                    self.send_error(502)
                    return
                if code != 200 or not blob:
                    self.send_error(404)
                    return
                self.write_body(200, blob, "image/png")
                return
            elif session_route or app_events_route or self.path == "/health" or (
                not target.query and target.path in _PANEL_DEVICE_READ
            ):
                if current["endpoint"] is None:
                    self.send_error(502)
                    return
                try:
                    code, data = _panel_request(current["endpoint"], self.path)
                except (HTTPException, OSError, ValueError, UsageError):
                    self.send_error(502)
                    return
                if code != 200:
                    self.send_error(code if code in {400, 401, 404} else 502)
                    return
                body = json.dumps(data).encode()
                kind = "application/json"
            else:
                self.send_error(404)
                return
            self.write_body(200, body, kind)

        def log_message(self, *_args: object) -> None:
            return

    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        print(f"idh: {exc}", file=sys.stderr)
        return 1
    print(f"http://{host}:{server.server_port}/", file=sys.stderr, flush=True)
    try:
        with server:
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    parser = build_parser()
    args = parser.parse_args(_normalize_argv(sys.argv[1:] if argv is None else argv))
    try:
        if args.command not in {"update", "settings", "status", "tools"} and not getattr(args, "json", False):
            _run_auto_update(args)
        if args.command == "connect":
            return _run_connect(args)
        if args.command == "disconnect":
            return _run_disconnect(args)
        if args.command == "devices":
            return _run_devices(args)
        if args.command == "status":
            return _run_status(args)
        if args.command == "tools":
            return _run_tools(args)
        if args.command == "mcp":
            return _run_mcp(args)
        if args.command == "panel":
            return _run_panel(args)
        if args.command == "call":
            return _run_call(args)
        if args.command == "export":
            return _run_export(args)
        if args.command == "update":
            return _run_update(args)
        if args.command == "settings":
            return _run_settings(args)
    except ValueError as exc:
        print(f"idh: {exc}", file=sys.stderr)
        return 2
    parser.print_help()
    return 0
