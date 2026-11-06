import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ids are interpolated into filenames under the state dir; keep them to a
# conservative character set so they can never escape it.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

DEFAULT_PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")

# 标准 AFSIM 项目目录结构 —— 每次写出场景文件时强制创建
STANDARD_PROJECT_DIRS = [
    "doc",
    "output",
    "platforms",
    "processors",
    "scenarios",
    "sensors",
    "weapons",
]

try:
    from ..tools import build_tool_router, build_tool_specs
    from .analysis import AnalysisService
    from .argument_types import ArgumentTypes
    from .knowledge import AfsimEventIndex
    from .knowledge import AfsimTypeIndex
    from .knowledge import CommandReference
    from .knowledge import ScriptApi
    from .results import ResultsService
    from .runtime import RuntimeService
    from .validation import AfsimValidationService
except ImportError:
    from tools import build_tool_router, build_tool_specs
    from core.analysis import AnalysisService
    from core.knowledge.argument_types import ArgumentTypes
    from core.knowledge import AfsimEventIndex
    from core.knowledge import AfsimTypeIndex
    from core.knowledge import CommandReference
    from core.knowledge import ScriptApi
    from core.results import ResultsService
    from core.runtime import RuntimeService
    from core.validation import AfsimValidationService


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code = int(code)
        self.message = str(message)
        self.data = data

    def to_error_obj(self):
        obj = {"code": self.code, "message": self.message}
        if self.data is not None:
            obj["data"] = self.data
        return obj


class MCPServer:
    JsonRpcError = JsonRpcError
    STANDARD_PROJECT_DIRS = STANDARD_PROJECT_DIRS

    def __init__(self):
        self.base_dir = self.resolve_base_dir()
        self.config_dir = self.resolve_config_dir()
        self.config_path = self.config_dir / "config.json"
        self.state_dir = self.resolve_state_dir()
        self.scenarios_dir = self.state_dir / "scenarios"
        self.runs_dir = self.state_dir / "runs"
        self.results_dir = self.state_dir / "results"
        self.processes_dir = self.state_dir / "processes"
        self.scenarios_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.processes_dir.mkdir(parents=True, exist_ok=True)

        self._tool_specs = build_tool_specs()
        self._tool_router = build_tool_router(self)
        self._processes = {}
        self.analysis_service = AnalysisService(self)
        self.type_index = AfsimTypeIndex(self)
        self.command_reference = CommandReference(self)
        self.event_index = AfsimEventIndex(self)
        self.argument_types = ArgumentTypes(self)
        self.script_api = ScriptApi(self)
        self.results_service = ResultsService(self)
        self.runtime_service = RuntimeService(self)
        self.validation_service = AfsimValidationService(self)

    def resolve_base_dir(self):
        env_dir = os.environ.get("AFSIM_MCP_BASE_DIR")
        if env_dir:
            return Path(env_dir)
        file_path = Path(__file__).resolve()
        if len(file_path.parents) > 3 and file_path.parents[2].name == "src":
            return file_path.parents[3]
        return file_path.parents[1]

    def resolve_config_dir(self):
        env_dir = os.environ.get("AFSIM_MCP_CONFIG_DIR")
        if env_dir:
            return Path(env_dir)
        legacy_dir = os.environ.get("AFSIM_MCP_STATE_DIR")
        if legacy_dir:
            return Path(legacy_dir)
        return Path.home() / ".afsim_mcp"

    def resolve_state_dir(self):
        env_dir = os.environ.get("AFSIM_MCP_STATE_DIR")
        if env_dir:
            return Path(env_dir)
        config = self.read_config()
        cfg_state = config.get("state_dir")
        if cfg_state and Path(cfg_state).exists():
            return Path(cfg_state)
        env_project = os.environ.get("AFSIM_PROJECT_ROOT")
        if env_project and Path(env_project).exists():
            return Path(env_project) / "mcp_state"
        cfg_root = config.get("project_root")
        if cfg_root and Path(cfg_root).exists():
            return Path(cfg_root) / "mcp_state"
        return self.config_dir / "state"

    def resolve_afsim_root(self):
        env_root = os.environ.get("AFSIM_ROOT")
        if env_root and Path(env_root).exists():
            return Path(env_root)
        config = self.read_config()
        cfg_root = config.get("afsim_root")
        if cfg_root and Path(cfg_root).exists():
            return Path(cfg_root)
        # Deliberately no guess here. Falling back to the parent of the repo
        # made an entire user directory (e.g. the Desktop) a readable root on a
        # fresh install. Callers treat None as "AFSIM root not configured".
        return None


    def resolve_demos_root(self):
        env_root = os.environ.get("AFSIM_DEMOS_DIR")
        if env_root and Path(env_root).exists():
            return Path(env_root)
        config = self.read_config()
        cfg_root = config.get("demos_root")
        if cfg_root and Path(cfg_root).exists():
            return Path(cfg_root)
        afsim_root = self.resolve_afsim_root()
        if afsim_root:
            candidate = afsim_root / "demos"
            if candidate.exists():
                return candidate
        return None

    def tools_list(self):
        return self._tool_specs

    def handle_request(self, request):
        if not isinstance(request, dict):
            raise JsonRpcError(-32600, "Invalid Request", {"reason": "request must be an object"})
        method = request.get("method")
        if not method:
            raise JsonRpcError(-32600, "Invalid Request", {"reason": "missing method"})
        if method == "initialize":
            params = request.get("params")
            if not isinstance(params, dict):
                params = {}
            requested = params.get("protocolVersion")
            # The tool surface is identical across these revisions, so echoing
            # the client's version is safe; anything unknown falls back.
            version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
            return {
                "protocolVersion": version,
                "serverInfo": {"name": "afsim-mcp", "version": "0.1.0"},
                "capabilities": {"tools": {"listChanged": False}},
                "instructions": (
                    "AFSIM MCP server. Use the tools to create scenarios, generate "
                    "platform/sensor/weapon definitions, run Mission, and analyse output."
                ),
            }
        if method == "ping":
            return {}
        if method.startswith("notifications/"):
            # Client-to-server notifications expect no reply.
            return {}
        if method == "tools/list":
            return {"tools": self.tools_list()}
        if method == "tools/call":
            params = request.get("params")
            if params is None:
                params = {}
            if not isinstance(params, dict):
                raise JsonRpcError(-32602, "Invalid params", {"reason": "params must be an object"})
            name = params.get("name")
            if not name or not isinstance(name, str):
                raise JsonRpcError(-32602, "Invalid params", {"reason": "params.name must be a string"})
            arguments = params.get("arguments")
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, dict):
                raise JsonRpcError(-32602, "Invalid params", {"reason": "params.arguments must be an object"})
            return self.call_tool(name, arguments)
        raise JsonRpcError(-32601, f"Unsupported method: {method}")

    def call_tool(self, name, arguments):
        handler = self._tool_router.get(name)
        if handler:
            try:
                return handler(arguments)
            except JsonRpcError:
                raise
            except Exception as exc:
                raise JsonRpcError(-32000, "Tool execution failed", {"tool": name, "error": str(exc)})
        raise JsonRpcError(-32601, f"Unknown tool: {name}")





























































    def scenario_path(self, scenario_id):
        return self.scenarios_dir / f"{self.require_safe_id(scenario_id, 'scenario_id')}.json"

    def run_path(self, run_id):
        return self.runs_dir / f"{self.require_safe_id(run_id, 'run_id')}.json"

    def process_path(self, process_id):
        return self.processes_dir / f"{self.require_safe_id(process_id, 'process_id')}.json"

    def write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))

    def write_text(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.atomic_write_text(path, text)

    def atomic_write_text(self, path, text):
        """Write via a temp file in the same directory, then replace.

        A crash or a second server instance sharing the state dir must never
        leave a half-written JSON file behind.
        """
        path = Path(path)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, path)
        except BaseException:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise


    def read_text(self, path):
        return Path(path).read_text(encoding="utf-8", errors="ignore")


    def read_json(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def now(self):
        return datetime.now(timezone.utc).isoformat()


    def require_str(self, args, key: str, *, allow_empty: bool = False) -> str:
        if not isinstance(args, dict):
            raise JsonRpcError(-32602, "Invalid params", {"reason": "arguments must be an object"})
        if key not in args:
            raise JsonRpcError(-32602, "Invalid params", {"reason": f"missing required field: {key}"})
        value = args.get(key)
        if not isinstance(value, str):
            raise JsonRpcError(-32602, "Invalid params", {"reason": f"{key} must be a string"})
        if not allow_empty and value.strip() == "":
            raise JsonRpcError(-32602, "Invalid params", {"reason": f"{key} must be non-empty"})
        return value

    def require_safe_id(self, value, kind: str) -> str:
        """Validate an id that gets joined onto a state directory.

        Ids such as scenario_id / run_id / process_id are interpolated straight
        into a filename, so anything containing a separator or ``..`` would
        escape the state dir.
        """
        text = str(value) if value is not None else ""
        if text in ("", ".", ".."):
            raise JsonRpcError(-32602, "Invalid params", {"reason": f"{kind} must be non-empty"})
        if not _SAFE_ID_RE.match(text) or ".." in text:
            raise JsonRpcError(
                -32602,
                "Invalid params",
                {
                    "reason": f"{kind} may only contain letters, digits, dot, dash and underscore",
                    "value": text,
                },
            )
        return text





    def assert_path_allowed(self, path: Path, *, write: bool, purpose: str):
        """Kept as a call-site-compatible no-op.

        There is deliberately no path sandbox: the operator drives the agent
        directly and the MCP client already scopes its own file access. This
        used to refuse anything outside the state dir, project root and AFSIM
        root, which only got in the way of legitimate work on demo files.
        """
        return None

    def wrap(self, payload):
        result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
        # Tools report expected failures as an ordinary payload carrying an
        # "error" key; without isError a client cannot tell that from success.
        if isinstance(payload, dict) and payload.get("error"):
            result["isError"] = True
        return result

    def truncate_text(self, text: str, max_chars: int) -> str:
        if text is None:
            return ""
        if max_chars is None or max_chars <= 0:
            return text
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...<truncated>\n"

    def start_background_process(self, cmd, working_dir, *, env=None):
        return self.runtime_service.start_background_process(cmd, working_dir, env=env)

    # ==================================================================
    # Consolidated entry points
    # ==================================================================

    def afsim_types(self, args):
        """The closed AFSIM type namespaces: platform types and component types."""
        return self.type_index.afsim_types(args)

    def afsim_command(self, args):
        """Syntax of an AFSIM input-file command, or of a simulation event name.

        The command index holds commands. The names event_output's enable and
        disable accept are a separate namespace, declared in the SDK headers
        and absent from both the command index and most of the HTML
        documentation, so they are looked up here rather than leaving the
        caller to guess and read "Invalid event name" back.
        """
        kind = str(args.get("kind") or "").lower()
        if kind == "script":
            return self.script_api.query(
                name=args.get("name"),
                keyword=args.get("keyword"),
                limit=args.get("limit"),
            )
        if kind == "event":
            return self.event_index.query(
                name=args.get("name"),
                keyword=args.get("keyword"),
                limit=args.get("limit"),
            )

        name = args.get("name")
        if name:
            # Checked first because an event name is never a command name, and
            # CommandReference raises on a miss rather than returning one --
            # an agent told only "not found" goes on to invent a third thing.
            entry, data, _count, _close = self.event_index.resolve(name=name)
            if entry is not None:
                return self.wrap(self.event_index.describe(entry, data))

        try:
            query = self.command_reference.query(
                name=name,
                keyword=args.get("keyword"),
                limit=int(args.get("limit") or 25),
            )
        except Exception:
            query = None

        if query is None or not query.get("forms"):
            # A miss that found no command may still name simulation events.
            selected, data, count, close = self.event_index.resolve(
                keyword=args.get("keyword") or name,
                limit=int(args.get("limit") or 10),
            )
            if count:
                return self.wrap(
                    {
                        "query": args.get("keyword") or name,
                        "matched_in": "simulation events",
                        "note": "No input-file command matched this. These are simulation "
                        "event names, which event_output's enable and disable accept.",
                        "total_matching": count,
                        "events": selected[:10],
                        "did_you_mean": close,
                    }
                )
            return self.wrap(
                {
                    "error": f"AFSIM command {name or args.get('keyword')!r} not found",
                    "did_you_mean": (query or {}).get("did_you_mean", [])[:10],
                    "event_names_indexed": data.get("event_count"),
                    "hint": "Pass keyword to search the whole command index, or "
                    "kind='event' to search the simulation event names that "
                    "event_output's enable and disable accept.",
                }
            )
        return self.wrap(query)

    def analyze_run(self, args):
        """Turn a completed run's outputs into a battle report."""
        return self.analysis_service.analyze_scenario_outputs(args)


    def launch_afsim_tool(self, args):
        """Launch any of the AFSIM GUI/utility executables."""
        tool = self.require_str(args, "tool").lower()
        runtime = self.runtime_service
        dispatch = {
            "wizard": runtime.run_wizard,
            "warlock": runtime.run_warlock,
            "mystic": runtime.run_mystic,
            "engage": runtime.run_engage,
            "sensor_plot": runtime.run_sensor_plot,
        }
        if tool not in dispatch:
            raise JsonRpcError(
                -32602,
                "Invalid params",
                {
                    "reason": "tool must be one of " + ", ".join(sorted(dispatch)),
                    "value": tool,
                },
            )
        return dispatch[tool](args)

    def run_mission_tool(self, args):
        """Run Mission, or query/stop a background run, depending on `action`."""
        action = args.get("action") or "run"
        if action == "status":
            if args.get("process_id"):
                return self.runtime_service.get_process_status(args)
            if args.get("run_id"):
                return self.results_service.get_simulation_status(args)
            raise JsonRpcError(
                -32602, "Invalid params", {"reason": "pass run_id or process_id"}
            )
        if action == "stop":
            if args.get("process_id"):
                return self.runtime_service.stop_process(args)
            if args.get("run_id"):
                return self.results_service.stop_simulation(args)
            raise JsonRpcError(
                -32602, "Invalid params", {"reason": "pass run_id or process_id"}
            )
        if action != "run":
            raise JsonRpcError(
                -32602, "Invalid params", {"reason": "action must be run, status or stop"}
            )
        if not args.get("scenario") and not args.get("scenarios"):
            raise JsonRpcError(
                -32602,
                "Invalid params",
                {"reason": "pass scenario (one entry file) or scenarios (several)"},
            )
        return self.run_mission_files(args)

    def run_mission_files(self, args):
        """Run Mission on one scenario file, several files, or a run record.

        Replaces run_mission / run_mission_with_args / batch_run_mission /
        run_mission_and_open_mystic. A single file still takes the fast path.
        """
        scenarios = args.get("scenarios")
        if not scenarios:
            single = args.get("scenario")
            scenarios = [single] if single else []
        if not scenarios:
            raise JsonRpcError(
                -32602,
                "Invalid params",
                {"reason": "pass scenario (one file) or scenarios (several files)"},
            )
        if not all(isinstance(item, str) for item in scenarios):
            raise JsonRpcError(
                -32602, "Invalid params", {"reason": "scenarios must be an array of strings"}
            )

        extra_args = args.get("args") or []
        if isinstance(extra_args, str):
            extra_args = [extra_args]
        extra_args = [str(value) for value in extra_args]

        def one(scenario):
            # Go through the validator, not a bare exit code: Mission returns 0
            # for a run that placed platforms and then did nothing.
            if args.get("background"):
                payload = {
                    "scenario": scenario,
                    "working_dir": args.get("working_dir"),
                    "background": True,
                }
                if extra_args:
                    payload["args"] = extra_args
                return self.runtime_service.run_mission(payload)
            # Pass the caller's arguments through: the policy switches in
            # core/policy.py arrive as ordinary arguments and were being
            # dropped here.
            validation_args = dict(args)
            validation_args.update(
                {
                    "scenario_file": scenario,
                    "output_dir": args.get("output_dir"),
                    "timeout_sec": args.get("timeout_sec") or 300,
                }
            )
            return self.validation_service.validate_afsim_scenario(validation_args)

        if len(scenarios) == 1:
            result = one(scenarios[0])
            if args.get("open_mystic"):
                working = args.get("working_dir") or str(Path(scenarios[0]).parent)
                latest = self.runtime_service.find_latest_aer(working)
                if latest:
                    mystic = self.runtime_service.run_mystic({"recording": str(latest)})
                    return self.wrap(
                        {
                            "mission": json.loads(result["content"][0]["text"]),
                            "latest_aer": str(latest),
                            "mystic": json.loads(mystic["content"][0]["text"]),
                        }
                    )
            return result

        results = []
        for scenario in scenarios:
            result = one(scenario)
            results.append(
                {"scenario": scenario, "result": json.loads(result["content"][0]["text"])}
            )
        return self.wrap({"results": results})











    def resolve_exe(self, base_name):
        return self.runtime_service.resolve_exe(base_name)

    def resolve_bin_path(self):
        return self.runtime_service.resolve_bin_path()










    def find_latest_aer(self, base_dir):
        return self.runtime_service.find_latest_aer(base_dir)

    def find_latest_matching_file(self, base_dir, pattern):
        if not base_dir:
            return None
        base_dir = Path(base_dir)
        if not base_dir.exists():
            return None
        candidates = list(base_dir.rglob(pattern))
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]









































































    def format_time_label(self, seconds):
        total_seconds = int(float(seconds or 0))
        minutes = total_seconds // 60
        remain = total_seconds % 60
        return f"{minutes:02d}:{remain:02d}"

    def read_config(self):
        # Called from __init__, so a malformed config must not take the server
        # down at startup; fall back to defaults and warn on stderr.
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            sys.stderr.write(
                f"afsim-mcp: ignoring unreadable config {self.config_path}: {exc}" + chr(10)
            )
            return {}
        if not isinstance(data, dict):
            sys.stderr.write(
                f"afsim-mcp: ignoring config {self.config_path}: expected a JSON object" + chr(10)
            )
            return {}
        return data




