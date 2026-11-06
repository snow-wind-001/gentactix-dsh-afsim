"""stdio transport for the AFSIM MCP server.

MCP on stdio is newline-delimited JSON, one message per line, and the spec
requires UTF-8. Python's stdio defaults to the locale encoding, which on a
zh-CN Windows install is cp936 — client-sent UTF-8 Chinese would then raise
UnicodeDecodeError while iterating stdin, and that happens outside any
per-request try/except, so it would kill the server. Pin the streams to UTF-8.
"""

import json
import sys
from pathlib import Path

base_dir = Path(__file__).resolve().parent.parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

try:
    from ..core.server import JsonRpcError, MCPServer
except ImportError:
    from core.server import JsonRpcError, MCPServer

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
INTERNAL_ERROR = -32000


def force_utf8(stream):
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return stream
    try:
        reconfigure(encoding="utf-8", errors="replace", newline="\n")
    except (ValueError, OSError):
        pass
    return stream


def write_payload(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def error_payload(req_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": error}


def handle_one(server, request):
    """Handle a single JSON-RPC message; return the response, or None.

    A request without an "id" member is a notification and gets no response —
    that covers notifications/initialized, notifications/cancelled and
    notifications/progress.
    """
    if not isinstance(request, dict):
        return error_payload(
            None, INVALID_REQUEST, "Invalid Request", {"reason": "request must be an object"}
        )

    is_notification = "id" not in request
    req_id = request.get("id")

    if is_notification:
        try:
            server.handle_request(request)
        except Exception:
            pass
        return None

    try:
        return {"jsonrpc": "2.0", "id": req_id, "result": server.handle_request(request)}
    except JsonRpcError as exc:
        return {"jsonrpc": "2.0", "id": req_id, "error": exc.to_error_obj()}
    except Exception as exc:
        return error_payload(req_id, INTERNAL_ERROR, "Internal error", {"error": str(exc)})


def handle_line(server, line):
    try:
        request = json.loads(line)
    except ValueError as exc:
        write_payload(error_payload(None, PARSE_ERROR, "Parse error", {"error": str(exc)}))
        return

    if isinstance(request, list):
        # JSON-RPC 2.0 batch, required by MCP. Notifications are omitted from
        # the response array, and an all-notification batch gets no reply.
        if not request:
            write_payload(
                error_payload(
                    None, INVALID_REQUEST, "Invalid Request", {"reason": "empty batch"}
                )
            )
            return
        responses = [r for r in (handle_one(server, item) for item in request) if r is not None]
        if responses:
            write_payload(responses)
        return

    response = handle_one(server, request)
    if response is not None:
        write_payload(response)


def main():
    force_utf8(sys.stdin)
    force_utf8(sys.stdout)
    force_utf8(sys.stderr)

    server = MCPServer()
    while True:
        try:
            line = sys.stdin.readline()
        except (UnicodeDecodeError, OSError) as exc:
            # Never let a decode error on one line take the server down.
            write_payload(error_payload(None, PARSE_ERROR, "Parse error", {"error": str(exc)}))
            continue
        if line == "":
            break
        line = line.strip()
        if not line:
            continue
        handle_line(server, line)


if __name__ == "__main__":
    main()
