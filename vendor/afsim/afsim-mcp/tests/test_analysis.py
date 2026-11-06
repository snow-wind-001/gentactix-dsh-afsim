"""Loss accounting and .evt parsing.

The defect these lock down was a false negative on an acceptance criterion:
an expended missile was counted as a destroyed aircraft, so a scenario with
zero combat losses reported nine. The name-token heuristic that caused it is
gone, so the tests assert on the evidence path instead of on a vocabulary.
"""

import json


# Field shapes copied from evt files shipped with AFSIM 2.9.0, not invented.
# These runs carry only Type / Side / Ps, which is all AFSIM emits for
# PLATFORM_INITIALIZED and PLATFORM_BROKEN.
INIT_FIGHTER = "0.0 PLATFORM_INITIALIZED BLUE_FIGHTER_1 Type: BLUE_FIGHTER Side: blue\n"
INIT_SAM = "0.0 PLATFORM_INITIALIZED BLUE_SAM_SITE Type: BLUE_SAM_SITE Side: blue\n"
FIRED_ROUND = (
    "600.0 WEAPON_FIRED BLUE_FIGHTER_1 RED_ATTACK_1 "
    "BLUE_FIGHTER_1:1_blue_a4_a2a_missile_1 Engagement: 1 Start_Time: 600.0 \\\n"
    "   Weapon: blue_a4_a2a_missile\n"
)
BROKEN_ROUND = (
    "640.0 PLATFORM_BROKEN BLUE_FIGHTER_1:1_blue_a4_a2a_missile_1 "
    "Type: BLUE_A4_A2A_MISSILE Side: blue Ps: 0\n"
)
BROKEN_TARGET = (
    "641.0 PLATFORM_BROKEN RED_ATTACK_1 Type: RED_ATTACK Type: RED_ATTACK Side: red Ps: 0\n"
)
BROKEN_SAM = "1500.0 PLATFORM_BROKEN BLUE_SAM_SITE Type: BLUE_SAM_SITE Side: blue Ps: 0\n"


def _write_evt(tmp_path, body, name="scenario.evt"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _analyze(call_tool, path):
    result, _req_id = call_tool("analyze_run", {"evt_path": str(path)})
    payload = result.responses[-1]["result"]
    text = payload["content"][0]["text"]
    return json.loads(text)["analysis"]


def test_launched_round_is_not_a_combat_loss(call_tool, tmp_path):
    analysis = _analyze(call_tool, _write_evt(tmp_path, INIT_FIGHTER + FIRED_ROUND + BROKEN_ROUND))

    blue = analysis["red_blue_losses"]["blue"]
    assert blue["platforms_lost"] == 0
    assert blue["weapons_expended"] == 1
    assert analysis["loss_accounting"]["launched_weapon_platforms"] == 1
    assert analysis["loss_accounting"]["unverified_loss_count"] == 0


def test_real_platform_loss_is_counted_and_verified(call_tool, tmp_path):
    body = INIT_FIGHTER + INIT_SAM + FIRED_ROUND + BROKEN_ROUND + BROKEN_SAM
    analysis = _analyze(call_tool, _write_evt(tmp_path, body))

    blue = analysis["red_blue_losses"]["blue"]
    assert blue["platforms_lost"] == 1
    assert blue["weapons_expended"] == 1
    assert analysis["loss_accounting"]["unverified_loss_count"] == 0
    assert analysis["loss_accounting"]["initialized_platforms"] == 2


def test_loss_without_evidence_is_flagged_not_guessed(call_tool, tmp_path):
    # No PLATFORM_INITIALIZED and no WEAPON_FIRED: event_output omitted them.
    # The report must say the number is unverified rather than silently pick
    # a bucket from the spelling of the name.
    analysis = _analyze(call_tool, _write_evt(tmp_path, BROKEN_SAM))

    accounting = analysis["loss_accounting"]
    assert accounting["unverified_loss_count"] == 1
    assert accounting["unverified_losses"][0]["platform"] == "BLUE_SAM_SITE"
    assert analysis["red_blue_losses"]["blue"]["platforms_lost"] == 1


def test_hh_mm_ss_timestamps_are_parsed(call_tool, tmp_path):
    # AFSIM emits this format when the run selects it; a parser anchored on
    # decimal seconds returned zero records for the whole file.
    body = (
        "00:10:00.0 PLATFORM_INITIALIZED BLUE_FIGHTER_1 Type: BLUE_FIGHTER Side: blue\n"
        "00:12:26.8 PLATFORM_BROKEN RED_MRBM_1 Type: RED_MRBM Side: red Ps: 0\n"
    )
    analysis = _analyze(call_tool, _write_evt(tmp_path, body))

    assert analysis["records_parsed"] == 2
    assert analysis["first_event_sec"] == 600.0
    assert analysis["last_event_sec"] == 746.8
    assert analysis["red_blue_losses"]["red"]["platforms_lost"] == 1


def test_sustained_tracking_without_engagement_is_flagged():
    # The failure shape that cost a whole evaluation round: sensors work, the
    # engagement decision never follows, and nothing in the report says why.
    from core.analysis import AnalysisService

    service = AnalysisService(None)
    notes = service.build_diagnostics(
        [],
        {"PLATFORM_INITIALIZED": 4, "SENSOR_TRACK_INITIATED": 30, "SENSOR_TRACK_UPDATED": 900},
        evt_path=None,
        scenario_dir=None,
    )
    flagged = [n for n in notes if n["issue"] == "tracking_without_engagement"]
    assert flagged, "sustained tracking with zero shots must produce a diagnostic"
    assert "demo_instantiations" in flagged[0]["likely_cause"]


def test_tracking_without_engagement_stays_silent_when_weapons_fire():
    from core.analysis import AnalysisService

    service = AnalysisService(None)
    notes = service.build_diagnostics(
        [],
        {"SENSOR_TRACK_UPDATED": 900, "WEAPON_FIRED": 11, "WEAPON_HIT": 2},
        evt_path=None,
        scenario_dir=None,
    )
    assert "tracking_without_engagement" not in {n["issue"] for n in notes}
