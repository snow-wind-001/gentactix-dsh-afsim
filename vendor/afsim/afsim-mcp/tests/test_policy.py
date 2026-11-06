"""The policy layer: the judgements, named and overridable.

If a caller disagrees with how a result is judged, they can say so rather than
being stuck with it. These tests pin both the defaults and the overrides.
"""

from core import policy


def observations(**overrides):
    base = {
        "returncode": 0,
        "errors": [],
        "timed_out": False,
        "simulation_complete": True,
        "inert_simulation": False,
        "no_evidence": False,
        "not_analyzable": False,
    }
    base.update(overrides)
    return base


def test_a_clean_run_passes():
    verdict = policy.judge(observations(), policy.resolve())
    assert verdict["ok"] is True
    assert verdict["problems"] == []


def test_a_located_error_fails():
    # AFSIM's error grammar puts a file, line and column on anything wrong
    # with the scenario: "Could not find platform_type X" arrives as
    # broken.txt 3:18.
    verdict = policy.judge(
        observations(
            errors=[{"severity": "ERROR", "message": "bad", "file": "s.txt", "line": 3}]
        ),
        policy.resolve(),
    )
    assert verdict["ok"] is False
    assert "1 error(s)" in verdict["problems"][0]


def test_an_unlocated_error_is_environmental_by_default():
    # "Unable to open system log file" and "Unable to open event_pipe file"
    # carry no location, and counting them made a two-hour battle that ran to
    # 7200 s report as a failed validation.
    verdict = policy.judge(
        observations(
            errors=[{"severity": "ERROR", "message": "Unable to open event_pipe file."}]
        ),
        policy.resolve(),
    )
    assert verdict["ok"] is True
    # Not silently dropped: the message is handed back verbatim.
    assert any("event_pipe" in caveat for caveat in verdict["caveats"])


def test_unlocated_errors_can_be_made_fatal():
    settings = policy.resolve({"unlocated_errors_are_environmental": False})
    verdict = policy.judge(
        observations(errors=[{"severity": "ERROR", "message": "boom"}]), settings
    )
    assert verdict["ok"] is False


def test_a_located_error_outweighs_an_unlocated_one():
    verdict = policy.judge(
        observations(
            errors=[
                {"severity": "ERROR", "message": "Could not find platform_type X",
                 "file": "s.txt", "line": 3},
                {"severity": "ERROR", "message": "Unable to open system log file."},
            ]
        ),
        policy.resolve(),
    )
    assert verdict["ok"] is False
    assert "2 error(s)" in verdict["problems"][0]
    assert any("may be environmental" in caveat for caveat in verdict["caveats"])


def test_inert_is_a_failure_by_default():
    verdict = policy.judge(observations(inert_simulation=True), policy.resolve())
    assert verdict["ok"] is False
    assert "no activity" in verdict["problems"][0]


def test_inert_can_be_downgraded_to_a_caveat():
    settings = policy.resolve({"inert_is_failure": False})
    verdict = policy.judge(observations(inert_simulation=True), settings)
    assert verdict["ok"] is True
    assert verdict["problems"] == []
    assert verdict["caveats"]


def test_not_analyzable_passes_with_a_caveat_by_default():
    """The simulation ran; it simply cannot be scored."""
    verdict = policy.judge(observations(not_analyzable=True), policy.resolve())
    assert verdict["ok"] is True
    assert verdict["caveats"]


def test_no_evidence_fails_by_default_and_can_be_overridden():
    settings = policy.resolve()
    assert policy.judge(observations(no_evidence=True), settings)["ok"] is False

    relaxed = policy.resolve({"no_evidence_is_failure": False})
    verdict = policy.judge(observations(no_evidence=True), relaxed)
    assert verdict["ok"] is True
    assert verdict["caveats"]


def test_the_verdict_reports_which_policy_produced_it():
    """A verdict without its policy is not auditable."""
    settings = policy.resolve({"inert_is_failure": False})
    verdict = policy.judge(observations(), settings)
    assert verdict["policy"]["inert_is_failure"] is False


def test_unknown_overrides_are_ignored():
    settings = policy.resolve({"made_up_switch": True})
    assert "made_up_switch" not in settings


def test_policy_defaults_are_all_named_and_documented():
    for name in policy.DEFAULT_POLICY:
        assert name.isidentifier()


def test_a_truncated_run_fails_by_default():
    """A scenario asking for two hours that simulated one minute is a failure."""
    verdict = policy.judge(
        observations(duration={"requested_sec": 7200, "achieved_sec": 60, "ratio": 0.008,
                               "declared_end_time": False}),
        policy.resolve(),
    )
    assert verdict["ok"] is False
    assert "60 s" in verdict["problems"][0] or "60.0" in verdict["problems"][0]


def test_truncation_can_be_overridden():
    verdict = policy.judge(
        observations(duration={"requested_sec": 7200, "achieved_sec": 60, "ratio": 0.008,
                               "declared_end_time": True}),
        policy.resolve({"truncated_run_is_failure": False}),
    )
    assert verdict["ok"] is True


def test_leaving_off_end_time_is_nudged():
    verdict = policy.judge(
        observations(duration={"requested_sec": 60, "achieved_sec": 60, "ratio": 1.0,
                               "declared_end_time": False}),
        policy.resolve(),
    )
    assert verdict["ok"] is True
    assert any("end_time" in c for c in verdict["caveats"])


def test_repeated_environmental_errors_collapse_into_one_counted_caveat():
    # Every platform whose script context fails repeats the same unlocated
    # error; forty identical lines hide the shape of the failure behind volume.
    from core.policy import DEFAULT_POLICY, judge

    observations = {
        "returncode": 0,
        "errors": [
            {"severity": "ERROR", "message": "Could not resolve reference to extern variable."}
        ]
        * 40,
        "timed_out": False,
        "simulation_complete": True,
        "inert_simulation": False,
        "no_evidence": False,
        "not_analyzable": False,
    }
    verdict = judge(observations, dict(DEFAULT_POLICY))
    extern = [c for c in verdict["caveats"] if "extern variable" in c]
    assert len(extern) == 1
    assert extern[0].endswith("(x40)")
