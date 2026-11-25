from __future__ import annotations

import os
import plistlib
import socket
import struct
import threading

import pytest

from idh import usbmux
from idh.cli import _pick_usb_endpoint
from idh.models import AppEndpoint


class FakeUsbMuxd:
    """Minimal usbmuxd v1 peer: Listen handshake, ListDevices, Connect→echo."""

    def __init__(self, devices: list[dict]):
        self.devices = devices
        self.connect_requests: list[dict] = []
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.listener.close()

    def _serve(self) -> None:
        while True:
            try:
                client, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._session, args=(client,), daemon=True).start()

    def _session(self, client: socket.socket) -> None:
        def recv() -> dict:
            header = b""
            while len(header) < 16:
                chunk = client.recv(16 - len(header))
                if not chunk:
                    raise OSError("closed")
                header += chunk
            length, _v, _m, _t = struct.unpack("<IIII", header)
            body = b""
            while len(body) < length - 16:
                body += client.recv(length - 16 - len(body))
            return plistlib.loads(body)

        def send(payload: dict) -> None:
            body = plistlib.dumps(payload, fmt=plistlib.FMT_BINARY)
            client.sendall(struct.pack("<IIII", 16 + len(body), 1, 8, 1) + body)

        try:
            request = recv()
            kind = request.get("MessageType")
            if kind == "Listen":
                send({"MessageType": "Result", "Number": 0})
                request = recv()
                kind = request.get("MessageType")
            while True:
                if kind == "ListDevices":
                    send(
                        {
                            "DeviceList": [
                                {
                                    "DeviceID": device["device_id"],
                                    "MessageType": "Attached",
                                    "Properties": {
                                        "SerialNumber": device["udid"],
                                        "ProductID": device.get("product_id", 0),
                                        "ConnectionType": "USB",
                                    },
                                }
                                for device in self.devices
                            ]
                        }
                    )
                elif kind == "Connect":
                    self.connect_requests.append(request)
                    send({"MessageType": "Result", "Number": 0})
                    while True:  # raw tunnel: echo back
                        data = client.recv(4096)
                        if not data:
                            break
                        client.sendall(data)
                    return
                else:
                    return
                request = recv()
                kind = request.get("MessageType")
        except OSError:
            pass
        finally:
            client.close()


@pytest.fixture()
def muxd(monkeypatch):
    fake = FakeUsbMuxd(
        [{"udid": "deadbeefcafe1234", "device_id": 7, "product_id": 4776}]
    )
    monkeypatch.setenv("IDH_USBMUXD", f"127.0.0.1:{fake.port}")
    yield fake
    fake.close()


def test_devices_listed(muxd):
    devices = usbmux.usbmux_devices()
    assert devices == [
        {
            "udid": "deadbeefcafe1234",
            "device_id": 7,
            "connection_type": "USB",
            "product_id": 4776,
        }
    ]


def test_pick_single_device(muxd):
    endpoint = _pick_usb_endpoint()
    assert endpoint.properties["usb_udid"] == "deadbeefcafe1234"
    assert endpoint.base_url.startswith("http://127.0.0.1:")


def test_pick_by_udid_and_missing(muxd):
    assert _pick_usb_endpoint("DEADBEEFCAFE1234").properties["usb_udid"] == "deadbeefcafe1234"
    with pytest.raises(ValueError, match="not attached"):
        _pick_usb_endpoint("00001111")


def test_pick_requires_usbmuxd(monkeypatch):
    monkeypatch.setenv("IDH_USBMUXD", "127.0.0.1:1")
    with pytest.raises(ValueError, match="cannot reach usbmuxd"):
        _pick_usb_endpoint()


def test_pick_multiple_requires_udid(monkeypatch):
    fake = FakeUsbMuxd(
        [
            {"udid": "aaaa", "device_id": 1},
            {"udid": "bbbb", "device_id": 2},
        ]
    )
    monkeypatch.setenv("IDH_USBMUXD", f"127.0.0.1:{fake.port}")
    try:
        with pytest.raises(ValueError, match="multiple USB devices"):
            _pick_usb_endpoint()
        assert _pick_usb_endpoint("bbbb").properties["usb_udid"] == "bbbb"
    finally:
        fake.close()


def test_forwarder_tunnels_bytes(muxd):
    port = usbmux.ensure_usb_forwarder("deadbeefcafe1234")
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.sendall(b"GET /health HTTP/1.0\r\n\r\n")
        assert sock.recv(4096) == b"GET /health HTTP/1.0\r\n\r\n"
    assert muxd.connect_requests
    assert muxd.connect_requests[0]["DeviceID"] == 7


def test_resolve_endpoint_rewrites_usb(muxd):
    raw = AppEndpoint.from_url("http://127.0.0.1:9999").with_properties(
        {"transport": "usb", "usb_udid": "deadbeefcafe1234"}
    )
    resolved = usbmux.resolve_endpoint(raw)
    assert resolved.port == usbmux.ensure_usb_forwarder("deadbeefcafe1234")


def test_resolve_endpoint_leaves_lan_alone(muxd):
    raw = AppEndpoint.from_url("http://192.168.1.9:8088")
    assert usbmux.resolve_endpoint(raw) is raw
