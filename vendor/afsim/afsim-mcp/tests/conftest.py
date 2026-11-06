"""Shared fixtures.

The tests drive the real server over real JSON-RPC rather than calling service
classes directly: the defects that mattered (a validator that reported success
on a simulation that did nothing, error regexes that never matched real Mission
output) all lived in the wiring.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STDIO_ENTRY = REPO_ROOT / "transport" / "stdio.py"

SURVIVING_TOOLS = {
    "afsim_types",
    "afsim_command",
    "run_mission",
    "analyze_run",
    "launch_afsim_tool",
}


class StdioResult:
    def __init__(self, responses, returncode, stderr, stdout_raw):
        self.responses = responses
        self.returncode = returncode
        self.stderr = stderr
        self.stdout_raw = stdout_raw

    def by_id(self, req_id):
        for response in self.responses:
            if response.get("id") == req_id:
                return response
        raise AssertionError(f"no response with id={req_id!r}; got {self.responses!r}")

    def payload(self, req_id):
        response = self.by_id(req_id)
        assert "result" in response, f"expected a result, got {response!r}"
        return json.loads(response["result"]["content"][0]["text"])

    def is_error(self, req_id):
        return bool(self.by_id(req_id).get("result", {}).get("isError"))


def run_stdio_raw(payload, env, timeout=180):
    proc = subprocess.run(
        [sys.executable, str(STDIO_ENTRY)],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )
    responses = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        if isinstance(parsed, list):
            responses.extend(parsed)
        else:
            responses.append(parsed)
    return StdioResult(responses, proc.returncode, proc.stderr, proc.stdout)


@pytest.fixture
def afsim_env(tmp_path):
    """Point the server at a real AFSIM install when one is available."""
    root = Path(r"C:\SoftCode\Sim\AFSim")
    env = dict(os.environ)
    env.update(
        {
            "AFSIM_PROJECT_ROOT": str(tmp_path / "project"),
            "AFSIM_MCP_STATE_DIR": str(tmp_path / "state"),
            "AFSIM_MCP_CONFIG_DIR": str(tmp_path / "config"),
        }
    )
    for path in (tmp_path / "project", tmp_path / "state", tmp_path / "config"):
        path.mkdir(parents=True, exist_ok=True)
    if root.is_dir():
        env["AFSIM_ROOT"] = str(root)
        env["AFSIM_BIN"] = str(root / "bin")
        env["AFSIM_DEMOS_DIR"] = str(root / "demos")
    return env


@pytest.fixture
def run_stdio(afsim_env):
    def _run(messages, env=None, timeout=180):
        lines = [json.dumps(m, ensure_ascii=False) for m in messages]
        return run_stdio_raw("\n".join(lines) + "\n", env or afsim_env, timeout=timeout)

    return _run


@pytest.fixture
def call_tool(run_stdio):
    def _call(name, arguments=None, req_id=1, env=None, timeout=180):
        result = run_stdio(
            [
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments or {}},
                }
            ],
            env=env,
            timeout=timeout,
        )
        return result, req_id

    return _call


def was_rejected(response):
    if "error" in response:
        return True
    return bool(response.get("result", {}).get("isError"))
