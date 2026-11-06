"""Explicit numerical QA: outside units continue hunger/noncombat accounting."""
import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
if not args.live:parser.error('Actual local Native execution requires --live')
root=Path('.cache/qa/operation-boundary-2026-11-02/outside-shortage');root.mkdir(parents=True,exist_ok=True)
for key,suffix in [('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('ROLE_INDEX','roles.json')]:os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
from tools.qa.operation_boundary_fixture import inputs
from verify_support_dynamics import config
from verify_unit_participation import order
from gentactix import historical_operations as ho,missions,unit_participation as up,sim_clock
from backend import afsim_world,afsim_rules,harness_engine
try:
    source,p=inputs();p['clock']['time_step']='6小时';p['support_dynamics']={**config(),
        'food_work_per_hour':.2,'incapacity_after_hours':1,'incapacity_fraction_per_hour':.001,
        'assumption':'仅阈值敏感性QA，不能当作历史饥饿生理损耗率。'}
    for actor in p['actors'].values():actor['personnel']=10000;actor['logistics']['food']=.1
    for node in p['support'].values():node['stock']=0
    world=ho.initial(source,p);name=next(u['name'] for u in world['red_units'] if u['historical_unit_id']=='ww2.cn.division159')
    selected=lambda w:next(u for u in w['red_units'] if u['name']==name)
    checks=[]
    for turn in (1,2):
        orders=[dict(unit=u['name'],action='hold') for _,u in missions.units(world)]
        if turn==1:orders=[o for o in orders if o['unit']!=name]+[order(name,p['operation_boundary']['routes'][0]['outside'])]
        scene=afsim_world.compile_scene(world,orders,21600,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python physical fallback')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence['native_effects'],scene['native_model'],scene,afsim_world.apply_observations(world,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(world,'6小时');up.advance(world,after,orders,21600,source='afsim_native');missions.evaluate(after);missions.validate(after)
        (root/f'turn-{turn}-world.json').write_text(json.dumps(after,ensure_ascii=False));(root/f'turn-{turn}-native.json').write_text(json.dumps(evidence,ensure_ascii=False))
        unit=selected(after);assert up.unit_view(after,unit)['status']=='offmap'
        assert unit['personnel']['casualties']==0 and unit['personnel']['noncombat_losses']>selected(world)['personnel']['noncombat_losses']
        assert unit['logistics']['food']==0 and unit['sustainment']['shortage_hours']>selected(world)['sustainment']['shortage_hours']
        assert unit['personnel']['committed']==unit['personnel']['current']+unit['personnel']['casualties']+unit['personnel']['noncombat_losses']
        checks.append(dict(turn=turn,noncombat_losses=unit['personnel']['noncombat_losses'],shortage_hours=unit['sustainment']['shortage_hours'],fatigue=unit['formation']['fatigue']))
        world=after
    result=dict(passed=True,actual_native_turns=2,checks=checks,scope='Threshold sensitivity only, outside hunger remains accounted separately from combat casualties; not historical physiology')
    (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False),flush=True)
finally:harness_engine.close_harness()
