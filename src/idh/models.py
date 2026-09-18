from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit


def _path(value: str | None, default: str) -> str:
    value = value or default
    return value if value.startswith("/") else f"/{value}"


@dataclass(frozen=True, slots=True)
class AppEndpoint:
    service_name: str
    server: str
    addresses: tuple[str, ...]
    port: int
    properties: Mapping[str, str] = field(default_factory=dict)
    source: str = "manual"

    @classmethod
    def from_url(cls, value: str) -> AppEndpoint:
        raw = value if "://" in value else f"http://{value}"
        parsed = urlsplit(raw)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError(f"only HTTP URLs are supported: {value}")
        port = parsed.port or 80
        path = parsed.path.rstrip("/")
        path = path.removesuffix("/api/mcp")
        properties = {
            "mcp_path": f"{path}/api/mcp" if path else "/api/mcp",
            "panel_path": f"{path}/" if path else "/",
        }
        return cls(
            service_name=f"manual-{parsed.hostname}-{port}",
            server=parsed.hostname,
            addresses=(parsed.hostname,),
            port=port,
            properties=properties,
            source="manual",
        )

    @property
    def primary_address(self) -> str:
        if not self.addresses:
            return self.server.rstrip(".")
        return min(self.addresses, key=self._address_rank)

    @staticmethod
    def _address_rank(value: str) -> tuple[int, str]:
        try:
            parsed = ip_address(value.split("%", 1)[0])
        except ValueError:
            return (2, value)
        return (0 if parsed.version == 4 else 1, value)

    @property
    def host_for_url(self) -> str:
        host = self.primary_address
        return f"[{host}]" if ":" in host and not host.startswith("[") else host

    @property
    def base_url(self) -> str:
        return f"http://{self.host_for_url}:{self.port}"

    @property
    def mcp_url(self) -> str:
        return f"{self.base_url}{_path(self.properties.get('mcp_path'), '/api/mcp')}"

    @property
    def panel_url(self) -> str:
        return f"{self.base_url}{_path(self.properties.get('panel_path'), '/')}"

    @property
    def app_name(self) -> str:
        return self.properties.get("app_name") or self.properties.get("app") or self.short_name

    @property
    def bundle_id(self) -> str:
        return self.properties.get("bundle") or self.properties.get("bundle_id") or ""

    @property
    def short_name(self) -> str:
        suffix = "._idh-mcp._tcp.local."
        return self.service_name.removesuffix(suffix)

    @property
    def device_key(self) -> str:
        return self.server.rstrip(".") or self.primary_address

    @property
    def key(self) -> str:
        return self.properties.get("id") or self.short_name

    def selectors(self) -> set[str]:
        values = {
            self.key,
            self.short_name,
            self.service_name,
            self.bundle_id,
            self.app_name,
            f"{self.device_key}/{self.bundle_id}",
            f"{self.device_key}/{self.app_name}",
            self.mcp_url,
            self.panel_url,
        }
        return {value.casefold() for value in values if value}

    def with_properties(self, values: Mapping[str, Any]) -> AppEndpoint:
        merged = dict(self.properties)
        for key, value in values.items():
            if value is not None and str(value):
                merged[key] = str(value)
        return replace(self, properties=merged)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.key,
            "target_id": self.key,
            "device": self.device_key,
            "service": self.short_name,
            "app": self.app_name,
            "bundle": self.bundle_id,
            "addresses": list(self.addresses),
            "port": self.port,
            "web": self.panel_url,
            "mcp": self.mcp_url,
            "source": self.source,
            "properties": dict(self.properties),
        }
