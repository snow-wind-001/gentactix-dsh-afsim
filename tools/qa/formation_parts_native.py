"""Opt-in actual WSF tests for split positions, accounting and shared goals."""
import argparse
import copy
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true')
args = parser.parse_args()
if not args.live:
    parser.error('Actual AFSIM requires --live')
root = Path('.cache/qa/formation-partitions/native') / str(time.time_ns())
root.mkdir(parents=True)
for key, suffix in (('SESSION_DIR', 'sessions'), ('TRACE_DIR', 'traces'), ('DSH_HOME', 'dsh-home'),
                    ('DSH_WORKSPACE', 'workspace'), ('ROLE_INDEX', 'roles.json'),
                    ('LLM_CONFIG', 'llm.enc'), ('VAULT_KEY_FILE', 'vault.key')):
    os.environ['GENTACTIX_' + key] = str(root.resolve() / suffix)

from backend import afsim_world, afsim_rules, harness_engine
from gentactix import historical_operations as ho, missions, sim_clock, formation_parts
from tools.qa.historical_crossing_fixture import inputs
from verify_formation_parts import partition_input

results = []
passed = False


def execute(label, before, orders):
    frozen = copy.deepcopy(before)
    scene = afsim_world.compile_scene(before, orders, 1800, native_rules=True)
    with patch.object(missions, 'advance', side_effect=AssertionError('No Python executor')):
        positions, evidence = afsim_world.run_scene({}, scene)
        after = afsim_rules.apply_telemetry(evidence.pop('native_effects'), scene['native_model'], scene,
                                          afsim_world.apply_observations(before, positions, scene))
    after['current_time'], after['simulation_clock'] = sim_clock.target(before, '30分钟')
    after['afsim'] = evidence
    missions.validate(after)
    assert before == frozen
    (root / (label + '.json')).write_text(json.dumps(after, ensure_ascii=False, indent=2) + '\n')
    print(label, 'native receipts decoded', flush=True)
    return after


try:
    snapshot, params = inputs()
    params['partitions'] = partition_input(params)
    initial = ho.initial(snapshot, params)
    after = execute('two-banks-hold', initial, [])
    group = formation_parts.observation(after)['groups'][0]
    assert [p['current'] for p in group['parts']] == [1595, 5]
    assert group['parts'][0]['lat'] < 27.3148 < group['parts'][1]['lat']
    assert abs(group['normalized_stock_equivalent']['food'] - 78) < 1e-8
    assert abs(sum(r['food_spent'] for r in after['mission']['ledger'] if r['unit'] in initial['formation_groups']['groups'][0]['members']) - 2) < 1e-8
    results.append({'case': 'two-banks-hold', 'passed': True})
    # A five-person element can be supplied by its own explicitly allocated
    # vehicle. Fractional parent-equivalent stocks must survive native output.
    parts = params['partitions']['groups']['lm.red.cmc_column']['parts']
    parts[0]['equipment']['transport'] = 3
    parts[1]['equipment']['transport'] = 1
    parts[1]['position']['lat'] = 27.3139
    params['support']['red']['stock'] = 10
    supplied = ho.initial(snapshot, params)
    tiny = supplied['red_units'][1]
    after = execute('fractional-stock-supply', supplied, [{'unit': tiny['name'], 'action': 'resupply'}])
    # Main: 3 trucks*.15 tonnes/.25=1.8 equivalent units; tiny: .025;
    # the other red formation: 2. The depot must retain the fractional balance.
    assert abs(after['supply_nodes'][0]['stock'] - 6.175) < 1e-8
    assert abs(after['red_units'][1]['logistics']['food'] - 86) < 1e-8
    assert abs(after['red_units'][1]['logistics']['ammo'] - 88) < 1e-8
    assert abs(next(r for r in after['mission']['ledger'] if r['unit'] == tiny['name'])['delivery'] - .025) < 1e-8
    results.append({'case': 'fractional-stock-supply', 'passed': True})
    moving = execute('only-five-move', initial, [{'unit': initial['red_units'][1]['name'], 'action': 'move',
                                                'lat': 27.3165, 'lng': 107.402}])
    assert missions.distance(initial['red_units'][0], moving['red_units'][0]) < .001
    assert missions.distance(moving['red_units'][1], {'lat': 27.3165, 'lng': 107.402}) < .01
    assert moving['red_units'][0]['logistics']['food'] == 78 and moving['red_units'][1]['logistics']['food'] == 76
    results.append({'case': 'independent-five-person-move', 'passed': True})
    snapshot, fighting_params = inputs()
    fighting_params['partitions'] = partition_input(fighting_params)
    blue_id = next(i for i in fighting_params['actors'] if i.startswith('lm.blue.'))
    fighting_params['actors'][blue_id].update(personnel=20, position={'lat': 27.3166, 'lng': 107.402})
    fighting = ho.initial(snapshot, fighting_params)
    fire_order = [{'unit': fighting['red_units'][1]['name'], 'action': 'fire', 'target': fighting['blue_units'][0]['name']}]
    fought = execute('five-person-covering-fire', fighting, fire_order)
    held = execute('same-prior-no-fire', fighting, [])
    assert fought['red_units'][1]['formation']['last_execution']['fire_cycles'] > 0
    assert fought['red_units'][0]['logistics']['ammo'] == 80
    assert 0 < fought['blue_units'][0]['personnel']['casualties'] <= 20
    assert held['blue_units'][0]['personnel']['casualties'] == 0
    assert fighting['blue_units'][0]['personnel']['casualties'] == 0
    results.append({'case': 'five-person-fire-versus-hold', 'passed': True})
    snapshot, starving_params = inputs()
    starving_params['actors']['lm.red.cmc_column']['logistics']['food'] = 0
    starving_params['partitions'] = partition_input(starving_params)
    starving = ho.initial(snapshot, starving_params)
    for turn in range(1, 5):
        starving = execute('fractional-noncombat-t' + str(turn), starving, [])
    parts = starving['red_units'][:2]
    assert abs(sum(u['personnel']['noncombat_losses'] + u['formation']['partition_noncombat_remainder'] for u in parts) - 8) < 1e-8
    assert parts[1]['personnel']['current'] == 5  # Not two fabricated losses per small part per turn.
    results.append({'case': 'noncombat-loss-fractional-carry-four-turns', 'passed': True})
    snapshot, goal_params = inputs()
    goal_params['partitions'] = partition_input(goal_params)
    goal_params['goal'].update(profile='breakout', exit={'lat': 27.324, 'lng': 107.402}, required_survivors=2)
    goal_params['rules'].update(goal_profile='breakout', required_survivors=2)
    for part in goal_params['partitions']['groups']['lm.red.cmc_column']['parts']:
        part['position'] = copy.deepcopy(goal_params['goal']['exit'])
    goal_world = ho.initial(snapshot, goal_params)
    goal_after = execute('fragments-not-two-surviving-formations', goal_world, [])
    assert goal_after['mission']['progress'] == 0
    results.append({'case': 'native-parent-objective-counting', 'passed': True})
    snapshot, crossing_params = inputs()
    crossing_params['partitions'] = partition_input(crossing_params)
    crossing_params['goal']['required_survivors'] = crossing_params['rules']['required_survivors'] = 1
    crossing_world = ho.initial(snapshot, crossing_params)
    crossed = execute('parent-passes-with-initial-opposite-bank-party', crossing_world,
                      [{'unit': crossing_world['red_units'][0]['name'], 'action': 'move', 'lat': 27.3158, 'lng': 107.402}])
    assert crossed['red_units'][0]['crossing']['status'] == 'completed'
    assert 'crossing' not in crossed['red_units'][1]
    assert crossed['mission']['status'] == 'completed' and crossed['mission']['winner'] == 'red'
    results.append({'case': 'prepositioned-party-and-parent-crossing-objective', 'passed': True})
    passed = True
    print('PASS native disjoint-position and resource cases', flush=True)
finally:
    (root / 'acceptance.json').write_text(json.dumps({'passed': passed, 'cases': results}) + '\n')
    (root.parent / 'latest.json').write_text(json.dumps({'directory': str(root)}) + '\n')
    harness_engine.close_harness()
