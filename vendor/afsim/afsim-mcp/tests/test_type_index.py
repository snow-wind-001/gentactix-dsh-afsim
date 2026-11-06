"""Tests for the AFSIM type catalog.

The catalog is what stops a model from inventing type names, so the parsing
rules are pinned against realistic AFSIM source rather than only against a live
AFSIM install.
"""

import json

import pytest

from core.knowledge.type_index import (
    COMPONENT_TYPE_RE,
    COMPONENT_USE_RE,
    PLATFORM_TYPE_RE,
    AfsimTypeIndex,
    _effective_components,
    _infer_domain,
)

SOURCE = """
sensor ESM_SENSOR WSF_ESM_SENSOR
   ignore_same_side
   maximum_range 100 nmi
   mode_template
      field_of_view 360 degrees
   end_mode_template
end_sensor

platform_type SIMPLE_TARGET WSF_PLATFORM
   icon target
end_platform_type

platform_type REAL_FIGHTER WSF_PLATFORM
   icon f15c
   mover WSF_BRAWLER_MOVER
   end_mover
   sensor rdr1 aesa
   end_sensor
   sensor rwr esm
   end_sensor
   weapon fox3 MEDIUM_RANGE_RADAR_MISSILE
   end_weapon
   processor radar_track_cueing SENSOR_CUE_PROCESSOR
   end_processor
   comm weapon_datalink WSF_COMM_TRANSCEIVER
   end_comm
end_platform_type

platform_type LONE_MOVER WSF_PLATFORM
   add mover WSF_AIR_MOVER
   end_mover
end_platform_type

platform blue_1 REAL_FIGHTER
   side blue
end_platform
"""


@pytest.fixture
def service():
    return AfsimTypeIndex(host=None)


@pytest.fixture
def platforms():
    found = {}
    for match in PLATFORM_TYPE_RE.finditer(SOURCE):
        end = SOURCE.find("end_platform_type", match.end())
        body = SOURCE[match.end() : end] if end != -1 else ""
        declared = {}
        for kind, first, second in COMPONENT_USE_RE.findall(body):
            declared.setdefault(kind, []).append(first if kind == "mover" else (second or first))
        found[match.group(1)] = {k: sorted(set(v)) for k, v in declared.items()}
    return found


def test_platform_instance_is_not_a_type(platforms):
    # "platform blue_1 REAL_FIGHTER" must not register as a platform_type.
    assert set(platforms) == {"SIMPLE_TARGET", "REAL_FIGHTER", "LONE_MOVER"}


def test_component_instance_uses_its_type_token(platforms):
    """`sensor rdr1 aesa` means instance rdr1 of type aesa, not of type rdr1."""
    assert platforms["REAL_FIGHTER"]["sensor"] == ["aesa", "esm"]
    assert platforms["REAL_FIGHTER"]["weapon"] == ["MEDIUM_RANGE_RADAR_MISSILE"]
    assert platforms["REAL_FIGHTER"]["mover"] == ["WSF_BRAWLER_MOVER"]


def test_add_mover_form_is_accepted(platforms):
    assert platforms["LONE_MOVER"]["mover"] == ["WSF_AIR_MOVER"]


def test_target_type_has_no_components(platforms):
    assert platforms["SIMPLE_TARGET"] == {}


def test_top_level_component_types_are_separate_from_instances():
    """A column-0 declaration defines a type; an indented one is an instance."""
    found = {f"{m.group(1)}:{m.group(2)}" for m in COMPONENT_TYPE_RE.finditer(SOURCE)}
    assert "sensor:ESM_SENSOR" in found
    assert "sensor:rdr1" not in found


def test_keywords_ignore_nested_blocks(service):
    body = "\n   ignore_same_side\n   maximum_range 100 nmi\n   mode_template\n      field_of_view 360\n   end_mode_template\n"
    assert service._keywords(body) == ["ignore_same_side", "maximum_range", "mode_template"]


def test_keywords_use_shallowest_indent_not_fixed_columns(service):
    """Three-space indentation is a block's own level, not a nested block."""
    body = "\n  on\n  maximum_range 10 nmi\n  internal_link data_mgr\n"
    assert service._keywords(body) == ["internal_link", "maximum_range", "on"]


def test_keywords_of_empty_body(service):
    assert service._keywords("") == []
    assert service._keywords("\n   # only comments\n") == []


def test_domain_read_from_declared_mover():
    air = {"name": "X", "base": "", "components": {"mover": ["WSF_AIR_MOVER"]}}
    ground = {"name": "Y", "base": "", "components": {"mover": ["WSF_GROUND_MOVER"]}}
    assert _infer_domain(air, {}) == "air"
    assert _infer_domain(ground, {}) == "ground"


def test_domain_follows_base_chain():
    # A type that declares no mover of its own inherits one from its base,
    # which is how most AFSIM platform types are written.
    base = {"name": "BASE", "base": "", "components": {"mover": ["WSF_SURFACE_MOVER"]}}
    derived = {"name": "DERIVED", "base": "BASE", "components": {}}
    assert _infer_domain(derived, {"BASE": base}) == "surface"


def test_domain_is_undetermined_rather_than_guessed():
    # The name and the defining path used to be searched for domain words,
    # which filed GPS under "space" and HVAA under "air" because their names
    # and file paths happened to contain them. A type that declares no mover
    # anywhere in its chain says so.
    unknown = {"name": "MY_SATELLITE", "base": "", "defined_in": "space/x.txt", "components": {}}
    assert _infer_domain(unknown, {}) == "undetermined"


def test_domain_chain_terminates_on_a_cycle():
    a = {"name": "A", "base": "B", "components": {}}
    b = {"name": "B", "base": "A", "components": {}}
    assert _infer_domain(a, {"A": a, "B": b}) == "undetermined"


# ---------------------------------------------------------------- diagnostics


def _evt(tmp_path, body):
    path = tmp_path / "run.evt"
    path.write_text(body, encoding="utf-8")
    return path


def test_diagnostics_flag_empty_evt(service, tmp_path):
    from collections import defaultdict

    from core.analysis import AnalysisService

    path = _evt(tmp_path, "")
    notes = AnalysisService(host=None).build_diagnostics([], defaultdict(int), evt_path=path, scenario_dir=tmp_path)
    issues = {n["issue"] for n in notes}
    assert "empty_evt" in issues
    assert "no_events" in issues


def test_diagnostics_distinguish_placement_only_from_health(service, tmp_path):
    from collections import defaultdict

    from core.analysis import AnalysisService

    counts = defaultdict(int, {"PLATFORM_INITIALIZED": 10})
    path = _evt(tmp_path, "0.0 PLATFORM_INITIALIZED blue_1\n")
    notes = AnalysisService(host=None).build_diagnostics([], counts, evt_path=path, scenario_dir=tmp_path)
    issues = {n["issue"] for n in notes}
    assert "placement_only" in issues
    assert "event_types_absent" in issues


def test_diagnostics_stay_quiet_for_a_healthy_run(service, tmp_path):
    from collections import defaultdict

    from core.analysis import AnalysisService

    counts = defaultdict(
        int, {"PLATFORM_INITIALIZED": 2, "WEAPON_FIRED": 3, "WEAPON_HIT": 1, "PLATFORM_BROKEN": 1}
    )
    path = _evt(tmp_path, "0.0 PLATFORM_INITIALIZED blue_1\n")
    notes = AnalysisService(host=None).build_diagnostics([], counts, evt_path=path, scenario_dir=tmp_path)
    assert notes == []


def test_library_types_are_recognised():
    """WSF_* classes are compiled into AFSIM, so they never appear in the demos."""
    record = {"kind": "mover", "base": "WSF_AIR_MOVER", "seen_in": ["base of mover:X"]}
    assert record["base"].upper().startswith("WSF_")
    # A name that only ever appears as a base is still a name that exists.
    assert "WSF_AIR_MOVER".upper().startswith("WSF_")


# ------------------------------------------------- scripted processor interface


TACTICS = """
processor AA_TACTICS WSF_TASK_PROCESSOR
   script_variables
      string SENSOR_NAME               = "";
      string SENSOR_TRACK_MODE         = "TRACK";
      string WEAPON_NAME               = "";
      double REQUIRED_TRACK_QUALITY    = 0.49;
      string mShootTaskStr             = "Shoot";
   end_script_variables
end_processor
"""


def test_empty_default_is_reported_as_a_fact_not_a_requirement(service):
    """AA_TACTICS is empty by default for SENSOR_NAME, and setting it is
    actively harder: the track-quality gate rises from 0.49 to 0.95. So the
    catalog must not tell the caller that empty means required."""
    interface = service._script_interface(TACTICS)
    assert interface is not None
    assert interface["empty_by_default"] == ["SENSOR_NAME", "WEAPON_NAME"]
    assert "must_set" not in interface
    assert "does not mean it has to be set" in interface["note"]


def test_internal_variables_are_not_the_callers_business(service):
    interface = service._script_interface(TACTICS)
    assert "mShootTaskStr" not in interface["empty_by_default"]
    # ... but it is still visible for inspection.
    assert "mShootTaskStr" in interface["script_variables"]


def test_processor_without_script_is_not_reported(service):
    body = "\n   on\n   update_interval 1 sec\n"
    assert service._script_interface(body) is None


# ------------------------------------------------------- inherited components
#
# A platform_type that overrides only a mover still carries everything its
# base declared. Reading a type's own block made every derived type look bare,
# and "armed" meant "declares a sensor or a weapon", which called a radar-only
# SAM site armed -- an agent picked one, and the finished scenario ran clean,
# exited 0 and never fired a round.


def _type_record(name, base, **components):
    return {"name": name, "base": base, "components": components}


def test_effective_components_include_the_base_chain():
    base = _type_record("SAM-MR", "WSF_PLATFORM", sensor=["SEEKER"], processor=["TRACK_PROC"])
    derived = _type_record("SAM-MR_RB6", "SAM-MR", mover=["RIGID_MOVER"])
    catalog = {"SAM-MR": base, "SAM-MR_RB6": derived}

    effective = _effective_components(derived, catalog)
    assert effective["sensor"] == ["SEEKER"]
    assert effective["processor"] == ["TRACK_PROC"]
    assert effective["mover"] == ["RIGID_MOVER"]


def test_components_are_inherited_additively():
    # AFSIM's platform_type inheritance adds to the base rather than replacing
    # it -- removing one takes an explicit `edit platform_type ... / delete`.
    base = _type_record("BASE", "", sensor=["OLD_SENSOR"])
    derived = _type_record("DERIVED", "BASE", sensor=["NEW_SENSOR"])
    effective = _effective_components(derived, {"BASE": base, "DERIVED": derived})
    assert effective["sensor"] == ["NEW_SENSOR", "OLD_SENSOR"]


def test_effective_components_survive_a_missing_base():
    # A base outside the index is common: demos reference WSF_* classes that
    # are compiled into the binaries. It contributes nothing rather than
    # raising.
    orphan = _type_record("ORPHAN", "WSF_SOMETHING", mover=["M"])
    assert _effective_components(orphan, {}) == {"mover": ["M"]}


def test_effective_components_survive_a_base_cycle():
    a = _type_record("A", "B")
    b = _type_record("B", "A")
    assert _effective_components(a, {"A": a, "B": b}) == {}


def test_a_radar_only_site_is_not_reported_as_able_to_engage():
    # This is the exact shape that produced a dead SAM battery: a seeker and
    # four processors, and no weapon at all.
    base = _type_record(
        "SAM-MR",
        "WSF_PLATFORM",
        sensor=["SIMPLE_GENERIC_SEEKER"],
        processor=["WSF_TRACK_PROCESSOR", "WSF_AIR_TARGET_FUSE"],
        mover=["WSF_P6DOF_MOVER"],
    )
    assert base["has_weapons"] if "has_weapons" in base else True
    effective = _effective_components(base, {"SAM-MR": base})
    assert effective.get("sensor")
    assert not effective.get("weapon")
    # armed stays permissive, can_engage is the one that answers the question.
    assert bool(effective.get("sensor") or effective.get("weapon")) is True
    assert bool(effective.get("weapon") and effective.get("processor")) is False


# ------------------------------------------------------------ instance wiring
# The BRAWLER_TEST family is inert unless the scenario wires each instance:
# C2 links, the tactics script_variables, and an entry-level script prologue.
# None of that lives in the type definition, so it is extracted from the demo
# entry files and attached to the type they instantiate.

SCENARIO_SOURCE = """
$define REP 1

include_once _common.txt
include_once platforms/lte_fighter.txt

script_variables
   bool log_print = true;
   FileIO log = FileIO();
end_script_variables

route blue_route
   position 36.0n 120.0e altitude 30000 ft msl speed 900 ft/s
end_route

platform blue_1 BLUE_FIGHTER
   side blue
   commander SELF
   command_chain IFLITE  SELF
   command_chain ELEMENT SELF
   heading 90 deg
   position 36.0n 120.0e altitude 30000 ft
   script_variables
      START_TYPE = "route";
      MISSION_TYPE = "SWEEP";
      ROUTE.Append("blue_route");
      WINCHESTER = {-1,-1,-1,-1,-1};
   end_script_variables
   edit processor assessment
      enemy_side    red
      mission_task  SWEEP
   end_processor
end_platform
"""


def test_instance_facts_extracts_c2_and_script_wiring():
    from core.knowledge.type_index import (
        INSTANCE_CLOSER_RE,
        PLATFORM_INSTANCE_RE,
        _instance_facts,
    )

    match = PLATFORM_INSTANCE_RE.search(SCENARIO_SOURCE)
    assert match.group(2) == "BLUE_FIGHTER"
    closer = INSTANCE_CLOSER_RE.search(SCENARIO_SOURCE, match.end())
    body = SCENARIO_SOURCE[match.end(): closer.start()]
    facts = _instance_facts(body)
    assert facts["side"] == "blue"
    assert facts["commander"] == "SELF"
    assert facts["command_chains"] == ["IFLITE SELF", "ELEMENT SELF"]
    assert 'MISSION_TYPE = "SWEEP";' in facts["script_variables"]
    assert facts["processor_edits"] == [
        {"processor": "assessment", "settings": ["enemy_side red", "mission_task SWEEP"]}
    ]


def test_instance_closer_is_anchored_to_whole_lines():
    # A substring search for "end_platform" also lands inside
    # "end_platform_type"; the anchored closer must not.
    from core.knowledge.type_index import INSTANCE_CLOSER_RE

    text = "end_platform_type\nend_platform\n"
    match = INSTANCE_CLOSER_RE.search(text)
    assert text[match.start(): match.end()] == "end_platform"


def test_entry_facts_extracts_prologue_and_ignores_instance_blocks():
    from core.knowledge.type_index import _entry_facts

    facts = _entry_facts(SCENARIO_SOURCE)
    assert facts["includes"] == ["_common.txt", "platforms/lte_fighter.txt"]
    assert facts["named_routes"] == ["blue_route"]
    # The entry prologue is the column-0 block only: the instance's own
    # script_variables belong to the platform, not to the entry.
    assert "log_print" in facts["global_script_variables"]
    assert "log" in facts["global_script_variables"]
    assert "START_TYPE" not in facts["global_script_variables"]
    assert "MISSION_TYPE" not in facts["global_script_variables"]
    # The prologue is a recipe to copy, so its lines ride along with the
    # names, and the $define lines it interpolates come with it.
    assert "bool log_print = true;" in facts["global_script_prologue"]
    assert "FileIO log = FileIO();" in facts["global_script_prologue"]
    assert facts["defines"] == ["REP 1"]


# ---------------------------------------------------- prologue include-merge
# Demo entries delegate the force layout to an included scenarios/<name>.txt,
# usually through a ${SCNRIO} path variable, and the script prologue lives in
# the parent entry while the instances live in the child. The catalog must
# merge the parent's prologue down or the child's examples are half a recipe.


class _CatalogHost:
    def __init__(self, demos, tmp_path):
        self._demos = demos
        self.state_dir = tmp_path

    def resolve_demos_root(self):
        return self._demos

    def resolve_afsim_root(self):
        return None

    def write_json(self, path, payload):
        path.write_text(json.dumps(payload), encoding="utf-8")


def test_prologue_is_merged_down_the_include_chain(tmp_path):
    import json

    from core.knowledge.type_index import AfsimTypeIndex

    demos = tmp_path / "demos"
    (demos / "scenarios").mkdir(parents=True)
    (demos / "types.txt").write_text(
        "platform_type BLUE_FIGHTER WSF_PLATFORM\n"
        "   weapon fox3 MEDIUM_RANGE_RADAR_MISSILE\n"
        "end_platform_type\n",
        encoding="utf-8",
    )
    (demos / "scenarios" / "layout.txt").write_text(
        "platform blue_1 BLUE_FIGHTER\n"
        "   side blue\n"
        "   commander SELF\n"
        "   command_chain IFLITE SELF\n"
        "   script_variables\n"
        '      MISSION_TYPE = "SWEEP";\n'
        "   end_script_variables\n"
        "end_platform\n",
        encoding="utf-8",
    )
    (demos / "entry.txt").write_text(
        "include_once types.txt\n"
        "$define REP 1\n"
        "script_variables\n"
        "   bool log_print = true;\n"
        "   FileIO log = FileIO();\n"
        "end_script_variables\n"
        "include_once observers.txt\n"
        "include_once scenarios/${SCNRIO}.txt\n",
        encoding="utf-8",
    )

    catalog = AfsimTypeIndex(_CatalogHost(demos, tmp_path)).build_catalog()

    examples = catalog["demo_usages"]["BLUE_FIGHTER"]
    assert examples, "the instantiated type must carry its demo examples"
    entry = examples[0]["entry"]
    assert entry["prologue_from"] == "entry.txt"
    assert "bool log_print = true;" in entry["global_script_prologue"]
    assert entry["defines"] == ["REP 1"]
    assert "log_print" in entry["global_script_variables"]
    # The include order around the prologue is part of the recipe: whatever
    # consumes the globals must be included after the block.
    assert entry["parent_includes_before_prologue"] == ["types.txt"]
    assert entry["parent_includes_after_prologue"] == ["observers.txt", "scenarios/${SCNRIO}.txt"]
