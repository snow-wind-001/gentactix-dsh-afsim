"""Native-only supply-route regression: staging, live defence, death and capture.

Three-entity artificial geometry based on the existing QA fixture, not history.
No model calls or Python combat executor. Every case retains its native output.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native',action='store_true');p.add_argument('--config',type=Path,required=True)
    args=p.parse_args()
    if not args.native:p.error('--native required')
    root=Path('.cache/qa/supply-interdiction-2026-10-29')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from backend import afsim_world,afsim_rules,runtime_bridge,harness_engine as h
    from backend.main import _native_tool_dispatch
    from gentactix import missions,historical_operations,sim_clock
    from tools.qa.campaign_fixture import inputs
    runtime_bridge.register_dispatcher(_native_tool_dispatch)
    results=[]
    cases=('staged','active','killed','captured','fractional_red','fractional_blue')
    try:
        for kind in cases:
            snapshot,params=inputs();center=params['area']['center'];lat,lng=center['lat'],center['lng']
            red=params['actors']['ww2.cn.division31'];red['position']={'lat':lat,'lng':lng+.002}
            params['support']['red']['position']={'lat':lat,'lng':lng-.01}
            other=params['actors']['ww2.jp.seya_detachment'];other['position']={'lat':lat+.04,'lng':lng+.04}
            target=params['actors']['ww2.jp.sakamoto_detachment'];target['position']=copy.deepcopy(center)
            target['ground_control_radius_km']=.3
            if kind!='staged':params['campaign']['arrivals']['ww2.jp.sakamoto_detachment']['not_before']=params['clock']['start']
            if kind=='killed':
                target['personnel']=1
                target['equipment']={k:0 for k in target['equipment']}
                target['formation'].update(protection=0,entrenchment=0)
            if kind=='captured':target['logistics']['ammo']=0
            if kind.startswith('fractional_'):
                # A single small native volley consumes the existing 0.8 casualty
                # carry. Check both roster orders: victim settled before/after
                # the opposing recipient. No loss is injected into telemetry.
                victim_params,shooter_params=(red,target) if kind=='fractional_red' else (target,red)
                victim_params['personnel']=1
                victim_params['formation'].update(protection=0,entrenchment=0)
                victim_params['position']=copy.deepcopy(center)
                victim_params['ground_control_radius_km']=.3
                shooter_params['personnel']=30
                shooter_params['logistics']['ammo']=1
                shooter_params['position']={'lat':lat,'lng':lng+.002}
                for unit in (victim_params,shooter_params):
                    unit['equipment']={k:0 for k in unit['equipment']}
                side='blue' if kind=='fractional_red' else 'red'
                params['support'][side]['position']={'lat':lat,'lng':lng-.01}
            before=historical_operations.initial(snapshot,params);original=copy.deepcopy(before)
            actor=before['red_units'][0];victim=next(u for u in before['blue_units'] if u['historical_unit_id']=='ww2.jp.sakamoto_detachment')
            if kind=='fractional_red':actor,victim=victim,actor
            if kind.startswith('fractional_'):
                victim['formation']['combat_damage_remainder']=.8
                original=copy.deepcopy(before)
            orders=[{'unit':u['name'],'action':'hold'} for _,u in missions.units(before)]
            if kind in ('killed','captured') or kind.startswith('fractional_'):
                index=next(i for i,o in enumerate(orders) if o['unit']==actor['name'])
                orders[index]={'unit':actor['name'],'action':'capture' if kind=='captured' else 'fire','target':victim['name']}
            scene=afsim_world.compile_scene(before,orders,1800,native_rules=True)
            with patch.object(missions,'advance',side_effect=AssertionError('No Python battle fallback')):
                positions,evidence=afsim_world.run_scene({},scene)
                after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                    afsim_world.apply_observations(before,positions,scene))
            after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟');after['afsim']=evidence
            missions.validate(after);assert before==original
            receipt=next(r for r in after['mission']['ledger'] if r['unit']==actor['name'])
            enemy=next(u for _,u in missions.units(after) if u['name']==victim['name'])
            connected=receipt['supply_status']=='未切断'
            expected=kind!='active'
            row={'case':kind,'passed':connected==expected,'connected':connected,'expected_connected':expected,
                'supply_receipt':receipt,'target_current':enemy['personnel']['current'],
                'target_captured':enemy['personnel'].get('captured',0),'target_active':after['campaign']['actors'][enemy['name']]['active'],
                'native':{k:evidence[k] for k in ('returncode','artifact','wall_ms')}}
            if kind=='killed':assert enemy['personnel']['current']==0,'fixture did not remove target'
            if kind=='captured':assert enemy['personnel']['captured']>0 and enemy['personnel']['current']==0
            if kind.startswith('fractional_'):
                shooter=next(u for _,u in missions.units(after) if u['name']==actor['name'])
                assert enemy['personnel']['current']==0,'fractional volley did not remove target'
                assert shooter['formation']['last_execution']['fire_cycles']==1,'expected one native volley'
            (root/f'{kind}.json').write_text(json.dumps({'before':before,'after':after,'result':row},ensure_ascii=False,indent=2))
            results.append(row);print(kind,'PASS' if row['passed'] else 'FAIL',connected,flush=True)
    finally:
        h.close_harness();(root/'result.json').write_text(json.dumps({'passed':len(results)==len(cases) and all(r['passed'] for r in results),'model_calls':0,'results':results},ensure_ascii=False,indent=2))
        print(root,flush=True)
    if not all(r['passed'] for r in results):raise SystemExit(1)


if __name__=='__main__':main()
