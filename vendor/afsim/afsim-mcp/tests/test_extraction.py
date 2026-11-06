"""Argument types and include resolution.

Both modules exist because the command index stops at a placeholder and the
entry file stops at its first line, and in both cases the missing half was
being rediscovered by running mission until it stopped complaining:

  altitude 5000m msl   rejected, because <length-value> is <real> <length-units>
  end_time 00:00:30    rejected, because <time-value> is a real plus a unit
  "the run used AFSIM's 60 s default"  wrong, because end_time was in an
                        included file that nothing read
"""

import json

import pytest

from core.knowledge.argument_types import ArgumentTypes
from core.knowledge.mission_grammar import IncludeResolver, declared_duration

PAGE = """<dl class="argtype">
<dt id="length-value">length-value <a href="#real"><em> &lt;real&gt;</em></a>\
<a href="#length-units"><em> &lt;length-units&gt;</em></a></dt>
<dt id="length-units">length-units</dt>
<dd><table><tr><th>Unit of Measure</th><th>Allowable Input Values</th></tr>
<tr><td>Length</td><td>meters meters meter m feet feet ft</td></tr></dd>
<dt id="time-value">time-value <a href="#real"><em> &lt;real&gt;</em></a>\
<a href="#time-units"><em> &lt;time-units&gt;</em></a></dt>
<dt id="time-units">time-units</dt>
<dd><table><tr><th>Unit of Measure</th><th>Allowable Input Values</th></tr>
<tr><td>Time</td><td>seconds second secs sec s hours hour hrs hr h</td></tr></dd>
<dt id="boolean-value">boolean-value</dt>
<dt id="latitude-value">latitude-value</dt>
<dt id="longitude-value">longitude-value</dt>
<dd><p>A value with two states.</p></dd>
<dt id="speed-units">speed-units</dt>
<dd><table><tr><th>Unit of Measure</th><th>Allowable Input Values</th></tr>
<tr><td>Speed</td><td>kmh mph knots kts</td></tr></dd>
</dl>
"""


class Host:
    def __init__(self, tmp_path, demos=None):
        self.state_dir = tmp_path / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._root = tmp_path / "afsim"
        docs = self._root / "documentation" / "html" / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "argumenttypes.html").write_text(PAGE, encoding="utf-8")
        self._demos = demos

    def resolve_afsim_root(self):
        return str(self._root)

    def resolve_demos_root(self):
        return str(self._demos) if self._demos else None


@pytest.fixture
def types(tmp_path):
    return ArgumentTypes(Host(tmp_path))


# ------------------------------------------------------------- argument types


def test_unit_bearing_production_is_two_tokens(types):
    detail = types.explain("length-value", types.load())
    assert detail["written_as"] == "<real> <length-units>"


def test_unit_spellings_come_from_the_documentation(types):
    detail = types.explain("length-value", types.load())
    spellings = detail["parts"][1]["accepted_spellings"]
    assert spellings == ["meters", "meter", "m", "feet", "ft"]


def test_primitive_placeholders_resolve_to_a_single_token(types):
    # boolean-value, real-value and integer-value outnumber every
    # unit-bearing placeholder in the command index, and each is one opaque
    # token.
    detail = types.explain("boolean-value", types.load())
    assert detail is not None
    assert detail["written_as"] == "<value>"
    assert detail["parts"] == []


def test_a_sibling_heading_is_not_treated_as_an_alias(types):
    # latitude-value and longitude-value share one <dd>; neither defines the
    # other. Routing one to the other produced "latitude-value is a
    # longitude".
    detail = types.explain("latitude-value", types.load())
    assert detail is not None
    assert detail["written_as"] == "<value>"
    assert detail.get("alias_of") is None


def test_an_undefined_placeholder_is_left_alone(types):
    assert types.explain("dbratio-value", types.load()) is None


def test_expand_leaves_unknown_syntax_untouched(types):
    data = types.load()
    expanded, found = types.expand("route <name-or-type> <real>", data)
    assert expanded == "route <name-or-type> <real>"
    assert found == []


def test_expand_substitutes_a_known_placeholder(types):
    data = types.load()
    expanded, found = types.expand("altitude <length-value>", data)
    assert expanded == "altitude <real> <length-units>"
    assert found[0]["type"] == "length-value"


# ------------------------------------------------------------ include walking


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_end_time_is_found_in_an_included_file(tmp_path):
    # The run reported "used AFSIM's 60 s default" while the payload beside it
    # said achieved_sec: 7200, because only the entry file was read.
    _write(tmp_path / "scenario.txt", "include config/control.txt\n")
    _write(tmp_path / "config" / "control.txt", "end_time 2 hr\nrandom_seed 1\n")
    assert declared_duration(tmp_path / "scenario.txt") == (7200.0, True)


def test_end_time_in_the_entry_file_still_wins(tmp_path):
    _write(tmp_path / "scenario.txt", "end_time 30 min\ninclude config/c.txt\n")
    _write(tmp_path / "config" / "c.txt", "end_time 2 hr\n")
    assert declared_duration(tmp_path / "scenario.txt") == (1800.0, True)


def test_no_end_time_anywhere_reports_the_afsim_default(tmp_path):
    _write(tmp_path / "scenario.txt", "include config/c.txt\n")
    _write(tmp_path / "config" / "c.txt", "random_seed 1\n")
    assert declared_duration(tmp_path / "scenario.txt") == (60.0, False)


def test_a_missing_entry_file_reports_nothing(tmp_path):
    assert declared_duration(tmp_path / "nope.txt") == (None, False)


def test_include_resolves_relative_to_the_including_file(tmp_path):
    _write(tmp_path / "a.txt", "include sub/b.txt\n")
    _write(tmp_path / "sub" / "b.txt", "include c.txt\n")
    _write(tmp_path / "sub" / "c.txt", "end_time 90 sec\n")
    files, _paths, missing = IncludeResolver().resolve(tmp_path / "a.txt")
    assert missing == []
    assert len(files) == 3


def test_file_path_entries_are_searched_in_order(tmp_path):
    # AFSIM's documented order: absolute, then the directory of the file being
    # processed, then each file_path entry in order.
    lib = tmp_path / "lib"
    _write(lib / "types.txt", "end_time 45 sec\n")
    _write(tmp_path / "a.txt", "file_path " + str(lib) + "\ninclude types.txt\n")
    files, paths, missing = IncludeResolver().resolve(tmp_path / "a.txt")
    assert [f.name for f in files] == ["a.txt", "types.txt"]
    assert paths == [str(lib)]
    assert missing == []


def test_path_variables_are_substituted(tmp_path):
    data = tmp_path / "data"
    _write(data / "types.txt", "end_time 20 sec\n")
    _write(tmp_path / "a.txt", "define_path_variable DATA %s\ninclude $(DATA)/types.txt\n" % data)
    files, _paths, missing = IncludeResolver().resolve(tmp_path / "a.txt")
    assert missing == []
    assert [f.name for f in files] == ["a.txt", "types.txt"]


def test_an_unresolvable_include_is_reported_not_swallowed(tmp_path):
    _write(tmp_path / "a.txt", "include nowhere/missing.txt\n")
    _files, _paths, missing = IncludeResolver().resolve(tmp_path / "a.txt")
    assert len(missing) == 1
    assert missing[0]["include"] == "nowhere/missing.txt"
    assert "file_path" in missing[0]


def test_include_cycles_terminate(tmp_path):
    _write(tmp_path / "a.txt", "include b.txt\n")
    _write(tmp_path / "b.txt", "include a.txt\n")
    files, _paths, missing = IncludeResolver().resolve(tmp_path / "a.txt")
    assert [f.name for f in files] == ["a.txt", "b.txt"]
    assert missing == []


# ------------------------------------------------------- task-dependent firing
#
# can_engage is "has a weapon and a processor". That is not a promise that
# anything fires. A tactics processor's state machine enters ENGAGE only once
# a task has been assigned, and the task arrives over C2 -- so the platform
# detects, holds ENGAGEABLE and never fires, with nothing in the output saying
# why. An empty `platform_type MY_SAM SR_SAM_TELAR` does exactly this: 24
# rounds become 0 and mission still exits 0.

TASK_MGR_SCRIPT = """
   state ENGAGEABLE
      next_state ENGAGE
         Engage();
         return (TrackingNow() && (TasksAssignedFor(TRACK.TrackId(), mTrackTaskStr) > 0));
      end_next_state
   end_state
   script bool IsAssignable()
      return ((PLATFORM == PLATFORM.Commander()) || (TasksReceivedFor(TRACK.TrackId()) > 0));
   end_script
"""

DETECT_ONLY_SCRIPT = """
   script bool IsEngageable()
      return (TRACK.TrackQuality() > 0.9);
   end_script
   next_state ENGAGEABLE
"""

PLAIN_PROCESSOR = "\n   on\n   update_interval 1 sec\n"


def test_a_processor_gated_on_task_flow_is_flagged():
    from core.knowledge.type_index import AfsimTypeIndex

    flagged = AfsimTypeIndex._task_dependent(TASK_MGR_SCRIPT)
    assert flagged is not None
    assert "TasksAssignedFor" in flagged["gating_calls"]
    assert "TasksReceivedFor" in flagged["gating_calls"]


def test_a_processor_that_only_asks_is_not_flagged():
    # IsEngageable() decides whether a track is worth engaging. It contains
    # the letters "Engage" and is not a call to fire.
    from core.knowledge.type_index import AfsimTypeIndex

    assert AfsimTypeIndex._task_dependent(DETECT_ONLY_SCRIPT) is None


def test_a_processor_with_no_state_machine_is_not_flagged():
    from core.knowledge.type_index import AfsimTypeIndex

    assert AfsimTypeIndex._task_dependent(PLAIN_PROCESSOR) is None


def test_task_dependence_is_inherited_through_a_component_base_chain():
    # `processor SR_SAM_TELAR_TASK_MGR TELAR_TASK_MGR` carries no script of its
    # own; the flag lives on TELAR_TASK_MGR and has to be visible anyway.
    from core.knowledge.type_index import _chain_has_flag

    components = {
        "processor:SR_SAM_TELAR_TASK_MGR": {"base": "TELAR_TASK_MGR"},
        "processor:TELAR_TASK_MGR": {"base": "WSF_TASK_PROCESSOR", "task_dependent": {"gating_calls": []}},
    }
    assert _chain_has_flag(components, "processor", "SR_SAM_TELAR_TASK_MGR", "task_dependent")
    assert not _chain_has_flag(components, "processor", "WSF_UNRELATED", "task_dependent")


def test_a_component_base_cycle_terminates():
    from core.knowledge.type_index import _chain_has_flag

    components = {"processor:A": {"base": "B"}, "processor:B": {"base": "A"}}
    assert not _chain_has_flag(components, "processor", "A", "task_dependent")


# ------------------------------------------------------- defining-file facts
#
# Two things decide whether a demo type is usable, and neither is visible from
# the type name: whether its file's include closure closes, and whether
# including that file also places platforms. Both used to be discovered by
# reading the demo source -- which an agent using this server is told not to
# do -- or by running mission until it complained.


DEMO_SCENARIO = """include sub/other.txt
platform airliner WSF_PLATFORM
   side white
end_platform
platform sam SR_SAM
   side red
end_platform
"""


def test_a_file_that_places_platforms_is_reported_as_such(tmp_path):
    from core.knowledge.type_index import TOP_LEVEL_PLATFORM_RE

    found = sorted(m.group(1) for m in TOP_LEVEL_PLATFORM_RE.finditer(DEMO_SCENARIO))
    assert found == ["airliner", "sam"]


def test_an_absent_include_is_a_definitive_miss(tmp_path):
    # A name that exists nowhere in the installation proves the file cannot
    # load. base_types pulls in a radar signature that was never shipped, and
    # every type behind it is unusable.
    from core.knowledge.type_index import _has_unsubstituted_var

    assert not _has_unsubstituted_var("../signatures/missing_signature.txt")


def test_a_path_variable_dependent_include_is_not_a_definitive_miss():
    # The name is assembled from the platform type being instantiated, so the
    # resolution failure says nothing about whether the file loads.
    from core.knowledge.type_index import _has_unsubstituted_var

    assert _has_unsubstituted_var("platforms/commander_track_manager$(TRACKER_TYPE).txt")
    assert _has_unsubstituted_var("platforms/x${TYPE}.txt")


# ------------------------------------------------------------- script API
#
# A tactics processor is a script written against objects -- PLATFORM, SENSOR,
# WEAPON, TRACK, PROCESSOR -- and none of that was reachable: the command index
# holds input-file commands and the event index holds event names, so "what
# methods does WsfTrack have" had no answer. Wiring a processor together meant
# guessing identifiers and running mission until it stopped saying "Unknown
# identifier".

SCRIPT_PAGE = """<h1>WsfTrack &para;</h1>
<section><h2>General Methods</h2>
<dl class="method">
<dt id="WsfTrack.TrackQuality">double TrackQuality<span class="sig-paren">(</span><span class="sig-paren">)</span></dt>
<dd><p>Return the track quality in the range [0..1].</p></dd>
<dt id="WsfTrack.SetSide">void SetSide<span class="sig-paren">(</span>string aSide<span class="sig-paren">)</span></dt>
<dd></dd>
</dl></section>
"""


class ScriptHost:
    def __init__(self, tmp_path):
        self.state_dir = tmp_path / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        docs = tmp_path / "afsim" / "documentation" / "html" / "docs"
        (docs / "script").mkdir(parents=True, exist_ok=True)
        (docs / "script" / "wsftrack.html").write_text(SCRIPT_PAGE, encoding="utf-8")

    def resolve_afsim_root(self):
        return str(self.state_dir.parent / "afsim")


@pytest.fixture
def scripts(tmp_path):
    from core.knowledge.script_api import ScriptApi

    return ScriptApi(ScriptHost(tmp_path))


def test_the_permalink_marker_does_not_hijack_the_class_name(scripts):
    # The heading carries a trailing pilcrow. Stripping it matters: without it
    # the title fails its identifier test and falls back to the lower-cased
    # file name, after which every method compares unequal to its own class and
    # is filed as inherited rather than declared.
    data = scripts.load()
    assert "WsfTrack" in data["classes"]
    assert len(data["classes"]["WsfTrack"]["methods"]) == 2


def test_a_method_reports_its_return_type_and_arguments(scripts):
    entry, _data = scripts.describe("WsfTrack")
    by_name = {m["name"]: m for m in entry["methods"]}
    assert by_name["TrackQuality"]["returns"] == "double"
    assert by_name["SetSide"]["args"] == "string aSide"


def test_a_method_keeps_its_documentation(scripts):
    entry, _data = scripts.describe("WsfTrack")
    by_name = {m["name"]: m for m in entry["methods"]}
    assert "[0..1]" in by_name["TrackQuality"]["description"]


def test_a_method_name_resolves_to_its_classes(scripts):
    owners, _data = scripts.find_method("trackquality")
    assert owners == ["WsfTrack"]


def test_an_unknown_class_is_reported_as_not_found(scripts):
    assert scripts.describe("WsfNoSuchClass")[0] is None


def test_the_script_keyword_is_derived_from_the_class_name(scripts):
    entry, _data = scripts.describe("WsfTrack")
    assert entry["script_keyword"] == "Track"


# ------------------------------------------------- processor configuration
#
# A tactics processor ships with SENSOR_NAME and WEAPON_NAME empty, and
# mission rejects redeclaring them in script_variables -- so they have to be
# assigned in an on_initialize block inside the processor. The demos show how.
# Returning only the first match gave one processor an example and told the
# other seventeen to infer their values, which is the trial-and-error this was
# built to remove.

TACTICS_WITH_SETUP = """
   script_variables
      string SENSOR_NAME = "";
      string WEAPON_NAME = "";
   end_script_variables
   on_initialize
      SENSOR_NAME = "ttr";
      WEAPON_NAME = "sam";
   end_on_initialize
"""


def _interface(*names):
    return {"empty_by_default": list(names)}


def test_the_type_own_on_initialize_block_is_kept_whole():
    from core.knowledge.type_index import AfsimTypeIndex

    blocks = AfsimTypeIndex._on_initialize_blocks(TACTICS_WITH_SETUP)
    assert len(blocks) == 1
    # One block, not a flat list of assignments: the two variables are copied
    # together or not at all.
    assert blocks[0] == [
        {"SENSOR_NAME": '"ttr"'},
        {"WEAPON_NAME": '"sam"'},
    ]


def test_several_blocks_are_kept_separate():
    from core.knowledge.type_index import AfsimTypeIndex

    body = (
        "   on_initialize\n      A = 1;\n   end_on_initialize\n"
        "   on_initialize\n      B = 2;\n   end_on_initialize\n"
    )
    assert AfsimTypeIndex._on_initialize_blocks(body) == [[{"A": "1"}], [{"B": "2"}]]


def test_a_block_with_no_assignments_is_dropped():
    from core.knowledge.type_index import AfsimTypeIndex

    assert AfsimTypeIndex._on_initialize_blocks(
        "   on_initialize\n   end_on_initialize\n"
    ) == []


def test_a_configuration_on_a_derived_type_is_found():
    # TELAR_TASK_MGR declares no block; the complete one sits on the demo's
    # SR_SAM_TELAR_TASK_MGR, one derivation away.
    from core.knowledge.type_index import _derives_from

    components = {
        "processor:SR_SAM_TELAR_TASK_MGR": {"name": "SR_SAM_TELAR_TASK_MGR", "base": "TELAR_TASK_MGR"},
        "processor:TELAR_TASK_MGR": {"name": "TELAR_TASK_MGR", "base": "WSF_TASK_PROCESSOR"},
    }
    derived = components["processor:SR_SAM_TELAR_TASK_MGR"]
    assert _derives_from(derived, "TELAR_TASK_MGR", components, "processor")
    assert not _derives_from(components["processor:TELAR_TASK_MGR"], "SR_SAM_TELAR_TASK_MGR", components, "processor")


def test_derivation_lookup_terminates_on_a_cycle():
    from core.knowledge.type_index import _derives_from

    components = {
        "processor:A": {"name": "A", "base": "B"},
        "processor:B": {"name": "B", "base": "A"},
    }
    assert not _derives_from(components["processor:A"], "Z", components, "processor")


# --------------------------------------------------------- engagement envelope
#
# A zone is both a limit and a handle: its name is what a tactics processor is
# given in ENVELOPE = "...", and its extent is what gates whether a shot is
# taken. SR_SAM_TELAR's whole envelope is two numbers, and neither was visible
# -- maximum_radius was not in the keyword set at all, and _performance was
# only ever called for component types, never for a platform_type. Finding out
# that the launcher could not reach a 9 km target at 60 km meant bisecting
# twenty-odd geometries.

ZONE_BODY = """
   zone full_kinematic
      circular
         maximum_altitude 20000 ft
         maximum_radius   6 nm
   end_zone
"""


def test_a_zone_reports_its_name_shape_and_extent():
    from core.knowledge.type_index import AfsimTypeIndex

    zones = AfsimTypeIndex._zones(ZONE_BODY)
    assert zones == [
        {
            "name": "full_kinematic",
            "shape": "circular",
            "extent": {"maximum_altitude": "20000 ft", "maximum_radius": "6 nm"},
        }
    ]


def test_maximum_radius_is_a_performance_keyword():
    # Without it in the set, the radius that decides the envelope was dropped
    # while the altitude beside it was kept.
    from core.knowledge.type_index import PERFORMANCE_KEYWORDS

    assert "maximum_radius" in PERFORMANCE_KEYWORDS
    assert "minimum_radius" in PERFORMANCE_KEYWORDS


def test_a_platform_type_reports_its_zones():
    from core.knowledge.type_index import AfsimTypeIndex

    assert AfsimTypeIndex._performance(ZONE_BODY) == {
        "maximum_altitude": ["20000 ft"],
        "maximum_radius": ["6 nm"],
    }


def test_zone_inheritance_follows_the_base_chain():
    from core.knowledge.type_index import _chain_records

    base = {
        "name": "BASE",
        "base": "WSF_PLATFORM",
        "zones": [{"name": "full_kinematic", "shape": "circular", "extent": {}}],
    }
    derived = {"name": "DERIVED", "base": "BASE", "zones": []}
    chain = _chain_records(derived, {"BASE": base, "DERIVED": derived})
    assert [r["name"] for r in chain] == ["DERIVED", "BASE"]


def test_a_zone_chain_terminates_on_a_cycle():
    from core.knowledge.type_index import _chain_records

    a = {"name": "A", "base": "B"}
    b = {"name": "B", "base": "A"}
    assert [r["name"] for r in _chain_records(a, {"A": a, "B": b})] == ["A", "B"]
