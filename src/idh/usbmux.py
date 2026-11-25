"""usbmuxd client: list USB-attached devices and forward loopback ports.

Implements the v1 usbmuxd protocol (binary plist over the mux socket) so USB
devices appear as ordinary ``http://127.0.0.1:<port>`` endpoints — the same
shape frida's ``-U`` produces. No third-party dependency; works with Apple's
mobile-device service on Windows (TCP 27015) and macOS usbmuxd
(/var/run/usbmuxd). ``IDH_USBMUXD`` can point at ``host:port`` or a unix socket
path, e.g. an SSH-forwarded usbmuxd on another machine.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import socket
import struct
import threading
from dataclasses import replace

from .models import AppEndpoint

IDH_DEVICE_PORT = 8088


class UsbMuxError(OSError):
    pass


def _usbmuxd_address() -> str | tuple[str, int]:
    override = os.environ.get("IDH_USBMUXD", "").strip()
    if override:
        if ":" in override and not override.startswith("/"):
            host, _, port = override.rpartition(":")
            return host or "127.0.0.1", int(port)
        return override
    if os.path.exists("/var/run/usbmuxd"):
        return "/var/run/usbmuxd"
    return "127.0.0.1", 27015


def _open(timeout: float) -> socket.socket:
    address = _usbmuxd_address()
    if isinstance(address, str):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(address)
        return sock
    return socket.create_connection(address, timeout=timeout)


def _exchange(sock: socket.socket, payload: dict) -> dict:
    body = plistlib.dumps(payload, fmt=plistlib.FMT_BINARY)
    sock.sendall(struct.pack("<IIII", 16 + len(body), 1, 8, 1) + body)
    header = b""
    while len(header) < 16:
        chunk = sock.recv(16 - len(header))
        if not chunk:
            raise UsbMuxError("usbmuxd closed the connection")
        header += chunk
    length, _version, _message, _tag = struct.unpack("<IIII", header)
    data = b""
    while len(data) < length - 16:
        chunk = sock.recv(length - 16 - len(data))
        if not chunk:
            raise UsbMuxError("usbmuxd closed mid-message")
        data += chunk
    return plistlib.loads(data)


def usbmux_devices(timeout: float = 2.0) -> list[dict]:
    """Return USB-attached devices as {udid, device_id, connection_type}."""
    try:
        sock = _open(timeout)
    except OSError as exc:
        raise UsbMuxError(f"usbmuxd unavailable: {exc}") from exc
    with sock:
        hello = {
            "MessageType": "Listen",
            "ClientVersionString": "idh",
            "ProgName": "idh",
            "kLibUSBMuxVersion": 3,
        }
        result = _exchange(sock, hello)
        if result.get("Number") != 0:
            raise UsbMuxError(f"usbmuxd listen failed: {result}")
        result = _exchange(sock, {**hello, "MessageType": "ListDevices"})
        devices = []
        for entry in result.get("DeviceList") or []:
            props = entry.get("Properties") or {}
            udid = props.get("SerialNumber")
            if udid:
                devices.append(
                    {
                        "udid": udid,
                        "device_id": entry.get("DeviceID"),
                        "connection_type": props.get("ConnectionType", "USB"),
                        "product_id": props.get("ProductID"),
                    }
                )
        return devices


def _device_id(udid: str, timeout: float) -> int:
    for device in usbmux_devices(timeout):
        if device["udid"] == udid:
            return int(device["device_id"])
    raise UsbMuxError(f"usb device detached: {udid}")


def _connect(device_id: int, device_port: int, timeout: float) -> socket.socket:
    sock = _open(timeout)
    try:
        result = _exchange(
            sock,
            {
                "MessageType": "Connect",
                "ClientVersionString": "idh",
                "ProgName": "idh",
                "kLibUSBMuxVersion": 3,
                "DeviceID": device_id,
                "PortNumber": socket.htons(device_port),
            },
        )
        if result.get("Number") != 0:
            raise UsbMuxError(f"usbmuxd connect refused: {result}")
        return sock
    except Exception:
        sock.close()
        raise


def _pump(client: socket.socket, udid: str) -> None:
    try:
        remote = _connect(_device_id(udid, 2.0), IDH_DEVICE_PORT, 2.0)
    except OSError:
        client.close()
        return
    remote.settimeout(None)
    client.settimeout(None)

    def forward(source: socket.socket, target: socket.socket) -> None:
        try:
            while True:
                data = source.recv(65536)
                if not data:
                    break
                target.sendall(data)
        except OSError:
            pass
        finally:
            for sock in (source, target):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass

    threading.Thread(target=forward, args=(client, remote), daemon=True).start()
    threading.Thread(target=forward, args=(remote, client), daemon=True).start()


_forwarders: dict[str, int] = {}
_forwarders_lock = threading.Lock()


def _forward_port(udid: str) -> int:
    return 18400 + int.from_bytes(hashlib.sha256(udid.encode()).digest()[:2], "big") % 400


def ensure_usb_forwarder(udid: str, device_port: int = IDH_DEVICE_PORT) -> int:
    """Bind a loopback forwarder for a USB device; return its local port."""
    with _forwarders_lock:
        if udid in _forwarders:
            return _forwarders[udid]
        port = _forward_port(udid)
        for _ in range(200):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", port))
                listener.listen(8)
            except OSError:
                listener.close()
                port += 1
                continue
            break
        else:
            raise UsbMuxError("no loopback port available for usb forwarder")

        def serve() -> None:
            while True:
                try:
                    client, _ = listener.accept()
                except OSError:
                    return
                threading.Thread(target=_pump, args=(client, udid), daemon=True).start()

        threading.Thread(target=serve, daemon=True).start()
        _forwarders[udid] = port
        return port


def resolve_endpoint(endpoint: AppEndpoint) -> AppEndpoint:
    """Rewrite a usb-transport endpoint to its live loopback forwarder URL."""
    udid = endpoint.properties.get("usb_udid")
    if not udid:
        return endpoint
    port = ensure_usb_forwarder(str(udid))
    if port == endpoint.port:
        return endpoint
    return replace(endpoint, addresses=("127.0.0.1",), server="127.0.0.1", port=port)


def usb_endpoint(udid: str, timeout: float = 2.0) -> AppEndpoint:
    """Build an endpoint for a USB device id (starting its forwarder)."""
    port = ensure_usb_forwarder(udid)
    return AppEndpoint.from_url(f"http://127.0.0.1:{port}").with_properties(
        {"transport": "usb", "usb_udid": udid}
    )
