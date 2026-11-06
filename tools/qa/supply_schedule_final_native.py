"""Actual AFSIM checks for final phase clock anchoring and shared depot limits."""
import argparse
import copy
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    if not parser.parse_args().live:
        parser.error('--live required for actual AFSIM execution')
    root = Path('.cache/qa/supply-schedule-2026-11-01/final-native') / str(time.time_ns())
    root.mkdir(parents=True)
    for key, suffix in [('SESSION_DIR', 'sessions'), ('TRACE_DIR', 'traces'), ('DSH_HOME', 'dsh-home'),
                        ('DSH_WORKSPACE', 'workspace'), ('ROLE_INDEX', 'roles.json'), ('LLM_CONFIG', 'llm.enc'), ('VAULT_KEY_FILE', 'vault.key')]:
        os.environ['GENTACTIX_' + key] = str(root.resolve() / suffix)
    from backend import afsim_rules, afsim_world, harness_engine
    from gentactix import missions, phase_continuity, sim_clock, supply_schedule
    from verify_supply_schedule import world
    result = {'passed': False, 'actual_model': False, 'actual_afsim': True, 'cases': [],
              'scope': 'Uncalibrated stationary QA: civil-time phase anchor and shared warehouse handling limit; not historical operation or transit cargo'}

    def run(label, before):
        frozen = copy.deepcopy(before)
        seconds = sim_clock.duration_seconds(before['mission']['definition']['time_step'])
        scene = afsim_world.compile_scene(before, [], seconds, native_rules=True)
        positions, evidence = afsim_world.run_scene({}, scene)
        after = afsim_rules.apply_telemetry(evidence.pop('native_effects'), scene['native_model'], scene,
                                           afsim_world.apply_observations(before, positions, scene))
        after['current_time'], after['simulation_clock'] = sim_clock.target(before, before['mission']['definition']['time_step'])
        missions.evaluate(after)
        missions.validate(after)
        assert before == frozen
        (root / (label + '.json')).write_text(json.dumps(after, ensure_ascii=False) + '\n')
        result['cases'].append({'label': label, 'native': evidence})
        print('PASS', label, flush=True)
        return after

    try:
        source = world(food=80, step='5分钟')
        source['current_time'], source['simulation_clock'] = sim_clock.target(source, '55分钟')
        source['mission'].update(turn=11, status='completed')
        binding = source['mission']['definition']['historical_calculation']
        params = copy.deepcopy(binding['parameters'])
        params['clock']['start'] = source['current_time']
        from gentactix import historical_operations
        target = {'format': historical_operations.FORMAT, 'initial': binding['initial'], 'parameters': params}
        child = missions.from_definition(phase_continuity.definition(phase_continuity.bind(source, target)))
        # Compare against an active source clock clone. The real completed
        # source is only used to bind the branch, never illegally advanced.
        source['mission']['status'] = 'active'
        left, right = run('source-next-five-minutes', source), run('adjacent-phase-next-five-minutes', child)
        for before, after in ((source, left), (child, right)):
            expected = supply_schedule.event_times(before, 300)
            assert expected == [(300, 'delivery'), (300, 'settlement')]
            for row in after['supply_schedule']['ledger']['units']:
                assert [(e['seconds'], e['kind']) for e in row['events']] == expected
        for (_, a), (_, b) in zip(missions.units(left), missions.units(right)):
            assert a['logistics'] == b['logistics']
            for key in ('version', 'shortage_hours', 'noncombat_remainder'):
                assert a['sustainment'][key] == b['sustainment'][key]
            # Branch turn counters intentionally restart; physical receipts
            # match independently of their different local turn numbers.
            a_receipt = {k:v for k,v in a['sustainment']['last_receipt'].items() if k != 'turn'}
            b_receipt = {k:v for k,v in b['sustainment']['last_receipt'].items() if k != 'turn'}
            assert a_receipt == b_receipt
        template = world()
        binding = copy.deepcopy(template['mission']['definition']['historical_calculation'])
        cfg = binding['parameters']['supply_schedule']
        rules = template['mission']['definition']['combined_rules']
        one_food_delivery = 4 * .5 * rules['ton_per_supply_unit']
        cfg['warehouse_tons_per_hour']['blue-historical-supply'] = one_food_delivery
        shared = historical_operations.initial(binding['initial'], binding['parameters'])
        after = run('two-units-one-warehouse-period-budget', shared)
        checked = supply_schedule.validate_ledger(shared, after['supply_schedule']['ledger'], [], 21600)
        blue = [checked[u['name']] for team, u in missions.units(shared) if team == 'blue']
        assert sum(r['food_received'] for r in blue) == 24
        assert any(r['food_received'] == 0 for r in blue)
        result.update(passed=True, phase_delivery_s=300, phase_resource_equality=True,
                      shared_food_received=24, independent_unit_budgets_would_receive=48,
                      allocation='Stable execution order; no fair-share or priority optimizer claimed')
    except Exception as exc:
        result['error'] = str(exc)
        raise
    finally:
        (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        harness_engine.close_harness()
        print('Evidence:', root, flush=True)


if __name__ == '__main__':
    main()
