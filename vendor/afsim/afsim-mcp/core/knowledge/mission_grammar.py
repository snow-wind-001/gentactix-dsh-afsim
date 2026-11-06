"""The grammar of mission.exe output.

This is the AFSIM 2.9 format, recorded as it actually appears:

    mission:
        WSF Version: 2.9.0 02-25-2022
    Loading simulation input.
    ***** FATAL: Could not process input files.
        ***** ERROR: Unknown command: totally_bogus_keyword
                 's.txt', line 2, near column 22
    Reading of simulation input failed
    Simulation complete
        Elapsed Wall Clock Time: 0.914619

Parsing is separated from interpretation on purpose. Whether a run "passed" is
a judgement, and judgements live in core/policy.py; this module only reports
what the text said.

Two earlier attempts at this failed and the reasons are worth keeping: a set of
hand-written regexes never matched the real output (it returned an empty list
against genuine mission.exe text), and a repair pass built on them then wrote
empty placeholder files over real ones and declared the result validated.
"""

import re
from pathlib import Path

# "***** ERROR: <message>" / "***** FATAL: ..." / "***** WARNING: ..."
MESSAGE_RE = re.compile(r"^\s*\*{2,}\s*(ERROR|FATAL|WARNING)\s*:\s*(.+?)\s*$")
# "'some_file.txt', line 12, near column 34"
LOCATION_RE = re.compile(
    r"^\s*'(?P<file>[^']+)'\s*,\s*line\s+(?P<line>\d+)\s*,\s*near column\s+(?P<column>\d+)"
)
# "***** FATAL: Could not process input files."
FATAL_PREFIX_RE = re.compile(r"^\s*\*{2,}\s*FATAL\s*:", re.IGNORECASE)
# "Cannot open file: observer.txt"
MISSING_FILE_RE = re.compile(r"Cannot open file:\s*(\S+)", re.IGNORECASE)
# "Could not find platform_type WIDGET"
MISSING_TYPE_RE = re.compile(r"Could not find (\w+) (\S+)", re.IGNORECASE)
# "Unable to compile script."
COMPILE_ERROR_RE = re.compile(r"Unable to compile script", re.IGNORECASE)

COMPLETION_MARKER = "Simulation complete"


class MissionGrammar:
    """Turns Mission's output into structured facts. No verdicts."""

    def __init__(self, host=None):
        self.host = host

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def parse(self, text, base_dir=None):
        """Return one dict per ERROR/FATAL/WARNING, with location when given."""
        diagnostics = []
        pending = None
        for raw_line in str(text or "").splitlines():
            message = MESSAGE_RE.match(raw_line)
            if message:
                pending = {
                    "severity": message.group(1),
                    "message": message.group(2),
                    "file": None,
                    "line": None,
                    "column": None,
                    "source_line": None,
                }
                diagnostics.append(pending)
                continue
            location = LOCATION_RE.match(raw_line)
            if location and pending is not None:
                name = location.group("file")
                if base_dir and not Path(name).is_absolute():
                    name = str(Path(base_dir) / name)
                pending["file"] = name
                pending["line"] = int(location.group("line"))
                pending["column"] = int(location.group("column"))
                pending["source_line"] = self.read_source_line(name, pending["line"])
                pending = None
        return diagnostics

    @staticmethod
    def read_source_line(path, line_number):
        if not path or not line_number:
            return None
        target = Path(path)
        if not target.is_file():
            return None
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
        if 1 <= line_number <= len(lines):
            return lines[line_number - 1].strip()
        return None

    # ------------------------------------------------------------------
    # Specific facts Mission reports
    # ------------------------------------------------------------------

    @staticmethod
    def is_complete(text):
        return COMPLETION_MARKER in str(text or "")

    @staticmethod
    def input_phase_failed(text):
        return bool(FATAL_PREFIX_RE.search(str(text or "")))

    @staticmethod
    def missing_files(text):
        return [m.group(1).strip("'\"") for m in MISSING_FILE_RE.finditer(str(text or ""))]

    @staticmethod
    def missing_types(text):
        """Types Mission could not resolve, e.g. ('platform_type', 'WIDGET')."""
        return [(m.group(1), m.group(2)) for m in MISSING_TYPE_RE.finditer(str(text or ""))]

    @staticmethod
    def has_compile_error(text):
        return bool(COMPILE_ERROR_RE.search(str(text or "")))


# --------------------------------------------------------------- run duration
# AFSIM's default is 60 seconds when the entry file declares no end_time. A
# scenario written for a two-hour engagement then silently runs for one minute
# and exits 0, so the tool has to compare what was asked for against what ran.

END_TIME_RE = re.compile(
    r"^[ \t]*end_time[ \t]+([0-9]*\.?[0-9]+)[ \t]*([A-Za-z]+)", re.MULTILINE
)
MISSION_LOG_COMPLETE_RE = re.compile(
    r"complete[ \t]+([0-9]*\.?[0-9]+)", re.IGNORECASE
)
UNIT_SECONDS = {
    "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
    "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
    "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0, "hours": 3600.0,
}
DEFAULT_DURATION_SEC = 60.0


class RunDuration:
    """What the scenario asked for versus what mission actually simulated."""

    def __init__(self, requested_sec, achieved_sec, source, declared=True):
        self.requested_sec = requested_sec
        self.achieved_sec = achieved_sec
        self.source = source
        self.declared = declared

    @property
    def ratio(self):
        if not self.requested_sec or not self.achieved_sec:
            return None
        return self.achieved_sec / self.requested_sec

    def as_dict(self):
        return {
            "requested_sec": self.requested_sec,
            "achieved_sec": self.achieved_sec,
            "ratio": round(self.ratio, 4) if self.ratio is not None else None,
            "source": self.source,
            "declared_end_time": self.declared,
        }


FILE_PATH_RE = re.compile(r"^[ \t]*file_path[ \t]+(\S+)", re.MULTILINE)
INCLUDE_RE = re.compile(r"^[ \t]*(include|include_once)[ \t]+(\S+)", re.MULTILINE)
DEFINE_PATH_VAR_RE = re.compile(
    r"^[ \t]*define_path_variable[ \t]+(\w+)[ \t]+(\S+)", re.MULTILINE
)
UNDEFINE_PATH_VAR_RE = re.compile(r"^[ \t]*undefine_path_variable[ \t]+(\w+)", re.MULTILINE)
# AFSIM accepts $(name) as well as ${name} for path variables. The paren
# form was missed, so any scenario using the documented spelling failed
# to resolve.
PATH_VAR_RE = re.compile(r"\$(?:\{|\()?(\w+)(?:\}|\))?")
COMMENT_RE = re.compile(r"//[^\n]*")


class IncludeResolver:
    """Locate include files the way AFSIM does.

    The search order is the one stated in the AFSIM File Commands page, which
    describes it as the same algorithm the C/C++ preprocessor uses:

      1. substitute $(name) / ${name} path variables
      2. an absolute name is used as-is
      3. concatenate onto the directory of the file being processed
      4. concatenate onto each file_path entry, in order, first hit wins
      5. otherwise return the name unchanged and let mission report it

    Two defects in this project came from not having this. A scenario kept its
    end_time in an included file and was reported as using AFSIM's 60 s
    default, and the "add this file_path" hint pointed at a demo root instead
    of the directory the missing file actually sits in.
    """

    def __init__(self, max_files=4000):
        self.max_files = max_files

    def read(self, path):
        try:
            return Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

    def substitute(self, name, variables):
        def replace(match):
            return variables.get(match.group(1), "")

        return PATH_VAR_RE.sub(replace, name)

    def path_variables(self, text, inherited):
        variables = dict(inherited)
        for match in DEFINE_PATH_VAR_RE.finditer(text):
            variables[match.group(1)] = self.substitute(match.group(2), variables)
        for match in UNDEFINE_PATH_VAR_RE.finditer(text):
            variables.pop(match.group(1), None)
        return variables

    def search(self, name, current_file, file_paths, variables):
        candidate = self.substitute(name, variables)
        if candidate.startswith("/") or (len(candidate) > 1 and candidate[1] == ":"):
            return Path(candidate) if Path(candidate).exists() else None
        base = Path(current_file).parent if current_file else Path(".")
        combined = base / candidate
        if combined.exists():
            return combined
        for entry in file_paths:
            combined = Path(entry) / candidate
            if combined.exists():
                return combined
        return None

    def resolve(self, entry_path):
        """Walk the include graph.

        Returns the files in visit order, the file_path entries accumulated in
        the order AFSIM applies them, and the includes that could not be found.
        """
        entry = Path(entry_path)
        visited = []
        seen = set()
        file_paths = []
        missing = []
        queue = [(entry, 0, {})]
        while queue and len(visited) < self.max_files:
            current, depth, inherited_vars = queue.pop(0)
            try:
                key = current.resolve()
            except OSError:
                key = current
            if key in seen:
                continue
            seen.add(key)
            text = self.read(current)
            if text is None:
                continue
            visited.append(current)
            variables = self.path_variables(text, inherited_vars)
            for match in FILE_PATH_RE.finditer(text):
                entry_value = self.substitute(match.group(1), variables)
                base = current.parent
                if not (entry_value.startswith("/") or (len(entry_value) > 1 and entry_value[1] == ":")):
                    entry_value = str(base / entry_value)
                file_paths.append(entry_value)
            for match in INCLUDE_RE.finditer(text):
                name = COMMENT_RE.sub("", match.group(2)).strip()
                found = self.search(name, current, file_paths, variables)
                if found is None:
                    missing.append({"include": name, "from": str(current), "file_path": list(file_paths)})
                else:
                    queue.append((found, depth + 1, variables))
        return visited, file_paths, missing

    def texts(self, entry_path):
        files, _file_paths, _missing = self.resolve(entry_path)
        return [(path, self.read(path) or "") for path in files]


def declared_duration(entry_path):
    """Seconds the scenario asks for, following includes.

    A top-level end_time is just as valid in an included file as in the entry
    file, and reading only the entry file reported a 7200 s run as "using
    AFSIM's 60 s default" while simultaneously reporting that it ran 7200 s.
    """
    entry = Path(entry_path)
    text = IncludeResolver().read(entry)
    if text is None:
        return None, False
    match = END_TIME_RE.search(text)
    if match:
        return _seconds(match), True
    for _path, body in IncludeResolver().texts(entry):
        match = END_TIME_RE.search(body)
        if match:
            return _seconds(match), True
    return DEFAULT_DURATION_SEC, False


def _seconds(match):
    value, unit = float(match.group(1)), match.group(2).lower()
    return value * UNIT_SECONDS.get(unit, 1.0)


def achieved_duration(working_dir):
    """What mission.log says it simulated, if it got that far."""
    log = Path(working_dir) / "mission.log"
    try:
        text = log.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = MISSION_LOG_COMPLETE_RE.search(text)
    return float(match.group(1)) if match else None
