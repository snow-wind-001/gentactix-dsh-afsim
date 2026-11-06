"""34 source identities +1air pool, explicit numerical QA, no historical fit claim."""
import argparse,copy,json,os,time
from pathlib import Path
from unittest.mock import patch
parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');a=parser.parse_args()
if not a.live:parser.error('ActualAFSIMrequires--live')
r=Path('.cache/qa/scenario-admission-2026-11-01/jizhong-native')/str(time.time_ns());r.mkdir(parents=True)
for k,s in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:os.environ['GENTACTIX_'+k]=str(r.resolve()/s)
from gentactix import historical_initial as hi,historical_operations as ho,air_assets,air_availability,missions,sim_clock
from backend import afsim_world,afsim_rules
from tools.qa.historical_operational_fixture import inputs as base_inputs
from tools.qa.jizhong_assembly_fixture import inputs,NOTE
snapshot,p=inputs()
world=ho.initial(snapshot,p);before_source=copy.deepcopy(snapshot);ids={u['historical_unit_id'] for _,u in missions.units(world)};checks=[]
def check(ok,label):
 if not ok:raise AssertionError(label)
 checks.append(label);print('PASS',label,flush=True)
def execute(label,w,orders):
 scene=afsim_world.compile_scene(w,orders,1800,native_rules=True);check(len(scene['entities'])==34,label+' compiles34groundentities')
 with patch.object(missions,'advance',side_effect=AssertionError('NoPythoncombat')):
  positions,e=afsim_world.run_scene({},scene);after=afsim_rules.apply_telemetry(e['native_effects'],scene['native_model'],scene,afsim_world.apply_observations(w,positions,scene))
 after['current_time'],after['simulation_clock']=sim_clock.target(w,'30分钟');missions.validate(after)
 check({u['historical_unit_id'] for _,u in missions.units(after)}==ids,label+' all34identitiespersist')
 check(after['historical_initial']==before_source,label+' frozenhistoryunchanged')
 (r/(label+'-world.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n');(r/(label+'-native.json')).write_text(json.dumps(e,ensure_ascii=False,indent=2)+'\n');return after
try:
 check(len(ids)==34,'all34mutuallyexclusivegroundidentities')
 check(not air_assets.available(world,'blue'),'blueairpendingatT0')
 held=execute('hold',world,[]);check(air_assets.available(held,'blue')[0]['id']=='ww2.jp.flight29','blueairactivatesat30minutes')
 order={'unit':held['blue_units'][0]['name'],'action':'air_support','target':held['red_units'][0]['name'],'air_pool':'ww2.jp.flight29'}
 after=execute('blue-flight',held,[order]);pool=after['air_operations']['pools']['ww2.jp.flight29']
 check(pool['sorties']==2 and pool['ordnance']==6 and pool['fuel']==12,'bluesourcedpoolflightsettlesindependentresources')
 check(after['air_operations']['missions'][0]['events'][-1]['phase']=='returned','blueflightreturnsfromactualNativeevents')
 check(sum(u['personnel']['casualties'] for _,u in missions.units(after))>0,'actualairstrikehastargetpersonneleffect')
 check(ho.from_binding(after['mission']['definition']['historical_calculation'])==after['mission']['definition'],'whole34unitdefinitioncoldrestoreexact')
 result={'passed':True,'checks':checks,'actual_afsim_turns':2,'actual_model':False,'ground_entities':34,'aviation_pools':1,'simulated_hours':1,'historical_process_accepted':False,'scope':NOTE};(r/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('RESULT',r/'result.json',flush=True)
finally:(r/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n')
