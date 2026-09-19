from __future__ import annotations

from idh.gateway import GatewayServer


def test_gateway_exposes_skills_without_a_device() -> None:
    server = GatewayServer(list)

    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert {"idh_list_skills", "idh_get_skill"} <= names

    listed = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "idh_list_skills", "arguments": {}},
        }
    )
    skills = listed["result"]["structuredContent"]["skills"]
    assert any(item["name"] == "static-linked-crypto" for item in skills)

    fetched = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "idh_get_skill",
                "arguments": {"name": "static-linked-crypto"},
            },
        }
    )
    content = fetched["result"]["structuredContent"]["content"]
    assert "capture_memory" in content


def test_gateway_instructions_come_from_prompt_store() -> None:
    server = GatewayServer(list)
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    instructions = response["result"]["instructions"]
    assert "idh_list_devices" in instructions
    assert "idh_list_skills" in instructions
