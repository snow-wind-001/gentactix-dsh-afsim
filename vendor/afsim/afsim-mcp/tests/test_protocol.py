"""Protocol-level tests and the shape of the surviving tool surface."""

import json
from pathlib import Path

from conftest import SURVIVING_TOOLS


def test_only_the_four_capabilities_are_exposed(run_stdio):
    """Everything else is a client file tool's job."""
    result = run_stdio([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
    listed = {tool["name"] for tool in result.by_id(1)["result"]["tools"]}
    assert listed == SURVIVING_TOOLS


def test_every_tool_has_a_schema_and_description(run_stdio):
    result = run_stdio([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
    for tool in result.by_id(1)["result"]["tools"]:
        assert tool["description"].strip(), f"{tool['name']} has no description"
        assert tool["inputSchema"]["type"] == "object"


def test_router_and_specs_agree():
    from core.server import MCPServer
    from tools import build_tool_router, build_tool_specs

    server = MCPServer()
    assert {s["name"] for s in build_tool_specs()} == set(build_tool_router(server))


def test_initialize_negotiates_known_version(run_stdio):
    result = run_stdio(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            }
        ]
    )
    assert result.by_id(1)["result"]["protocolVersion"] == "2025-06-18"


def test_initialize_falls_back_for_unknown_version(run_stdio):
    result = run_stdio(
        [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}]
    )
    assert result.by_id(1)["result"]["protocolVersion"] == "2024-11-05"


def test_ping(run_stdio):
    result = run_stdio([{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert result.by_id(1)["result"] == {}


def test_notification_gets_no_response(run_stdio):
    result = run_stdio([{"jsonrpc": "2.0", "method": "notifications/initialized"}])
    assert result.responses == []
    assert result.returncode == 0


def test_batch_omits_notifications(run_stdio):
    result = run_stdio(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
    )
    assert result.by_id(1)["result"] == {}
    assert {t["name"] for t in result.by_id(2)["result"]["tools"]} == SURVIVING_TOOLS


def test_parse_error_does_not_kill_the_server(afsim_env):
    from conftest import run_stdio_raw

    result = run_stdio_raw(
        "{not json\n" + json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}) + "\n",
        afsim_env,
    )
    assert result.responses[0]["error"]["code"] == -32700
    assert result.responses[1]["result"] == {}


def test_unknown_method_is_reported(run_stdio):
    result = run_stdio([{"jsonrpc": "2.0", "id": 1, "method": "does/not/exist"}])
    assert result.by_id(1)["error"]["code"] == -32601


def test_unknown_tool_is_reported(run_stdio):
    result = run_stdio(
        [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "nope", "arguments": {}}}]
    )
    assert result.by_id(1)["error"]["code"] == -32601


def test_stdout_is_json_only(run_stdio):
    result = run_stdio(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ]
    )
    for line in result.stdout_raw.splitlines():
        if line.strip():
            json.loads(line)


def test_corrupt_config_does_not_prevent_startup(run_stdio, afsim_env):
    config = Path(afsim_env["AFSIM_MCP_CONFIG_DIR"]) / "config.json"
    config.write_text("{ not json", encoding="utf-8")
    result = run_stdio([{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert result.returncode == 0
    assert result.by_id(1)["result"] == {}

