from __future__ import annotations

import json
import sys
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TextIO

from . import __version__
from .http_mcp import MCPHTTPClient, MCPTransportError, probe_endpoint
from .models import AppEndpoint
from .prompts import PromptStore

EndpointProvider = Callable[[], list[AppEndpoint]]


class TargetResolutionError(LookupError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        target: str | None = None,
        candidates: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.target = target
        self.candidates = candidates or []

    def details(self) -> dict[str, Any]:
        return {"target": self.target, "candidates": self.candidates}


def _target_candidate(endpoint: AppEndpoint) -> dict[str, Any]:
    return {
        "target_id": endpoint.key,
        "app": endpoint.app_name,
        "bundle": endpoint.bundle_id,
        "device": endpoint.device_key,
        "mcp": endpoint.mcp_url,
    }


def resolve_target(endpoints: Iterable[AppEndpoint], target: str | None) -> AppEndpoint:
    items = list(endpoints)
    if not items:
        raise TargetResolutionError(
            "no_online_devices",
            "no saved or specified IOSDecryptHub app; run idh connect <device IP>:8088",
            target=target,
            candidates=[],
        )
    if target is None or not target.strip():
        if len(items) == 1:
            return items[0]
        raise TargetResolutionError(
            "target_required",
            "multiple apps found; use the target_id returned by idh_list_devices",
            candidates=[_target_candidate(item) for item in items],
        )

    value = target.strip().casefold()
    if value.isdigit():
        index = int(value) - 1
        if 0 <= index < len(items):
            return items[index]

    exact = [item for item in items if value in item.selectors()]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise TargetResolutionError(
            "ambiguous_target",
            f"target matches multiple apps: {target}; use a unique target_id",
            target=target,
            candidates=[_target_candidate(item) for item in exact],
        )

    partial = [item for item in items if any(value in selector for selector in item.selectors())]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise TargetResolutionError(
            "ambiguous_target",
            f"target matches multiple apps: {target}; use a unique target_id",
            target=target,
            candidates=[_target_candidate(item) for item in partial],
        )
    raise TargetResolutionError(
        "target_not_found",
        f"target not found: {target}",
        target=target,
        candidates=[_target_candidate(item) for item in items],
    )


def resolve_live_target(endpoints: Iterable[AppEndpoint], target: str | None) -> AppEndpoint:
    """Re-check device liveness over HTTP, filtering saved-but-unreachable connections."""
    checked = [probe_endpoint(item) for item in endpoints]
    return resolve_target(checked, target)


def inventory(endpoints: Iterable[AppEndpoint], *, probe: bool = True) -> dict[str, Any]:
    items = list(endpoints)
    if probe and items:
        with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
            items = list(pool.map(probe_endpoint, items))

    devices: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, endpoint in enumerate(items, start=1):
        app = endpoint.as_dict()
        app["index"] = index
        devices[endpoint.device_key].append(app)
    return {
        "count": len(items),
        "devices": [
            {"name": name, "apps": apps}
            for name, apps in sorted(devices.items(), key=lambda pair: pair[0].casefold())
        ],
    }


def _tool_result(value: Any) -> dict[str, Any]:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "structuredContent": value}


def _tool_error(
    message: str,
    *,
    code: str = "gateway_error",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error.update(details)
    return {
        "content": [{"type": "text", "text": message}],
        "structuredContent": {"ok": False, "error": error},
        "isError": True,
    }


TARGET_PROPERTY = {
    "type": "string",
    "description": (
        "Target app. Agents MUST use the target_id returned by the latest idh_list_devices call; "
        "do not guess or reuse it across app restarts. Index, Bundle ID, app name, service name and MCP URL are for manual use only."
    ),
}

MUTATING_TOOLS = frozenset(
    {
        "set_capture",
        "set_pause",
        "clear_events",
        "start_dump",
        "set_spoof",
        "set_noise_config",
        "clear_noise",
        "set_config",
        "hook_import",
        "hook_method",
        "unhook",
    }
)
MUTATING_PREFIXES = ("set_", "clear_", "start_", "hook_", "unhook")

MUTATION_CONFIRMATION_PROPERTY = {
    "type": "boolean",
    "description": (
        "Local idh safety confirmation. Must be true after the user explicitly requests this "
        "state-changing operation; idh removes it before forwarding to the device."
    ),
}

TRANSPARENT_PROXY_INSTRUCTIONS = (
    " idh proxy safety and analysis rules: state-changing tools expose a required "
    "allow_mutation parameter and are blocked unless the user explicitly requested the operation."
    " For call-stack or branch addresses, when returned, inspect "
    "symbolicate.symbol_source/confidence and use function_start or "
    "disassemble_function.resolved_start; never infer a function entry only from a prologue pattern. "
    "For paged scans, when returned, inspect scan.coverage_complete/scan.has_more and continue "
    "with scan.next_scan_offset before claiming that no reference exists. correlate_request proves an "
    "exact value match in a time window, not causality by itself. For full offline evidence, use "
    "export_events and keep cursor.snapshot_until_seq fixed while following cursor.next_after_seq."
)


def is_mutating_tool(name: str) -> bool:
    return name in MUTATING_TOOLS or name.startswith(MUTATING_PREFIXES)


def _add_mutation_confirmation(tool: dict[str, Any]) -> dict[str, Any]:
    """Advertise idh's local confirmation parameter on a proxied mutating tool."""
    name = tool.get("name")
    if not isinstance(name, str) or not is_mutating_tool(name):
        return tool
    updated = dict(tool)
    schema = dict(updated.get("inputSchema") or {"type": "object"})
    properties = dict(schema.get("properties") or {})
    properties["allow_mutation"] = MUTATION_CONFIRMATION_PROPERTY
    required = list(schema.get("required") or [])
    if "allow_mutation" not in required:
        required.append("allow_mutation")
    schema["properties"] = properties
    schema["required"] = required
    updated["inputSchema"] = schema
    annotations = dict(updated.get("annotations") or {})
    annotations.update({"readOnlyHint": False, "destructiveHint": True})
    updated["annotations"] = annotations
    return updated


def _annotate_proxy_response(message: Any, response: Any) -> Any:
    if not isinstance(message, dict) or not isinstance(response, dict):
        return response
    method = message.get("method")
    result = response.get("result")
    if not isinstance(result, dict):
        return response
    if method == "tools/list" and isinstance(result.get("tools"), list):
        result["tools"] = [
            _add_mutation_confirmation(tool) if isinstance(tool, dict) else tool
            for tool in result["tools"]
        ]
    elif method == "initialize":
        existing = result.get("instructions")
        result["instructions"] = (
            f"{existing}{TRANSPARENT_PROXY_INSTRUCTIONS}"
            if isinstance(existing, str) and existing
            else TRANSPARENT_PROXY_INSTRUCTIONS.strip()
        )
    return response


GATEWAY_TOOLS = [
    {
        "name": "idh_list_devices",
        "description": (
            "List the currently online IOSDecryptHub apps and their facts: target_id, app name, Bundle ID, "
            "device address and status. This is the first step for the Agent to identify the analysis target; the tool only returns facts "
            "and does not interpret user intent. Match the app the user mentioned against app/bundle: use its target_id when unique; "
            "ask the user when ambiguous; tell the user to launch/inject the app when nothing matches."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "name": "idh_list_tools",
        "description": (
            "List the real MCP tools provided by the device for a target_id. description is the factual source of capability "
            "boundaries; the Agent must choose tools from it and never invent tools or parameters. Returns a compact summary by default; "
            "query is a literal substring filter on name/description, not semantic; use idh_get_tool_schema for the full schema."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": TARGET_PROPERTY,
                "query": {"type": "string", "description": "filter by tool name or description"},
                "detail": {
                    "type": "string",
                    "enum": ["summary", "full"],
                    "default": "summary",
                    "description": "summary returns a compact listing, full returns the complete inputSchema",
                },
            },
            "required": ["target"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "name": "idh_get_tool_schema",
        "description": (
            "Fetch the complete inputSchema of a real remote tool on a target_id. Read the schema before calling it for the first "
            "time and build tool_arguments strictly by required, types and enums."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": TARGET_PROPERTY,
                "tool_name": {"type": "string", "description": "exact name of the remote tool"},
            },
            "required": ["target", "tool_name"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "name": "idh_call_tool",
        "description": (
            "Route the call verbatim to the real remote tool on a target_id; this tool does not understand natural language, "
            "does not pick targets and does not plan analysis. Read the tool description/schema first. Read-only analysis may run "
            "autonomously; tools that mutate state require explicit user intent and allow_mutation=true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": TARGET_PROPERTY,
                "tool_name": {"type": "string", "description": "exact name of the remote tool"},
                "tool_arguments": {
                    "type": "object",
                    "description": "arguments passed to the remote tool",
                },
                "allow_mutation": {
                    "type": "boolean",
                    "default": False,
                    "description": "must be explicitly true when calling tools that mutate state or have side effects",
                },
                "name": {
                    "type": "string",
                    "description": "compat for legacy clients; use tool_name for new calls",
                    "deprecated": True,
                },
                "arguments": {
                    "type": "object",
                    "description": "compat for legacy clients; use tool_arguments for new calls",
                    "deprecated": True,
                },
            },
            "required": ["target"],
            "anyOf": [{"required": ["tool_name"]}, {"required": ["name"]}],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    },
    {
        "name": "idh_get_panel_url",
        "description": "Return the LAN Web panel URL of the given app.",
        "inputSchema": {
            "type": "object",
            "properties": {"target": TARGET_PROPERTY},
            "required": ["target"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "name": "idh_list_skills",
        "description": (
            "List the currently available reverse-engineering skills from the idh prompt registry. "
            "Skills are refreshed independently of the idh package; call idh_get_skill to read one."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "name": "idh_get_skill",
        "description": (
            "Read the full markdown content of a skill returned by idh_list_skills. "
            "Use the skill name exactly as returned."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "skill name from idh_list_skills"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    },
]


class GatewayServer:
    def __init__(self, endpoints: EndpointProvider) -> None:
        self._endpoints = endpoints
        self._clients: dict[str, MCPHTTPClient] = {}
        self._prompts = PromptStore()
        self._next_id = 1
        self._lock = threading.Lock()

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return self._error(None, -32600, "Invalid Request")
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return (
                None if "id" not in message else self._error(request_id, -32600, "Invalid Request")
            )
        if "id" not in message:
            return None
        if method == "initialize":
            params = message.get("params") if isinstance(message.get("params"), dict) else {}
            version = params.get("protocolVersion") or "2025-03-26"
            return self._result(
                request_id,
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "idh", "version": __version__},
                    "instructions": self._prompts.instructions(),
                },
            )
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            return self._result(request_id, {"tools": GATEWAY_TOOLS})
        if method == "tools/call":
            params = message.get("params") if isinstance(message.get("params"), dict) else {}
            name = params.get("name")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            return self._result(request_id, self._call_tool(name, arguments))
        return self._error(request_id, -32601, f"Method not found: {method}")

    def _call_tool(self, name: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "idh_list_skills":
                return _tool_result({"skills": self._prompts.list_skills()})
            if name == "idh_get_skill":
                skill_name = arguments.get("name")
                if not isinstance(skill_name, str) or not skill_name:
                    return _tool_error("missing skill name", code="skill_name_required")
                content = self._prompts.get_skill(skill_name)
                if content is None:
                    return _tool_error(
                        f"skill does not exist: {skill_name}",
                        code="skill_not_found",
                        details={
                            "available_skills": [
                                item["name"] for item in self._prompts.list_skills()
                            ]
                        },
                    )
                return _tool_result({"name": skill_name, "content": content})
            if name == "idh_list_devices":
                return _tool_result(inventory(self._endpoints()))
            if name == "idh_get_panel_url":
                endpoint = resolve_live_target(self._endpoints(), arguments.get("target"))
                return _tool_result({"target_id": endpoint.key, "url": endpoint.panel_url})
            if name == "idh_list_tools":
                endpoint = resolve_live_target(self._endpoints(), arguments.get("target"))
                tools = self._remote_tools(endpoint)
                query = arguments.get("query")
                if isinstance(query, str) and query.strip():
                    value = query.strip().casefold()
                    tools = [
                        tool
                        for tool in tools
                        if value in str(tool.get("name", "")).casefold()
                        or value in str(tool.get("description", "")).casefold()
                    ]
                detail = arguments.get("detail", "summary")
                if detail != "full":
                    tools = [
                        {
                            key: tool[key]
                            for key in ("name", "description", "annotations")
                            if key in tool
                        }
                        for tool in tools
                    ]
                return _tool_result(
                    {
                        "target_id": endpoint.key,
                        "count": len(tools),
                        "detail": detail,
                        "tools": tools,
                    }
                )
            if name == "idh_get_tool_schema":
                endpoint = resolve_live_target(self._endpoints(), arguments.get("target"))
                tool_name = arguments.get("tool_name")
                if not isinstance(tool_name, str) or not tool_name:
                    return _tool_error(
                        "missing remote tool name tool_name", code="tool_name_required"
                    )
                tools = self._remote_tools(endpoint)
                tool = next((item for item in tools if item.get("name") == tool_name), None)
                if tool is None:
                    return _tool_error(
                        f"remote tool does not exist: {tool_name}",
                        code="tool_not_found",
                        details={
                            "target_id": endpoint.key,
                            "available_tools": [item.get("name") for item in tools],
                        },
                    )
                return _tool_result({"target_id": endpoint.key, "tool": tool})
            if name == "idh_call_tool":
                endpoint = resolve_live_target(self._endpoints(), arguments.get("target"))
                remote_name = arguments.get("tool_name") or arguments.get("name")
                if not isinstance(remote_name, str) or not remote_name:
                    return _tool_error(
                        "missing remote tool name tool_name", code="tool_name_required"
                    )
                if is_mutating_tool(remote_name) and arguments.get("allow_mutation") is not True:
                    return _tool_error(
                        f"tool {remote_name} mutates remote state; confirm user intent and pass allow_mutation=true",
                        code="mutation_confirmation_required",
                        details={"target_id": endpoint.key, "tool_name": remote_name},
                    )
                remote_args = arguments.get("tool_arguments")
                if remote_args is None:
                    remote_args = arguments.get("arguments")
                remote_args = remote_args if isinstance(remote_args, dict) else {}
                response = self._client(endpoint).send(
                    {
                        "jsonrpc": "2.0",
                        "id": self._request_id(),
                        "method": "tools/call",
                        "params": {"name": remote_name, "arguments": remote_args},
                    }
                )
                if isinstance(response, dict) and "error" in response:
                    return _tool_error(
                        json.dumps(response["error"], ensure_ascii=False),
                        code="remote_mcp_error",
                        details={"target_id": endpoint.key, "remote_error": response["error"]},
                    )
                result = response.get("result") if isinstance(response, dict) else None
                return result if isinstance(result, dict) else _tool_result(result)
            return _tool_error(f"Unknown gateway tool: {name}", code="unknown_gateway_tool")
        except TargetResolutionError as exc:
            return _tool_error(str(exc), code=exc.code, details=exc.details())
        except MCPTransportError as exc:
            return _tool_error(str(exc), code="mcp_transport_error")

    def _remote_tools(self, endpoint: AppEndpoint) -> list[dict[str, Any]]:
        response = self._client(endpoint).send(
            {"jsonrpc": "2.0", "id": self._request_id(), "method": "tools/list"}
        )
        if isinstance(response, dict) and "error" in response:
            raise MCPTransportError(json.dumps(response["error"], ensure_ascii=False))
        tools = response.get("result", {}).get("tools", []) if isinstance(response, dict) else []
        return [tool for tool in tools if isinstance(tool, dict)]

    def _client(self, endpoint: AppEndpoint) -> MCPHTTPClient:
        key = endpoint.key
        client = self._clients.get(key)
        if client is None:
            client = self._clients[key] = MCPHTTPClient(endpoint)
        else:
            client.update_endpoint(endpoint)
        client.ensure_initialized()
        return client

    def _request_id(self) -> str:
        with self._lock:
            value = f"idh-{self._next_id}"
            self._next_id += 1
            return value

    @staticmethod
    def _result(request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class TransparentProxy:
    def __init__(self, endpoints: EndpointProvider, target: str) -> None:
        self._endpoints = endpoints
        self._target = target
        self._client: MCPHTTPClient | None = None

    def handle(self, message: Any) -> Any | None:
        is_notification = isinstance(message, dict) and "id" not in message
        outbound = message
        if isinstance(message, dict) and message.get("method") == "tools/call":
            params = message.get("params") if isinstance(message.get("params"), dict) else {}
            tool_name = params.get("name")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            if isinstance(tool_name, str) and is_mutating_tool(tool_name):
                if arguments.get("allow_mutation") is not True:
                    if is_notification:
                        print(
                            f"idh: blocked mutating notification {tool_name} without allow_mutation",
                            file=sys.stderr,
                            flush=True,
                        )
                        return None
                    return {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "result": _tool_error(
                            f"tool {tool_name} mutates remote state; confirm user intent and pass "
                            "allow_mutation=true",
                            code="mutation_confirmation_required",
                            details={"tool_name": tool_name},
                        ),
                    }
                forwarded_arguments = dict(arguments)
                forwarded_arguments.pop("allow_mutation", None)
                outbound = dict(message)
                outbound_params = dict(params)
                outbound_params["arguments"] = forwarded_arguments
                outbound["params"] = outbound_params
        try:
            endpoint = resolve_live_target(self._endpoints(), self._target)
            if self._client is None:
                self._client = MCPHTTPClient(endpoint)
            else:
                self._client.update_endpoint(endpoint)
            response = self._client.send(outbound)
            return _annotate_proxy_response(message, response)
        except (TargetResolutionError, MCPTransportError) as exc:
            if is_notification:
                print(f"idh: {exc}", file=sys.stderr, flush=True)
                return None
            request_id = message.get("id") if isinstance(message, dict) else None
            error: dict[str, Any] = {"code": -32000, "message": str(exc)}
            if isinstance(exc, TargetResolutionError):
                error["data"] = {"code": exc.code, **exc.details()}
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": error,
            }


def serve_stdio(
    handler: Callable[[Any], Any | None],
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> None:
    for raw_line in input_stream:
        if not raw_line.strip():
            continue
        try:
            message = json.loads(raw_line)
            response = handler(message)
        except json.JSONDecodeError:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        except Exception as exc:  # noqa: BLE001 - one bad message must not kill the long-running stdio service
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": f"Internal error: {exc}"},
            }
        if response is not None:
            output_stream.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
            output_stream.write("\n")
            output_stream.flush()
