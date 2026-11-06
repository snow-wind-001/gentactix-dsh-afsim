"""Run mission.exe and report what actually happened.

This is an executor. Parsing Mission's output is core/knowledge; deciding
whether the result counts as a pass is core/policy. Neither belongs here.

The earlier version did both inline, and a set of hand-written regexes that
never matched real Mission output was used to "repair" scenarios by writing
empty placeholder files over real ones -- the run then exited 0 and was
reported as validated while simulating nothing.
"""

import re
from pathlib import Path
from subprocess import DEVNULL, TimeoutExpired, run

from . import policy as policy_module

try:
    from .knowledge import MissionGrammar
    from .knowledge.mission_grammar import (
        RunDuration,
        achieved_duration,
        declared_duration,
    )
except ImportError:
    from core.knowledge import MissionGrammar
    from core.knowledge.mission_grammar import (
        RunDuration,
        achieved_duration,
        declared_duration,
    )


class AfsimValidationService:
    def __init__(self, host):
        self.host = host
        self.grammar = MissionGrammar(host)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse_mission_output(self, text, base_dir=None):
        """Delegates to the knowledge layer; kept for existing callers."""
        return self.grammar.parse(text, base_dir=base_dir)

    def summarize_outputs(self, output_dir, scenario_name, scenario_dir=None):
        """Measure what the run actually produced.

        An .evt with only PLATFORM_INITIALIZED lines means every platform was
        placed and then nothing happened: no sensor, weapon or track event.

        Both the requested output directory and the scenario's own directory
        are swept. A scenario that writes its .evt next to the entry file --
        which is what AFSIM does unless the scenario says otherwise -- looks
        completely empty to a scan of output_dir alone, and a run that
        produced a complete battle record was reported as having recorded no
        events at all.
        """
        output_dir = Path(output_dir)
        scenario_dir = Path(scenario_dir) if scenario_dir else None
        summary = {
            "evt_events": 0,
            "evt_categories": {},
            "aer_bytes": 0,
            "files": [],
            # A run directory can hold several .evt files -- a renamed
            # copy, a smoke test, an earlier attempt -- so the per-file
            # breakdown is reported rather than only a sum that would
            # disagree with analyze_run, which reads one file.
            "evt_files_counted": 0,
            "per_evt_file": [],
            "searched_dirs": [],
        }

        search_dirs = []
        for candidate in (output_dir, scenario_dir):
            if candidate is not None and candidate.is_dir() and candidate not in search_dirs:
                search_dirs.append(candidate)
        summary["searched_dirs"] = [str(d) for d in search_dirs]
        if not search_dirs:
            return summary

        for directory in search_dirs:
            for path in sorted(directory.iterdir()):
                if not path.is_file():
                    continue
                if path.stat().st_size == 0 and path.suffix.lower() in (".evt", ".aer"):
                    continue
                summary["files"].append(
                    {
                        "name": path.name,
                        "bytes": path.stat().st_size,
                        "dir": str(directory),
                    }
                )
                if path.suffix.lower() == ".aer":
                    summary["aer_bytes"] += path.stat().st_size
                elif path.suffix.lower() != ".evt":
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                counts = {}
                events = 0
                # An event record is "<time> <EVENT_NAME> <details>", continued
                # on indented lines. AFSIM also writes the time as HH:MM:SS.s.
                for line in text.splitlines():
                    if not line or line[0].isspace():
                        continue
                    tokens = line.split()
                    if len(tokens) < 2:
                        continue
                    stamp, event = tokens[0], tokens[1]
                    if not re.match(r"^\d+(?::\d+){0,2}(?:\.\d+)?$", stamp):
                        continue
                    events += 1
                    counts[event] = counts.get(event, 0) + 1
                if not events:
                    continue
                summary["evt_events"] += events
                summary["evt_files_counted"] += 1
                for event, count in counts.items():
                    summary["evt_categories"][event] = (
                        summary["evt_categories"].get(event, 0) + count
                    )
                summary["per_evt_file"].append(
                    {
                        "name": path.name,
                        "dir": str(directory),
                        "bytes": path.stat().st_size,
                        "events": events,
                        "categories": counts,
                    }
                )
        summary["per_evt_file"].sort(key=lambda item: -item["events"])
        return summary

    def resolve_include_hint(self, missing):
        """Locate a file Mission could not open inside the AFSIM install.

        Demo type files include siblings by relative path, and those only
        resolve if the entry file's `file_path` names the directory the file
        actually sits in. The hint used to report the demo's top-level folder
        instead, which sent the caller to add `file_path demos/suppressor` for
        a file living under demos/suppressor/platforms -- a line that changes
        nothing.

        AFSIM searches by concatenating the file_path entry onto the name it
        was asked for, so the entry is not the directory holding the file but
        the directory left after removing the requested name from it: for
        `include sam_radar.txt` that is .../sensors/radar, and for
        `include sensors/radar/sam_radar.txt` it is .../platforms.
        """
        demos = self.host.resolve_demos_root()
        afsim = self.host.resolve_afsim_root()
        wanted = str(missing or "").replace("\\", "/").strip("'\"")
        if not wanted:
            return None
        leaf = wanted.rsplit("/", 1)[-1]
        depth = len([part for part in wanted.split("/") if part])

        exact = []
        by_name = []
        for root in [demos, afsim]:
            if not root or not Path(root).is_dir():
                continue
            root = Path(root)
            try:
                candidates = list(Path(root).rglob(leaf))
            except OSError:
                continue
            for candidate in candidates:
                try:
                    relative = candidate.relative_to(root)
                except ValueError:
                    continue
                rel = str(relative).replace("\\", "/")
                # Drop the requested name's own path components so that
                # file_path + wanted == the file that was found.
                keep = max(len(relative.parts) - depth, 0)
                search_root = root.joinpath(*relative.parts[:keep]) if keep else root
                entry = {
                    "path": rel,
                    "found_at": str(candidate),
                    "add_to_entry_file": f"file_path {search_root}",
                }
                (exact if rel == wanted else by_name).append(entry)

        if exact:
            return {
                "found": True,
                "match": "exact",
                "candidates": exact[:3],
                "note": "AFSIM resolves an include by concatenating each file_path entry "
                "onto the name it was given, so the entry is the directory the name "
                "is relative to, not the demo's top-level folder.",
            }
        if by_name:
            return {
                "found": True,
                "match": "basename",
                "candidates": by_name[:5],
                "note": "No file has that exact relative path. The basename exists "
                "elsewhere; add one of the file_path lines above to the entry file. "
                "Each line points at the directory the requested name is relative to.",
            }
        return {
            "found": False,
            "path": wanted,
            "hint": "The file does not exist anywhere under the AFSIM install. Either the "
            "name is wrong, or the file has to be written first.",
        }

    # ------------------------------------------------------------------
    # The tool
    # ------------------------------------------------------------------

    def validate_afsim_scenario(self, args):
        scenario_file = Path(self.host.require_str(args, "scenario_file"))
        self.host.assert_path_allowed(scenario_file, write=False, purpose="validate_afsim_scenario")
        if not scenario_file.is_file():
            return self.host.wrap({"error": "scenario_file not found", "scenario_file": str(scenario_file)})

        mission = self.host.resolve_exe("mission")
        if not mission:
            raise self.host.JsonRpcError(
                -32002,
                "mission executable not found",
                {
                    "tool": "validate_afsim_scenario",
                    "hint": "Set AFSIM_BIN, AFSIM_MISSION_PATH, or afsim_bin in the config.",
                },
            )

        timeout_sec = args.get("timeout_sec")
        timeout_sec = float(timeout_sec) if timeout_sec else 300.0
        base_dir = scenario_file.parent
        output_dir = Path(args["output_dir"]) if args.get("output_dir") else base_dir / "output"
        # Mission fails with "Unable to open system log/event_pipe file" if the
        # directory a scenario logs into does not exist yet.
        if args.get("create_output_dir", True):
            output_dir.mkdir(parents=True, exist_ok=True)

        cmd = [str(mission), scenario_file.name]
        timed_out = False
        try:
            result = run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=DEVNULL,
                cwd=str(base_dir),
                timeout=timeout_sec,
            )
            returncode = result.returncode
            combined = (result.stdout or "") + "\n" + (result.stderr or "")
        except TimeoutExpired as exc:
            timed_out = True
            returncode = None
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            combined = stdout + "\n" + stderr

        diagnostics = self.grammar.parse(combined, base_dir=base_dir)
        for diagnostic in diagnostics:
            match = re.search(r"Cannot open file:\s*(\S+)", diagnostic.get("message", ""))
            if match:
                diagnostic["include_resolution"] = self.resolve_include_hint(match.group(1))

        errors = [d for d in diagnostics if d["severity"] in ("ERROR", "FATAL")]
        warnings = [d for d in diagnostics if d["severity"] == "WARNING"]

        simulation_complete = self.grammar.is_complete(combined)
        outputs = self.summarize_outputs(output_dir, scenario_file.stem, scenario_dir=base_dir)

        # A run that places platforms and then does nothing is an experiment
        # that produced no result, even though Mission exits 0.
        activity_events = sum(
            count
            for name, count in outputs["evt_categories"].items()
            if name != "PLATFORM_INITIALIZED"
        )
        inert = (
            not errors
            and not timed_out
            and simulation_complete
            and outputs["evt_events"] > 0
            and activity_events == 0
        )
        # Two different situations, and conflating them misleads in both
        # directions: a run that wrote nothing at all is not evidence of
        # anything, while a run that produced a real .aer but no .evt events
        # did simulate and merely cannot be analysed.
        no_evidence = (
            not errors
            and not timed_out
            and simulation_complete
            and outputs["evt_events"] == 0
            and not outputs["files"]
        )
        not_analyzable = (
            not errors
            and not timed_out
            and simulation_complete
            and outputs["evt_events"] == 0
            and bool(outputs["files"])
        )

        requested_sec, declared = declared_duration(scenario_file)
        achieved_sec = achieved_duration(base_dir)
        duration = None
        if requested_sec and achieved_sec:
            duration = RunDuration(
                requested_sec,
                achieved_sec,
                "end_time declared" if declared else "AFSIM default (no end_time)",
                declared=declared,
            ).as_dict()

        settings = policy_module.resolve(
            {
                key: args[key]
                for key in (
                    "inert_is_failure",
                    "no_evidence_is_failure",
                    "not_analyzable_is_failure",
                    "unlocated_errors_are_environmental",
                )
                if key in args
            }
        )
        settings["default_timeout_sec"] = timeout_sec
        verdict = policy_module.judge(
            {
                "returncode": returncode,
                "errors": errors,
                "timed_out": timed_out,
                "simulation_complete": simulation_complete,
                "inert_simulation": inert,
                "no_evidence": no_evidence,
                "not_analyzable": not_analyzable,
                "duration": duration,
            },
            settings,
        )
        problems = verdict["problems"]
        caveats = verdict["caveats"]
        ok = verdict["ok"]
        payload = {
            "policy": verdict["policy"],
            "ok": ok,
            "validated": ok,
            "scenario_file": str(scenario_file),
            "returncode": returncode,
            "timed_out": timed_out,
            "simulation_complete": simulation_complete,
            "inert_simulation": inert,
            "no_evidence": no_evidence,
            "not_analyzable": not_analyzable,
            "duration": duration,
            "problems": problems,
            "caveats": caveats,
            "errors": errors[:20],
            "error_count": len(errors),
            "warning_count": len(warnings),
            "warnings": warnings[:10],
            "outputs": outputs,
        }
        if args.get("include_stdout"):
            # AFSIM puts behavioural diagnostics (show_state_transitions,
            # show_task_messages) on stdout, and those are often the only way to
            # find out why a tactics processor is not shooting.
            payload["stdout"] = self.host.truncate_text(combined, int(args.get("stdout_chars") or 20000))
        if ok:
            return self.host.wrap(payload)
        return self.host.wrap({"error": "AFSIM validation failed", **payload})
