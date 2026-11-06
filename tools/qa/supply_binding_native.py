"""Exercise frozen multi-depot inputs through real DSH Native MCP / AFSIM.

Requires --live. Separate QA sessions, no model request or user-world mutation.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live required to start actual AFSIM')
    root = Path('.cache/qa/supply-binding-2026-11-01/native') / str(time.time_ns())
    root.mkdir(parents=True)
    for key, suffix in [('SESSION_DIR', 'sessions'), ('TRACE_DIR', 'traces'), ('DSH_HOME', 'dsh-home'),
                        ('DSH_WORKSPACE', 'workspace'), ('ROLE_INDEX', 'roles.json'),
                        ('LLM_CONFIG', 'llm.enc'), ('VAULT_KEY_FILE', 'vault.key')]:
        os.environ['GENTACTIX_' + key] = str((root / suffix).resolve())
    from backend import afsim_rules, afsim_world, harness_engine
    from gentactix import missions, sim_clock
    from tools.qa.supply_binding_fixture import definition
    result = {'passed': False, 'actual_afsim': True, 'actual_model': False, 'cases': [],
              'scope': 'Bound food/ammo warehouse identity; not site-specific fuel/shell depots or historical calibration'}

    def save():
        (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')

    def run(label, before):
        frozen = copy.deepcopy(before)
        scene = afsim_world.compile_scene(before, [], 1800, native_rules=True)
        with patch.object(missions, 'advance', side_effect=AssertionError('No Python physical executor')):
            positions, evidence = afsim_world.run_scene({}, scene)
            after = afsim_rules.apply_telemetry(evidence.pop('native_effects'), scene['native_model'], scene,
                                               afsim_world.apply_observations(before, positions, scene))
        after['current_time'], after['simulation_clock'] = sim_clock.target(before, '30分钟')
        missions.evaluate(after)
        missions.validate(after)
        assert before == frozen
        assert len(missions.units(before)) == len(missions.units(after)) == 6
        stocks = {n['id']: n['stock'] for n in after['supply_nodes']}
        ledger = {r['unit']: r for r in after['mission']['ledger']}
        draws = {n['id']: 0.0 for n in before['supply_nodes']}
        for _, unit in missions.units(before):
            assert ledger[unit['name']]['source_node_id'] == unit['supply_node_id']
            draws[unit['supply_node_id']] += ledger[unit['name']]['delivery']
        for node in before['supply_nodes']:
            assert abs(node['stock'] - draws[node['id']] - stocks[node['id']]) < 1e-6
        main_id = before['red_units'][0]['supply_node_id']
        assert stocks[main_id] == 0
        assert ledger[before['red_units'][0]['name']]['delivery'] == 0
        assert stocks['qa-red-unused'] == 99
        positive = next(n for n in before['supply_nodes'] if n['id'] == 'qa-red-branch')['stock'] > 0
        for unit in before['red_units'][1:]:
            assert (ledger[unit['name']]['delivery'] > 0) == positive
        (root / (label + '.json')).write_text(json.dumps(after, ensure_ascii=False) + '\n')
        result['cases'].append({'label': label, 'stocks': stocks, 'draws': draws,
                                'deliveries': {k: v['delivery'] for k, v in ledger.items()}, 'native': evidence})
        save()
        print('PASS', label, flush=True)
        return after

    try:
        for combined, split in ((False, False), (True, False), (True, True)):
            spec = definition(combined=combined, split=split)
            original = missions.definition
            with patch.object(missions, 'definition', side_effect=lambda identity:
                              copy.deepcopy(spec) if identity == spec['id'] else original(identity)):
                state = missions.from_definition(spec)
                label = ('combined' if combined else 'legacy') + ('-split' if split else '')
                first = run(label, state)
                run(label + '-continued', first)
                empty = copy.deepcopy(state)
                depot = next(n for n in empty['supply_nodes'] if n['id'] == 'qa-red-branch')
                depot['stock'] = 0
                if split:
                    depot['commodities'] = {'food': 0, 'ammo': 0}
                run(label + '-branch-empty', empty)
        result['passed'] = True
    except Exception as exc:
        result['error'] = str(exc)
        raise
    finally:
        save()
        harness_engine.close_harness()
        print('Evidence:', root, flush=True)


if __name__ == '__main__': main()
