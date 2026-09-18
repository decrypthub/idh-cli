from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import (
    clear_endpoints,
    config_path,
    load_saved_endpoints,
    remove_endpoint,
    save_endpoint,
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

PROBE_TIMEOUT = 3.0


def _manual_endpoints(values: Sequence[str], *, include_saved: bool = True) -> list[AppEndpoint]:
    endpoints = load_saved_endpoints() if include_saved else []
    for value in values:
        endpoints.append(AppEndpoint.from_url(value))
    return list({endpoint.mcp_url: endpoint for endpoint in endpoints}.values())


def _probed_endpoints(endpoints: Sequence[AppEndpoint]) -> list[AppEndpoint]:
    if not endpoints:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(endpoints))) as pool:
        return list(pool.map(probe_endpoint, endpoints))


def _resolve_device(
    endpoints: Sequence[AppEndpoint], target: str | None, *, command: str
) -> AppEndpoint:
    """解析目标设备：显式 target 优先，否则用唯一在线设备。"""
    probed = _probed_endpoints(endpoints)
    if target and target.strip():
        try:
            return resolve_target(probed, target)
        except LookupError as exc:
            raise SystemExit(f"idh: {exc}") from exc
    online = [e for e in probed if e.properties.get("status") == "online"]
    if len(online) == 1:
        return online[0]
    if len(online) > 1:
        raise SystemExit(
            f"idh: {len(online)} devices online; specify --target <target_id> from `idh devices`\n"
            + "\n".join(f"  {e.key}: {e.base_url} ({e.app_name})" for e in online)
        )
    offline = ", ".join(e.base_url for e in probed) or "none saved"
    raise SystemExit(
        f"idh: no online device ({offline})\n"
        f"  make sure the target app is running, then: idh connect <device IP>:8088"
    )


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
    subparsers = parser.add_subparsers(dest="command")

    connect = subparsers.add_parser("connect", help="save and connect a device address")
    connect.add_argument("endpoint", nargs="?", help="device address, e.g. 192.168.100.65:8088")
    connect.add_argument("--timeout", type=float, default=PROBE_TIMEOUT, help="HTTP probe timeout in seconds")
    connect.add_argument("--force", action="store_true", help="save the address even when the device is unreachable")
    connect.add_argument("--json", action="store_true", help="output JSON")

    disconnect = subparsers.add_parser("disconnect", help="remove a saved device address")
    disconnect.add_argument("endpoint", nargs="?", help="device address to remove")
    disconnect.add_argument("--all", action="store_true", help="remove all saved addresses")

    devices = subparsers.add_parser("devices", help="list saved devices and --endpoint targets")
    devices.add_argument("--json", action="store_true", help="output JSON")
    _add_endpoint_options(devices)

    mcp = subparsers.add_parser("mcp", help="start the stdio MCP gateway")
    mcp.add_argument("--target", help="transparent proxy to one app; omit for the aggregate gateway")
    _add_endpoint_options(mcp)

    call = subparsers.add_parser("call", help="call an MCP tool on a device (defaults to the only online device)")
    call.add_argument("target", nargs="?", help="target_id from `idh devices`; omit with a single online device")
    call.add_argument("tool_name", help="remote MCP tool name")
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

    update = subparsers.add_parser("update", help="check for and upgrade idh to the latest version")
    update.add_argument("--check-only", action="store_true", help="only check the latest PyPI version, do not upgrade")
    update.add_argument("--yes", "-y", action="store_true", help="upgrade without confirmation")
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
        endpoint = AppEndpoint.from_url(args.endpoint)
    except ValueError as exc:
        print(f"idh: {exc}", file=sys.stderr)
        return 2
    probed = probe_endpoint(endpoint, timeout=max(0.1, args.timeout))
    online = probed.properties.get("status") == "online"
    if not online and not args.force:
        print(
            f"idh: cannot reach {endpoint.base_url}; make sure the target app is running, or use --force to save",
            file=sys.stderr,
        )
        return 1
    added = save_endpoint(endpoint)
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
        if online:
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


def _run_devices(args: argparse.Namespace) -> int:
    endpoints = _manual_endpoints(args.endpoint, include_saved=not args.no_saved)
    data = inventory(endpoints)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_inventory(data)
    return 0


def _run_mcp(args: argparse.Namespace) -> int:
    endpoints = _manual_endpoints(args.endpoint, include_saved=not args.no_saved)
    if not endpoints:
        print(
            "idh: no devices; run idh connect <device IP>:8088 or pass --endpoint",
            file=sys.stderr,
        )
        return 2
    if args.target:
        handler = TransparentProxy(lambda: endpoints, args.target).handle
    else:
        online = [e for e in _probed_endpoints(endpoints) if e.properties.get("status") == "online"]
        if len(online) == 1:
            target = online[0].key
            print(f"idh: proxying to {online[0].base_url} ({online[0].app_name})", file=sys.stderr)
            handler = TransparentProxy(lambda: endpoints, target).handle
        else:
            handler = GatewayServer(lambda: endpoints).handle
    serve_stdio(handler)
    return 0


def _run_call(args: argparse.Namespace) -> int:
    try:
        tool_arguments = json.loads(args.arguments)
    except json.JSONDecodeError as exc:
        print(f"idh: --arguments is not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(tool_arguments, dict):
        print("idh: --arguments must be a JSON object", file=sys.stderr)
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
        client = MCPHTTPClient(endpoint)
        client.ensure_initialized()
        response = client.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": args.tool_name, "arguments": tool_arguments},
            }
        )
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


def _latest_version() -> str | None:
    try:
        with urllib.request.urlopen(
            "https://pypi.org/pypi/ios-decrypt-hub/json", timeout=5
        ) as resp:
            return json.load(resp).get("info", {}).get("version")
    except Exception:  # noqa: BLE001 - fail silently on network errors
        return None


def _run_update(args: argparse.Namespace) -> int:
    current = __version__
    latest = _latest_version()
    if not latest:
        print("idh: cannot check the latest PyPI version (network unreachable)", file=sys.stderr)
        return 1
    if latest == current:
        print(f"idh is already up to date ({current})")
        return 0
    print(f"new version available: {current} → {latest}")
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
    try:
        print(f"upgrading idh → {latest} ...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "ios-decrypt-hub"],
            check=False,
        )
    except OSError as exc:
        print(f"idh: upgrade failed: {exc}", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print("idh: upgrade failed; run manually: pipx upgrade ios-decrypt-hub", file=sys.stderr)
        return 1
    print(f"upgrade complete, current version: {_latest_version() or latest}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(_normalize_argv(sys.argv[1:] if argv is None else argv))
    try:
        if args.command == "connect":
            return _run_connect(args)
        if args.command == "disconnect":
            return _run_disconnect(args)
        if args.command == "devices":
            return _run_devices(args)
        if args.command == "mcp":
            return _run_mcp(args)
        if args.command == "call":
            return _run_call(args)
        if args.command == "export":
            return _run_export(args)
        if args.command == "update":
            return _run_update(args)
    except ValueError as exc:
        print(f"idh: {exc}", file=sys.stderr)
        return 2
    parser.print_help()
    return 0
