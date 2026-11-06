"""The four capabilities an AFSIM model cannot do for itself.

Everything else a client file tool already covers: an AFSIM project is a
directory of plain text, and the model can read and write it directly.

    afsim_types       the platform_type namespace is closed -- names cannot be
                      guessed, only looked up
    run_mission       compiling, instantiating and running are one mission.exe
                      invocation, and its diagnostics have to be parsed from
                      real output
    analyze_run       KPIs and timelines come out of multi-megabyte .evt files
    launch_afsim_tool GUI executables

There is no path sandbox and no directory-structure enforcement: the operator
drives the agent directly, and the MCP client already scopes its own file
access to the project.
"""


def specs():
    return [
        {
            "name": "afsim_types",
            "description": (
                "Look up real AFSIM platform_type definitions. mission.exe rejects "
                "any type name it does not know, so a scenario must reference types "
                "that exist. Without arguments this lists the types worth using "
                "(those carrying sensors or weapons); pass name to inspect one. "
                "Call this before choosing platform types."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "A platform_type to inspect, e.g. LTE_FIGHTER",
                    },
                    "domain": {
                        "type": "string",
                        "enum": ["air", "ground", "surface", "space", "undetermined"],
                        "description": "Read off the platform's declared mover, following the base chain. A type whose mover is not declared anywhere in the index stays 'undetermined' rather than being guessed from its name.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": [
                            "sensor", "weapon", "mover", "processor", "comm", "filter",
                        ],
                        "description": "List or inspect component types instead of "
                        "platform types, e.g. kind='sensor'",
                    },
                    "keyword": {"type": "string"},
                    "armed_only": {
                        "type": "boolean",
                        "description": "Only types carrying a sensor or weapon. Off by "
                        "default: whether an unarmed platform is useful is a judgement "
                        "the caller makes, so the listing reports `armed` per type "
                        "instead of deciding.",
                    },
                    "limit": {"type": "integer"},
                    "refresh": {
                        "type": "boolean",
                        "description": "Rebuild the catalog from the AFSIM demos",
                    },
                },
            },
        },
        {
            "name": "afsim_command",
            "description": (
                "Look up the syntax of an AFSIM input-file command, from the command "
                "index shipped with AFSIM. Returns the exact argument pattern, whether "
                "the command opens a block (and its end_<keyword> terminator), and which "
                "required/optional arguments it takes. Call this before writing AFSIM text "
                "rather than guessing: argument order, positional counts, unit separation "
                "and block terminators are all exact here. Pass kind='event' to search the "
                "simulation event names that event_output's enable and disable accept; "
                "mission rejects any other name with 'Invalid event name for event_output'. "
                "Pass kind='script' for the scripting API -- the objects a processor script "
                "calls (WsfPlatform, WsfTrack, WsfAssetManager, ...) and their methods, which "
                "is the only place the identifiers inside a tactics processor are listed."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Command, e.g. end_time"},
                    "keyword": {"type": "string", "description": "Free-text search"},
                    "kind": {
                        "type": "string",
                        "enum": ["event"],
                        "description": "Search simulation event names instead of commands",
                    },
                    "limit": {"type": "integer"},
                },
            },
        },
        {
            "name": "run_mission",
            "description": (
                "Run mission.exe and report what actually happened: exit code, errors "
                "parsed from real Mission output with file/line/column, whether the run "
                "reached 'Simulation complete', and whether it was inert (platforms "
                "placed but no sensor, track or weapon events). A run that only places "
                "platforms fails even though mission exits 0. Use action='status' or "
                "'stop' for a background run."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scenario": {
                        "type": "string",
                        "description": "Entry file to run, e.g. C:\\proj\\scn.txt",
                    },
                    "scenarios": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Run several entry files",
                    },
                    "action": {"type": "string", "enum": ["run", "status", "stop"]},
                    "process_id": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "working_dir": {"type": "string"},
                    "output_dir": {"type": "string"},
                    "timeout_sec": {"type": "number"},
                    "background": {"type": "boolean"},
                    "max_output_chars": {"type": "integer"},
                    "open_mystic": {
                        "type": "boolean",
                        "description": "Open the resulting AER in Mystic",
                    },
                    "inert_is_failure": {
                        "type": "boolean",
                        "description": "Whether a run that only placed platforms counts as a "
                        "failure. Default true; see core/policy.py.",
                    },
                    "no_evidence_is_failure": {
                        "type": "boolean",
                        "description": "Whether a run that wrote no output at all counts as a "
                        "failure. Default true; see core/policy.py.",
                    },
                    "not_analyzable_is_failure": {
                        "type": "boolean",
                        "description": "Whether a run that produced output but no .evt events "
                        "counts as a failure. Default false: it simulated, it just cannot be "
                        "analysed. See core/policy.py.",
                    },
                    "unlocated_errors_are_environmental": {
                        "type": "boolean",
                        "description": "Whether an error naming no file/line/column counts "
                        "against the scenario. Default true: AFSIM reports a scenario defect "
                        "located (file, line, column), so an unlocated error is its own log "
                        "or event_pipe plumbing. Set false to make every ERROR fatal. See "
                        "core/policy.py.",
                    },
                    "include_stdout": {
                        "type": "boolean",
                        "description": "Return Mission's raw stdout, which is where AFSIM puts "
                        "behavioural diagnostics such as show_state_transitions",
                    },
                    "stdout_chars": {"type": "integer"},
                },
            },
        },
        {
            "name": "analyze_run",
            "description": (
                "Turn a completed run's outputs into a battle report: event counts, "
                "timeline, losses, weapon and interception statistics, sensor "
                "detection chains, and KPIs such as kill-chain closure and "
                "first-detection time. Writes ANALYSIS.md and ANALYSIS.json next to "
                "the scenario."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scenario_dir": {"type": "string"},
                    "evt_path": {"type": "string"},
                    "aer_path": {"type": "string"},
                    "sensor_path": {"type": "string"},
                },
            },
        },
        {
            "name": "launch_afsim_tool",
            "description": (
                "Launch an AFSIM desktop tool: wizard (scenario builder), warlock "
                "(replay), mystic (3D viewer), engage, or sensor_plot."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "enum": ["wizard", "warlock", "mystic", "engage", "sensor_plot"],
                    },
                    "scenario_file": {"type": "string"},
                    "recording": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "working_dir": {"type": "string"},
                    "background": {"type": "boolean"},
                    "timeout_sec": {"type": "number"},
                },
                "required": ["tool"],
            },
        },
    ]


def build_tool_specs():
    return specs()


def build_tool_router(server):
    return router(server)


def router(server):
    return {
        "afsim_types": server.afsim_types,
        "afsim_command": server.afsim_command,
        "run_mission": server.run_mission_tool,
        "analyze_run": server.analyze_run,
        "launch_afsim_tool": server.launch_afsim_tool,
    }
