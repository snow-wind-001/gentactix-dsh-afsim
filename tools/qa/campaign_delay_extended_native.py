"""Opt-in Native blue-goal and partition contrasts; isolated numerical QA, no LLM."""
import argparse
import copy
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live', action='store_true')
args = parser.parse_args()
if not args.live:
    parser.error('Actual local AFSIM execution requires --live')
out = Path('.cache/qa/state-observation-map-2026-11-01/delay-extension-native') / str(time.time_ns())
out.mkdir(parents=True)
for key, suffix in [('SESSION_DIR', 'sessions'), ('TRACE_DIR', 'traces'),
                    ('DSH_HOME', 'dsh-home'), ('DSH_WORKSPACE', 'workspace'), ('ROLE_INDEX', 'roles.json')]:
    os.environ['GENTACTIX_' + key] = str((out / suffix).resolve())

from tools.qa.jizhong_assembly_fixture import inputs, NOTE
from gentactix import missions, historical_operations as ho, sim_clock, campaign
from backend import afsim_world, afsim_rules, harness_engine


def partition(parameters, identity):
    parent = parameters['actors'][identity]
    parts = []
    for n in (0, 1):
        share = lambda value: value // 2 if n == 0 else value - value // 2
        parts.append(dict(id='part' + str(n), label='QA分队' + str(n),
            personnel=share(parent['personnel']), position=copy.deepcopy(parent['position']),
            equipment={k: share(v) for k, v in parent['equipment'].items()},
            resources={k: share(parent['formation'][k]) for k in ('fuel_liters', 'spares', 'materials', 'shells', 'aa_rounds')},
            dispersion_km2=parent['formation']['dispersion_km2'] / 2, assumption=NOTE))
    parameters['partitions'] = dict(version='formation-partitions-2',
        groups={identity: dict(parts=parts, assumption=NOTE)})


checks = []
try:
    cases = [('blue', c, False, expected) for c, expected in [
        ('survive', True), ('enemy_exit', False), ('friendly_pending', False), ('enemy_pending', True)]]
    cases += [(team, case, True, expected) for team in ('red', 'blue')
              for case, expected in [('survive', True), ('friendly_pending', False)]]
    for team, case, parts, expected in cases:
        source, p = inputs()
        p['goal'].update(team=team, profile='delay', required_survivors=2, required_turns=1,
            exit={'lat': 38.7, 'lng': 115.6})
        p['rules'].update(goal_profile='delay', required_survivors=2)
        p['campaign']['objective_policy'] = 'defensive-delay-1'
        owners = {u['id']: u['team'] for u in source['definition']['units']}
        friendly = [i for i in p['actors'] if owners[i] == team]
        enemy = [i for i in p['actors'] if owners[i] != team]
        if case in ('enemy_exit', 'enemy_pending'):
            p['actors'][enemy[0]]['position'] = copy.deepcopy(p['goal']['exit'])
        if case == 'enemy_pending':
            p['campaign']['arrivals'][enemy[0]]['not_before'] = '1942-05-02T00:00:00'
        if case == 'friendly_pending':
            for identity in friendly[1:]:
                p['campaign']['arrivals'][identity]['not_before'] = '1942-05-02T00:00:00'
        if parts:
            partition(p, friendly[0])
        before = ho.initial(source, p)
        orders = [{'unit': u['name'], 'action': 'hold'} for _, u in missions.units(before)]
        scene = afsim_world.compile_scene(before, orders, 1800, native_rules=True)
        with patch.object(missions, 'advance', side_effect=AssertionError('No Python physical fallback')):
            positions, evidence = afsim_world.run_scene({}, scene)
            after = afsim_rules.apply_telemetry(evidence['native_effects'], scene['native_model'], scene,
                afsim_world.apply_observations(before, positions, scene))
        after['current_time'], after['simulation_clock'] = sim_clock.target(before, '30分钟')
        missions.validate(after)
        native = after['mission']['metrics']['condition']
        host = campaign.delay_assess(after)
        label = f'{team}-{case}-' + ('partitioned' if parts else 'whole')
        assert native == expected and host['condition'] == expected, (label, native, host, expected)
        assert after['historical_initial'] == source
        assert len(list(missions.units(after))) == (35 if parts else 34)
        if parts and case == 'friendly_pending':
            assert host['survivors'] == 1, 'Two disjoint parts cannot become two parent survivors'
        (out / (label + '-world.json')).write_text(json.dumps(after, ensure_ascii=False))
        (out / (label + '-native.json')).write_text(json.dumps(evidence, ensure_ascii=False))
        checks.append(dict(case=label, condition=native, host=host, entities=len(scene['entities']),
            returncode=evidence['returncode']))
        print('PASS', label, native, flush=True)
    result = dict(passed=True, checks=checks, actual_native_turns=len(checks), actual_model=False,
        original_historical_identities=34, scope=NOTE + ' Independent30minute goal-only contrasts; partitions are explicit calculation assumptions, not runtime split or complete history.')
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print('RESULT', out / 'result.json', flush=True)
finally:
    harness_engine.close_harness()
