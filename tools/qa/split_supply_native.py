"""Actual WSF cargo contrasts; no model or Python simulation executor."""
import argparse
import copy
import json
import os
import time
from pathlib import Path
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    root=Path('.cache/qa/split-supply-native')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from verify_split_supply import config
    from verify_support_dynamics import config as nutrition
    from tools.qa.historical_operational_fixture import inputs
    from gentactix import historical_operations as ho,missions,sim_clock,split_supply
    from backend import afsim_world,afsim_rules,afsim_split_supply,runtime_bridge,harness_engine as h
    from backend.main import _native_tool_dispatch
    runtime_bridge.register_dispatcher(_native_tool_dispatch)
    result={'passed':False,'cases':[],'live_model':False}
    def seed(food=0,ammo=100,delay=0,priority='food',limited=False,legacy=False,blocked=False,dry=False):
        s,p=inputs();p['goal']['deadline_turn']=8;p['support_dynamics']=nutrition()
        if not legacy:p['supply_distribution']={**config(),'priority':priority}
        p['rules'].update(command_base_s=delay,command_signal_s=0,command_distance_s_per_km=0,motorized=False)
        for a in p['actors'].values():
            a['logistics']={'food':food,'ammo':ammo};a['ground_control_radius_km']=100 if blocked else 0;a['formation']['motorized']=dry
            if dry:a['formation']['fuel_liters']=0
            if limited:a['equipment']['transport']=1
        if limited:p['rules']['transport_tons_per_truck']=.1
        if dry:
            for support in p['support'].values():support['inventory']['fuel_liters']=0
        return ho.initial(s,p)
    def run(name,before):
        original=copy.deepcopy(before);orders=[{'unit':u['name'],'action':'resupply'} for _,u in missions.units(before)]
        scene=afsim_world.compile_scene(before,orders,1800,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python executor')),patch.object(h,'get_ai_response',side_effect=AssertionError('No LLM')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟');after['afsim']=evidence;missions.validate(after)
        checks={'world_unchanged':before==original,'native_success':evidence['returncode']==0}
        if split_supply.configuration(before):
            try:afsim_split_supply.parse('',scene['native_model'],scene,{}, {})
            except ValueError:checks['missing_receipt_rejected']=True
            else:checks['missing_receipt_rejected']=False
        (root/(name+'.json')).write_text(json.dumps({'before':before,'after':after},ensure_ascii=False,indent=2))
        result['cases'].append({'name':name,'checks':checks,'ledger':after['mission']['ledger'],'native':evidence})
        print(json.dumps({'case':name,'checks':checks,'ledger':after['mission']['ledger'][0]},ensure_ascii=False),flush=True)
        return after
    try:
        food=run('food-with-full-ammo',seed());r=food['mission']['ledger'][0];assert r['food_received']==8 and r['ammo_received']==0 and r['delivery']==4
        ammo=run('ammo-with-full-food',seed(100,0));r=ammo['mission']['ledger'][0];assert r['food_received']==0 and r['ammo_received']==8
        both=run('both',seed(20,20));assert all(r['food_received']==r['ammo_received']==8 for r in both['mission']['ledger'])
        delayed=run('delayed',seed(delay=4000));assert all(r['food_received']==2 for r in delayed['mission']['ledger'])
        limited_food=run('limited-food-priority',seed(20,20,limited=True));limited_ammo=run('limited-ammo-priority',seed(20,20,priority='ammo',limited=True))
        assert limited_food['mission']['ledger'][0]['food_received']>0 and limited_food['mission']['ledger'][0]['ammo_received']==0
        assert limited_ammo['mission']['ledger'][0]['ammo_received']>0 and limited_ammo['mission']['ledger'][0]['food_received']==0
        empty=seed();node=empty['supply_nodes'][0];node['commodities']['food']=0;node['stock']=split_supply.equivalent(config(),**node['commodities'])
        exhausted=run('food-exhausted',empty);assert exhausted['mission']['ledger'][0]['food_received']==0
        cut=run('enemy-blocks-route',seed(blocked=True))
        assert cut['mission']['ledger'][0]['food_received']==cut['mission']['ledger'][0]['ammo_received']==0
        nofuel=run('convoy-no-fuel',seed(dry=True))
        assert all(row['food_received']==row['ammo_received']==0 for row in nofuel['mission']['ledger'])
        restored=json.loads(json.dumps(food))
        assert missions.validate(restored) and restored==food
        second=run('food-second-turn',food);assert second['red_units'][0]['sustainment']['shortage_hours']==0
        old=run('legacy',seed(legacy=True));assert old['mission']['ledger'][0]['delivery']==0
        result['passed']=all(all(case['checks'].values()) for case in result['cases'])
    finally:
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));h.close_harness();print(root/'result.json')
    assert result['passed']


if __name__=='__main__':main()
