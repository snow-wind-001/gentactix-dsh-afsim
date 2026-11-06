"""Tests for the real-AFSIM validation service.

The parser and the output summarizer are exercised directly against the
formats Mission 2.9 actually produces; only the tool itself needs mission.exe.
"""

from pathlib import Path

import pytest

from core.validation import AfsimValidationService

REAL_FATAL = """mission:
    WSF Version: 2.9.0 02-25-2022
Loading simulation input.

***** FATAL: Could not process input files.
    ***** ERROR: Unknown command: totally_bogus_keyword
             's.txt', line 2, near column 22
Reading of simulation input failed
"""

# A real .evt record: timestamp then event name, continued on indented lines.
REAL_EVT = """0.00000 PLATFORM_INITIALIZED blue_1 Type: WSF_PLATFORM Side: blue \\
 LLA: 33:02:24.00n 42:25:12.00e 9753.6 m Heading: 69.234 deg Pitch: 0.000 deg Roll: 0.000 deg \\
 Speed: 231.500 m/s * [ 0.355 0.935 0.000 ] Acceleration: 0.000 m/s2 * [ 0.000 0.000 0.000 ]
0.00000 PLATFORM_INITIALIZED red_1 Type: WSF_PLATFORM Side: red \\
 LLA: 33:00:00.00n 45:36:00.00e 9144 m Heading: 281.351 deg \\
 Speed: 216.067 m/s * [ 0.197 -0.980 0.000 ] Acceleration: 0.000 m/s2
"""


@pytest.fixture
def service():
    return AfsimValidationService(host=None)


def test_parses_real_mission_error_with_file_line_column(service, tmp_path):
    """The old regexes returned [] against real Mission output."""
    (tmp_path / "s.txt").write_text("end_time 10 min\ntotally_bogus_keyword 5\n", encoding="utf-8")

    diagnostics = service.parse_mission_output(REAL_FATAL, base_dir=tmp_path)

    errors = [d for d in diagnostics if d["severity"] in ("ERROR", "FATAL")]
    assert errors, "real Mission errors must be detected"
    detail = errors[-1]
    assert detail["message"] == "Unknown command: totally_bogus_keyword"
    assert detail["line"] == 2
    assert detail["column"] == 22
    assert detail["file"] == str(tmp_path / "s.txt")
    assert detail["source_line"] == "totally_bogus_keyword 5"


def test_missing_file_error_is_detected(service, tmp_path):
    real = (
        "***** FATAL: Could not process input files.\n"
        "    ***** ERROR: Cannot open file: observer.txt\n"
    )
    diagnostics = service.parse_mission_output(real, base_dir=tmp_path)
    assert any("Cannot open file" in d["message"] for d in diagnostics)


def test_evt_summary_uses_second_token_as_event_name(service, tmp_path):
    (tmp_path / "run.evt").write_text(REAL_EVT, encoding="utf-8")

    summary = service.summarize_outputs(tmp_path, "run")

    assert summary["evt_events"] == 2, "continuation lines must not count as events"
    assert summary["evt_categories"] == {"PLATFORM_INITIALIZED": 2}


def test_evt_summary_counts_activity_events(service, tmp_path):
    text = REAL_EVT + (
        "120.500 SENSOR_TRACK_INITIATED blue_1 red_1\n"
        "180.000 WEAPON_FIRED blue_1 red_1\n"
        "181.000 WEAPON_HIT blue_1 red_1\n"
    )
    (tmp_path / "run.evt").write_text(text, encoding="utf-8")

    summary = service.summarize_outputs(tmp_path, "run")

    assert summary["evt_events"] == 5
    assert summary["evt_categories"]["SENSOR_TRACK_INITIATED"] == 1
    assert summary["evt_categories"]["WEAPON_HIT"] == 1


def test_aer_size_is_reported(service, tmp_path):
    (tmp_path / "run.evt").write_text(REAL_EVT, encoding="utf-8")
    (tmp_path / "run.aer").write_bytes(b"x" * 4096)

    summary = service.summarize_outputs(tmp_path, "run")

    assert summary["aer_bytes"] == 4096


def test_missing_output_dir_is_not_an_error(service, tmp_path):
    summary = service.summarize_outputs(tmp_path / "nope", "run")
    assert summary["evt_events"] == 0
    assert summary["aer_bytes"] == 0


# ---------------------------------------------------------------- regression
# These came out of an end-to-end evaluation: a subagent built a scenario with
# only the four tools, and these are the failures it could have hit silently.


def test_parsed_compile_error_keeps_its_location(service):
    """"Unable to compile script." does carry file/line/column; the parser must keep it."""
    text = (
        "***** FATAL: Could not process input files.\n"
        "    ***** ERROR: Unable to compile script.\n"
        "             's.txt', line 5, near column 21\n"
    )
    diagnostics = service.parse_mission_output(text)
    located = [d for d in diagnostics if d.get("line") is not None]
    assert located, "the compile error must keep its location"
    assert located[0]["line"] == 5
    assert located[0]["column"] == 21
    assert located[0]["message"] == "Unable to compile script."


def test_unlocated_errors_do_not_shift_the_next_location(service):
    """A bare ERROR with no location must not absorb the following location line."""
    text = (
        "***** ERROR: Cannot implicitly cast to int from string.\n"
        "***** ERROR: Error in script.\n"
        "***** ERROR: Unable to compile script.\n"
        "         's.txt', line 5, near column 21\n"
    )
    diagnostics = service.parse_mission_output(text)
    compile_error = [d for d in diagnostics if d["message"] == "Unable to compile script."][0]
    assert compile_error["line"] == 5
    assert all(d["line"] is None for d in diagnostics[:-1])


def test_include_hint_finds_a_demo_file(tmp_path, monkeypatch):
    """A demo type's sibling includes only resolve if file_path names its demo."""
    from core.validation import AfsimValidationService

    demos = tmp_path / "demos" / "my_demo" / "platforms"
    (demos / "widgets").mkdir(parents=True)
    (demos / "widgets" / "thing.txt").write_text("platform_type WIDGET WSF_PLATFORM\nend_platform_type\n")

    class Host:
        def resolve_demos_root(self):
            return tmp_path / "demos"

        def resolve_afsim_root(self):
            return None

    hint = AfsimValidationService(Host()).resolve_include_hint("platforms/widgets/thing.txt")
    assert hint["found"] is True
    assert hint["match"] == "basename"
    assert hint["candidates"][0]["add_to_entry_file"].endswith("my_demo")


def test_include_hint_reports_a_genuinely_missing_file(tmp_path):
    from core.validation import AfsimValidationService

    class Host:
        def resolve_demos_root(self):
            return tmp_path / "empty"

        def resolve_afsim_root(self):
            return None

    (tmp_path / "empty").mkdir()
    hint = AfsimValidationService(Host()).resolve_include_hint("platforms/nope.txt")
    assert hint["found"] is False
    assert hint["path"] == "platforms/nope.txt"
