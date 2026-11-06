"""Policy: the judgements this server makes, in one place.

Everything below is a decision, not a fact. The facts come from the AFSIM
installation (core/knowledge) and the executor runs things (core/runtime,
core/validation, core/analysis). Which of those facts should count as a
failure is a judgement, and it used to be buried inside validation.py where it
read as if Mission had said so.

Each rule is named and can be switched off from the tool arguments, so a caller
who disagrees with a judgement is not stuck with it.
"""

# A run that placed platforms and then did nothing is a failed experiment
# under any reasonable standard, so this defaults to on. A caller who only
# cares about exit codes can pass inert_is_failure=false.
DEFAULT_POLICY = {
    # inert_simulation counts as failure
    "inert_is_failure": True,
    # no output files at all counts as failure
    "no_evidence_is_failure": True,
    # a run that produced a .aer but no .evt events passes, with a caveat
    "not_analyzable_is_failure": False,
    # mission's own exit code is trusted when it reported no errors
    "exit_code_is_failure": True,
    # An error that names no file, line and column is about the environment,
    # not the scenario: AFSIM reports log and event_pipe destinations that way.
    # A scenario defect always arrives located, so an unlocated error alone
    # does not invalidate a run mission itself called complete.
    "unlocated_errors_are_environmental": True,
    # a run that simulated a fraction of the time the scenario asked for
    "truncated_run_is_failure": True,
    # how far short of the requested duration still counts as a truncation
    "truncation_tolerance": 0.9,
    # how long to let mission run before giving up
    "default_timeout_sec": 300.0,
    # how much of mission's stdout to echo back when asked
    "default_stdout_chars": 20000,
}


def resolve(overrides=None):
    """Merge caller overrides onto the defaults."""
    policy = dict(DEFAULT_POLICY)
    for key, value in (overrides or {}).items():
        if key in policy:
            policy[key] = value
    return policy


def judge(observations, policy):
    """Turn observed facts into a verdict.

    observations: returncode, errors, timed_out, simulation_complete,
                  inert_simulation, no_evidence, not_analyzable
    """
    problems = []
    caveats = []

    if observations["timed_out"]:
        problems.append(
            f"mission timed out after {policy['default_timeout_sec']}s"
        )
    if observations["errors"]:
        # AFSIM's own error grammar puts a file, line and column on anything
        # wrong with the scenario -- "Could not find platform_type X" arrives
        # as broken.txt 3:18. An error with no location cannot be a defect in
        # a scenario file, and on a run mission itself declared complete the
        # ones that show up are its own plumbing: "Unable to open system log
        # file", "Unable to open event_pipe file". Counting those turned a
        # two-hour battle that ran to 7200 s into a failed validation, so the
        # located errors are what counts and the rest are reported.
        located = [e for e in observations["errors"] if e.get("file")]
        unlocated = [e for e in observations["errors"] if not e.get("file")]
        if policy["unlocated_errors_are_environmental"] and not located:
            for error in unlocated:
                caveats.append(
                    f"mission reported {error.get('severity', 'ERROR')}: "
                    f"{error.get('message', '').strip()} (no scenario location; this is "
                    "about the environment, not the scenario)"
                )
        else:
            problems.append(f"{len(observations['errors'])} error(s) reported by mission")
            if unlocated and located:
                caveats.append(
                    f"{len(unlocated)} of these carry no scenario location and may be "
                    "environmental rather than scenario defects"
                )
    if (
        policy["exit_code_is_failure"]
        and observations["returncode"] not in (0, None)
        and not observations["errors"]
    ):
        problems.append(f"mission exited with code {observations['returncode']}")
    if not observations["simulation_complete"] and not observations["timed_out"]:
        problems.append("mission never reported 'Simulation complete'")

    if observations["no_evidence"]:
        if policy["no_evidence_is_failure"]:
            problems.append(
                "the run wrote no output at all, so nothing can be concluded: the "
                "scenario probably has no event_output or event_pipe block, and no "
                "output directory. Add event_output enabling at least "
                "PLATFORM_INITIALIZED, SENSOR_TRACK_UPDATED and WEAPON_FIRED."
            )
        else:
            caveats.append("the run wrote no output at all")

    if observations["not_analyzable"]:
        message = (
            "no .evt events were recorded, so no KPI can be derived even though the "
            "simulation produced output. Add an event_output block that enables "
            "PLATFORM_INITIALIZED, SENSOR_TRACK_UPDATED and WEAPON_FIRED."
        )
        if policy["not_analyzable_is_failure"]:
            problems.append(message)
        else:
            caveats.append(message)

    duration = observations.get("duration")
    if duration and duration.get("ratio") is not None:
        if duration["ratio"] < policy["truncation_tolerance"]:
            message = (
                f"the run simulated {duration['achieved_sec']:.1f}s of the "
                f"{duration['requested_sec']:.1f}s the scenario asked for "
                f"({duration['ratio'] * 100:.0f}%). AFSIM defaults to 60 s when the "
                "entry file declares no end_time."
            )
            if policy["truncated_run_is_failure"]:
                problems.append(message)
            else:
                caveats.append(message)

    if duration and not duration.get("declared_end_time", True):
        # The old wording asserted the run "used AFSIM's 60 s default" and told
        # the caller to add an end_time. It fired on a run that had just
        # reported achieved_sec: 7200 -- the caveat claimed 60 s while the
        # payload beside it said two hours, and the advice was to add a line
        # the scenario already had and which was working. Only claim the
        # default when the evidence supports it.
        achieved = duration.get("achieved_sec")
        requested = duration.get("requested_sec")
        if achieved is not None and abs(achieved - 60.0) <= 1.0:
            caveats.append(
                "no end_time is declared anywhere in the scenario's include graph, and "
                "the run stopped at AFSIM's 60 s default. If the engagement is meant "
                "to last longer, add a top-level 'end_time N min'."
            )
        else:
            caveats.append(
                f"no end_time is declared anywhere in the scenario's include graph. The "
                f"run still reached {achieved:.0f}s, so it was ended by something other "
                "than AFSIM's 60 s default -- usually every platform has been deleted or "
                "the last route is finished. Declaring the intended length with "
                "'end_time N min' makes the run stop when you mean it to."
                if achieved is not None
                else "no end_time is declared anywhere in the scenario's include graph. "
                "Declaring the intended length with 'end_time N min' makes the run stop "
                "when you mean it to."
            )

    if observations["inert_simulation"]:
        message = (
            "simulation ran but produced no activity: only PLATFORM_INITIALIZED events, "
            "so nothing detected, tracked or fired"
        )
        if policy["inert_is_failure"]:
            problems.append(message)
        else:
            caveats.append(message)

    # One environmental error repeats per affected object (each platform's
    # script context), and echoing it forty times hides the shape of the
    # failure behind volume. Identical caveats collapse into one with a count.
    counts = {}
    order = []
    for message in caveats:
        if message not in counts:
            counts[message] = 0
            order.append(message)
        counts[message] += 1
    caveats = [
        f"{message} (x{counts[message]})" if counts[message] > 1 else message
        for message in order
    ]

    return {
        "ok": not problems,
        "problems": problems,
        "caveats": caveats,
        "policy": policy,
    }
