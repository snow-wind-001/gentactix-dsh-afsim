"""Actual local Native contrast: an outside formation remains a physical target."""
import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch

parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
if not args.live:parser.error('Actual local execution requires --live')
root=Path('.cache/qa/operation-boundary-2026-11-02/outside-attack');root.mkdir(parents=True,exist_ok=True)
for key,suffix in [('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('ROLE_INDEX','roles.json')]:
    os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
from tools.qa.operation_boundary_fixture import inputs
from verify_unit_participation import order
from gentactix import historical_operations as ho,missions,unit_participation as up,sim_clock
from backend import afsim_world,afsim_rules,harness_engine


def advance(world,orders,label):
    scene=afsim_world.compile_scene(world,orders,21600,native_rules=True)
    with patch.object(missions,'advance',side_effect=AssertionError('No Python physical fallback')):
        positions,evidence=afsim_world.run_scene({},scene)
        after=afsim_rules.apply_telemetry(evidence['native_effects'],scene['native_model'],scene,
            afsim_world.apply_observations(world,positions,scene))
    after['current_time'],after['simulation_clock']=sim_clock.target(world,'6小时')
    up.advance(world,after,orders,21600,source='afsim_native');missions.evaluate(after);missions.validate(after)
    (root/(label+'-world.json')).write_text(json.dumps(after,ensure_ascii=False))
    (root/(label+'-native.json')).write_text(json.dumps(evidence,ensure_ascii=False))
    return after


try:
    source,p=inputs();p['clock']['time_step']='6小时'
    for actor in p['actors'].values():actor['personnel']=10000
    world=ho.initial(source,p);red=next(u for u in world['red_units'] if u['historical_unit_id']=='ww2.cn.division159')
    blue=world['blue_units'][0];route=p['operation_boundary']['routes'][0]
    holds=lambda w:[dict(unit=u['name'],action='hold') for _,u in missions.units(w)]
    orders=holds(world);orders=[o for o in orders if o['unit']!=red['name']]+[order(red['name'],route['outside'])]
    outside=advance(world,orders,'exit')
    member=lambda w:next(u for u in w['red_units'] if u['name']==red['name'])
    assert up.unit_view(outside,member(outside))['status']=='offmap'
    center=p['area']['center'];point=dict(lat=center['lat']+.008,lng=route['outside']['lng'])
    orders=[o for o in holds(outside) if o['unit']!=blue['name']]+[dict(unit=blue['name'],action='move',**point)]
    approached=advance(outside,orders,'approach')
    orders=[o for o in holds(approached) if o['unit']!=blue['name']]+[dict(unit=blue['name'],action='fire',target=red['name'])]
    hit=advance(approached,orders,'outside-hit')
    delta=member(hit)['personnel']['casualties']-member(approached)['personnel']['casualties']
    assert delta>0 and up.unit_view(hit,member(hit))['status']=='offmap'
    assert len(list(missions.units(hit)))==6 and hit['historical_initial']==source
    result=dict(passed=True,actual_native_turns=3,outside_target_casualty_delta=delta,
        entity_count=6,status='offmap',actual_model=False,scope='Explicit QA geometry/strengths; actual remote targetability, not historical loss calibration')
    (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False),flush=True)
finally:harness_engine.close_harness()
