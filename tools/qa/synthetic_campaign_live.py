"""Actual AFSIM: added exercise actors wait, move and fight under campaign rules."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live for the real native runtime')
    root=Path('.cache/qa/synthetic-campaign-2026-10-31/native')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from tools.qa.campaign_fixture import inputs
    from gentactix import historical_operations as ho, synthetic_history as sh, missions, sim_clock, campaign
    from backend import afsim_world, afsim_rules, harness_engine
    snapshot,params=inputs();params['goal'].update(termination_mode='objectives',required_turns=4,deadline_turn=6)
    base=ho.definition(snapshot,params);binding=copy.deepcopy(base['historical_calculation'])
    config=sh.seed(binding)['configuration'];center=base['map_center']
    for side,offset in [('red',-.001),('blue',.001)]:
        row=copy.deepcopy(config['teams'][side][-1]);row['name']=side+'新增演习单位'
        row['position']={'lat':center['lat'],'lng':center['lng']+offset};config['teams'][side].append(row)
    world=missions.from_definition(sh.definition(binding,config));initial=copy.deepcopy(world)
    result={'passed':False,'actual_afsim':True,'scope':'Five actors, QA numerical estimates; not historical calibration','checks':[]}
    def check(value,label):
        if not value:raise AssertionError(label)
        result['checks'].append(label);print('PASS',label,flush=True)
    def advance(number,orders):
        nonlocal world
        scene=afsim_world.compile_scene(world,orders,1800,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('Real native effects required')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(world,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(world,'30分钟')
        missions.validate(after);world=after
        (root/f'turn{number}.json').write_text(json.dumps({'world':world,'evidence':evidence},ensure_ascii=False))
    try:
        (root/'initial.json').write_text(json.dumps(initial,ensure_ascii=False))
        check(len(world['campaign']['actors'])==5,'All five process rows initialized')
        blue=next(u for u in world['blue_units'] if u['name']=='blue新增演习单位')
        check(campaign.release_seconds(world,blue)==3600,'Added blue actor retains its source arrival delay')
        advance(1,[{'unit':u['name'],'action':'move','lat':center['lat']+.0005,'lng':center['lng']-.001}
                   if u['name']=='red新增演习单位' else {'unit':u['name'],'action':'hold'} for _,u in missions.units(world)])
        red=next(u for u in world['red_units'] if u['name']=='red新增演习单位')
        old=next(u for u in initial['red_units'] if u['name']==red['name'])
        check(missions.distance(old,red)>.01,'Added red actor actually moves in AFSIM')
        check(not world['campaign']['actors']['blue新增演习单位']['active'],'Added blue actor still waits after 30 minutes')
        check(all(u['personnel']['casualties']==0 for _,u in missions.units(world)),'No fabricated battle losses before fire')
        advance(2,[{'unit':u['name'],'action':'hold'} for _,u in missions.units(world)])
        check(world['campaign']['actors']['blue新增演习单位']['active'],'Native scheduler activates added blue actor at one hour')
        advance(3,[{'unit':u['name'],'action':'fire','target':'blue新增演习单位' if team=='red' else 'red新增演习单位'}
                   if u['name'] in ('red新增演习单位','blue新增演习单位') else {'unit':u['name'],'action':'hold'}
                   for team,u in missions.units(world)])
        added=[u for _,u in missions.units(world) if '新增演习' in u['name']]
        check(all(u['personnel']['casualties']>0 for u in added),'Both added actors receive actual native battle losses')
        check(world['historical_initial']==snapshot and binding==base['historical_calculation'],'Historical facts and original binding unchanged')
        check(all(u['personnel']['committed']==sum(u['personnel'][k] for k in ('current','casualties','noncombat_losses'))
                  for _,u in missions.units(world)),'All personnel ledgers conserve')
        check(all(e['committed']==sum(e[k] for k in ('operational','damaged','destroyed'))
                  for _,u in missions.units(world) for e in u['equipment']),'All equipment ledgers conserve')
        result.update(passed=True,turns=3,casualties={u['name']:u['personnel']['casualties'] for u in added})
    finally:
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        harness_engine.close_harness();print('Evidence:',root,flush=True)


if __name__=='__main__':main()
