"""Execute the new sourced phases through the native plugin, with explicit QA inputs.

This validates native contracts and decision differences, not historical efficacy.
"""
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    root = Path('.cache/qa/remaining-initial-native')/str(time.time_ns())
    root.mkdir(parents=True)
    for key, suffix in [('DSH_HOME','dsh-home'), ('DSH_WORKSPACE','workspace'),
                        ('ROLE_INDEX','roles.json'), ('TRACE_DIR','traces')]:
        os.environ['GENTACTIX_'+key] = str((root/suffix).resolve())
    from backend import afsim_world, afsim_rules, runtime_bridge, harness_engine as h
    from backend.main import _native_tool_dispatch
    from gentactix import historical_operations as ho, missions, sim_clock
    from tools.qa.remaining_initial_fixture import cases, inputs
    runtime_bridge.register_dispatcher(_native_tool_dispatch)
    results = {'passed':False, 'live_model':False, 'cases':[],
               'scope':'原生导入、两轮位置与账本连续性、同初态待命/机动差异；非全程历史效能验收。'}

    def advance(before, moving):
        target = before['mission']['definition']['historical_calculation']['parameters']['goal']['exit']
        orders = [{'unit':u['name'], 'action':'move', **target}
                  if moving and team == 'red' else {'unit':u['name'], 'action':'hold'}
                  for team,u in missions.units(before)]
        original = copy.deepcopy(before)
        scene = afsim_world.compile_scene(before, orders, 1800, native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('Python executor forbidden')), \
             patch.object(h,'get_ai_response',side_effect=AssertionError('No model substitute')):
            positions, evidence = afsim_world.run_scene({},scene)
            after = afsim_rules.apply_telemetry(evidence.pop('native_effects'), scene['native_model'],
                scene, afsim_world.apply_observations(before, positions, scene))
        after['current_time'], after['simulation_clock'] = sim_clock.target(before,'30分钟')
        after['afsim'] = evidence
        assert before == original and evidence['returncode'] == 0
        assert missions.validate(after)
        assert {u['name'] for _,u in missions.units(before)} == {u['name'] for _,u in missions.units(after)}
        for _,u in missions.units(after):
            assert u['formation']['last_execution']['turn'] == after['mission']['turn']
            assert u['logistics']['food'] >= 0 and u['logistics']['ammo'] >= 0
        return after

    try:
        for battle, phase in cases():
            before = ho.initial(*inputs(battle,phase))
            hold = advance(before, False)
            move = advance(before, True)
            # A successful move can finish a local objective in one turn.
            # Continue the waiting branch; never bypass the terminal-state guard.
            second = advance(hold, True)
            different = any(missions.distance(a,b) > .001 for a,b in zip(hold['red_units'],move['red_units']))
            assert different, (battle,phase,'orders had no positional effect')
            assert second['simulation_clock']['elapsed_seconds'] == 3600
            case = {'battle':battle,'phase':phase,'passed':True,
                    'actors':len(list(missions.units(before))), 'decision_difference':different,
                    'native_runs':3, 'elapsed_seconds':3600}
            (root/(phase+'.json')).write_text(json.dumps({'case':case,'before':before,'hold':hold,'move':move,'second':second},ensure_ascii=False,indent=2))
            results['cases'].append(case)
            print(json.dumps(case,ensure_ascii=False),flush=True)
        results['passed'] = True
    finally:
        (root/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        h.close_harness()
        print(root/'result.json',flush=True)


if __name__ == '__main__':
    main()
