"""Opt-in actual AFSIM: future/active/expired pool, no Python combat fallback."""
import argparse,copy,json,os,time
from pathlib import Path
from unittest.mock import patch

parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
if not args.live:parser.error('Actual AFSIM requires --live')
root=Path('.cache/qa/scenario-admission-2026-11-01/native')/str(time.time_ns());root.mkdir(parents=True)
for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
    os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
from gentactix import historical_operations as ho,sim_clock,missions,air_assets,air_availability
from backend import afsim_world,afsim_rules,afsim_state
from tools.qa.historical_air_fixture import inputs

checks=[]
def check(value,label):
    if not value:raise AssertionError(label)
    checks.append(label);print('PASS',label,flush=True)
def execute(label,world,orders):
    before=copy.deepcopy(world);scene=afsim_world.compile_scene(world,orders,1800,native_rules=True)
    with patch.object(missions,'advance',side_effect=AssertionError('No Python executor')):
        positions,evidence=afsim_world.run_scene({},scene)
        after=afsim_rules.apply_telemetry(evidence['native_effects'],scene['native_model'],scene,afsim_world.apply_observations(world,positions,scene))
    after['current_time'],after['simulation_clock']=sim_clock.target(world,'30分钟');missions.validate(after)
    check(world==before,label+' original world unchanged')
    (root/(label+'-after.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
    (root/(label+'-evidence.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    return after
try:
    snapshot,params=inputs();params['aviation']['ww2.cacw.group5']['availability']={
        'version':'air-availability-1','start':'1945-04-25T06:01:00','end':'1945-04-25T07:00:00',
        'assumption':'QA availability boundaries only, not a sourced1945flight or airfield.'}
    world=ho.initial(snapshot,params);order={'unit':world['red_units'][0]['name'],'action':'air_support',
        'target':world['blue_units'][0]['name'],'air_pool':'ww2.cacw.group5'}
    try:afsim_world.compile_scene(world,[order],1800,native_rules=True)
    except ValueError:check(True,'pending pool rejected before execution')
    else:raise AssertionError('Future aircraft launched')
    held=execute('hold-to-active',world,[])
    check(air_assets.world_state(held)['pools']['ww2.cacw.group5']==air_assets.world_state(world)['pools']['ww2.cacw.group5'],'pending interval does not consume/refill aircraft or fuel')
    check(air_availability.view(held)['ww2.cacw.group5']['status']=='active','program clock activates pool')
    observed=afsim_state.initial_observation({'id':'a'*12,'war_state':held,'turn_count':1,'time_step':'30分钟','execution_backend':'afsim'})
    check(observed['air_operations']['pools']['ww2.cacw.group5']['availability']['status']=='active','Native observation discloses availability')
    after=execute('active-flight',held,[order]);pool=after['air_operations']['pools']['ww2.cacw.group5']
    check(pool['sorties']==2 and pool['fuel']==12 and pool['ordnance']==6,'actual flight independently settles sorties fuel and ordnance')
    task=after['air_operations']['missions'][0]
    check(task['events'][0]['phase']=='launch' and task['events'][-1]['phase']=='returned' and task['events'][-1]['seconds']<=1800,'actual returned flight fits declared interval')
    check(air_availability.view(after)['ww2.cacw.group5']['status']=='expired' and not air_assets.available(after,'red'),'end boundary expires availability without deleting resource account')
    try:afsim_world.compile_scene(after,[order],1800,native_rules=True)
    except ValueError:check(True,'expired pool cannot launch')
    else:raise AssertionError('Expired aircraft launched')
    check(after['historical_initial']==snapshot,'source identity/presence/facts remain frozen')
    restored=ho.from_binding(after['mission']['definition']['historical_calculation'])
    check(restored==after['mission']['definition'],'frozen schedule definition restores exactly')
    result={'passed':True,'checks':checks,'actual_afsim_turns':2,'actual_model':False,'elapsed_simulated_seconds':3600,
        'historical_process_accepted':False,'scope':'Two source-bound local actors and1estimated aviation pool; temporal eligibility and actual native flight, not fullJizhongcampaign'}
    (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('RESULT',root/'result.json',flush=True)
finally:(root/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n')
