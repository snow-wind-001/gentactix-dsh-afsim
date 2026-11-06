"""The knowledge layer: extraction rules, pinned.

These tests cover the rules that turn AFSIM source into facts. If an AFSIM
upgrade changes the format, these fail here rather than the index silently
returning less than it used to.
"""

from core.knowledge.mission_grammar import MissionGrammar
from core.knowledge.source import read_normalized

CR = chr(13)
LF = chr(10)


def test_crlf_does_not_defeat_parsing(tmp_path):
    """AFSIM demos are Windows-authored; a trailing CR silently dropped lines."""
    path = tmp_path / "d.txt"
    body = (CR + LF).join(
        ["processor P WSF_TASK_PROCESSOR", "   on", "end_processor", ""]
    )
    path.write_bytes(body.encode("utf-8"))

    text = read_normalized(path)

    assert CR not in text
    assert text.count(LF) == 3


def test_grammar_reports_completion_as_a_fact():
    grammar = MissionGrammar()
    assert grammar.is_complete("Simulation complete" + LF + "  Elapsed: 0.9") is True
    assert grammar.is_complete("***** FATAL: Could not process input files.") is False


def test_grammar_extracts_missing_types():
    grammar = MissionGrammar()
    assert grammar.missing_types(
        "***** ERROR: Could not find platform_type WIDGET"
    ) == [("platform_type", "WIDGET")]


def test_grammar_extracts_missing_files():
    grammar = MissionGrammar()
    assert grammar.missing_files(
        "***** ERROR: Cannot open file: observer.txt"
    ) == ["observer.txt"]


def test_grammar_separates_facts_from_verdicts():
    """The grammar states what Mission said; it has no opinion about passing."""
    assert not hasattr(MissionGrammar, "judge")
    assert not hasattr(MissionGrammar, "is_ok")
    assert not hasattr(MissionGrammar, "validate")


# ------------------------------------------------------------- event name union
# Event result classes are spread across one header per extension. Reading only
# the core header lost the whole WEAPON_* family, so the index unions every
# *EventResults*.hpp and must not confuse an export macro with a class name.


def test_event_index_unions_extension_headers_and_skips_export_macros():
    from core.knowledge.event_index import AfsimEventIndex

    index = AfsimEventIndex(None)
    events = {}
    index._parse_header(
        'class WSF_EXPORT PlatformBroken\n'
        '{\n'
        '   static constexpr const char* cNAME = "PLATFORM_BROKEN";',
        events,
    )
    index._parse_header(
        'class WSF_MIL_EXPORT WeaponFired\n'
        '{\n'
        '   static constexpr const char* cNAME = "WEAPON_FIRED";',
        events,
    )
    assert set(events) == {"PLATFORM_BROKEN", "WEAPON_FIRED"}
    assert events["WEAPON_FIRED"]["result_class"] == "WeaponFired"


# ---------------------------------------------------------------- run duration
# AFSIM's default is 60 s when the entry file declares no end_time, and a
# two-hour engagement then silently runs for one minute and exits 0.


def test_declared_duration_reads_end_time(tmp_path):
    from core.knowledge.mission_grammar import declared_duration

    entry = tmp_path / "s.txt"
    entry.write_text("end_time 120 min" + LF + "random_seed 1", encoding="utf-8")
    assert declared_duration(entry) == (7200.0, True)


def test_missing_end_time_falls_back_to_the_afsim_default(tmp_path):
    from core.knowledge.mission_grammar import DEFAULT_DURATION_SEC, declared_duration

    entry = tmp_path / "s.txt"
    entry.write_text("random_seed 1", encoding="utf-8")
    seconds, declared = declared_duration(entry)
    assert seconds == DEFAULT_DURATION_SEC
    assert declared is False


def test_achieved_duration_reads_the_mission_log(tmp_path):
    from core.knowledge.mission_grammar import achieved_duration

    (tmp_path / "mission.log").write_text(
        "2026-09-24 16:38:09 complete 60.001 0.000 0.000", encoding="utf-8"
    )
    assert achieved_duration(tmp_path) == 60.001


def test_run_duration_ratio_flags_a_truncated_run():
    from core.knowledge.mission_grammar import RunDuration

    short = RunDuration(7200.0, 60.001, "AFSIM default (no end_time)", declared=False)
    assert short.ratio < 0.01
    assert short.as_dict()["declared_end_time"] is False
