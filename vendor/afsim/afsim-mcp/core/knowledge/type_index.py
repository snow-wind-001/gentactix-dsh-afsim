"""The AFSIM type index: what type names exist in this installation.

An invented name is rejected by mission.exe -- "Could not find platform_type X",
"Could not find sensor type Y" -- so both namespaces are closed and enumerable.
This service indexes the real definitions shipped in the AFSIM demos so a model
can pick from them instead of inventing them.

Two levels are indexed:

platform_types   top-level ``platform_type NAME BASE ... end_platform_type``
component_types  top-level ``sensor NAME BASE ... end_sensor`` and the same
                 shape for weapon / comm / processor / mover / filter / launcher
                 / jammer

The distinction is indentation: a declaration at column 0 defines a type, while
an indented one inside a platform_type is an instance ("sensor rdr1 aesa"
creates an instance named rdr1 of type aesa).

Every entry also records which keywords its block accepts and which
platform_types reference it, so a model can write a correct component without
guessing either the type name or the parameters it takes.
"""

import fnmatch
import json
import re
import time
from pathlib import Path

try:
    from .mission_grammar import PATH_VAR_RE, IncludeResolver
    from .source import iter_demo_files, read_normalized
except ImportError:
    from core.knowledge.mission_grammar import PATH_VAR_RE, IncludeResolver
    from core.knowledge.source import iter_demo_files, read_normalized

PLATFORM_TYPE_RE = re.compile(r"^platform_type[ \t]+(\S+)(?:[ \t]+(\S+))?[ \t]*$", re.M)

# A top-level `platform NAME TYPE ... end_platform` places a platform on the
# field. This is how a demo scenario file differs from a library file, and it
# is invisible from the type it happens to declare.
TOP_LEVEL_PLATFORM_RE = re.compile(
    r"^platform[ \t]+(\S+)(?:[ \t]+\S+)?[ \t]*(?://.*|#.*)?$", re.M
)

_UNSET = object()

# A component type declaration at column 0. Trailing // and # comments are not
# part of the type.
COMPONENT_TYPE_RE = re.compile(
    r"^(sensor|weapon|comm|processor|filter|mover|launcher|jammer)[ \t]+(\S+)(?:[ \t]+(\S+))?"
    r"[ \t]*(?://.*|#.*)?$",
    re.M,
)

# Inside a platform_type body: both "add mover X" and "mover X" are accepted.
# mover takes no instance name; every other component does.
COMPONENT_USE_RE = re.compile(
    r"^[ \t]+(?:add[ \t]+)?(mover|sensor|weapon|processor|comm|launcher|jammer|filter|fuel|"
    r"signature|magazine|store|transponder)[ \t]+(\S+)(?:[ \t]+(\S+))?[ \t]*(?://.*|#.*)?$",
    re.M,
)

# A demo scenario instantiates a type with `platform NAME TYPE ... end_platform`
# at column 0. How an instance is wired is not part of the type definition: the
# BRAWLER_TEST tactics processors stay idle unless the instance carries
# commander / command_chain and the script_variables their scripts read
# (MISSION_TYPE, ROUTE.Append, WINCHESTER, ...), and the entry file itself must
# define the script globals those scripts reference. Both facts live only in
# the demo entry files, so they are extracted next to the types that need them.
PLATFORM_INSTANCE_RE = re.compile(
    r"^platform[ \t]+(\S+)[ \t]+(\S+)[ \t]*(?://.*|#.*)?$", re.M
)
# The instance block's closer must be matched as a whole line: a substring
# search for "end_platform" also lands inside "end_platform_type".
INSTANCE_CLOSER_RE = re.compile(r"^end_platform[ \t]*$", re.M)
TOP_LEVEL_INCLUDE_RE = re.compile(r"^(include_once|include)[ \t]+(\S+)[ \t]*$", re.M)
TOP_LEVEL_ROUTE_RE = re.compile(r"^route[ \t]+(\S+)[ \t]*$", re.M)

# Nothing needs excluding here: a block's own indentation is the shallowest
# indent among its lines, so sub-blocks are already identified by being deeper.
# A few names that look like block openers are still keywords a model may want
# to write (`on` enables a sensor, `edit` modifies a component), so they are
# reported rather than filtered.

# Movers that state a domain, keyed by the mover a platform declares.
#
# Deliberately short. Counting the movers the demos actually use, the
# most frequent are WSF_AIR_MOVER (93 platforms), WSF_GUIDED_MOVER (83),
# WSF_P6DOF_MOVER (78), WSF_POINT_MASS_SIX_DOF_MOVER (43) -- and the second
# of those is a *missile* mover, as are WSF_FIRES_MOVER, WSF_UNGUIDED_MOVER,
# the per-weapon SAM movers and the ballistic movers. A missile has no domain:
# it flies through whatever it was fired into. So the table lists platform
# movers only and everything else resolves to "undetermined", which is the
# truthful answer and not a gap to be filled by guessing.
#
# The SDK headers declare WsfAirMover / WsfGroundMover / WsfSurfaceMover and
# their descendants, but the six-degree-of-freedom movers ship compiled into
# plugin DLLs with no header, so those two are identified by the names the
# demos use for them.
MOVER_DOMAINS = (
    (
        "air",
        (
            "WSF_AIR_MOVER",
            "WSF_BRAWLER_MOVER",
            "WSF_P6DOF_MOVER",
            "WSF_SIX_DOF_MOVER",
            "WSF_POINT_MASS_SIX_DOF_MOVER",
            "HELO_MOVER",
        ),
    ),
    ("ground", ("WSF_GROUND_MOVER", "WSF_KINEMATIC_MOVER", "WSF_OFF_ROAD_MOVER")),
    ("surface", ("WSF_SURFACE_MOVER", "WSF_SURFACE_MOVER_2D", "WSF_SHIP_MOVER")),
    ("space", ("WSF_SPACE_MOVER", "WSF_NORAD_SPACE_MOVER")),
)

# A processor is inert until its script variables are filled in. AA_TACTICS
# ships SENSOR_NAME and WEAPON_NAME empty, and a platform that adds the
# processor without configuring it will detect tracks and never fire. The
# values go in an on_initialize block -- redeclaring them in script_variables
# is rejected by mission.
SCRIPT_VARS_RE = re.compile(
    r"^[ \t]*script_variables[ \t]*$([\s\S]*?)^[ \t]*end_script_variables[ \t]*$", re.M
)
ON_INIT_RE = re.compile(
    r"^[ \t]*on_initialize[ \t]*$([\s\S]*?)^[ \t]*end_on_initialize[ \t]*$", re.M
)
VAR_DECL_RE = re.compile(
    r"^[ \t]*(?:string|int|double|bool|real|uint|WsfSensor|WsfWeapon|[A-Za-z_][\w:<>]*)[ \t]+"
    r"([A-Za-z_]\w*)[ \t]*(?:=[ \t]*([^;\n]+))?;",
    re.M,
)
VAR_ASSIGN_RE = re.compile(r"^[ \t]*([A-Za-z_]\w*)[ \t]*=[ \t]*([^;\n]+);", re.M)


# Performance characteristics live several blocks deep -- a radar's range and
# field of view sit inside a mode_template -- so they are collected at any
# indentation. Without these values a caller cannot tell whether a sensor can
# see a target at all, and a scenario's geometry becomes guesswork.
PERFORMANCE_KEYWORDS = {
    "maximum_range", "minimum_range", "maximum_altitude", "minimum_altitude",
    "azimuth_field_of_view", "elevation_field_of_view", "field_of_view",
    "frame_time", "update_interval", "slew_rate", "rotation_rate",
    "antenna_tilt", "beam_width", "azimuth_slew_limits", "elevation_slew_limits",
    # A zone states its extent as a radius, not a range. SR_SAM_TELAR's whole
    # engagement envelope is `zone full_kinematic { circular { maximum_radius
    # 6 nm; maximum_altitude 20000 ft } }`, and neither word was in this set,
    # so the one number that decides whether the launcher can reach a target
    # was invisible.
    "maximum_radius", "minimum_radius",
}
PERFORMANCE_RE = re.compile(
    r"^[ \t]*(%s)[ \t]+([^;\n#]+)" % "|".join(sorted(PERFORMANCE_KEYWORDS))
)

# `zone <name> circular|rectangular ... end_zone` is how a platform declares
# where it may operate or engage. The name matters: a tactics processor is
# pointed at a zone by string, so "full_kinematic" is both the extent and the
# handle a caller has to pass.
ZONE_RE = re.compile(
    r"^[ \t]*zone[ \t]+(\S+)(?:[ \t]+(circular|rectangular|latlon|polygon))?"
    r"([\s\S]*?)^[ \t]*end_zone[ \t]*$",
    re.M,
)
ZONE_LIMIT_RE = re.compile(
    r"^[ \t]*(maximum_radius|minimum_radius|maximum_altitude|minimum_altitude|"
    r"maximum_range|minimum_range|maximum_latitude|minimum_latitude|"
    r"maximum_longitude|minimum_longitude)[ \t]+([^;\n#]+)",
    re.M,
)


CACHE_MAX_AGE_HOURS = 24

# Bump when extraction rules change so catalogs written by older rules are
# rebuilt instead of served from cache.
EXTRACTION_VERSION = 11


class AfsimTypeIndex:
    def __init__(self, host):
        self.host = host
        self._file_names = _UNSET

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------

    def catalog_path(self):
        return self.host.state_dir / "afsim_catalog.json"

    @staticmethod
    def _block_body(text, start, closer):
        end = text.find(closer, start)
        return text[start:end] if end != -1 else ""

    @staticmethod
    def _keywords(body):
        """Direct keyword children of a block, ignoring nested blocks.

        A block's own indentation is the shallowest indent among its non-blank
        lines; anything deeper belongs to a sub-block.
        """
        lines = [
            line
            for line in body.splitlines()
            if line.strip() and not line.strip().startswith(("#", "//"))
        ]
        if not lines:
            return []
        base = min(len(line) - len(line.lstrip()) for line in lines)
        found = set()
        for line in lines:
            if len(line) - len(line.lstrip()) != base:
                continue
            head = line.strip().split()[0]
            if head.startswith("end_"):
                continue
            found.add(head)
        return sorted(found)

    @staticmethod
    @staticmethod
    def _performance(body):
        """Sensor / mover performance values, at whatever depth they appear."""
        found = {}
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "//")):
                continue
            match = PERFORMANCE_RE.match(line)
            if not match:
                continue
            value = match.group(2).strip()
            if not value:
                continue
            found.setdefault(match.group(1), []).append(value)
        return {key: values for key, values in sorted(found.items())}

    @staticmethod
    def _requirement_statements(documented, per_page=2):
        """Flatten documented_requirements() into a list of quoted sentences.

        The payload also carries a _coverage entry describing how much of the
        documentation was searched, which is not a requirement statement.
        """
        statements = []
        for entry in (documented or {}).values():
            if not isinstance(entry, dict) or "statements" not in entry:
                continue
            statements.extend(entry["statements"][:per_page])
        return statements

    @staticmethod
    def _zones(body):
        """Every `zone NAME ... end_zone` in a body, with its extent.

        A zone is where a platform may operate or engage, and its name is the
        handle a tactics processor is given in ENVELOPE = "...". Reporting the
        extent without the name, or the name without the extent, leaves the
        caller unable to connect the two.
        """
        zones = []
        for match in ZONE_RE.finditer(body or ""):
            name, shape, inner = match.group(1), match.group(2), match.group(3)
            limits = {}
            for limit in ZONE_LIMIT_RE.finditer(inner):
                limits[limit.group(1)] = limit.group(2).strip()
            zones.append(
                {
                    "name": name,
                    "shape": shape or "circular",
                    "extent": {key: limits[key] for key in sorted(limits)},
                }
            )
        return zones

    @staticmethod
    def _on_initialize_blocks(body):
        """Each on_initialize block in a body, as a list of {var: value}."""
        blocks = []
        for block in ON_INIT_RE.findall(body or ""):
            assignments = [
                {match.group(1): (match.group(2) or "").strip()}
                for match in VAR_ASSIGN_RE.finditer(block)
            ]
            if assignments:
                blocks.append(assignments)
        return blocks

    @staticmethod
    def _task_dependent(body):
        """Whether this processor only fires once tasks reach it over C2.

        A tactics processor's state machine reads like any other: DETECTED,
        then ENGAGEABLE, then ENGAGE. What decides whether ENGAGE is ever
        entered is not the geometry but a task:

            next_state ENGAGE
               Engage();
               return (TrackingNow() && (TasksAssignedFor(TRACK.TrackId(), mTrackTaskStr) > 0));

        and IsAssignable() only returns true for a Commander, a received task,
        or an ENGAGE operating level it was already granted. So a platform
        carrying one of these can detect a target, hold it in ENGAGEABLE and
        never fire, with no error anywhere -- which is what an empty
        derivation of SR_SAM_TELAR does: 24 rounds become 0, mission still
        exits 0, and nothing in the output says why.

        Detected from the script, so it is a property of the shipped
        processor rather than a guess about what such a platform might need.
        """
        text = body or ""
        # A lookbehind rather than a word boundary: a boundary also matches the
        # "Engage" inside "IsEngageable", which asks whether a track is
        # engageable and says nothing about whether anything fires.
        fires = re.search(r"(?<![A-Za-z])Engage\s*\(", text) or re.search(
            r'ChangeOperatingLevel\s*\(\s*"ENGAGE"', text
        )
        if not fires:
            return None
        gates = sorted(
            {m.group(0) for m in re.finditer(
                r"TasksAssignedFor|TasksReceivedFor|IsAssignable|PLATFORM\.Commander", text
            )}
        )
        if not gates:
            return None
        return {
            "gating_calls": gates,
            "note": "Firing is gated on task flow: this processor enters ENGAGE only when a "
            "task has been assigned or received, which requires a working comm / C2 link. "
            "A platform carrying it can detect, track and hold ENGAGEABLE indefinitely "
            "and never fire, with no error reported.",
        }

    @staticmethod
    def _script_interface(body):
        """What a scripted processor needs before it will do anything.

        Returns the variables it declares, the ones that default to empty (so
        they must be supplied), and an example on_initialize block showing how
        the demos actually configure it.
        """
        declared = {}
        for block in SCRIPT_VARS_RE.findall(body):
            for match in VAR_DECL_RE.finditer(block):
                name, value = match.group(1), (match.group(2) or "").strip()
                declared[name] = value
        assignments = []
        for block in ON_INIT_RE.findall(body):
            for match in VAR_ASSIGN_RE.finditer(block):
                assignments.append({match.group(1): (match.group(2) or "").strip()})
        if not declared and not assignments:
            return None
        # Which variables default to empty is a fact; whether you must set one
        # is not. AA_TACTICS is the counterexample: SENSOR_NAME is empty by
        # default, and setting it raises the track-quality gate from 0.49 to
        # 0.95 and adds a sensor-mode requirement, so "empty" does not mean
        # "required" -- it can mean the opposite.
        empty_by_default = sorted(
            name
            for name, value in declared.items()
            if not name.startswith("m") and value.strip() in ('""', "''", "")
        )
        return {
            "script_variables": dict(sorted(declared.items())),
            "empty_by_default": empty_by_default,
            "configurable_via_on_initialize": bool(assignments),
            "example_setup": assignments[:1],
            "note": "A variable being empty by default does not mean it has to be set. "
            "Read the processor's script, or copy a working_configuration below.",
        }

    def build_catalog(self):
        demos = self.host.resolve_demos_root()
        if not demos or not demos.is_dir():
            raise self.host.JsonRpcError(
                -32003,
                "AFSIM demos directory not found",
                {
                    "hint": "Set afsim_root or demos_dir; the catalog is built from the demos "
                    "that ship with AFSIM.",
                },
            )

        platforms = {}
        components = {}
        used_by = {}
        instantiations = []
        entry_facts = {}
        include_targets = {}
        prologue_by_file = {}

        for path in iter_demo_files(demos):
            try:
                # AFSIM demos are Windows-authored, and a trailing carriage
                # return defeats every end-of-line anchor in this module,
                # which silently drops declarations.
                text = read_normalized(path)
            except OSError:
                continue

            for match in COMPONENT_TYPE_RE.finditer(text):
                kind, name, base = match.group(1), match.group(2), match.group(3)
                key = f"{kind}:{name}"
                body = self._block_body(text, match.end(), f"end_{kind}")
                record = {
                    "kind": kind,
                    "name": name,
                    "base": base or f"WSF_{kind.upper()}",
                    "defined_in": str(path.relative_to(demos)).replace("\\", "/"),
                    "parameters": self._keywords(body),
                    "used_by": [],
                }
                performance = self._performance(body)
                if performance:
                    record["performance"] = performance
                interface = self._script_interface(body)
                if interface:
                    record["script_interface"] = interface
                task_dependent = self._task_dependent(body)
                if task_dependent:
                    record["task_dependent"] = task_dependent
                # A processor's own definition often carries the on_initialize
                # block that configures it -- TELAR_TASK_MGR ships with
                # ACQ_SENSOR_NAME, SENSOR_NAME and WEAPON_NAME all set, while
                # no platform_type in the demos does. That block is written by
                # whoever wrote the type, so it outranks anything assembled
                # from a consumer.
                own_setup = self._on_initialize_blocks(body)
                if own_setup:
                    record["own_on_initialize"] = own_setup
                previous = components.get(key)
                if previous is None or _record_score(record) > _record_score(previous):
                    record["used_by"] = previous.get("used_by", []) if previous else []
                    components[key] = record

            for match in PLATFORM_TYPE_RE.finditer(text):
                name, base = match.group(1), match.group(2) or "WSF_PLATFORM"
                body = self._block_body(text, match.end(), "end_platform_type")
                declared = {}
                for kind, first, second in COMPONENT_USE_RE.findall(body):
                    value = first if kind == "mover" else (second or first)
                    if value.startswith("end_") or value.startswith("$"):
                        continue
                    declared.setdefault(kind, []).append(value)
                relative = path.relative_to(demos)
                # Blocks are kept whole. An on_initialize block is copied as a
                # unit, and a processor that needs SENSOR_NAME and WEAPON_NAME
                # only works when both are set in the same block -- so a flat
                # list of assignments cannot be used to reproduce one.
                setup = self._on_initialize_blocks(body)
                record = {
                    "on_initialize": setup,
                    "name": name,
                    "base": base,
                    "defined_in": str(relative).replace("\\", "/"),
                    "demo_dir": relative.parts[0] if len(relative.parts) > 1 else ".",
                    "include_path": "/".join(relative.parts[1:]) or relative.name,
                    "components": {k: sorted(set(v)) for k, v in sorted(declared.items())},
                    "zones": self._zones(body),
                    "performance": self._performance(body),
                }
                previous = platforms.get(name)
                if previous is None or _platform_score(record) > _platform_score(previous):
                    platforms[name] = record

            # Instance wiring is a scenario-file fact, not a type fact, but it
            # is what makes the type behave the way the demo behaves, so it is
            # collected in the same pass and attached to the types below.
            # Includes and prologues are recorded for every file because the
            # merge below walks the include chain between entry and layout.
            rel_path = str(path.relative_to(demos)).replace("\\", "/")
            include_matches = list(TOP_LEVEL_INCLUDE_RE.finditer(text))
            if include_matches:
                include_targets[rel_path] = [m.group(2) for m in include_matches]
            prologue, names, prologue_offset = _global_prologue(text)
            if prologue:
                # The include order around the prologue is part of the recipe:
                # observers consuming the globals sit after the block.
                before = [m.group(2) for m in include_matches if m.start() < prologue_offset]
                after = [m.group(2) for m in include_matches if m.start() > prologue_offset]
                prologue_by_file[rel_path] = (prologue, names, _defines(text), before, after)
            file_instances = []
            for match in PLATFORM_INSTANCE_RE.finditer(text):
                closer = INSTANCE_CLOSER_RE.search(text, match.end())
                body = text[match.end():closer.start()] if closer else ""
                file_instances.append(
                    {
                        "file": rel_path,
                        "instance": match.group(1),
                        "type": match.group(2),
                        "facts": _instance_facts(body),
                    }
                )
            if file_instances:
                instantiations.extend(file_instances)
                entry_facts[rel_path] = _entry_facts(text)

        for name, record in platforms.items():
            effective = _effective_components(record, platforms)
            record["effective_components"] = effective
            # Zones and performance limits inherit like components do, and an
            # engagement envelope usually lives in the base type, so a derived
            # launcher's own block alone understates what it can reach.
            inherited_zones = {}
            for zone in _chain_records(record, platforms):
                for item in zone.get("zones") or []:
                    inherited_zones.setdefault(item["name"], item)
            record["effective_zones"] = [inherited_zones[key] for key in sorted(inherited_zones)]
            inherited_limits = {}
            for level in reversed(_chain_records(record, platforms)):
                for key, values in (level.get("performance") or {}).items():
                    merged = inherited_limits.setdefault(key, [])
                    for value in values:
                        if value not in merged:
                            merged.append(value)
            record["effective_performance"] = {
                key: inherited_limits[key] for key in sorted(inherited_limits)
            }
            record["has_sensors"] = bool(effective.get("sensor"))
            record["has_weapons"] = bool(effective.get("weapon"))
            record["has_processors"] = bool(effective.get("processor"))
            # "armed" used to mean "declares a sensor or a weapon", which called
            # a radar-only SAM site armed. An agent picking a defender was
            # told a type could fight when it carries no missile at all --
            # SAM-MR has a seeker and four processors and no weapon, and a
            # scenario built on it ran clean, exited 0, and never fired.
            record["armed"] = record["has_sensors"] or record["has_weapons"]
            record["can_engage"] = record["has_weapons"] and record["has_processors"]
            # A processor whose state machine only enters ENGAGE once a task
            # has been assigned turns can_engage into a promise the platform
            # cannot keep on its own. Naming them is the difference between
            # "this type can fight" and "this type fires only if its C2 link
            # delivers tasks", which is what an empty derivation of
            # SR_SAM_TELAR silently breaks.
            record["task_dependent_processors"] = sorted(
                {
                    value
                    for value in effective.get("processor", [])
                    if _chain_has_flag(components, "processor", value, "task_dependent")
                }
            )
            record["inherited_from_base"] = sorted(
                k for k in effective if not record["components"].get(k)
            )
            record["domain"] = _infer_domain(record, platforms)
            for kind, values in record["components"].items():
                for value in values:
                    used_by.setdefault(f"{kind}:{value}", set()).add(name)

        for key, record in components.items():
            record["used_by"] = sorted(used_by.get(key, ()))[:12]

        # WSF_* classes are compiled into the AFSIM libraries, so they never
        # appear as a declaration in the demos. Every one that shows up as a
        # base class or in a component-use position was parsed by mission at
        # some point, which makes it a name known to exist even though this
        # catalog cannot claim the set is complete.
        library = {}
        for record in components.values():
            base = record.get("base")
            if base and base.upper().startswith("WSF_"):
                entry = library.setdefault(base, {"kind": record["kind"], "seen_in": []})
                entry["seen_in"].append(f"base of {record['kind']}:{record['name']}")
        for name, record in platforms.items():
            base = record.get("base")
            if base and base.upper().startswith("WSF_"):
                entry = library.setdefault(base, {"kind": "platform_type", "seen_in": []})
                entry["seen_in"].append(f"base of platform_type:{name}")
        # A platform can reference a WSF_* class directly ("mover WSF_AIR_MOVER")
        # without any demo ever declaring a type of that name.
        for name, record in platforms.items():
            for kind, values in record["components"].items():
                for value in values:
                    if value.upper().startswith("WSF_"):
                        entry = library.setdefault(value, {"kind": kind, "seen_in": []})
                        entry["seen_in"].append(f"used by platform_type:{name}")
        for entry in library.values():
            entry["seen_in"] = sorted(set(entry["seen_in"]))[:8]

        # A demo entry often delegates its force layout to an included
        # scenarios/<name>.txt -- usually through a path variable such as
        # ${SCNRIO} -- and the script-globals prologue lives in the parent
        # entry while the instances live in the child. Until the parent's
        # prologue and defines are merged down, the child's examples answer
        # "how is the platform wired" but leave the part that fails first
        # unsolved.
        exact_includers = {}
        pattern_includers = []
        for includer, target_list in include_targets.items():
            # Include targets resolve against the including file's directory
            # first, so a variable-bearing target matches the child through
            # the includer's demo dir, not from the demos root.
            includer_dir = includer.rsplit("/", 1)[0] if "/" in includer else ""
            for target in target_list:
                normalized = target.replace("\\", "/")
                base = normalized.split("/")[-1]
                if PATH_VAR_RE.search(base):
                    pattern = PATH_VAR_RE.sub("*", normalized)
                    if includer_dir and not normalized.startswith("/"):
                        pattern = includer_dir + "/" + pattern
                    pattern_includers.append((pattern, includer))
                else:
                    exact_includers.setdefault(base, []).append(includer)
        for rel_path, facts in entry_facts.items():
            if facts["global_script_prologue"]:
                continue
            base = rel_path.split("/")[-1]
            candidates = list(exact_includers.get(base, []))
            if not candidates:
                candidates = [
                    includer
                    for pattern, includer in pattern_includers
                    if fnmatch.fnmatch(rel_path, pattern)
                ]
            candidates = [c for c in candidates if c != rel_path and c in prologue_by_file]
            candidates.sort(
                key=lambda c: (0 if c.split("/")[0] == rel_path.split("/")[0] else 1, c)
            )
            if candidates:
                parent = candidates[0]
                prologue, names, defines, _, _ = prologue_by_file[parent]
                facts["prologue_from"] = parent
                facts["global_script_prologue"] = prologue
                facts["global_script_variables"] = names
                facts["defines"] = defines
                # The parent's include order around its prologue is part of
                # the same setup: the layout include and the type files come
                # first, the observers that consume the globals come after.
                _, _, _, before, after = prologue_by_file[parent]
                facts["parent_includes_before_prologue"] = before
                facts["parent_includes_after_prologue"] = after

        # The examples ride along with the entry facts because the prologue
        # globals and the extra includes are part of the same working setup:
        # an entry that instantiates BRAWLER_TEST types without the globals
        # their scripts reference fails before the first platform initializes.
        demo_usages = {}
        for item in instantiations:
            if item["type"] not in platforms:
                continue
            demo_usages.setdefault(item["type"], []).append(
                {
                    "file": item["file"],
                    "instance": item["instance"],
                    "wiring": item["facts"],
                    "entry": entry_facts.get(item["file"]),
                }
            )
        for type_name, examples in demo_usages.items():
            # The entry prologue outranks wiring length: an example whose
            # entry carries the copyable script prologue is a complete recipe
            # on its own, while more script_variables on an entry that hides
            # its globals elsewhere leaves the hardest part unsolved.
            examples.sort(
                key=lambda e: (
                    1 if (e.get("entry") or {}).get("global_script_prologue") else 0,
                    _instantiation_score(e["wiring"]),
                ),
                reverse=True,
            )
            demo_usages[type_name] = examples[:3]

        file_facts = self._analyze_defining_files(platforms)
        for record in platforms.values():
            facts = file_facts.get(record.get("defined_in"))
            if facts:
                record["defining_file_facts"] = facts

        payload = {
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "extraction_version": EXTRACTION_VERSION,
            "demos_root": str(demos),
            "platform_type_count": len(platforms),
            "component_type_count": len(components),
            "library_type_count": len(library),
            "armed_platform_count": sum(1 for r in platforms.values() if r["armed"]),
            "platform_types": platforms,
            "component_types": components,
            "library_types": library,
            "demo_usages": demo_usages,
        }
        self.host.write_json(self.catalog_path(), payload)
        return payload

    def load_catalog(self, *, refresh=False, max_age_hours=CACHE_MAX_AGE_HOURS):
        path = self.catalog_path()
        if refresh or not path.is_file():
            return self.build_catalog()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.build_catalog()
        if payload.get("extraction_version") != EXTRACTION_VERSION:
            return self.build_catalog()
        demos = self.host.resolve_demos_root()
        if demos and payload.get("demos_root") != str(demos):
            return self.build_catalog()
        try:
            if (time.time() - path.stat().st_mtime) / 3600.0 > max_age_hours:
                return self.build_catalog()
        except OSError:
            return self.build_catalog()
        return payload

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def catalog_entry(self, name, kind="platform_type"):
        try:
            catalog = self.load_catalog()
        except Exception:
            return None
        if kind == "platform_type":
            return catalog["platform_types"].get(name)
        found = catalog["component_types"].get(f"{kind}:{name}")
        if found:
            return found
        # WSF_* library classes are valid but never declared in the demos.
        return catalog.get("library_types", {}).get(name)

    def suggest_types(self, name, kind=None, limit=8):
        """Closest real type names, for one a model invented."""
        try:
            catalog = self.load_catalog()
        except Exception:
            return []
        wanted = str(name or "").lower()
        if not wanted:
            return []
        if kind:
            pool = [
                key.split(":", 1)[1]
                for key in catalog["component_types"]
                if key.startswith(f"{kind}:")
            ]
        else:
            pool = list(catalog["platform_types"])
        scored = []
        for candidate in pool:
            lower = candidate.lower()
            if lower == wanted:
                continue
            if wanted in lower or lower in wanted:
                scored.append((0, candidate))
            else:
                shared = len(set(wanted) & set(lower))
                if shared >= 3:
                    scored.append((shared, candidate))
        scored.sort()
        return [name for _, name in scored[:limit]]

    # ------------------------------------------------------------------
    # The tool
    # ------------------------------------------------------------------

    def afsim_types(self, args):
        name = args.get("name")
        kind = (args.get("kind") or "").lower() or None
        if name and kind:
            return self.describe_component(name, kind)
        if name:
            return self.describe_platform(name)
        if kind:
            return self.list_components(args, kind)
        return self.list_platforms(args)

    def list_platforms(self, args):
        catalog = self.load_catalog(refresh=bool(args.get("refresh")))
        domain = (args.get("domain") or "").lower() or None
        keyword = (args.get("keyword") or "").lower() or None
        # Whether an unarmed platform is useless is a domain judgement, not a
        # fact, so the default lists everything and surfaces `armed` for the
        # caller to weigh. Pass armed_only to narrow it.
        armed_only = bool(args.get("armed_only"))

        selected = []
        for record in catalog["platform_types"].values():
            if domain and record.get("domain") != domain:
                continue
            if armed_only and not record.get("armed"):
                continue
            if keyword and keyword not in json.dumps(record, ensure_ascii=False).lower():
                continue
            selected.append(record)

        # Presentation, not policy: the most capable types surface first.
        selected.sort(key=lambda r: (not r.get("armed"), -_richness(r), r["name"]))
        limit = int(args.get("limit") or 40)
        return self.host.wrap(
            {
                "listing": "platform_type",
                "total_in_catalog": catalog["platform_type_count"],
                "armed_in_catalog": catalog["armed_platform_count"],
                "total_matching": len(selected),
                "types": [
                    {
                        "name": r["name"],
                        "domain": r.get("domain"),
                        "base": r["base"],
                        "sensors": len(r["effective_components"].get("sensor", [])),
                        "weapons": len(r["effective_components"].get("weapon", [])),
                        "processors": len(r["effective_components"].get("processor", [])),
                        "can_engage": r.get("can_engage"),
                        "task_dependent": bool(r.get("task_dependent_processors")),
                        "loads": (r.get("defining_file_facts") or {}).get("loads"),
                        "defining_file_instantiates": len(
                            (r.get("defining_file_facts") or {}).get("instantiates_platforms") or []
                        ),
                        "defined_in": r["defined_in"],
                    }
                    for r in selected[:limit]
                ],
                "hint": "pass name to inspect one, or kind to list component types "
                "(sensor / weapon / mover / processor / comm / filter).",
            }
        )

    def list_components(self, args, kind):
        catalog = self.load_catalog(refresh=bool(args.get("refresh")))
        keyword = (args.get("keyword") or "").lower() or None
        prefix = f"{kind}:"
        selected = [
            record
            for key, record in catalog["component_types"].items()
            if key.startswith(prefix)
            and (not keyword or keyword in json.dumps(record, ensure_ascii=False).lower())
        ]
        if args.get("include_built_in"):
            for name, record in catalog.get("library_types", {}).items():
                if record["kind"] != kind:
                    continue
                if keyword and keyword not in json.dumps(record, ensure_ascii=False).lower():
                    continue
                selected.append(
                    {"name": name, "base": None, "defined_in": None, "used_by": [],
                     "used_by_count": 0, "built_in": True}
                )
        selected.sort(key=lambda r: (-len(r.get("used_by", [])), r["name"]))
        limit = int(args.get("limit") or 40)
        return self.host.wrap(
            {
                "listing": f"{kind}_type",
                "total_in_catalog": catalog["component_type_count"],
                "library_type_count": catalog.get("library_type_count", 0),
                "total_matching": len(selected),
                "types": [
                    {
                        "name": r["name"],
                        "base": r["base"],
                        "defined_in": r["defined_in"],
                        "used_by_count": len(r.get("used_by", [])),
                        "used_by": r.get("used_by", [])[:6],
                    }
                    for r in selected[:limit]
                ],
                "hint": f"pass name and kind='{kind}' to see the parameters this type accepts.",
            }
        )

    def describe_platform(self, name):
        catalog = self.load_catalog()
        record = catalog["platform_types"].get(name)
        if not record:
            built_in = catalog.get("library_types", {}).get(name)
            if built_in:
                # AFSIM library classes ship compiled into the binaries. They
                # are in the catalog because demos reference them, but there is
                # no demo source to read parameters out of -- saying so is more
                # useful than "not defined", which is what this used to return
                # for WSF_TASK_PROCESSOR and every other WSF_ class.
                try:
                    documented = self.host.command_reference.documented_requirements([name])
                except Exception:
                    documented = {}
                return self.host.wrap(
                    {
                        "kind": built_in["kind"],
                        "name": name,
                        "built_in": True,
                        "defined_in": None,
                        "seen_in": built_in.get("seen_in", []),
                        "documented_requirements": self._requirement_statements(documented),
                        "hint": "An AFSIM library class: compiled into the binaries rather "
                        "than declared in a demo, so there is no source here to read a "
                        "parameter list out of. The demos that reference it are in "
                        "seen_in -- reading one of those is the only way to see it wired up.",
                    }
                )
            return self.host.wrap(
                {
                    "error": f"platform_type {name!r} is not defined in the AFSIM demos",
                    "did_you_mean": self.suggest_types(name),
                    "hint": "mission.exe rejects undefined platform_type names; pick one "
                    "from the listing.",
                }
            )
        return self.host.wrap(
            {
                "kind": "platform_type",
                "name": record["name"],
                "base": record["base"],
                "domain": record.get("domain"),
                "armed": record["armed"],
                "has_sensors": record["has_sensors"],
                "has_weapons": record["has_weapons"],
                "has_processors": record["has_processors"],
                "can_engage": record["can_engage"],
                "task_dependent_processors": record.get("task_dependent_processors") or [],
                "task_dependent_note": (
                    "These processors enter ENGAGE only once a task has been assigned or "
                    "received over C2. can_engage stays true because the platform does carry "
                    "a weapon and a processor, but it will hold ENGAGEABLE and never fire if "
                    "the comm link never delivers a task -- silently, with no error."
                    if record.get("task_dependent_processors")
                    else None
                ),
                "defining_file": record.get("defining_file_facts"),
                "zones": record.get("effective_zones") or [],
                "performance": record.get("effective_performance") or {},
                "envelope_note": (
                    "zones are the operating and engagement envelopes this type declares, "
                    "including any inherited from its base chain. A zone's name is the "
                    "handle a tactics processor takes in ENVELOPE = \"...\"; its extent is "
                    "the limit that actually gates whether a shot is taken. No geometric "
                    "bisection is needed to find either."
                ),
                "components": record["components"],
                "effective_components": record["effective_components"],
                "inherited_from_base": record["inherited_from_base"],
                "capability_note": (
                    "can_engage is true when the type carries both a weapon and a "
                    "processor, counting what it inherits from its base chain. It is "
                    "necessary, not sufficient: a scripted processor can still be inert "
                    "until its script variables are set, and mission does not reject an "
                    "unwired platform at load time -- the scenario runs, exits 0, and "
                    "never fires."
                ),
                "demo_dir": record.get("demo_dir"),
                "include_path": record.get("include_path"),
                "defined_in": record["defined_in"],
                "demo_instantiations": catalog.get("demo_usages", {}).get(name) or [],
                "instantiation_note": (
                    "How demo scenarios wire an instance of this type. The C2 links "
                    "(commander / command_chain) and the script_variables block are set "
                    "on the platform instance, not on the type, and the entry file "
                    "itself carries the includes and the top-level script_variables "
                    "block that the processors' scripts read. Copying one of these "
                    "configurations is how the type is meant to be used; an instance "
                    "placed without its wiring detects and tracks but never fires."
                    if catalog.get("demo_usages", {}).get(name)
                    else None
                ),
            }
        )

    def _analyze_defining_files(self, platforms):
        """What happens when you include the file a type is defined in.

        Two questions decide whether a demo type is usable, and neither was
        answerable from the catalog before:

        - Does the file's include closure resolve? `base_types` in the shipped
          demos pulls in `../signatures/blue_multirole_fighter_3_radar_signature.txt`,
          a file that does not exist anywhere in the installation, so every
          `*_ripr.txt` type in that tree cannot be loaded at all. The catalog
          listed them as if they were fine.
        - Does including the file also instantiate platforms? A demo scenario
          file declares types *and* places platforms, so including one to
          borrow a type drags in the demo's own order of battle and its
          end_time. The only way to find out was to read the file, which is
          exactly what an agent working through this server is told not to do.

        Analysis is per file, not per type: 657 types come from 455 files.
        """
        demos = self.host.resolve_demos_root()
        if not demos:
            return {}
        demos = Path(demos)
        wanted = sorted({r["defined_in"] for r in platforms.values() if r.get("defined_in")})
        resolver = IncludeResolver()
        facts = {}
        for relative in wanted:
            path = demos / relative
            text = self._read_normalized(path)
            if text is None:
                facts[relative] = {"readable": False}
                continue
            # Include resolution depends on the file_path entries declared
            # around the include, so resolve from the file itself.
            _files, _paths, missing = resolver.resolve(path)
            missing = list(missing)
            # A path variable whose value depends on the platform type being
            # instantiated cannot be resolved from the file alone.
            contextual = [m for m in missing if _has_unsubstituted_var(m["include"])]
            # A relative include that did not resolve may simply mean the demo
            # is meant to be included from an entry file that sets file_path --
            # that is what file_path is for. Only a name that exists nowhere
            # in the installation proves the file cannot load. Calling a
            # merely-unresolved relative name "unloadable" condemned 135 types
            # that the demos themselves include successfully.
            install = self._install_file_names()
            hard_missing = []
            for item in missing:
                if item in contextual:
                    continue
                leaf = item["include"].replace("\\", "/").rsplit("/", 1)[-1]
                if install is None or leaf not in install:
                    hard_missing.append(item)
            soft_missing = [m for m in missing if m not in hard_missing and m not in contextual]
            instantiated = sorted(
                {
                    match.group(1)
                    for match in TOP_LEVEL_PLATFORM_RE.finditer(text)
                }
            )
            if hard_missing:
                loads = False
            elif contextual or soft_missing:
                loads = None
            else:
                loads = True
            entry = {
                "readable": True,
                "instantiates_platforms": instantiated,
                "missing_includes": [m["include"] for m in hard_missing][:6],
                "unresolved_relative_includes": [m["include"] for m in soft_missing][:4],
                "context_dependent_includes": [m["include"] for m in contextual][:4],
                "loads": loads,
            }
            if hard_missing:
                entry["note"] = (
                    "This file includes a name that does not exist anywhere in the AFSIM "
                    "installation, so a type defined here cannot be loaded. Declaring it "
                    "in a scenario fails at include time."
                )
            elif contextual or soft_missing:
                entry["note"] = (
                    "Some includes did not resolve from this file alone -- they are "
                    "relative names or names built from a path variable, which AFSIM "
                    "resolves through file_path entries supplied by whichever entry file "
                    "includes it. Whether this file loads is unproven here, not refuted."
                )
            if instantiated:
                entry["note"] = (entry.get("note", "") + " " if entry.get("note") else "") + (
                    "Including this file also places " + str(len(instantiated)) + " platform(s) "
                    "(" + ", ".join(instantiated[:6]) + "). Borrow a type from it and you "
                    "borrow the demonstration order of battle and its end_time with it."
                )
            facts[relative] = entry
        return facts

    def _install_file_names(self):
        """Every filename present under AFSIM_ROOT, built once per catalog.

        Used to tell an include that is genuinely absent from the product
        from one that merely did not resolve from the file being examined.
        """
        if self._file_names is not _UNSET:
            return self._file_names
        root = self.host.resolve_afsim_root()
        names = None
        if root:
            found = set()
            try:
                for path in Path(root).rglob("*"):
                    if path.is_file():
                        found.add(path.name.lower())
            except OSError:
                pass
            names = found or None
        self._file_names = names
        return names

    def _read_normalized(self, path):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
        return text.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))

    def _derived_with_setup(self, catalog, kind, name):
        """The nearest type at or below `name` that ships its own configuration.

        AFSIM lets a demo specialise a library processor:

            processor SR_SAM_TELAR_TASK_MGR TELAR_TASK_MGR
               on_initialize
                  ACQ_SENSOR_NAME = "...";
                  SENSOR_NAME     = "...";
                  WEAPON_NAME     = "sam";
               end_on_initialize
            end_processor

        TELAR_TASK_MGR itself declares no block, so looking only at the type
        being asked about finds nothing and the caller is told to infer the
        values -- while the answer is sitting in a one-line derivation away.
        """
        components = catalog.get("component_types", {})
        direct = (components.get(f"{kind}:{name}") or {}).get("own_on_initialize")
        if direct:
            return name, direct
        best = None
        for key, record in components.items():
            if not key.startswith(f"{kind}:"):
                continue
            blocks = record.get("own_on_initialize")
            if not blocks:
                continue
            if _derives_from(record, name, components, kind):
                if best is None or len(blocks) > len(best[1]):
                    best = (record["name"], blocks)
        return best

    def find_working_configuration(self, catalog, kind, name, interface):
        """Every demo that configures this component, best example first.

        A tactics processor that must be handed SENSOR_NAME and WEAPON_NAME is
        the single most common reason a scenario detects but never fires, and
        the demos show the correct on_initialize block. Returning only the
        first match meant one processor in the catalog had a working example
        and the other seventeen had none, when the demos in fact configure
        most of them -- a caller who hit the second one was told to infer the
        values from script source, which is the trial-and-error this was meant
        to remove.
        """
        if not interface or not interface.get("empty_by_default"):
            return None
        wanted = set(interface["empty_by_default"])
        examples = []

        def entry_for(blocks, source_type, defined_in, origin):
            provided = {key for block in blocks for item in block for key in item}
            best = max(
                blocks,
                key=lambda block: len(wanted & {k for item in block for k in item}),
            )
            return {
                "platform_type": source_type,
                "on_initialize": best,
                "defined_in": defined_in,
                "origin": origin,
                "covers": sorted(wanted & {k for item in best for k in item}),
                "missing": sorted(wanted - {k for item in best for k in item}),
                "covers_all_required": wanted <= {k for item in best for k in item},
            }

        # The block in the type's own definition, or in a type derived from it,
        # comes first: it was written by whoever wrote the processor, and it is
        # the only complete one for TELAR_TASK_MGR -- whose configuration
        # lives on the derived SR_SAM_TELAR_TASK_MGR, not on TELAR_TASK_MGR.
        derived = self._derived_with_setup(catalog, kind, name)
        if derived:
            component, blocks = derived
            example = entry_for(blocks, component, None, "the type's own definition")
            example["derived_from"] = name
            examples.append(example)

        for platform in catalog["platform_types"].values():
            blocks = platform.get("on_initialize") or []
            if not blocks:
                continue
            provided = {key for block in blocks for item in block for key in item}
            if not (wanted & provided):
                continue
            examples.append(
                entry_for(blocks, platform["name"], platform["defined_in"], "a platform that uses it")
            )
        examples.sort(
            key=lambda e: (
                not e["covers_all_required"],
                e["origin"] != "the type's own definition",
                -len(e["covers"]),
                e["platform_type"],
            )
        )
        if not examples:
            return {
                "examples": [],
                "required": sorted(wanted),
                "note": "No demo in the AFSIM install configures this processor, so these "
                "variables have to be inferred from its script source. The script API "
                "index (afsim_command kind='script') is where the processor's own methods "
                "are listed.",
            }
        complete = [e for e in examples if e["covers_all_required"]]
        return {
            "examples": examples[:6],
            "example_count": len(examples),
            "complete_count": len(complete),
            "required": sorted(wanted),
            "note": "Assign these in an on_initialize block inside the processor, copying "
            "one of the blocks above. Redeclaring them in script_variables is rejected by "
            "mission, which is the usual reason a tactics processor is added but never "
            "fires."
            + ("" if complete else " No demo supplies every required variable, so the "
               "missing ones are yours to assign."),
        }

    def describe_component(self, name, kind):
        catalog = self.load_catalog()
        record = catalog["component_types"].get(f"{kind}:{name}")
        if not record:
            built_in = catalog.get("library_types", {}).get(name)
            if built_in:
                # A library class has no source in the demos, but the shipped
                # documentation still says what it needs in order to work.
                try:
                    documented = self.host.command_reference.documented_requirements([name])
                except Exception:
                    documented = {}
                return self.host.wrap(
                    {
                        "kind": built_in["kind"],
                        "name": name,
                        "built_in": True,
                        "defined_in": None,
                        "seen_in": built_in.get("seen_in", []),
                        "documented_requirements": self._requirement_statements(documented),
                        "hint": "This is an AFSIM library class: it ships compiled into the "
                        "binaries rather than as demo source, so it has no file and no "
                        "documented parameter list here. Check the AFSIM HTML documentation "
                        "under <AFSIM_ROOT>/documentation for its inputs.",
                    }
                )
            return self.host.wrap(
                {
                    "error": f"{kind} type {name!r} is not a known AFSIM type",
                    "did_you_mean": self.suggest_types(name, kind=kind),
                    "hint": "mission.exe rejects undefined component type names. Names the "
                    "demos never declare may still exist as AFSIM library classes; try "
                    "kind='sensor' (or weapon/mover/processor/comm) with a keyword.",
                }
            )
        interface = record.get("script_interface")
        example = self.find_working_configuration(catalog, kind, record["name"], interface)
        # Scanning the HTML documentation costs tens of seconds, so it happens
        # for one type on demand rather than during a catalog rebuild.
        try:
            documented = self.host.command_reference.documented_requirements([record["name"]])
        except Exception:
            documented = {}
        requirements = self._requirement_statements(documented)
        return self.host.wrap(
            {
                "kind": kind,
                "name": record["name"],
                "base": record["base"],
                "built_in": False,
                "parameters": record["parameters"],
                "performance": record.get("performance"),
                "script_interface": interface,
                "documented_requirements": requirements,
                "working_configuration": example,
                "used_by": record.get("used_by", []),
                "defined_in": record["defined_in"],
                "catalog": {
                    "built_at": catalog["built_at"],
                    "demos_root": catalog["demos_root"],
                    "component_type_count": catalog["component_type_count"],
                    "library_type_count": catalog.get("library_type_count", 0),
                },
            }
        )


def _instantiation_score(facts):
    """Prefer examples that carry the wiring a scenario author must repeat.

    The point of an example is to be copied: one showing the script variables
    and C2 links outranks a bare placement.
    """
    return (
        len(facts.get("script_variables") or []),
        1 if (facts.get("command_chains") or facts.get("commander")) else 0,
        len(facts.get("processor_edits") or []),
    )


def _instance_facts(body):
    """Structured wiring facts from a platform instance block.

    Only what a scenario author must repeat to make the type behave as the
    demo behaves: the C2 links, the script_variables block the tactics
    processors read, and the `edit processor` blocks that retune one. Lines
    are kept as written rather than interpreted.
    """
    facts = {"script_variables": [], "processor_edits": [], "command_chains": []}
    scope = []
    for raw in body.splitlines():
        # Demo entries align assignments into columns; the spacing is
        # decoration, the tokens are what a scenario author copies.
        stripped = " ".join(raw.split())
        if not stripped or stripped.startswith(("//", "#")):
            continue
        if scope:
            kind, payload = scope[-1]
            closer = "end_script_variables" if kind == "script_variables" else "end_processor"
            if stripped == closer:
                scope.pop()
                continue
            if kind == "script_variables":
                payload.append(stripped)
            else:
                payload["settings"].append(stripped)
            continue
        tokens = stripped.split()
        key = tokens[0]
        if key == "script_variables":
            scope.append(("script_variables", facts["script_variables"]))
        elif key == "edit" and len(tokens) >= 3 and tokens[1] == "processor":
            payload = {"processor": tokens[2], "settings": []}
            facts["processor_edits"].append(payload)
            scope.append(("processor_edit", payload))
        elif key == "side" and len(tokens) >= 2 and "side" not in facts:
            facts["side"] = tokens[1]
        elif key == "commander" and len(tokens) >= 2:
            facts["commander"] = tokens[1]
        elif key == "command_chain" and len(tokens) >= 3:
            pair = f"{tokens[1]} {tokens[2]}"
            if pair not in facts["command_chains"]:
                facts["command_chains"].append(pair)
    return facts


def _global_prologue(text):
    """The column-0 script_variables block(s) of an entry file.

    This is the entry's script-globals prologue: the definitions the type
    files' scripts reference but never declare. Returns (lines, names,
    start_offset); the lines are a recipe to copy, the names answer "what
    must exist", and the offset locates the block inside the file so callers
    can tell which includes surround it -- the observers that consume these
    globals are included after the block, and an entry that includes them
    first fails to initialize the script context.
    """
    prologue = []
    globals_declared = []
    start_offset = -1
    for match in re.finditer(r"^script_variables[ \t]*$", text, re.M):
        if start_offset == -1:
            start_offset = match.start()
        end = text.find("end_script_variables", match.end())
        if end == -1:
            continue
        for raw in text[match.end():end].splitlines():
            stripped = " ".join(raw.split())
            if not stripped or stripped.startswith(("//", "#")):
                continue
            if stripped not in prologue:
                prologue.append(stripped)
        for decl in VAR_DECL_RE.finditer(text[match.end():end]):
            name = decl.group(1)
            if name not in globals_declared:
                globals_declared.append(name)
    return prologue, globals_declared, start_offset


def _defines(text):
    """Top-level `$define NAME VALUE` lines, verbatim.

    The prologue interpolates these, so a recipe that copies one without the
    other fails to parse.
    """
    return [
        f"{m.group(1)} {m.group(2)}".strip()
        for m in re.finditer(r"^\$define[ \t]+(\S+)(?:[ \t]+(.+))?[ \t]*$", text, re.M)
    ]


def _entry_facts(text):
    """Facts about the entry file an instance lives in.

    The BRAWLER_TEST family's scripts reference globals (log, iout, ...) that
    no type file defines: each demo entry declares them in a top-level
    script_variables block, and an entry without that prologue fails to
    initialize the script context. The prologue is returned with its lines,
    not just the names -- it is a recipe to copy, and `$define` lines ride
    along because the prologue interpolates them.
    """
    includes = []
    for match in TOP_LEVEL_INCLUDE_RE.finditer(text):
        target = match.group(2)
        if target not in includes:
            includes.append(target)
    named_routes = sorted({m.group(1) for m in TOP_LEVEL_ROUTE_RE.finditer(text)})
    prologue, globals_declared, _ = _global_prologue(text)
    return {
        "includes": includes,
        "named_routes": named_routes,
        "defines": _defines(text),
        "global_script_variables": globals_declared,
        "global_script_prologue": prologue,
    }


def _platform_score(record):
    """Prefer the definition that is actually configured for use.

    Several demos define a type with the same name; the one carrying an
    on_initialize block is the one that fires, and the one with the most
    component mentions can be a different, inert copy.
    """
    return (1 if record.get("on_initialize") else 0, _richness(record))


def _record_score(record):
    return (
        len(record.get("parameters", [])),
        1 if record.get("script_interface") else 0,
    )


def _richness(record):
    return sum(len(v) for v in record.get("components", {}).values())


def _has_unsubstituted_var(name):
    """True when a still-missing include name carries a path-variable marker.

    The resolver reports the name it could not resolve. If that name still
    contains $(...) or ${...}, the variable was never bound in this file's
    scope, which in AFSIM means the name is assembled from the platform type
    being instantiated -- a resolution failure that says nothing about whether
    the file loads.
    """
    return bool(PATH_VAR_RE.search(name or ""))


def _chain_records(record, platform_types):
    """A platform type and its bases, nearest first."""
    chain = []
    seen = set()
    current = record
    while current is not None and current["name"] not in seen:
        seen.add(current["name"])
        chain.append(current)
        base = current.get("base")
        current = platform_types.get(base) if base else None
    return chain


def _derives_from(record, ancestor, components, kind, _seen=None):
    """Whether a component type's base chain reaches `ancestor`."""
    seen = _seen or set()
    base = record.get("base")
    if not base or base in seen:
        return False
    seen.add(base)
    if base == ancestor:
        return True
    parent = components.get(f"{kind}:{base}")
    return bool(parent) and _derives_from(parent, ancestor, components, kind, seen)


def _chain_has_flag(table, kind, name, flag, _seen=None):
    """Whether a component or anything it derives from carries a flag.

    A tactics processor is usually declared as `processor X WSF_TASK_PROCESSOR`
    with the state machine in a separate file, so the flag found on the one
    declared type has to be visible to everything that inherits from it.
    """
    seen = _seen or set()
    if name in seen:
        return False
    seen.add(name)
    record = table.get(f"{kind}:{name}") or {}
    if record.get(flag):
        return True
    base = record.get("base")
    return bool(base) and _chain_has_flag(table, kind, base, flag, seen)


def _effective_components(record, platform_types):
    """Components a platform actually has, own declarations plus inherited.

    A platform_type that only overrides a mover still carries everything its
    base declared. Reading a type's own block made every derived type look
    bare -- SAM-MR_RB6 reported no sensors and no weapons while inheriting
    SAM-MR's seeker and four processors -- and because the listing sorts
    armed types first, that pushed derived types to the bottom of every
    result set. Own components win over inherited ones of the same kind, and
    a base that is not itself in the index simply contributes nothing.
    """
    merged = {}
    chain = []
    seen = set()
    current = record
    while current is not None and current["name"] not in seen:
        seen.add(current["name"])
        chain.append(current)
        base_name = current.get("base")
        current = platform_types.get(base_name) if base_name else None
    for level in reversed(chain):
        for kind, values in level.get("components", {}).items():
            merged[kind] = sorted(set(merged.get(kind, [])) | set(values))
    return merged


def _infer_domain(record, platform_types):
    """Read a platform's domain off its mover, following the base chain.

    The mover is the only thing in the AFSIM source that states where a
    platform moves, so it is the only thing consulted.  A substring guess over
    the type name and the file it came from was tried first and produced
    confident nonsense -- "space" returned GPS and COMMANDER because the
    defining file path contained the word, and HVAA and SSM_MISSILE came back
    as "air" because their names contain "hvaa" and "missile" while both are
    surface- or ground-launched.  A platform whose mover is nowhere in the
    chain is reported as undetermined instead.
    """
    seen = set()
    current = record
    while current is not None and current["name"] not in seen:
        seen.add(current["name"])
        for mover in current.get("components", {}).get("mover", []):
            upper = mover.upper()
            for domain, markers in MOVER_DOMAINS:
                if upper in markers:
                    return domain
        base_name = current.get("base")
        current = platform_types.get(base_name) if base_name else None
    return "undetermined"
